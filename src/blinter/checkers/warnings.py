"""Warning-level line checks (W-prefix rules)."""

import re
from typing import (
    FrozenSet,
    List,
    Set,
    Tuple,
)

from blinter.checkers.cmd_extended import (
    _split_amp_commands,
    check_extended_warning_line,
)
from blinter.checkers.warnings_compat import _check_compatibility_warnings
from blinter.constants import PSEUDO_ENV_VARS
from blinter.models import LintIssue
from blinter.parsing.structure import (
    _collect_empty_assigned_variables,
    _defined_vars_cache_var,
    _empty_assigned_vars_cache_var,
    _identity_cached,
    _paren_depth_before_line,
)
from blinter.patterns import _COMPILED_IF_PATTERN
from blinter.rules.registry import RULES


def _check_command_warnings(  # pylint: disable=unused-argument
    line: str, line_num: int, stripped: str
) -> List[LintIssue]:
    """Check for command-specific warning issues."""
    issues: List[LintIssue] = []

    # W006: Network operation without timeout
    if re.match(r"ping\s+[^-]*$", stripped, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W006"],
                context="PING command without timeout parameter",
            )
        )

    # W008: Permanent PATH modification
    if re.match(r"setx\s+path", stripped, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W008"],
                context="SETX modifies PATH permanently",
            )
        )

    issues.extend(_check_setx_equals_syntax(stripped, line_num))

    return issues


def _check_unquoted_variables(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for unquoted variables with spaces (W005).

    Only flags genuinely problematic cases:
    - IF string comparisons (==) with unquoted variables
    """
    issues: List[LintIssue] = []

    # Only check IF string comparisons with == operator
    # These are the most common source of issues with unquoted variables
    if_string_comp = re.search(
        r"\bif\s+(?:not\s+)?%[A-Z0-9_]+%\s*==\s*", stripped, re.IGNORECASE
    )
    if if_string_comp:
        # Don't flag if already quoted properly elsewhere in the comparison
        if not re.search(
            r'\bif\s+(?:not\s+)?"[^"]*%[A-Z0-9_]+%[^"]*"', stripped, re.IGNORECASE
        ):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["W005"],
                    context=(
                        "IF string comparison with unquoted variable "
                        "may fail if variable contains spaces"
                    ),
                )
            )

    return issues


def _check_non_ascii_chars(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for non-ASCII characters (W012)."""
    issues: List[LintIssue] = []
    if not all(ord(c) < 128 for c in stripped):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W012"],
                context="Line contains non-ASCII characters",
            )
        )
    return issues


def _check_errorlevel_comparison(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for errorlevel comparison semantic difference (W017)."""
    issues: List[LintIssue] = []
    w017_if_match = _COMPILED_IF_PATTERN.match(stripped)
    if not w017_if_match:
        return issues

    w017_group_result = w017_if_match.group(1)
    if w017_group_result is None:
        return issues

    w017_if_content: str = w017_group_result.strip()
    if re.search(r"&&|\|\|", w017_if_content):
        return issues
    if re.search(r"%errorlevel%\s+neq\s+1\b", w017_if_content, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W017"],
                context=(
                    "IF %ERRORLEVEL% NEQ 1 behaves differently than "
                    "IF NOT ERRORLEVEL 1"
                ),
            )
        )
    elif re.search(r"not\s+errorlevel\s+0\b", w017_if_content, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W017"],
                context=(
                    "IF NOT ERRORLEVEL 0 matches only negative exit codes "
                    "(NOT >= 0), not a general failure check"
                ),
            )
        )
    elif re.search(r"errorlevel\s+0\b", w017_if_content, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W017"],
                context=(
                    "IF ERRORLEVEL 0 is always true for native commands "
                    "(ERRORLEVEL n means >= n)"
                ),
            )
        )
    return issues


def _check_inefficient_modifiers(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for inefficient parameter modifier usage (W026)."""
    issues: List[LintIssue] = []
    inefficient_param_match: List[Tuple[str, str]] = re.findall(
        r"(%~[fdpnx][0-9]+%)\s*(%~[fdpnx][0-9]+%)", stripped, re.IGNORECASE
    )
    if inefficient_param_match:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W026"],
                context="Multiple parameter modifiers can be combined for efficiency",
            )
        )
    return issues


def _char_outside_cp437(char: str) -> bool:
    """Return True when a character cannot be represented in Code Page 437."""
    if ord(char) < 128:
        return False
    try:
        char.encode("cp437")
        return False
    except UnicodeEncodeError:
        return True


def _check_extended_non_ascii(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for characters outside Code Page 437 (W030)."""
    issues: List[LintIssue] = []
    outside_cp437 = {char for char in stripped if _char_outside_cp437(char)}
    if outside_cp437:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W030"],
                context=(
                    "Characters outside Code Page 437 detected: "
                    f"{''.join(sorted(outside_cp437))}"
                ),
            )
        )
    return issues


def _check_unicode_filenames(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for Unicode filename in batch operation (W031)."""
    issues: List[LintIssue] = []
    unicode_file_ops = ["copy", "move", "del", "type", "ren", "rename"]
    parts = stripped.split()
    first_word = parts[0].lower() if parts else ""
    if first_word in unicode_file_ops:
        # Look for non-ASCII characters in file paths
        if re.search(r"[^\x00-\x7F]", stripped):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["W031"],
                    context="File operation with Unicode filename may cause issues",
                )
            )
    return issues


def _check_set_spacing(stripped: str, line_num: int) -> List[LintIssue]:
    """Check SET command spacing around equals (W044)."""
    if re.match(r"set\s+(?!/)([^\s=]+)\s+=", stripped, re.IGNORECASE):
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["W044"],
                context="A space before = in SET is part of the variable name",
            )
        ]
    return []


def _is_pseudo_env_clear_assignment(var_name: str, value_part: str) -> bool:
    """True when SET clears a shadow pseudo-env var (SET \"errorlevel=\")."""
    return var_name in PSEUDO_ENV_VARS and value_part == ""


def _check_set_a_pseudo_env_assignment(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when SET /A assigns to a pseudo-environment variable (W049)."""
    match = re.match(
        r"set\s+/a\s+([^=]+)=(.*)$",
        stripped,
        re.IGNORECASE,
    )
    if not match:
        return []
    lhs = str(match.group(1)).strip()
    if not lhs:
        return []
    var_name = re.sub(r"\s+", "", lhs).upper()
    if var_name not in PSEUDO_ENV_VARS:
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W049"],
            context=(f"SET /A assigns to pseudo-environment variable {var_name}"),
        )
    ]


def _check_shift_inside_paren_block(
    stripped: str,
    line_num: int,
    lines: list[str],
) -> List[LintIssue]:
    """Warn when SHIFT runs inside a parenthesized block (W052)."""
    if not re.match(r"^\s*shift\b", stripped, re.IGNORECASE):
        return []
    if _paren_depth_before_line(lines, line_num) <= 0:
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W052"],
            context=(
                "SHIFT inside a parenthesized block does not affect %1-%9 "
                "expansion until after the block completes"
            ),
        )
    ]


def _check_bare_shift_mutates_pct0(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when bare SHIFT may replace %0 with the former %1 (W053)."""
    if not re.match(r"^\s*shift\s*$", stripped, re.IGNORECASE):
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W053"],
            context="Bare SHIFT copies %1 into %0; use SHIFT /1 to preserve the script name",
        )
    ]


def _check_invalid_shift_switch(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when SHIFT /n uses n outside the valid 0-8 range (W050)."""
    match = re.search(r"^\s*shift\s+/(\d+)\b", stripped, re.IGNORECASE)
    if not match:
        return []
    switch_value = int(match.group(1))
    if switch_value <= 8:
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W050"],
            context=(f"SHIFT /{switch_value} is invalid; /n must be between 0 and 8"),
        )
    ]


def _check_digit_prefixed_variable(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn on digit-prefixed SET names or ambiguous %digitName% expansion (W054)."""
    issues: List[LintIssue] = []

    def _append(var_name: str) -> None:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W054"],
                context=(
                    f"Variable name {var_name!r} starts with a digit; "
                    "% expansion resolves as a batch parameter plus literal text"
                ),
            )
        )

    quoted = re.match(r'set\s+"([^"]+)"', stripped, re.IGNORECASE)
    if quoted:
        assignment = str(quoted.group(1))
        if "=" in assignment:
            var_name = assignment.partition("=")[0].strip()
            if var_name and var_name[0].isdigit():
                _append(var_name)
                return issues

    unquoted = re.match(r"set\s+(?!/)([^\s=]+)\s*=", stripped, re.IGNORECASE)
    if unquoted:
        var_name = str(unquoted.group(1)).strip()
        if var_name and var_name[0].isdigit():
            _append(var_name)
            return issues

    set_a = re.match(r"set\s+/a\s+([^=]+)=", stripped, re.IGNORECASE)
    if set_a:
        lhs = str(set_a.group(1)).strip()
        var_match = re.match(r"([A-Za-z_]\w*|\d\w*)", lhs)
        if var_match:
            var_name = str(var_match.group(1))
            if var_name and var_name[0].isdigit():
                _append(var_name)
                return issues

    for match in re.finditer(
        r"%(~[fdpnxsatz]*)?(\d)([a-zA-Z_]\w*)%",
        stripped,
        re.IGNORECASE,
    ):
        suffix = str(match.group(3))
        if not suffix:
            continue
        start = match.start()
        if start > 0 and stripped[start - 1] == "%":
            continue
        prefix = stripped[:start]
        if re.search(r"%\w+:\s*$", prefix, re.IGNORECASE):
            continue
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W054"],
                context=(
                    f"%{match.group(2)}{suffix}% is parsed as %{match.group(2)} "
                    f"plus literal {suffix!r}, not a variable name"
                ),
            )
        )
        return issues

    return issues


def _check_double_digit_batch_param(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when a batch parameter uses two or more digits (W051)."""
    for match in re.finditer(r"%(~[fdpnxsatz]*)?(\d+)", stripped, re.IGNORECASE):
        digits = str(match.group(2))
        if len(digits) < 2:
            continue
        start = match.start()
        if start > 0 and stripped[start - 1] == "%":
            continue
        prefix = stripped[:start]
        if re.search(r"%\w+:\s*$", prefix, re.IGNORECASE):
            continue
        if re.match(r"%\w+:", stripped[start:], re.IGNORECASE):
            continue
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["W051"],
                context=(
                    f"%{digits} is not a valid parameter; cmd.exe parses it as "
                    f"%{digits[0]} plus literal '{digits[1:]}'"
                ),
            )
        ]
    return []


def _pseudo_env_assignment_issues(
    var_name: str, value_part: str, line_num: int
) -> List[LintIssue]:
    """Return W049 issues when SET assigns to a pseudo-environment variable."""
    if _is_pseudo_env_clear_assignment(var_name, value_part):
        return []
    if var_name not in PSEUDO_ENV_VARS:
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W049"],
            context=f"SET assigns to pseudo-environment variable {var_name}",
        )
    ]


def _check_pseudo_env_assignment(line: str, line_num: int) -> List[LintIssue]:
    """Warn when assigning to cmd.exe pseudo-environment variables (W049)."""
    command = line.rstrip("\r\n").lstrip()
    quoted = re.match(
        r'set\s+"([^"]+)"',
        command,
        re.IGNORECASE,
    )
    if quoted:
        assignment = str(quoted.group(1))
        if "=" not in assignment:
            return []
        var_name, _, value_part = assignment.partition("=")
        return _pseudo_env_assignment_issues(
            var_name.strip().upper(), value_part, line_num
        )

    unquoted = re.match(
        r"set\s+(?!/)([^\s=]+)\s*=(.*)$",
        command,
        re.IGNORECASE,
    )
    if not unquoted:
        return []
    return _pseudo_env_assignment_issues(
        str(unquoted.group(1)).strip().upper(),
        str(unquoted.group(2)),
        line_num,
    )


def _check_set_a_octal_literal(stripped: str, line_num: int) -> List[LintIssue]:
    """Check SET /A leading-zero octal literals (W045)."""
    if re.search(
        r"set\s+/a\s+[^=]*=\s*0[0-7]+\b",
        stripped,
        re.IGNORECASE,
    ):
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["W045"],
                context="SET /A interprets leading-zero values as octal",
            )
        ]
    return []


_LEADING_ZERO_LHS_RE = re.compile(
    r"\b0+\d+\b\s+(?:equ|neq|==|!=|lss|leq|gtr|geq)\b",
    re.IGNORECASE,
)
_LEADING_ZERO_RHS_RE = re.compile(
    r"\b(?:equ|neq|==|!=|lss|leq|gtr|geq)\s+0+\d+\b",
    re.IGNORECASE,
)


def _if_segment_has_leading_zero(segment: str) -> bool:
    """Return True when one IF command compares an unquoted leading-zero number."""
    body = segment.strip().lstrip("@").lstrip("(").strip()
    if not re.match(r"if\b", body, re.IGNORECASE):
        return False
    return (
        _LEADING_ZERO_LHS_RE.search(body) is not None
        or _LEADING_ZERO_RHS_RE.search(body) is not None
    )


def _check_unquoted_numeric_if_compare(stripped: str, line_num: int) -> List[LintIssue]:
    """Check unquoted IF numeric comparisons with leading zeros (W046)."""
    if "if" not in stripped.lower():
        return []
    masked = _strip_double_quoted_strings(stripped)
    if not any(
        _if_segment_has_leading_zero(part) for part in _split_amp_commands(masked)
    ):
        return []
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W046"],
            context="Unquoted numeric IF comparisons use numeric equality semantics",
        )
    ]


def _uppercased_defined_vars(set_vars: Set[str]) -> frozenset[str]:
    """Return uppercased defined variable names, cached per lint pass."""
    return _identity_cached(
        _defined_vars_cache_var.get(),
        set_vars,
        lambda: frozenset(name.upper() for name in set_vars),
    )


def _empty_assigned_vars_for_lines(lines: list[str]) -> FrozenSet[str]:
    """Return variables assigned empty values, cached per lint pass."""
    return _identity_cached(
        _empty_assigned_vars_cache_var.get(),
        lines,
        lambda: frozenset(_collect_empty_assigned_variables(lines)),
    )


_SUBSTRING_EXPANSION_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*):~[^%]+%")


def _check_substring_on_unset_var(
    stripped: str,
    line_num: int,
    set_vars: Set[str],
    *,
    lines: list[str] | None = None,
    empty_assigned_vars: FrozenSet[str] | None = None,
) -> List[LintIssue]:
    """Warn when substring expansion references undefined or empty variables (W047)."""
    if ":~" not in stripped:
        return []
    defined = _uppercased_defined_vars(set_vars)
    if empty_assigned_vars is None and lines is not None:
        empty_assigned_vars = _empty_assigned_vars_for_lines(lines)
    empty_vars = empty_assigned_vars or frozenset()
    for match in _SUBSTRING_EXPANSION_RE.finditer(stripped):
        var_name = str(match.group(1)).upper()
        if var_name in empty_vars:
            return [
                LintIssue(
                    line_number=line_num,
                    rule=RULES["W047"],
                    context=(
                        f"Substring expansion on empty variable %{var_name}% "
                        "expands literally (e.g. ~0,1)"
                    ),
                )
            ]
        if var_name in defined:
            continue
        # FOR loop variables (%%i in source) appear as %i% in parsed lines
        if len(var_name) == 1 and var_name.isalpha():
            continue
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["W047"],
                context=(
                    f"Substring expansion on undefined variable %{var_name}% "
                    "may expand literally"
                ),
            )
        ]
    return []


def _check_for_f_null_fields(stripped: str, line_num: int) -> List[LintIssue]:
    """Check FOR /F CSV parsing without honoring empty fields (W048)."""
    lowered = stripped.lower()
    if (
        lowered.startswith("for")
        and "/f" in lowered
        and "delims=," in lowered.replace(" ", "")
        and "tokens=*" not in lowered
        and "honoring" not in lowered
    ):
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["W048"],
                context="FOR /F with comma delimiters skips consecutive empty tokens by default",
            )
        ]
    return []


_PSEUDO_IF_LOGICAL_RE = re.compile(
    r"(?:"
    r"(?:EQU|NEQ|LSS|LEQ|GTR|GEQ|==|>=|<=|>|<)\s+\S+|"
    r"(?:exist|defined|errorlevel)\s+\S+"
    r")\s+(AND|OR)\s+"
    r"(?:%|!|defined|exist|not|errorlevel|/i|[\w(])",
    re.IGNORECASE,
)


def _strip_double_quoted_strings(text: str) -> str:
    """Remove double-quoted spans so pseudo-operator detection ignores string literals."""
    return re.sub(r'"[^"]*"', '""', text)


def _check_if_pseudo_logical_operator(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when IF uses pseudo AND/OR operators (W056)."""
    if not re.match(r"\bif\b", stripped, re.IGNORECASE):
        return []
    unquoted = _strip_double_quoted_strings(stripped)
    match = _PSEUDO_IF_LOGICAL_RE.search(unquoted)
    if not match:
        return []
    operator = str(match.group(1)).upper()
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W056"],
            context=(
                f"Batch has no {operator} operator in IF clauses; "
                "use nested IF statements instead"
            ),
        )
    ]


def _check_if_defined_percent_wrapped(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when IF DEFINED uses %var% instead of a bare name (W055)."""
    match = re.search(
        r"\bif\s+(?:/i\s+)?(?:not\s+)?defined\s+%([A-Za-z_@][\w@]*)%",
        stripped,
        re.IGNORECASE,
    )
    if not match:
        return []
    var_name = str(match.group(1))
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W055"],
            context=(
                f"IF DEFINED %{var_name}% checks the wrong name; "
                f"use IF DEFINED {var_name} without percent signs"
            ),
        )
    ]


_NON_BAT_COMMAND_PREFIXES: frozenset[str] = frozenset(
    {
        "call",
        "start",
        "echo",
        "rem",
        "goto",
        "if",
        "for",
        "set",
        "cd",
        "chdir",
        "pushd",
        "popd",
        "del",
        "erase",
        "copy",
        "move",
        "ren",
        "rename",
        "type",
        "find",
        "findstr",
        "pause",
        "exit",
        "shift",
        "endlocal",
        "setlocal",
        "title",
        "color",
        "cls",
        "break",
        "choice",
        "timeout",
        "ping",
        "dir",
        "md",
        "mkdir",
        "rd",
        "rmdir",
        "assoc",
        "ftype",
        "chcp",
        "doskey",
        "more",
        "sort",
        "fc",
        "ver",
        "vol",
        "tree",
        "xcopy",
        "robocopy",
        "wmic",
        "powershell",
        "pwsh",
        "cmd",
        "where",
        "sc",
        "net",
        "taskkill",
        "tasklist",
        "reg",
        "attrib",
        "cacls",
        "icacls",
    }
)


def _tokenize_setx_arguments(rest: str) -> list[str]:
    """Split SETX arguments into tokens (quoted strings or bare words)."""
    tokens: list[str] = []
    index = 0
    length = len(rest)
    while index < length:
        while index < length and rest[index].isspace():
            index += 1
        if index >= length:
            break
        if rest[index] == '"':
            end = rest.find('"', index + 1)
            if end == -1:
                tokens.append(rest[index:])
                break
            tokens.append(rest[index : end + 1])
            index = end + 1
            continue
        end = index
        while end < length and not rest[end].isspace():
            end += 1
        tokens.append(rest[index:end])
        index = end
    return tokens


def _check_setx_equals_syntax(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when SETX uses SET-style equals sign instead of space-delimited syntax (W060)."""
    if not re.match(r"setx\s+", stripped, re.IGNORECASE):
        return []
    rest = re.sub(r"^setx\s+", "", stripped, count=1, flags=re.IGNORECASE)
    for token in _tokenize_setx_arguments(rest):
        bare = token.strip('"')
        if bare.startswith("/"):
            continue
        if "=" in bare:
            return [
                LintIssue(
                    line_number=line_num,
                    rule=RULES["W060"],
                    context=(
                        "SETX uses space-delimited syntax (SETX var value), "
                        "not SET-style equals; cmd.exe reports invalid syntax"
                    ),
                )
            ]
        break
    return []


def _check_bat_invocation_without_call(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when a .bat/.cmd file is invoked without CALL (W057)."""
    if stripped.startswith("::"):
        return []
    normalized = stripped.lstrip("@").strip()
    if not normalized or normalized.lower().startswith("rem "):
        return []
    first_word_match = re.match(r"^(\S+)", normalized)
    if not first_word_match:
        return []
    first_word = str(first_word_match.group(1)).lower().rstrip(":")
    if first_word in _NON_BAT_COMMAND_PREFIXES:
        return []
    invoke_match = re.match(
        r'^(?:"([^"]+\.(?:bat|cmd))"|([^\s&|<>^]+\.(?:bat|cmd)))\b',
        normalized,
        re.IGNORECASE,
    )
    if not invoke_match:
        return []
    target = str(invoke_match.group(1) or invoke_match.group(2))
    return [
        LintIssue(
            line_number=line_num,
            rule=RULES["W057"],
            context=(
                f"Invoking {target!r} without CALL does not return control "
                "to the caller"
            ),
        )
    ]


def _check_ren_destination_path(stripped: str, line_num: int) -> List[LintIssue]:
    """Warn when REN/RENAME uses a path in the destination argument (W058)."""
    match = re.match(r"^(?:ren|rename)\s+(\S+)\s+(.+)$", stripped, re.IGNORECASE)
    if not match:
        return []
    destination = str(match.group(2)).strip()
    if destination.startswith('"'):
        quote_end = destination.find('"', 1)
        if quote_end == -1:
            new_name = destination[1:]
        else:
            new_name = destination[1:quote_end]
    else:
        new_name = destination.split()[0]
    if re.search(r"[:\\/]", new_name):
        return [
            LintIssue(
                line_number=line_num,
                rule=RULES["W058"],
                context=(
                    "REN destination must be a filename only; "
                    "use MOVE to relocate files to another directory"
                ),
            )
        ]
    return []


def _check_call_ambiguity(stripped: str, line_num: int) -> List[LintIssue]:
    """Check for command execution ambiguity (W033)."""
    issues: List[LintIssue] = []
    call_match = re.match(r"call\s+([^:\s]+)", stripped, re.IGNORECASE)
    if call_match:
        call_target: str = call_match.group(1)
        # Check if it's a filename without extension
        if not re.search(
            r"\.[a-z]{1,4}$", call_target.lower()
        ) and not call_target.startswith(":"):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["W033"],
                    context=f"CALL '{call_target}' without extension may be ambiguous with PATHEXT",
                )
            )
    return issues


def _check_warning_issues(
    line: str,
    line_num: int,
    _set_vars: Set[str],
    _delayed_expansion_enabled: bool,
    *,
    lines: list[str] | None = None,
    file_path: str = "",
) -> List[LintIssue]:
    """Check for warning level issues."""
    issues: List[LintIssue] = []
    stripped = line.strip()
    line_context = lines if lines is not None else []

    # Use helper functions to check for various warning issues
    issues.extend(_check_unquoted_variables(stripped, line_num))
    issues.extend(_check_non_ascii_chars(stripped, line_num))
    issues.extend(_check_errorlevel_comparison(stripped, line_num))
    issues.extend(_check_inefficient_modifiers(stripped, line_num))
    issues.extend(_check_extended_non_ascii(stripped, line_num))
    issues.extend(_check_unicode_filenames(stripped, line_num))
    issues.extend(_check_call_ambiguity(stripped, line_num))
    issues.extend(_check_set_spacing(stripped, line_num))
    issues.extend(_check_pseudo_env_assignment(line, line_num))
    issues.extend(_check_set_a_pseudo_env_assignment(stripped, line_num))
    issues.extend(_check_invalid_shift_switch(stripped, line_num))
    issues.extend(_check_shift_inside_paren_block(stripped, line_num, line_context))
    issues.extend(_check_bare_shift_mutates_pct0(stripped, line_num))
    issues.extend(_check_digit_prefixed_variable(stripped, line_num))
    issues.extend(_check_double_digit_batch_param(stripped, line_num))
    issues.extend(_check_set_a_octal_literal(stripped, line_num))
    issues.extend(_check_unquoted_numeric_if_compare(stripped, line_num))
    issues.extend(
        _check_substring_on_unset_var(
            stripped,
            line_num,
            _set_vars,
            lines=line_context or None,
        )
    )
    issues.extend(_check_for_f_null_fields(stripped, line_num))
    issues.extend(_check_if_defined_percent_wrapped(stripped, line_num))
    issues.extend(_check_if_pseudo_logical_operator(stripped, line_num))
    issues.extend(_check_bat_invocation_without_call(stripped, line_num))
    issues.extend(_check_ren_destination_path(stripped, line_num))
    issues.extend(_check_compatibility_warnings(line, line_num, stripped))
    issues.extend(_check_command_warnings(line, line_num, stripped))
    issues.extend(
        check_extended_warning_line(
            line,
            line_num,
            lines=line_context or None,
            file_path=file_path,
        )
    )

    return issues
