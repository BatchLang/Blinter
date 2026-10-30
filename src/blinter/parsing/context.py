"""Comment detection and safe-context helpers for checkers."""

import re
from typing import Iterator, List, Optional, cast

from blinter.logging_config import logger
from blinter.patterns import (
    _DANGEROUS_CMDS_REGEX,
)

_GOTO_LABEL_RE = re.compile(r"\bgoto\s+(:?)([a-zA-Z_][\w]*)", re.IGNORECASE)
_CALL_LABEL_RE = re.compile(r"\bcall\s+:([a-zA-Z_][\w]*)", re.IGNORECASE)
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


def _split_command_separators(body: str) -> list[str]:
    """Split on unescaped ``&``, ``&&`` and ``||`` outside quoting.

    A caret escapes the next character (``^&`` is data). A lone ``|`` is a
    pipe whose right-hand side runs in another ``cmd``, so it is not a
    separator for SETLOCAL or GOTO/CALL on this line.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(body):
        char = body[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char == "^":
            current.append(char)
            if index + 1 < len(body):
                current.append(body[index + 1])
            index += 2
            continue
        if char in '"`':
            quote = char
            current.append(char)
            index += 1
            continue
        two = body[index : index + 2]
        if char == "&" or two == "||":
            parts.append("".join(current))
            current = []
            index += 2 if two in ("&&", "||") else 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


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


def _command_segments(line: str) -> list[str]:
    """Return each command a line runs, starting at its command word.

    Drops ``ECHO`` output and ``REM``/``::`` segments so
    ``echo done & rem call :label`` is not a CALL, while
    ``echo x || goto :label`` still is.
    """
    body = _command_body(line)
    if not body:
        return []
    segments: list[str] = []
    for part in _split_command_separators(body):
        tokens = _split_tokens(part.strip().lstrip("(").strip())
        while tokens and tokens[0].lower() in _SEGMENT_PREFIXES:
            tokens = tokens[1:]
        tokens = _strip_if_predicate(tokens)
        if not tokens:
            continue
        first = tokens[0].lower()
        if first in _NON_COMMAND_STARTERS or first.startswith("::"):
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
        colon = str(match.group(1) or "")
        name = str(match.group(2))
        yield colon + name, name.lower()


def _goto_and_call_label_names(line: str) -> set[str]:
    """Return label names referenced by GOTO or CALL :label on an executable line."""
    text = _executable_jump_text(line)
    if not text:
        return set()
    names = {name for _raw, name in _iter_goto_label_refs(line)}
    for match in _CALL_LABEL_RE.finditer(text):
        names.add(str(match.group(1)).lower())
    return names


def _call_subroutine_label_names(line: str) -> set[str]:
    """Return label names invoked via CALL :label on an executable line."""
    text = _executable_jump_text(line)
    if not text:
        return set()
    return {str(match.group(1)).lower() for match in _CALL_LABEL_RE.finditer(text)}


def _set_line_without_dangerous_substitution(stripped: str) -> bool:
    """Return True when a SET line has no dangerous command substitution."""
    if not stripped.startswith(("set ", "set\t")):
        return False
    dangerous_in_substitution = re.search(
        rf"where\s+({_DANGEROUS_CMDS_REGEX})", stripped
    ) or re.search(rf"['\(]\s*({_DANGEROUS_CMDS_REGEX})\s+", stripped)
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


def _consume_redir(text: str, index: int, current: List[str]) -> Optional[int]:
    """Consume ``1>&`` / ``2>&`` so the ampersand is not a separator."""
    if text[index] not in "12" or index + 2 >= len(text):
        return None
    if text[index + 1 : index + 3] != ">&":
        return None
    span = 4 if index + 3 < len(text) else len(text) - index
    current.append(text[index : index + span])
    return index + span


def _consume_separator(text: str, index: int, *, andand_only: bool) -> Optional[int]:
    """Return the index after an unquoted command separator."""
    two = text[index : index + 2]
    if two == "&&" or (not andand_only and two == "||"):
        return index + 2
    if not andand_only and text[index] == "&":
        return index + 1
    return None


def _split_unquoted(text: str, *, andand_only: bool) -> List[str]:
    """Split on unquoted separators without breaking ``2>&1``."""
    parts: List[str] = []
    current: List[str] = []
    quote = ""
    index = 0
    length = len(text)
    while index < length:
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
        redir_index = _consume_redir(text, index, current)
        if redir_index is not None:
            index = redir_index
            continue
        separator_index = _consume_separator(text, index, andand_only=andand_only)
        if separator_index is not None:
            parts.append("".join(current))
            current = []
            index = separator_index
            continue
        current.append(text[index])
        index += 1
    parts.append("".join(current))
    return parts
