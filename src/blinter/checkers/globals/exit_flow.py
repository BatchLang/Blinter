"""Exit statements and unreachable-code detection."""

from dataclasses import dataclass, field
import re
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.models import LintIssue
from blinter.parsing.context import _is_blank_or_comment
from blinter.parsing.structure import _update_paren_depth
from blinter.rules.registry import RULES


@dataclass(frozen=True)
class _ScriptLayout:
    """First meaningful executable and label positions in a script."""

    has_meaningful_code: bool
    first_executable_line: int
    first_label_line: int


def _analyze_script_layout(lines: List[str]) -> _ScriptLayout:
    """Scan lines for the first executable command and label."""
    has_meaningful_code = False
    first_executable_line = -1
    first_label_line = -1

    for index, line in enumerate(lines):
        stripped = line.strip().lower()
        if _is_blank_or_comment(stripped):
            continue
        if stripped.startswith(":") and not stripped.startswith("::"):
            if first_label_line == -1:
                first_label_line = index
            continue
        if _is_truly_executable_command(stripped):
            if first_executable_line == -1:
                first_executable_line = index
            if not re.match(r"^@?echo\s+(off|on)$", stripped):
                has_meaningful_code = True

    return _ScriptLayout(
        has_meaningful_code=has_meaningful_code,
        first_executable_line=first_executable_line,
        first_label_line=first_label_line,
    )


def _find_last_executable_line(lines: List[str]) -> int:
    """Return the 1-based line number of the last executable command."""
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip().lower()
        if _is_truly_executable_command(stripped):
            return index + 1
    return -1


def _is_subroutine_library(layout: _ScriptLayout) -> bool:
    """Return True when labels precede all executable code."""
    return (
        layout.first_label_line != -1
        and layout.first_executable_line != -1
        and layout.first_label_line < layout.first_executable_line
    )


def _check_missing_exit_statement(lines: List[str]) -> List[LintIssue]:
    """Check if script can reach EOF without an explicit EXIT statement (W001).

    This function performs control flow analysis to determine if the main execution
    path can fall through to end-of-file without encountering an EXIT statement.

    Smart detection includes:
    - Allows scripts where all paths lead to EXIT or GOTO :EOF
    - Allows pure subroutine libraries (scripts that start with a label before any executable code)
    - Allows scripts with only @echo off and comments (essentially setup-only scripts)
    - Flags scripts where main execution can fall through to EOF
    - Understands GOTO, labels, and conditional branches
    """
    issues: List[LintIssue] = []
    layout = _analyze_script_layout(lines)

    if not layout.has_meaningful_code or _is_subroutine_library(layout):
        return issues

    if _can_execution_reach_eof(lines):
        last_executable_line = _find_last_executable_line(lines)
        if last_executable_line > 0:
            issues.append(
                LintIssue(
                    line_number=last_executable_line,
                    rule=RULES["W001"],
                    context="Script can reach end of file without explicit EXIT statement",
                )
            )

    return issues


def _has_executable_after(lines: List[str], start_index: int) -> bool:
    """Return True when executable commands appear after start_index."""
    for line in lines[start_index + 1 :]:
        if _is_truly_executable_command(line.strip().lower()):
            return True
    return False


def _is_else_transition(stripped: str) -> bool:
    """Return True when a line closes a block and opens an ELSE branch."""
    close_match = re.match(r"^\)(?:\s*(?:>>|[12]>|[<>]))?", stripped)
    if not close_match:
        return False
    remainder = stripped[close_match.end() :].strip()
    return bool(re.match(r"else\b", remainder, re.IGNORECASE))


def _if_else_block_exits_reach_eof(
    previous_depth: int,
    paren_depth: int,
    branch_state: tuple[bool, bool],
    lines: List[str],
    index: int,
) -> bool:
    """Return True when a completed IF/ELSE always exits and has no code after."""
    if_branch_exited, else_branch_exited = branch_state
    return (
        previous_depth == 1
        and paren_depth == 0
        and if_branch_exited
        and else_branch_exited
        and not _has_executable_after(lines, index)
    )


def _build_label_index(lines: List[str]) -> Dict[str, int]:
    """Map normalized label names to zero-based line indices."""
    labels: Dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip().lower()
        if not stripped.startswith(":") or stripped.startswith("::"):
            continue
        label_content = stripped[1:]
        if re.search(r"[a-zA-Z0-9]", label_content):
            labels[stripped] = index
    return labels


def _normalize_goto_target(target: str) -> str:
    """Normalize a GOTO target to lowercase label form ``:name``."""
    normalized = target.lower().strip()
    if not normalized.startswith(":"):
        normalized = f":{normalized}"
    return normalized


def _parse_goto_target(stripped: str) -> Optional[str]:
    """Extract and normalize the label target from a GOTO line."""
    match = re.match(r"goto\s+(\S+)", stripped, re.IGNORECASE)
    if match is None:
        return None
    return _normalize_goto_target(match.group(1))


def _is_goto_eof_target(target: str) -> bool:
    """Return True when GOTO targets the implicit end-of-file label."""
    return target.lstrip(":") == "eof"


def _apply_exit_to_branch_state(
    paren_depth: int,
    in_else_branch: bool,
    if_branch_exited: bool,
    else_branch_exited: bool,
) -> tuple[bool, bool, Optional[bool]]:
    """Update branch exit flags; return (if_exited, else_exited, stop_result)."""
    if paren_depth != 0:
        if in_else_branch:
            return if_branch_exited, True, None
        return True, else_branch_exited, None
    return if_branch_exited, else_branch_exited, False


def _follow_goto_target(
    stripped: str,
    labels: Dict[str, int],
    visiting_labels: Set[str],
    lines: List[str],
) -> Optional[bool]:
    """Follow a GOTO target when resolvable; None when the line is not GOTO."""
    if not re.match(r"goto\s+", stripped):
        return None
    target = _parse_goto_target(stripped)
    if target is None or _is_goto_eof_target(target):
        return False
    if target in visiting_labels:
        return False
    label_index = labels.get(target)
    if label_index is None:
        return False
    visiting_labels.add(target)
    return _can_execution_reach_eof(
        lines,
        start_index=label_index,
        visiting_labels=visiting_labels,
    )


@dataclass
class _ReachabilityScanState:  # pylint: disable=too-many-instance-attributes
    """Mutable state while scanning for paths that reach EOF."""

    reachable: bool = True
    paren_depth: int = 0
    if_branch_exited: bool = False
    else_branch_exited: bool = False
    in_else_branch: bool = False
    lines: List[str] = field(default_factory=list)
    labels: Dict[str, int] = field(default_factory=dict)
    visiting_labels: Set[str] = field(default_factory=set)


def _update_reachability_for_line(
    state: _ReachabilityScanState,
    stripped: str,
    previous_depth: int,
) -> None:
    """Update branch-tracking state for the current line."""
    state.paren_depth = _update_paren_depth(stripped, state.paren_depth)
    if state.paren_depth > previous_depth and re.search(
        r"\bif\b", stripped, re.IGNORECASE
    ):
        state.if_branch_exited = False
        state.else_branch_exited = False
        state.in_else_branch = False
    elif _is_else_transition(stripped):
        state.in_else_branch = True


def _scan_line_for_reachability(
    state: _ReachabilityScanState,
    stripped: str,
    index: int,
) -> Optional[bool]:
    """Process one line; return True/False to stop, or None to continue scanning."""
    if _is_blank_or_comment(stripped):
        return None

    if stripped.startswith(":") and not stripped.startswith("::"):
        state.reachable = True
        return None

    previous_depth = state.paren_depth
    _update_reachability_for_line(state, stripped, previous_depth)

    if re.match(r"exit\b", stripped):
        state.if_branch_exited, state.else_branch_exited, stop_result = (
            _apply_exit_to_branch_state(
                state.paren_depth,
                state.in_else_branch,
                state.if_branch_exited,
                state.else_branch_exited,
            )
        )
        return stop_result

    if _if_else_block_exits_reach_eof(
        previous_depth,
        state.paren_depth,
        (state.if_branch_exited, state.else_branch_exited),
        state.lines,
        index,
    ):
        return False

    if state.paren_depth == 0:
        return _follow_goto_target(
            stripped, state.labels, state.visiting_labels, state.lines
        )

    return None


def _can_execution_reach_eof(
    lines: List[str],
    start_index: int = 0,
    visiting_labels: Optional[Set[str]] = None,
) -> bool:
    """Determine if execution from start_index can reach EOF without EXIT."""
    if visiting_labels is None:
        visiting_labels = set()

    labels = _build_label_index(lines)
    state = _ReachabilityScanState(
        lines=lines,
        labels=labels,
        visiting_labels=visiting_labels,
    )

    for index in range(start_index, len(lines)):
        stripped = lines[index].strip().lower()
        scan_result = _scan_line_for_reachability(state, stripped, index)
        if scan_result is not None:
            return scan_result

    return state.reachable


def _check_nested_paren_mismatch(lines: List[str]) -> List[LintIssue]:
    """Check for mismatched IF/FOR parenthesis blocks (E001)."""
    issues: List[LintIssue] = []
    depth = 0
    last_open_line = 0

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if _is_blank_or_comment(stripped):
            continue

        previous_depth = depth
        depth = _update_paren_depth(stripped, depth)
        if depth > previous_depth:
            last_open_line = i

        if depth < 0:
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["E001"],
                    context="Unmatched closing parenthesis in IF/FOR block",
                )
            )
            depth = 0

    if depth > 0:
        issues.append(
            LintIssue(
                line_number=last_open_line or len(lines),
                rule=RULES["E001"],
                context=f"{depth} unclosed parenthesis block(s) in IF/FOR structure",
            )
        )

    return issues


def _check_unreachable_code(lines: List[str]) -> List[LintIssue]:
    """Check for unreachable code after EXIT or GOTO statements."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if re.match(r"(exit\s|goto\s)", stripped):
            # Find unreachable code after this EXIT/GOTO
            unreachable_line = _find_truly_unreachable_code(lines, i)
            if unreachable_line is not None:
                command = stripped.split()[0].upper()
                issues.append(
                    LintIssue(
                        line_number=unreachable_line + 1,
                        rule=RULES["E008"],
                        context=(
                            f"Code after {command} on line {i + 1} will never execute"
                        ),
                    )
                )

    return issues


def _find_truly_unreachable_code(
    lines: List[str], exit_line_index: int
) -> Optional[int]:
    """Find truly unreachable code, considering batch file control flow properly."""
    exit_paren_depth = _calculate_exit_paren_depth(lines, exit_line_index)
    return _scan_for_unreachable_code(lines, exit_line_index, exit_paren_depth)


def _calculate_exit_paren_depth(lines: List[str], exit_line_index: int) -> int:
    """Calculate the parentheses depth at the EXIT statement."""
    current_paren_depth = 0

    for i in range(exit_line_index + 1):
        line = lines[i].strip().lower()
        current_paren_depth = _update_paren_depth(line, current_paren_depth)

    return current_paren_depth


def _scan_for_unreachable_code(
    lines: List[str], exit_line_index: int, exit_paren_depth: int
) -> Optional[int]:
    """Scan forward from EXIT to find unreachable code."""
    current_paren_depth = exit_paren_depth

    for j in range(exit_line_index + 1, len(lines)):
        line = lines[j].strip().lower()

        # Skip empty lines and comments
        if _is_blank_or_comment(line):
            continue

        # Check if this line makes code reachable again
        if _line_makes_code_reachable(line):
            return None

        # Update parentheses depth
        current_paren_depth = _update_paren_depth(line, current_paren_depth)

        # EXIT/GOTO inside a block: code after the block closes is reachable.
        if exit_paren_depth > 0 and current_paren_depth < exit_paren_depth:
            return None

        # Handle closing parentheses specially
        if line == ")" or line.startswith(")"):
            if current_paren_depth < exit_paren_depth:
                return None
            continue

        # Skip certain structural elements
        if line in {"endlocal", "setlocal"}:
            continue

        # Check for executable code
        if _is_truly_executable_command(line):
            if exit_paren_depth == 0 or current_paren_depth >= exit_paren_depth:
                return j
            return None

    return None


def _line_makes_code_reachable(line: str) -> bool:
    """Check if a line makes code reachable again."""
    # Labels make code reachable
    if line.startswith(":") and not line.startswith("::"):
        return True

    # ') else' creates a new reachable path
    if re.match(r"^\)\s*else\b", line):
        return True

    return False


def _is_truly_executable_command(line: str) -> bool:
    """Check if a line is truly executable code (not structural)."""
    line = line.strip().lower()

    # Skip empty, comments, labels
    if _is_blank_or_comment(line) or line.startswith(":"):
        return False

    # Skip pure structural elements
    if line in {")", "endlocal", "setlocal"}:
        return False

    # Skip ') else' patterns
    if re.match(r"^\)\s*(else\b.*)?$", line):
        return False

    # Skip closing parenthesis with redirection operators
    # These are part of block I/O redirection, not executable code
    # Examples: ) >>file.txt 2>&1, ) >output.log, ) 2>nul
    if re.match(r"^\)\s*(?:>>?|<|[12]>&?[12]?)", line):
        return False

    return True
