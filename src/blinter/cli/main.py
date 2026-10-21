"""CLI entry point and multi-file batch processing orchestration."""

import logging
from pathlib import Path
import sys
from typing import (
    Callable,
    List,
    NoReturn,
    Optional,
    Sequence,
    Tuple,
    assert_never,
)

from blinter._version import __version__
from blinter.baseline import (
    BaselineEntry,
    apply_baseline,
    load_baseline,
    update_baseline,
)
from blinter.cli.args import _parse_cli_arguments
from blinter.config.loader import load_config
from blinter.constants import MAX_FOLLOW_CALL_DEPTH, MAX_FOLLOW_CALL_FILES
from blinter.engine.dependencies import _extract_called_scripts
from blinter.engine.lines_cache import get_cached_lines
from blinter.engine.linter import lint_batch_file
from blinter.io.discovery import find_batch_files, is_path_under_root
from blinter.logging_config import logger
from blinter.models import (
    BlinterConfig,
    CliArguments,
    LintIssue,
    OutputFormat,
    ProcessingResults,
    ProcessingState,
    parse_fail_on,
)
from blinter.output.formatters import (
    print_detailed,
    print_severity_info,
    print_stale_baseline_entries,
    print_summary,
)
from blinter.output.json_formatter import (
    BaselineReportInfo,
    build_report,
    print_report,
    write_report,
)
from blinter.output.sarif_formatter import (
    build_sarif_report,
    print_sarif_report,
    write_sarif_report,
)
from blinter.paths import display_path, path_basename

_CLI_HANDLER_ATTR = "blinter_cli_handler"


def _stream_is_closed(stream: object) -> bool:
    """Return True when a stream object reports itself as closed."""
    closed_attr: object = getattr(stream, "closed", False)
    return isinstance(closed_attr, bool) and closed_attr


def _configure_cli_logging(log_level: int = logging.WARNING) -> None:
    """Attach a stderr handler when no logging is configured by the host app."""
    blinter_logger = logging.getLogger("blinter")

    for handler in list(blinter_logger.handlers):
        if not isinstance(handler, logging.StreamHandler):
            continue
        if not hasattr(handler, _CLI_HANDLER_ATTR):
            continue
        stream = handler.stream
        if stream is None or _stream_is_closed(stream):
            blinter_logger.removeHandler(handler)
            continue
        handler.setStream(sys.stderr)
        handler.setLevel(log_level)
        blinter_logger.setLevel(log_level)
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    setattr(handler, _CLI_HANDLER_ATTR, True)
    blinter_logger.addHandler(handler)
    blinter_logger.setLevel(log_level)


def _cli_error(message: str) -> NoReturn:
    """Print an error message to stderr and exit with status code 1."""
    print(message, file=sys.stderr)
    raise SystemExit(1)


_FILE_PROCESSING_ERRORS: Tuple[type[BaseException], ...] = (
    FileNotFoundError,
    PermissionError,
    OSError,
    ValueError,
    TypeError,
)


def _process_single_called_script(
    called_script: Path,
    config: BlinterConfig,
    state: ProcessingState,
    parent_path: str,
) -> Tuple[int, int]:
    """
    Process a single called script.

    Follow-calls analysis is best-effort: read or lint failures on called scripts
    are logged and skipped without adding to ``skipped_files`` (unlike primary
    targets, which affect the CLI exit code when unreadable).

    Returns:
        Tuple of (files_processed, files_with_errors)
    """
    if called_script.resolve() in state.processed_files:
        return (0, 0)

    if len(state.processed_files) >= MAX_FOLLOW_CALL_FILES:
        logger.warning(
            "Follow-calls file limit (%d) reached; skipping %s",
            MAX_FOLLOW_CALL_FILES,
            called_script,
        )
        return (0, 0)

    if config.scan_root is not None and not is_path_under_root(
        called_script, Path(config.scan_root)
    ):
        logger.debug("Skipping called script outside scan root: %s", called_script)
        return (0, 0)

    try:
        called_issues = lint_batch_file(
            str(called_script),
            config=config,
            lines_cache=state.lines_cache,
        )
        state.file_results[str(called_script)] = called_issues
        state.all_issues.extend(called_issues)
        state.processed_files.add(called_script.resolve())

        existing_paths = {path for path, _parent in state.processed_file_paths}
        called_path_str = str(called_script)
        if called_path_str not in existing_paths:
            state.processed_file_paths.append((called_path_str, parent_path))

        has_fatal = any(
            config.is_fatal_severity(issue.rule.severity) for issue in called_issues
        )
        return (1, 1 if has_fatal else 0)

    except _FILE_PROCESSING_ERRORS as called_error:
        error_msg = (
            f"Warning: Could not process called script "
            f"'{called_script}': {called_error}"
        )
        logger.warning(error_msg)
        return (0, 0)
    except Exception:
        logger.exception(
            "Internal error linting called script '%s'",
            called_script,
        )
        return (0, 0)


def _process_called_scripts(
    batch_file: Path,
    config: BlinterConfig,
    state: ProcessingState,
    depth: int = 0,
) -> Tuple[int, int]:
    """
    Process all called scripts for a batch file.

    Args:
        batch_file: The batch file to extract called scripts from
        config: Configuration settings
        state: Processing state container

    Returns:
        Tuple of (files_processed, files_with_errors)
    """
    resolved_file = batch_file.resolve()
    if resolved_file in state.expanded_files:
        logger.debug("Skipping already-expanded called script: %s", batch_file)
        return 0, 0

    if depth > MAX_FOLLOW_CALL_DEPTH:
        logger.warning(
            "Follow-calls depth limit (%d) reached at %s",
            MAX_FOLLOW_CALL_DEPTH,
            batch_file,
        )
        return 0, 0

    state.expanded_files.add(resolved_file)

    files_processed = 0
    files_with_errors = 0
    called_scripts = _extract_called_scripts(
        batch_file,
        scan_root=config.scan_root,
        lines=get_cached_lines(state.lines_cache, batch_file),
    )

    for called_script in called_scripts:
        if len(state.processed_files) >= MAX_FOLLOW_CALL_FILES:
            logger.warning(
                "Follow-calls file limit (%d) reached; stopping at %s",
                MAX_FOLLOW_CALL_FILES,
                batch_file,
            )
            break
        result = _process_single_called_script(
            called_script,
            config,
            state,
            str(batch_file),
        )
        files_processed += result[0]
        files_with_errors += result[1]
        nested = _process_called_scripts(
            called_script,
            config,
            state,
            depth + 1,
        )
        files_processed += nested[0]
        files_with_errors += nested[1]

    return files_processed, files_with_errors


def _record_skipped_file(
    skipped_files: List[Tuple[str, str]],
    batch_file: Path,
    reason: str,
) -> None:
    """Record a file that could not be processed."""
    skipped_files.append((str(batch_file), reason))
    logger.warning("Could not process '%s': %s", batch_file, reason)


def _print_skipped_files_summary(skipped_files: List[Tuple[str, str]]) -> None:
    """Print a user-visible summary of files that could not be processed."""
    if not skipped_files:
        return

    print("\nSkipped files (could not be processed):")
    for file_path, reason in skipped_files:
        print(f"  - {file_path}: {reason}")


def _process_batch_files(
    batch_files: List[Path],
    config: BlinterConfig,
    *,
    suppress_human_stdout: bool = False,
) -> Optional[ProcessingResults]:
    """Process all batch files and collect results."""
    state = ProcessingState(
        processed_files=set(), all_issues=[], file_results={}, processed_file_paths=[]
    )
    total_files_processed = 0
    files_with_errors = 0
    skipped_files: List[Tuple[str, str]] = []

    for batch_file in batch_files:
        if batch_file.resolve() in state.processed_files:
            continue

        try:
            issues = lint_batch_file(
                str(batch_file),
                config=config,
                lines_cache=state.lines_cache,
            )
            state.file_results[str(batch_file)] = issues
            state.all_issues.extend(issues)
            total_files_processed += 1
            state.processed_files.add(batch_file.resolve())
            state.processed_file_paths.append((str(batch_file), None))

            if any(config.is_fatal_severity(issue.rule.severity) for issue in issues):
                files_with_errors += 1

            if config.follow_calls:
                called_results = _process_called_scripts(
                    batch_file,
                    config,
                    state,
                )
                total_files_processed += called_results[0]
                files_with_errors += called_results[1]

        except _FILE_PROCESSING_ERRORS as file_error:
            _record_skipped_file(skipped_files, batch_file, str(file_error))
            continue
        except Exception as internal_error:
            logger.exception("Internal error linting '%s'", batch_file)
            _record_skipped_file(
                skipped_files,
                batch_file,
                f"internal lint error: {internal_error}",
            )
            continue

    if total_files_processed == 0:
        if suppress_human_stdout:
            return ProcessingResults(
                [],
                {},
                0,
                0,
                [],
                skipped_files,
                lines_cache=state.lines_cache,
            )
        _print_skipped_files_summary(skipped_files)
        print("Error: No batch files could be processed.", file=sys.stderr)
        return None

    if skipped_files and not suppress_human_stdout:
        _print_skipped_files_summary(skipped_files)

    return ProcessingResults(
        state.all_issues,
        state.file_results,
        total_files_processed,
        files_with_errors,
        state.processed_file_paths,
        skipped_files,
        lines_cache=state.lines_cache,
    )


def _display_analyzed_scripts(
    processed_file_paths: List[Tuple[str, Optional[str]]],
    target_path: str,
    is_directory: bool,
) -> None:
    """
    Display the list of analyzed scripts.

    Args:
        processed_file_paths: List of (file_path, called_by_parent) tuples
        target_path: The original target path provided by user
        is_directory: Whether the target was a directory
    """
    if not processed_file_paths:
        return

    print("Scripts Analyzed:")
    for idx, (file_path, parent) in enumerate(processed_file_paths, 1):
        display_path_value = display_path(
            file_path,
            target_path,
            is_directory=is_directory,
        )

        if parent:
            parent_name = path_basename(parent)
            print(f"  {idx}.   ↳ {display_path_value} (called by {parent_name})")
        else:
            print(f"  {idx}. {display_path_value}")

    print()


def _display_results(
    results: ProcessingResults,
    target_path: str,
    config: BlinterConfig,
    stale_entries: Sequence[BaselineEntry] = (),
) -> None:
    """Display lint results to the user."""
    is_directory = Path(target_path).is_dir()

    if is_directory:
        print(f"\n Batch Files Analysis: {target_path}")
        print("=" * (26 + len(target_path)))
        file_count_text = "s" if results.total_files_processed != 1 else ""
        print(f"Processed {results.total_files_processed} batch file{file_count_text}")
        print()

        _display_analyzed_scripts(
            results.processed_file_paths, target_path, is_directory
        )

        if len(results.file_results) > 1:
            for file_path, issues in results.file_results.items():
                try:
                    relative_path = Path(file_path).relative_to(Path(target_path))
                except ValueError:
                    relative_path = Path(file_path)
                print(f"\n File: {relative_path}")
                print("-" * (8 + len(str(relative_path))))

                if issues:
                    print_detailed(issues)
                else:
                    print("No issues found! OK")
                print()
        else:
            print_detailed(results.all_issues)
    else:
        print(f"\n Batch File Analysis: {target_path}")
        print("=" * (25 + len(target_path)))

        _display_analyzed_scripts(
            results.processed_file_paths, target_path, is_directory
        )

        print_detailed(results.all_issues)

    if is_directory and len(results.file_results) > 1:
        print("\n COMBINED RESULTS:")
        print("===================")

    print_stale_baseline_entries(
        [(entry.code, entry.file, entry.text) for entry in stale_entries]
    )

    if config.show_summary:
        print_summary(results.all_issues)

    print_severity_info(results.all_issues)


def _target_scan_root(target_path: str) -> Path:
    """Return the directory that contains the resolved CLI target."""
    resolved = Path(target_path).resolve()
    if resolved.is_dir():
        return resolved
    return resolved.parent


def _report_no_batch_files(target_path: str, discovery_root: Path) -> None:
    """Exit when discovery returns nothing, naming a rejected single file."""
    target = Path(target_path)
    if target.is_file() and target.suffix.lower() in {".bat", ".cmd"}:
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target
        _cli_error(
            f"Error: '{target_path}' resolves to '{resolved}', "
            f"which is outside '{discovery_root}'."
        )
    _cli_error(f"No batch files (.bat or .cmd) found in: {target_path}")


def _normalized_path(path: str) -> str:
    """Return a resolved, comparable path string."""
    return str(Path(path).resolve())


def _primary_target_paths(results: ProcessingResults) -> set[str]:
    """Return normalized paths for primary lint targets (not follow-call callees)."""
    return {
        _normalized_path(file_path)
        for file_path, called_by_parent in results.processed_file_paths
        if called_by_parent is None
    }


def _count_fatal_issues_for_exit(
    results: ProcessingResults, config: BlinterConfig
) -> int:
    """Count fatal issues on primary targets only; callee findings are informational."""
    primary_paths = _primary_target_paths(results)
    return sum(
        1
        for issue in results.all_issues
        if config.is_fatal_severity(issue.rule.severity)
        and issue.file_path is not None
        and _normalized_path(issue.file_path) in primary_paths
    )


def _plural(count: int, suffix: str = "s") -> str:
    """Return plural suffix when count is not 1."""
    return "" if count == 1 else suffix


def _handle_skipped_files_exit(
    results: ProcessingResults,
    *,
    suppress_stdout: bool = False,
) -> None:
    """Print skipped-file warning and exit with code 1 when any primary file was skipped."""
    if not results.skipped_files:
        return
    if not suppress_stdout:
        print(
            f"\nWARNING  {len(results.skipped_files)} batch file"
            f"{_plural(len(results.skipped_files))} could not be processed."
        )
    sys.exit(1)


def _exit_directory_results(
    results: ProcessingResults,
    fatal_count: int,
    *,
    suppress_stdout: bool = False,
) -> None:
    """Exit with the appropriate code for directory analysis."""
    if fatal_count > 0:
        if not suppress_stdout:
            print(
                f"\nWARNING  Found {fatal_count} critical issue{_plural(fatal_count)} "
                f"at or above the failure threshold across {results.files_with_errors} "
                f"file{_plural(results.files_with_errors)} that must be fixed."
            )
        sys.exit(1)
    elif results.all_issues:
        if not suppress_stdout:
            print(
                f"\nOK No critical errors found, but {len(results.all_issues)} "
                f"total issue{_plural(len(results.all_issues))} detected across "
                f"{results.total_files_processed} "
                f"file{_plural(results.total_files_processed)}."
            )
        sys.exit(0)
    else:
        if not suppress_stdout:
            print(
                f"\n* No issues found! All {results.total_files_processed} "
                f"batch file{_plural(results.total_files_processed)} "
                f"look{'s' if results.total_files_processed == 1 else ''} great!"
            )
        sys.exit(0)


def _exit_single_file_results(
    results: ProcessingResults,
    fatal_count: int,
    *,
    suppress_stdout: bool = False,
) -> None:
    """Exit with the appropriate code for single-file analysis."""
    if fatal_count > 0:
        if not suppress_stdout:
            print(
                f"\nWARNING  Found {fatal_count} critical issue{_plural(fatal_count)} "
                f"at or above the failure threshold that must be fixed."
            )
        sys.exit(1)
    elif results.all_issues:
        if not suppress_stdout:
            print(
                f"\nOK No critical errors found, but {len(results.all_issues)} "
                f"issue{_plural(len(results.all_issues))} detected."
            )
        sys.exit(0)
    else:
        if not suppress_stdout:
            print("\nNo issues found! Your batch file looks great!")
        sys.exit(0)


def _exit_with_results(
    results: ProcessingResults,
    target_path: str,
    config: BlinterConfig,
    *,
    suppress_stdout: bool = False,
    stale_count: int = 0,
) -> None:
    """Exit with appropriate code based on results."""
    fatal_count = _count_fatal_issues_for_exit(results, config)
    _handle_skipped_files_exit(results, suppress_stdout=suppress_stdout)
    if stale_count > 0 and fatal_count == 0:
        if not suppress_stdout:
            noun = "entry" if stale_count == 1 else "entries"
            print(
                f"\nWARNING  {stale_count} baseline {noun} "
                "no longer match a finding."
            )
        sys.exit(1)

    if Path(target_path).is_dir():
        _exit_directory_results(
            results,
            fatal_count,
            suppress_stdout=suppress_stdout,
        )
    else:
        _exit_single_file_results(
            results,
            fatal_count,
            suppress_stdout=suppress_stdout,
        )


def _suppress_human_stdout(cli_args: CliArguments) -> bool:
    """Return True when human-readable stdout should be omitted."""
    return cli_args.cli_output_format in (OutputFormat.JSON, OutputFormat.SARIF)


def _should_emit_structured(cli_args: CliArguments) -> bool:
    """Return True when a JSON or SARIF report should be built."""
    return cli_args.cli_output_path is not None or _suppress_human_stdout(cli_args)


def _write_structured_report(write: Callable[[], None], label: str) -> None:
    """Write a structured report, exiting on filesystem errors."""
    try:
        write()
    except (OSError, PermissionError) as write_error:
        print(
            f"Error: Could not write {label} report: {write_error}",
            file=sys.stderr,
        )
        sys.exit(1)


def _emit_json_report(
    results: ProcessingResults,
    cli_args: CliArguments,
    config: BlinterConfig,
    *,
    baselined_issues: int = 0,
    stale_entries: Sequence[BaselineEntry] = (),
) -> None:
    """Build and write or print a JSON lint report."""
    fatal_count = _count_fatal_issues_for_exit(results, config)
    report = build_report(
        results,
        cli_args.target_path,
        __version__,
        fatal_count,
        BaselineReportInfo(
            baselined_issues=baselined_issues,
            stale_baseline_entries=[
                {"code": entry.code, "file": entry.file, "text": entry.text}
                for entry in stale_entries
            ],
        ),
    )
    output_path = cli_args.cli_output_path
    if output_path is not None:

        def write_json_file(path: str = output_path) -> None:
            write_report(path, report)

        _write_structured_report(write_json_file, "JSON")
    if (
        cli_args.cli_output_format == OutputFormat.JSON
        and cli_args.cli_output_path is None
    ):
        print_report(report)


def _emit_sarif_report(results: ProcessingResults, cli_args: CliArguments) -> None:
    """Build and write or print a SARIF lint report."""
    report = build_sarif_report(results, __version__)
    output_path = cli_args.cli_output_path
    if output_path is not None:

        def write_sarif_file(path: str = output_path) -> None:
            write_sarif_report(path, report)

        _write_structured_report(write_sarif_file, "SARIF")
    if (
        cli_args.cli_output_format == OutputFormat.SARIF
        and cli_args.cli_output_path is None
    ):
        print_sarif_report(report)


def _emit_structured_report(
    results: ProcessingResults,
    cli_args: CliArguments,
    config: BlinterConfig,
    *,
    baselined_issues: int = 0,
    stale_entries: Sequence[BaselineEntry] = (),
) -> None:
    """Emit JSON or SARIF based on the selected format.

    ``--output`` without ``--format`` keeps the historical JSON report.
    SARIF lists findings only. Stale baseline entries are in the JSON report.
    """
    match cli_args.cli_output_format:
        case OutputFormat.SARIF:
            _emit_sarif_report(results, cli_args)
        case OutputFormat.JSON | OutputFormat.TEXT:
            _emit_json_report(
                results,
                cli_args,
                config,
                baselined_issues=baselined_issues,
                stale_entries=stale_entries,
            )
        case _ as unreachable:
            assert_never(unreachable)


def _apply_cli_config_overrides(
    cli_args: CliArguments,
    config: BlinterConfig,
) -> None:
    """Apply CLI flag overrides and derive scan_root from the target path."""
    if cli_args.cli_show_summary is not None:
        config.show_summary = cli_args.cli_show_summary
    if cli_args.cli_recursive is not None:
        config.recursive = cli_args.cli_recursive
    if cli_args.cli_follow_calls is not None:
        config.follow_calls = cli_args.cli_follow_calls
    if cli_args.cli_max_line_length is not None:
        config.max_line_length = cli_args.cli_max_line_length
    if cli_args.cli_fail_on is not None:
        config.fail_on = parse_fail_on(cli_args.cli_fail_on)

    config.scan_root = str(_target_scan_root(cli_args.target_path))


def _results_keeping(
    results: ProcessingResults,
    kept: Sequence[LintIssue],
    config: BlinterConfig,
) -> ProcessingResults:
    """Return results whose issue lists contain only findings the baseline kept."""
    kept_ids = {id(issue) for issue in kept}
    file_results = {
        file_path: [issue for issue in issues if id(issue) in kept_ids]
        for file_path, issues in results.file_results.items()
    }
    files_with_errors = sum(
        1
        for issues in file_results.values()
        if any(config.is_fatal_severity(issue.rule.severity) for issue in issues)
    )
    return ProcessingResults(
        all_issues=list(kept),
        file_results=file_results,
        total_files_processed=results.total_files_processed,
        files_with_errors=files_with_errors,
        processed_file_paths=results.processed_file_paths,
        skipped_files=results.skipped_files,
        lines_cache=results.lines_cache,
    )


def _load_baseline_or_exit(path: Path) -> List[BaselineEntry]:
    """Load a baseline file or exit with a message that names the file."""
    try:
        return load_baseline(path)
    except FileNotFoundError:
        _cli_error(f"Error: Baseline file not found: {path}")
    except ValueError as error:
        _cli_error(f"Error: {error}")
    except OSError as error:
        _cli_error(f"Error: Cannot read baseline file '{path}': {error}")


def _baseline_entry_noun(count: int) -> str:
    """Return 'entry' or 'entries' for a baseline count."""
    return "entry" if count == 1 else "entries"


def _update_baseline_and_exit(
    results: ProcessingResults,
    cli_args: CliArguments,
    config: BlinterConfig,
    path: Path,
    *,
    suppress_human: bool,
) -> NoReturn:
    """Rewrite the baseline from this run and exit."""
    try:
        count = update_baseline(path, results)
    except ValueError as error:
        _cli_error(f"Error: {error}")
    except OSError as error:
        _cli_error(f"Error: Could not write baseline file '{path}': {error}")
    if _should_emit_structured(cli_args):
        _emit_structured_report(results, cli_args, config)
    if not suppress_human:
        print(f"Updated baseline {path} ({count} {_baseline_entry_noun(count)}).")
    _handle_skipped_files_exit(results, suppress_stdout=suppress_human)
    sys.exit(0)


def _apply_baseline_or_exit(
    results: ProcessingResults,
    cli_args: CliArguments,
    config: BlinterConfig,
    *,
    suppress_human: bool,
) -> Tuple[ProcessingResults, List[BaselineEntry], int]:
    """Filter findings through the baseline.

    ``--update-baseline`` rewrites the file and does not return.
    """
    baseline_path = cli_args.cli_baseline_path
    if baseline_path is None:
        return results, [], 0
    path = Path(baseline_path)
    if cli_args.cli_update_baseline:
        _update_baseline_and_exit(
            results,
            cli_args,
            config,
            path,
            suppress_human=suppress_human,
        )
    entries = _load_baseline_or_exit(path)
    diff = apply_baseline(
        results,
        entries,
        path.resolve().parent,
        results.lines_cache,
    )
    filtered = _results_keeping(results, diff.kept, config)
    return filtered, list(diff.stale), len(diff.matched)


def _configure_stdio_utf8() -> None:
    """Reconfigure stdout/stderr for UTF-8 on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


def main() -> None:
    """Main entry point for the blinter application."""
    try:
        _run_cli()
    except BrokenPipeError:
        raise SystemExit(0) from None
    except Exception:
        logger.exception("Unexpected error during CLI execution")
        print("Error: An unexpected internal error occurred.", file=sys.stderr)
        if logger.getEffectiveLevel() > logging.DEBUG:
            print(
                "Re-run with --verbose for a full traceback.",
                file=sys.stderr,
            )
        raise SystemExit(2) from None


def _run_cli() -> None:
    """Run the blinter CLI after argument parsing and setup."""
    _configure_stdio_utf8()

    cli_args = _parse_cli_arguments()
    if cli_args is None:
        return

    _configure_cli_logging(
        cli_args.cli_log_level
        if cli_args.cli_log_level is not None
        else logging.WARNING
    )

    suppress_human = _suppress_human_stdout(cli_args)
    if not suppress_human:
        print(f"Blinter v{__version__} - Batch File Linter\n")

    try:
        config = load_config(
            config_path=cli_args.config_path,
            use_config=cli_args.use_config,
        )
    except FileNotFoundError as error:
        _cli_error(f"Error: {error}")
    except ValueError as error:
        _cli_error(f"Error: {error}")
    _apply_cli_config_overrides(cli_args, config)

    discovery_root = _target_scan_root(cli_args.target_path)
    try:
        batch_files = find_batch_files(
            cli_args.target_path,
            recursive=config.recursive,
            root=discovery_root,
            max_scan_files=config.max_scan_files,
        )
    except FileNotFoundError:
        _cli_error(f"Error: Path '{cli_args.target_path}' not found.")
    except ValueError as value_error:
        _cli_error(f"Error: {value_error}")
    except (OSError, PermissionError) as path_error:
        _cli_error(f"Error: Cannot access '{cli_args.target_path}': {path_error}")

    if not batch_files:
        _report_no_batch_files(cli_args.target_path, discovery_root)

    results = _process_batch_files(
        batch_files,
        config,
        suppress_human_stdout=suppress_human,
    )
    if results is None:
        sys.exit(1)

    results, stale_entries, baselined_issues = _apply_baseline_or_exit(
        results,
        cli_args,
        config,
        suppress_human=suppress_human,
    )

    if _should_emit_structured(cli_args):
        _emit_structured_report(
            results,
            cli_args,
            config,
            baselined_issues=baselined_issues,
            stale_entries=stale_entries,
        )

    if not suppress_human:
        _display_results(
            results,
            cli_args.target_path,
            config,
            stale_entries,
        )
    _exit_with_results(
        results,
        cli_args.target_path,
        config,
        suppress_stdout=suppress_human,
        stale_count=len(stale_entries),
    )
