"""Global style rules: indentation, pause, duplication, and casing."""

from collections import defaultdict
import re
from typing import (
    Dict,
    List,
    Optional,
    Tuple,
)

from blinter.checkers.cmd_extended import _is_caret_escaped
from blinter.constants import LARGE_FILE_LINE_THRESHOLD
from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import _is_blank_or_comment, _is_comment_line
from blinter.patterns import COMMAND_CASING_KEYWORDS
from blinter.rules.registry import RULES

# REM or :: at the start of a command segment, after optional ``(`` groups.
_INLINE_REM_RE = re.compile(
    r"[\s(]*@?(?:rem(?:\s|$)|::)",
    re.IGNORECASE,
)
# Text immediately before a quote that is the command string of cmd /c or /k.
_CMD_CK_BEFORE_QUOTE_RE = re.compile(
    r"(?:^|[&|(])\s*@?(?:\S*[/\\])?cmd(?:\.exe)?(?:\s+/\S+)*\s+/[ck]\b\s*$",
    re.IGNORECASE,
)

# What phase 1 expands before phase 2 reads quotes: ``%%``, an argument such as
# ``%1`` or ``%~dp0``, or a ``%name%`` span, which may hold ``:`` edits.
_ARGUMENT_TOKEN = r"%%|%~[^%\s]*?[0-9*]|%[0-9*]"
_NAME_TOKEN = r"%[^%\r\n]+%"
_PERCENT_TOKEN_RE = re.compile(f"{_ARGUMENT_TOKEN}|{_NAME_TOKEN}")
# The search text of ``%name:search=replace%`` may also hold ``%`` after its
# first character; ``%p:%`` is the variable ``p:``.
_SEARCH_TOKEN = r"%[^\s%:&|<>][^%:&|<>\r\n]*:[^%~=\r\n][^=\r\n]*=[^%\r\n]*%"
_SEARCH_TOKEN_RE = re.compile(f"{_ARGUMENT_TOKEN}|{_SEARCH_TOKEN}|{_NAME_TOKEN}")
# These end a percent scan. A quote does not: ``%"=Y%`` is one token.
_STRAY_PERCENT_NAME_CHARS = frozenset("&|<>")

# One compiled pattern per keyword. A single separator character plus ``\s*``
# would rescan a space run from every space in it, so the keyword follows the
# separator directly: a space before the keyword is a separator already.
_COMMAND_CASE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = tuple(
    (
        keyword,
        re.compile(rf"(^|[\s&|(])({re.escape(keyword)})\b", re.IGNORECASE),
    )
    for keyword in sorted(COMMAND_CASING_KEYWORDS)
)
_COMMAND_CASE_RE = dict(_COMMAND_CASE_PATTERNS)
# ENABLEDELAYEDEXPANSION is an argument of SETLOCAL, so S003 counts it anywhere.
_ARGUMENT_CASE_KEYWORDS = ("enabledelayedexpansion",)
_WORD_RE = re.compile(r"\w+")
# ``<file`` or ``2<file``, written with or without a space before the file.
_INPUT_REDIRECT_RE = re.compile(r"\d?<")
# A line such as ``^^^& SET a=1`` after one that ends in ``^`` (_collect_cmd_cases).
_LEADING_CARET_SEPARATOR_RE = re.compile(r"(?:\^\^)*\^[&|]")
# START switches that take a value, such as ``/d c:\x``.
_START_VALUE_SWITCHES = frozenset({"/d", "/node", "/affinity"})
_CMD_NAMES = ("cmd", "cmd.exe", "%comspec%", "!comspec!")
# Prefixes that may have a switch glued to them, as in ``start/b``.
_GLUED_PREFIXES = frozenset({"if", "call", "start", '""', *_CMD_NAMES})
# IF conditions with one operand; any other condition compares two.
_IF_UNARY = frozenset({"exist", "defined", "errorlevel", "cmdextversion"})
_IF_OPERATORS = frozenset({"==", "equ", "neq", "lss", "leq", "gtr", "geq"})
# ``_depth_after_separator`` records ``_BLOCK - depth`` for the ``(`` of a block.
_BLOCK = -1
_Parens = Tuple[List[Optional[int]], List[int]]


def _check_redundant_operations(lines: List[str]) -> List[LintIssue]:
    """Check for redundant file operations."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        # Look for repeated IF EXIST checks on the same file
        exist_match = re.search(r"if\s+exist\s+(\S+)", stripped)
        if exist_match:
            filename_result = exist_match.group(1)
            if filename_result is not None:
                filename: str = filename_result
                # Check subsequent lines for same file
                for j in range(i + 1, min(i + 5, len(lines))):
                    next_stripped = lines[j].strip().lower()
                    if f"if exist {filename}" in next_stripped:
                        issues.append(
                            LintIssue(
                                line_number=j + 1,
                                rule=RULES["P001"],
                                context=f"Redundant existence check for {filename} "
                                f"(first check on line {i + 1})",
                            )
                        )
                        break

    return issues


def _duplication_report_threshold(script_size: int) -> int:
    """Return minimum repeated-command count before flagging duplication."""
    if script_size < 100:
        return 3
    if script_size < 500:
        return 5
    if script_size < 2000:
        return 10
    return 20


def _check_code_duplication(lines: List[str]) -> List[LintIssue]:
    """Check for code duplication that could be refactored."""
    issues: List[LintIssue] = []

    # Very large scripts: skip expensive similarity scan (dominates lint time).
    if len(lines) > LARGE_FILE_LINE_THRESHOLD:
        return issues

    # Simple heuristic: look for repeated command patterns
    command_blocks: Dict[str, List[int]] = defaultdict(list)

    # Commands that are commonly repeated for user interaction and don't need refactoring
    ui_commands = [
        r"timeout\s+/t\s+\d+",  # timeout commands
        r"pause\s*$",  # pause commands
        r"echo\s+\.?\s*$",  # echo blank lines
        r"^\s*echo\s+",  # echo commands in general
        r"^\s*if\s+",  # if statements
        r"^\s*set\s+",  # set commands
        r"^\s*call\s+",  # call commands
        r"^\s*goto\s+",  # goto commands
        r"^\s*for\s+",  # for loops
    ]

    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if (
            stripped
            and not stripped.startswith(":")
            and not _is_blank_or_comment(stripped)
        ):
            # Skip common user interface commands that are legitimately repeated
            is_ui_command = any(re.search(pattern, stripped) for pattern in ui_commands)
            if is_ui_command:
                continue

            # Normalize the command for comparison
            normalized = re.sub(r"\S+\.(txt|log|bat|cmd)", "FILE", stripped)
            normalized = re.sub(r"%\w+%", "VAR", normalized)

            if (
                len(normalized) > 40
            ):  # Only consider substantial commands (increased from 20)
                command_blocks[normalized].append(i + 1)

    script_size = len(lines)
    threshold = _duplication_report_threshold(script_size)

    for _normalized_cmd, line_numbers in command_blocks.items():
        if len(line_numbers) >= threshold:  # Found threshold+ similar commands
            # Only flag if occurrences are close together (within 100 lines)
            # This catches actual duplication that should be refactored
            for i in range(len(line_numbers) - 1):
                if line_numbers[i + 1] - line_numbers[i] < 100:
                    # Found close duplicates, flag this group
                    issues.append(
                        LintIssue(
                            line_number=line_numbers[i + 1],
                            rule=RULES["P002"],
                            context=f"Similar command pattern repeated "
                            f"(also on lines {line_numbers[i]})",
                        )
                    )

    return issues


def _is_interactive_set_prompt(line: str) -> bool:
    """Return True when set /p prompts the user (not file input redirection)."""
    if not re.search(r"set\s+/p\s+", line, re.IGNORECASE):
        return False
    return not re.search(r"set\s+/p\s+\S+\s*=<", line, re.IGNORECASE)


def _check_missing_pause(lines: List[str]) -> List[LintIssue]:
    """Check for missing PAUSE in interactive scripts (W014)."""
    issues: List[LintIssue] = []

    has_user_input = any(
        _is_interactive_set_prompt(line) or re.search(r"choice\s+", line, re.IGNORECASE)
        for line in lines
    )

    has_pause = any(
        re.search(r"\bpause\b", line, re.IGNORECASE)
        or re.search(r"\btimeout\s+/t\b", line, re.IGNORECASE)
        for line in lines
    )

    if has_user_input and not has_pause:
        # Find an appropriate line number (near the end)
        for i in range(len(lines) - 1, -1, -1):
            if not _is_blank_or_comment(lines[i]):
                issues.append(
                    LintIssue(
                        line_number=i + 1,
                        rule=RULES["W014"],
                        context="Interactive script should include PAUSE to prevent window closing",
                    )
                )
                break

    return issues


def _collect_indented_lines(lines: List[str]) -> List[Tuple[int, str]]:
    """Collect all indented lines with their leading whitespace."""
    indented_lines = []
    for i, line in enumerate(lines, start=1):
        if line.startswith(("\t", " ")):
            leading_whitespace = ""
            for char in line:
                if char in ("\t", " "):
                    leading_whitespace += char
                else:
                    break
            indented_lines.append((i, leading_whitespace))
    return indented_lines


def _normalize_block_indent(whitespace: str) -> str:
    """Collapse tab + optional single space used before block commands.

    Professional batch files often indent IF/FOR bodies as tab then one space
    before the command (e.g. ``\\t SET ...``). That is not inconsistent mixing.
    """
    normalized: List[str] = []
    index = 0
    while index < len(whitespace):
        char = whitespace[index]
        if char == "\t":
            normalized.append("\t")
            index += 1
            if index < len(whitespace) and whitespace[index] == " ":
                index += 1
        else:
            normalized.append(char)
            index += 1
    return "".join(normalized)


def _leading_indent_uses_tabs(whitespace: str) -> bool:
    """Return True when normalized leading indent is tab-based."""
    return "\t" in _normalize_block_indent(whitespace)


def _leading_indent_uses_spaces(whitespace: str) -> bool:
    """Return True when normalized leading indent is space-based."""
    normalized = _normalize_block_indent(whitespace)
    return " " in normalized and "\t" not in normalized


def _find_single_line_mixed_indent(
    indented_lines: List[Tuple[int, str]],
) -> List[LintIssue]:
    """Check for mixed tabs and spaces within single lines."""
    issues: List[LintIssue] = []
    for line_num, whitespace in indented_lines:
        normalized = _normalize_block_indent(whitespace)
        if "\t" in normalized and " " in normalized:
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["S012"],
                    context="Line mixes tabs and spaces for indentation",
                )
            )
    return issues


def _find_file_mixed_indent(
    indented_lines: List[Tuple[int, str]],
) -> Optional[LintIssue]:
    """Check for inconsistent indentation across the entire file."""
    uses_tabs = False
    uses_spaces = False
    first_tab_line = 0
    first_space_line = 0

    for line_num, whitespace in indented_lines:
        if _leading_indent_uses_tabs(whitespace):
            uses_tabs = True
            if first_tab_line == 0:
                first_tab_line = line_num
        if _leading_indent_uses_spaces(whitespace):
            uses_spaces = True
            if first_space_line == 0:
                first_space_line = line_num

    if uses_tabs and uses_spaces:
        later_line = max(first_tab_line, first_space_line)
        if first_tab_line < first_space_line:
            context = (
                f"File mixes tabs (line {first_tab_line}) and spaces "
                f"(line {first_space_line}) for indentation"
            )
        else:
            context = (
                f"File mixes spaces (line {first_space_line}) and tabs "
                f"(line {first_tab_line}) for indentation"
            )
        return LintIssue(line_number=later_line, rule=RULES["S012"], context=context)
    return None


def _check_inconsistent_indentation(
    lines: List[str],
) -> List[LintIssue]:
    """Check for inconsistent indentation patterns across the file (S012)."""
    issues: List[LintIssue] = []

    indented_lines = _collect_indented_lines(lines)
    if len(indented_lines) < 2:
        return issues

    single_line_issues = _find_single_line_mixed_indent(indented_lines)
    issues.extend(single_line_issues)

    file_issue = _find_file_mixed_indent(indented_lines)
    if file_issue is not None:
        issues.append(file_issue)

    return issues


def _check_missing_header_doc(lines: List[str]) -> List[LintIssue]:
    """Check for missing file header documentation (S013)."""
    issues: List[LintIssue] = []

    # Skip short files (under 30 lines) - likely simple utilities
    # Increased threshold to be less aggressive
    if len(lines) < 30:
        return issues

    # Check first 15 lines for meaningful comments (expanded from 10)
    meaningful_comments = 0
    general_comments = 0

    for line in lines[:15]:
        stripped = line.strip().lower()
        if _is_comment_line(line) and len(stripped) > 6:
            general_comments += 1
            # Look for formal documentation indicators (strict)
            if any(
                keyword in stripped
                for keyword in [
                    "script:",
                    "purpose:",
                    "author:",
                    "date:",
                    "description:",
                    "usage:",
                    "function:",
                    "does:",
                    "created:",
                    "modified:",
                    "version:",
                ]
            ):
                meaningful_comments += 1
            # Also accept descriptive comments about what the script does
            elif any(
                keyword in stripped
                for keyword in [
                    "this script",
                    "this batch",
                    "this file",
                    "repairs",
                    "fixes",
                    "cleans",
                    "updates",
                    "installs",
                    "configures",
                    "enables",
                    "disables",
                    "resets",
                    "restores",
                    "optimizes",
                    "removes",
                    "deletes",
                    "creates",
                    "sets up",
                    "flushes",
                ]
            ):
                meaningful_comments += 1

    # Only flag if there are NO meaningful comments AND very few general comments
    # Increased threshold to 3 to be even more lenient
    if meaningful_comments == 0 and general_comments < 3:
        issues.append(
            LintIssue(
                line_number=1,
                rule=RULES["S013"],
                context="Script lacks header documentation (purpose, author, date)",
            )
        )

    return issues


def _closing_double_quote(text: str, start: int) -> Optional[int]:
    """Return the index of the next double quote, or None when unclosed."""
    index = text.find('"', start)
    if index < 0:
        return None
    return index


def _token_start(text: str, index: int) -> int:
    """Return where the token ending at or before index starts."""
    while index > 0 and text[index - 1].isspace():
        index -= 1
    while index > 0 and not text[index - 1].isspace():
        index -= 1
    return index


def _ends_like_cmd(text: str, start: int) -> bool:
    """Return True when the token at start ends with ``cmd`` or ``cmd.exe``."""
    end = start
    while end < len(text) and not text[end].isspace():
        end += 1
    token = text[start:end].casefold()
    return token.endswith("cmd") or token.endswith("cmd.exe")


def _is_cmd_command_string(text: str, quote: int, seen: Dict[int, bool]) -> bool:
    """Return True when the quote at ``quote`` opens a cmd /c or cmd /k string.

    A match ends with ``/c`` or ``/k`` and any whitespace before the quote.
    Before that come only switches, tokens of ``/`` and at least one more
    character, and the cmd token, which ends with ``cmd`` or ``cmd.exe``.
    The walk back over the switches stops at a ``/c`` or ``/k`` already seen
    on this line: if that quote matched, this one does too, and if not, only
    the tokens after it can hold the cmd token. So each token is walked once.
    The regex then starts on the token before that cmd token. ``^`` matches
    only the real start of the string, so a preceding ``&``, ``|`` or ``(``
    has to sit inside the window.
    ``seen`` maps the start of each ``/c`` or ``/k`` checked on the line to
    its result.
    """
    end = quote
    while end > 0 and text[end - 1].isspace():
        end -= 1
    if end < 3 or not text[end - 3].isspace() or text[end - 2] != "/":
        return False
    if text[end - 1].lower() not in ("c", "k"):
        return False
    switch = token = end - 2
    candidate: Optional[int] = None
    while True:
        if _ends_like_cmd(text, token):
            candidate = token
        if token != switch and token in seen:
            if seen[token]:
                seen[switch] = True
                return True
            break
        before = _token_start(text, token)
        if token == 0 or text[before] != "/" or text[before + 1].isspace():
            if token > 0 and _ends_like_cmd(text, before):
                candidate = before
            break
        token = before
    matched = candidate is not None and (
        _CMD_CK_BEFORE_QUOTE_RE.search(text, _token_start(text, candidate), quote)
        is not None
    )
    seen[switch] = matched
    return matched


def _percent_name_is_stray(name: str) -> bool:
    """Return True when ``name`` is a stray ``%``, not a variable name.

    A leading space or ``&``, ``|``, ``<`` or ``>`` ends the scan, as in
    ``set p=50% & dir c: & SET a=1 %``. A quote does not end it.
    """
    if not name or name[0].isspace():
        return True
    return bool(set(name) & _STRAY_PERCENT_NAME_CHARS)


def _percent_token_for_casing(match: re.Match[str]) -> str:
    """Return the token with the quotes phase 2 will not see removed.

    A finished ``%name%`` is expanded before quotes are read, so ``%"=Y%`` and
    the ``%%`` in ``%p:%%"=Y%`` do not hide a later command. ``%`` still closes
    the token, so the quote in ``%p:%"=Y%`` stays. Search text of
    ``%name:search=replace%`` is dropped and a replacement quote is kept.
    """
    token = match.group(0)
    name, colon, edit = token[1:-1].partition(":")
    if _percent_name_is_stray(name):
        return token
    if not colon:
        return token.replace('"', "'")
    if not edit.startswith("~") and "=" in edit:
        return edit.partition("=")[2]
    return token.replace('"', "'")


def _hide_expansion_quotes(text: str) -> str:
    """Blank quotes that percent expansion removes before phase 2.

    Phase 1 expands a defined ``name`` before phase 2 reads quotes, so with ``p``
    defined ``SET`` runs in ``set p=%p:"=% & SET q=1``. The name may hold
    spaces. A name that leads with one or holds ``&``, ``|``, ``<`` or ``>`` is
    almost never defined, so it is left alone: in
    ``set p=50% & dir c: & SET a=1 %`` cmd.exe removes ``% & dir c:`` as an
    undefined ``%name:`` and runs ``SET``. When ``name``
    is defined, the search text of ``%name:search=replace%`` never reaches
    phase 2, so ``SET`` does not run in ``set x=%p:" & SET y "=%``. A quote in
    the replacement reaches phase 2 wherever the search text matched, so it
    stays a quote. S003 reads the value as the search text alone, so a caret
    right before the token escapes that quote, as it does in cmd.exe when the
    value starts with the search text. An undefined ``name`` has only
    ``%name:`` removed. A quote inside a finished token is not a quote either.
    The search text may hold ``%`` after its first character, so with ``p``
    defined or not ``SET`` runs in ``set x=%p:a%"=Y% & SET q=1``. A quote in the
    replacement of such a token is not a quote.
    """
    # A search text needs an ``=`` with a ``%`` after it, so past the last such
    # ``=`` only the plain pattern can match. Trying the search-text pattern
    # there would rescan the rest of the line from every ``%``.
    last_equals = text.rfind("=", 0, text.rfind("%"))
    parts: List[str] = []
    index = 0
    while True:
        pattern = _SEARCH_TOKEN_RE if index < last_equals else _PERCENT_TOKEN_RE
        match = pattern.search(text, index)
        if match is None:
            break
        parts.append(text[index : match.start()])
        token = _percent_token_for_casing(match)
        if "%" in match.group(0)[1:-1]:
            # A search text holding ``%`` is almost never in the value, and with
            # ``name`` undefined cmd.exe removes its ``%`` up to the closing ``%``
            # as a variable, so the replacement does not reach phase 2.
            token = token.replace('"', "'")
        parts.append(token)
        index = match.end()
    parts.append(text[index:])
    return "".join(parts)


def _strip_casing_quotes(text: str) -> str:
    """Drop ordinary quotes and keep the text of a cmd /c or cmd /k string.

    A caret-escaped quote is literal, so ``set x=^" & SET y=2 & dir ^"`` still
    exposes ``SET``. An unescaped quote hides a PowerShell ``-Command`` string.
    An unclosed quote runs to the end of the line, so ``call :x "a & SET y=2``
    hides ``SET``. A quote inside a finished ``%name%`` token is not a quote.
    """
    text = _hide_expansion_quotes(text)
    parts: List[str] = []
    seen: Dict[int, bool] = {}
    index = 0
    length = len(text)
    while index < length:
        if text[index] != '"' or _is_caret_escaped(text, index):
            parts.append(text[index])
            index += 1
            continue
        closing = _closing_double_quote(text, index + 1)
        if closing is None:
            closing = length
        inner = text[index + 1 : closing]
        if _is_cmd_command_string(text, index, seen):
            logger.debug("Keeping cmd command string for S003: %s", inner)
            parts.append(inner)
        else:
            parts.append('""')
        index = closing + 1
    return "".join(parts)


def _drop_inline_comments(text: str) -> str:
    """Remove a REM or :: comment and the separator that introduces it.

    An even run of carets leaves ``&`` and ``|`` active (``^^&`` is a
    separator). An odd run escapes the separator, so the rest stays.
    """
    if _INLINE_REM_RE.match(text):
        logger.debug("Dropping leading REM/:: segment from S003 scan")
        return ""
    for index, char in enumerate(text):
        if char not in "&|" or _is_caret_escaped(text, index):
            continue
        if _INLINE_REM_RE.match(text[index + 1 :]):
            logger.debug("Dropping inline comment from S003 scan at %s", index)
            return text[:index]
    return text


def _casing_scan_text(stripped: str) -> str:
    """Return the text S003 should scan for command keywords."""
    return _drop_inline_comments(_strip_casing_quotes(stripped))


def _separator_level(code: str, pos: int) -> int:
    """Return how many command strings deep the separator at pos splits commands.

    Each parse of a line turns ``^^`` into ``^`` and ``^&`` into a plain ``&``.
    So ``&`` splits the line itself (level 0), ``^&`` splits the command string
    of a ``cmd /c`` on that line (level 1), and ``^^^&`` one nested in it (level 2).
    """
    carets = 0
    while pos - carets > 0 and code[pos - carets - 1] == "^":
        carets += 1
    level = 0
    while carets % 2:
        carets //= 2
        level += 1
    return level


def _expansion_end(code: str, pos: int) -> Optional[int]:
    """Return the end of the ``%...%`` expansion at pos, or None if there is none.

    The name rules are those of ``_hide_expansion_quotes``, so ``%my var%`` is
    one expansion and the ``%`` of ``50% & dir %`` is a stray one.
    """
    match = _PERCENT_TOKEN_RE.match(code, pos)
    if not match:
        return None
    token = match.group(0)
    if len(token) > 2 and token.endswith("%"):
        if _percent_name_is_stray(token[1:-1].partition(":")[0]):
            return None
    return match.end()


def _read_token(
    code: str, pos: int, separators: str, depth: int = 0, operand: bool = False
) -> Tuple[str, int, int]:
    """Return the token after pos, its start and its end.

    A token ends at whitespace or at a separator that splits commands within
    ``depth`` command strings. At a separator the token is empty and starts and
    ends there. An IF ``operand`` also ends at a comma or semicolon, and a
    ``%...%`` expansion in it is part of it, spaces included.
    """
    blanks = ",;" if operand else ""
    while pos < len(code) and (code[pos].isspace() or code[pos] in blanks):
        pos += 1
    start = pos
    while pos < len(code) and not (code[pos].isspace() or code[pos] in blanks):
        if code[pos] in separators and _separator_level(code, pos) <= depth:
            break
        end = _expansion_end(code, pos) if operand and code[pos] == "%" else None
        pos = end if end is not None else pos + 1
    return code[start:pos], start, pos


def _skip_if_condition(code: str, pos: int, depth: int) -> int:
    """Return the position after the IF condition that starts at pos.

    Parentheses are part of an operand here, as in ``if (a)==(b)``, and a comma
    or semicolon separates tokens, as in ``if exist,x``. A ``%...%`` expansion
    is one operand, as in ``if %my var% == x``: cmd.exe expands it first.
    """

    def _next(start: int) -> Tuple[str, int, int]:
        return _read_token(code, start, "&|", depth, operand=True)

    text, _, end = _next(pos)
    for flag in ("/i", "not"):
        if text.casefold() == flag:
            pos = end
            text, _, end = _next(pos)
    first = text.casefold()
    second, _, after_second = _next(end)
    if not first:
        return pos
    if first in _IF_UNARY or (first.endswith("==") and first != "=="):
        return after_second
    if "==" in first:
        return end
    if second.casefold() in _IF_OPERATORS:
        return _next(after_second)[2]
    return after_second  # ``a ==b``


def _skip_cmd_switches(code: str, pos: int, depth: int) -> Optional[int]:
    """Return the position after cmd's ``/c``, ``/k`` or ``/r``, or None without one.

    Switches may be glued, as in ``/d/c``, and so may the command, as in
    ``/cset``: no other switch of cmd starts with ``c``, ``k`` or ``r``, and
    ``/r`` is ``/c``.
    """
    while True:
        text, start, end = _read_token(code, pos, "&|()", depth=depth)
        if not text.startswith("/"):
            return None
        index = start
        for switch in text.split("/")[1:]:
            index += 1
            if switch[:1].casefold() in ("c", "k", "r"):
                return index + 1
            index += len(switch)
        pos = end


def _skip_start_options(code: str, pos: int, depth: int) -> int:
    """Return the position of the command START runs, after its title and switches."""
    while True:
        text, _, end = _read_token(code, pos, "&|()", depth=depth)
        if text != '""' and not text.startswith("/"):
            return pos
        pos = end
        if text.casefold() in _START_VALUE_SWITCHES:
            pos = _read_token(code, pos, "&|()", depth=depth)[2]


def _skip_for_f_options(code: str, pos: int, depth: int) -> Optional[int]:
    """Return where the command string of ``FOR /F ... in ('...')`` starts, or None.

    FOR /F runs the text in single quotes or backquotes in a child cmd.exe.
    The options, quoted, are ``""`` by now, so a ``usebackq`` string in single
    quotes is read as a command string too.
    """
    text, _, pos = _read_token(code, pos, "&|()", depth=depth)
    if text.casefold() != "/f":
        return None
    while text.casefold() != "in":
        text, _, pos = _read_token(code, pos, "&|()", depth=depth)
        if not text:
            return None
    while pos < len(code) and code[pos].isspace():
        pos += 1
    if not code.startswith("(", pos):
        return None
    pos += 1
    while pos < len(code) and code[pos].isspace():
        pos += 1
    return pos + 1 if code.startswith(("'", "`"), pos) else None


def _after_command_word(
    code: str, lowered: str, pos: int, offset: int, depth: int
) -> Optional[Tuple[int, int]]:
    """Return where the next command starts after a prefix, and its depth.

    Return None after a command. cmd.exe ends a command name at ``/``, so
    ``start/b`` is START and ``/b``. A quoted program, ``""`` once its quotes
    are dropped, may be cmd. The command string of ``cmd /c``, ``/k`` or
    ``/r``, that of FOR /F and the command START runs are one level deeper
    (``_separator_level``).
    """
    head = lowered.split("/", 1)[0]
    if head != lowered and head in _GLUED_PREFIXES:
        lowered, pos = head, offset + len(head)
    after: Optional[int]
    if lowered == "if":
        return _skip_if_condition(code, pos, depth), depth
    if lowered == '""' or re.split(r"[/\\]", lowered)[-1] in _CMD_NAMES:
        after = _skip_cmd_switches(code, pos, depth)
        return None if after is None else (after, depth + 1)
    if lowered == "for":
        after = _skip_for_f_options(code, pos, depth)
        return None if after is None else (after, depth + 1)
    if lowered == "start":
        # START runs an internal command in a child cmd.exe, as ``cmd /k``.
        return _skip_start_options(code, pos, depth), depth + 1
    return (pos, depth) if lowered == "call" else None


def _depth_after_separator(
    code: str, pos: int, depth: int, parens: _Parens, command: bool
) -> int:
    """Return the depth after the separator at pos.

    A parenthesis keeps the depth, as in ``cmd /c (dir) ^& SET a=1``. After the
    ``)`` of a block, which opens where a command starts, ``^&`` splits
    commands, as in ``(for /f %%a in ('ver') do echo X) ^& SET a=1``, where
    cmd.exe runs ``SET``. The first unescaped ``)`` in a FOR /F set closes
    it, even after an unescaped ``(`` in its string, as in ``for /f %%a in
    ('(ver') do``, and restores the depth before the FOR. A ``)`` escaped for
    a command string closes a block opened in it, as ``^)`` in ``for /f %%a
    in ('(ver^) ^^^& SET b') do echo``. ``parens`` holds the open groups,
    with that depth for a FOR /F set, ``_BLOCK`` minus its depth for a block
    and None for any other parenthesis, and the indices of the FOR /F sets
    among them, so that a ``)`` finds the outermost without a walk.
    """
    groups, for_sets = parens
    char = code[pos : pos + 1]
    level = _separator_level(code, pos)
    top = groups[-1] if groups else None
    closes_block = top is not None and top <= _BLOCK and level <= _BLOCK - top
    if char in ("(", ")") and level > 0 and not (char == ")" and closes_block):
        # An escaped parenthesis closes no FOR /F set, as in ``('echo a^)')``.
        return depth
    if char == "(":
        groups.append(_BLOCK - depth if command else None)
        return depth
    if char == ")":
        if level == 0 and for_sets:
            # Close the outermost FOR /F set open and all opened in its string.
            del groups[for_sets[0] + 1 :]
            del for_sets[1:]
        restored = groups.pop() if groups else None
        if for_sets and for_sets[-1] == len(groups):
            for_sets.pop()
        if restored is not None and restored <= _BLOCK:
            # One level past the block's own, as ``^^^&`` in ``cmd /c (dir) ^^^& SET``.
            return max(depth, _BLOCK - restored + 1)
        return depth if restored is None else restored
    return _separator_level(code, pos)


def _command_keyword(code: str, name: str, offset: int) -> Optional[str]:
    """Return the keyword the command ``name`` at offset spells, or None.

    The keyword's own pattern must match there, and an argument keyword is
    counted apart.
    """
    word = _WORD_RE.match(name)
    keyword = word.group(0).casefold() if word else ""
    pattern = _COMMAND_CASE_RE.get(keyword)
    match = pattern.match(code, max(offset - 1, 0)) if pattern else None
    if match and keyword not in _ARGUMENT_CASE_KEYWORDS:
        return match.group(2)
    return None


def _command_words(code: str) -> List[str]:
    """Return the keywords in code where a command starts, as this scan reads it.

    A command starts the line, or follows ``&`` or ``|`` where they split
    commands, any unescaped ``(`` or ``)``, ``@``, ``ELSE``, ``DO``, a ``<`` or ``2<``
    redirection, an IF condition, ``CALL``, ``START`` with its quoted words and
    switches, ``cmd``, ``%comspec%``, ``!comspec!`` or a quoted program with
    ``/c``, ``/k`` or ``/r``, or the opening quote of a FOR /F command string.
    In the command strings of the last two, a separator escaped once more
    splits commands too (``_separator_level``). The FOR /F one ends at the
    first unescaped ``)`` in its set, even after an unescaped ``(``; a ``)``
    closing any other parenthesis does not end a command string, and after
    the ``)`` of a block ``^&`` splits commands. Commas, semicolons and equals
    signs standing alone before a command are skipped. Any other word is an
    argument. The keyword's own pattern must still match, so a keyword is
    dropped where it was counted before but never added, and a word glued to
    ``@``, ``)``, ``,``, ``;``, ``=`` or a quote does not count. Argument
    keywords are counted apart. Commands still missed include one after
    ``if (a b) == x``, ``if 1==1(`` or ``if defined=x``, or after a
    ``%debug%`` prefix.
    """
    words: List[str] = []
    pos = 0
    depth = 0
    parens: _Parens = ([], [])  # _depth_after_separator
    command = True
    while pos < len(code):
        text, start, pos = _read_token(code, pos, "&|()", depth=depth)
        if not text:  # a separator
            depth = _depth_after_separator(code, pos, depth, parens, command)
            command = True
            pos += 1
            continue
        if not command or not text.strip(",;="):
            # cmd.exe skips a comma, semicolon or equals sign before a command.
            continue
        name = text.lstrip("@")
        offset = start + len(text) - len(name)
        lowered = name.casefold()
        if lowered in ("", "else", "do"):
            continue
        if _INPUT_REDIRECT_RE.match(lowered):
            if lowered.endswith("<"):
                pos = _read_token(code, pos, "&|()", depth=depth)[2]
            continue
        keyword = _command_keyword(code, name, offset)
        if keyword:
            words.append(keyword)
        after = _after_command_word(code, lowered, pos, offset, depth)
        if after is None:
            command = False
        else:
            if lowered == "for":  # _skip_for_f_options read its ``(``
                parens[1].append(len(parens[0]))
                parens[0].append(depth)
            pos, depth = after
    return words


def _collect_cmd_cases(lines: List[str]) -> Dict[str, List[Tuple[int, str]]]:
    """Collect command casing patterns from file lines."""
    command_cases: Dict[str, List[Tuple[int, str]]] = {}
    continued = False

    for line_num, line in enumerate(lines, 1):
        # cmd.exe usually joins a line that ends in an odd caret run to the next
        # one, whose first character is then escaped, so ``^& SET`` there runs
        # SET: it reads as ``^^& SET``. Only a leading odd run of carets before
        # ``&`` or ``|`` is read so; any other line is scanned as it is. SET
        # still counts where the next line does not run as a joined one: after
        # ``rem x ^`` or inside an open quote it runs on its own (B-o27, B-o28 in
        # https://github.com/fametrano/Blinter/actions/runs/41436871703), and
        # after ``:: x ^`` cmd.exe joins it to the comment, so it does not run
        # (T3 in https://github.com/fametrano/Blinter/actions/runs/41658084012).
        escaped = continued and _LEADING_CARET_SEPARATOR_RE.match(line) is not None
        continued = _separator_level(line, len(line.rstrip("\r\n"))) > 0
        stripped = line.strip()
        if _is_blank_or_comment(stripped):
            continue

        # Skip lines where commands appear in contexts that aren't actual batch commands
        # (e.g., within echo statements, comments, or file output)
        if (
            stripped.lower().startswith("echo ")
            or ">" in stripped  # File redirection (content being written to file)
            or ">>" in stripped
        ):
            continue

        # Quoted text and an inline comment are not commands cmd.exe runs,
        # except a cmd /c or cmd /k string, which cmd.exe does execute.
        code = _casing_scan_text("^" + stripped if escaped else stripped)

        # A keyword counts where cmd.exe runs it as a command, not as an argument.
        found = [
            (keyword, match.group(2))
            for keyword in _ARGUMENT_CASE_KEYWORDS
            for match in _COMMAND_CASE_RE[keyword].finditer(code)
        ]
        found.extend((word.casefold(), word) for word in _command_words(code))
        for keyword, actual_case in found:
            command_cases.setdefault(keyword, []).append((line_num, actual_case))

    return command_cases


def _find_most_common_case(
    occurrences: List[Tuple[int, str]],
) -> Tuple[str, Dict[str, List[int]]]:
    """Find the most common case variant and return case counts."""
    case_counts: Dict[str, List[int]] = {}
    for line_num, actual_case in occurrences:
        if actual_case not in case_counts:
            case_counts[actual_case] = []
        case_counts[actual_case].append(line_num)

    def _get_count(case_variant: str) -> int:
        return len(case_counts[case_variant])

    most_common_case = max(case_counts.keys(), key=_get_count)
    return most_common_case, case_counts


def _check_cmd_case_consistency(lines: List[str]) -> List[LintIssue]:
    """Check for consistent command capitalization within the file (S003)."""
    issues: List[LintIssue] = []

    if len(lines) < 2:  # Skip very short files
        return issues

    command_cases = _collect_cmd_cases(lines)

    # Check for inconsistency within each command
    for _, occurrences in command_cases.items():
        if len(occurrences) < 2:  # Need at least 2 occurrences to check consistency
            continue

        most_common_case, case_counts = _find_most_common_case(occurrences)

        if len(case_counts) > 1:  # Inconsistent casing found
            # Report inconsistencies
            for case_variant, line_numbers in case_counts.items():
                if case_variant != most_common_case:
                    for line_num in line_numbers:
                        issues.append(
                            LintIssue(
                                line_number=line_num,
                                rule=RULES["S003"],
                                context=f"Command '{case_variant}' should be "
                                f"'{most_common_case}' for consistency "
                                f"(most common in this file)",
                            )
                        )

    return issues
