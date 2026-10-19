"""Advanced style, security, and performance rules."""

from contextvars import ContextVar
import re
from typing import (
    Dict,
    List,
    Optional,
    Tuple,
    cast,
)

from blinter.checkers.cmd_extended import (
    check_sec025_unquoted_cd,
    has_unquoted_user_args,
)
from blinter.constants import MAGIC_NUMBER_EXCEPTIONS
from blinter.models import LintIssue
from blinter.parsing.context import _is_comment_line
from blinter.parsing.structure import _is_in_subroutine_context
from blinter.patterns import SAFE_COMMAND_INJECTION_PATTERNS
from blinter.rules.registry import RULES

_REDIRECT_MACRO_VARS: frozenset[str] = frozenset(
    {
        "nul",
        "nul1",
        "nul2",
        "nul3",
        "nul6",
        "_silent",
        "psc",
        "ps",
        "red",
        "white",
        "gray",
        "grey",
        "blue",
        "yellow",
        "green",
        "magenta",
        "cyan",
        "black",
        "_red",
        "_yellow",
        "_gray",
        "_grey",
    }
)


_SEC011_PATH_OP_PATTERN = re.compile(r"\b(cd|copy|move|del)\b", re.IGNORECASE)
_SEC012_TEMP_FILE_PATTERN = re.compile(
    r"(%temp%|%tmp%|\\temp\\|\bc:\\temp\\).*\.(tmp|bat|cmd|exe)\b"
    r"|\.(tmp|bat|cmd|exe)\b.*(%temp%|%tmp%|\\temp\\|\bc:\\temp\\)",
    re.IGNORECASE,
)


def _has_path_traversal_risk(stripped: str) -> bool:
    """Return True when a line uses .. with a path-operation command."""
    if ".." not in stripped or _is_comment_line(stripped):
        return False
    return _SEC011_PATH_OP_PATTERN.search(stripped) is not None


def _has_unsafe_temp_creation(stripped: str) -> bool:
    """Return True when temp file creation lacks a randomness component."""
    lower = stripped.lower()
    if "%random%" in lower:
        return False
    return _SEC012_TEMP_FILE_PATTERN.search(stripped) is not None


def _has_unescaped_user_args(stripped: str) -> bool:
    """Return True when unquoted %1-%9, %*, %~1 or delayed equivalents appear."""
    if _is_comment_line(stripped):
        return False
    return has_unquoted_user_args(stripped)


def _check_sec014_unescaped_input(
    line: str, line_number: int, lines: List[str], labels: Dict[str, int]
) -> Optional[LintIssue]:
    """SEC014: Unescaped user input in command execution."""
    if _is_in_subroutine_context(lines, line_number, labels):
        return None
    stripped = line.strip()
    if not _has_unescaped_user_args(stripped):
        return None
    return LintIssue(
        line_number,
        RULES["SEC014"],
        context='Quote user arguments, for example "%~1"',
    )


def _check_sec017_predictable_temp(line: str, line_number: int) -> Optional[LintIssue]:
    """SEC017: Temporary file creation in predictable location."""
    stripped = line.strip()
    lowered = stripped.lower()
    if "temp" not in lowered or (".tmp" not in stripped and ".temp" not in stripped):
        return None
    if "%random%" in lowered or "%time%" in lowered:
        return None
    return LintIssue(
        line_number,
        RULES["SEC017"],
        context="Temp files should use %RANDOM% or timestamp",
    )


_SEC018_REDIRECTION_PATTERNS: tuple[str, ...] = (
    r">\s*c:\\temp",
    r">\s*c:\\windows\\temp",
    r">\s*\\\\.*\\share",
)


def _check_sec018_insecure_redirection(
    line: str, line_number: int
) -> Optional[LintIssue]:
    """SEC018: Command output redirection to insecure location."""
    stripped_lower = line.strip().lower()
    for pattern in _SEC018_REDIRECTION_PATTERNS:
        if re.search(pattern, stripped_lower):
            return LintIssue(
                line_number,
                RULES["SEC018"],
                context="Output redirected to potentially insecure location",
            )
    return None


def _check_advanced_security(
    line: str, line_number: int, lines: List[str], labels: Dict[str, int]
) -> List[LintIssue]:
    """Check for advanced security patterns."""
    issues: List[LintIssue] = []
    sec014 = _check_sec014_unescaped_input(line, line_number, lines, labels)
    if sec014 is not None:
        issues.append(sec014)
    issues.extend(check_sec025_unquoted_cd(line, line_number))
    sec017 = _check_sec017_predictable_temp(line, line_number)
    if sec017 is not None:
        issues.append(sec017)
    sec018 = _check_sec018_insecure_redirection(line, line_number)
    if sec018 is not None:
        issues.append(sec018)
    return issues


def _check_for_block_performance(
    lines: List[str], line_number: int, line: str, stripped: str
) -> List[LintIssue]:
    """Check performance issues that apply inside FOR loop blocks."""
    issues: List[LintIssue] = []
    if not _line_is_inside_for_block(lines, line_number):
        return issues

    if re.search(r"set\s+\w+=.*%", stripped) and "set /a" not in stripped:
        issues.append(
            LintIssue(
                line_number,
                RULES["P016"],
                context="String concatenation inside FOR loop is inefficient",
            )
        )
    if re.search(r"![^!]+!", line) and stripped.count("!") >= 4:
        issues.append(
            LintIssue(
                line_number,
                RULES["P019"],
                context="Excessive delayed expansion inside FOR loop",
            )
        )
    if re.search(r">\s*nul", stripped) or re.search(r"2>\s*nul", stripped):
        issues.append(
            LintIssue(
                line_number,
                RULES["P022"],
                context="Output redirection inside loop adds I/O overhead",
            )
        )
    if stripped.startswith("set /a"):
        issues.append(
            LintIssue(
                line_number,
                RULES["P023"],
                context="Complex SET /A inside loop; use intermediate variables",
            )
        )
    return issues


def _check_advanced_performance(
    lines: List[str], line_number: int, line: str
) -> List[LintIssue]:
    """Check for performance patterns."""
    issues: List[LintIssue] = []
    stripped = line.strip().lower()

    # P017: Repeated file existence checks
    if stripped.startswith("if exist"):
        filename_match = re.search(r'if exist\s+(["\']?)([^"\'\s]+)\1', stripped)
        if filename_match:
            filename = filename_match.group(2)
            # Count occurrences of the same file check in surrounding lines
            check_range = max(0, line_number - 5), min(len(lines), line_number + 5)
            same_checks = 0
            for i in range(check_range[0], check_range[1]):
                if i != line_number - 1 and filename in lines[i].lower():
                    same_checks += 1
            if same_checks >= 2:
                issues.append(
                    LintIssue(
                        line_number,
                        RULES["P017"],
                        context=f"File '{filename}' checked multiple times",
                    )
                )

    # P020: Redundant command echoing suppression
    if stripped.startswith("@echo off") and line_number > 1:
        issues.append(
            LintIssue(
                line_number,
                RULES["P020"],
                context="@ECHO OFF should only appear once at script start",
            )
        )

    # P021: Inefficient process checking pattern
    if stripped.startswith("tasklist") and "/fi" not in stripped:
        issues.append(
            LintIssue(
                line_number,
                RULES["P021"],
                context="TASKLIST should use /FI filters for efficiency",
            )
        )

    in_for_block = _line_is_inside_for_block(lines, line_number)
    issues.extend(
        _check_for_block_performance(lines, line_number, line, stripped)
        if in_for_block
        else []
    )

    if stripped.startswith("for /r") and "*.*" in stripped:
        issues.append(
            LintIssue(
                line_number,
                RULES["P018"],
                context="FOR /R with *.* traverses unnecessary files",
            )
        )

    if "*.*" in stripped and any(
        stripped.startswith(prefix) for prefix in ("del ", "copy ", "for ")
    ):
        issues.append(
            LintIssue(
                line_number,
                RULES["P025"],
                context="Use specific extensions instead of *.* wildcard",
            )
        )

    return issues


_ForBlockSlot = Tuple[List[str], List[bool]]
_for_block_cache_var: ContextVar[Optional[_ForBlockSlot]] = ContextVar(
    "for_block_membership",
    default=None,
)


def _next_paren_depth(depth: int, line: str) -> int:
    """Return parenthesis depth after ``line``, never below zero."""
    lowered = line.strip().lower()
    return max(depth + lowered.count("(") - lowered.count(")"), 0)


def _build_inside_for_block(lines: List[str]) -> List[bool]:
    """Mark lines that belong to a FOR statement.

    A one-line ``for ... do`` command is inside only on that line. A
    parenthesized body stays inside through its closing parenthesis.
    Lines after the block are outside, including an else-branch that follows.
    """
    flags: List[bool] = []
    depth = 0
    resume_depth: Optional[int] = None
    for line in lines:
        lowered = line.strip().lower()
        if resume_depth is None and lowered.startswith("for "):
            flags.append(True)
            depth_before = depth
            depth = _next_paren_depth(depth, line)
            if depth > depth_before:
                resume_depth = depth_before
            continue
        if resume_depth is None:
            flags.append(False)
            depth = _next_paren_depth(depth, line)
            continue
        flags.append(True)
        depth = _next_paren_depth(depth, line)
        if depth <= resume_depth:
            resume_depth = None
    return flags


def _inside_for_block_flags(lines: List[str]) -> List[bool]:
    """Return one scan of ``lines``, reused until a different list is checked.

    The slot holds the list object so a recycled ``id`` cannot serve stale flags.
    """
    cached = _for_block_cache_var.get()
    if cached is not None and cached[0] is lines:
        return cached[1]
    flags = _build_inside_for_block(lines)
    _for_block_cache_var.set((lines, flags))
    return flags


def _line_is_inside_for_block(lines: List[str], line_number: int) -> bool:
    """Return True when line_number appears inside a FOR loop block."""
    if line_number < 1:
        return False
    return _inside_for_block_flags(lines)[line_number - 1]


def _timeout_lacks_explanation(
    lines: List[str], line_number: int, timeout_value: int
) -> bool:
    """Return True when a large TIMEOUT value has no nearby comment."""
    if timeout_value <= 10:
        return False
    for check_line in (line_number - 2, line_number - 1, line_number):
        if 0 <= check_line - 1 < len(lines) and _is_comment_line(lines[check_line - 1]):
            return False
    return True


def _group_has_unquoted_chain(text: str) -> bool:
    """Return True when ``text`` contains ``&`` or ``|`` outside quotes."""
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in '"`':
            quote = char
            index += 1
            continue
        if char == "^" and index + 1 < len(text):
            index += 2
            continue
        if char in "&|":
            return True
        index += 1
    return False


def _is_simple_parenthesized_if(stripped: str) -> bool:
    """Return True for an IF whose only parentheses wrap one command."""
    if not re.match(r"^\s*if\s+.+\)\s*$", stripped) or "(" not in stripped:
        return False
    inner = re.sub(r"^\s*if\s+", "", stripped, flags=re.IGNORECASE)
    if inner.count("(") != 1:
        return False
    open_at = inner.find("(")
    close_at = inner.rfind(")")
    if close_at <= open_at:
        return False
    return not _group_has_unquoted_chain(inner[open_at + 1 : close_at])


def _check_advanced_style_patterns(
    line: str, line_number: int, lines: List[str]
) -> List[LintIssue]:
    """Check for advanced style patterns."""
    issues: List[LintIssue] = []
    stripped = line.strip()

    timeout_match = re.search(r"timeout\s+/t\s+(\d+)", stripped.lower())
    if timeout_match and _timeout_lacks_explanation(
        lines, line_number, int(timeout_match.group(1))
    ):
        timeout_value = int(timeout_match.group(1))
        issues.append(
            LintIssue(
                line_number,
                RULES["S023"],
                context=f"Timeout value {timeout_value} needs explanation",
            )
        )

    # S024: Complex one-liner should be split
    if len(stripped) > 80 and ("&&" in stripped or "||" in stripped):
        if "^" not in stripped:  # No continuation used
            issues.append(
                LintIssue(
                    line_number,
                    RULES["S024"],
                    context="Complex command should be split using continuation character",
                )
            )

    # S026: Inconsistent continuation character usage
    if "^" in stripped and not stripped.endswith("^"):
        # Check for improper continuation usage (exclude escape sequences)
        # In batch files, ^ is used for both line continuation AND escaping special chars
        # Only flag if it appears to be a continuation character, not an escape character
        if stripped.count("^") == 1 and not re.search(r"\^\s*$", line):
            # Check if ^ is used as escape character (followed by special char)
            # Special chars that can be escaped: & | ( ) < > ^ " space tab
            if not re.search(r"\^[&|()<>^\"\s]", stripped):
                issues.append(
                    LintIssue(
                        line_number,
                        RULES["S026"],
                        context="Continuation character should be at line end",
                    )
                )

    # S027: Missing blank lines around code blocks
    if re.match(r"^\s*:[a-zA-Z_]", stripped):
        prev_idx = line_number - 2
        if 0 <= prev_idx < len(lines):
            prev_line = lines[prev_idx].strip()
            if prev_line and not _is_comment_line(lines[prev_idx]):
                issues.append(
                    LintIssue(
                        line_number,
                        RULES["S027"],
                        context="Add a blank line before subroutine or block label",
                    )
                )

    # S028: Redundant parentheses in simple commands
    if _is_simple_parenthesized_if(stripped):
        issues.append(
            LintIssue(
                line_number,
                RULES["S028"],
                context="Simple IF command does not need parentheses",
            )
        )

    return issues


def _check_variable_naming(
    line: str, line_number: int, variables_seen: Dict[str, str]
) -> List[LintIssue]:
    """Check variable naming consistency (S017)."""
    issues: List[LintIssue] = []
    # Find SET commands with both quoted and unquoted variable names
    var_matches: List[re.Match[str]] = []
    set_patterns = [
        r"set\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=",  # Regular set: set VAR=value
        r'set\s+"([a-zA-Z_][a-zA-Z0-9_]*)\s*=',  # Quoted set: set "VAR=value"
    ]
    for pattern in set_patterns:
        matches = list(re.finditer(pattern, line, re.IGNORECASE))
        var_matches.extend(matches)

    for match in var_matches:
        var_name = str(match.group(1))
        if var_name.isupper():
            case_style = "upper"
        elif var_name.islower():
            case_style = "lower"
        else:
            case_style = "mixed"

        if var_name.upper() in variables_seen:
            if variables_seen[var_name.upper()] != case_style:
                issues.append(
                    LintIssue(
                        line_number=line_number,
                        rule=RULES["S017"],
                        context=f"Inconsistent case for variable {var_name}",
                    )
                )
        else:
            variables_seen[var_name.upper()] = case_style

    return issues


def _check_function_docs(
    line: str, line_number: int, lines: List[str]
) -> List[LintIssue]:
    """Check for function documentation (S018) - hybrid implementation."""
    issues: List[LintIssue] = []

    stripped = line.strip()
    # Match all labels (subroutines) - pattern: :LabelName
    if re.match(r"\s*:[a-zA-Z_][a-zA-Z0-9_]*\s*$", stripped):
        # Found a label that might be a subroutine
        # Check if previous 3 lines have documentation (more focused than 5)
        doc_found = False
        for j in range(max(0, line_number - 3), line_number - 1):
            if j < len(lines) and _is_comment_line(lines[j]):
                doc_found = True
                break

        if not doc_found:
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["S018"],
                    context="Function/subroutine lacks documentation",
                )
            )

    return issues


def _find_set_exclusion_ranges(line: str) -> List[Tuple[int, int]]:
    """
    Find exclusion ranges for SET statements in a line.

    Args:
        line: The line to analyze

    Returns:
        List of (start, end) tuples representing character ranges to exclude from checks
    """
    # Pattern matches: SET VAR=value, SET /A VAR=value, including in IF statements
    # We want to skip checking the value part after the = sign
    set_pattern = r"\bSET\s+(?:/A\s+)?([A-Z_@#$][A-Z0-9_@#$]*)\s*="

    # Find all SET statement positions to create exclusion zones
    exclusion_ranges: List[Tuple[int, int]] = []
    for set_match in re.finditer(set_pattern, line, re.IGNORECASE):
        # Find the equals sign position
        equals_pos = set_match.end() - 1

        # The exclusion zone starts right after the equals sign and goes to:
        # 1. End of line
        # 2. Next SET statement
        # 3. Closing parenthesis (for IF statements)
        # 4. Start of next command (via & or |)

        search_start = equals_pos + 1
        end_pos = len(line)

        # Look for terminators after the equals sign
        remainder = line[search_start:]

        # Find the earliest terminator
        # Check for command separators (but not in quoted strings)
        # Simple heuristic: look for & or | that aren't inside quotes
        for i, char in enumerate(remainder):
            if char in ("&", "|", ")"):
                # Check if we're inside quotes (simple check)
                before = remainder[:i]
                if before.count('"') % 2 == 0:  # Even number of quotes = not in string
                    end_pos = search_start + i
                    break

        exclusion_ranges.append((search_start, end_pos))

    return exclusion_ranges


def _is_number_in_special_context(
    immediate_before: str, immediate_after: str, context_before: str, context_after: str
) -> bool:
    """
    Check if a number is in a special context (GUID, path, math expr) and should be skipped.

    Args:
        immediate_before: Last 2 chars before number (stripped)
        immediate_after: First 2 chars after number (stripped)
        context_before: Full text before number
        context_after: Full text after number

    Returns:
        True if number should be skipped, False otherwise
    """
    # Check for GUID or identifier pattern: dash/brace immediately adjacent
    has_guid_before = immediate_before and immediate_before[-1] in ["-", "{"]
    has_guid_after = immediate_after and immediate_after[0] in ["-", "}"]

    # Check for file path: backslash or forward slash immediately adjacent
    has_path_before = immediate_before and immediate_before[-1] in ["\\", "/"]
    has_path_after = immediate_after and immediate_after[0] in ["\\", "/"]

    # Check if it's in a PowerShell math expression context
    context_lower = context_before.lower()
    in_math_round = "round(" in context_lower and ")" in context_after
    in_math_class = "[math]::" in context_lower

    return (
        has_guid_before
        or has_guid_after
        or has_path_before
        or has_path_after
        or in_math_round
        or in_math_class
    )


def _check_magic_numbers(line: str, line_number: int) -> List[LintIssue]:
    """Check for magic numbers (S019)."""
    # Skip comment lines - magic numbers in comments are documentation, not code
    if _is_comment_line(line):
        return []

    issues: List[LintIssue] = []
    number_pattern = r"\b(?<!%)\d{2,}\b(?!%)"

    # Find SET statement exclusion zones
    exclusion_ranges = _find_set_exclusion_ranges(line)

    for match in re.finditer(number_pattern, line):
        number = match.group(0)
        match_start = match.start()

        # Skip if this number is within a SET statement's value assignment
        if any(start <= match_start < end for start, end in exclusion_ranges):
            continue

        # Get context around the number
        context_before = line[: match.start()]
        context_after = line[match.end() :]
        immediate_before = context_before[-2:].strip()
        immediate_after = context_after[:2].strip()

        # Skip if in special context (GUID, path, math expression)
        if _is_number_in_special_context(
            immediate_before, immediate_after, context_before, context_after
        ):
            continue

        # Check if number is a common exception
        if number not in MAGIC_NUMBER_EXCEPTIONS:
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["S019"],
                    context=f"Magic number {number} should be defined as constant",
                )
            )

    return issues


def _check_line_length(
    line: str, line_number: int, max_line_length: int = 100
) -> List[LintIssue]:
    """Check for long lines (S020)."""
    issues: List[LintIssue] = []

    line_body = line.rstrip("\r\n")
    line_length = len(line_body)
    if line_length > max_line_length and not line_body.rstrip().endswith("^"):
        issues.append(
            LintIssue(
                line_number=line_number,
                rule=RULES["S020"],
                context=f"Line length {line_length} exceeds {max_line_length} characters",
            )
        )

    return issues


def _check_advanced_style_rules(
    lines: List[str], max_line_length: int = 100
) -> List[LintIssue]:
    """Check for advanced style and best practice issues (S017-S020)."""
    issues: List[LintIssue] = []
    variables_seen: Dict[str, str] = {}  # var_name -> case_style

    for i, line in enumerate(lines, start=1):
        issues.extend(_check_variable_naming(line, i, variables_seen))
        issues.extend(_check_function_docs(line, i, lines))
        issues.extend(_check_magic_numbers(line, i))
        issues.extend(_check_line_length(line, i, max_line_length))

    return issues


def _get_safe_system_variables() -> List[str]:
    """Return list of safe system variables that don't pose injection risks."""
    return [
        "SystemDrive",
        "SystemRoot",
        "Windows",
        "WinDir",
        "ProgramFiles",
        "ProgramData",
        "CommonProgramFiles",
        "UserProfile",
        "AppData",
        "LocalAppData",
        "Temp",
        "TMP",
        "ComSpec",
        "Path",
        "PathExt",
        "Processor_Architecture",
        "Number_Of_Processors",
        "OS",
        "HomeDrive",
        "HomePath",
        "Public",
        "AllUsersProfile",
        "CommonProgramW6432",
        "ProgramFiles(x86)",
        "CommonProgramFiles(x86)",
    ]


def _uses_only_system_variables(stripped: str) -> bool:
    """Return True when expanded variables are system or redirect macros."""
    system_variables = {name.lower() for name in _get_safe_system_variables()}
    variables_in_line: List[str] = cast(
        List[str], re.findall(r"%([a-zA-Z_][a-zA-Z0-9_()]*)%", stripped)
    )
    return all(
        var.lower() in system_variables
        or var.lower() in _REDIRECT_MACRO_VARS
        or var.startswith("~")
        or var.isdigit()
        for var in variables_in_line
    )


def _has_unsafe_command_chaining(stripped: str) -> bool:
    """Return True when & or | chain commands beyond I/O redirection."""
    potential_chaining: List[str] = cast(List[str], re.findall(r"[&|]", stripped))
    for match in potential_chaining:
        match_pos = stripped.find(match)
        context = stripped[max(0, match_pos - 3) : match_pos + 3]
        if "2>&1" not in context and ">&1" not in context:
            return True
    return False


def _is_safe_file_redirection_only(stripped: str) -> bool:
    """Return True for file operations that only redirect output."""
    is_file_operation = bool(
        re.search(
            r"\b(del|copy|move|type|xcopy|rd|md|mkdir|rmdir)\b", stripped, re.IGNORECASE
        )
    )
    has_only_redirection = bool(re.search(r">.*$", stripped))
    return (
        is_file_operation
        and has_only_redirection
        and not _has_unsafe_command_chaining(stripped)
    )


def _is_safe_installer_style_redirection(stripped: str) -> bool:
    """Return True for script-controlled commands that only redirect output."""
    if re.search(r"\bfor\s+/f\b.*\bpowershell\b.*-file\b", stripped, re.IGNORECASE):
        return True
    if re.search(
        r'^"[^"]*(?:%[a-zA-Z_][a-zA-Z0-9_]*%|![^!]+!)[^"]*\.exe"[^&|]*(?:>|\^>)',
        stripped,
        re.IGNORECASE,
    ):
        return not _has_unsafe_command_chaining(stripped)
    if re.search(r"\bcurl\b", stripped, re.IGNORECASE) and re.search(
        r"(?:>|\^>|2>&1)", stripped
    ):
        return not _has_unsafe_command_chaining(stripped)
    if re.search(r"\bfor\s+/f\b.*\b(dir|powershell)\b", stripped, re.IGNORECASE):
        return True
    return False


def _unquoted_percent_var_spans(stripped: str) -> List[Tuple[int, int]]:
    """Return spans of ``%VAR%`` that are outside quotes."""
    spans: List[Tuple[int, int]] = []
    quote = ""
    index = 0
    length = len(stripped)
    while index < length:
        char = stripped[index]
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char == "^" and index + 1 < length:
            index += 2
            continue
        if char in '"`':
            quote = char
            index += 1
            continue
        if char == "%":
            match = re.match(r"%[A-Za-z_][A-Za-z0-9_]*%", stripped[index:])
            if match:
                end = index + match.end()
                spans.append((index, end))
                index = end
                continue
        index += 1
    return spans


def _percent_var_is_command(stripped: str, start: int) -> bool:
    """Return True when ``%VAR%`` is the command token, not an argument."""
    prefix = stripped[:start].strip()
    if not prefix or prefix == "@":
        return True
    return prefix.rstrip().endswith(("&", "|", "("))


def _percent_var_touches_operator(stripped: str, start: int, end: int) -> bool:
    """Return True when an unquoted variable sits next to a shell operator."""
    left = start - 1
    while left >= 0 and stripped[left].isspace():
        left -= 1
    if left >= 0 and stripped[left] in "&|<>":
        return True
    right = end
    while right < len(stripped) and stripped[right].isspace():
        right += 1
    return right < len(stripped) and stripped[right] in "&|<>"


def _has_unquoted_injection_var(stripped: str) -> bool:
    """Return True when an unquoted variable can inject a shell operator."""
    for start, end in _unquoted_percent_var_spans(stripped):
        if _percent_var_is_command(stripped, start) or _percent_var_touches_operator(
            stripped, start, end
        ):
            return True
    return False


def _is_safe_command_injection(stripped: str) -> bool:
    """Check if a command with variables is safe from injection attacks."""
    if _uses_only_system_variables(stripped):
        return True
    if _is_safe_installer_style_redirection(stripped):
        return True
    if any(
        re.search(pattern, stripped, re.IGNORECASE)
        for pattern in SAFE_COMMAND_INJECTION_PATTERNS
    ):
        return True
    return _is_safe_file_redirection_only(stripped)


def _check_enhanced_security_rules(lines: List[str]) -> List[LintIssue]:
    """Check for enhanced security issues (SEC011-SEC013)."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Check for path traversal (SEC011)
        if _has_path_traversal_risk(stripped):
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["SEC011"],
                    context="Path contains .. which may allow directory traversal",
                )
            )

        # Check for unsafe temp file creation (SEC012)
        if _has_unsafe_temp_creation(stripped):
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["SEC012"],
                    context="Temp file creation without random component",
                )
            )

        # Check for command injection via variables (SEC013)
        # Exclude echo statements as they are generally safe for output
        if _has_unquoted_injection_var(stripped):
            # Skip echo statements - they are safe for variable expansion
            if not re.match(r"\s*echo\s+", stripped, re.IGNORECASE):
                if not _is_safe_command_injection(stripped):
                    issues.append(
                        LintIssue(
                            line_number=i,
                            rule=RULES["SEC013"],
                            context="Variable used with shell operators may allow injection",
                        )
                    )

    return issues


def _check_unnecessary_output_p014(
    lines: List[str], i: int, stripped: str
) -> Optional[LintIssue]:
    """Check for unnecessary output in non-interactive context (P014)."""
    # Only flag TYPE and DIR commands - ECHO is typically intentional user communication
    noisy_commands = ["type", "dir"]

    for cmd in noisy_commands:
        if re.match(rf"\s*{cmd}\s+", stripped, re.IGNORECASE):
            if ">nul" not in stripped.lower() and ">" not in stripped:
                # Check if nearby lines suggest interactive context
                nearby_interactive = _has_nearby_interactive_cmds(lines, i)

                if not nearby_interactive:
                    return LintIssue(
                        line_number=i,
                        rule=RULES["P014"],
                        context=(
                            f"{cmd.upper()} output may be unnecessary in "
                            "non-interactive context"
                        ),
                    )
    return None


def _has_nearby_interactive_cmds(lines: List[str], line_index: int) -> bool:
    """Check if there are interactive commands near the given line."""
    interactive_keywords = ["pause", "timeout", "set /p", "choice"]

    for j in range(max(0, line_index - 3), min(len(lines), line_index + 4)):
        nearby_line = lines[j].lower() if j < len(lines) else ""
        if any(keyword in nearby_line for keyword in interactive_keywords):
            return True
    return False


def _check_enhanced_performance(lines: List[str]) -> List[LintIssue]:
    """Check for enhanced performance issues (P012-P014)."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Check DIR without /B for performance (P013)
        if re.match(r"\s*dir\s+(?!.*\/b)", stripped, re.IGNORECASE):
            if "|" in stripped or ">" in stripped:  # Output is being processed
                issues.append(
                    LintIssue(
                        line_number=i,
                        rule=RULES["P013"],
                        context="DIR output processed - consider /B flag for performance",
                    )
                )

        # Check for unnecessary output (P014)
        p014_issue = _check_unnecessary_output_p014(lines, i, stripped)
        if p014_issue:
            issues.append(p014_issue)

        # P012: Inefficient string operations (multiple substring ops on one line)
        subst_ops = cast(
            List[str],
            re.findall(r"%[^%]*:[^%]*%", stripped, re.IGNORECASE),
        )
        if len(subst_ops) >= 2:
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["P012"],
                    context="Multiple string substitution operations on one line",
                )
            )

    return issues
