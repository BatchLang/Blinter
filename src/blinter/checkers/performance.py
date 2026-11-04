"""Performance issue line checks (P-prefix rules)."""

import re
from typing import (
    List,
    Optional,
)

from blinter.checkers.globals.label_flow import _for_do_body
from blinter.models import LintIssue
from blinter.parsing.context import (
    _command_segments,
    _is_comment_line,
    _is_endlocal_command,
    _is_setlocal_command,
)
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
    if (
        not _is_comment_line(stripped)
        and not _delayed_expansion_active_at_line(_lines, line_num)
        and re.search(r"![^!]+!", stripped)
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


_SET_ASSIGN_RE = re.compile(
    r'set\s+"?([A-Za-z_][\w]*)=\s*"?([^"\r\n]*)',
    re.IGNORECASE,
)
_NUL_REDIRECT_RE = re.compile(r">\s*nul\b")
_IF_EXIST_QUOTED_RE = re.compile(r'^if\s+exist\s+"([^"]+)"')
_IF_EXIST_BARE_RE = re.compile(r"^if\s+exist\s+(\S+)")
_ELSE_IF_EXIST_RE = re.compile(
    r"(?:^|[)&|])\s*else\s+if\s+exist\b",
    re.IGNORECASE,
)
_ELSE_WORD_RE = re.compile(r"\belse\b")


def _match_text(match: re.Match[str], index: int) -> str:
    """Return one regex capture as ``str``."""
    captured = match.group(index)
    return "" if captured is None else str(captured)


def _value_reads_assigned_name(name: str, value: str) -> bool:
    """True when the assignment reads the same variable back."""
    key = name.lower()
    return (
        f"%{key}%" in value
        or f"!{key}!" in value
        or f"%{key}:" in value
        or f"!{key}:" in value
    )


def _same_metavar_twice(value: str) -> bool:
    """True when one FOR metavariable is written twice, as in ``%%a%%a``."""
    seen: set[str] = set()
    index = 0
    while index < len(value) - 2:
        if value[index : index + 2] == "%%" and value[index + 2].isalpha():
            token = value[index : index + 3]
            if token in seen:
                return True
            seen.add(token)
            index += 3
            continue
        index += 1
    return False


def _segment_concatenates(segment: str) -> bool:
    """True when one executed command in ``segment`` appends to its variable."""
    if _is_comment_line(segment):
        return False
    if re.match(r"\s*@?\(?\s*set\s+/a\b", segment, re.IGNORECASE):
        return False
    match = _SET_ASSIGN_RE.search(segment)
    if match is None:
        return False
    name = _match_text(match, 1)
    value = _match_text(match, 2)
    return _value_reads_assigned_name(name, value) or _same_metavar_twice(value)


def _set_concatenates_in_loop(stripped: str) -> bool:
    """True when SET appends to its own value inside a loop.

    ``set VALUE=%%a`` stores the current token. Concatenation reads that
    variable again (``!result!`` / ``%result%``) or repeats one metavariable.
    ``echo set result=!result!`` and ``if exist echo.txt set VALUE=%%a`` are not.
    """
    text = _for_do_body(stripped) if stripped.startswith("for ") else stripped
    return any(_segment_concatenates(segment) for segment in _command_segments(text))


def _visible_redirect_text(text: str) -> str:
    """Drop double-quoted spans and caret escapes, leaving real redirects."""
    parts: List[str] = []
    quoted = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if quoted:
            if char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            index += 1
            continue
        if char == "^" and index + 1 < length:
            index += 2
            continue
        parts.append(char)
        index += 1
    return "".join(parts)


def _unescaped_nul_redirect(text: str) -> bool:
    """True when ``text`` redirects to NUL outside quotes and caret escapes."""
    return _NUL_REDIRECT_RE.search(_visible_redirect_text(text)) is not None


def _loop_body_redirects_to_nul(stripped: str) -> bool:
    """True for a NUL redirect that runs with the loop body.

    A redirect in ``FOR /F``'s ``IN`` command, including ``2^>nul``, belongs
    to that one child process. A redirect after ``DO`` runs on each iteration.
    """
    target = _for_do_body(stripped) if stripped.startswith("for ") else stripped
    return _unescaped_nul_redirect(target)


def _exist_operand_at(command: str) -> str:
    """Return the operand of an ``IF EXIST`` command, without quotes."""
    quoted = _IF_EXIST_QUOTED_RE.search(command)
    if quoted is not None:
        return _match_text(quoted, 1).rstrip("\\/")
    bare = _IF_EXIST_BARE_RE.search(command)
    if bare is None:
        return ""
    return _match_text(bare, 1).rstrip("\\/")


def _if_exist_operand(stripped: str) -> str:
    """Return the path an IF EXIST line checks, or empty for any other line."""
    if stripped.startswith("if exist"):
        return _exist_operand_at(stripped)
    else_form = _ELSE_IF_EXIST_RE.search(stripped)
    if else_form is None:
        return ""
    command_at = stripped.find("if", else_form.start())
    if command_at < 0:
        return ""
    return _exist_operand_at(stripped[command_at:])


def _nearby_same_exist_count(lines: List[str], line_number: int, operand: str) -> int:
    """Count other IF EXIST lines in a five-line window with this operand."""
    start = max(0, line_number - 5)
    end = min(len(lines), line_number + 5)
    count = 0
    current = line_number - 1
    for index in range(start, end):
        if index == current:
            continue
        other = _if_exist_operand(lines[index].strip().lower())
        if other == operand:
            count += 1
    return count


def _repeated_exist_issue(
    lines: List[str], line_number: int, stripped: str
) -> Optional[LintIssue]:
    """P017 when the same path is checked often enough to be worth storing."""
    operand = _if_exist_operand(stripped)
    if not operand or not stripped.startswith("if exist"):
        return None
    if _nearby_same_exist_count(lines, line_number, operand) < 2:
        return None
    return LintIssue(
        line_number,
        RULES["P017"],
        context=f"File '{operand}' checked multiple times",
    )


def _exist_filename(stripped: str) -> str:
    """Return the IF EXIST operand, including spaces inside quotes."""
    return _if_exist_operand(stripped)


_ELSE_COMMAND_RE = re.compile(r"(?:^|\))\s*else\b", re.IGNORECASE)


def _else_between(lines: List[str], start: int, end: int) -> bool:
    """True when an ELSE command between two checks opens the other branch."""
    for index in range(start + 1, end):
        if _ELSE_COMMAND_RE.search(lines[index].strip()):
            return True
    return False


def _feed_parens(text: str, depth: int, opened: bool) -> tuple[int, bool, bool]:
    """Walk ``text`` and report whether an open ELSE block closes."""
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
            opened = True
        elif char == ")" and opened:
            depth -= 1
            if depth <= 0:
                return depth, opened, True
        elif char == "^" and index + 1 < len(text):
            index += 2
            continue
        index += 1
    return depth, opened, False


def _else_still_open(lines: List[str], start: int, end: int) -> bool:
    """True when ``end`` is still inside an ELSE opened on line ``start``."""
    first = lines[start].strip()
    match = _ELSE_COMMAND_RE.search(first)
    if match is None:
        return False
    depth, opened, closed = _feed_parens(first[match.end() :], 0, False)
    if closed:
        return False
    if not opened:
        return end == start + 1
    for index in range(start + 1, end):
        depth, opened, closed = _feed_parens(lines[index], depth, opened)
        if closed:
            return False
    return depth > 0


def _line_repeats_exist(lines: List[str], start: int, end: int, filename: str) -> bool:
    """True when line ``end`` checks ``filename`` again on the same branch.

    ``else if exist`` is the other branch of the earlier IF, so it is not a
    second execution of that check. An ``ELSE`` on a line between the checks
    opens that other branch too. Quoted paths keep their spaces, so
    ``"file one.txt"`` is not ``"file two.txt"``.
    """
    if _else_between(lines, start, end) or _else_still_open(lines, start, end):
        return False
    lowered = lines[end].strip().lower()
    if not filename or _if_exist_operand(lowered) != filename:
        return False
    else_word = _ELSE_WORD_RE.search(lowered)
    if else_word is None:
        return True
    exist_at = lowered.find("if")
    return exist_at < 0 or else_word.start() >= exist_at
