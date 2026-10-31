"""Undefined and unsafe variable usage checks."""

import re
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.constants import BUILTIN_VARS
from blinter.models import LintIssue
from blinter.parsing.context import _is_comment_line
from blinter.rules.helpers import _add_issue


def _get_available_vars_at_line(
    line_num: int,
    set_vars: Set[str],
    called_scripts_vars: Optional[Dict[int, Set[str]]],
) -> Set[str]:
    """
    Get all variables available at a specific line number.

    Args:
        line_num: Current line number
        set_vars: Variables defined in current file
        called_scripts_vars: Optional dict mapping line numbers to variables from called scripts

    Returns:
        Set of all available variable names
    """
    available_vars = set_vars.copy()

    if called_scripts_vars:
        for call_line_num, called_vars in called_scripts_vars.items():
            if call_line_num < line_num:
                available_vars.update(called_vars)

    return available_vars


def _should_check_variable(
    var_name: str,
    uses_dynamic_vars: bool,
    available_vars: Set[str],
) -> bool:
    """
    Determine if a variable should be checked for being undefined.

    Args:
        var_name: Variable name to check
        uses_dynamic_vars: Whether script uses dynamic variable assignment
        available_vars: Set of available variables

    Returns:
        True if variable should be checked
    """
    # Skip built-in variables and single character variables (usually loop variables)
    if var_name in BUILTIN_VARS or len(var_name) <= 1:
        return False

    # If dynamic vars are used, skip undefined variable warnings
    if uses_dynamic_vars:
        return False

    # Only check if variable is not defined
    return var_name not in available_vars


def _is_doubled_percent_literal(line: str, match: re.Match[str]) -> bool:
    """Return True when %VAR% is a batch-escaped literal (%%VAR%%) not expansion."""
    start = match.start()
    end = match.end()
    if start > 0 and line[start - 1] == "%":
        return True
    return end < len(line) and line[end] == "%"


def _check_undefined_variables(
    lines: List[str],
    set_vars: Set[str],
    called_scripts_vars: Optional[Dict[int, Set[str]]] = None,
) -> List[LintIssue]:
    """
    Check for usage of undefined variables with position-aware tracking.

    When called_scripts_vars is provided (via --follow-calls), variables from called
    scripts are considered "defined" only for lines AFTER the CALL statement.

    Args:
        lines: Lines of the batch file
        set_vars: Variables defined in the current file
        called_scripts_vars: Optional dict mapping line numbers to variables from called scripts

    Returns:
        List of LintIssue objects for undefined variables
    """
    issues: List[LintIssue] = []
    uses_dynamic_vars = "__DYNAMIC_VARS__" in set_vars
    var_usage_pattern = re.compile(
        r"%([A-Z][A-Z0-9_]*)%|!([A-Z][A-Z0-9_]*)!", re.IGNORECASE
    )
    string_op_pattern = re.compile(
        r"%[A-Z0-9_]+:[^%]*%|![A-Z0-9_]+:[^!]*!",
        re.IGNORECASE,
    )
    macro_temp_pattern = re.compile(r"^[A-Z]\d+$")

    for i, line in enumerate(lines, start=1):
        # A comment reads no variable
        if _is_comment_line(line):
            continue

        # Skip lines with string operations like %DATE:/=-% or !VAR:"=!
        if string_op_pattern.search(line):
            continue

        # CALL SET with %% indirection defines variables dynamically
        if re.search(r"\bcall\s+set\s", line, re.IGNORECASE) and "%%" in line:
            continue

        available_vars = _get_available_vars_at_line(i, set_vars, called_scripts_vars)

        for match in var_usage_pattern.finditer(line):
            if _is_doubled_percent_literal(line, match):
                continue

            var_name: str = (match.group(1) or match.group(2) or "").upper()

            if macro_temp_pattern.match(var_name):
                continue

            if _should_check_variable(var_name, uses_dynamic_vars, available_vars):
                _add_issue(
                    issues,
                    line_number=i,
                    rule_code="E006",
                    context=f"Variable '{var_name}' is used but never defined",
                )

    return issues
