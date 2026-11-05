"""Coordinates all checker categories for a parsed script."""

from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.checkers.advanced import (
    _check_advanced_escaping_rules,
    _check_advanced_for_rules,
    _check_advanced_performance,
    _check_advanced_process_mgmt,
    _check_advanced_security,
    _check_advanced_style_patterns,
    _check_advanced_style_rules,
    _check_advanced_vars,
    _check_enhanced_commands,
    _check_enhanced_performance,
    _check_enhanced_security_rules,
)
from blinter.checkers.cmd_extended import check_extended_warning_file
from blinter.checkers.globals import (
    _check_cmd_case_consistency,
    _check_code_duplication,
    _check_inconsistent_indentation,
    _check_missing_exit_statement,
    _check_missing_header_doc,
    _check_missing_pause,
    _check_nested_paren_mismatch,
    _check_redundant_operations,
    _check_unreachable_code,
)
from blinter.checkers.performance import (
    _check_performance_issues,
    _check_setlocal_nesting_depth,
)
from blinter.checkers.security import _check_security_issues
from blinter.checkers.style import _check_style_issues
from blinter.checkers.syntax import (
    _check_for_do_paren_next_line,
    _check_if_block_paren_next_line,
    _check_syntax_errors,
)
from blinter.checkers.vars import _check_undefined_variables
from blinter.checkers.warnings import _check_warning_issues
from blinter.constants import LARGE_FILE_LINE_THRESHOLD
from blinter.models import BlinterConfig, LintIssue
from blinter.rules.helpers import _has_any_enabled_rules, _rule_codes_with_prefix

_ERROR_RULES = _rule_codes_with_prefix("E")
_WARNING_RULES = _rule_codes_with_prefix("W")
_STYLE_RULES = _rule_codes_with_prefix("S")
_SECURITY_RULES = _rule_codes_with_prefix("SEC")
_PERFORMANCE_RULES = _rule_codes_with_prefix("P")
_TEMP_PATH_RULE_PRIORITY: tuple[str, ...] = ("SEC012", "SEC017", "SEC007")


def _dedupe_temp_path_issues(issues: List[LintIssue]) -> List[LintIssue]:
    """Keep at most one temp-path SEC rule per line (most specific wins)."""
    winners_by_line: Dict[int, str] = {}
    for issue in issues:
        if issue.rule.code not in _TEMP_PATH_RULE_PRIORITY:
            continue
        current = winners_by_line.get(issue.line_number)
        if current is None:
            winners_by_line[issue.line_number] = issue.rule.code
            continue
        if _TEMP_PATH_RULE_PRIORITY.index(
            issue.rule.code
        ) < _TEMP_PATH_RULE_PRIORITY.index(current):
            winners_by_line[issue.line_number] = issue.rule.code

    if not winners_by_line:
        return issues

    seen_winners: Set[tuple[int, str]] = set()
    result: List[LintIssue] = []
    for issue in issues:
        if issue.rule.code not in _TEMP_PATH_RULE_PRIORITY:
            result.append(issue)
            continue
        winner = winners_by_line.get(issue.line_number)
        key = (issue.line_number, winner or "")
        if winner == issue.rule.code and key not in seen_winners:
            seen_winners.add(key)
            result.append(issue)
    return result


def _append_line_checks(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    issues: List[LintIssue],
    *,
    lines: List[str],
    line: str,
    line_number: int,
    labels: Dict[str, int],
    set_vars: Set[str],
    has_setlocal: bool,
    has_set_commands: bool,
    uses_delayed_vars: bool,
    has_literal_exclamations: bool,
    config: BlinterConfig,
    run_errors: bool,
    run_warnings: bool,
    run_style: bool,
    run_security: bool,
    run_performance: bool,
    file_path: str = "",
) -> None:
    """Run enabled per-line checker groups for a single script line."""
    if run_errors:
        issues.extend(_check_syntax_errors(line, line_number, labels, lines=lines))
        stripped_lower = line.strip().lower()
        if stripped_lower.startswith("if"):
            issues.extend(_check_if_block_paren_next_line(lines, line_number))
        if stripped_lower.startswith("for"):
            issues.extend(_check_for_do_paren_next_line(lines, line_number))
        issues.extend(_check_advanced_escaping_rules(line, line_number))

    if run_warnings:
        issues.extend(
            _check_warning_issues(
                line,
                line_number,
                set_vars,
                lines=lines,
                file_path=file_path,
            )
        )
        issues.extend(_check_advanced_for_rules(line, line_number, lines=lines))
        issues.extend(_check_advanced_process_mgmt(lines, line_number))

    if run_style:
        issues.extend(_check_style_issues(line, line_number, config.max_line_length))
        issues.extend(_check_advanced_style_patterns(line, line_number, lines))

    if run_security:
        issues.extend(_check_security_issues(line, line_number, lines))
        issues.extend(_check_advanced_security(line, line_number, lines, labels))

    if run_performance:
        issues.extend(
            _check_performance_issues(
                lines,
                line_number,
                line,
                has_setlocal,
                has_set_commands,
                uses_delayed_vars,
                has_literal_exclamations,
            )
        )
        if len(lines) <= LARGE_FILE_LINE_THRESHOLD:
            issues.extend(_check_advanced_performance(lines, line_number, line))


def _append_global_checks(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    issues: List[LintIssue],
    *,
    lines: List[str],
    set_vars: Set[str],
    called_scripts_vars: Optional[Dict[int, Set[str]]],
    config: BlinterConfig,
    run_errors: bool,
    run_warnings: bool,
    run_style: bool,
    run_security: bool,
    run_performance: bool,
) -> None:
    """Run enabled global checker groups across the full script."""
    if run_errors:
        issues.extend(_check_undefined_variables(lines, set_vars, called_scripts_vars))
        issues.extend(_check_nested_paren_mismatch(lines))
        issues.extend(_check_advanced_vars(lines))

    if run_warnings:
        issues.extend(_check_missing_exit_statement(lines))
        if len(lines) <= LARGE_FILE_LINE_THRESHOLD:
            issues.extend(_check_unreachable_code(lines))
        issues.extend(_check_code_duplication(lines))
        issues.extend(_check_enhanced_commands(lines))
        issues.extend(_check_missing_pause(lines))
        issues.extend(check_extended_warning_file(lines, file_path=""))

    if run_security:
        issues.extend(_check_enhanced_security_rules(lines))

    if run_performance:
        issues.extend(_check_redundant_operations(lines))
        issues.extend(_check_enhanced_performance(lines))
        issues.extend(_check_setlocal_nesting_depth(lines))

    if run_style:
        issues.extend(_check_inconsistent_indentation(lines))
        issues.extend(_check_missing_header_doc(lines))
        if len(lines) <= LARGE_FILE_LINE_THRESHOLD:
            issues.extend(_check_cmd_case_consistency(lines))
        issues.extend(_check_advanced_style_rules(lines, config.max_line_length))


def _process_file_checks(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    lines: List[str],
    labels: Dict[str, int],
    set_vars: Set[str],
    has_setlocal: bool,
    has_set_commands: bool,
    uses_delayed_vars: bool,
    has_literal_exclamations: bool,
    config: BlinterConfig,
    skip_lines: Optional[Set[int]] = None,
    called_scripts_vars: Optional[Dict[int, Set[str]]] = None,
    file_path: str = "",
) -> List[LintIssue]:
    """Process all line-by-line and global checks.

    Args:
        skip_lines: Optional set of line numbers to skip (e.g., embedded script blocks)
        called_scripts_vars: Optional dict mapping line numbers to variables from called scripts
    """
    issues: List[LintIssue] = []

    if skip_lines is None:
        skip_lines = set()

    run_errors = _has_any_enabled_rules(config, _ERROR_RULES)
    run_warnings = _has_any_enabled_rules(config, _WARNING_RULES)
    run_style = _has_any_enabled_rules(config, _STYLE_RULES)
    run_security = _has_any_enabled_rules(config, _SECURITY_RULES)
    run_performance = _has_any_enabled_rules(config, _PERFORMANCE_RULES)

    # Check each line with all rule categories
    for i, line in enumerate(lines, start=1):
        if i in skip_lines:
            continue

        _append_line_checks(
            issues,
            lines=lines,
            line=line,
            line_number=i,
            labels=labels,
            set_vars=set_vars,
            has_setlocal=has_setlocal,
            has_set_commands=has_set_commands,
            uses_delayed_vars=uses_delayed_vars,
            has_literal_exclamations=has_literal_exclamations,
            config=config,
            run_errors=run_errors,
            run_warnings=run_warnings,
            run_style=run_style,
            run_security=run_security,
            run_performance=run_performance,
            file_path=file_path,
        )

    _append_global_checks(
        issues,
        lines=lines,
        set_vars=set_vars,
        called_scripts_vars=called_scripts_vars,
        config=config,
        run_errors=run_errors,
        run_warnings=run_warnings,
        run_style=run_style,
        run_security=run_security,
        run_performance=run_performance,
    )

    if run_security:
        issues[:] = _dedupe_temp_path_issues(issues)

    return issues


def _filter_issues_by_config(
    issues: List[LintIssue],
    config: BlinterConfig,
    suppressions: Dict[int, Set[str]],
) -> List[LintIssue]:
    """
    Filter issues based on configuration settings and inline suppressions.

    Args:
        issues: List of all issues found during linting
        config: Configuration object with rule and severity settings
        suppressions: Dictionary mapping line numbers to sets of suppressed rule codes

    Returns:
        Filtered list of issues that should be reported
    """
    filtered_issues = []
    for issue in issues:
        # Check if rule is enabled
        if not config.is_rule_enabled(issue.rule.code):
            continue

        # Check if severity should be included
        if not config.should_include_severity(issue.rule.severity):
            continue

        # Check if issue is suppressed by inline comment
        if issue.line_number in suppressions:
            suppressed_codes = suppressions[issue.line_number]
            # Empty set means suppress all rules on this line
            if not suppressed_codes or issue.rule.code in suppressed_codes:
                continue

        filtered_issues.append(issue)

    return filtered_issues
