"""Shared helpers for constructing LintIssue instances."""

import re
from typing import AbstractSet, List, Optional

from blinter.models import BlinterConfig, LintIssue, Rule
from blinter.rules.registry import RULES

_PERCENT_TILDE_INTERIOR = (
    r"(?:[fdpnxsatz$])*(?:[A-Za-z_][A-Za-z0-9_]*:\d+|[0-9*]|[A-Za-z_][A-Za-z0-9_]*)"
)
PERCENT_TILDE_TOKEN_RE = re.compile(
    rf"(?<!\%)%~({_PERCENT_TILDE_INTERIOR})(?:%|(?![0-9]))",
    re.IGNORECASE,
)
_FOR_METAVAR_TILDE_RE = re.compile(r"%%~[A-Za-z]")
SUBSTRING_OP_RE = re.compile(
    r"%([a-zA-Z_][a-zA-Z0-9_]*):~([^%]*)%",
    re.IGNORECASE,
)
REPLACEMENT_OP_RE = re.compile(
    r"%([a-zA-Z_][a-zA-Z0-9_]*):(?!~)([^%]*)%",
    re.IGNORECASE,
)
_PLAIN_PERCENT_VAR_RE = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")


def strip_percent_expansions(text: str) -> str:
    """Remove percent expansions so a later literal ``N%`` check ignores them."""
    without_escaped = text.replace("%%", "")
    without_tilde = PERCENT_TILDE_TOKEN_RE.sub("", without_escaped)
    without_substring = SUBSTRING_OP_RE.sub("", without_tilde)
    without_replacement = REPLACEMENT_OP_RE.sub("", without_substring)
    return _PLAIN_PERCENT_VAR_RE.sub("", without_replacement)


def strip_for_metavar_tilde_tokens(line: str) -> str:
    """Remove FOR-loop %%~X tokens before percent-tilde parameter checks."""
    return _FOR_METAVAR_TILDE_RE.sub("", line)


def _has_any_enabled_rules(config: BlinterConfig, rule_codes: AbstractSet[str]) -> bool:
    """Return True when at least one rule in rule_codes is enabled."""
    return any(config.is_rule_enabled(code) for code in rule_codes)


def _rule_codes_with_prefix(prefix: str) -> frozenset[str]:
    """Return all registry rule codes that start with prefix."""
    return frozenset(code for code in RULES if code.startswith(prefix))


def _s011_rule(max_line_length: int) -> Rule:
    """Return the S011 rule, with explanation adjusted for custom line length."""
    base_rule = RULES["S011"]
    if max_line_length == 100:
        return base_rule
    return Rule(
        code=base_rule.code,
        name=base_rule.name,
        severity=base_rule.severity,
        explanation=(
            f"Lines longer than {max_line_length} characters are hard to read "
            "and maintain"
        ),
        recommendation=base_rule.recommendation,
    )


def _add_issue(
    issues: List[LintIssue],
    line_number: int,
    rule_code: str,
    context: str = "",
    file_path: Optional[str] = None,
) -> None:
    """
    Add a linting issue to the issues list.

    This helper function reduces code duplication by centralizing the pattern of
    creating and appending LintIssue objects.

    Args:
        issues: List to append the issue to
        line_number: Line number where the issue occurs
        rule_code: Code of the rule being violated (e.g., "E001")
        context: Additional context about the issue
        file_path: Optional path to the file containing the issue

    Thread-safe: Yes - only appends to provided list (caller manages thread safety)
    """
    issues.append(
        LintIssue(
            line_number=line_number,
            rule=RULES[rule_code],
            context=context,
            file_path=file_path,
        )
    )
