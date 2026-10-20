"""Tests for Rule and LintIssue data classes validation."""

import pytest

from blinter import (
    BlinterConfig,
    LintIssue,
    Rule,
    RuleSeverity,
)
from blinter.constants import MAX_LINE_LENGTH


class TestRuleValidation:
    """Test Rule dataclass validation."""

    def test_valid_rule_creation(self) -> None:
        """Test creating a valid rule."""
        rule = Rule(
            code="E001",
            name="Test Rule",
            severity=RuleSeverity.ERROR,
            explanation="This is a test rule",
            recommendation="Fix the issue",
        )
        assert rule.code == "E001"
        assert rule.name == "Test Rule"
        assert rule.severity == RuleSeverity.ERROR
        assert rule.explanation == "This is a test rule"
        assert rule.recommendation == "Fix the issue"

    def test_rule_empty_code_validation(self) -> None:
        """Test Rule validation with empty code."""
        with pytest.raises(ValueError, match="Rule code must be a non-empty string"):
            Rule(
                code="",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_none_code_validation(self) -> None:
        """Test Rule validation with None code."""
        with pytest.raises(ValueError, match="Rule code must be a non-empty string"):
            Rule(
                code=None,
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_non_string_code_validation(self) -> None:
        """Test Rule validation with non-string code."""
        with pytest.raises(ValueError, match="Rule code must be a non-empty string"):
            Rule(
                code=123,
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_empty_name_validation(self) -> None:
        """Test Rule validation with empty name."""
        with pytest.raises(ValueError, match="Rule name must be a non-empty string"):
            Rule(
                code="E001",
                name="",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_none_name_validation(self) -> None:
        """Test Rule validation with None name."""
        with pytest.raises(ValueError, match="Rule name must be a non-empty string"):
            Rule(
                code="E001",
                name=None,
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_non_string_name_validation(self) -> None:
        """Test Rule validation with non-string name."""
        with pytest.raises(ValueError, match="Rule name must be a non-empty string"):
            Rule(
                code="E001",
                name=123,
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_invalid_severity_validation(self) -> None:
        """Test Rule validation with invalid severity."""
        with pytest.raises(
            ValueError, match="Rule severity must be a RuleSeverity enum"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity="invalid",
                explanation="This is a test rule",
                recommendation="Fix the issue",
            )

    def test_rule_empty_explanation_validation(self) -> None:
        """Test Rule validation with empty explanation."""
        with pytest.raises(
            ValueError, match="Rule explanation must be a non-empty string"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="",
                recommendation="Fix the issue",
            )

    def test_rule_none_explanation_validation(self) -> None:
        """Test Rule validation with None explanation."""
        with pytest.raises(
            ValueError, match="Rule explanation must be a non-empty string"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation=None,
                recommendation="Fix the issue",
            )

    def test_rule_non_string_explanation_validation(self) -> None:
        """Test Rule validation with non-string explanation."""
        with pytest.raises(
            ValueError, match="Rule explanation must be a non-empty string"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation=123,
                recommendation="Fix the issue",
            )

    def test_rule_empty_recommendation_validation(self) -> None:
        """Test Rule validation with empty recommendation."""
        with pytest.raises(
            ValueError, match="Rule recommendation must be a non-empty string"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation="",
            )

    def test_rule_none_recommendation_validation(self) -> None:
        """Test Rule validation with None recommendation."""
        with pytest.raises(
            ValueError, match="Rule recommendation must be a non-empty string"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation=None,
            )

    def test_rule_non_string_recommendation_validation(self) -> None:
        """Test Rule validation with non-string recommendation."""
        with pytest.raises(
            ValueError, match="Rule recommendation must be a non-empty string"
        ):
            Rule(
                code="E001",
                name="Test Rule",
                severity=RuleSeverity.ERROR,
                explanation="This is a test rule",
                recommendation=123,
            )


class TestLintIssueValidation:
    """Test LintIssue dataclass validation."""

    def test_valid_lint_issue_creation(self) -> None:
        """Test creating a valid lint issue."""
        rule = Rule(
            code="E001",
            name="Test Rule",
            severity=RuleSeverity.ERROR,
            explanation="This is a test rule",
            recommendation="Fix the issue",
        )
        issue = LintIssue(line_number=5, rule=rule, context="Test context")
        assert issue.line_number == 5
        assert issue.rule == rule
        assert issue.context == "Test context"

    def test_valid_lint_issue_creation_no_context(self) -> None:
        """Test creating a valid lint issue without context."""
        rule = Rule(
            code="E001",
            name="Test Rule",
            severity=RuleSeverity.ERROR,
            explanation="This is a test rule",
            recommendation="Fix the issue",
        )
        issue = LintIssue(line_number=5, rule=rule)
        assert issue.line_number == 5
        assert issue.rule == rule
        assert issue.context == ""

    def test_lint_issue_negative_line_number_validation(self) -> None:
        """Test LintIssue validation with negative line number."""
        rule = Rule(
            code="E001",
            name="Test Rule",
            severity=RuleSeverity.ERROR,
            explanation="This is a test rule",
            recommendation="Fix the issue",
        )
        with pytest.raises(ValueError, match="Line number must be positive"):
            LintIssue(line_number=-1, rule=rule)

    def test_lint_issue_zero_line_number_validation(self) -> None:
        """Test LintIssue validation with zero line number."""
        rule = Rule(
            code="E001",
            name="Test Rule",
            severity=RuleSeverity.ERROR,
            explanation="This is a test rule",
            recommendation="Fix the issue",
        )
        with pytest.raises(ValueError, match="Line number must be positive"):
            LintIssue(line_number=0, rule=rule)

    def test_lint_issue_invalid_rule_validation(self) -> None:
        """Test LintIssue validation with invalid rule."""
        with pytest.raises(ValueError, match="Rule must be a Rule instance"):
            LintIssue(line_number=5, rule="invalid")

    def test_lint_issue_none_rule_validation(self) -> None:
        """Test LintIssue validation with None rule."""
        with pytest.raises(ValueError, match="Rule must be a Rule instance"):
            LintIssue(line_number=5, rule=None)


class TestBlinterConfigValidation:
    """Test BlinterConfig dataclass validation."""

    def test_scan_root_empty_string_rejected(self) -> None:
        """Empty scan_root must be rejected."""
        with pytest.raises(ValueError, match="scan_root must be a non-empty string"):
            BlinterConfig(scan_root="   ")

    def test_max_line_length_zero_rejected(self) -> None:
        """max_line_length of zero must be rejected."""
        with pytest.raises(ValueError, match="max_line_length must be between"):
            BlinterConfig(max_line_length=0)

    def test_max_line_length_over_limit_rejected(self) -> None:
        """max_line_length above MAX_LINE_LENGTH must be rejected."""

        with pytest.raises(ValueError, match="max_line_length must be between"):
            BlinterConfig(max_line_length=MAX_LINE_LENGTH + 1)
