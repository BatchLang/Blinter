"""Discover and load SSOT corpus cases under spec/corpus/."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from blinter.models import BlinterConfig, LintIssue
from blinter.rules.registry import RULES

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "spec" / "corpus"


@dataclass(frozen=True)
class SpecCorpusCase:
    """One committed corpus fixture with expected diagnostics."""

    id: str
    case_dir: Path
    input_path: Path
    expect: dict[str, Any]
    config: BlinterConfig


def _expected_rule_codes(expect: dict[str, Any]) -> set[str]:
    """Collect all rule codes referenced by a corpus expect.json."""
    codes: set[str] = set()
    rules = expect.get("rules", [])
    if isinstance(rules, list):
        codes.update(str(rule) for rule in rules)
    must_not = expect.get("must_not", [])
    if isinstance(must_not, list):
        codes.update(str(rule) for rule in must_not)
    lines = expect.get("lines", {})
    if isinstance(lines, dict):
        for line_codes in lines.values():
            if isinstance(line_codes, list):
                codes.update(str(rule) for rule in line_codes)
    return codes


def _case_requires_missing_rules(expect: dict[str, Any]) -> bool:
    """Return True when the case asserts rules not yet present in RULES."""
    return not _expected_rule_codes(expect).issubset(RULES.keys())


def discover_spec_corpus_cases() -> list[SpecCorpusCase]:
    """Return all corpus cases that have expect.json."""
    cases: list[SpecCorpusCase] = []
    for expect_path in sorted(CORPUS_DIR.glob("**/expect.json")):
        case_dir = expect_path.parent
        input_path = case_dir / "input.cmd"
        if not input_path.is_file():
            bat_path = case_dir / "input.bat"
            if bat_path.is_file():
                input_path = bat_path
            else:
                scripts = sorted(case_dir.glob("*.cmd")) + sorted(
                    case_dir.glob("*.bat")
                )
                if not scripts:
                    continue
                input_path = scripts[0]
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
        if _case_requires_missing_rules(expect):
            continue
        config_data = expect.get("config", {})
        if not isinstance(config_data, dict):
            config_data = {}
        scan_root = str(case_dir.resolve()) if config_data.get("follow_calls") else None
        disabled = config_data.get("disabled_rules")
        enabled = config_data.get("enabled_rules")
        config = BlinterConfig(
            follow_calls=bool(config_data.get("follow_calls", False)),
            scan_root=scan_root,
            disabled_rules=set(disabled) if disabled else set(),
            enabled_rules=set(enabled) if enabled else set(),
        )
        case_id = "/".join(case_dir.relative_to(CORPUS_DIR).parts)
        cases.append(
            SpecCorpusCase(
                id=case_id,
                case_dir=case_dir,
                input_path=input_path,
                expect=expect,
                config=config,
            )
        )
    return cases


def assert_issues_match(issues: list[LintIssue], expect: dict[str, Any]) -> None:
    """Assert lint issues match expect.json oracle fields."""
    typed_issues = list(issues)
    codes = {issue.rule.code for issue in typed_issues}
    by_line: dict[int, set[str]] = {}
    for issue in typed_issues:
        by_line.setdefault(issue.line_number, set()).add(issue.rule.code)

    for rule in expect.get("rules", []):
        assert rule in codes, f"Expected rule {rule} in findings, got {sorted(codes)}"

    lines = expect.get("lines", {})
    if isinstance(lines, dict):
        for line_str, expected_codes in lines.items():
            line_number = int(line_str)
            actual = by_line.get(line_number, set())
            for rule in expected_codes:
                assert (
                    rule in actual
                ), f"Line {line_number}: expected {rule}, got {sorted(actual)}"

    for rule in expect.get("must_not", []):
        assert rule not in codes, f"Rule {rule} must not appear, but was found"

    total = expect.get("total")
    if total is not None:
        assert len(typed_issues) == int(
            total
        ), f"Expected {total} total issues, got {len(typed_issues)}"
