"""Security vulnerability line checks (SEC-prefix rules)."""

import re
from typing import (
    List,
    Optional,
)

from blinter.checkers.cmd_extended import (
    check_sec001_same_line,
    check_sec001_setp_dataflow,
)
from blinter.models import LintIssue
from blinter.parsing.context import (
    _is_command_in_safe_context,
    _is_comment_line,
    _is_safe_ctx_for_privilege,
)
from blinter.patterns import (
    _DANGEROUS_CMDS_REGEX,
    CREDENTIAL_PATTERNS,
    DANGEROUS_COMMAND_PATTERNS,
    SENSITIVE_ECHO_PATTERNS,
)
from blinter.rules.registry import RULES


def _in_order(*parts: str) -> str:
    """Return a search pattern requiring ``parts`` to appear in order.

    Equivalent to ``part1.*part2.*part3`` under ``re.search`` but linear in the
    line length: it is anchored, and each lazy segment is atomic so the engine
    never retries earlier segments. The leftmost occurrence of each part is
    always sufficient, so no match is lost.
    """
    return r"\A" + "".join(f"(?>.*?(?:{part}))" for part in parts)


_ADMIN_COMMANDS: tuple[str, ...] = ("reg add hklm", "reg delete hklm", "sc ")
_EXECUTION_POLICY_BYPASS_PATTERN = _in_order("powershell", r"-executionpolicy\s+bypass")
_HOSTS_REDIRECT_PATTERNS: tuple[str, ...] = (
    _in_order(">>", "hosts"),
    _in_order("echo", ">>", "drivers", "etc", "hosts"),
)
_AUTORUN_CREATION_PATTERNS: tuple[str, ...] = (
    _in_order("echo", ">", r"autorun\.inf"),
    _in_order("copy", r"autorun\.inf"),
)
_SELF_COPY_REMOVABLE_PATTERN = _in_order("xcopy", "%0", "[a-z]:")
_HARDCODED_TEMP_PATH_PATTERNS: tuple[str, ...] = (
    r"C:\temp",
    r"C:\tmp",
    r"/tmp",
)
_NET_PRIVILEGE_CHECK_PATTERNS: tuple[str, ...] = (
    r"net\s+session\s*>",  # net session redirected (used for checking)
    r"net\s+session\s*$",  # net session at end of line (used for checking)
)
_COMPOUND_SET_SPLIT = re.compile(r"&\s+set\s+", re.IGNORECASE)
_STRING_REPLACE_ONLY = re.compile(
    r"^[%!][A-Za-z0-9_@]+:[^%!]+[%!]$",
    re.IGNORECASE,
)
_HARDCODED_TEMP_PATH_BOUNDARY_BEFORE = frozenset(" \t\"'=")


def _matches_hardcoded_temp_path(stripped: str) -> bool:
    """Return True when ``stripped`` contains a hardcoded temp directory path."""
    lowered = stripped.lower()
    for temp_path in _HARDCODED_TEMP_PATH_PATTERNS:
        temp_lower = temp_path.lower()
        search_from = 0
        while True:
            pos = lowered.find(temp_lower, search_from)
            if pos == -1:
                break
            before_ok = (
                pos == 0 or stripped[pos - 1] in _HARDCODED_TEMP_PATH_BOUNDARY_BEFORE
            )
            after_pos = pos + len(temp_path)
            if after_pos >= len(stripped):
                after_ok = True
            elif temp_path.startswith("/"):
                after_ok = stripped[after_pos] in "/ \t\"'"
            else:
                after_ok = stripped[after_pos] in "\\ \t\"'"
            if before_ok and after_ok:
                return True
            search_from = pos + 1
    return False


def _first_set_value_text(var_val_text: str) -> str:
    """Return RHS of the first SET when a line chains ``set a=1& set b=2``."""
    match = _COMPOUND_SET_SPLIT.search(var_val_text)
    if match:
        return var_val_text[: match.start()]
    return var_val_text


def _is_safe_unquoted_set_value(var_val: str) -> bool:
    """Return True when an unquoted SET value is unlikely to need quoting."""
    if (
        _STRING_REPLACE_ONLY.match(var_val)
        or var_val == "%*"
        or re.search(r"%[A-Za-z0-9_]+:'.*'.*%", var_val)
    ):
        return True
    if " " in var_val or "\t" in var_val or re.search(r"[&|<>`;]", var_val):
        return False
    if re.match(r"^[\w.]+$", var_val) or var_val.lower().startswith(
        ("http://", "https://")
    ):
        return True
    return re.match(r"^[%!\w\\.:~\-,+/()=]+$", var_val) is not None


def _check_sec001_user_input_in_command(
    stripped: str, line_num: int
) -> Optional[LintIssue]:
    """SEC001: SET /P used unquoted on the same line."""
    return check_sec001_same_line(stripped, line_num)


def _check_sec002_unquoted_set(stripped: str, line_num: int) -> Optional[LintIssue]:
    """SEC002: Unsafe SET command usage."""
    set_match = re.match(r"set\s+([A-Za-z0-9_@]+)=(.+)", stripped, re.IGNORECASE)
    if not set_match:
        return None
    var_name: str = set_match.group(1)
    var_val_text: str = _first_set_value_text(set_match.group(2))
    var_val: str = var_val_text.strip()
    is_ansi_or_color = (
        "ESC" in var_name.upper()
        or "COLOR" in var_name.upper()
        or "%ESC%" in var_val
        or var_val.startswith("(")
        or var_val.upper().startswith("FOR ")
    )
    if (
        var_name.startswith("@")
        or is_ansi_or_color
        or _is_safe_unquoted_set_value(var_val)
        or (var_val.startswith('"') and var_val.endswith('"'))
    ):
        return None
    return LintIssue(
        line_number=line_num,
        rule=RULES["SEC002"],
        context="SET command value should be quoted for safety",
    )


def _check_sec003_dangerous_commands(
    line: str, stripped: str, line_num: int
) -> Optional[LintIssue]:
    """SEC003: Dangerous command without confirmation."""
    if _is_command_in_safe_context(line):
        return None
    for pattern, rule_code in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return LintIssue(
                line_number=line_num,
                rule=RULES[rule_code],
                context="Destructive command should have user confirmation",
            )
    return None


def _check_sec003_where_substitution(
    stripped: str, line_num: int
) -> Optional[LintIssue]:
    """SEC003: WHERE with dangerous commands in command substitution."""
    where_match = re.search(
        rf"where\s+({_DANGEROUS_CMDS_REGEX})", stripped, re.IGNORECASE
    )
    if not where_match:
        return None
    cmd = str(where_match.group(1)).upper()
    return LintIssue(
        line_number=line_num,
        rule=RULES["SEC003"],
        context=f"Checking for {cmd} command should have user confirmation",
    )


def _check_input_validation_sec(
    line: str, line_num: int, stripped: str
) -> List[LintIssue]:
    """Check for input validation and command security issues (SEC001-SEC003)."""
    issues: List[LintIssue] = []
    sec001 = _check_sec001_user_input_in_command(stripped, line_num)
    if sec001 is not None:
        issues.append(sec001)
    sec002 = _check_sec002_unquoted_set(stripped, line_num)
    if sec002 is not None:
        issues.append(sec002)
    sec003 = _check_sec003_dangerous_commands(line, stripped, line_num)
    if sec003 is not None:
        issues.append(sec003)
    if not _is_comment_line(line):
        where_issue = _check_sec003_where_substitution(stripped, line_num)
        if where_issue is not None:
            issues.append(where_issue)
    return issues


def _has_priv_check_before(lines: List[str], target_line_num: int) -> bool:
    """Check if there's a privilege check (net session) before the target line."""
    for _, line in enumerate(lines[: target_line_num - 1], start=1):
        stripped = line.strip().lower()
        if re.search(r"net\s+session\s*(>|$)", stripped):
            return True
    return False


def _should_skip_sec005(lines: Optional[List[str]], line_num: int) -> bool:
    """Return True when an earlier privilege check makes SEC005 unnecessary."""
    return bool(lines and _has_priv_check_before(lines, line_num))


def _append_sec005_issue(issues: List[LintIssue], line_num: int, context: str) -> None:
    """Append a SEC005 issue to the issues list."""
    issues.append(
        LintIssue(
            line_number=line_num,
            rule=RULES["SEC005"],
            context=context,
        )
    )


def _check_privilege_security(
    stripped: str, line_num: int, lines: Optional[List[str]] = None, line: str = ""
) -> List[LintIssue]:
    """Check for privilege escalation security issues (SEC005)."""
    issues: List[LintIssue] = []

    # Skip commands in safe contexts (comments, ECHO, SET statements)
    # Note: Uses privilege-specific safe context check that excludes IF DEFINED
    if line and _is_safe_ctx_for_privilege(line):
        return issues

    for cmd in _ADMIN_COMMANDS:
        if cmd in stripped.lower():
            if not _should_skip_sec005(lines, line_num):
                _append_sec005_issue(
                    issues,
                    line_num,
                    f"Command '{cmd.strip()}' may require administrator privileges",
                )
            break

    # Check for net commands that aren't privilege checks
    # Use word boundary to match "net" as a command, not as part of words like "internet"
    if re.search(r"\bnet\s+", stripped.lower()):
        is_privilege_check = any(
            re.search(pattern, stripped.lower())
            for pattern in _NET_PRIVILEGE_CHECK_PATTERNS
        )
        if not is_privilege_check and not _should_skip_sec005(lines, line_num):
            _append_sec005_issue(
                issues,
                line_num,
                "NET command may require administrator privileges",
            )

    return issues


def _check_path_security(line: str, stripped: str, line_num: int) -> List[LintIssue]:
    """Check for path-related security issues (SEC006-SEC007, SEC020)."""
    issues: List[LintIssue] = []

    # Skip ECHO statements, REM comments, and :: comments as these are typically
    # used for documentation/help text and don't perform actual file operations
    if _is_command_in_safe_context(line):
        return issues

    # CALL targets are script paths, not direct file operations on hardcoded paths
    if re.match(r"^\s*call\s+", stripped, re.IGNORECASE):
        return issues

    # SEC006: Hardcoded absolute path
    hardcoded_paths = [r"C:\\", r"D:\\", r"E:\\", r"/Users/", r"/home/"]
    for path_pattern in hardcoded_paths:
        if re.search(path_pattern, stripped):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["SEC006"],
                    context="Hardcoded absolute path may not exist on other systems",
                )
            )
            break

    # SEC007: Hardcoded temporary directory (patterns scanned by this rule, not runtime paths)
    if _matches_hardcoded_temp_path(stripped):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["SEC007"],
                context="Use %TEMP% instead of hardcoded temporary paths",
            )
        )

    # SEC020: UNC path without UAC elevation check
    unc_operations = ["pushd", "copy", "xcopy", "robocopy", "move"]
    parts = stripped.split()
    first_word = parts[0].lower() if parts else ""
    if first_word in unc_operations or re.search(r"\\\\[^\\]+\\", stripped):
        if "\\\\" in stripped:
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["SEC020"],
                    context="UNC path operation may fail under UAC without elevation check",
                )
            )

    return issues


def _check_info_disclosure_sec(
    line: str, stripped: str, line_num: int
) -> List[LintIssue]:
    """Check for information disclosure security issues (SEC008-SEC010)."""
    issues: List[LintIssue] = []

    # Skip REM/:: documentation lines only (SET and ECHO may still disclose secrets)
    if _is_comment_line(line):
        return issues

    # SEC008: Plain text credentials detected
    for pattern in CREDENTIAL_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["SEC008"],
                    context="Potential hardcoded credentials detected",
                )
            )
            break

    # SEC009: PowerShell execution policy bypass
    if re.search(_EXECUTION_POLICY_BYPASS_PATTERN, stripped, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["SEC009"],
                context="PowerShell execution policy bypass detected",
            )
        )

    # SEC010: Sensitive information in ECHO output
    for pattern in SENSITIVE_ECHO_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["SEC010"],
                    context="ECHO statement may display sensitive information",
                )
            )
            break

    return issues


_MALWARE_HIGH_CONFIDENCE_PATTERNS: tuple[str, ...] = (
    r"%systemroot%",
    r"drivers\\etc\\hosts",
    r"autorun\.inf",
    r'start\s+""\s*%0',
    r"start\s+%0",
    r"start\s+cmd\s*/c\s*%0",
    r"copy\s+%0\s+[a-z]:",
    _SELF_COPY_REMOVABLE_PATTERN,
)


def _is_malware_check_suppressed(line: str) -> bool:
    """Return True when malware heuristics should not run on a documentation line."""
    if _is_comment_line(line):
        return True
    stripped = line.strip().lower()
    if any(
        re.search(pattern, stripped, re.IGNORECASE)
        for pattern in _MALWARE_HIGH_CONFIDENCE_PATTERNS
    ):
        return False
    return _is_command_in_safe_context(line)


def _check_malware_security(line: str, stripped: str, line_num: int) -> List[LintIssue]:
    """Check for malware-like behavior security issues (SEC021-SEC024)."""
    issues: List[LintIssue] = []

    if _is_malware_check_suppressed(line):
        return issues

    # SEC021: Fork bomb pattern detected
    if (
        re.search(r'start\s+""\s*%0', stripped, re.IGNORECASE)
        or re.search(r"start\s+%0", stripped, re.IGNORECASE)
        or re.search(r"start\s+cmd\s*/c\s*%0", stripped, re.IGNORECASE)
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["SEC021"],
                context="Fork bomb pattern detected: recursive self-execution",
            )
        )

    # SEC022: Potential hosts file modification
    if any(
        re.search(pattern, stripped, re.IGNORECASE)
        for pattern in _HOSTS_REDIRECT_PATTERNS
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["SEC022"],
                context="Hosts file modification detected - potential DNS poisoning",
            )
        )

    # SEC023: Autorun.inf creation detected
    if any(
        re.search(pattern, stripped, re.IGNORECASE)
        for pattern in _AUTORUN_CREATION_PATTERNS
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["SEC023"],
                context="Autorun.inf creation detected - potential malware vector",
            )
        )

    # SEC024: Batch file copying itself to removable media
    if re.search(r"copy\s+%0\s+[a-z]:", stripped, re.IGNORECASE) or re.search(
        _SELF_COPY_REMOVABLE_PATTERN, stripped, re.IGNORECASE
    ):
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["SEC024"],
                context="Batch file copying itself to other drives - potential virus behavior",
            )
        )

    return issues


def _check_security_issues(
    line: str, line_num: int, lines: Optional[List[str]] = None
) -> List[LintIssue]:
    """Check for security level issues."""
    issues: List[LintIssue] = []
    stripped = line.strip()

    # Check different categories of security issues
    issues.extend(_check_input_validation_sec(line, line_num, stripped))
    issues.extend(_check_privilege_security(stripped, line_num, lines=lines, line=line))
    issues.extend(_check_path_security(line, stripped, line_num))
    issues.extend(_check_info_disclosure_sec(line, stripped, line_num))
    issues.extend(_check_malware_security(line, stripped, line_num))
    if lines is not None and line_num == 1:
        issues.extend(check_sec001_setp_dataflow(lines))

    return issues
