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
_PERCENT_TOKEN_RE = re.compile(r"%%|%~[^%\s]*?[0-9*]|%[0-9*]|%[^%\r\n]+%")

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


def _is_cmd_command_string(prefix: str) -> bool:
    """Return True when prefix ends with a cmd /c or cmd /k command string."""
    return _CMD_CK_BEFORE_QUOTE_RE.search(prefix) is not None


def _hide_expansion_quotes(text: str) -> str:
    """Blank the quotes inside ``%name:...%``.

    Phase 1 expands a defined ``name`` before phase 2 reads quotes, so with ``p``
    defined ``SET`` runs in ``set p=%p:"=% & SET q=1``.
    """

    def _blank(match: re.Match[str]) -> str:
        token = match.group(0)
        name, colon, _ = token[1:].partition(":")
        if not colon or not name or '"' in name or any(c.isspace() for c in name):
            return token
        return token.replace('"', "'")

    return _PERCENT_TOKEN_RE.sub(_blank, text)


def _strip_casing_quotes(text: str) -> str:
    """Drop ordinary quotes and keep the text of a cmd /c or cmd /k string.

    A caret-escaped quote is literal, so ``set x=^" & SET y=2 & dir ^"`` still
    exposes ``SET``. An unescaped quote hides a PowerShell ``-Command`` string.
    An unclosed quote runs to the end of the line, so ``call :x "a & SET y=2``
    hides ``SET``. A quote inside ``%name:...%`` is not a quote.
    """
    text = _hide_expansion_quotes(text)
    parts: List[str] = []
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
        if _is_cmd_command_string(text[:index]):
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


def _collect_cmd_cases(lines: List[str]) -> Dict[str, List[Tuple[int, str]]]:
    """Collect command casing patterns from file lines."""
    command_cases: Dict[str, List[Tuple[int, str]]] = {}

    for line_num, line in enumerate(lines, 1):
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
        code = _casing_scan_text(stripped)

        # Find commands in this line - only at the start or after common batch separators
        for keyword, pattern in _COMMAND_CASE_PATTERNS:
            for match in pattern.finditer(code):
                actual_case = match.group(2)  # Group 2 is the keyword itself
                if keyword not in command_cases:
                    command_cases[keyword] = []
                command_cases[keyword].append((line_num, actual_case))

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
