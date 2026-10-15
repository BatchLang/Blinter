"""Main lint orchestration entry point for single batch files."""

from collections import Counter
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.checkers.cmd_extended import issues_for_overlong_lines
from blinter.checkers.globals import (
    _check_global_style_rules,
    _check_new_global_rules,
)
from blinter.checkers.line_endings import _check_line_ending_rules
from blinter.checkers.orchestration import (
    _filter_issues_by_config,
    _process_file_checks,
)
from blinter.engine.dependencies import _collect_called_vars
from blinter.engine.lines_cache import store_cached_lines
from blinter.io.encoding import _validate_and_read_file
from blinter.logging_config import logger
from blinter.models import BlinterConfig, LintIssue, RuleSeverity
from blinter.parsing.embedded import _detect_embedded_script_blocks
from blinter.parsing.structure import (
    _analyze_script_structure,
    _begin_structure_cache_pass,
    _collect_labels,
    _collect_set_variables,
    _parse_suppression_comments,
)


def lint_batch_file(  # pylint: disable=too-many-locals
    file_path: str,
    config: Optional[BlinterConfig] = None,
    lines_cache: Optional[Dict[Path, List[str]]] = None,
) -> List[LintIssue]:
    """
    Lint a batch file and return list of issues found.

    This is the main entry point for batch file analysis. It performs comprehensive
    static analysis including syntax validation, security checks, style analysis,
    and performance optimization suggestions.

    Thread-safe for concurrent ``lint_batch_file`` calls with an optional shared
    ``lines_cache`` (CLI orchestration is single-threaded).
    Performance: Optimized for files up to 10MB; files above 50MB are rejected

    Args:
        file_path: Path to the batch file (.bat or .cmd) to lint.
                  Can be absolute or relative path.
        config: BlinterConfig object with configuration settings. If None, uses defaults.
        lines_cache: Optional shared dict mapping resolved file paths to line lists.
                     Reads and writes are synchronized for concurrent linting.

    Returns:
        List of LintIssue objects containing detailed issue information.
        Each issue includes line number, rule details and contextual information.

    Raises:
        OSError: If file cannot be read or encoding issues occur
        FileNotFoundError: If the specified file doesn't exist
        PermissionError: If insufficient permissions to read the file
        ValueError: If file_path is empty or invalid

    Example:
        >>> issues = lint_batch_file("script.bat")
        >>> for issue in issues:
        ...     print(f"Line {issue.line_number}: {issue.rule.name}")

        >>> # With custom configuration
        >>> config = BlinterConfig(max_line_length=100)
        >>> issues = lint_batch_file("script.bat", config=config)
    """
    logger.info("Starting lint analysis of file: %s", file_path)

    if Path(file_path).suffix.lower() not in {".bat", ".cmd"}:
        raise ValueError(f"File '{file_path}' is not a batch file (.bat or .cmd)")

    # Use provided config or create default
    if config is None:
        config = BlinterConfig()

    scan_root = config.scan_root
    if scan_root is None:
        scan_root = str(Path(file_path).parent.resolve())

    # Read and validate file
    lines, _encoding_used, line_ending_info, overlong_lines = _validate_and_read_file(
        file_path
    )
    if lines_cache is not None:
        store_cached_lines(lines_cache, Path(file_path), lines)

    if not lines:
        return []  # Empty file, no issues

    _begin_structure_cache_pass()

    # Detect embedded PowerShell/VBScript/C#/JScript blocks to avoid false positives
    skip_lines = _detect_embedded_script_blocks(lines)

    issues: List[LintIssue] = []
    issues.extend(issues_for_overlong_lines(overlong_lines))

    # Analyze script structure for context-aware checking
    structure_data = _analyze_script_structure(lines)
    (
        has_setlocal,
        has_set_commands,
        has_delayed_expansion,
        uses_delayed_vars,
        has_disable_delayed_expansion,
        has_literal_exclamations,
        has_disable_expansion_lines,
    ) = structure_data

    # Critical line ending checks (includes ERROR level E018)
    issues.extend(
        _check_line_ending_rules(lines, file_path, ending_info=line_ending_info)
    )

    # Style rules that apply globally
    issues.extend(_check_global_style_rules(lines, file_path))

    # Collect labels and check for duplicates
    labels, label_issues = _collect_labels(lines)
    issues.extend(label_issues)

    # Collect set variables for undefined variable checking
    set_vars = _collect_set_variables(lines)

    # Collect variables from called scripts if follow_calls is enabled
    called_scripts_vars: Optional[Dict[int, Set[str]]] = None
    if config.follow_calls:
        try:
            batch_path = Path(file_path)
            called_scripts_vars = _collect_called_vars(
                batch_path,
                scan_root=scan_root,
                lines=lines,
                lines_cache=lines_cache,
            )
        except (OSError, ValueError) as collect_error:
            logger.warning(
                "Could not collect variables from called scripts for %s: %s",
                file_path,
                collect_error,
            )
            called_scripts_vars = None

    # Process all line-by-line and global checks
    issues.extend(
        _process_file_checks(
            lines,
            labels,
            set_vars,
            has_setlocal,
            has_set_commands,
            has_delayed_expansion,
            uses_delayed_vars,
            has_disable_delayed_expansion,
            has_literal_exclamations,
            has_disable_expansion_lines,
            config,
            skip_lines,
            called_scripts_vars,
            file_path,
        )
    )

    # Global checks for new rules
    issues.extend(_check_new_global_rules(lines, file_path))

    # Set file_path on all issues that don't have it
    for issue in issues:
        if issue.file_path is None:
            issue.file_path = file_path

    # Parse inline suppression comments
    suppressions = _parse_suppression_comments(lines)

    # Filter issues based on configuration and inline suppressions
    filtered_issues = _filter_issues_by_config(issues, config, suppressions)

    severity_counts = Counter(issue.rule.severity for issue in filtered_issues)
    logger.info(
        "Lint analysis completed. Found %d issues (filtered to %d) across %d error(s), "
        "%d warning(s), %d style issue(s), %d security issue(s), "
        "%d performance issue(s)",
        len(issues),
        len(filtered_issues),
        severity_counts[RuleSeverity.ERROR],
        severity_counts[RuleSeverity.WARNING],
        severity_counts[RuleSeverity.STYLE],
        severity_counts[RuleSeverity.SECURITY],
        severity_counts[RuleSeverity.PERFORMANCE],
    )

    return filtered_issues
