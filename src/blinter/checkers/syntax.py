"""Syntax error checks (E-prefix rules)."""

# pylint: disable=too-many-lines

import re
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.checkers.cmd_extended import check_extended_syntax_line
from blinter.checkers.warnings import (
    _strip_double_quoted_strings,
)
from blinter.models import LintIssue
from blinter.parsing.context import (
    _is_blank_or_comment,
    _is_comment_line,
    _split_tokens,
)
from blinter.parsing.structure import (
    _delayed_expansion_state_for_lines,
    _paren_depth_before_line,
)
from blinter.patterns import (
    _COMPILED_IF_PATTERN,
    BUILTIN_COMMANDS,
    COMMON_COMMAND_TYPOS,
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
    target_label: str = label_text.lower()

    # E015: GOTO EOF must use colon (GOTO :EOF is required, GOTO EOF is invalid)
    if target_label == "eof":
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E015"],
                context="GOTO EOF should be GOTO :EOF (colon is mandatory for EOF)",
            )
        )
    elif target_label == ":eof":
        # :eof is a built-in construct, always valid with colon
        pass
    elif _is_dynamic_jump_target(label_text):
        # Dynamic labels like "label.%errorlevel%", ":%1", or "%~1" can't be
        # statically validated
        pass
    else:
        # Static label - check if it exists
        if not target_label.startswith(":"):
            target_label = ":" + target_label
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


def _check_call_labels(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for CALL label issues (E014)."""
    issues: List[LintIssue] = []
    call_match = re.match(r"call\s+(:?\S+)", stripped, re.IGNORECASE)
    if not call_match:
        return issues

    call_label_text: str = call_match.group(1)
    if _is_dynamic_jump_target(call_label_text) or call_label_text.startswith(":"):
        return issues

    # Check if this looks like a label call (not an external program)
    # Skip if it contains path separators, extensions, or is a known command
    if (
        not re.search(r"[\\/.:]|\.(?:bat|cmd|exe|com)$", call_label_text.lower())
        and call_label_text.lower() not in BUILTIN_COMMANDS
    ):
        # This appears to be a label call without colon
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


def _check_if_statement_formatting(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for IF statement formatting issues (E003)."""
    issues: List[LintIssue] = []
    issues.extend(_check_if_exists_typo(stripped, line_num))
    if issues:
        return issues
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
        remaining = line[index + 1 :].strip()
        if remaining == "^":
            index += 1
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
    line_continues = line.rstrip().endswith("^")

    if quote_count % 2 != 0 and not line_continues:
        if not _is_e009_special_case_exemption(stripped, line):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["E009"],
                    context="Unmatched double quotes detected",
                )
            )
    return issues


def _check_for_loop_syntax(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for malformed FOR loop (E010)."""
    issues: List[LintIssue] = []
    if not re.match(r"for\s+.*", stripped, re.IGNORECASE):
        return issues
    lowered = stripped.lower()
    has_do = bool(re.search(r"\bdo(?:\s|\()", lowered))
    if has_do:
        return issues
    # Don't flag multiline FOR loops (those ending with opening parenthesis)
    if not re.search(r"\(\s*$", stripped):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["E010"],
                context="FOR loop is missing required DO keyword",
            )
        )
    return issues


def _has_special_variable_patterns(stripped: str) -> bool:
    """Check if line contains special variable patterns that should skip E011 checks."""
    # Check for indirect variable expansion patterns like !%1!, !%var%!, or !%~n1!
    if re.search(r"!([^!]*%[^%!]+%?[^!]*|%~?[a-z0-9]+)!", stripped, re.IGNORECASE):
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

    # Skip if it's a known builtin command or external program
    if first_word in BUILTIN_COMMANDS:
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
    """Check for invalid command syntax / typos (E013)."""
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


def _is_caret_escaped(text: str, index: int) -> bool:
    """Return True when an odd number of carets precede text[index]."""
    caret_count = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "^":
        caret_count += 1
        pos -= 1
    return caret_count % 2 == 1


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


def _invalid_token_after_close_paren(text: str) -> Optional[str]:
    """Return the unexpected token after an inner ')' if cmd.exe would reject it."""
    in_quotes = False
    for index, char in enumerate(text):
        if char == '"' and not _is_caret_escaped(text, index):
            in_quotes = not in_quotes
            continue
        if in_quotes or char != ")" or _is_caret_escaped(text, index):
            continue
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
        unexpected = _invalid_token_after_close_paren(region)
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
    issues.extend(_check_call_labels(stripped, line_num))
    issues.extend(_check_if_statement_formatting(stripped, line_num))
    issues.extend(_check_errorlevel_syntax(stripped, line_num))
    issues.extend(_check_if_exist_mixing(stripped, line_num))
    issues.extend(_check_path_syntax(stripped, line_num))
    issues.extend(_check_quotes(line, line_num))
    issues.extend(_check_for_loop_syntax(stripped, line_num))
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
