"""Tests for SARIF output formatting and CLI integration."""

from __future__ import annotations

from functools import lru_cache
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from jsonschema import Draft4Validator, FormatChecker
import pytest

from blinter import main
from blinter.models import LintIssue, ProcessingResults
from blinter.output.sarif_formatter import (
    SarifLog,
    build_sarif_report,
    print_sarif_report,
    write_sarif_report,
)
from blinter.rules.registry import RULES

_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "sarif-schema-2.1.0.json"


@lru_cache(maxsize=1)
def _sarif_validator() -> Draft4Validator:
    """Load the vendored SARIF 2.1.0 schema once per test session."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft4Validator(schema, format_checker=FormatChecker())


def _validate_sarif(document: SarifLog) -> None:
    """Raise if the document does not match the SARIF 2.1.0 schema."""
    _sarif_validator().validate(document)


def _issue(
    line_number: int,
    rule_code: str,
    *,
    context: str = "",
    file_path: str | None = None,
) -> LintIssue:
    """Build a lint issue from a catalog rule."""
    return LintIssue(
        line_number=line_number,
        rule=RULES[rule_code],
        context=context,
        file_path=file_path,
    )


def _results(
    issues: list[LintIssue],
    *,
    skipped_files: list[tuple[str, str]] | None = None,
) -> ProcessingResults:
    """Wrap issues in processing results for the SARIF builder."""
    file_results: dict[str, list[LintIssue]] = {}
    for issue in issues:
        key = issue.file_path or "unknown"
        file_results.setdefault(key, []).append(issue)
    return ProcessingResults(
        all_issues=issues,
        file_results=file_results,
        total_files_processed=len(file_results),
        files_with_errors=0,
        processed_file_paths=[("script.bat", None)],
        skipped_files=skipped_files or [],
    )


class TestBuildSarifReport:
    """Unit tests for SARIF document construction."""

    def test_severity_mapping_and_rule_metadata(self, tmp_path: Path) -> None:
        """Each Blinter severity maps to a SARIF level, and rules keep their text."""
        script = tmp_path / "main.bat"
        issues = [
            _issue(2, "E002", context="GOTO missing label", file_path=str(script)),
            _issue(4, "W001", file_path=str(script)),
            _issue(6, "S001", file_path=str(script)),
            _issue(8, "SEC001", file_path=str(script)),
            _issue(10, "P001", file_path=str(script)),
        ]
        report = build_sarif_report(_results(issues), "1.2.3", cwd=tmp_path)
        _validate_sarif(report)

        assert report["version"] == "2.1.0"
        assert report["$schema"].endswith("sarif-schema-2.1.0.json")
        driver = report["runs"][0]["tool"]["driver"]
        assert driver["name"] == "Blinter"
        assert driver["version"] == "1.2.3"
        assert driver["informationUri"] == "https://github.com/BatchLang/Blinter"

        rule_ids = [rule["id"] for rule in driver["rules"]]
        assert rule_ids == ["E002", "P001", "S001", "SEC001", "W001"]
        security_rule = next(rule for rule in driver["rules"] if rule["id"] == "SEC001")
        assert security_rule["properties"]["tags"] == ["security"]
        assert security_rule["shortDescription"]["text"] == RULES["SEC001"].name
        assert security_rule["fullDescription"]["text"] == RULES["SEC001"].explanation
        assert security_rule["help"]["text"] == RULES["SEC001"].recommendation
        assert "properties" not in next(
            rule for rule in driver["rules"] if rule["id"] == "E002"
        )

        by_rule = {result["ruleId"]: result for result in report["runs"][0]["results"]}
        assert by_rule["E002"]["level"] == "error"
        assert by_rule["E002"]["properties"]["blinterSeverity"] == "Error"
        assert by_rule["E002"]["message"]["text"] == "GOTO missing label"
        assert by_rule["E002"]["ruleIndex"] == rule_ids.index("E002")
        assert by_rule["SEC001"]["level"] == "error"
        assert by_rule["SEC001"]["properties"]["blinterSeverity"] == "Security"
        assert by_rule["SEC001"]["message"]["text"] == RULES["SEC001"].explanation
        assert by_rule["W001"]["level"] == "warning"
        assert by_rule["W001"]["properties"]["blinterSeverity"] == "Warning"
        assert by_rule["S001"]["level"] == "note"
        assert by_rule["S001"]["properties"]["blinterSeverity"] == "Style"
        assert by_rule["P001"]["level"] == "note"
        assert by_rule["P001"]["properties"]["blinterSeverity"] == "Performance"
        region = by_rule["E002"]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 2
        assert region["startColumn"] == 1
        assert (
            by_rule["E002"]["locations"][0]["physicalLocation"]["artifactLocation"][
                "uri"
            ]
            == "main.bat"
        )

    def test_empty_results_are_valid_sarif(self, tmp_path: Path) -> None:
        """A clean run is a SARIF log with no results and no notifications."""
        report = build_sarif_report(_results([]), "1.0.0", cwd=tmp_path)
        _validate_sarif(report)
        run = report["runs"][0]
        assert run["results"] == []
        assert run["tool"]["driver"]["rules"] == []
        assert "notifications" not in run["tool"]["driver"]
        invocation = run["invocations"][0]
        assert invocation["executionSuccessful"] is True
        assert "toolExecutionNotifications" not in invocation

    def test_skipped_files_become_notifications(self, tmp_path: Path) -> None:
        """Skipped files stay in the log when human stdout is suppressed."""
        skipped = str(tmp_path / "bad.bat")
        report = build_sarif_report(
            _results([], skipped_files=[(skipped, "Access denied")]),
            "1.0.0",
            cwd=tmp_path,
        )
        _validate_sarif(report)
        driver = report["runs"][0]["tool"]["driver"]
        assert driver["notifications"][0]["id"] == "BLINT001"
        notifications = report["runs"][0]["invocations"][0][
            "toolExecutionNotifications"
        ]
        assert len(notifications) == 1
        assert notifications[0]["level"] == "error"
        assert notifications[0]["descriptor"]["id"] == "BLINT001"
        assert skipped in notifications[0]["message"]["text"]
        assert "Access denied" in notifications[0]["message"]["text"]
        assert report["runs"][0]["invocations"][0]["executionSuccessful"] is True

    def test_uris_are_cwd_relative_or_file_uris(self, tmp_path: Path) -> None:
        """Paths inside cwd are relative; paths outside cwd are file URIs."""
        cwd = tmp_path / "repo"
        cwd.mkdir()
        inside = cwd / "scripts" / "my script.bat"
        outside = tmp_path / "outside" / "main.bat"
        report = build_sarif_report(
            _results(
                [
                    _issue(1, "E002", file_path=str(inside)),
                    _issue(3, "S001", file_path="nested/other.bat"),
                    _issue(5, "W001", file_path=str(outside)),
                    _issue(7, "P001", file_path=None),
                ]
            ),
            "1.0.0",
            cwd=cwd,
        )
        _validate_sarif(report)
        uris = [
            result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for result in report["runs"][0]["results"]
        ]
        assert uris[0] == "scripts/my%20script.bat"
        assert uris[1] == "nested/other.bat"
        assert uris[2].startswith("file:")
        assert "outside/main.bat" in uris[2]
        assert "\\" not in uris[2]
        assert uris[3] == "unknown"

    def test_unresolvable_path_uses_unknown_uri(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A path that cannot be resolved still produces a schema-valid URI."""

        def _fail_resolve(*_args: object, **_kwargs: object) -> Path:
            raise OSError("cannot resolve")

        monkeypatch.setattr(Path, "resolve", _fail_resolve)
        report = build_sarif_report(
            _results([_issue(1, "E002", file_path=str(tmp_path / "main.bat"))]),
            "1.0.0",
            cwd=tmp_path,
        )
        uri = report["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "unknown"
        _validate_sarif(report)

    def test_write_and_print_report_round_trip(self, tmp_path: Path) -> None:
        """write_sarif_report and print_sarif_report should emit the same JSON."""
        report = build_sarif_report(_results([]), "1.0.0", cwd=tmp_path)
        report_path = tmp_path / "report.sarif"
        write_sarif_report(str(report_path), report)
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        assert loaded == report

        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            print_sarif_report(report)
            parsed = json.loads(captured.getvalue())
        finally:
            sys.stdout = old_stdout
        assert parsed == report


class TestSarifOutputCli:
    """Integration tests for --format sarif."""

    def test_format_sarif_stdout_only(self) -> None:
        """--format sarif should emit SARIF on stdout without human output."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write("@echo off\necho Hello\n")
            batch_path = temp_file.name
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            with patch("sys.argv", ["blinter.py", batch_path, "--format", "SARIF"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code in [0, 1]
            output = captured.getvalue()
        finally:
            sys.stdout = old_stdout
            os.unlink(batch_path)

        assert "DETAILED ISSUES:" not in output
        assert "Blinter v" not in output
        report = json.loads(output)
        _validate_sarif(report)
        assert report["version"] == "2.1.0"
        assert report["runs"][0]["tool"]["driver"]["name"] == "Blinter"

    def test_format_sarif_with_output_file(self) -> None:
        """--format sarif --output should write the file and leave stdout empty."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write("@echo off\necho Hello\n")
            batch_path = temp_file.name
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = str(Path(temp_dir) / "results.sarif")
            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                with patch(
                    "sys.argv",
                    [
                        "blinter.py",
                        batch_path,
                        "--format",
                        "sarif",
                        "--output",
                        report_path,
                    ],
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code in [0, 1]
                output = captured.getvalue()
            finally:
                sys.stdout = old_stdout
                os.unlink(batch_path)

            assert output.strip() == ""
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            _validate_sarif(report)
            assert report["runs"][0]["results"] is not None

    def test_format_sarif_skipped_files_stay_in_the_log(self) -> None:
        """Skipped-file notes belong in SARIF notifications, not ahead of the log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            good_bat = os.path.join(tmpdir, "good.bat")
            bad_bat = os.path.join(tmpdir, "bad.bat")
            Path(good_bat).write_text("@echo off\nexit /b 0\n", encoding="utf-8")
            Path(bad_bat).write_text("@echo off\n", encoding="utf-8")

            def lint_side_effect(
                file_path: str, *_args: object, **_kwargs: object
            ) -> list[object]:
                if file_path.endswith("bad.bat"):
                    raise PermissionError("Access denied")
                return []

            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                with patch(
                    "blinter.cli.main.lint_batch_file", side_effect=lint_side_effect
                ):
                    with patch("sys.argv", ["blinter.py", tmpdir, "--format", "sarif"]):
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1
                output = captured.getvalue()
            finally:
                sys.stdout = old_stdout

        assert not output.startswith("Skipped files")
        report = json.loads(output)
        _validate_sarif(report)
        notifications = report["runs"][0]["invocations"][0][
            "toolExecutionNotifications"
        ]
        assert any("bad.bat" in item["message"]["text"] for item in notifications)

    def test_write_sarif_report_failure(self) -> None:
        """Write failures should print to stderr and exit with code 1."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write("@echo off\necho Hello\n")
            batch_path = temp_file.name
        old_stderr = sys.stderr
        sys.stderr = captured_err = io.StringIO()

        def failing_write(_path: str, _report: SarifLog) -> None:
            raise PermissionError("access denied")

        try:
            with patch(
                "blinter.cli.main.write_sarif_report",
                side_effect=failing_write,
            ):
                with patch(
                    "sys.argv",
                    [
                        "blinter.py",
                        batch_path,
                        "--format",
                        "sarif",
                        "--output",
                        "out.sarif",
                    ],
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1
            assert "Could not write SARIF report" in captured_err.getvalue()
        finally:
            sys.stderr = old_stderr
            os.unlink(batch_path)

    def test_unknown_format_lists_sarif(self) -> None:
        """Unknown --format values should exit with code 1."""
        old_stderr = sys.stderr
        sys.stderr = captured_err = io.StringIO()
        try:
            with patch("sys.argv", ["blinter.py", "script.bat", "--format", "xml"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
            error_output = captured_err.getvalue()
            assert "Unknown format" in error_output
            assert "json, sarif" in error_output
        finally:
            sys.stderr = old_stderr
