"""Performance issue line checks (P-prefix rules)."""

from functools import lru_cache
import re
from typing import (
    FrozenSet,
    Iterator,
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
    _split_pipe_stages,
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
    uses_delayed_vars: bool,
    has_literal_exclamations: bool,
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


_PATH_REMOVING_COMMANDS = frozenset(
    {"del", "erase", "rd", "rmdir", "move", "ren", "rename"}
)
# A redirection with its target: ``>nul``, ``2>&1``, ``>> "a b.log"``. A
# handle digit counts only at the start of a word, as in ``2>nul``.
_REDIRECT_RE = re.compile(
    r'(?:(?<!\S)\d)?(?:>>?|<)(?:&\d|\s*(?:"[^"]*"|[^\s"<>|&()]*))'
)


def _split_arguments(text: str) -> List[str]:
    """Split on whitespace, commas, semicolons and equals signs outside quotes."""
    arguments: List[str] = []
    current: List[str] = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        if not quoted and (char.isspace() or char in ",;="):
            if current:
                arguments.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        arguments.append("".join(current))
    return arguments


# One word, split as ``_split_tokens`` splits: whitespace outside quotes.
_WORD_RE = re.compile(r'(?:[^\s"`]|"[^"]*"?|`[^`]*`?)+')
# A command that starts with none of these words is not split into words.
_PREFIX_WORD_RE = re.compile(r"\s*[(@]*(?:call|cmd|cmd\.exe|for)(?:\s|$)")


def _after_cmd_switches(words: Iterator[re.Match[str]]) -> bool:
    """Consume ``cmd``'s switches; True when ``/c`` or ``/k`` was among them."""
    for match in words:
        switch = match.group()
        if not switch.startswith("/"):
            return False
        if switch in ("/c", "/k"):
            return True
    return False


def _after_for_do(words: Iterator[re.Match[str]]) -> bool:
    """Consume FOR up to its DO, the first ``do`` after a ``)``; True if found."""
    previous = ""
    for match in words:
        word = match.group()
        if word == "do" and previous.endswith(")"):
            return True
        previous = word
    return False


def _command_after_prefixes(text: str) -> str:
    """Return the command that ``call``, ``cmd /c`` or ``for ... do`` runs.

    A leading ``@`` only hides the command's echo, so ``@del`` is ``del``.
    The words are read one at a time, so a long line is not split whole.
    """
    if _PREFIX_WORD_RE.match(text) is None:
        return text.lstrip().lstrip("(@")
    words = _WORD_RE.finditer(text)
    for match in words:
        word = match.group().lstrip("(@")
        if word == "call":
            continue
        if word in ("cmd", "cmd.exe"):
            if not _after_cmd_switches(words):
                return ""
        elif word == "for":
            if not _after_for_do(words):
                return ""
        else:
            return text[match.start() :].lstrip("(@")
    return ""


_ELSE_REST_RE = re.compile(r"\s*else\b(.*)", re.IGNORECASE | re.DOTALL)
_ELSE_AFTER_RE = re.compile(r"\s*else\b", re.IGNORECASE)


def _paren_events(text: str, chars: str = "()") -> Iterator[tuple[int, str]]:
    """Yield the position of each ``(`` and ``)`` (or ``chars``) outside quotes.

    A caret escapes the next character, so ``^)`` is text, while ``^^)`` is
    an escaped caret followed by a ``)``.
    """
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            quoted = not quoted
        elif quoted:
            pass
        elif char == "^":
            index += 1
        elif char in chars:
            yield index, char
        index += 1


def _split_at_group_close(text: str) -> tuple[str, str]:
    """Split ``text`` at the first ``)`` that closes no ``(`` opened in it.

    That ``)`` is read as closing the group the command runs in. A ``)``
    inside quotes or escaped by a caret is text (``_paren_events``), and so
    is one that closes a ``(`` of the path, as in ``rd obj(x64)``.
    """
    depth = 0
    for index, char in _paren_events(text):
        if char == "(":
            depth += 1
        elif depth == 0:
            return text[:index], text[index + 1 :]
        else:
            depth -= 1
    return text, ""


def _removed_paths(segment: str) -> List[str]:
    """Return the paths one command segment removes, in lower case.

    DEL, ERASE, RD and RMDIR remove every path they name. MOVE removes its
    sources, not the destination it moves them into. REN and RENAME remove
    their first path and leave the new name in that path's folder. The
    command can follow ``call``, ``cmd /c`` (or ``/k``), ``for ... do`` and
    ``@``. A redirection is not a path, even when glued to one, as in
    ``"%F%">nul``. A comma, semicolon or equals sign separates two paths, as
    in ``del a.txt,b.txt``. The command ends at the ``)`` of its group
    (``_split_at_group_close``). The command of the ELSE after that ``)``
    counts too, as in ``(echo a) else (del b.txt)``, but not an IF that the
    ELSE runs, nor a second ELSE after it.
    """
    text = _command_after_prefixes(_REDIRECT_RE.sub(" ", segment.lower()))
    command, rest = _split_at_group_close(text)
    paths = _command_removed_paths(_split_arguments(command))
    match = _ELSE_REST_RE.match(rest)
    if match is not None:
        else_text = _command_after_prefixes(match.group(1))
        else_command, _ = _split_at_group_close(else_text)
        paths.extend(_command_removed_paths(_split_arguments(else_command)))
    return paths


def _command_removed_paths(tokens: List[str]) -> List[str]:
    """Return the paths a DEL, ERASE, RD, RMDIR, MOVE or REN command removes."""
    if not tokens:
        return []
    command = tokens[0].split("/")[0]
    if command not in _PATH_REMOVING_COMMANDS:
        return []
    paths = [
        token.strip('"').rstrip("\\/")
        for token in tokens[1:]
        if not token.startswith("/")
    ]
    if command in ("ren", "rename"):
        return paths[:1]
    if command == "move" and len(paths) > 1:
        return paths[:-1]
    return paths


# typeshed types the lru_cache wrapper as Any under disallow_any_expr.
@lru_cache(maxsize=1024)  # type: ignore[misc]
def _line_removed_paths(line: str) -> FrozenSet[str]:
    """Return the paths every command on a line removes (``_removed_paths``).

    A command after a pipe runs too, as in ``echo y| del a.txt``. P001 and
    P017 ask about the same line once per nearby check, so the answer is
    cached; the cache is bounded.
    """
    if _is_comment_line(line):
        return frozenset()
    return frozenset(
        path
        for stage in _split_pipe_stages(line)
        for segment in _command_segments(stage)
        for path in _removed_paths(segment)
    )


def _line_removes(line: str, operand: str) -> bool:
    """True when a command on ``line`` removes ``operand``."""
    # A line without the operand's text cannot remove it.
    return operand in line.lower() and operand in _line_removed_paths(line)


# An IF EXIST and its operand, read as ``_exist_operand_at`` reads them.
_EXIST_CHECK_RE = re.compile(r'if\s+exist\s+(?:"([^"]+)"|(\S+))\s*')
_COMMAND_LEAD_RE = re.compile(r"[\s@]*")


def _then_groups_at(lowered: str, operand: str) -> FrozenSet[int]:
    """Return where the ``(`` after each IF EXIST of ``operand`` opens.

    An IF EXIST counts where a command starts: at the start of the line,
    after ``&``, ``|``, ``(`` or an ELSE, and after ``@``.
    """
    if operand not in lowered:
        return frozenset()
    starts = [0]
    for index, char in _paren_events(lowered, "()&|"):
        if char != ")":
            starts.append(index + 1)
            continue
        else_word = _ELSE_AFTER_RE.match(lowered, index + 1)
        if else_word is not None:
            starts.append(else_word.end())
    found: set[int] = set()
    for start in starts:
        lead = _COMMAND_LEAD_RE.match(lowered, start)
        check = _EXIST_CHECK_RE.match(lowered, start if lead is None else lead.end())
        if check is None or lowered[check.end() : check.end() + 1] != "(":
            continue
        path = _match_text(check, 1) or _match_text(check, 2)
        if path.rstrip("\\/") == operand:
            found.add(check.end())
    return frozenset(found)


# typeshed types the lru_cache wrapper as Any under disallow_any_expr.
@lru_cache(maxsize=1024)  # type: ignore[misc]
def _walk_exist_else(
    lowered: str, operand: str, groups: tuple[str, ...], else_line: bool
) -> tuple[int, tuple[str, ...], bool]:
    """Walk one line for ``_outside_exist_else``.

    ``groups`` holds the kind of each ``(`` still open: ``"then"`` for the
    ``(...)`` an IF EXIST of ``operand`` runs, ``"else"`` for one inside its
    ELSE, ``""`` for any other. Return where the line is cut, the groups it
    leaves open, and whether the next line is an ELSE command. Only groups
    from the lowest ``"then"`` or ``"else"`` up are kept, since the ones
    below it never close before it does.
    """
    cut = 0 if else_line or "else" in groups else len(lowered)
    then_at = _then_groups_at(lowered, operand) if cut else frozenset()
    if not groups and not else_line and not then_at:
        return cut, (), False
    stack = list(groups)
    next_else = False
    for index, char in _paren_events(lowered):
        if char == "(":
            stack.append("else" if index >= cut else "then" if index in then_at else "")
        elif stack and stack.pop() == "then" and index < cut:
            match = _ELSE_AFTER_RE.match(lowered, index + 1)
            if match is not None:
                cut = index + 1
                next_else = not lowered[match.end() :].strip()
    lowest = next((at for at, kind in enumerate(stack) if kind), len(stack))
    return cut, tuple(stack[lowest:]), next_else


def _outside_exist_else(
    lines: List[str], first: int, last: int, operand: str
) -> List[str]:
    """Return lines ``first`` up to ``last``, each cut before an ELSE of IF EXIST.

    That ELSE is the one after the ``(...)`` an IF EXIST of ``operand`` runs.
    A line is cut where that ELSE starts, and the lines its ``(`` keeps open
    are left out. A line that ends in that ELSE leaves out the next line,
    as ``_else_still_open`` reads it. Comment lines are left out too.
    """
    kept: List[str] = []
    groups: tuple[str, ...] = ()
    else_line = False
    for line in lines[first:last]:
        if _is_comment_line(line):
            kept.append("")
            continue
        lowered = line.lower()
        cut, groups, else_line = _walk_exist_else(lowered, operand, groups, else_line)
        kept.append(lowered[:cut])
    return kept


def _path_removed_between(
    lines: List[str], first: int, last: int, operand: str
) -> bool:
    """True when a line from ``first`` up to ``last`` removes ``operand``.

    The command on the line of the first check runs after that check, so it
    counts. A later IF EXIST then tests whether the removal worked. The ELSE
    of an IF EXIST of ``operand`` runs only when the path is absent, so a
    removal there does not count (``_outside_exist_else``), on any line.
    """
    if not any(_line_removes(line, operand) for line in lines[first:last]):
        return False
    return any(
        _line_removes(text, operand)
        for text in _outside_exist_else(lines, first, last, operand)
    )


def _nearby_same_exist_count(lines: List[str], line_number: int, operand: str) -> int:
    """Count other IF EXIST lines in a five-line window with this operand.

    A check with a removal of the path between the two lines is not a
    repeat (``_path_removed_between``).
    """
    start = max(0, line_number - 5)
    end = min(len(lines), line_number + 5)
    count = 0
    current = line_number - 1
    for index in range(start, end):
        if index == current:
            continue
        other = _if_exist_operand(lines[index].strip().lower())
        if other != operand:
            continue
        first, last = min(index, current), max(index, current)
        if not _path_removed_between(lines, first, last, operand):
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
    for _, char in _paren_events(text):
        if char == "(":
            depth += 1
            opened = True
        elif opened:
            depth -= 1
            if depth <= 0:
                return depth, opened, True
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
    ``"file one.txt"`` is not ``"file two.txt"``. A removal of ``filename``
    from line ``start`` on (``_path_removed_between``) makes the later check
    test its result.
    """
    if _else_between(lines, start, end) or _else_still_open(lines, start, end):
        return False
    lowered = lines[end].strip().lower()
    if not filename or _if_exist_operand(lowered) != filename:
        return False
    if _path_removed_between(lines, start, end, filename):
        return False
    else_word = _ELSE_WORD_RE.search(lowered)
    if else_word is None:
        return True
    exist_at = lowered.find("if")
    return exist_at < 0 or else_word.start() >= exist_at
