"""Whole-script analysis: globals, nesting, and documentation patterns."""

from collections import defaultdict
from pathlib import Path
import re
from typing import (
    DefaultDict,
    Dict,
    List,
    Tuple,
)

from blinter.checkers.globals.for_scope import (
    _check_for_var_case_mismatch,
)
from blinter.constants import LARGE_FILE_LINE_THRESHOLD
from blinter.models import LintIssue
from blinter.parsing.context import (
    _command_segments,
    _goto_and_call_label_names,
    _is_comment_line,
    _is_endlocal_command,
    _is_setlocal_command,
    _iter_goto_label_refs,
)
from blinter.rules.helpers import _add_issue
from blinter.rules.registry import RULES


def _check_global_style_rules(lines: List[str], file_path: str) -> List[LintIssue]:
    """Check global style rules that apply to the entire file."""
    issues: List[LintIssue] = []

    if not lines:
        return issues
    # S001: Missing @ECHO OFF at file start
    if not lines[0].strip().lower().startswith("@echo off"):
        issues.append(
            LintIssue(
                line_number=1,
                rule=RULES["S001"],
                context="Script should start with @ECHO OFF",
            )
        )

    # S002: ECHO OFF without @ prefix
    first_line = lines[0].strip().lower()
    if first_line.startswith("echo off") and not first_line.startswith("@echo off"):
        issues.append(
            LintIssue(
                line_number=1,
                rule=RULES["S002"],
                context="Use @ECHO OFF instead of ECHO OFF",
            )
        )

    # S007: File extension recommendation
    if file_path.lower().endswith(".bat"):
        issues.append(
            LintIssue(
                line_number=1,
                rule=RULES["S007"],
                context="Consider using .cmd extension instead of .bat for scripts "
                "targeting Windows 2000 and newer",
            )
        )

    # S015: Inconsistent colon usage in GOTO statements
    issues.extend(_check_goto_colon_consistency(lines))

    # S010: Unused labels
    issues.extend(_check_unused_labels(lines))

    return issues


# A FOR prefix ends at its first DO, so the command it runs is the jump or nothing.
_COMPUTED_JUMP_RE = re.compile(
    r"(?:for\b(?:(?!\bdo\s).)*\bdo\s+)?(?:\(\s*)?"
    r"(?:goto(?:\s+:?|:)|call\s+:)([^\s%!]*)[%!]",
    re.IGNORECASE,
)


def _computed_jump_prefixes(lines: List[str]) -> set[str]:
    """Return the literal start of each computed GOTO or CALL target, lowercased.

    ``goto %ACTION%`` can reach any label and ``goto case_%1`` any label starting
    with ``case_``.
    """
    prefixes: set[str] = set()
    for line in lines:
        for segment in _command_segments(line):
            match = _COMPUTED_JUMP_RE.match(segment)
            if match:
                prefixes.add(str(match.group(1)).lower())
    return prefixes


def _check_unused_labels(lines: List[str]) -> List[LintIssue]:
    """Check for labels that are never referenced by GOTO or CALL (S010)."""
    issues: List[LintIssue] = []
    labels: Dict[str, int] = {}
    referenced: set[str] = set()

    computed_prefixes = _computed_jump_prefixes(lines)

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        label_match = re.match(r"^:([a-zA-Z_][\w]*)", stripped, re.IGNORECASE)
        if label_match:
            labels[str(label_match.group(1)).lower()] = i
            continue

        referenced.update(_goto_and_call_label_names(line))

    for label_name, line_num in labels.items():
        if label_name not in referenced and not label_name.startswith(
            tuple(computed_prefixes)
        ):
            issues.append(
                LintIssue(
                    line_number=line_num,
                    rule=RULES["S010"],
                    context=f"Label ':{label_name}' is never referenced",
                )
            )

    return issues


def _check_goto_colon_consistency(  # pylint: disable=too-many-locals
    lines: List[str],
) -> List[LintIssue]:
    """Check for consistent colon usage in GOTO statements throughout the script (S015)."""
    issues: List[LintIssue] = []

    goto_statements: List[Tuple[int, str, bool]] = []

    # Collect all GOTO statements (excluding GOTO :EOF which has special rules)
    for i, line in enumerate(lines, start=1):
        for label_text_raw, _name in _iter_goto_label_refs(line):
            label_text = label_text_raw.lower()
            if label_text in {":eof", "eof"}:
                continue
            if re.search(r"%[^%]+%|!\w+!", label_text):
                continue
            uses_colon = label_text.startswith(":")
            goto_statements.append((i, label_text, uses_colon))

    if len(goto_statements) < 2:
        # Need at least 2 GOTO statements to check consistency
        return issues

    # Check if there's inconsistency in colon usage
    first_uses_colon = goto_statements[0][2]
    inconsistent_lines = []

    for line_num, _label, uses_colon in goto_statements[1:]:
        if uses_colon != first_uses_colon:
            inconsistent_lines.append(line_num)

    # Flag all inconsistent occurrences
    for line_num in inconsistent_lines:
        first_line = goto_statements[0][0]
        first_style = "with colon" if first_uses_colon else "without colon"
        current_style = "without colon" if first_uses_colon else "with colon"
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["S015"],
                context=(
                    f"GOTO statement uses {current_style} but first GOTO (line {first_line}) "
                    f"uses {first_style}"
                ),
            )
        )

    return issues


def _check_new_global_rules(lines: List[str], file_path: str) -> List[LintIssue]:
    """Check for new global rules that require full file context."""
    issues: List[LintIssue] = []

    issues.extend(_check_bat_cmd_differences(lines, file_path))

    if len(lines) > LARGE_FILE_LINE_THRESHOLD:
        issues.extend(_check_setlocal_redundancy(lines))
        issues.extend(_check_error_handling_warnings(lines))
        return issues

    issues.extend(_check_advanced_global_patterns(lines, file_path))
    issues.extend(_check_code_documentation(lines))
    issues.extend(_check_setlocal_redundancy(lines))
    issues.extend(_check_error_handling_warnings(lines))
    issues.extend(_check_infinite_loop_warnings(lines))
    issues.extend(_check_locked_file_operations(lines))
    issues.extend(_check_endlocal_before_exit(lines))
    issues.extend(_check_pushd_popd_balance(lines))
    issues.extend(_check_cd_without_d_switch(lines))

    return issues


def _line_starts_with_command(stripped: str, command: str) -> bool:
    """Return True when a line begins with the given cmd.exe command."""
    normalized = stripped.lstrip("@").strip()
    return bool(re.match(rf"{command}\b", normalized, re.IGNORECASE))


def _check_pushd_popd_balance(lines: List[str]) -> List[LintIssue]:
    """Warn when PUSHD/POPD calls are unbalanced (W061)."""
    issues: List[LintIssue] = []
    depth = 0
    unmatched_pushd: list[int] = []

    for i, line in enumerate(lines, start=1):
        if _is_comment_line(line):
            continue
        stripped = line.strip()
        if _line_starts_with_command(stripped, "pushd"):
            depth += 1
            unmatched_pushd.append(i)
            continue
        if _line_starts_with_command(stripped, "popd"):
            if depth > 0:
                depth -= 1
                unmatched_pushd.pop()
            else:
                issues.append(
                    LintIssue(
                        line_number=i,
                        rule=RULES["W061"],
                        context="POPD without matching PUSHD",
                    )
                )

    for line_num in unmatched_pushd:
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W061"],
                context=(
                    "PUSHD without matching POPD; temporary network drive "
                    "letters may remain mapped"
                ),
            )
        )

    return issues


_CD_DRIVE_PATH_RE = re.compile(r"[A-Za-z]:(?:\\|[^:\s])")
_CD_HAS_D_SWITCH_RE = re.compile(r"/d\b", re.IGNORECASE)


def _check_cd_without_d_switch(lines: List[str]) -> List[LintIssue]:
    """Warn when CD/CHDIR targets another drive without /D (W062)."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        if _is_comment_line(line):
            continue
        stripped = line.strip().lstrip("@").strip()
        if not re.match(r"(?:cd|chdir)\b", stripped, re.IGNORECASE):
            continue
        args = re.sub(
            r"^(?:cd|chdir)\b", "", stripped, count=1, flags=re.IGNORECASE
        ).strip()
        if not args or re.match(r"^\.\.+$", args):
            continue
        if _CD_HAS_D_SWITCH_RE.search(args):
            continue
        if re.match(r"^[A-Za-z]:\s*$", args):
            continue
        if _CD_DRIVE_PATH_RE.search(args):
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["W062"],
                    context=(
                        "CD without /D changes the target drive directory but "
                        "does not switch the active drive"
                    ),
                )
            )

    return issues


def _check_bat_cmd_differences(lines: List[str], file_path: str) -> List[LintIssue]:
    """Check for .bat/.cmd specific issues."""
    issues: List[LintIssue] = []

    # W028: .bat/.cmd errorlevel handling difference
    file_extension = Path(file_path).suffix.lower()
    errorlevel_commands = ["append", "dpath", "ftype", "set", "path", "assoc", "prompt"]

    if file_extension == ".bat":
        for i, line in enumerate(lines, start=1):
            stripped = line.strip().lower()
            first_word = stripped.split()[0] if stripped.split() else ""
            if first_word in errorlevel_commands:
                issues.append(
                    LintIssue(
                        line_number=i,
                        rule=RULES["W028"],
                        context=f"Command '{first_word}' handles errorlevel differently in "
                        f".bat vs .cmd files",
                    )
                )
                break  # Only flag once per file

    # W032: Missing character set declaration
    has_non_ascii = False
    has_chcp = False

    for line in lines:
        # Check for non-ASCII characters
        if any(ord(char) > 127 for char in line):
            has_non_ascii = True

        # Check for CHCP command
        if re.match(r"@?chcp\s", line.strip(), re.IGNORECASE):
            has_chcp = True

    if has_non_ascii and not has_chcp:
        issues.append(
            LintIssue(
                line_number=1,
                rule=RULES["W032"],
                context="File contains non-ASCII characters but no character set "
                "declaration (CHCP)",
            )
        )

    return issues


def _check_advanced_global_patterns(
    lines: List[str], file_path: str
) -> List[LintIssue]:
    """Check advanced patterns of Batch Scripting."""
    issues: List[LintIssue] = []

    # W039: Nested FOR loops without call optimization
    issues.extend(_check_nested_for_loops(lines))

    # W059: FOR loop variable case mismatch
    issues.extend(_check_for_var_case_mismatch(lines))

    # SEC016: Automatic restart without failure limits
    issues.extend(_check_restart_limits(lines))

    # SEC019: Batch self-modification vulnerability
    issues.extend(_check_self_modification(lines, file_path))

    return issues


def _check_nested_for_loops(lines: List[str]) -> List[LintIssue]:
    """Check for nested FOR loops that should use CALL optimization."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if not stripped.startswith("for "):
            continue

        # Found a FOR loop, check for nested FORs
        nested_for_issues = _find_nested_for_issues(lines, i)
        if nested_for_issues:
            issues.extend(nested_for_issues)

    return issues


def _find_nested_for_issues(lines: List[str], start_line: int) -> List[LintIssue]:
    """Find nested FOR loop issues starting from given line."""
    brace_count = 0
    in_for_block = False

    for j in range(start_line - 1, min(start_line - 1 + 20, len(lines))):
        check_line = lines[j].strip()
        brace_count += check_line.count("(") - check_line.count(")")

        if brace_count > 0:
            in_for_block = True

        # Check for nested FOR loop
        if in_for_block and check_line.lower().strip().startswith("for "):
            if j != start_line - 1:  # Not the same line
                outer_line = lines[start_line - 1]
                outer_var = re.search(
                    r"for\s+(?:/[lfdr]\s+.*?)?%%(\w)",
                    outer_line,
                    re.IGNORECASE,
                )
                inner_var = re.search(
                    r"for\s+(?:/[lfdr]\s+.*?)?%%(\w)",
                    check_line,
                    re.IGNORECASE,
                )
                nested_issues: List[LintIssue] = [
                    LintIssue(
                        line_number=j + 1,
                        rule=RULES["W023"],
                        context="Nested FOR loops can be inefficient with large data sets",
                    )
                ]
                outer_var_name = str(outer_var.group(1)) if outer_var else ""
                inner_var_name = str(inner_var.group(1)) if inner_var else ""
                if outer_var_name and outer_var_name == inner_var_name:
                    nested_issues.append(
                        LintIssue(
                            line_number=j + 1,
                            rule=RULES["W040"],
                            context=(
                                "Nested FOR loops reuse the same loop variable name"
                            ),
                        )
                    )
                if "call :" not in check_line.lower():
                    nested_issues.append(
                        LintIssue(
                            line_number=j + 1,
                            rule=RULES["W039"],
                            context="Nested FOR loop should use CALL :subroutine",
                        )
                    )
                return nested_issues
            continue

        if brace_count <= 0 and in_for_block:
            break

    return []


def _check_restart_limits(lines: List[str]) -> List[LintIssue]:
    """Check for restart patterns without proper limits."""
    issues: List[LintIssue] = []
    restart_patterns = ["goto", ":retry", ":restart", "call :retry"]

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        for pattern in restart_patterns:
            if pattern in stripped and ("retry" in stripped or "restart" in stripped):
                # Look for counter or limit logic
                has_limit = False
                check_range = max(0, i - 10), min(len(lines), i + 10)
                for j in range(check_range[0], check_range[1]):
                    check_line = lines[j].lower()
                    limit_words = ["counter", "attempt", "limit", "max", "count"]
                    if any(word in check_line for word in limit_words):
                        has_limit = True
                        break
                if not has_limit:
                    issues.append(
                        LintIssue(
                            line_number=i,
                            rule=RULES["SEC016"],
                            context="Restart logic should have failure attempt limits",
                        )
                    )
                break

    return issues


def _check_self_modification(lines: List[str], file_path: str) -> List[LintIssue]:
    """Check for batch self-modification vulnerabilities."""
    issues: List[LintIssue] = []
    script_name = Path(file_path).name.lower()

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if "echo" not in stripped or (">" not in stripped and ">>" not in stripped):
            continue

        writes_batch = ".bat" in stripped or ".cmd" in stripped
        writes_self = any(
            keyword in stripped
            for keyword in ("%~f0", "%0", file_path.lower(), script_name)
        )
        if writes_self and (writes_batch or "%~f0" in stripped or "%0" in stripped):
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["SEC019"],
                    context="Script appears to modify itself - potential security risk",
                )
            )

    return issues


def _check_code_documentation(lines: List[str]) -> List[LintIssue]:
    """Check for code documentation and style issues."""
    issues: List[LintIssue] = []

    # S022: Inconsistent variable naming convention
    issues.extend(_check_var_naming(lines))

    # S008: Missing comments for complex parenthesis blocks
    issues.extend(_check_missing_complex_comments(lines))

    return issues


def _is_comment_before_line(lines: List[str], line_number: int) -> bool:
    """Return True when the nearest non-blank line above ``line_number`` is a comment."""
    for index in range(line_number - 2, -1, -1):
        previous = lines[index].strip()
        if previous:
            return _is_comment_line(previous)
    return False


def _check_missing_complex_comments(lines: List[str]) -> List[LintIssue]:
    """Flag long IF/FOR blocks that lack explanatory comments (S008)."""
    issues: List[LintIssue] = []
    block_start = 0
    depth = 0

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or _should_skip_line_for_var_check(stripped.lower()):
            continue

        previous_depth = depth
        depth += stripped.count("(") - stripped.count(")")

        if depth > 0 and previous_depth == 0:
            block_start = i

        if previous_depth > 0 and depth == 0 and (i - block_start) >= 6:
            has_comment = _is_comment_before_line(lines, block_start) or any(
                _is_comment_line(lines[j - 1]) for j in range(block_start, i + 1)
            )
            if not has_comment:
                issues.append(
                    LintIssue(
                        line_number=block_start,
                        rule=RULES["S008"],
                        context="Complex block lacks REM comments explaining its purpose",
                    )
                )

    return issues


def _categorize_variable_style(var_name: str) -> str:
    """
    Determine the naming style of a variable.

    Args:
        var_name: Variable name to analyze

    Returns:
        Style name: "snake_case", "PascalCase", "camelCase", "UPPERCASE", or "lowercase"
    """
    if "_" in var_name and var_name.islower():
        return "snake_case"
    if var_name[0].isupper() and any(c.islower() for c in var_name[1:]):
        return "PascalCase"
    if var_name[0].islower() and any(c.isupper() for c in var_name[1:]):
        return "camelCase"
    if var_name.isupper():
        return "UPPERCASE"
    if var_name.islower():
        return "lowercase"
    return "unknown"


def _should_skip_line_for_var_check(stripped: str) -> bool:
    """
    Check if line should be skipped for variable name checking.

    Args:
        stripped: Stripped line content

    Returns:
        True if line should be skipped
    """
    skip_prefixes = ("echo ", "rem ", "::")
    skip_chars = (">", ">>")

    if any(stripped.startswith(prefix) for prefix in skip_prefixes):
        return True
    if any(char in stripped for char in skip_chars):
        return True
    return False


def _dominant_naming_style(styles: DefaultDict[str, int]) -> str:
    """Return the most frequently used naming style label."""
    dominant_style = ""
    highest_count = -1
    for style, count in styles.items():
        if count > highest_count:
            highest_count = count
            dominant_style = style
    return dominant_style


def _check_var_naming(lines: List[str]) -> List[LintIssue]:
    """Check for inconsistent variable naming conventions."""
    issues: List[LintIssue] = []
    variable_names = set()
    naming_styles: DefaultDict[str, int] = defaultdict(int)

    # Combined pattern for efficiency
    set_pattern = re.compile(
        r'^\s*set\s+(?:")?([a-zA-Z_][a-zA-Z0-9_]*)\s*=', re.IGNORECASE
    )

    for line in lines:
        stripped = line.strip()
        if _should_skip_line_for_var_check(stripped):
            continue

        # Extract variable names from SET commands
        match = set_pattern.search(line)
        if match:
            var_name = match.group(1)
            variable_names.add(var_name)
            style = _categorize_variable_style(var_name)
            naming_styles[style] += 1

    # Check for mixed styles (only if we have enough variables to analyze)
    if len(variable_names) >= 3:
        used_styles = sum(1 for count in naming_styles.values() if count > 0)
        if used_styles > 1:
            dominant_style = _dominant_naming_style(naming_styles)
            _add_issue(
                issues,
                line_number=1,
                rule_code="S022",
                context=f"Mixed variable naming styles detected. "
                f"Consider using {dominant_style} consistently",
            )

    return issues


def _check_setlocal_redundancy(lines: List[str]) -> List[LintIssue]:
    """Flag a second real SETLOCAL command (P024). Unmatched ENDLOCAL is not P024."""
    issues: List[LintIssue] = []
    setlocal_lines = [
        index for index, line in enumerate(lines, start=1) if _is_setlocal_command(line)
    ]
    if len(setlocal_lines) < 2:
        return issues

    issues.append(
        LintIssue(
            line_number=setlocal_lines[1],
            rule=RULES["P024"],
            context="Multiple SETLOCAL commands create unnecessary overhead",
        )
    )
    return issues


_RISKY_COMMANDS = (
    "xcopy",
    "robocopy",
    "copy",
    "move",
    "del",
    "erase",
    "reg",
    "sc",
    "net",
    "wmic",
    "powershell",
)


def _has_nearby_errorlevel_check(lines: List[str], line_index: int) -> bool:
    """Return True when error handling appears within a few lines."""
    for j in range(line_index, min(line_index + 4, len(lines))):
        lowered = lines[j].lower()
        if (
            "errorlevel" in lowered
            or "if not" in lowered
            or "if %errorlevel%" in lowered
        ):
            return True
    return False


def _check_error_handling_warnings(lines: List[str]) -> List[LintIssue]:
    """Check for missing ERRORLEVEL and general error handling (W002, W003)."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        for cmd in _RISKY_COMMANDS:
            if stripped.startswith(cmd + " ") or stripped == cmd:
                if not _has_nearby_errorlevel_check(lines, i - 1):
                    issues.append(
                        LintIssue(
                            line_number=i,
                            rule=RULES["W002"],
                            context=(
                                f"Command '{cmd}' should be followed by ERRORLEVEL check"
                            ),
                        )
                    )
                if cmd in {
                    "xcopy",
                    "robocopy",
                    "reg",
                    "sc",
                    "net",
                    "wmic",
                    "powershell",
                }:
                    if not _has_nearby_errorlevel_check(lines, i - 1):
                        issues.append(
                            LintIssue(
                                line_number=i,
                                rule=RULES["W003"],
                                context=(
                                    f"External operation '{cmd}' lacks error handling"
                                ),
                            )
                        )
                break

    return issues


def _collect_label_line_numbers(lines: List[str]) -> Dict[str, int]:
    """Map label names to their first defining line number."""
    label_lines: Dict[str, int] = {}
    for i, line in enumerate(lines, start=1):
        label_match = re.match(r"^\s*:([a-zA-Z_][a-zA-Z0-9_]*)\s*$", line.strip())
        if label_match:
            label_name = str(label_match.group(1)).lower()
            if label_name not in label_lines:
                label_lines[label_name] = i
    return label_lines


_EMPTY_ARG_IF = re.compile(
    r'\bif\b[^&\r\n]*"%~?\d"\s*==\s*""',
    re.IGNORECASE,
)


def _context_has_shift_exit_guard(context_lines: List[str]) -> bool:
    """Return True when a nearby shift loop exits on an empty argument."""
    has_shift = False
    has_empty_arg = False
    for ctx in context_lines:
        if re.search(r"\bshift\b", ctx, re.IGNORECASE):
            has_shift = True
        if _EMPTY_ARG_IF.search(ctx):
            has_empty_arg = True
        if has_shift and has_empty_arg:
            return True
    return False


def _check_infinite_loop_warnings(lines: List[str]) -> List[LintIssue]:
    """Check for potential infinite loops (W004)."""
    issues: List[LintIssue] = []
    label_lines = _collect_label_line_numbers(lines)

    for i, line in enumerate(lines, start=1):
        for _raw, target in _iter_goto_label_refs(line):
            target_line = label_lines.get(target)
            if target_line is None:
                continue
            # Forward jumps to exit handlers are not loops; only backward jumps are.
            if target_line >= i:
                continue
            context_lines = lines[max(0, i - 5) : min(len(lines), i + 5)]
            has_exit_guard = _context_has_shift_exit_guard(context_lines) or any(
                "set /a" in ctx.lower() or "counter" in ctx.lower()
                for ctx in context_lines
            )
            if not has_exit_guard:
                issues.append(
                    LintIssue(
                        line_number=i,
                        rule=RULES["W004"],
                        context=(
                            f"GOTO :{target} may create an infinite loop "
                            "without exit condition"
                        ),
                    )
                )

    return issues


def _check_locked_file_operations(lines: List[str]) -> List[LintIssue]:
    """Check file operations on potentially locked targets (W007)."""
    issues: List[LintIssue] = []
    locked_patterns = (
        r"\\windows\\",
        r"\\system32\\",
        r"\\program files",
        r"\.exe\b",
        r"\.dll\b",
    )

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if not stripped.startswith(
            ("copy ", "move ", "del ", "erase ", "ren ", "rename ")
        ):
            continue
        if any(re.search(pattern, stripped) for pattern in locked_patterns):
            issues.append(
                LintIssue(
                    line_number=i,
                    rule=RULES["W007"],
                    context=(
                        "File operation targets a path that may be locked or in use"
                    ),
                )
            )

    return issues


def _check_endlocal_before_exit(lines: List[str]) -> List[LintIssue]:
    """Check for SETLOCAL without ENDLOCAL before EXIT (P006)."""
    issues: List[LintIssue] = []
    setlocal_depth = 0

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if _is_setlocal_command(line):
            setlocal_depth += 1
        if _is_endlocal_command(line) and setlocal_depth > 0:
            setlocal_depth -= 1
        if not re.match(r"exit\b", stripped) or setlocal_depth <= 0:
            continue
        # exit /b either returns from a called subroutine or ends this batch
        # file. SETLOCAL ends with the batch file, so only a bare EXIT is flagged.
        if re.match(r"exit\s+/b\b", stripped):
            continue
        issues.append(
            LintIssue(
                line_number=i,
                rule=RULES["P006"],
                context="EXIT with active SETLOCAL should be preceded by ENDLOCAL",
            )
        )

    return issues
