"""Advanced caret and percent escaping rules (E030-E033)."""

import re
from typing import List

from blinter.models import LintIssue
from blinter.rules.helpers import strip_percent_expansions
from blinter.rules.registry import RULES


def _should_flag_caret_escape(stripped: str, caret_pos: int, line: str = "") -> bool:
    """Check if a caret escape sequence should be flagged as improper."""
    # Check if this is within a FOR loop command string (within single quotes)
    # In FOR loops, command strings like 'command 2^>nul ^| filter' use single caret correctly
    if re.search(r"\bfor\s+", stripped, re.IGNORECASE):
        # Find all single-quoted strings in FOR commands
        # Look for patterns like FOR ... IN ('...') where carets inside quotes are valid
        for_match = re.search(r"\bin\s*\('([^']*)'\)", stripped, re.IGNORECASE)
        if for_match:
            # Check if the caret is within the quoted string
            quote_start = for_match.start(1)
            quote_end = for_match.end(1)
            if quote_start <= caret_pos < quote_end:
                return False

    # Check if this is an ECHO statement (likely ASCII art)
    if re.match(r"echo\s+", stripped, re.IGNORECASE):
        # ECHO statements often contain ASCII art with carets - don't flag these
        return False

    # Check if this is a SET statement (storing escaped commands)
    # SET commands often store command strings with escaped special characters
    # Example: SET @PRINT_IF_DEBUG=ECHO:^& SET @^& ECHO:^& TIMEOUT 5
    # Also check for SET inside IF statements: IF ... (SET VAR=value^&...)
    if re.search(r"\bset\s+", stripped, re.IGNORECASE):
        # SET statements commonly use single carets to store command strings - don't flag these
        return False

    # Check if this line is within a parenthesized command block (FOR DO block, IF block, etc.)
    # Lines inside blocks are typically indented and need carets for proper redirection
    # Pattern: line starts with whitespace/tabs (indented) and contains command with redirection
    if line and re.match(r"^\s+", line):
        # This is an indented line, likely inside a block
        # Carets for redirection (2^>NUL, ^|, etc.) are necessary in blocks
        # to prevent premature evaluation
        return False

    # Check if this line is a DO block on the same line as FOR
    # Pattern: FOR ... DO ( command with carets )
    if re.search(r"\bdo\s*\(", stripped, re.IGNORECASE):
        # This is a FOR DO block, carets are necessary
        return False

    return True


def _check_improper_caret_escape(
    stripped: str, line_number: int, line: str = ""
) -> List[LintIssue]:
    """Check for E030: Improper caret escape sequence."""
    issues: List[LintIssue] = []
    # Look for single caret attempting to escape special chars
    # But exclude FOR loop command strings, ECHO statements (ASCII art), and SET commands
    caret_matches = re.finditer(r"\^[&|><](?!\^)", stripped)
    for match in caret_matches:
        caret_pos = match.start()
        if _should_flag_caret_escape(stripped, caret_pos, line):
            issues.append(LintIssue(line_number, RULES["E030"], context=stripped))
    return issues


def _check_multilevel_escaping(stripped: str, line_number: int) -> List[LintIssue]:
    """Check for E031: Invalid multilevel escaping."""
    issues: List[LintIssue] = []
    # Check for incorrect caret counts in multilevel escaping
    caret_sequences: List[str] = re.findall(r"\^+[&|><]", stripped)
    for seq in caret_sequences:
        caret_count = len(seq) - 1  # -1 for the target character
        # Valid counts follow 2^n-1 pattern: 1, 3, 7, 15...
        valid_counts: List[int] = [1, 3, 7, 15, 31]  # 2^n-1 pattern for n=1 to 5
        if caret_count > 0 and caret_count not in valid_counts:
            issues.append(LintIssue(line_number, RULES["E031"], context=seq))
    return issues


def _check_continuation_spaces(
    line: str, stripped: str, line_number: int
) -> List[LintIssue]:
    """Check for E032: Continuation character with trailing spaces."""
    issues: List[LintIssue] = []
    # Check if line ends with ^ followed by spaces/tabs (before the line ending)
    if stripped.endswith("^"):
        # Get the line without line endings
        line_no_newline = line.rstrip("\r\n")
        # If the line doesn't end with ^ after removing spaces,
        # then there are trailing spaces after ^
        if not line_no_newline.endswith("^"):
            issues.append(
                LintIssue(
                    line_number, RULES["E032"], context="Caret with trailing spaces"
                )
            )
    return issues


def _check_double_percent_escaping(stripped: str, line_number: int) -> List[LintIssue]:
    """Check for E033: Double percent escaping error."""
    issues: List[LintIssue] = []
    # Look for single % in echo statements that should be %%
    if stripped.lower().startswith("echo") and "%" in stripped:
        # Only flag if there's a literal percentage (like "50%") not a variable reference
        # Variable references like %var% are fine
        # Check for percentage signs that might need escaping (number followed by %)
        # But exclude variable references %VAR%
        line_without_vars = strip_percent_expansions(stripped)
        if re.search(r"\b\d+%(?!%)", line_without_vars):
            issues.append(
                LintIssue(
                    line_number,
                    RULES["E033"],
                    context="Percentage needs double escaping",
                )
            )
    return issues


def _check_advanced_escaping_rules(line: str, line_number: int) -> List[LintIssue]:
    """Check for advanced escaping technique issues."""
    # Multiple escaping rules (E030-E033) require checking various patterns
    issues: List[LintIssue] = []
    stripped = line.strip()

    # E030: Improper caret escape sequence
    issues.extend(_check_improper_caret_escape(stripped, line_number, line))

    # E031: Invalid multilevel escaping
    issues.extend(_check_multilevel_escaping(stripped, line_number))

    # E032: Continuation character with trailing spaces
    issues.extend(_check_continuation_spaces(line, stripped, line_number))

    # E033: Double percent escaping error
    issues.extend(_check_double_percent_escaping(stripped, line_number))

    return issues
