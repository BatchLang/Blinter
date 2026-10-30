"""Performance issue line checks (P-prefix rules)."""

import re
from typing import (
    List,
)

from blinter.models import LintIssue
from blinter.parsing.context import _is_endlocal_command, _is_setlocal_command
from blinter.parsing.structure import _delayed_expansion_active_at_line
from blinter.patterns import (
    _COMPILED_SETLOCAL_DISABLE,
)
from blinter.rules.registry import RULES

_DIR_COMMAND_RE = re.compile(r"dir(?:\s|$)", re.IGNORECASE)
_DIR_BARE_SWITCH_RE = re.compile(r"/b", re.IGNORECASE)
# A pipe, or a stdout redirect. ``2>`` and ``2>>`` only redirect stderr.
_OUTPUT_PROCESSED_RE = re.compile(r"\||(?<![2>])>")


def _is_dir_output_processed_without_bare(stripped: str) -> bool:
    """Return True for a DIR line that pipes or redirects output without /B."""
    return (
        _DIR_COMMAND_RE.match(stripped) is not None
        and _DIR_BARE_SWITCH_RE.search(stripped) is None
        and _OUTPUT_PROCESSED_RE.search(stripped) is not None
    )


def _check_temp_file_usage(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for P007: Temporary file without random name."""
    issues: List[LintIssue] = []
    temp_patterns = [r"temp\.txt", r"tmp\.txt", r"temp\.log"]
    for pattern in temp_patterns:
        if (
            re.search(pattern, stripped, re.IGNORECASE)
            and "random" not in stripped.lower()
        ):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["P007"],
                    context="Temporary file should use %RANDOM% to prevent collisions",
                )
            )
            break
    return issues


def _check_for_loop_optimization(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for P009: Inefficient FOR loop pattern."""
    issues: List[LintIssue] = []
    for_match = re.match(
        r"for\s+/f\s+(?:[\"']([^\"']*)[\"']|(\S+))\s+%%\w+\s+in",
        stripped,
        re.IGNORECASE,
    )
    if for_match:
        for_options = str(for_match.group(1) or for_match.group(2) or "").lower()
        if "tokens=" not in for_options and "delims=" not in for_options:
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["P009"],
                    context=(
                        "FOR /F defaults to tokens=1; use tokens=* when the "
                        "entire line is needed"
                    ),
                )
            )
    return issues


def _check_delay_implementation(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for P015: Inefficient delay implementation."""
    issues: List[LintIssue] = []
    if (
        re.search(r"ping\s+.*localhost.*", stripped, re.IGNORECASE)
        or re.search(r"ping\s+127\.0\.0\.1", stripped, re.IGNORECASE)
        or re.search(r"choice\s+/t\s+\d+", stripped, re.IGNORECASE)
    ):
        # Check if this looks like a delay implementation
        if re.search(r"ping.*-n\s+\d+.*localhost", stripped, re.IGNORECASE):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["P015"],
                    context=(
                        "Using ping localhost for delays is inefficient - "
                        "use TIMEOUT command for Vista+"
                    ),
                )
            )
        elif re.search(r"choice\s+/t\s+\d+.*>nul", stripped, re.IGNORECASE):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["P015"],
                    context=(
                        "Using CHOICE for delays is inefficient - "
                        "use TIMEOUT command for Vista+"
                    ),
                )
            )
    return issues


def _check_redundant_disable_delay(
    stripped: str, line_num: int, _lines: List[str], has_literal_exclamations: bool
) -> List[LintIssue]:
    """Check for P026: Redundant DISABLEDELAYEDEXPANSION."""
    issues: List[LintIssue] = []
    if not _COMPILED_SETLOCAL_DISABLE.search(stripped):
        return issues

    # Check if this is redundant based on context
    is_redundant = True

    # Don't flag if at the very start of the script (lines 1-10) - defensive programming
    if line_num <= 10:
        is_redundant = False

    # Don't flag if script has literal exclamation marks (protecting ! characters)
    if has_literal_exclamations:
        is_redundant = False

    # Don't flag if there's an ENDLOCAL within 3 lines before this (toggling pattern)
    # Check the previous 3 lines for ENDLOCAL to identify genuine toggling
    start_check = max(0, line_num - 4)  # Check up to 3 lines back
    recent_lines = _lines[start_check : line_num - 1]
    if any(
        "endlocal" in prev_line.lower()
        for prev_line in recent_lines
        if prev_line.strip()
    ):
        is_redundant = False

    # Don't flag if combined with enableextensions (common pattern)
    if re.search(r"setlocal\s+enableextensions", stripped, re.IGNORECASE):
        is_redundant = False

    if is_redundant:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["P026"],
                context=(
                    "DISABLEDELAYEDEXPANSION is redundant "
                    "(delayed expansion is disabled by default)"
                ),
            )
        )
    return issues


def _check_performance_issues(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    _lines: List[str],
    line_num: int,
    line: str,
    has_setlocal: bool,
    has_set_commands: bool,
    _has_delayed_expansion: bool,
    uses_delayed_vars: bool,
    has_disable_delayed_expansion: bool,  # pylint: disable=unused-argument
    has_literal_exclamations: bool,
    has_disable_expansion_lines: bool,  # pylint: disable=unused-argument
) -> List[LintIssue]:
    """Check for performance level issues."""
    issues: List[LintIssue] = []
    stripped = line.strip()

    # P003: Unnecessary SETLOCAL
    if _is_setlocal_command(line) and not has_set_commands:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["P003"],
                context="SETLOCAL used without any SET commands",
            )
        )

    # P004: Unnecessary ENABLEDELAYEDEXPANSION
    if "enabledelayedexpansion" in stripped.lower() and not uses_delayed_vars:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["P004"],
                context="ENABLEDELAYEDEXPANSION used without !variables!",
            )
        )

    # P005: ENDLOCAL without SETLOCAL
    if _is_endlocal_command(line) and not has_setlocal:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["P005"],
                context="ENDLOCAL used without corresponding SETLOCAL",
            )
        )

    # P007: Temporary file without random name
    issues.extend(_check_temp_file_usage(stripped, line_num))

    # P008: Delayed expansion without enablement
    # Match any content between exclamation marks, including special chars like @, -, #, $, etc.
    if not _delayed_expansion_active_at_line(_lines, line_num) and re.search(
        r"![^!]+!", stripped
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["P008"],
                context="Delayed expansion variables used without ENABLEDELAYEDEXPANSION",
            )
        )

    # P009: Inefficient FOR loop pattern
    issues.extend(_check_for_loop_optimization(stripped, line_num))

    # P010: DIR without /B when its output is redirected or piped
    if _is_dir_output_processed_without_bare(stripped):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["P010"],
                context="DIR output is processed - use /B to list bare file names",
            )
        )

    # P015: Inefficient delay implementation
    issues.extend(_check_delay_implementation(stripped, line_num))

    # P026: Redundant DISABLEDELAYEDEXPANSION
    issues.extend(
        _check_redundant_disable_delay(
            stripped, line_num, _lines, has_literal_exclamations
        )
    )

    return issues


def _check_setlocal_nesting_depth(lines: List[str]) -> List[LintIssue]:
    """Check SETLOCAL nesting depth against cmd.exe limit (P027)."""
    depth = 0
    max_depth = 0
    max_line = 0
    for index, line in enumerate(lines, start=1):
        if _is_setlocal_command(line):
            depth += 1
            if depth > max_depth:
                max_depth = depth
                max_line = index
        elif _is_endlocal_command(line):
            depth = max(depth - 1, 0)
    if max_depth > 32:
        return [
            LintIssue(
                line_number=max_line,
                rule=RULES["P027"],
                context=(
                    f"SETLOCAL nesting depth {max_depth} exceeds cmd.exe limit of 32"
                ),
            )
        ]
    return []
