"""Where a batch command starts, for the S003 casing check.

The style checker reports the diagnostic. This module only reads the line.
"""

import re
from typing import Dict, List, Optional, Tuple

from blinter.logging_config import logger
from blinter.parsing.context import (
    _is_blank_or_comment,
    _is_caret_escaped,
    caret_joins_next_physical_line,
)
from blinter.parsing.structure import _build_paren_depth_before
from blinter.patterns import COMMAND_CASING_KEYWORDS

# REM or :: at the start of a command segment, after optional ``(`` groups.
_INLINE_REM_RE = re.compile(
    r"[\s(]*@?(?:rem(?:\s|$)|::)",
    re.IGNORECASE,
)
# Text immediately before a quote that is the command string of cmd /c or /k.
# The cmd token may itself be quoted, as in ``"cmd.exe" /c "SET a=1"``.
_CMD_CK_BEFORE_QUOTE_RE = re.compile(
    r"(?:^|[&|(])\s*@?\"?(?:\S*[/\\])?cmd(?:\.exe)?\"?(?:\s+/\S+)*\s+/[ck]\b\s*$",
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
_QUOTED_CMD_NAMES = frozenset(f'"{name}"' for name in _CMD_NAMES)
# Prefixes that may have a switch glued to them, as in ``start/b``.
_GLUED_PREFIXES = frozenset({"if", "call", "start", *_CMD_NAMES, *_QUOTED_CMD_NAMES})
# IF conditions with one operand; any other condition compares two.
_IF_UNARY = frozenset({"exist", "defined", "errorlevel", "cmdextversion"})
_IF_OPERATORS = frozenset({"==", "equ", "neq", "lss", "leq", "gtr", "geq"})
# ``_depth_after_separator`` records ``_BLOCK - depth`` for the ``(`` of a block.
_BLOCK = -1
_Parens = Tuple[List[Optional[int]], List[int]]


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
    token = text[start:end].casefold().strip('"')
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
        else:  # A quoted path to cmd keeps its name (_after_command_word).
            name = inner.replace("/", "\\").rsplit("\\", 1)[-1]
            parts.append(f'"{name}"' if name.casefold() in _CMD_NAMES else '""')
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
    title = True  # Only the first quoted word is the title; a later one is the program.
    while True:
        text, _, end = _read_token(code, pos, "&|()", depth=depth)
        if title and (text == '""' or text.casefold() in _QUOTED_CMD_NAMES):
            title = False
        elif not text.startswith("/"):
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
    ``start/b`` is START and ``/b``. A quoted path to cmd keeps only its last
    component, as ``"cmd.exe"`` (``_strip_casing_quotes``). The command string
    of ``cmd /c``, ``/k`` or ``/r``, that of FOR /F and an internal command
    START runs are one level deeper (``_separator_level``).
    """
    head = lowered.split("/", 1)[0]
    if head != lowered and head in _GLUED_PREFIXES:
        lowered, pos = head, offset + len(head)
    after: Optional[int]
    if lowered == "if":
        return _skip_if_condition(code, pos, depth), depth
    if lowered in _QUOTED_CMD_NAMES or re.split(r"[/\\]", lowered)[-1] in _CMD_NAMES:
        after = _skip_cmd_switches(code, pos, depth)
        return None if after is None else (after, depth + 1)
    if lowered == "for":
        after = _skip_for_f_options(code, pos, depth)
        return None if after is None else (after, depth + 1)
    if lowered == "start":
        # START runs an internal command in a child cmd.exe, as ``cmd /k``, but
        # a program directly, so ``start cmd /c`` is one level deeper, not two.
        after = _skip_start_options(code, pos, depth)
        program = _read_token(code, after, "&|()", depth=depth)[0].casefold()
        head = program.lstrip("@").split("/", 1)[0]
        last = re.split(r"[/\\]", program)[-1]
        cmd = head in _CMD_NAMES or head in _QUOTED_CMD_NAMES or last in _CMD_NAMES
        return after, depth if cmd else depth + 1
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


def _glued_paren_hides_keyword(
    code: str, pos: int, groups: List[Optional[int]], depth_before: int
) -> bool:
    """Return True when ``)`` follows a keyword and closes no open group.

    ``call)`` is not CALL. ``(call)`` is CALL, because ``)`` closes the group
    that is already open.
    """
    if pos >= len(code) or code[pos] != ")":
        return False
    if _is_caret_escaped(code, pos):
        return False
    if depth_before > 0 or groups:
        return False
    logger.debug(
        "Keyword glued to ')' is not a command: %s",
        code[max(0, pos - 8) : pos + 1],
    )
    return True


def _command_words(code: str, *, depth_before: int = 0) -> List[str]:
    """Return the keywords in code where a command starts, as this scan reads it.

    A command starts the line, or follows ``&`` or ``|`` where they split
    commands, any unescaped ``(`` or ``)``, ``@``, ``ELSE``, ``DO``, a ``<``
    or ``2<`` redirection, or a prefix such as IF, CALL, START, cmd /c or the
    quote opening a FOR /F string (``_after_command_word``, and
    ``_depth_after_separator`` for parentheses). Any other word is an
    argument. The keyword's own pattern must still match (``_command_keyword``),
    so a keyword is dropped where it was counted before but never added, and a
    word glued to ``@``, ``)``, ``,``, ``;``, ``=`` or a quote does not count.
    Still missed: a command after ``if (a b) == x``, ``if 1==1(`` or ``if
    defined=x``, or after a ``%debug%`` prefix.
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
        if keyword and _glued_paren_hides_keyword(code, pos, parens[0], depth_before):
            command = False
            continue
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
    depths = _build_paren_depth_before(lines)

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
        depth_before = depths[line_num - 1] if line_num - 1 < len(depths) else 0
        continued = caret_joins_next_physical_line(line, depth_before=depth_before)
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
        found.extend(
            (word.casefold(), word)
            for word in _command_words(code, depth_before=depth_before)
        )
        for keyword, actual_case in found:
            command_cases.setdefault(keyword, []).append((line_num, actual_case))

    return command_cases
