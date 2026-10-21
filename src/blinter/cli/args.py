"""Command-line argument parsing for the Blinter CLI."""

from dataclasses import dataclass, field
import logging
from pathlib import Path
import sys
from typing import (
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

from blinter.config.loader import create_default_config_file
from blinter.constants import MAX_LINE_LENGTH
from blinter.models import CliArguments, OutputFormat
from blinter.output.formatters import print_help, print_version

_DEFAULT_CONFIG_PATH = "blinter.ini"

_ArgHandlerResult = Tuple[
    None,
    Optional[bool],
    Optional[bool],
    Optional[bool],
    Optional[bool],
]


def _print_cli_error(message: str) -> None:
    """Print a CLI error message to stderr."""
    print(message, file=sys.stderr)


def _handle_special_cli_flags() -> Optional[bool]:
    """
    Handle special CLI flags that should exit early.

    Returns:
        None if should continue parsing, False if should exit with None
    """
    if "--version" in sys.argv:
        print_version()
        return False

    if len(sys.argv) < 2 or "--help" in sys.argv:
        print_help()
        return False

    if "--create-config" in sys.argv:
        force = "--force" in sys.argv
        if not create_default_config_file(_DEFAULT_CONFIG_PATH, force=force):
            if Path(_DEFAULT_CONFIG_PATH).exists() and not force:
                _print_cli_error(
                    f"Configuration file already exists: {_DEFAULT_CONFIG_PATH}\n"
                    "Use --create-config --force to overwrite, or edit the existing "
                    "file.\n"
                )
            else:
                _print_cli_error(
                    f"Error creating configuration file: {_DEFAULT_CONFIG_PATH}\n"
                )
            sys.exit(1)
        print(f"Default configuration file created: {_DEFAULT_CONFIG_PATH}")
        return False

    return None


def _parse_max_line_length_arg(arg_index: int) -> Optional[Tuple[int, int]]:
    """
    Parse the value following ``--max-line-length``.

    Returns:
        Tuple of (next argv index, parsed line length), or None when invalid.
    """
    if arg_index + 1 >= len(sys.argv):
        _print_cli_error("Error: --max-line-length requires a value.\n")
        print_help()
        return None
    try:
        line_length = int(sys.argv[arg_index + 1])
        if line_length <= 0:
            _print_cli_error("Error: --max-line-length must be a positive integer.\n")
            return None
        if line_length > MAX_LINE_LENGTH:
            _print_cli_error(
                f"Error: --max-line-length must not exceed {MAX_LINE_LENGTH}.\n"
            )
            return None
        return arg_index + 1, line_length
    except ValueError:
        _print_cli_error(
            f"Error: --max-line-length requires a numeric value, "
            f"got '{sys.argv[arg_index + 1]}'.\n"
        )
        return None


def _parse_config_arg(arg_index: int) -> Optional[Tuple[int, str]]:
    """Parse the value following ``--config``."""
    if arg_index + 1 >= len(sys.argv):
        _print_cli_error("Error: --config requires a path.\n")
        print_help()
        return None
    return arg_index + 1, sys.argv[arg_index + 1]


def _parse_output_arg(arg_index: int) -> Optional[Tuple[int, str]]:
    """Parse the value following ``--output``."""
    if arg_index + 1 >= len(sys.argv):
        _print_cli_error("Error: --output requires a path.\n")
        print_help()
        return None
    return arg_index + 1, sys.argv[arg_index + 1]


def _parse_baseline_arg(arg_index: int) -> Optional[Tuple[int, str]]:
    """Parse the value following ``--baseline``."""
    if arg_index + 1 >= len(sys.argv) or sys.argv[arg_index + 1].startswith("--"):
        _print_cli_error("Error: --baseline requires a path.\n")
        print_help()
        return None
    return arg_index + 1, sys.argv[arg_index + 1]


_FAIL_ON_VALUES = frozenset(
    {"error", "security", "warning", "performance", "style", "none"}
)


def _parse_fail_on_arg(arg_index: int) -> Optional[Tuple[int, str]]:
    """Parse the value following ``--fail-on``."""
    if arg_index + 1 >= len(sys.argv):
        _print_cli_error("Error: --fail-on requires a value.\n")
        print_help()
        return None
    fail_on_value = sys.argv[arg_index + 1].lower()
    if fail_on_value in _FAIL_ON_VALUES:
        return arg_index + 1, fail_on_value
    supported = ", ".join(sorted(_FAIL_ON_VALUES))
    _print_cli_error(
        f"Error: Unknown fail-on threshold '{sys.argv[arg_index + 1]}'. "
        f"Supported values: {supported}.\n"
    )
    print_help()
    return None


_FORMAT_VALUES: Dict[str, OutputFormat] = {
    "json": OutputFormat.JSON,
    "sarif": OutputFormat.SARIF,
}


def _parse_format_arg(arg_index: int) -> Optional[Tuple[int, OutputFormat]]:
    """Parse the value following ``--format``."""
    if arg_index + 1 >= len(sys.argv):
        _print_cli_error("Error: --format requires a value.\n")
        print_help()
        return None
    format_value = sys.argv[arg_index + 1].lower()
    parsed_format = _FORMAT_VALUES.get(format_value)
    if parsed_format is not None:
        return arg_index + 1, parsed_format
    supported = ", ".join(sorted(_FORMAT_VALUES))
    _print_cli_error(
        f"Error: Unknown format '{sys.argv[arg_index + 1]}'. "
        f"Supported values: {supported}.\n"
    )
    print_help()
    return None


def _apply_handler_flags(
    handler_result: _ArgHandlerResult,
    *,
    use_config: bool,
    cli_show_summary: Optional[bool],
    cli_recursive: Optional[bool],
    cli_follow_calls: Optional[bool],
) -> Tuple[bool, Optional[bool], Optional[bool], Optional[bool]]:
    """Apply flag handler side effects to parse state."""
    _, config_flag, summary_flag, recursive_flag, follow_flag = handler_result
    return (
        use_config if config_flag is None else config_flag,
        cli_show_summary if summary_flag is None else summary_flag,
        cli_recursive if recursive_flag is None else recursive_flag,
        cli_follow_calls if follow_flag is None else follow_flag,
    )


@dataclass
class _ArgParseState:  # pylint: disable=too-many-instance-attributes
    """Mutable state while parsing CLI arguments."""

    positional_paths: List[str] = field(default_factory=list)
    use_config: bool = True
    cli_show_summary: Optional[bool] = None
    cli_recursive: Optional[bool] = None
    cli_follow_calls: Optional[bool] = None
    cli_max_line_length: Optional[int] = None
    cli_verbose: bool = False
    cli_quiet: bool = False
    config_path: Optional[str] = None
    cli_output_path: Optional[str] = None
    cli_output_format: OutputFormat = OutputFormat.TEXT
    cli_fail_on: Optional[str] = None
    cli_baseline_path: Optional[str] = None
    cli_update_baseline: bool = False


def _warn_severity_flag_deprecated() -> _ArgHandlerResult:
    """Warn that ``--severity`` is deprecated and has no effect."""
    print(
        "Warning: --severity is deprecated and has no effect. "
        "Use min_severity in blinter.ini instead.",
        file=sys.stderr,
    )
    return (None, None, None, None, None)


_ARG_HANDLERS: Dict[str, Callable[[], _ArgHandlerResult]] = {
    "--summary": lambda: (None, None, True, None, None),
    "--severity": _warn_severity_flag_deprecated,
    "--no-recursive": lambda: (None, None, None, False, None),
    "--no-config": lambda: (None, False, None, None, None),
    "--follow-calls": lambda: (None, None, None, None, True),
}


def _resolve_cli_log_level(verbose: bool, quiet: bool) -> Optional[int]:
    """Map verbose/quiet flags to a logging level."""
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.ERROR
    return None


_PATH_OPTION_PARSERS: Dict[str, Callable[[int], Optional[Tuple[int, str]]]] = {
    "--config": _parse_config_arg,
    "--output": _parse_output_arg,
    "--baseline": _parse_baseline_arg,
}


def _store_path_option(state: _ArgParseState, arg: str, value: str) -> None:
    """Store a parsed path option on the argument state."""
    if arg == "--config":
        state.config_path = value
        return
    if arg == "--output":
        state.cli_output_path = value
        return
    if arg == "--baseline":
        state.cli_baseline_path = value
        return
    raise ValueError(f"Unknown path option '{arg}'")


def _apply_path_option(arg: str, index: int, state: _ArgParseState) -> int:
    """Parse and store ``--config``, ``--output``, or ``--baseline``."""
    parser = _PATH_OPTION_PARSERS[arg]
    parsed = parser(index)
    if parsed is None:
        sys.exit(1)
    next_index, value = parsed
    _store_path_option(state, arg, value)
    return next_index


def _apply_value_option(arg: str, index: int, state: _ArgParseState) -> Optional[int]:
    """Apply a value-taking ``--`` option; return next index or None."""
    if arg == "--max-line-length":
        parsed_length = _parse_max_line_length_arg(index)
        if parsed_length is None:
            sys.exit(1)
        next_index, state.cli_max_line_length = parsed_length
        return next_index
    if arg in _PATH_OPTION_PARSERS:
        return _apply_path_option(arg, index, state)
    if arg == "--format":
        parsed_format = _parse_format_arg(index)
        if parsed_format is None:
            sys.exit(1)
        next_index, state.cli_output_format = parsed_format
        return next_index
    if arg == "--fail-on":
        parsed_fail_on = _parse_fail_on_arg(index)
        if parsed_fail_on is None:
            sys.exit(1)
        next_index, state.cli_fail_on = parsed_fail_on
        return next_index
    return None


def _process_dash_argument(
    arg: str,
    index: int,
    state: _ArgParseState,
) -> int:
    """Handle a single ``--`` argument and return the next argv index."""
    next_index = _apply_value_option(arg, index, state)
    if next_index is not None:
        return next_index

    if arg == "--verbose":
        state.cli_verbose = True
        return index

    if arg == "--quiet":
        state.cli_quiet = True
        return index

    if arg == "--update-baseline":
        state.cli_update_baseline = True
        return index

    if arg in _ARG_HANDLERS:
        (
            state.use_config,
            state.cli_show_summary,
            state.cli_recursive,
            state.cli_follow_calls,
        ) = _apply_handler_flags(
            _ARG_HANDLERS[arg](),
            use_config=state.use_config,
            cli_show_summary=state.cli_show_summary,
            cli_recursive=state.cli_recursive,
            cli_follow_calls=state.cli_follow_calls,
        )
        return index

    _print_cli_error(f"Error: Unknown option '{arg}'.\n")
    print_help()
    sys.exit(1)


def _parse_regular_arguments() -> Tuple[
    Optional[str],
    bool,
    Optional[bool],
    Optional[bool],
    Optional[bool],
    Optional[int],
    Optional[int],
    Optional[str],
    Optional[str],
    OutputFormat,
    Optional[str],
    Optional[str],
    bool,
]:
    """
    Parse regular command-line arguments using a lookup table.

    Returns:
        Tuple of (target_path, use_config, cli_show_summary, cli_recursive,
        cli_follow_calls, cli_max_line_length, cli_log_level, config_path,
        cli_output_path, cli_output_format, cli_fail_on, cli_baseline_path,
        cli_update_baseline)
    """
    state = _ArgParseState()

    index = 1
    while index < len(sys.argv):
        arg = sys.argv[index]
        if not arg.startswith("--"):
            state.positional_paths.append(arg)
        else:
            index = _process_dash_argument(arg, index, state)
        index += 1

    if state.cli_verbose and state.cli_quiet:
        _print_cli_error("Error: --verbose and --quiet cannot be used together.\n")
        print_help()
        sys.exit(1)

    if len(state.positional_paths) > 1:
        _print_cli_error("Error: Only one target path is allowed.\n")
        print_help()
        sys.exit(1)

    if state.cli_update_baseline and state.cli_baseline_path is None:
        _print_cli_error("Error: --update-baseline requires --baseline.\n")
        print_help()
        sys.exit(1)

    target_path = state.positional_paths[0] if state.positional_paths else None

    return (
        target_path,
        state.use_config,
        state.cli_show_summary,
        state.cli_recursive,
        state.cli_follow_calls,
        state.cli_max_line_length,
        _resolve_cli_log_level(state.cli_verbose, state.cli_quiet),
        state.config_path,
        state.cli_output_path,
        state.cli_output_format,
        state.cli_fail_on,
        state.cli_baseline_path,
        state.cli_update_baseline,
    )


def _parse_cli_arguments() -> Optional[CliArguments]:
    """Parse command line arguments."""
    should_continue = _handle_special_cli_flags()
    if should_continue is False:
        return None

    (
        target_path,
        use_config,
        cli_show_summary,
        cli_recursive,
        cli_follow_calls,
        cli_max_line_length,
        cli_log_level,
        config_path,
        cli_output_path,
        cli_output_format,
        cli_fail_on,
        cli_baseline_path,
        cli_update_baseline,
    ) = _parse_regular_arguments()

    if not target_path:
        _print_cli_error("Error: No batch file or directory provided.\n")
        print_help()
        sys.exit(1)

    return CliArguments(
        target_path,
        use_config,
        cli_show_summary,
        cli_recursive,
        cli_follow_calls,
        cli_max_line_length,
        cli_log_level,
        config_path=config_path,
        cli_output_path=cli_output_path,
        cli_output_format=cli_output_format,
        cli_fail_on=cli_fail_on,
        cli_baseline_path=cli_baseline_path,
        cli_update_baseline=cli_update_baseline,
    )
