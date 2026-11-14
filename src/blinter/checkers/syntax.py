"""Syntax error checks (E-prefix rules)."""

# pylint: disable=too-many-lines

from contextvars import ContextVar
import re
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.checkers.cmd_extended import check_extended_syntax_line
from blinter.checkers.globals.label_flow import _for_in_set_open
from blinter.checkers.warnings import (
    _strip_double_quoted_strings,
)
from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import (
    _is_blank_or_comment,
    _is_caret_escaped,
    _is_comment_line,
    _rem_remark_consumes_paren,
    _rem_verb_owns_line,
    _split_tokens,
    caret_joins_next_physical_line,
    grouped_if_has_no_condition,
    jump_lookup_key,
)
from blinter.parsing.structure import (
    _delayed_expansion_state_for_lines,
    _paren_depth_before_line,
)
from blinter.patterns import (
    _COMPILED_IF_PATTERN,
    BUILTIN_COMMANDS,
    COMMON_COMMAND_TYPOS,
    COMMON_EXTERNAL_TOOLS,
)
from blinter.rules.expansion_data import VALID_MODIFIERS
from blinter.rules.helpers import PERCENT_TILDE_TOKEN_RE, strip_for_metavar_tilde_tokens
from blinter.rules.registry import RULES


def _check_goto_labels(
    stripped: str, line_num: int, labels: Dict[str, int]
) -> List[LintIssue]:
    """Check for GOTO label issues (E002, E015)."""
    issues: List[LintIssue] = []
    goto_match = re.match(r"goto\s+(:?\S+)", stripped, re.IGNORECASE)
    if not goto_match:
        return issues

    label_text: str = goto_match.group(1)
    target_key = jump_lookup_key(label_text)

    # E015: GOTO EOF must use colon (GOTO :EOF is required, GOTO EOF is invalid)
    if target_key == "eof" and not label_text.startswith(":"):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E015"],
                context="GOTO EOF should be GOTO :EOF (colon is mandatory for EOF)",
            )
        )
    elif target_key == "eof" and label_text.startswith(":"):
        # :eof is a built-in construct, always valid with colon
        pass
    elif not target_key or _is_dynamic_jump_target(target_key):
        # Dynamic labels like "label.%errorlevel%", ":%1", or "%~1" can't be
        # statically validated. A colon after the key is not part of the search.
        pass
    else:
        # Static label - check if it exists
        target_label = ":" + target_key
        if target_label not in labels:
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E002"],
                    context=f"GOTO points to non-existent label '{label_text}'",
                )
            )
    return issues


_DYNAMIC_JUMP_RE = re.compile(
    r"%[^%\s]+%|!\w+!|%(?:~[fdpnxsatz$]*)?(?:\d|\*)",
    re.IGNORECASE,
)


def _is_dynamic_jump_target(target: str) -> bool:
    """Return True when a GOTO/CALL target is expanded at runtime."""
    body = target[1:] if target.startswith(":") else target
    return _DYNAMIC_JUMP_RE.search(body) is not None


def _is_known_command(name: str) -> bool:
    """Return True when ``name`` is a stock command or a common external tool.

    E012 and E014 use this so a label that shares a command name is not treated
    as a subroutine call. Stock commands and third-party tools stay separate sets.
    """
    return name in BUILTIN_COMMANDS or name in COMMON_EXTERNAL_TOOLS


def _check_call_labels(
    stripped: str, line_num: int, labels: Dict[str, int]
) -> List[LintIssue]:
    """Check for CALL label issues (E014)."""
    issues: List[LintIssue] = []
    call_match = re.match(r"call\s+(:?\S+)", stripped, re.IGNORECASE)
    if not call_match:
        return issues

    call_label_text: str = call_match.group(1)
    if call_label_text.startswith(":"):
        return issues
    call_name = jump_lookup_key(call_label_text)
    if not call_name or _is_dynamic_jump_target(call_name):
        return issues
    # An external name is only a missing-colon label when that label exists.
    if (
        f":{call_name}" in labels
        and not _is_known_command(call_name)
        and not re.search(r"[\\/]|\.(?:bat|cmd|exe|com)$", call_name)
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E014"],
                context=(
                    f"CALL to label '{call_label_text}' should use colon: "
                    f"CALL :{call_label_text}"
                ),
            )
        )
    return issues


_SET_P_VALID_RE = re.compile(
    r'^set\s+/p\s+(?:"[A-Za-z_#][\w#]*=|[A-Za-z_#][\w#]*=)',
    re.IGNORECASE,
)


def _check_set_p_syntax(stripped: str, line_num: int) -> List[LintIssue]:
    """Flag SET /P lines missing variable=[promptString] (E041)."""
    if not re.match(r"set\s+/p\b", stripped, re.IGNORECASE):
        return []
    if _SET_P_VALID_RE.match(stripped):
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["E041"],
            context="SET /P requires variable=[promptString] per SET /?",
        )
    ]


def _check_if_exists_typo(stripped: str, line_num: int) -> List[LintIssue]:
    """Flag IF EXISTS / EXIT / EXITS typos (E036). cmd.exe requires IF EXIST."""
    match = re.search(
        r"\bif\s+(?:/i\s+)?(not\s+)?exi(sts|t|ts)\b",
        stripped,
        re.IGNORECASE,
    )
    if match is None:
        return []
    negation = "NOT " if match.group(1) else ""
    typo = f"EXI{match.group(2)}".upper()
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["E036"],
            context=f"IF {negation}{typo} is invalid; use IF {negation}EXIST",
        )
    ]


def _check_if_statement_formatting(
    stripped: str, line_num: int, lines: List[str] | None = None
) -> List[LintIssue]:
    """Check for IF statement formatting issues (E003)."""
    issues: List[LintIssue] = []
    issues.extend(_check_if_exists_typo(stripped, line_num))
    if issues:
        return issues
    bare_if = _check_grouped_bare_if(stripped, line_num, lines)
    if bare_if:
        return bare_if
    if re.match(r'if(?=["\'%!])', stripped, re.IGNORECASE) or re.match(
        r"if\(", stripped, re.IGNORECASE
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E003"],
                context="IF keyword must be followed by a space before the condition",
            )
        )
        return issues

    if_match = _COMPILED_IF_PATTERN.match(stripped)
    if not if_match:
        return issues

    if_group_result = if_match.group(1)
    if if_group_result is None:
        return issues

    if_content: str = if_group_result.strip()

    # Valid IF patterns to check for:
    valid_if_patterns = [
        r"exist\s+",  # IF EXIST
        r"defined\s+",  # IF DEFINED
        r"errorlevel\s+\d+",  # IF ERRORLEVEL n
        r"/i\s+",  # IF /I (case insensitive)
        r"not\s+",  # IF NOT
        r"(==|equ|neq|lss|leq|gtr|geq)",  # Comparison operators (search is unanchored)
    ]

    # Check if this IF statement matches any valid pattern
    is_valid_if = any(
        re.search(pattern, if_content, re.IGNORECASE) for pattern in valid_if_patterns
    )

    # If it doesn't match any valid pattern and seems incomplete, flag it
    if not is_valid_if and not re.search(
        r"[&|()]", if_content
    ):  # Not a complex conditional
        # Only flag if it looks like an incomplete comparison (has words but no operators)
        if re.match(r"[\"']?%?\w+%?[\"']?\s*$", if_content):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E003"],
                    context=(
                        "IF statement appears to be missing comparison operator "
                        "or condition"
                    ),
                )
            )
    issues.extend(_check_if_equals_paren(stripped, line_num))
    return issues


def _check_grouped_bare_if(
    stripped: str, line_num: int, lines: List[str] | None
) -> List[LintIssue]:
    """Flag ``(if)`` and ``if)`` inside a group (E003).

    The ``)`` closes a group that is already open, so IF stays the keyword
    and cmd.exe rejects the missing condition. ``if)`` with no group open is
    not IF. ``echo (if)`` prints its argument.
    """
    depth_before = 0
    if lines is not None:
        depth_before = _paren_depth_before_line(lines, line_num)
    if not grouped_if_has_no_condition(stripped, depth_before=depth_before):
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["E003"],
            context=(
                "IF with no condition is a syntax error; ')' closes the IF keyword"
            ),
        )
    ]


_IF_PREFIX_TOKENS = frozenset({"/i", "not"})
_IF_CONDITION_OPERATORS = frozenset(
    {"==", "=", "equ", "neq", "lss", "leq", "gtr", "geq"}
)


def _if_condition_text(stripped: str) -> str:
    """Return the IF condition, excluding the command that follows it."""
    body = stripped[1:].lstrip() if stripped.startswith("@") else stripped
    tokens = _split_tokens(body)
    if not tokens or tokens[0].lower() != "if":
        return ""
    index = 1
    while index < len(tokens) and tokens[index].lower() in _IF_PREFIX_TOKENS:
        index += 1
    if index >= len(tokens):
        return ""
    operator_index = index + 1
    if (
        operator_index + 1 < len(tokens)
        and tokens[operator_index].lower() in _IF_CONDITION_OPERATORS
    ):
        return " ".join(tokens[index : operator_index + 2])
    return tokens[index]


def _check_if_equals_paren(stripped: str, line_num: int) -> List[LintIssue]:
    """E003: single ``=`` where ``==`` is required, or ``IF a==b(`` glued paren."""
    if not re.match(r"@?if\b", stripped, re.IGNORECASE):
        return []
    if re.search(
        r"\bif\s+(?:/i\s+)?(?:not\s+)?(?:exist|defined|errorlevel|cmdextversion)\b",
        stripped,
        re.IGNORECASE,
    ):
        return []
    condition = _if_condition_text(stripped)
    unquoted = _strip_double_quoted_strings(condition)
    issues: List[LintIssue] = []
    if re.search(r"(?:==|equ|neq|lss|leq|gtr|geq)\S*\(", unquoted, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E003"],
                context="IF comparison must have a space before (",
            )
        )
    without_double_equals = re.sub(r"==", "", unquoted)
    if re.search(r"=", without_double_equals) and not re.search(
        r"\b(equ|neq|lss|leq|gtr|geq)\b", unquoted, re.IGNORECASE
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E003"],
                context="IF string comparison requires ==, not a single =",
            )
        )
    return issues


def _check_if_block_paren_next_line(lines: list[str], line_num: int) -> List[LintIssue]:
    """IF block open parenthesis must be on the same line as IF (E039)."""
    if line_num < 1 or line_num > len(lines):
        return []
    current = lines[line_num - 1].strip()
    if not re.match(r"if\b", current, re.IGNORECASE):
        return []
    if "(" in current:
        return []
    if re.search(r"\b(if\s+)?(exist|defined|errorlevel)\b", current, re.IGNORECASE):
        # IF EXIST/ DEFINED / ERRORLEVEL forms may run a command without a block
        return []
    next_index = line_num
    while next_index < len(lines):
        nxt = lines[next_index].strip()
        if _is_blank_or_comment(nxt):
            next_index += 1
            continue
        if nxt.startswith("("):
            return [
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E039"],
                    context="IF block open parenthesis must be on the same line as IF",
                )
            ]
        break
    return []


def _check_for_do_paren_next_line(lines: list[str], line_num: int) -> List[LintIssue]:
    """FOR block open parenthesis must be on the same line as DO (E040)."""
    if line_num < 1 or line_num > len(lines):
        return []
    current = lines[line_num - 1].strip()
    if not re.match(r"for\b", current, re.IGNORECASE):
        return []
    do_match = re.search(r"\bdo\b(.*)$", current, re.IGNORECASE)
    if not do_match:
        return []
    if "(" in do_match.group(1):
        return []
    next_index = line_num
    while next_index < len(lines):
        nxt = lines[next_index].strip()
        if _is_blank_or_comment(nxt):
            next_index += 1
            continue
        if nxt.startswith("("):
            return [
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E040"],
                    context="FOR block open parenthesis must be on the same line as DO",
                )
            ]
        break
    return []


def _check_errorlevel_syntax(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for invalid errorlevel comparison syntax (E016)."""
    issues: List[LintIssue] = []
    errorlevel_if_match = _COMPILED_IF_PATTERN.match(stripped)
    if not errorlevel_if_match:
        return issues

    errorlevel_group_result = errorlevel_if_match.group(1)
    if errorlevel_group_result is None:
        return issues

    errorlevel_content: str = errorlevel_group_result.strip()

    if re.match(r"%errorlevel%\s+\d+\b", errorlevel_content, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E016"],
                context=(
                    "Invalid 'IF %ERRORLEVEL% number' syntax - "
                    "missing comparison operator (use EQU, NEQ, GEQ, etc.)"
                ),
            )
        )
        return issues

    # Check for invalid "if not %errorlevel% number" pattern (missing operator)
    if re.match(r"not\s+%errorlevel%\s+\d+", errorlevel_content, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E016"],
                context=(
                    "Invalid 'IF NOT %ERRORLEVEL% number' syntax - "
                    "missing comparison operator"
                ),
            )
        )
    # Check for other invalid errorlevel patterns
    elif re.match(
        r"not\s+%errorlevel%\s+[^\s]+(?:\s|$)", errorlevel_content, re.IGNORECASE
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E016"],
                context=(
                    "Invalid 'IF NOT %ERRORLEVEL%' syntax - use 'IF NOT ERRORLEVEL n' "
                    "or add comparison operator"
                ),
            )
        )
    return issues


def _check_if_exist_mixing(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for IF EXIST syntax mixing (E004)."""
    issues: List[LintIssue] = []
    exist_to_equals = re.search(r"if\s+exist\s+(\S+)\s+==", stripped, re.IGNORECASE)
    if exist_to_equals is None:
        return issues
    between_text = exist_to_equals.group(1)
    if re.search(r"\bif\b", between_text, re.IGNORECASE):
        return issues
    issues.append(
        LintIssue(
            line_number=line_num,
            rule=RULES["E004"],
            context="Mixing IF EXIST with comparison operators",
        )
    )
    return issues


_SCRIPT_COMMAND_PATTERN = re.compile(
    r"(for\s+|powershell\s+|cscript\s+|wscript\s+|msiexec\s+|%ps[c]?%|%powershell%)",
    re.IGNORECASE,
)

_SCRIPT_INDICATOR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\$\w+\s*=",  # PowerShell variable assignment
        r"-match\s+",  # PowerShell match operator
        r"\.Matches\(",  # Regex.Matches
        r"IndexOf\(",  # Array.IndexOf
        r"foreach\s*\(",  # foreach loops
        r"\[regex\]::",  # PowerShell [regex]::
        r"\[System\.",  # .NET class references
        r"Get-Content",  # PowerShell cmdlets
        r"ToArray\(\)",  # .ToArray() method calls
        r"Write-Output\s+",  # PowerShell Write-Output
        r"Write-Host\s+",  # PowerShell Write-Host
        r"^echo\s+",  # echo command at line start
        r"^\s*\$\w+",  # PowerShell variable at line start
    )
)

_XML_OR_MARKUP_PATTERN = re.compile(
    r"<\?xml|^\s*<\w+[\s>]|['\"]<\w+\s",
    re.IGNORECASE,
)

_QUOTED_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'"([^"]*[<>|*?][^"]*)",'),
    re.compile(r"'([^']*[<>|*?][^']*)'"),
)

_SCRIPT_STRING_SKIP_PATTERN = re.compile(
    r"(::|scriptblock|split\s|regex)",
    re.IGNORECASE,
)


def _line_has_script_command(stripped: str) -> bool:
    """Return True when the line invokes an external scripting runtime."""
    return _SCRIPT_COMMAND_PATTERN.search(stripped) is not None


def _line_looks_like_embedded_script(stripped: str) -> bool:
    """Return True when the line resembles embedded PowerShell or .NET code."""
    return any(pattern.search(stripped) for pattern in _SCRIPT_INDICATOR_PATTERNS)


def _line_has_xml_or_markup_prefix(stripped: str) -> bool:
    """Return True when the line starts XML/HTML-like markup."""
    return _XML_OR_MARKUP_PATTERN.search(stripped) is not None


def _quoted_path_has_invalid_chars(stripped: str) -> bool:
    """Return True when a quoted path segment contains invalid redirection chars."""
    for pattern in _QUOTED_PATH_PATTERNS:
        match = pattern.search(stripped)
        if not match:
            continue
        path_content = match.group(1)
        escaped_content = re.sub(r"\^[<>|]", "", path_content)
        if _SCRIPT_STRING_SKIP_PATTERN.search(escaped_content):
            continue
        if re.search(r"[<>|]", escaped_content):
            return True
    return False


def _unquoted_path_has_invalid_chars(stripped: str) -> bool:
    """Return True when an unquoted path token contains invalid path characters."""
    if _line_has_script_command(stripped):
        return False
    for token in stripped.split():
        if token.lower() == "rem":
            break
        if re.search(r"[a-zA-Z]:\\[^\"']*[<>|][^\"'\s]*", token):
            return True
        if re.search(r"\\\\[^\\]+\\[^\"'\s]*[<>|]", token):
            return True
    return False


def _check_path_syntax(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for invalid path syntax (E005)."""
    if _line_has_script_command(stripped):
        return []
    if _line_looks_like_embedded_script(stripped):
        return []
    if _line_has_xml_or_markup_prefix(stripped):
        return []
    if _quoted_path_has_invalid_chars(stripped) or _unquoted_path_has_invalid_chars(
        stripped
    ):
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["E005"],
                context="Path contains invalid characters",
            )
        ]
    return []


def _should_skip_e009_quote_check(stripped: str) -> bool:
    """Return True when odd quote counts are expected on this line."""
    if re.match(r'^\s*"@\s*$', stripped):
        return True

    if re.match(r"\s*echo\s+", stripped, re.IGNORECASE):
        quote_count = stripped.count('"')
        if quote_count == 1 and re.match(r'\s*echo\s+"\s+\S', stripped, re.IGNORECASE):
            return True
        percent_vars: list[str] = re.findall(r"%[A-Za-z@][\w]*%", stripped)
        if len(percent_vars) >= 2:
            return True
        if re.search(r'\becho\b.*![^!]+!"\s*$', stripped, re.IGNORECASE):
            return True

    return False


def _count_unmatched_batch_quotes(line: str) -> int:
    """Count unpaired double quotes respecting batch escape rules."""
    quote_count = 0
    index = 0
    while index < len(line):
        char = line[index]
        if char != '"':
            index += 1
            continue
        if index > 0 and line[index - 1] == "^":
            # Caret escapes a literal quote (e.g. content=^"%%b^"), but in "^"
            # the caret is quoted content, not an escape for the closing quote.
            if index > 1 and line[index - 2] == '"':
                pass
            else:
                index += 1
                continue
        if index + 1 < len(line) and line[index + 1] == '"':
            index += 2
            continue
        quote_count += 1
        index += 1
    return quote_count


def _is_e009_special_case_exemption(stripped: str, line: str) -> bool:
    """Return True when E009 should not fire despite odd quoting."""
    if "!" in line and re.search(r"\bset\s", stripped, re.IGNORECASE):
        return True
    if re.search(r"call\s+:[^:]+", stripped, re.IGNORECASE):
        return True
    if re.search(r"![^!]+:[^=]*\"[^=]*=[^!]*!", line) or re.search(
        r"![^!]+:[^=]*=[^!]*\"[^!]*!", line
    ):
        return True
    if re.search(r"%[^%]+:[^=]*\"[^=]*=[^%]*%", line) or re.search(
        r"%[^%]+:[^=]*=[^%]*\"[^%]*%", line
    ):
        return True
    if re.search(r"\bfor\s+/f\b", stripped, re.IGNORECASE) and re.search(
        r"\(\^\"",
        stripped,
    ):
        return True
    return False


def _check_quotes(line: str, line_num: int) -> List[LintIssue]:
    """Check for mismatched quotes (E009)."""
    issues: List[LintIssue] = []

    stripped = line.strip()
    if _is_comment_line(stripped):
        return issues

    if re.match(r"\s*echo\s+.*\.\.\.\.", stripped, re.IGNORECASE) or re.match(
        r"\s*echo\s+.*represents", stripped, re.IGNORECASE
    ):
        return issues

    if _should_skip_e009_quote_check(stripped):
        return issues

    quote_count = _count_unmatched_batch_quotes(line)

    if quote_count % 2 != 0 and not caret_joins_next_physical_line(line):
        if not _is_e009_special_case_exemption(stripped, line):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E009"],
                    context="Unmatched double quotes detected",
                )
            )
    return issues


_FOR_COMMAND_RE = re.compile(r"for\s", re.IGNORECASE)
_FOR_DO_RE = re.compile(r"\bdo(?:\s|\()", re.IGNORECASE)
# cmd.exe accepts ``do`` only as its own token. ``do(`` is one unexpected
# token, and ``echo do`` after the set is not the keyword.
_FOR_DO_TOKEN_RE = re.compile(r"do\s", re.IGNORECASE)
_FOR_TRAILING_OPEN_RE = re.compile(r"\(\s*$")
# The caret that joins a line escapes the next line's first character. A word
# character is not a delimiter and does not open a block, so ``do^`` / `` echo``
# and ``do^`` / ``(`` stay one token instead of the DO keyword.
_ESCAPED_JOIN_MARK = "X"
_caret_join_cache_var: ContextVar[Optional[Dict[int, tuple[object, List[bool]]]]] = (
    ContextVar("caret_join_cache", default=None)
)


def _begin_caret_join_pass() -> None:
    """Start a per-file cache of caret-continuation flags."""
    _caret_join_cache_var.set({})


def _continuation_body(text: str) -> str:
    """Return ``text`` with its escaped first character made non-syntactic.

    A letter stays a letter, so ``d^`` followed by ``o rem`` is still ``do rem``.
    A separator, quote, parenthesis, or caret does not keep its syntax.
    """
    if text and (text[0].isspace() or text[0] in "()\"'^&|"):
        return "X" + text[1:]
    return text


def _line_may_own_rem(parts: List[str], text: str) -> bool:
    """Return True when this line could be where REM becomes the verb."""
    if "rem" in text.lower():
        return True
    tail = parts[-1][-2:] if parts else ""
    return "rem" in (tail + text[:3]).lower()


def _caret_line_joins(
    line: str,
    *,
    depth: int,
    in_continuation: bool,
    parts: List[str],
    command_depth: int,
) -> bool:
    """Return True when ``line`` joins, using the command built so far.

    ``do rem`` can sit on a continued line, including when ``do`` is split as
    ``d^`` / ``o rem``. REM is visible only in that whole command.
    """
    if not caret_joins_next_physical_line(
        line, depth_before=depth, in_continuation=in_continuation
    ):
        return False
    if not parts:
        return True
    text = _continuation_body(line.rstrip("\r\n"))
    if not _line_may_own_rem(parts, text):
        return True
    command = "".join(parts) + text
    return not _rem_verb_owns_line(command, depth_before=command_depth)


def _build_caret_join_flags(lines: List[str]) -> List[bool]:
    """Return whether each physical line is joined onto the next one."""
    flags: List[bool] = []
    continuation = False
    parts: List[str] = []
    command_depth = 0
    for cursor, line in enumerate(lines):
        depth = _paren_depth_before_line(lines, cursor + 1)
        if not continuation:
            command_depth = depth
            parts.clear()
        joins = _caret_line_joins(
            line,
            depth=depth,
            in_continuation=continuation,
            parts=parts,
            command_depth=command_depth,
        )
        flags.append(joins)
        body = line.rstrip("\r\n")
        if continuation:
            body = _continuation_body(body)
        if joins:
            parts.append(body[:-1])
            continuation = True
            continue
        continuation = False
        parts.clear()
    return flags


def _caret_join_flags(lines: List[str]) -> List[bool]:
    """Return continuation flags, built once per file when a pass is active."""
    cache = _caret_join_cache_var.get()
    if cache is None:
        return _build_caret_join_flags(lines)
    source_id = id(lines)
    cached = cache.get(source_id)
    if cached is None or cached[0] is not lines:
        value = _build_caret_join_flags(lines)
        cache[source_id] = (lines, value)
        return value
    return cached[1]


def _line_joins_next(lines: List[str], index: int) -> bool:
    """Return True when physical line ``index`` is joined onto the next one."""
    if index < 0 or index >= len(lines):
        return False
    return _caret_join_flags(lines)[index]


def _prior_caret_joins(lines: List[str], line_num: int) -> bool:
    """Return True when the previous physical line is joined onto this one."""
    if line_num <= 1:
        return False
    return _line_joins_next(lines, line_num - 2)


def _neutralize_escaped_continuation_character(text: str) -> str:
    """Make the first character non-syntactic when a prior caret escaped it.

    An escaped space does not separate ``DO`` from the next word. An escaped
    parenthesis, quote, or caret does not close the IN set or escape the next
    character. A letter is unchanged, so ``d^`` followed by ``o echo`` is
    still the DO keyword.
    """
    if text and (text[0].isspace() or text[0] in '()"^'):
        return _ESCAPED_JOIN_MARK + text[1:]
    return text


def _caret_joined_for_command(lines: List[str], line_num: int) -> Optional[str]:
    """Return the FOR command cmd reads starting at this line.

    None means this physical line continues the previous caret, so it is not
    its own command. Only the caret that escapes the newline is removed. A
    caret inside an open quote or a REM remark does not join.
    """
    if line_num < 1 or line_num > len(lines):
        logger.debug("E010 caret join ignored out-of-range line %s", line_num)
        return None
    if _prior_caret_joins(lines, line_num):
        return None
    parts: List[str] = []
    index = line_num - 1
    escape_next = False
    while index < len(lines):
        text = lines[index].rstrip("\r\n")
        if escape_next:
            text = _neutralize_escaped_continuation_character(text)
        if _line_joins_next(lines, index):
            parts.append(text[:-1])
            logger.debug("E010 caret joins line %s onto the next line", index + 1)
            escape_next = True
            index += 1
            continue
        parts.append(text)
        break
    return "".join(parts).strip()


def _step_inside_set_quote(command: str, index: int, quote: str) -> tuple[int, str]:
    """Advance one character inside a set quote."""
    if quote == '"' and command[index] == '"':
        if index + 1 < len(command) and command[index + 1] == '"':
            return index + 2, quote
        return index + 1, ""
    if command[index] == quote:
        return index + 1, ""
    return index + 1, quote


def _for_set_end(command: str, open_paren: int) -> Optional[int]:
    """Return the index after the ')' that closes the IN set.

    The first unescaped ')' closes the set. ``(`` does not nest. An apostrophe
    or backtick is a character, including at the start of a classic set and
    inside a FOR /F command string. Double quotes hide ')', so ``"a)b"`` and
    ``"a""b)c"`` stay one value.
    """
    quote = ""
    index = open_paren + 1
    length = len(command)
    while index < length:
        if quote:
            index, quote = _step_inside_set_quote(command, index, quote)
            continue
        if command[index] == "^" and index + 1 < length:
            index += 2
            continue
        if command[index] == '"':
            quote = '"'
            index += 1
            continue
        if command[index] == ")":
            return index + 1
        index += 1
    return None


def _for_set_is_open(command: str) -> bool:
    """Return True when the FOR IN set has no closing parenthesis yet."""
    open_paren = _for_in_set_open(command)
    if open_paren is None:
        return False
    return _for_set_end(command, open_paren) is None


def _for_loop_has_do(command: str) -> bool:
    """Return True when DO follows the IN set.

    ``do`` inside the set is a value. ``for %%A in (do this) echo %%A`` has
    no DO keyword. A set that is still open has not reached DO yet.
    """
    open_paren = _for_in_set_open(command)
    if open_paren is None:
        return _FOR_DO_RE.search(command) is not None
    after_set = _for_set_end(command, open_paren)
    if after_set is None:
        return False
    return _FOR_DO_TOKEN_RE.match(command[after_set:].lstrip()) is not None


def _check_for_loop_syntax(
    stripped: str,
    line_num: int,
    lines: List[str] | None = None,
) -> List[LintIssue]:
    """Check for malformed FOR loop (E010).

    A line that ends in an odd caret is one command with the following
    physical lines. DO on one of those lines is present. A line that only
    continues an earlier caret is not checked again.
    """
    command = stripped
    if lines is not None:
        joined = _caret_joined_for_command(lines, line_num)
        if joined is None:
            if _FOR_COMMAND_RE.match(stripped):
                logger.debug(
                    "E010 skipped on line %s; it continues a caret-joined command",
                    line_num,
                )
            return []
        command = joined
    if _FOR_COMMAND_RE.match(command) is None:
        return []
    if _for_loop_has_do(command):
        if not _for_loop_has_do(stripped):
            logger.debug(
                "E010 skipped; FOR at line %s has DO after caret joining: %s",
                line_num,
                command,
            )
        return []
    # ``for %%A in (`` continues on later lines without a caret. ``for %%A
    # in (a) (`` already closed the set and is still missing DO.
    if _for_set_is_open(command) and _FOR_TRAILING_OPEN_RE.search(command):
        return []
    logger.debug("E010 FOR at line %s is missing DO: %s", line_num, command)
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["E010"],
            context="FOR loop is missing required DO keyword",
        )
    ]


def _has_indirect_bang_expansion(stripped: str) -> bool:
    """Return True for !%var%! or !%~n1! without backtracking across the line."""
    start = 0
    while True:
        open_at = stripped.find("!", start)
        if open_at < 0:
            return False
        close_at = stripped.find("!", open_at + 1)
        if close_at < 0:
            return False
        inner = stripped[open_at + 1 : close_at]
        if "%" in inner or re.fullmatch(r"%~?[a-z0-9]+", inner, re.IGNORECASE):
            return True
        start = close_at


def _has_special_variable_patterns(stripped: str) -> bool:
    """Check if line contains special variable patterns that should skip E011 checks."""
    if _has_indirect_bang_expansion(stripped):
        return True

    # Check for dynamic variable assignment like set "%1=value" or set "%%~a=value"
    if re.search(r'set\s+"[^"]*%%?~?[a-z0-9][^"]*=', stripped, re.IGNORECASE):
        return True

    # Check for wildcard patterns with variables
    if re.search(
        r"(?:\*+%%?[A-Z0-9_@-]+(?::[^%]*=[^%]*)?%%?|\b%%?[A-Z0-9_@-]+(?::[^%]*=[^%]*)?%%?\*+)",
        stripped,
        re.IGNORECASE,
    ):
        return True

    # Check for escaped percent signs, string replacement, or variables with suffixes
    return (
        "%%%%" in stripped
        or bool(re.search(r"%%?[A-Z0-9_@-]+:.+=.+%%?", stripped, re.IGNORECASE))
        or bool(re.search(r"%[A-Z0-9_@-]+%[\w.*\\/:]+", stripped, re.IGNORECASE))
    )


def _check_variable_expansion(
    stripped: str,
    line_num: int,
    *,
    lines: List[str] | None = None,
    delayed_expansion_state: List[bool] | None = None,
) -> List[LintIssue]:
    """Check for invalid variable expansion syntax (E011)."""
    issues: List[LintIssue] = []

    # Skip checking if line has special patterns
    if _has_special_variable_patterns(stripped):
        return issues

    # Remove FOR loop variables with modifiers (%%~a, %%~nx1, etc.)
    temp_stripped = re.sub(r"%%~[a-zA-Z]+", "", stripped)
    temp_stripped = re.sub(r"%%[a-zA-Z]", "", temp_stripped)

    # Remove command-line parameters with modifiers (%~nx1, %~dp0, etc.)
    temp_stripped = re.sub(
        r"%~?[fdpnxsatz]*[0-9*](?![0-9])", "", temp_stripped, flags=re.IGNORECASE
    )

    # Remove all valid percent expansion patterns (including @ prefix)
    temp_no_percent = re.sub(
        r"%[A-Z0-9_~@]+[^%]*%", "", temp_stripped, flags=re.IGNORECASE
    )

    # Look for incomplete percent patterns that suggest mismatched delimiters
    if re.search(r"%[A-Z0-9_@]+(?:[^%]|$)", temp_no_percent, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E011"],
                context="Variable reference may have mismatched % delimiters",
            )
        )

    de_state = delayed_expansion_state
    if de_state is None and lines is not None:
        de_state = _delayed_expansion_state_for_lines(lines)
    de_active = (
        de_state is not None
        and 1 <= line_num <= len(de_state)
        and de_state[line_num - 1]
    )
    if de_active:
        temp_no_exclaim = re.sub(r"![^!]+!", "", temp_stripped, flags=re.IGNORECASE)
        if re.search(r"![A-Z0-9_@]+(?:[^!]|$)", temp_no_exclaim, re.IGNORECASE):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E011"],
                    context=(
                        "Delayed expansion variable may have mismatched ! delimiters"
                    ),
                )
            )
    return issues


def _check_subroutine_call(
    stripped: str, line_num: int, labels: Dict[str, int]
) -> List[LintIssue]:
    """Check for missing CALL for subroutine invocation (E012).

    Detects when a user tries to invoke a defined label/subroutine without using
    CALL or GOTO, which won't work in batch files.

    Example:
        :MyFunction         <- Label definition
        MyFunction arg1     <- ERROR: Should be CALL :MyFunction arg1
    """
    issues: List[LintIssue] = []

    # Skip empty lines, comments, and label definitions
    if _is_blank_or_comment(stripped) or stripped.startswith(":"):
        return issues

    # Skip lines that already use CALL or GOTO
    if re.match(r"^(call|goto)\s+", stripped, re.IGNORECASE):
        return issues

    # Extract the first word (command/potential label invocation)
    first_word_match = re.match(r"^([a-z0-9_-]+)\b", stripped, re.IGNORECASE)
    if not first_word_match:
        return issues

    first_word: str = first_word_match.group(1).lower()

    # Skip a stock command or a common external tool such as docker or git.
    if _is_known_command(first_word):
        return issues

    # Skip if it looks like a file path or has an extension
    if re.search(r"[\\/.:]|\.(?:bat|cmd|exe|com|ps1)$", first_word):
        return issues

    # Check if this word matches any defined label (case-insensitive)
    # Labels are stored with colon prefix in lowercase (e.g., ":mylabel")
    potential_label = ":" + first_word

    if potential_label in labels:
        remainder = stripped[first_word_match.end() :].strip()
        context = f"Attempting to invoke label '{first_word}' without CALL or GOTO"
        if remainder:
            context = f"Attempting to call label '{first_word}' " "without CALL or GOTO"
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E012"],
                context=context,
            )
        )

    return issues


def _check_command_typos(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for invalid command syntax / typos (E013).

    The map is an exact match on the first token. Edit distance is not used:
    cmd names are only a few letters long, so a one-character guess collides
    with real commands, and an unknown executable is not a typo.
    """
    issues: List[LintIssue] = []
    first_word = stripped.split()[0].lower() if stripped.split() else ""
    if first_word in COMMON_COMMAND_TYPOS:
        correct_command = COMMON_COMMAND_TYPOS[first_word]
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E013"],
                context=(
                    f"Command '{first_word}' appears to be a typo, "
                    f"did you mean '{correct_command}'?"
                ),
            )
        )
    return issues


def _invalid_percent_tilde_modifier_chars(interior: str) -> set[str]:
    valid_modifiers: Set[str] = set(VALID_MODIFIERS)
    invalid: set[str] = set()
    index = 0
    while index < len(interior):
        char = interior[index]
        lowered = char.lower()
        if char == "$" or lowered in valid_modifiers:
            index += 1
            continue
        if char.isalpha():
            invalid.add(lowered)
            index += 1
            continue
        break
    parameter = interior[index:]
    prefix_match = re.match(r"^([a-z]+)(\d.*)$", parameter, re.IGNORECASE)
    if prefix_match:
        for char in str(prefix_match.group(1)).lower():
            if char not in valid_modifiers:
                invalid.add(char)
    return invalid


def _check_parameter_modifiers(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for invalid parameter modifier combinations (E024, E025)."""
    issues: List[LintIssue] = []
    scan_line = strip_for_metavar_tilde_tokens(stripped)

    for match in PERCENT_TILDE_TOKEN_RE.finditer(scan_line):
        interior = match.group(1)
        invalid_chars = _invalid_percent_tilde_modifier_chars(interior)
        if invalid_chars:
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E024"],
                    context=(
                        f"Invalid parameter modifier characters: "
                        f"{', '.join(sorted(invalid_chars))} in %~{interior}%"
                    ),
                )
            )

    # E025: Parameter modifier on wrong context
    temp_stripped = strip_for_metavar_tilde_tokens(stripped)
    temp_stripped = re.sub(r"%~[a-zA-Z]+[0-9]", "", temp_stripped)
    wrong_context_match: List[str] = re.findall(
        r"%~[a-zA-Z]+([^0-9%\s][^%\s]*|[A-Z_][A-Z0-9_]*)%", temp_stripped
    )
    if wrong_context_match:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E025"],
                context="Parameter modifiers should only be used with batch parameters "
                "(%1, %2, etc.) or FOR variables (%%i)",
            )
        )
    return issues


def _check_unc_path(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for UNC path used as working directory (E027)."""
    issues: List[LintIssue] = []
    if re.match(r"cd\s+\\\\[^\\]+\\", stripped, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E027"],
                context="CD command cannot use UNC paths as working directory",
            )
        )
    return issues


def _is_legitimate_quote_pattern(stripped: str) -> bool:
    """
    Check if a line contains legitimate quote patterns that should be excluded.

    Args:
        stripped: The stripped line to check

    Returns:
        True if the line contains legitimate quote patterns, False otherwise
    """
    # Check all legitimate patterns
    legitimate_patterns = [
        # ECHO statements displaying documentation/help text
        # Pattern: ECHO followed by spaces and text containing "Represents" or "...."
        re.match(r"\s*echo\s+.*\.\.\.\.", stripped, re.IGNORECASE) is not None,
        re.match(r"\s*echo\s+.*represents", stripped, re.IGNORECASE) is not None,
        # Comparisons with empty string: neq "", equ "", == "", != ""
        re.search(r'\b(neq|equ|==|!=|lss|leq|gtr|geq)\s+""', stripped, re.IGNORECASE)
        is not None,
        # START command with triple-quote escaping: start ... /c ""!var!" ...
        re.search(r'\bstart\b.*\s+/c\s+""[^"]+!"', stripped, re.IGNORECASE) is not None,
        # START command with empty window title: start "" command
        re.search(r'\bstart\s+""\s+', stripped, re.IGNORECASE) is not None,
        # Properly formatted triple-quote patterns: """text"""
        re.match(r'.*"""[^"]*""".*', stripped) is not None,
        # Empty string as function/subroutine parameter: CALL :label param1 "" param2
        re.search(r'\bcall\s+:[^\s]+.*\s+""\s+', stripped, re.IGNORECASE) is not None,
        # Empty string as command parameter (not just in CALL): command param "" param
        re.search(r'\s+""\s+[^\s]', stripped) is not None,
        # Empty argument, including find /v "" inside a FOR /F ('...') command
        re.search(r'(?:^|[\s=])""(?:$|[\s\')|&<>])', stripped) is not None,
    ]

    return any(legitimate_patterns)


def _check_quote_escaping(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for complex quote escaping errors (E028)."""
    issues: List[LintIssue] = []
    if '"""' not in stripped and not re.search(r'["\s]""[^"]', stripped):
        return issues

    if _is_legitimate_quote_pattern(stripped):
        return issues

    # Look for potentially problematic quote patterns
    quote_context = ""
    if '"""' in stripped:
        quote_context = "Triple quote pattern found"
    elif re.search(r'["\s]""[^"]', stripped):
        quote_context = "Complex quote escaping detected"

    issues.append(
        LintIssue(line_number=line_num, rule=RULES["E028"], context=quote_context)
    )
    return issues


def _check_set_a_expression(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for complex SET /A expression errors (E029)."""
    issues: List[LintIssue] = []
    seta_match = re.match(r"set\s+/a\s+(.+)", stripped, re.IGNORECASE)
    if not seta_match:
        return issues

    expression: str = seta_match.group(1)

    # Extract only the arithmetic expression, stopping at command separators
    # Command separators: & | && || (but not when escaped with ^)
    # Stop at the first unescaped command separator
    expr_match = re.match(r"^([^&|]*?)(?:\s*(?:[^\\^]|^)[&|]|$)", expression)
    if expr_match:
        expression = expr_match.group(1).strip()

    # Check for unbalanced parentheses in arithmetic expressions
    paren_count: int = expression.count("(") - expression.count(")")
    if paren_count != 0:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E029"],
                context=f"Unbalanced parentheses in SET /A expression: {paren_count} unclosed",
            )
        )

    # Check for unquoted expressions with special characters that might cause issues
    if not (expression.startswith('"') and expression.endswith('"')):
        if re.search(r"[&|<>^]", expression):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E029"],
                    context="SET /A expression with special characters should be quoted",
                )
            )
    return issues


def _check_empty_variable_syntax(stripped: str, line_num: int) -> List[LintIssue]:
    """Check IF comparisons with unquoted variables that may be empty (E007)."""
    issues: List[LintIssue] = []
    if not stripped.lower().startswith("if "):
        return issues

    if re.search(
        r'if\s+(?:(?:not)\s+)?(?![\'"])(%[^%]+%)\s*==\s*""',
        stripped,
        re.IGNORECASE,
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E007"],
                context=(
                    "Unquoted empty-variable comparison breaks when the variable is unset"
                ),
            )
        )
        return issues

    if re.search(
        r"if\s+(?:(?:not)\s+)?(?![\'\"])(%[^%]+%)\s*==(?:\s|$)",
        stripped,
        re.IGNORECASE,
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E007"],
                context=(
                    "IF comparison with unquoted variable and empty right-hand side "
                    "will break when the variable is unset"
                ),
            )
        )
    return issues


_SMART_QUOTE_CHARS = ("\u201c", "\u201d", "\u2018", "\u2019")


def _check_smart_quotes(line: str, line_num: int) -> List[LintIssue]:
    """Check for curly/smart quote characters (E035)."""
    if any(char in line for char in _SMART_QUOTE_CHARS):
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["E035"],
                context="Smart/curly quote characters are not valid batch delimiters",
            )
        ]
    return []


_VALID_AFTER_CLOSE_PAREN_RE = re.compile(
    r"^(?:[&|<>)]|\d*>|else\b|do\b)",
    re.IGNORECASE,
)
_REM_COMMENT_RE = re.compile(r"^@?rem(?:\s|$)", re.IGNORECASE)
_DO_BLOCK_OPEN_RE = re.compile(r"\bdo\s*\(", re.IGNORECASE)
_ELSE_BLOCK_OPEN_RE = re.compile(r"\belse\s*\(", re.IGNORECASE)
_LEADING_GROUP_OPEN_RE = re.compile(r"^@?\(")
_IF_LINE_RE = re.compile(r"^@?if\b", re.IGNORECASE)


def _first_unquoted_open_paren(text: str) -> Optional[int]:
    """Return the first unquoted '(' that opens a block, skipping NAME(X86)."""
    in_quotes = False
    for index, char in enumerate(text):
        if char == '"' and not _is_caret_escaped(text, index):
            in_quotes = not in_quotes
            continue
        if in_quotes or char != "(" or _is_caret_escaped(text, index):
            continue
        if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
            continue
        return index
    return None


def _invalid_token_after_close_paren(
    text: str, *, depth_before: int = 0
) -> Optional[str]:
    """Return the unexpected token after an inner ')' if cmd.exe would reject it."""
    in_quotes = False
    for index, char in enumerate(text):
        if char == '"' and not _is_caret_escaped(text, index):
            in_quotes = not in_quotes
            continue
        if in_quotes or char != ")" or _is_caret_escaped(text, index):
            continue
        if _rem_remark_consumes_paren(text, index, depth_before):
            # (rem) note is a remark: ')' is comment text, not a group closer.
            return None
        remainder = text[index + 1 :].lstrip()
        if not remainder or _VALID_AFTER_CLOSE_PAREN_RE.match(remainder):
            continue
        token = remainder.split()[0]
        return token
    return None


def _regions_inside_paren_blocks(stripped: str, depth_before: int) -> List[str]:
    """Return line slices that cmd.exe parses with block grouping rules."""
    if depth_before > 0:
        return [stripped]
    regions: List[str] = []
    if _LEADING_GROUP_OPEN_RE.match(stripped):
        group_open_at = stripped.find("(")
        regions.append(stripped[group_open_at + 1 :])
    for match in _DO_BLOCK_OPEN_RE.finditer(stripped):
        regions.append(stripped[match.end() :])
    for match in _ELSE_BLOCK_OPEN_RE.finditer(stripped):
        regions.append(stripped[match.end() :])
    if _IF_LINE_RE.match(stripped):
        if_open_at = _first_unquoted_open_paren(stripped)
        if if_open_at is not None:
            regions.append(stripped[if_open_at + 1 :])
    return regions


def _check_text_after_close_paren_in_block(
    stripped: str,
    line_num: int,
    lines: List[str] | None,
) -> List[LintIssue]:
    """Flag leftover text after ')' inside a parenthesized block (E042)."""
    if not stripped or _REM_COMMENT_RE.match(stripped):
        return []
    depth_before = 0
    if lines is not None:
        depth_before = _paren_depth_before_line(lines, line_num)
    unexpected: Optional[str] = None
    for region in _regions_inside_paren_blocks(stripped, depth_before):
        region_depth = depth_before if depth_before > 0 else 1
        unexpected = _invalid_token_after_close_paren(region, depth_before=region_depth)
        if unexpected is not None:
            break
    if unexpected is None:
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["E042"],
            context=(
                f"{unexpected!r} after ')' is a cmd.exe syntax error inside a "
                "parenthesized block; escape parentheses as ^(...^) or remove "
                "the trailing text"
            ),
        )
    ]


def _check_syntax_errors(
    line: str,
    line_num: int,
    labels: Dict[str, int],
    *,
    lines: List[str] | None = None,
) -> List[LintIssue]:
    """Check for syntax error level issues."""
    issues: List[LintIssue] = []
    stripped = line.strip()

    # Use helper functions to check for various syntax errors
    issues.extend(_check_goto_labels(stripped, line_num, labels))
    issues.extend(_check_call_labels(stripped, line_num, labels))
    issues.extend(_check_if_statement_formatting(stripped, line_num, lines))
    issues.extend(_check_errorlevel_syntax(stripped, line_num))
    issues.extend(_check_if_exist_mixing(stripped, line_num))
    issues.extend(_check_path_syntax(stripped, line_num))
    issues.extend(_check_quotes(line, line_num))
    issues.extend(_check_for_loop_syntax(stripped, line_num, lines))
    issues.extend(
        _check_variable_expansion(
            stripped,
            line_num,
            lines=lines,
        )
    )
    issues.extend(_check_subroutine_call(stripped, line_num, labels))
    issues.extend(_check_command_typos(stripped, line_num))
    issues.extend(_check_parameter_modifiers(stripped, line_num))
    issues.extend(_check_unc_path(stripped, line_num))
    issues.extend(_check_quote_escaping(stripped, line_num))
    issues.extend(_check_set_a_expression(stripped, line_num))
    issues.extend(_check_set_p_syntax(stripped, line_num))
    issues.extend(_check_text_after_close_paren_in_block(stripped, line_num, lines))
    issues.extend(_check_empty_variable_syntax(stripped, line_num))
    issues.extend(_check_smart_quotes(line, line_num))
    issues.extend(check_extended_syntax_line(line, line_num, lines))

    return issues
