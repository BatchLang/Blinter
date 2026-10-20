"""Tests for checker orchestration helpers."""

from unittest.mock import patch

from blinter.checkers.orchestration import (
    _dedupe_temp_path_issues,
    _filter_issues_by_config,
    _process_file_checks,
)
from blinter.models import BlinterConfig, LintIssue, Rule, RuleSeverity
from blinter.rules.registry import RULES

# Single-method classes group one orchestration behavior each.
# pylint: disable=too-few-public-methods


def _issue(code: str, line: int = 1) -> LintIssue:
    return LintIssue(
        line_number=line,
        rule=Rule(
            code=code,
            name=f"Rule {code}",
            severity=RuleSeverity.ERROR,
            explanation="test",
            recommendation="test",
        ),
    )


class TestFilterIssuesByConfig:
    """Direct tests for issue filtering and inline suppressions."""

    def test_disabled_rules_filter(self) -> None:
        config = BlinterConfig(disabled_rules={"E001"})
        issues = [_issue("E001"), _issue("E002")]
        filtered = _filter_issues_by_config(issues, config, {})
        assert [issue.rule.code for issue in filtered] == ["E002"]

    def test_min_severity_filter(self) -> None:
        config = BlinterConfig(min_severity=RuleSeverity.SECURITY)
        issues = [
            LintIssue(
                line_number=1,
                rule=Rule(
                    code="W001",
                    name="Warning",
                    severity=RuleSeverity.WARNING,
                    explanation="test",
                    recommendation="test",
                ),
            ),
            LintIssue(
                line_number=2,
                rule=Rule(
                    code="SEC001",
                    name="Security",
                    severity=RuleSeverity.SECURITY,
                    explanation="test",
                    recommendation="test",
                ),
            ),
        ]
        filtered = _filter_issues_by_config(issues, config, {})
        assert [issue.rule.code for issue in filtered] == ["SEC001"]

    def test_inline_suppression_all_rules(self) -> None:
        config = BlinterConfig()
        issues = [_issue("E001", line=5), _issue("E002", line=6)]
        suppressions: dict[int, set[str]] = {5: set()}
        filtered = _filter_issues_by_config(issues, config, suppressions)
        assert [issue.rule.code for issue in filtered] == ["E002"]

    def test_inline_suppression_specific_rule(self) -> None:
        config = BlinterConfig()
        issues = [_issue("E001", line=3), _issue("E002", line=3)]
        suppressions = {3: {"E001"}}
        filtered = _filter_issues_by_config(issues, config, suppressions)
        assert [issue.rule.code for issue in filtered] == ["E002"]

    def test_combined_filters(self) -> None:
        config = BlinterConfig(
            disabled_rules={"E002"},
            min_severity=RuleSeverity.ERROR,
        )
        issues = [
            _issue("E001", line=1),
            _issue("E002", line=2),
            LintIssue(
                line_number=3,
                rule=Rule(
                    code="W001",
                    name="Warning",
                    severity=RuleSeverity.WARNING,
                    explanation="test",
                    recommendation="test",
                ),
            ),
        ]
        suppressions: dict[int, set[str]] = {1: set()}
        filtered = _filter_issues_by_config(issues, config, suppressions)
        assert [issue.rule.code for issue in filtered] == []


class TestProcessFileChecks:
    """Tests for checker orchestration execution."""

    def test_skips_security_checker_when_all_sec_rules_disabled(self) -> None:
        """Security checkers are not invoked when every SEC rule is disabled."""
        all_sec_rules = {code for code in RULES if code.startswith("SEC")}
        config = BlinterConfig(disabled_rules=all_sec_rules)
        lines = ["net user admin password /add\n"]

        with patch(
            "blinter.checkers.orchestration._check_security_issues"
        ) as mock_security:
            _process_file_checks(
                lines,
                {},
                set(),
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                config,
            )
            mock_security.assert_not_called()


class TestDedupeTempPathIssues:
    """Tests for SEC007/SEC012/SEC017 deduplication."""

    def test_suppresses_sec007_when_sec012_present(self) -> None:
        issues = [
            LintIssue(line_number=1, rule=RULES["SEC007"]),
            LintIssue(line_number=1, rule=RULES["SEC012"]),
        ]
        deduped = _dedupe_temp_path_issues(issues)
        codes = [issue.rule.code for issue in deduped]
        assert codes == ["SEC012"]

    def test_suppresses_sec007_when_sec017_present(self) -> None:
        issues = [
            LintIssue(line_number=2, rule=RULES["SEC007"]),
            LintIssue(line_number=2, rule=RULES["SEC017"]),
        ]
        deduped = _dedupe_temp_path_issues(issues)
        codes = [issue.rule.code for issue in deduped]
        assert codes == ["SEC017"]

    def test_keeps_highest_priority_when_sec012_and_sec017_present(self) -> None:
        issues = [
            LintIssue(line_number=3, rule=RULES["SEC017"]),
            LintIssue(line_number=3, rule=RULES["SEC012"]),
        ]
        deduped = _dedupe_temp_path_issues(issues)
        codes = [issue.rule.code for issue in deduped]
        assert codes == ["SEC012"]

    def test_keeps_sec007_on_other_lines(self) -> None:
        issues = [
            LintIssue(line_number=1, rule=RULES["SEC007"]),
            LintIssue(line_number=2, rule=RULES["SEC012"]),
        ]
        deduped = _dedupe_temp_path_issues(issues)
        codes = [issue.rule.code for issue in deduped]
        assert codes == ["SEC007", "SEC012"]
