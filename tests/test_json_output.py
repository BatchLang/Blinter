"""Tests for JSON output formatting and CLI integration."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest

from blinter.cli.main import _count_fatal_issues_for_exit
from blinter import main
from blinter.models import LintIssue, ProcessingResults, RuleSeverity
from blinter.output.formatters import (
    compute_most_common_rule,
    compute_severity_counts,
)
from blinter.output.json_formatter import build_report, print_report, write_report
from blinter.rules.registry import RULES
from tests.conftest import get_project_version


class TestSummaryHelpers:
    """Tests for shared summary helper functions."""

    def _create_issue(self, line_number: int, rule_code: str) -> LintIssue:
        return LintIssue(line_number=line_number, rule=RULES[rule_code])

    def test_compute_severity_counts(self) -> None:
        """Severity counts should match issue severities."""
        issues = [
            self._create_issue(1, "S001"),
            self._create_issue(2, "W005"),
            self._create_issue(3, "W005"),
            self._create_issue(4, "E002"),
        ]
        counts = compute_severity_counts(issues)
        assert counts[RuleSeverity.STYLE] == 1
        assert counts[RuleSeverity.WARNING] == 2
        assert counts[RuleSeverity.ERROR] == 1

    def test_compute_most_common_rule(self) -> None:
        """Most common rule should be the highest-frequency code."""
        issues = [
            self._create_issue(1, "S003"),
            self._create_issue(2, "S003"),
            self._create_issue(3, "S003"),
            self._create_issue(4, "W005"),
            self._create_issue(5, "W005"),
            self._create_issue(6, "E002"),
        ]
        rule_code, count = compute_most_common_rule(issues)
        assert rule_code == "S003"
        assert count == 3

    def test_compute_most_common_rule_empty(self) -> None:
        """Empty issue list should return empty rule and zero count."""
        rule_code, count = compute_most_common_rule([])
        assert rule_code == ""
        assert count == 0


class TestBuildReport:
    """Unit tests for JSON report building."""

    def _create_issue(
        self,
        line_number: int,
        rule_code: str,
        *,
        context: str = "",
        file_path: str | None = None,
    ) -> LintIssue:
        return LintIssue(
            line_number=line_number,
            rule=RULES[rule_code],
            context=context,
            file_path=file_path,
        )

    def _make_results(
        self,
        issues: list[LintIssue],
        *,
        processed_file_paths: list[tuple[str, str | None]] | None = None,
        skipped_files: list[tuple[str, str]] | None = None,
    ) -> ProcessingResults:
        file_results: dict[str, list[LintIssue]] = {}
        for issue in issues:
            key = issue.file_path or "unknown"
            file_results.setdefault(key, []).append(issue)
        return ProcessingResults(
            all_issues=issues,
            file_results=file_results,
            total_files_processed=1,
            files_with_errors=0,
            processed_file_paths=processed_file_paths or [("C:\\test\\main.bat", None)],
            skipped_files=skipped_files or [],
        )

    def test_build_report_structure(self) -> None:
        """Report should include all top-level keys and issue fields."""
        issues = [
            self._create_issue(
                5,
                "E002",
                context="GOTO missing label",
                file_path="C:\\project\\main.bat",
            ),
            self._create_issue(
                10,
                "W005",
                file_path="C:\\project\\config.bat",
            ),
        ]
        results = self._make_results(
            issues,
            processed_file_paths=[
                ("C:\\project\\main.bat", None),
                ("C:\\project\\config.bat", "C:\\project\\main.bat"),
            ],
            skipped_files=[("C:\\project\\bad.bat", "Permission denied")],
        )
        fatal_count = _count_fatal_issues_for_exit(results)
        report = build_report(
            results,
            "C:\\project\\main.bat",
            get_project_version(),
            fatal_count,
        )

        assert report["blinter_version"] == get_project_version()
        assert report["target"] == "C:\\project\\main.bat"
        assert report["is_directory"] is False
        assert report["summary"]["total_issues"] == 2
        assert report["summary"]["fatal_issues"] == fatal_count
        assert report["summary"]["most_common_rule"] is not None
        assert len(report["processed_files"]) == 2
        assert report["skipped_files"] == [
            {"path": "C:\\project\\bad.bat", "reason": "Permission denied"}
        ]
        assert len(report["issues"]) == 2

        issue = report["issues"][0]
        assert issue["file"] == "C:\\project\\main.bat"
        assert issue["line"] == 5
        assert issue["code"] == "E002"
        assert issue["name"] == RULES["E002"].name
        assert issue["severity"] == "Error"
        assert issue["explanation"] == RULES["E002"].explanation
        assert issue["recommendation"] == RULES["E002"].recommendation
        assert issue["context"] == "GOTO missing label"

    def test_build_report_empty_issues(self) -> None:
        """Empty results should produce null most_common_rule."""
        results = self._make_results([])
        report = build_report(results, "script.bat", "1.0.0", 0)
        assert report["summary"]["total_issues"] == 0
        assert report["summary"]["most_common_rule"] is None
        assert report["issues"] == []


class TestJsonOutputCli:
    """Integration tests for JSON CLI flags."""

    def create_temp_batch_file(self, content: str) -> str:
        """Create a temporary batch file and return its path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def capture_stdout(self) -> io.StringIO:
        """Return a StringIO buffer installed as sys.stdout."""
        return io.StringIO()

    def test_output_flag_writes_json_file(self) -> None:
        """--output should write valid JSON while keeping human stdout."""
        content = "@echo off\necho Hello\n"
        temp_file = self.create_temp_batch_file(content)
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = str(Path(temp_dir) / "report.json")
            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                with patch(
                    "sys.argv", ["blinter.py", temp_file, "--output", report_path]
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code in [0, 1]
                output = captured.getvalue()
            finally:
                sys.stdout = old_stdout
                os.unlink(temp_file)

            assert "DETAILED ISSUES:" in output
            assert Path(report_path).is_file()
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            assert "issues" in report
            assert report["target"] == temp_file

    def test_format_json_stdout_only(self) -> None:
        """--format json should emit JSON on stdout without human output."""
        content = "@echo off\necho Hello\n"
        temp_file = self.create_temp_batch_file(content)
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            with patch("sys.argv", ["blinter.py", temp_file, "--format", "json"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code in [0, 1]
            output = captured.getvalue()
        finally:
            sys.stdout = old_stdout
            os.unlink(temp_file)

        assert "DETAILED ISSUES:" not in output
        assert "Blinter v" not in output
        report = json.loads(output)
        assert report["target"] == temp_file
        assert "summary" in report

    def test_format_json_with_output_file(self) -> None:
        """--format json --output should write file and suppress human stdout."""
        content = "@echo off\necho Hello\n"
        temp_file = self.create_temp_batch_file(content)
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = str(Path(temp_dir) / "report.json")
            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                with patch(
                    "sys.argv",
                    [
                        "blinter.py",
                        temp_file,
                        "--format",
                        "json",
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
                os.unlink(temp_file)

            assert output.strip() == ""
            assert "DETAILED ISSUES:" not in output
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            assert report["target"] == temp_file

    def test_invalid_output_flag_missing_value(self) -> None:
        """--output without a path should exit with code 1."""
        old_stderr = sys.stderr
        sys.stderr = captured_err = io.StringIO()
        try:
            with patch("sys.argv", ["blinter.py", "script.bat", "--output"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
            assert "requires a path" in captured_err.getvalue()
        finally:
            sys.stderr = old_stderr

    def test_invalid_format_value(self) -> None:
        """Unknown --format values should exit with code 1."""
        old_stderr = sys.stderr
        sys.stderr = captured_err = io.StringIO()
        try:
            with patch("sys.argv", ["blinter.py", "script.bat", "--format", "xml"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
            assert "Unknown format" in captured_err.getvalue()
        finally:
            sys.stderr = old_stderr

    def test_write_report_failure(self) -> None:
        """Write failures should print to stderr and exit with code 1."""
        content = "@echo off\necho Hello\n"
        temp_file = self.create_temp_batch_file(content)
        old_stderr = sys.stderr
        sys.stderr = captured_err = io.StringIO()

        def failing_write(_path: str, _report: dict[str, object]) -> None:
            raise PermissionError("access denied")

        try:
            with patch(
                "blinter.cli.main.write_report",
                side_effect=failing_write,
            ):
                with patch(
                    "sys.argv",
                    ["blinter.py", temp_file, "--output", "report.json"],
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1
            assert "Could not write JSON report" in captured_err.getvalue()
        finally:
            sys.stderr = old_stderr
            os.unlink(temp_file)

    def test_format_json_skipped_files_stay_out_of_stdout(self) -> None:
        """Skipped-file notes belong in the JSON report, not ahead of it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            good_bat = os.path.join(tmpdir, "good.bat")
            bad_bat = os.path.join(tmpdir, "bad.bat")
            Path(good_bat).write_text("@echo off\nexit /b 0\n", encoding="utf-8")
            Path(bad_bat).write_text("@echo off\n", encoding="utf-8")

            def lint_side_effect(
                file_path: str, *args: object, **kwargs: object
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
                    with patch("sys.argv", ["blinter.py", tmpdir, "--format", "json"]):
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1
                output = captured.getvalue()
            finally:
                sys.stdout = old_stdout

        assert not output.startswith("Skipped files")
        report = json.loads(output)
        assert report["skipped_files"]
        assert any(item["path"].endswith("bad.bat") for item in report["skipped_files"])

    def test_format_json_when_every_file_is_skipped(self) -> None:
        """JSON mode still emits a report when every file is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_bat = os.path.join(tmpdir, "bad.bat")
            Path(bad_bat).write_text("@echo off\n", encoding="utf-8")

            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                with patch(
                    "blinter.cli.main.lint_batch_file",
                    side_effect=PermissionError("Access denied"),
                ):
                    with patch("sys.argv", ["blinter.py", tmpdir, "--format", "json"]):
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1
                output = captured.getvalue()
            finally:
                sys.stdout = old_stdout

        report = json.loads(output)
        assert report["summary"]["files_processed"] == 0
        assert report["skipped_files"]


class TestJsonFormatterHelpers:
    """Tests for JSON formatter write/print helpers."""

    def test_write_and_print_report_round_trip(self) -> None:
        """write_report and print_report should produce valid JSON."""
        results = ProcessingResults(
            all_issues=[],
            file_results={},
            total_files_processed=0,
            files_with_errors=0,
            processed_file_paths=[],
        )
        report = build_report(results, "target.bat", "1.0.0", 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = str(Path(temp_dir) / "report.json")
            write_report(report_path, report)
            loaded = json.loads(Path(report_path).read_text(encoding="utf-8"))
            assert loaded == report

        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            print_report(report)
            parsed = json.loads(captured.getvalue())
            assert parsed == report
        finally:
            sys.stdout = old_stdout

    def test_help_documents_json_flags(self) -> None:
        """Help text should document JSON output options."""
        from blinter.output.formatters import print_help

        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            print_help()
            output = captured.getvalue()
        finally:
            sys.stdout = old_stdout

        assert "--output" in output
        assert "--format json" in output
