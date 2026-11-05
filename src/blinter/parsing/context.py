"""Comment detection and safe-context helpers for checkers."""

import re
from typing import Iterator, List, Optional, cast

from blinter.logging_config import logger
from blinter.patterns import (
    _DANGEROUS_CMDS_REGEX,
)

_GOTO_LABEL_RE = re.compile(r"\bgoto\s+(\S+)", re.IGNORECASE)
_CALL_LABEL_RE = re.compile(r"\bcall\s+:(\S+)", re.IGNORECASE)
# Label-line keys end here. Comma, semicolon, and equals stay in the key.
_LABEL_KEY_ENDS = frozenset(" \t+:&|<>")
# GOTO/CALL tokens end at command delimiters, then the key cut above applies.
_JUMP_TOKEN_ENDS = frozenset(" \t,;=&|<>")
_REM_SCAN_BREAKS = frozenset(' \t&|()<>"')
_IF_UNARY_PREDICATES = frozenset({"defined", "exist", "errorlevel", "cmdextversion"})
_IF_COMPARISON_OPERATORS = frozenset({"==", "equ", "neq", "lss", "leq", "gtr", "geq"})
_SEGMENT_PREFIXES = frozenset({"do", "else"})
_NON_COMMAND_STARTERS = frozenset({"echo", "rem"})
_COMMENT_TEXT_RE = re.compile(r"^@?(?:rem(?:\s|$)|::)", re.IGNORECASE)


def _is_blank_or_comment(line: str) -> bool:
    """Return True for blank lines and REM or :: comments.

    Unlike a bare ``startswith("rem")`` test, a command such as ``RENAME`` is not
    mistaken for a comment, and ``@rem`` and a lone ``rem`` are recognized.
    """
    stripped = line.strip()
    return not stripped or _COMMENT_TEXT_RE.match(stripped) is not None


def _is_comment_line(line: str) -> bool:
    """
    Check if a line is a comment (REM or ::).

    Args:
        line: The line to check

    Returns:
        True if the line is a comment
    """
    return _COMMENT_TEXT_RE.match(line.strip()) is not None


def _is_comment_or_label(line: str) -> bool:
    """Return True when the line is a comment or label definition."""
    stripped = line.strip().lower()
    return _is_comment_line(line) or stripped.startswith(":")


def label_line_key(body: str) -> str:
    """Return the lookup key of the text after a label's leading colon.

    The key ends at space, tab, ``+``, ``:``, ``&``, ``|``, ``<``, or ``>``.
    Comma, semicolon, equals, and dot stay in the key.
    """
    for index, char in enumerate(body):
        if char in _LABEL_KEY_ENDS:
            return body[:index]
    return body


def jump_lookup_key(operand: str) -> str:
    """Return the lowercase key a GOTO or CALL operand searches for.

    Comma, semicolon, and equals end the command token before the label key
    is cut, so ``goto eq=more`` searches for ``eq`` while a line ``:eq=more``
    is the key ``eq=more``. ``+``, ``:``, ``&``, ``|``, ``<``, and ``>`` end
    the key even when they are not command delimiters.
    """
    token = operand
    for index, char in enumerate(operand):
        if char in _JUMP_TOKEN_ENDS:
            token = operand[:index]
            break
    if token.startswith(":"):
        token = token[1:]
    return label_line_key(token).lower()


def _expansion_in_key(key: str) -> bool:
    """Return True when a lookup key is still expanded at runtime."""
    return "%" in key or "!" in key


def caret_joins_next_physical_line(line: str) -> bool:
    """Return True when an odd trailing caret joins this line to the next.

    A caret inside a REM remark does not join, including ``echo hi & rem note ^``.
    ``echo rem note ^`` still joins, because that ``rem`` is data. A label or
    ``::`` line that ends in an odd caret does join, and the next physical
    lines are part of that label or remark.
    """
    text = line.rstrip("\r\n")
    if (len(text) - len(text.rstrip("^"))) % 2 != 1:
        return False
    if _rem_verb_owns_line(text):
        logger.debug("REM remark does not continue the line: %s", text.strip())
        return False
    return True


def _rem_verb_owns_line(text: str) -> bool:
    """Return True when REM is the command verb on this physical line."""
    index = 0
    command = True
    quote = False
    length = len(text)
    while index < length:
        nxt, command, quote, found = _step_rem_scan(text, index, command, quote)
        if found:
            return True
        index = nxt if nxt > index else index + 1
    return False


def _step_rem_scan(
    text: str, index: int, command: bool, quote: bool
) -> tuple[int, bool, bool, bool]:
    """Advance one character or token. The last flag is True when REM owns the line."""
    char = text[index]
    if quote or char == '"' or char in " \t":
        return _step_rem_gap(text, index, command, quote)
    separated = _step_rem_separator(text, index, command)
    if separated is not None:
        return separated
    if not command:
        return index + 1, False, False, False
    return _step_rem_command(text, index)


def _step_rem_gap(
    text: str, index: int, command: bool, quote: bool
) -> tuple[int, bool, bool, bool]:
    """Advance through a quote or blank. Quotes are not command verbs."""
    char = text[index]
    if quote:
        return index + 1, command, char != '"', False
    if char == '"':
        return index + 1, False, True, False
    return index + 1, command, False, False


def _step_rem_separator(
    text: str, index: int, command: bool
) -> tuple[int, bool, bool, bool] | None:
    """Advance at a separator, or return None when ``index`` is a word."""
    char = text[index]
    if char in "&|":
        if _is_caret_escaped(text, index):
            return index + 1, command, False, False
        return index + 1, True, False, False
    if char in "()":
        return index + 1, char == "(", False, False
    return None


def _step_rem_command(text: str, index: int) -> tuple[int, bool, bool, bool]:
    """Advance from a command position. A REM token owns the rest of the line."""
    if text[index] == "@":
        return index + 1, True, False, False
    redirected = _skip_redirect(text, index)
    if redirected != index:
        return redirected, True, False, False
    return _step_rem_word(text, index)


def _step_rem_word(text: str, index: int) -> tuple[int, bool, bool, bool]:
    """Classify the command word at ``index``."""
    token, after = _read_scan_token(text, index)
    lowered = token.lower()
    if _is_rem_token(lowered):
        return after, False, False, True
    if lowered == "if":
        return _after_if_condition(text, after), True, False, False
    if lowered == "for":
        return _step_rem_for(text, after)
    return after, False, False, False


def _step_rem_for(text: str, index: int) -> tuple[int, bool, bool, bool]:
    """Return the command position after FOR's DO, or the end of the line."""
    after_do = _after_for_do(text, index)
    if after_do is None:
        return len(text), False, False, False
    return after_do, True, False, False


def _is_rem_token(token: str) -> bool:
    """Return True when ``token`` is the REM verb, not a longer command name."""
    if len(token) < 3 or token[:3] != "rem":
        return False
    if len(token) == 3:
        return True
    return not (token[3].isalnum() or token[3] == "_")


def _read_scan_token(text: str, index: int) -> tuple[str, int]:
    """Return the next command token and the index after it."""
    start = index
    while index < len(text) and text[index] not in _REM_SCAN_BREAKS:
        if text[index] == "^":
            index = min(index + 2, len(text))
            continue
        index += 1
    return text[start:index], index


def _skip_redirect(text: str, index: int) -> int:
    """Return the index after a redirection at ``index``, or ``index`` itself."""
    cursor = index
    if cursor < len(text) and text[cursor].isdigit():
        digits = cursor
        while digits < len(text) and text[digits].isdigit():
            digits += 1
        if digits >= len(text) or text[digits] not in "<>":
            return index
        cursor = digits
    if cursor >= len(text) or text[cursor] not in "<>":
        return index
    if text.startswith((">>", ">&", "<&"), cursor):
        cursor += 2
    else:
        cursor += 1
    return _skip_redirect_target(text, cursor)


def _skip_redirect_target(text: str, index: int) -> int:
    """Return the index after a redirection's target."""
    while index < len(text) and text[index] in " \t":
        index += 1
    if index < len(text) and text[index] == '"':
        closing = text.find('"', index + 1)
        return len(text) if closing < 0 else closing + 1
    while index < len(text) and text[index] not in " \t&|()":
        index += 1
    return index


def _after_if_condition(text: str, index: int) -> int:
    """Return the index of the command after an IF condition."""
    token, index = _read_scan_token_ws(text, index)
    while token.lower() in {"/i", "not"}:
        token, index = _read_scan_token_ws(text, index)
    lowered = token.lower()
    if lowered in _IF_UNARY_PREDICATES:
        _operand, index = _read_scan_token_ws(text, index)
        return index
    if "==" in lowered and lowered != "==":
        return index
    operator, after_operator = _read_scan_token_ws(text, index)
    if operator.lower() in _IF_COMPARISON_OPERATORS:
        _right, index = _read_scan_token_ws(text, after_operator)
        return index
    return index


def _read_scan_token_ws(text: str, index: int) -> tuple[str, int]:
    """Skip spaces and return the next scan token."""
    while index < len(text) and text[index] in " \t":
        index += 1
    return _read_scan_token(text, index)


def _after_for_do(text: str, index: int) -> int | None:
    """Return the index after FOR's DO, outside the IN parentheses."""
    depth = 0
    cursor = index
    while cursor < len(text):
        char = text[cursor]
        if char == "(":
            depth += 1
            cursor += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            cursor += 1
            continue
        if depth == 0 and _scan_word_at(text, cursor, "do"):
            return cursor + 2
        cursor += 1
    return None


def _scan_word_at(text: str, index: int, word: str) -> bool:
    """Return True when ``word`` sits at ``index`` as a whole word."""
    end = index + len(word)
    if text[index:end].lower() != word:
        return False
    before_ok = index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_")
    after_ok = end >= len(text) or not (text[end].isalnum() or text[end] == "_")
    return before_ok and after_ok


def _is_echo_statement(stripped: str) -> bool:
    """Return True when the line is an ECHO output statement."""
    return stripped.startswith(("echo ", "echo\t", "@echo ", "@echo\t"))


def _command_body(line: str) -> str:
    """Return command text after whitespace and a leading @, or empty for comments."""
    if _is_comment_line(line):
        return ""
    stripped = line.strip()
    if stripped.startswith("@"):
        stripped = stripped[1:].lstrip()
    return stripped


def _is_caret_escaped(text: str, index: int) -> bool:
    """Return True when an odd run of carets escapes the character at index."""
    caret_count = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "^":
        caret_count += 1
        pos -= 1
    return caret_count % 2 == 1


def _split_command_separators(body: str) -> list[str]:
    """Split on unescaped ``&``, ``&&`` and ``||`` outside quoting.

    A caret escapes the next character (``^&`` is data), and ``&`` right
    after ``>`` or ``<`` belongs to a redirection such as ``2>&1``. A lone
    ``|`` is a pipe whose right-hand side runs in another ``cmd``, so it is
    not a separator for SETLOCAL or GOTO/CALL on this line.
    """
    return _split_unquoted(body, andand_only=False)


def _split_pipe_stages(body: str) -> list[str]:
    """Split one command segment on unquoted, unescaped ``|`` pipes.

    ``||`` is not a pipe. A caret escapes the following character, so ``^|``
    stays inside the current stage.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char == "^":
            current.append(char)
            if index + 1 < length:
                current.append(body[index + 1])
            index += 2
            continue
        if char in '"`':
            quote = char
            current.append(char)
            index += 1
            continue
        if char == "|" and not body.startswith("|", index + 1):
            parts.append("".join(current))
            current = []
            index += 1
            continue
        if body.startswith("||", index):
            current.append("||")
            index += 2
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _split_tokens(text: str) -> list[str]:
    """Split on whitespace outside quoting, keeping each token's quotes."""
    tokens: list[str] = []
    current: list[str] = []
    quote = ""
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in '"`':
            quote = char
            current.append(char)
            continue
        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _strip_if_predicate(tokens: list[str]) -> list[str]:
    """Return tokens of the command an ``IF`` runs, or ``tokens`` unchanged."""
    if not tokens or tokens[0].lower() != "if":
        return tokens
    rest = tokens[1:]
    while rest and rest[0].lower() in ("/i", "not"):
        rest = rest[1:]
    if not rest:
        return []
    first = rest[0].lower()
    if first in _IF_UNARY_PREDICATES:
        return rest[2:]
    if len(rest) >= 3 and rest[1].lower() in _IF_COMPARISON_OPERATORS:
        return rest[3:]
    if "==" in rest[0]:
        return rest[1:]
    return rest


def _strip_leading_if_predicates(tokens: list[str]) -> list[str]:
    """Drop every leading IF, so ``if A if B command`` leaves ``command``.

    One predicate is the common case. ``if defined A if defined B goto %1``
    is also a command, and each pass removes exactly one predicate.
    """
    removed = 0
    while tokens and tokens[0].lower() == "if":
        remaining = _strip_if_predicate(tokens)
        if len(remaining) >= len(tokens):
            break
        removed += 1
        tokens = remaining
    if removed > 1:
        logger.debug(
            "Stripped %d nested IF predicates; next token is %r",
            removed,
            tokens[0] if tokens else "",
        )
    return tokens


def _command_segments(line: str) -> list[str]:
    """Return each command a line runs, starting at its command word.

    Drops ``ECHO`` output and ``REM``/``::`` segments so
    ``echo done & rem call :label`` is not a CALL, while
    ``echo x || goto :label`` still is. Nested IF predicates are removed
    before the command word is read.
    """
    body = _command_body(line)
    if not body:
        return []
    segments: list[str] = []
    for part in _split_command_separators(body):
        tokens = _split_tokens(part.strip().lstrip("(").strip())
        while tokens and tokens[0].lower() in _SEGMENT_PREFIXES:
            tokens = tokens[1:]
        tokens = _strip_leading_if_predicates(tokens)
        if not tokens:
            continue
        first = tokens[0].lower()
        if first in _NON_COMMAND_STARTERS or first.startswith(("echo.", "::")):
            logger.debug(
                "Ignoring non-command segment %r on line: %s", first, line.strip()
            )
            continue
        segments.append(" ".join(tokens))
    return segments


def _line_runs_command(line: str, command: str) -> bool:
    """Return True when one of the commands the line runs is ``command``."""
    return any(
        segment.split()[0].lower() == command for segment in _command_segments(line)
    )


def _is_setlocal_command(line: str) -> bool:
    """Return True when the line runs SETLOCAL, including after IF or ``&``."""
    if _is_comment_line(line) and "setlocal" in line.lower():
        logger.debug("Ignoring SETLOCAL mention in comment: %s", line.strip())
        return False
    runs = _line_runs_command(line, "setlocal")
    if runs:
        logger.debug("SETLOCAL command detected: %s", line.strip())
    return runs


def _is_endlocal_command(line: str) -> bool:
    """Return True when the line runs ENDLOCAL, including after IF or ``&``."""
    if _is_comment_line(line) and "endlocal" in line.lower():
        logger.debug("Ignoring ENDLOCAL mention in comment: %s", line.strip())
        return False
    return _line_runs_command(line, "endlocal")


def _executable_jump_text(line: str) -> str:
    """Return executable GOTO/CALL text from command segments.

    Comments and ECHO output are excluded whether they are the whole line
    or an ``&``-separated segment.
    """
    segments = _command_segments(line)
    if not segments:
        logger.debug("No executable GOTO/CALL context on line: %s", line.strip())
        return ""
    return " & ".join(segments)


def _iter_goto_label_refs(line: str) -> Iterator[tuple[str, str]]:
    """Yield (raw_target, label_name) for executable GOTO destinations."""
    text = _executable_jump_text(line)
    if not text:
        return
    for match in _GOTO_LABEL_RE.finditer(text):
        raw = str(match.group(1))
        key = jump_lookup_key(raw)
        if not key or _expansion_in_key(key):
            continue
        shown = f":{key}" if raw.startswith(":") else key
        yield shown, key


def _goto_and_call_label_names(line: str) -> set[str]:
    """Return label names referenced by GOTO or CALL :label on an executable line."""
    text = _executable_jump_text(line)
    if not text:
        return set()
    names = {name for _raw, name in _iter_goto_label_refs(line)}
    for match in _CALL_LABEL_RE.finditer(text):
        key = jump_lookup_key(str(match.group(1)))
        if key and not _expansion_in_key(key):
            names.add(key)
    return names


def _call_subroutine_label_names(line: str) -> set[str]:
    """Return label names invoked via CALL :label on an executable line."""
    text = _executable_jump_text(line)
    if not text:
        return set()
    names: set[str] = set()
    for match in _CALL_LABEL_RE.finditer(text):
        key = jump_lookup_key(str(match.group(1)))
        if key and not _expansion_in_key(key):
            names.add(key)
    return names


def _set_line_without_dangerous_substitution(stripped: str) -> bool:
    """Return True when a SET line has no dangerous command substitution."""
    if not stripped.startswith(("set ", "set\t")):
        return False
    dangerous_in_substitution = re.search(
        rf"\bwhere\s+({_DANGEROUS_CMDS_REGEX})\b", stripped
    ) or re.search(rf"['\(]\s*\b({_DANGEROUS_CMDS_REGEX})\b\s+", stripped)
    return dangerous_in_substitution is None


def _is_command_in_safe_context(line: str) -> bool:
    """
    Check if a potentially dangerous command is in a safe context.

    Safe contexts include REM comments, ECHO statements, labels, GOTO statements,
    or IF DEFINED variable checks. SET statements are generally safe UNLESS they
    contain dangerous commands in command substitution contexts (e.g., WHERE FORMAT,
    WHERE SHUTDOWN, etc.).

    Args:
        line: The line to check

    Returns:
        True if the command is in a safe context and shouldn't be flagged as dangerous
    """
    stripped = line.strip().lower()

    if _is_comment_or_label(line):
        return True

    if _is_echo_statement(stripped):
        return True

    if re.search(r"\bgoto\s+:", stripped) or re.search(r"\bif\s+defined\s+", stripped):
        return True

    if _set_line_without_dangerous_substitution(stripped):
        return True

    return False


def _is_safe_ctx_for_privilege(line: str) -> bool:
    """
    Check if a command is in a safe context for privilege (SEC005) checks.

    This is similar to _is_command_in_safe_context but EXCLUDES IF DEFINED
    because privilege-requiring commands still need admin rights even when
    wrapped in an IF DEFINED conditional.

    For example:
    - IF DEFINED @DLETTER NET USE %@DLETTER% /D /Y  <- Still needs admin rights
    - IF DEFINED @MSSHUTDOWN echo Variable defined   <- Truly safe (just echo)
    - IF DEFINED @MORECMDS ECHO Other NET USER Options <- Truly safe (just echo)
    - IF DEFINED *SERVICE_SC (                         <- Truly safe (just variable check)

    Safe contexts for privilege checks include REM comments, ECHO statements,
    labels, GOTO statements, and SET statements (without dangerous commands).
    IF DEFINED is NOT considered safe for privilege checks UNLESS the actual
    command after the condition is ECHO or there's just a variable name check.

    Args:
        line: The line to check

    Returns:
        True if the command is in a safe context for privilege checks
    """
    stripped = line.strip().lower()

    if _is_comment_or_label(line):
        return True

    if _is_echo_statement(stripped):
        return True

    # Check if line contains IF/IF DEFINED with ECHO as the actual command
    # Pattern: IF [/I] [NOT] [DEFINED] <condition> ECHO <text>
    # Examples:
    #   IF DEFINED @VAR ECHO text with NET USER <- ECHO is the command (SAFE)
    #   IF DEFINED @VAR NET USE <- NET USE is the command (NOT SAFE)
    if_match = re.match(
        r"^@?if\s+(?:/i\s+)?(?:not\s+)?(?:defined\s+\S+\s+)?(.+)", stripped
    )
    if if_match:
        # Extract the command portion after the condition
        command_portion: str = cast(str, if_match.group(1)).strip()
        # Check if the command is ECHO or if it's IF DEFINED with just a variable check
        # Pattern: IF DEFINED <varname> ( or IF DEFINED <varname> THEN or just IF DEFINED <varname>
        is_echo_command: bool = command_portion.startswith(("echo ", "echo\t"))
        is_variable_check: bool = bool(
            re.match(r"^@?if\s+(?:/i\s+)?defined\s+\S+\s*(?:\(|then)?$", stripped)
        )
        if is_echo_command or is_variable_check:
            return True

    if re.search(r"\bgoto\s+:", stripped):
        return True

    if _set_line_without_dangerous_substitution(stripped):
        return True

    return False


def _consume_quote_body(
    text: str, index: int, quote: str, current: List[str]
) -> tuple[int, str]:
    """Append one quoted character and clear the quote when it closes."""
    current.append(text[index])
    if text[index] == quote:
        return index + 1, ""
    return index + 1, quote


def _consume_caret(text: str, index: int, current: List[str]) -> Optional[int]:
    """Consume a caret escape, including the escaped character."""
    if text[index] != "^":
        return None
    current.append("^")
    if index + 1 < len(text):
        current.append(text[index + 1])
        return index + 2
    return index + 1


def _consume_quote_open(
    text: str, index: int, current: List[str]
) -> Optional[tuple[int, str]]:
    """Start a double or single quoted region."""
    if text[index] not in '"`':
        return None
    current.append(text[index])
    return index + 1, text[index]


def _consume_separator(text: str, index: int, *, andand_only: bool) -> Optional[int]:
    """Return the index after an unquoted command separator."""
    two = text[index : index + 2]
    if two == "&&" or (not andand_only and two == "||"):
        return index + 2
    if not andand_only and text[index] == "&":
        return index + 1
    return None


def _command_chain(body: str) -> list[tuple[str, str]]:
    """Return ``(separator, segment)`` pairs, including a leading empty separator.

    ``&&`` and ``||`` are conditional. A single ``&`` is not. An ``&`` in a
    redirection such as ``2>&1`` stays inside the segment, matching
    ``_split_unquoted``.
    """
    parts: list[tuple[str, str]] = []
    current: List[str] = []
    quote = ""
    redirect = False
    separator = ""
    index = 0
    length = len(body)
    while index < length:
        after_redirect, redirect = redirect, False
        if quote:
            index, quote = _consume_quote_body(body, index, quote, current)
            continue
        caret_index = _consume_caret(body, index, current)
        if caret_index is not None:
            index = caret_index
            continue
        opened = _consume_quote_open(body, index, current)
        if opened is not None:
            index, quote = opened
            continue
        separator_index = None
        if not (after_redirect and body[index] == "&"):
            separator_index = _consume_separator(body, index, andand_only=False)
        if separator_index is not None:
            parts.append((separator, "".join(current)))
            separator = body[index:separator_index]
            current = []
            index = separator_index
            continue
        redirect = body[index] in "<>"
        current.append(body[index])
        index += 1
    parts.append((separator, "".join(current)))
    return parts


def _split_unquoted(text: str, *, andand_only: bool) -> List[str]:
    """Split on unquoted separators without breaking ``2>&1``.

    An ``&`` right after an unescaped ``>`` or ``<`` names a handle, as in
    ``2>&1``, ``>&2`` and ``<&3``, so it is not a separator.
    """
    parts: List[str] = []
    current: List[str] = []
    quote = ""
    redirect = False
    index = 0
    length = len(text)
    while index < length:
        after_redirect, redirect = redirect, False
        if quote:
            index, quote = _consume_quote_body(text, index, quote, current)
            continue
        caret_index = _consume_caret(text, index, current)
        if caret_index is not None:
            index = caret_index
            continue
        opened = _consume_quote_open(text, index, current)
        if opened is not None:
            index, quote = opened
            continue
        separator_index = None
        if not (after_redirect and text[index] == "&"):
            separator_index = _consume_separator(text, index, andand_only=andand_only)
        if separator_index is not None:
            parts.append("".join(current))
            current = []
            index = separator_index
            continue
        redirect = text[index] in "<>"
        current.append(text[index])
        index += 1
    parts.append("".join(current))
    return parts
