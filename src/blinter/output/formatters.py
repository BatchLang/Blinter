"""CLI output formatting: summaries, grouping, and help text."""

from collections import defaultdict
from typing import (
    DefaultDict,
    Dict,
    List,
    Set,
    Tuple,
    Union,
)

from blinter._version import __version__
from blinter.models import LintIssue, RuleSeverity
from blinter.paths import path_basename
from blinter.rules.registry import RULES


def print_version() -> None:
    """Print version information."""
    print(f"v{__version__}")


def print_help() -> None:
    """Print help information for the blinter command."""
    help_text = f"""
Blinter - Help Menu
Version: {__version__}

Usage:
  blinter <path> [options]
  python -m blinter <path> [options]

Arguments:
  <path>              Path to a batch file (.bat or .cmd) OR directory containing batch files.
                     When a directory is specified, all .bat and .cmd files will be processed.

Options:
  --summary           Show a summary section with total errors and most common error.
  --severity          Deprecated; has no effect. Use min_severity in blinter.ini instead.
  --config <path>     Path to blinter.ini configuration file (default: blinter.ini).
  --max-line-length <n>  Set maximum line length for S011 and S020 rules (default: 100).
  --no-recursive      When processing directories, don't search subdirectories (default: recursive).
  --follow-calls      Scan scripts called by CALL statements from each seed file.
                     Variable context may be collected transitively; each seed file
                     lints its direct CALL targets only.
  --output <path>     Write a structured report to the given file path. The file is
                     JSON unless --format sarif is also set.
  --format <fmt>      Suppress human-readable stdout and emit json or sarif.
                     Writes to stdout unless --output is also set (then the
                     report is written only to that file).
  --verbose           Show detailed debug logging on stderr.
  --quiet             Show only error-level logging on stderr.
  --no-config         Don't use configuration file (blinter.ini) even if it exists.
  --create-config     Create a default blinter.ini configuration file and exit.
  --force             With --create-config, overwrite an existing blinter.ini file.
  --help              Display this help menu and exit.
  --version           Display version information and exit.

Configuration:
  Blinter automatically looks for a 'blinter.ini' file in the current directory.
  If found, settings from this file will be used as defaults.
  Command line options override configuration file settings.

Rule Categories:
  E001-E999   Error Level    - Issues that will cause script failure
  W001-W999   Warning Level  - Bad practices that won't necessarily break script
  S001-S999   Style Level    - Code style and formatting issues
  SEC001+     Security Level - Security-related issues and vulnerabilities
  P001-P999   Performance    - Performance and efficiency improvements

Examples:
  blinter myscript.bat
      Analyze a single batch file with detailed error list and recommendations.

  blinter /path/to/batch/files
      Analyze all .bat and .cmd files in directory and subdirectories.

  blinter /path/to/batch/files --no-recursive
      Analyze only .bat and .cmd files in the directory (no subdirectories).

  blinter myscript.cmd --summary
      Shows summary and detailed errors for a single file.

  blinter myscript.bat --follow-calls
      Analyze script and any scripts it calls (e.g., configuration scripts).

  blinter myscript.bat --max-line-length 120
      Analyze with custom maximum line length of 120 characters.

  blinter myscript.bat --output report.json
      Analyze and write a JSON report while keeping human-readable output.

  blinter myscript.bat --format json
      Emit a JSON report to stdout (no human-readable output).

  blinter myscript.bat --format sarif
      Emit a SARIF 2.1.0 report to stdout (no human-readable output).

  blinter project\\scripts --output results.json --format json
      Write JSON to a file with no human-readable stdout.

  blinter project\\scripts --output results.sarif --format sarif
      Write SARIF to a file with no human-readable stdout.

  blinter /project/scripts --summary --severity
      Shows summary, detailed errors and severity info for all batch files in directory.

If no <path> is specified or '--help' is passed, this help menu will be displayed.
"""
    print(help_text.strip())


def group_issues(issues: List[LintIssue]) -> DefaultDict[RuleSeverity, List[LintIssue]]:
    """Group issues by severity level.

    Args:
        issues: List of LintIssue objects

    Returns:
        Dictionary mapping severity levels to lists of issues
    """
    grouped: DefaultDict[RuleSeverity, List[LintIssue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.rule.severity].append(issue)
    return grouped


def compute_severity_counts(
    issues: List[LintIssue],
) -> DefaultDict[RuleSeverity, int]:
    """Count issues grouped by severity level."""
    severity_counts: DefaultDict[RuleSeverity, int] = defaultdict(int)
    for issue in issues:
        severity_counts[issue.rule.severity] += 1
    return severity_counts


def compute_most_common_rule(
    issues: List[LintIssue],
) -> Tuple[str, int]:
    """Return the most frequently occurring rule code and its count."""
    rule_counts: DefaultDict[str, int] = defaultdict(int)
    for issue in issues:
        rule_counts[issue.rule.code] += 1

    if not rule_counts:
        return ("", 0)

    max_count = 0
    max_rule = ""
    for rule_code, count in rule_counts.items():
        if count > max_count:
            max_count = count
            max_rule = rule_code
    return (max_rule, max_count)


def print_summary(issues: List[LintIssue]) -> None:
    """Print summary statistics of linting issues.

    Args:
        issues: List of LintIssue objects
    """
    total_issues = len(issues)

    most_common_rule = compute_most_common_rule(issues)

    # Count by severity
    severity_counts = compute_severity_counts(issues)

    print("\nSUMMARY:")
    print(f"Total issues: {total_issues}")
    if most_common_rule[0]:
        most_common_rule_obj = RULES.get(most_common_rule[0])
        rule_name = (
            most_common_rule_obj.name
            if most_common_rule_obj is not None
            else most_common_rule[0]
        )
        print(
            f"Most common issue: '{rule_name}' "
            f"({most_common_rule[0]}) - {most_common_rule[1]} occurrences"
        )
    else:
        print("No issues found")

    print("\nIssues by severity:")
    severity_order = [
        RuleSeverity.ERROR,
        RuleSeverity.WARNING,
        RuleSeverity.STYLE,
        RuleSeverity.SECURITY,
        RuleSeverity.PERFORMANCE,
    ]
    for severity in severity_order:
        count = severity_counts.get(severity, 0)
        if count > 0:
            print(f"  {severity.value}: {count}")


def _format_line_numbers_with_files(
    issues: List[LintIssue],
) -> Tuple[bool, Union[str, Dict[str, List[int]]]]:
    """Format line numbers with file annotations for multi-file issues.

    Args:
        issues: List of LintIssue objects for the same rule

    Returns:
        Tuple of (is_multi_file, data) where:
        - If single file: (False, "Line 296, 303, 4709")
        - If multiple files: (True, {"file1.bat": [1, 2, 3], "file2.bat": [4, 5]})
    """

    # Sort issues by file and line number
    def sort_key(issue: LintIssue) -> Tuple[str, int]:
        """Return sort key for LintIssue."""
        return (issue.file_path or "", issue.line_number)

    sorted_issues = sorted(issues, key=sort_key)

    # Check if we have multiple files
    files = {issue.file_path for issue in sorted_issues if issue.file_path}

    # If single file or no file info, use simple format
    if len(files) <= 1:
        line_numbers = sorted([issue.line_number for issue in sorted_issues])
        return (False, f"Line {', '.join(map(str, line_numbers))}")

    # Multiple files - group by file
    file_lines: Dict[str, List[int]] = defaultdict(list)
    for issue in sorted_issues:
        if issue.file_path:
            filename = path_basename(issue.file_path)
            file_lines[filename].append(issue.line_number)

    return (True, dict(file_lines))


def _get_unique_contexts(rule_issues: List[LintIssue]) -> List[str]:
    """Extract unique contexts from rule issues, preserving order.

    Args:
        rule_issues: List of LintIssue objects

    Returns:
        List of unique context strings
    """
    contexts = [issue.context for issue in rule_issues if issue.context]
    if not contexts:
        return []

    # Remove duplicates while preserving order
    unique_contexts: List[str] = []
    seen: Set[str] = set()
    for context in contexts:
        if context not in seen:
            unique_contexts.append(context)
            seen.add(context)
    return unique_contexts


def _print_rule_group(rule_code: str, rule_issues: List[LintIssue]) -> None:
    """Print a group of issues for a single rule.

    Args:
        rule_code: The rule code identifier
        rule_issues: List of LintIssue objects for this rule
    """
    rule = rule_issues[0].rule

    # Format line numbers with file annotations if multiple files are involved
    is_multi_file, line_data = _format_line_numbers_with_files(rule_issues)

    if is_multi_file:
        # Hierarchical format for multiple files
        print(f"\n{rule.name} ({rule_code})")
        if not isinstance(line_data, dict):
            raise TypeError("Expected dict line data for multi-file output")
        for filename in sorted(line_data.keys()):
            line_nums = line_data[filename]
            line_str = ", ".join(map(str, line_nums))
            print(f"  [{filename}] Line {line_str}")
    else:
        # Simple format for single file
        if not isinstance(line_data, str):
            raise TypeError("Expected str line data for single-file output")
        print(f"\n{line_data}: {rule.name} ({rule_code})")

    print(f"- Explanation: {rule.explanation}")
    print(f"- Recommendation: {rule.recommendation}")

    # Add context if available
    unique_contexts = _get_unique_contexts(rule_issues)
    for context in unique_contexts:
        print(f"- Context: {context}")


def print_detailed(issues: List[LintIssue]) -> None:
    """Print detailed issue information in the new format.

    Args:
        issues: List of LintIssue objects
    """
    if not issues:
        print("\nDETAILED ISSUES:")
        print("----------------")
        print("No issues found! *\n")
        return

    # Group by severity
    grouped = group_issues(issues)

    print("\nDETAILED ISSUES:")
    print("----------------")

    severity_order = [
        RuleSeverity.ERROR,
        RuleSeverity.WARNING,
        RuleSeverity.STYLE,
        RuleSeverity.SECURITY,
        RuleSeverity.PERFORMANCE,
    ]

    for severity in severity_order:
        if severity not in grouped:
            continue

        severity_issues = grouped[severity]
        print(f"\n{severity.value.upper()} LEVEL ISSUES:")
        print("=" * (len(severity.value) + 14))

        # Group by rule within severity
        rule_groups: DefaultDict[str, List[LintIssue]] = defaultdict(list)
        for issue in severity_issues:
            rule_groups[issue.rule.code].append(issue)

        for rule_code in sorted(rule_groups.keys()):
            _print_rule_group(rule_code, rule_groups[rule_code])

        print()  # Extra spacing between severity levels


def print_severity_info(issues: List[LintIssue]) -> None:
    """Print severity level information.

    Args:
        issues: List of LintIssue objects
    """
    severity_counts = compute_severity_counts(issues)

    descriptions: Dict[RuleSeverity, str] = {
        RuleSeverity.ERROR: "Critical issues that will cause script failure or incorrect behavior.",
        RuleSeverity.WARNING: "Issues that may cause problems or unexpected behavior.",
        RuleSeverity.STYLE: "Code style and formatting issues that affect readability.",
        RuleSeverity.SECURITY: "Security vulnerabilities and potential risks.",
        RuleSeverity.PERFORMANCE: "Performance issues and optimization opportunities.",
    }

    print("\nSEVERITY BREAKDOWN:")
    print("====================")

    severity_order = [
        RuleSeverity.ERROR,
        RuleSeverity.WARNING,
        RuleSeverity.STYLE,
        RuleSeverity.SECURITY,
        RuleSeverity.PERFORMANCE,
    ]

    for severity in severity_order:
        count = severity_counts.get(severity, 0)
        if count == 0:
            continue
        issue_word = "issue" if count == 1 else "issues"
        print(f"\n{severity.value}: {count} {issue_word}")
        print(f"  {descriptions.get(severity, 'No description available.')}")
