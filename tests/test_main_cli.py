"""Tests for main function and command-line interface."""

import io
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import TracebackType
from typing import TYPE_CHECKING, Dict, Optional, Protocol, Set, TextIO
from unittest.mock import patch

import pytest

from blinter.cli.args import _parse_cli_arguments, _parse_regular_arguments
from blinter.cli.main import (
    _apply_cli_config_overrides,
    _configure_cli_logging,
    _process_called_scripts,
    _process_single_called_script,
    main as cli_main,
)
from blinter.engine.linter import lint_batch_file as engine_lint_batch_file
from blinter import (
    find_batch_files,
    main,
)
from blinter.models import BlinterConfig, CliArguments, LintIssue, ProcessingState
from tests.conftest import get_project_version

# pylint: disable=too-many-lines,redefined-outer-name,reimported


if TYPE_CHECKING:
    from typing_extensions import Self


class StdoutCaptureProtocol(Protocol):
    """Protocol for stdout capture context manager."""

    def __enter__(self) -> "StdoutCaptureProtocol":
        """Enter context manager."""

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit context manager."""

    def getvalue(self) -> str:
        """Get the captured stdout output."""


class StdoutCapture:
    """Context manager for capturing stdout and stderr output during tests."""

    def __init__(self) -> None:
        self.captured_output: Optional[io.StringIO] = None
        self.captured_stderr: Optional[io.StringIO] = None
        self.old_stdout: Optional[TextIO] = None
        self.old_stderr: Optional[TextIO] = None

    def __enter__(self) -> "StdoutCapture":
        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr
        sys.stdout = self.captured_output = io.StringIO()
        sys.stderr = self.captured_stderr = io.StringIO()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self.old_stdout is not None:
            sys.stdout = self.old_stdout
        if self.old_stderr is not None:
            sys.stderr = self.old_stderr

    def getvalue(self) -> str:
        """Get captured stdout and stderr combined."""
        stdout_value = self.captured_output.getvalue() if self.captured_output else ""
        stderr_value = self.captured_stderr.getvalue() if self.captured_stderr else ""
        return stdout_value + stderr_value


class TestMainFunction:
    """Test cases for the main function and CLI interface."""

    def capture_stdout(self) -> StdoutCapture:
        """Context manager to capture stdout output."""
        return StdoutCapture()

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    @patch("sys.argv", ["blinter.py"])
    def test_main_no_arguments(self) -> None:
        """Test main function with no arguments shows help."""
        with self.capture_stdout() as captured:
            main()
            output = captured.getvalue()

        assert "Blinter - Help Menu" in output
        assert "Usage:" in output

    @patch("sys.argv", ["blinter.py", "--help"])
    def test_main_help_flag(self) -> None:
        """Test main function with --help flag."""
        with self.capture_stdout() as captured:
            main()
            output = captured.getvalue()

        assert "Blinter - Help Menu" in output
        assert "Usage:" in output

    def test_main_nonexistent_file(self) -> None:
        """Test main function with non-existent file."""
        with patch("sys.argv", ["blinter.py", "nonexistent.bat"]):
            with self.capture_stdout() as captured:
                with pytest.raises(SystemExit) as exit_info:
                    main()
                output = captured.getvalue()

            assert exit_info.value.code == 1
            assert "Error: Path 'nonexistent.bat' not found" in output

    def test_main_non_bat_file(self) -> None:
        """Test main function with non-.bat file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as temp_file:
            temp_file.write("test content")
            temp_file_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file_path]):
                with self.capture_stdout() as captured:
                    with pytest.raises(SystemExit) as exit_info:
                        main()
                    output = captured.getvalue()

                assert exit_info.value.code == 1
                assert "not a batch file (.bat or .cmd)" in output
        finally:
            os.unlink(temp_file_path)

    def test_main_valid_batch_file(self) -> None:
        """Test main function with valid batch file."""
        content = """@echo off
echo Hello World
set "var=test value"
echo %var%
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter.py", temp_file]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
                assert "SEVERITY BREAKDOWN:" in output
        finally:
            os.unlink(temp_file)

    def test_main_with_summary_flag(self) -> None:
        """Test main function with --summary flag."""
        content = """@echo off
echo Hello World
set var=unquoted
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter.py", temp_file, "--summary"]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
                assert "SUMMARY:" in output
                assert "Total issues:" in output
                assert "SEVERITY BREAKDOWN:" in output
        finally:
            os.unlink(temp_file)

    def test_main_with_severity_flag(self) -> None:
        """Test main function with --severity flag."""
        content = """@echo off
echo Hello World
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter.py", temp_file, "--severity"]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
                assert "SEVERITY BREAKDOWN:" in output
        finally:
            os.unlink(temp_file)

    def test_main_with_multiple_flags(self) -> None:
        """Test main function with multiple flags."""
        content = """@echo off
echo Hello World
set var=unquoted
echo %var%
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch(
                "sys.argv", ["blinter.py", temp_file, "--summary", "--severity"]
            ):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
                assert "SUMMARY:" in output
                assert "SEVERITY BREAKDOWN:" in output
        finally:
            os.unlink(temp_file)

    def test_main_file_not_found_error(self) -> None:
        """Test main function with file that gets deleted after validation."""
        temp_file = self.create_temp_batch_file("@echo off\necho test\n")

        # Delete the file to simulate FileNotFoundError
        os.unlink(temp_file)

        with patch("sys.argv", ["blinter.py", temp_file]):
            with self.capture_stdout() as captured:
                with pytest.raises(SystemExit) as exit_info:
                    main()
                output = captured.getvalue()

            assert exit_info.value.code == 1
            # The main function validates file existence before processing
            assert "Error: Path" in output and "not found" in output

    def test_main_scan_limit_exceeded(self) -> None:
        """Directory scan above max_scan_files exits with code 1."""
        with tempfile.TemporaryDirectory() as temp_dir:
            for index in range(4):
                script_path = os.path.join(temp_dir, f"script{index}.bat")
                with open(script_path, "w", encoding="utf-8") as file_handle:
                    file_handle.write("@echo off\n")

            config_path = os.path.join(temp_dir, "blinter.ini")
            with open(config_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("[general]\nmax_scan_files = 3\n")

            argv = ["blinter.py", "--config", config_path, temp_dir]
            with patch("sys.argv", argv):
                with self.capture_stdout() as captured:
                    with pytest.raises(SystemExit) as exit_info:
                        main()
                    output = captured.getvalue()

            assert exit_info.value.code == 1
            assert "exceeding the limit" in output

    def test_main_permission_error(self) -> None:
        """Test main function with permission error."""
        temp_file = self.create_temp_batch_file("@echo off\necho test\n")

        try:
            with patch(
                "blinter.cli.main.lint_batch_file",
                side_effect=PermissionError("Permission denied"),
            ):
                with patch("sys.argv", ["blinter.py", temp_file]):
                    with self.capture_stdout() as captured:
                        try:
                            main()
                        except SystemExit as sys_exit:
                            # Exit code 0 or 1 is expected
                            assert sys_exit.code in [0, 1]
                        output = captured.getvalue()

                    assert (
                        "Could not process" in output and "Permission denied" in output
                    )
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_main_unicode_decode_error(self) -> None:
        """Test main function when a file cannot be processed."""
        temp_file = self.create_temp_batch_file("@echo off\necho test\n")

        try:
            with patch(
                "blinter.cli.main.lint_batch_file",
                side_effect=OSError("Could not read file"),
            ):
                with patch("sys.argv", ["blinter.py", temp_file]):
                    with self.capture_stdout() as captured:
                        with pytest.raises(SystemExit) as exit_info:
                            main()
                        output = captured.getvalue()

                    assert exit_info.value.code == 1
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_main_general_exception(self) -> None:
        """Test main function with general exception."""
        temp_file = self.create_temp_batch_file("@echo off\necho test\n")

        try:
            with patch(
                "blinter.cli.main.lint_batch_file",
                side_effect=ValueError("Something went wrong"),
            ):
                with patch("sys.argv", ["blinter.py", temp_file]):
                    with self.capture_stdout() as captured:
                        try:
                            main()
                        except SystemExit as sys_exit:
                            # Exit code 0 or 1 is expected
                            assert sys_exit.code in [0, 1]
                        output = captured.getvalue()

                    assert "Could not process" in output
                    assert "Something went wrong" in output
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_main_argument_parsing_variations(self) -> None:
        """Test various argument parsing scenarios."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            test_cases = [
                ["blinter.py", temp_file],
                ["blinter.py", "--summary", temp_file],
                ["blinter.py", temp_file, "--summary"],
            ]
            if sys.platform == "win32":
                test_cases = [
                    ["blinter.py", temp_file.upper()],
                    ["blinter.py", temp_file.lower()],
                    *test_cases,
                ]

            for test_argv in test_cases:
                # Make sure file has .bat extension for recognition
                if temp_file.endswith(".bat"):
                    with patch("sys.argv", test_argv):
                        with self.capture_stdout() as captured:
                            try:
                                main()
                            except SystemExit as sys_exit:
                                # Exit code 0 or 1 is expected
                                assert sys_exit.code in [0, 1]
                            output = captured.getvalue()

                        # Should process successfully without showing help
                        assert "DETAILED ISSUES:" in output
                        assert "Blinter - Help Menu" not in output
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_main_mixed_case_bat_extension(self) -> None:
        """Test batch file recognition with mixed case .bat extension."""
        content = "@echo off\necho test\n"

        # Create file with mixed case extension
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".BaT", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file_path]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
        finally:
            os.unlink(temp_file_path)

    def test_main_cmd_extension(self) -> None:
        """Test batch file recognition with .cmd extension."""
        content = "@echo off\necho test\n"

        # Create file with .cmd extension
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cmd", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file_path]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
        finally:
            os.unlink(temp_file_path)

    def test_main_mixed_case_cmd_extension(self) -> None:
        """Test batch file recognition with mixed case .cmd extension."""
        content = "@echo off\necho test\n"

        # Create file with mixed case extension
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".CmD", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file_path]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
        finally:
            os.unlink(temp_file_path)

    def test_main_with_relative_path(self) -> None:
        """Test main function with relative path."""
        content = "@echo off\necho test\n"

        # Create temp file in current directory
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, dir="."
        ) as temp_file:
            temp_file.write(content)
            temp_filename = os.path.basename(temp_file.name)

        try:
            with patch("sys.argv", ["blinter.py", temp_filename]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                assert "DETAILED ISSUES:" in output
        finally:
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def test_main_output_structure(self) -> None:
        """Test the structure and order of main function output."""
        content = """echo Missing echo off
set var=unquoted
echo %var%
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter.py", temp_file, "--summary"]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                # Check output order: detailed first, then summary, then severity
                detailed_pos = output.find("DETAILED ISSUES:")
                summary_pos = output.find("SUMMARY:")
                severity_pos = output.find("SEVERITY BREAKDOWN:")

                assert detailed_pos != -1
                assert summary_pos != -1
                assert severity_pos != -1

                # Summary should come after detailed, severity should come last
                assert detailed_pos < summary_pos < severity_pos
        finally:
            os.unlink(temp_file)

    def test_main_no_issues_found(self) -> None:
        """Test main function behavior when no issues are found."""
        content = """@echo off
setlocal enabledelayedexpansion
set "var=properly quoted"
echo "%var%"
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter.py", temp_file, "--summary"]):
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()

                # Should still show structure even with no issues
                assert "DETAILED ISSUES:" in output
                assert "SUMMARY:" in output
                assert "SEVERITY BREAKDOWN:" in output
        finally:
            os.unlink(temp_file)

    def test_production_ready_main_execution(self) -> None:
        """Test main() function execution in production-like scenario."""
        original_argv = sys.argv

        # Create a realistic test batch file
        content = """@echo off
REM This is a test batch file for production testing
set "TEST_VAR=Hello World"
echo %TEST_VAR%
if exist "somefile.txt" (
    echo File exists
) else (
    echo File does not exist
)
"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Test main with various flag combinations
            test_cases = [
                [temp_file_path],
                [temp_file_path, "--summary"],
                [temp_file_path, "--severity"],
                [temp_file_path, "--summary", "--severity"],
            ]

            for test_argv in test_cases:
                sys.argv = ["blinter.py"] + test_argv

                # Capture output to verify main() executes correctly
                with self.capture_stdout() as captured:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = captured.getvalue()
                    # Should have printed something (detailed output at minimum)
                    assert "DETAILED ISSUES:" in output

        finally:
            sys.argv = original_argv
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)


class TestCommandLineIntegration:
    """Integration tests for command-line usage."""

    def test_pathlib_path_integration(self) -> None:
        """Test integration with pathlib Path objects."""
        content = "@echo off\necho test\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Test Path.is_file() integration
            path_obj = Path(temp_file_path)
            assert path_obj.is_file()

            with patch("sys.argv", ["blinter.py", temp_file_path]):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                    try:
                        main()
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]
                    output = mock_stdout.getvalue()

                assert "DETAILED ISSUES:" in output
        finally:
            os.unlink(temp_file_path)

    def test_error_handling_robustness(self) -> None:
        """Test robustness of error handling in various scenarios."""
        test_scenarios = [
            ("FileNotFoundError", FileNotFoundError("File not found")),
            ("PermissionError", PermissionError("Permission denied")),
            ("UnicodeDecodeError", UnicodeDecodeError("utf-8", b"", 0, 1, "invalid")),
            ("TypeError", TypeError("General error")),
            ("OSError", OSError("OS error")),
        ]

        content = "@echo off\necho test\n"
        temp_file = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".bat", delete=False
            ) as tf:
                tf.write(content)
                temp_file = tf.name

            for _error_name, error_obj in test_scenarios:
                with patch("blinter.cli.main.lint_batch_file", side_effect=error_obj):
                    with patch("sys.argv", ["blinter.py", temp_file]):
                        with StdoutCapture() as captured:
                            with pytest.raises(SystemExit) as exit_info:
                                main()
                            output = captured.getvalue()
                            assert exit_info.value.code == 1
                            assert (
                                "Could not process" in output
                                or "Could not read" in output
                                or "Error: No batch files could be processed" in output
                            )
        finally:
            if temp_file and os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_internal_lint_error_skips_file_and_continues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Internal checker failures skip one file without aborting the whole run."""
        good_file = tmp_path / "good.bat"
        bad_file = tmp_path / "bad.bat"
        good_file.write_text("@echo off\necho ok\n", encoding="utf-8")
        bad_file.write_text("@echo off\necho bad\n", encoding="utf-8")

        def selective_lint(
            file_path: str,
            config: BlinterConfig | None = None,
            lines_cache: dict[Path, list[str]] | None = None,
        ) -> list[LintIssue]:
            if Path(file_path).name == "bad.bat":
                raise KeyError("simulated checker bug")
            return engine_lint_batch_file(
                file_path,
                config=config,
                lines_cache=lines_cache,
            )

        with patch("blinter.cli.main.lint_batch_file", side_effect=selective_lint):
            with patch("sys.argv", ["blinter.py", str(tmp_path)]):
                with pytest.raises(SystemExit) as exit_info:
                    main()

        captured = capsys.readouterr()
        assert exit_info.value.code == 1
        assert "internal lint error" in captured.err
        assert "Processed 1 batch file" in captured.out

    def test_main_module_runpy_entry(self) -> None:
        """Test python -m blinter module exposes the CLI entry point."""
        with patch.object(sys, "argv", ["blinter", "--help"]):
            cli_main()

    def test_comprehensive_main_execution_scenarios(self) -> None:
        """Test main function execution with comprehensive scenarios."""
        original_argv = sys.argv

        # Create a test batch file with various issues for comprehensive testing
        content = """echo off
set UNQUOTED=value
goto nonexistent
set "PROPERLY_QUOTED=safe value"
"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Test main execution with different argument combinations
            test_cases = [
                [temp_file_path],
                [temp_file_path, "--summary"],
                [temp_file_path, "--severity"],
                [temp_file_path, "--summary", "--severity"],
            ]

            for args in test_cases:
                sys.argv = ["blinter.py"] + args

                # Mock print to capture output without cluttering test output
                with patch("builtins.print"):
                    try:
                        main()  # This should execute without error
                    except SystemExit as sys_exit:
                        # Exit code 0 or 1 is expected
                        assert sys_exit.code in [0, 1]

        finally:
            sys.argv = original_argv
            os.unlink(temp_file_path)


class TestDirectoryFunctionality:
    """Test cases for directory processing functionality."""

    def create_temp_directory_with_files(self) -> str:
        """Create a temporary directory with batch files for testing."""
        temp_dir = tempfile.mkdtemp()

        # Create test batch files
        test_files = {
            "script1.bat": "@echo off\necho Hello World\n",
            "script2.cmd": "@echo off\nset TEST=value\necho %TEST%\n",
            "good_script.bat": "@echo off\nREM This is a clean script\necho Done\nexit /b 0\n",
            "bad_script.bat": "echo off\ngoto nonexistent\nset UNQUOTED=value\n",
        }

        for filename, content in test_files.items():
            file_path = Path(temp_dir) / filename
            with open(file_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)

        # Create a subdirectory with more batch files
        subdir = Path(temp_dir) / "subdir"
        subdir.mkdir()

        subdirectory_files = {
            "sub_script.bat": "@echo off\necho From subdirectory\n",
            "another.cmd": "@echo off\nset VAR=test\n",
        }

        for filename, content in subdirectory_files.items():
            file_path = subdir / filename
            with open(file_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)

        # Create a non-batch file (should be ignored)
        non_batch_file = Path(temp_dir) / "readme.txt"
        with open(non_batch_file, "w", encoding="utf-8") as file_handle:
            file_handle.write("This is not a batch file")

        return temp_dir

    def cleanup_temp_directory(self, temp_dir: str) -> None:
        """Recursively clean up temporary directory."""
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    def test_find_batch_files_single_file(self) -> None:
        """Test find_batch_files with a single batch file."""
        content = "@echo off\necho test\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            result = find_batch_files(temp_file_path)
            assert len(result) == 1
            assert Path(result[0]) == Path(temp_file_path)
        finally:
            os.unlink(temp_file_path)

    def test_find_batch_files_single_cmd_file(self) -> None:
        """Test find_batch_files with a single CMD file."""
        content = "@echo off\necho test\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cmd", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            result = find_batch_files(temp_file_path)
            assert len(result) == 1
            assert Path(result[0]) == Path(temp_file_path)
        finally:
            os.unlink(temp_file_path)

    def test_find_batch_files_invalid_file_type(self) -> None:
        """Test find_batch_files with non-batch file raises error."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write("Not a batch file")
            temp_file_path = temp_file.name

        try:
            try:
                find_batch_files(temp_file_path)
                assert False, "Should have raised ValueError for non-batch file"
            except ValueError as error:
                assert "not a batch file" in str(error)
        finally:
            os.unlink(temp_file_path)

    def test_find_batch_files_directory_recursive(self) -> None:
        """Test find_batch_files with directory (recursive)."""
        temp_dir = self.create_temp_directory_with_files()

        try:
            result = find_batch_files(temp_dir, recursive=True)

            # Should find all .bat and .cmd files including in subdirectories
            batch_files = [f for f in result if f.suffix.lower() in [".bat", ".cmd"]]
            assert len(batch_files) == 6  # 4 in main dir + 2 in subdir

            # Check that files from subdirectory are included
            subdir_files = [f for f in result if "subdir" in str(f)]
            assert len(subdir_files) == 2

        finally:
            self.cleanup_temp_directory(temp_dir)

    def test_find_batch_files_directory_non_recursive(self) -> None:
        """Test find_batch_files with directory (non-recursive)."""
        temp_dir = self.create_temp_directory_with_files()

        try:
            result = find_batch_files(temp_dir, recursive=False)

            # Should find only .bat and .cmd files in main directory
            batch_files = [f for f in result if f.suffix.lower() in [".bat", ".cmd"]]
            assert len(batch_files) == 4  # Only files in main dir

            # Check that no files from subdirectory are included
            subdir_files = [f for f in result if "subdir" in str(f)]
            assert len(subdir_files) == 0

        finally:
            self.cleanup_temp_directory(temp_dir)

    def test_find_batch_files_nonexistent_path(self, tmp_path: Path) -> None:
        """Test find_batch_files with nonexistent path raises error."""
        with pytest.raises(FileNotFoundError):
            find_batch_files(str(tmp_path / "does-not-exist" / "nested"))

    def test_main_with_directory_argument(self) -> None:
        """Test main function with directory argument."""
        temp_dir = self.create_temp_directory_with_files()
        original_argv = sys.argv

        try:
            sys.argv = ["blinter.py", temp_dir]

            with self.capture_stdout() as captured:
                try:
                    main()
                except SystemExit as sys_exit:
                    assert sys_exit.code in [0, 1]  # Should exit with 0 or 1

                output = captured.getvalue()

                # Should show that multiple files were processed
                assert "Batch Files Analysis:" in output
                assert "Processed" in output
                assert "file" in output  # Should mention files processed

        finally:
            sys.argv = original_argv
            self.cleanup_temp_directory(temp_dir)

    def test_main_with_directory_and_summary(self) -> None:
        """Test main function with directory and --summary flag."""
        temp_dir = self.create_temp_directory_with_files()
        original_argv = sys.argv

        try:
            sys.argv = ["blinter.py", temp_dir, "--summary"]

            with self.capture_stdout() as captured:
                try:
                    main()
                except SystemExit as sys_exit:
                    assert sys_exit.code in [0, 1]

                output = captured.getvalue()

                # Should show both directory processing and summary
                assert "Batch Files Analysis:" in output
                assert "SUMMARY:" in output or "COMBINED RESULTS:" in output

        finally:
            sys.argv = original_argv
            self.cleanup_temp_directory(temp_dir)

    def test_main_with_empty_directory(self) -> None:
        """Test main function with empty directory."""
        temp_dir = tempfile.mkdtemp()
        original_argv = sys.argv

        try:
            sys.argv = ["blinter.py", temp_dir]

            with self.capture_stdout() as captured:
                with pytest.raises(SystemExit) as exit_info:
                    main()
                output = captured.getvalue()

                assert exit_info.value.code == 1
                # Should indicate no batch files found
                assert "No batch files" in output

        finally:
            sys.argv = original_argv
            self.cleanup_temp_directory(temp_dir)

    def test_main_with_no_recursive_flag(self) -> None:
        """Test main function with --no-recursive flag."""
        temp_dir = self.create_temp_directory_with_files()
        original_argv = sys.argv

        try:
            sys.argv = ["blinter.py", temp_dir, "--no-recursive"]

            with self.capture_stdout() as captured:
                try:
                    main()
                except SystemExit as sys_exit:
                    assert sys_exit.code in [0, 1]

                output = captured.getvalue()

                # Should process only main directory files (4 files)
                # The exact number might vary based on issues found
                assert "Batch Files Analysis:" in output

        finally:
            sys.argv = original_argv
            self.cleanup_temp_directory(temp_dir)

    def capture_stdout(self) -> StdoutCapture:
        """Helper method to capture stdout output."""
        return StdoutCapture()


# Advanced CLI testing scenarios
class TestCLIMainFunctionScenarios:
    """Test CLI main function edge cases and error paths."""

    def test_main_with_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main function with --help flag."""
        with patch("sys.argv", ["blinter.py", "--help"]):
            main()

        captured = capsys.readouterr()
        assert "Blinter - Help Menu" in captured.out

    def test_main_with_no_arguments(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main function with no arguments."""
        with patch("sys.argv", ["blinter.py"]):
            main()

        captured = capsys.readouterr()
        assert "Blinter - Help Menu" in captured.out

    def test_main_with_nonexistent_file(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function with nonexistent file."""
        with patch("sys.argv", ["blinter.py", "nonexistent.bat"]):
            with pytest.raises(SystemExit) as exit_info:
                main()

        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Path 'nonexistent.bat' not found." in captured.err

    def test_main_with_permission_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function with permission error."""

        with patch("sys.argv", ["blinter.py", "protected.bat"]):
            with patch(
                "blinter.cli.main.find_batch_files",
                side_effect=PermissionError("Access denied"),
            ):
                with pytest.raises(SystemExit) as exit_info:
                    main()

        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Cannot access 'protected.bat'" in captured.err

    def test_main_with_unicode_decode_error_in_processing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function handling UnicodeDecodeError during file processing."""

        # Create a test file
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".bat"
        ) as temp_file_handle:
            temp_file_handle.write("@echo off\\n")
            temp_file = temp_file_handle.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file]):
                with patch(
                    "blinter.cli.main.lint_batch_file",
                    side_effect=OSError("Could not read file"),
                ):
                    with pytest.raises(SystemExit) as exit_info:
                        main()

            assert exit_info.value.code == 1
            captured = capsys.readouterr()
            combined_output = captured.out + captured.err
            assert "Skipped files" in combined_output
        finally:
            os.unlink(temp_file)

    def test_main_with_generic_file_error_in_processing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function handling generic file errors during processing."""

        # Create a test file
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".bat"
        ) as temp_file_handle:
            temp_file_handle.write("@echo off\\n")
            temp_file = temp_file_handle.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file]):
                with patch(
                    "blinter.cli.main.lint_batch_file",
                    side_effect=OSError("Generic file error"),
                ):
                    with pytest.raises(SystemExit) as exit_info:
                        main()

            assert exit_info.value.code == 1
            captured = capsys.readouterr()
            combined_output = captured.out + captured.err
            assert "Could not process" in combined_output
        finally:
            os.unlink(temp_file)

    def test_main_no_files_could_be_processed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function when no files can be processed."""

        # Create a test file that will cause processing to fail
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".bat"
        ) as temp_file_handle:
            temp_file_handle.write("@echo off\\n")
            temp_file = temp_file_handle.name

        try:
            with patch("sys.argv", ["blinter.py", temp_file]):
                with patch(
                    "blinter.cli.main.lint_batch_file",
                    side_effect=ValueError("Processing error"),
                ):
                    with pytest.raises(SystemExit) as exit_info:
                        main()

            assert exit_info.value.code == 1
            captured = capsys.readouterr()
            assert "Error: No batch files could be processed." in captured.err
        finally:
            os.unlink(temp_file)


# Directory processing test scenarios
class TestDirectoryProcessingScenarios:
    """Test directory processing edge cases."""

    def test_find_batch_files_empty_directory(self) -> None:
        """Test find_batch_files with empty directory."""

        with tempfile.TemporaryDirectory() as temp_dir:
            batch_files = find_batch_files(temp_dir, recursive=False)
            assert len(batch_files) == 0

    def test_find_batch_files_directory_with_mixed_files(self) -> None:
        """Test find_batch_files with directory containing mixed file types."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create various file types
            (Path(temp_dir) / "script.bat").write_text("@echo off\\n")
            (Path(temp_dir) / "script.cmd").write_text("@echo off\\n")
            (Path(temp_dir) / "readme.txt").write_text("This is not a batch file\\n")
            (Path(temp_dir) / "script.py").write_text("print('hello')\\n")

            batch_files = find_batch_files(temp_dir, recursive=False)
            assert len(batch_files) == 2  # Only .bat and .cmd files

    def test_find_batch_files_recursive_vs_non_recursive(self) -> None:
        """Test find_batch_files recursive vs non-recursive behavior."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files in root directory
            (Path(temp_dir) / "root.bat").write_text("@echo off\\n")

            # Create subdirectory with files
            sub_dir = Path(temp_dir) / "subdir"
            sub_dir.mkdir()
            (sub_dir / "sub.bat").write_text("@echo off\\n")

            # Non-recursive should find only root file
            batch_files_non_recursive = find_batch_files(temp_dir, recursive=False)
            assert len(batch_files_non_recursive) == 1
            assert "root.bat" in str(batch_files_non_recursive[0])

            # Recursive should find both files
            batch_files_recursive = find_batch_files(temp_dir, recursive=True)
            assert len(batch_files_recursive) == 2


class TestMainFunctionEdgeCases:
    """Test main function edge cases and boundary conditions."""

    def test_main_function_no_path_provided_edge_case(self) -> None:
        """Test main function with no path provided after processing args."""

        original_argv = sys.argv.copy()
        try:
            # Test with only flags but no path
            sys.argv = ["blinter", "--summary", "--severity"]

            with patch("builtins.print") as mock_print:
                with patch("blinter.cli.args.print_help") as mock_help:
                    with pytest.raises(SystemExit) as exit_info:
                        main()

                    assert exit_info.value.code == 1
                    # Verify error message and help are shown
                    mock_print.assert_any_call(
                        "Error: No batch file or directory provided.\n",
                        file=sys.stderr,
                    )
                    mock_help.assert_called_once()
        finally:
            sys.argv = original_argv

    def test_main_function_argument_processing_edge_cases(self) -> None:
        """Test main function argument processing edge cases."""

        original_argv = sys.argv.copy()
        try:
            # Test with target_path being None initially
            sys.argv = ["blinter", "--severity", "test.bat"]

            # Create a temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".bat", delete=False
            ) as temp_file:
                temp_file.write("@echo off\necho test\n")
                temp_file_path = temp_file.name

            try:
                # Replace the test.bat with actual temp file
                sys.argv[2] = temp_file_path

                with patch("builtins.print"):
                    try:
                        main()  # Should process successfully
                    except SystemExit:
                        pass  # Expected for successful processing
            finally:
                os.unlink(temp_file_path)
        finally:
            sys.argv = original_argv

    def test_main_function_find_batch_files_error(self) -> None:
        """Test main function when find_batch_files raises an error."""

        original_argv = sys.argv.copy()
        try:
            sys.argv = ["blinter", "nonexistent_directory_path_12345"]

            with patch("builtins.print") as mock_print:
                with pytest.raises(SystemExit) as exit_info:
                    main()

                assert exit_info.value.code == 1
                # Should print file not found error
                mock_print.assert_any_call(
                    "Error: Path 'nonexistent_directory_path_12345' not found.",
                    file=sys.stderr,
                )
        finally:
            sys.argv = original_argv

    def test_main_function_file_processing_errors(self) -> None:
        """Test main function with file processing errors."""

        original_argv = sys.argv.copy()

        # Create a temporary directory with a file
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, "test.bat")
            with open(temp_file_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("@echo off\necho test\n")

            try:
                sys.argv = ["blinter", temp_dir]

                # Mock lint_batch_file to raise different types of errors
                with patch("blinter.cli.main.lint_batch_file") as mock_lint:
                    with patch("builtins.print") as mock_print:
                        # Test FileNotFoundError
                        mock_lint.side_effect = FileNotFoundError("File not found")
                        with pytest.raises(SystemExit):
                            main()

                        # Should handle the error gracefully
                        assert mock_print.called

                        # Test PermissionError
                        mock_lint.side_effect = PermissionError("Access denied")
                        with pytest.raises(SystemExit):
                            main()

                        # Test UnicodeDecodeError (skipped like other per-file failures)
                        mock_lint.side_effect = UnicodeDecodeError(
                            "utf-8", b"", 0, 1, "invalid start byte"
                        )
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1

                        # Test generic Exception (per-file internal errors are skipped)
                        mock_lint.side_effect = Exception("Generic error")
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1
            finally:
                sys.argv = original_argv

    def test_main_function_no_files_found_scenario(self) -> None:
        """Test main function when no batch files are found."""

        original_argv = sys.argv.copy()

        # Create a temporary directory with no batch files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a non-batch file
            non_batch_file = os.path.join(temp_dir, "test.txt")
            with open(non_batch_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("not a batch file")

            try:
                sys.argv = ["blinter", temp_dir]

                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exit_info:
                        main()

                    assert exit_info.value.code == 1
                    # Should report no files found (check for either possible message)
                    print_calls = [str(call) for call in mock_print.call_args_list]
                    assert any("No batch files" in call for call in print_calls)
            finally:
                sys.argv = original_argv

    def test_main_function_comprehensive_error_handling(self) -> None:
        """Test comprehensive error handling in main function."""

        original_argv = sys.argv.copy()

        try:
            # Test various argument combinations that might trigger different code paths
            test_cases = [
                ["blinter", "--help"],
                ["blinter"],  # No arguments
                ["blinter", "--summary"],  # Only flag, no path
                ["blinter", "--no-recursive", "nonexistent"],
            ]

            for test_argv in test_cases:
                sys.argv = test_argv.copy()
                try:
                    with patch("builtins.print"):
                        with patch("blinter.cli.args.print_help"):
                            main()
                except SystemExit:
                    pass  # Expected for some cases like --help
                except Exception:
                    pass  # Acceptable for error cases
        finally:
            sys.argv = original_argv

    def test_main_function_edge_paths(self) -> None:
        """Test main function paths that might not be covered."""

        original_argv = sys.argv.copy()

        try:
            # Test with various edge case arguments
            test_cases = [
                ["blinter", "--summary", "--no-recursive"],
                ["blinter", "--severity", "--summary"],
            ]

            for test_argv in test_cases:
                sys.argv = test_argv + ["nonexistent_file_xyz.bat"]
                try:
                    with patch("builtins.print"):
                        main()
                except SystemExit:
                    pass  # Expected
                except FileNotFoundError:
                    pass  # Expected
                except Exception:
                    pass  # Acceptable for edge cases
        finally:
            sys.argv = original_argv

    def test_main_function_no_path_provided(self) -> None:
        """Test main function when no path is provided."""

        original_argv = sys.argv[:]
        try:
            sys.argv = ["blinter.py"]  # No path argument
            main()  # Should print help and return
        except SystemExit:
            pass  # Expected
        finally:
            sys.argv = original_argv

    def test_main_function_single_file_processing(self) -> None:
        """Test main function processing single file vs directory."""

        # Create a temporary batch file
        fd, temp_path = tempfile.mkstemp(suffix=".bat")
        try:
            os.write(fd, b"@ECHO OFF\necho Hello World\nEXIT /b 0")
            os.close(fd)

            original_argv = sys.argv[:]
            try:
                sys.argv = ["blinter.py", temp_path]
                main()  # Should process single file
            except SystemExit:
                pass  # Expected
            finally:
                sys.argv = original_argv
        finally:
            try:
                os.unlink(temp_path)
            except (OSError, PermissionError):
                pass

    def test_main_success_path_with_clean_file(self) -> None:
        """Test main() success path when no issues are found."""
        # Create a very simple, clean batch file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            # Write minimal content that should have no issues
            temp_file.write("@echo off\n")
            temp_path = temp_file.name

        try:
            # Test the success path when no issues are found
            with patch("sys.argv", ["blinter", temp_path]):
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print") as mock_print:
                        main()
                        # Should exit with code 0 for success
                        mock_exit.assert_called_with(0)
                        # Check for success message output
                        print_calls = [str(call) for call in mock_print.call_args_list]
                        success_message_found = any(
                            "No issues found" in call for call in print_calls
                        )
                        assert success_message_found or mock_exit.called
        finally:
            os.unlink(temp_path)

    def test_main_error_path_with_critical_issues(self) -> None:
        """Test main() error path when critical errors are found."""
        # Create a batch file with critical errors
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write("@echo off\n" "goto :missing_label\n")
            temp_path = temp_file.name

        try:
            # Test the error path when critical issues are found
            with patch("sys.argv", ["blinter", temp_path]):
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print") as mock_print:
                        main()
                        # Should exit with error code 1
                        assert mock_exit.called
                        # Check that error handling was triggered
                        exit_code = (
                            mock_exit.call_args[0][0] if mock_exit.call_args else 0
                        )
                        assert exit_code == 1
                        # Verify that some output was generated
                        assert (
                            mock_print.called
                        )  # Should have printed error information
        finally:
            os.unlink(temp_path)


class TestVersionFunctionality:
    """Tests for version display functionality."""

    def test_version_flag(self) -> None:
        """Test that --version flag displays version information."""
        project_version = get_project_version()
        with patch("sys.argv", ["blinter", "--version"]):
            with StdoutCapture() as captured:
                main()
                output = captured.getvalue()

        # Check for version information in output (just the version number)
        assert f"v{project_version}" in output
        # Ensure author and license are NOT shown
        assert "Author:" not in output
        assert "License:" not in output

    def test_version_in_help(self) -> None:
        """Test that version is displayed in help menu."""
        project_version = get_project_version()
        with patch("sys.argv", ["blinter", "--help"]):
            with StdoutCapture() as captured:
                main()
                output = captured.getvalue()

            # Check for version in help text
            assert "Blinter - Help Menu" in output
            assert f"Version: {project_version}" in output

    def test_version_in_normal_run(self) -> None:
        """Test that version is displayed when script runs normally."""
        project_version = get_project_version()
        # Create a temporary batch file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write("@echo off\n")
            temp_file.write("echo Hello World\n")
            temp_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter", temp_path]):
                with patch("sys.exit"):
                    with StdoutCapture() as captured:
                        main()
                        output = captured.getvalue()

                    # Check that version is displayed at the start
                    assert f"Blinter v{project_version} - Batch File Linter" in output
        finally:
            os.unlink(temp_path)

    def test_unknown_flag_exits_with_error(self) -> None:
        """Test that unknown CLI flags exit with an error."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write("@echo off\n")
            temp_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter", temp_path, "--not-a-real-flag"]):
                with StdoutCapture() as captured:
                    with pytest.raises(SystemExit) as exit_info:
                        main()
                    output = captured.getvalue()

                assert exit_info.value.code == 1
                assert "Unknown option '--not-a-real-flag'" in output
        finally:
            os.unlink(temp_path)


class TestFollowCallsCLI:
    """Test follow_calls via CLI to cover additional code paths."""

    def test_cli_follow_calls_with_existing_script(self) -> None:
        """Test follow_calls via CLI with actual file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script
            helper_script = os.path.join(tmpdir, "helper.cmd")
            with open(helper_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("SET VAR=value\n")
                bat_file.write("EXIT /b 0\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.cmd")
            with open(main_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("CALL helper.cmd\n")
                bat_file.write("EXIT /b 0\n")

            # Test via CLI
            with patch.object(
                sys, "argv", ["blinter.py", main_script, "--follow-calls"]
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                # Exit code 0 means success
                assert exc_info.value.code == 0

    def test_cli_follow_calls_with_errors_in_called_script(self) -> None:
        """Test follow_calls when called script has syntax errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper_script = os.path.join(tmpdir, "helper.cmd")
            with open(helper_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("if ( echo bad syntax\n")
                bat_file.write("EXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.cmd")
            with open(main_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("CALL helper.cmd\n")
                bat_file.write("EXIT /b 0\n")

            # Callee errors are informational; parent exit stays 0 when primary is clean
            with patch.object(
                sys, "argv", ["blinter.py", main_script, "--follow-calls"]
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_cli_callee_fatal_issues_do_not_change_parent_exit(self) -> None:
        """Fatal findings in called scripts must not fail the primary target exit code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper_script = os.path.join(tmpdir, "helper.cmd")
            with open(helper_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("if ( unclosed syntax\n")
                bat_file.write("EXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.cmd")
            with open(main_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("CALL helper.cmd\n")
                bat_file.write("EXIT /b 0\n")

            with patch.object(
                sys, "argv", ["blinter.py", main_script, "--follow-calls"]
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_cli_callee_security_does_not_change_parent_exit(self) -> None:
        """Security findings in called scripts must not fail the primary exit code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper_script = os.path.join(tmpdir, "helper.cmd")
            with open(helper_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("reg delete HKLM\\Software\\Test /f\n")
                bat_file.write("EXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.cmd")
            with open(main_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write("CALL helper.cmd\n")
                bat_file.write("EXIT /b 0\n")

            with patch.object(
                sys, "argv", ["blinter.py", main_script, "--follow-calls"]
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_cli_follow_calls_outside_root_no_crash(self) -> None:
        """Directory scan with follow_calls must not crash on outside paths."""
        with tempfile.TemporaryDirectory() as outer:
            outside_dir = os.path.join(outer, "outside")
            scan_dir = os.path.join(outer, "scan")
            os.makedirs(outside_dir)
            os.makedirs(scan_dir)

            outside_script = os.path.join(outside_dir, "outside.bat")
            with open(outside_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\nSET X=1\nEXIT /b 0\n")

            main_script = os.path.join(scan_dir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\n")
                bat_file.write('CALL "..\\outside\\outside.bat"\n')
                bat_file.write("EXIT /b 0\n")

            second_script = os.path.join(scan_dir, "second.bat")
            with open(second_script, "w", encoding="utf-8") as bat_file:
                bat_file.write("@ECHO OFF\nEXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter.py", scan_dir, "--follow-calls"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code in [0, 1]


class TestScanRootDerivation:  # pylint: disable=too-few-public-methods
    """Test scan_root derivation from CLI target paths."""

    def test_scan_root_from_directory_target(self) -> None:
        """Directory target sets scan_root to the resolved directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cli_args = CliArguments(
                target_path=temp_dir,
                use_config=False,
                cli_show_summary=None,
                cli_recursive=None,
                cli_follow_calls=None,
                cli_max_line_length=None,
                cli_log_level=None,
            )
            config = BlinterConfig()
            _apply_cli_config_overrides(cli_args, config)
            assert config.scan_root == str(Path(temp_dir).resolve())

    def test_scan_root_from_file_target(self) -> None:
        """File target sets scan_root to the resolved parent directory."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write("@ECHO OFF\n")
            temp_path = temp_file.name

        try:
            cli_args = CliArguments(
                target_path=temp_path,
                use_config=False,
                cli_show_summary=None,
                cli_recursive=None,
                cli_follow_calls=None,
                cli_max_line_length=None,
                cli_log_level=None,
            )
            config = BlinterConfig()
            _apply_cli_config_overrides(cli_args, config)
            assert config.scan_root == str(Path(temp_path).parent.resolve())
        finally:
            os.unlink(temp_path)


class TestCliLogging:  # pylint: disable=too-few-public-methods
    """Test CLI logging configuration."""

    def test_configure_cli_logging_adds_handler(self) -> None:
        """CLI should attach a stderr handler when none is configured."""
        blinter_logger = logging.getLogger("blinter")
        blinter_logger.handlers.clear()
        _configure_cli_logging()
        assert blinter_logger.handlers

    def test_configure_cli_logging_verbose_level(self) -> None:
        """Verbose mode should set DEBUG log level."""
        blinter_logger = logging.getLogger("blinter")
        blinter_logger.handlers.clear()
        _configure_cli_logging(logging.DEBUG)
        assert blinter_logger.level == logging.DEBUG

    def test_configure_cli_logging_quiet_level(self) -> None:
        """Quiet mode should set ERROR log level."""
        blinter_logger = logging.getLogger("blinter")
        blinter_logger.handlers.clear()
        _configure_cli_logging(logging.ERROR)
        assert blinter_logger.level == logging.ERROR

    def test_configure_cli_logging_removes_closed_handler(self) -> None:
        """Closed CLI stream handlers are replaced with a fresh stderr handler."""
        import io

        blinter_logger = logging.getLogger("blinter")
        blinter_logger.handlers.clear()

        closed_stream = io.StringIO()
        closed_stream.close()
        stale_handler = logging.StreamHandler(closed_stream)
        setattr(stale_handler, "blinter_cli_handler", True)
        blinter_logger.addHandler(stale_handler)

        _configure_cli_logging()
        assert len(blinter_logger.handlers) == 1
        handler = blinter_logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr

    def test_configure_cli_logging_reuses_marked_open_handler(self) -> None:
        """An existing open CLI-marked handler is reused instead of adding another."""
        blinter_logger = logging.getLogger("blinter")
        blinter_logger.handlers.clear()

        handler = logging.StreamHandler(sys.stderr)
        setattr(handler, "blinter_cli_handler", True)
        blinter_logger.addHandler(handler)

        _configure_cli_logging(logging.INFO)

        assert len(blinter_logger.handlers) == 1
        assert blinter_logger.handlers[0] is handler
        assert blinter_logger.level == logging.INFO

    def test_configure_cli_logging_ignores_foreign_handlers(self) -> None:
        """Handlers without the CLI marker are left in place; a new CLI handler is added."""
        blinter_logger = logging.getLogger("blinter")
        blinter_logger.handlers.clear()

        foreign_handler = logging.StreamHandler(sys.stderr)
        blinter_logger.addHandler(foreign_handler)

        _configure_cli_logging(logging.WARNING)

        cli_handlers = [
            item
            for item in blinter_logger.handlers
            if getattr(item, "blinter_cli_handler", False)
        ]
        assert foreign_handler in blinter_logger.handlers
        assert len(cli_handlers) == 1


class TestFollowCallsProcessing:  # pylint: disable=too-few-public-methods
    """Test follow-calls processing limits in CLI."""

    def test_process_single_called_script_skips_at_file_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Called scripts are skipped once MAX_FOLLOW_CALL_FILES is reached."""
        monkeypatch.setattr("blinter.cli.main.MAX_FOLLOW_CALL_FILES", 1)

        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
        existing = tmp_path / "existing.bat"

        state = ProcessingState(
            processed_files={existing.resolve()},
            all_issues=[],
            file_results={},
            processed_file_paths=[],
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        processed, errors = _process_single_called_script(
            helper, config, state, "parent.bat"
        )
        assert (processed, errors) == (0, 0)

    def test_process_single_called_script_skips_outside_scan_root(
        self, tmp_path: Path
    ) -> None:
        """Called scripts outside scan_root are skipped without error."""
        scan_root = tmp_path / "project"
        scan_root.mkdir()
        outside = tmp_path / "outside.bat"
        outside.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")

        state = ProcessingState(
            processed_files=set(),
            all_issues=[],
            file_results={},
            processed_file_paths=[],
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(scan_root))

        processed, errors = _process_single_called_script(
            outside, config, state, "parent.bat"
        )
        assert (processed, errors) == (0, 0)

    def test_process_called_scripts_stops_at_depth_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nested follow-calls stop when MAX_FOLLOW_CALL_DEPTH is exceeded."""
        monkeypatch.setattr("blinter.cli.main.MAX_FOLLOW_CALL_DEPTH", 0)

        root_script = tmp_path / "root.bat"
        child_script = tmp_path / "child.bat"
        root_script.write_text(
            f'@ECHO OFF\ncall "{child_script.name}"\n', encoding="utf-8"
        )
        child_script.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")

        state = ProcessingState(
            processed_files={root_script.resolve()},
            all_issues=[],
            file_results={},
            processed_file_paths=[(str(root_script), None)],
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        processed, errors = _process_called_scripts(root_script, config, state, depth=1)

        assert (processed, errors) == (0, 0)

    def test_process_single_called_script_skips_already_processed(
        self, tmp_path: Path
    ) -> None:
        """Called scripts already in processed_files are not linted again."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")

        state = ProcessingState(
            processed_files={helper.resolve()},
            all_issues=[],
            file_results={},
            processed_file_paths=[],
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        processed, errors = _process_single_called_script(
            helper, config, state, "parent.bat"
        )
        assert (processed, errors) == (0, 0)

    def test_process_single_called_script_file_error_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """Read/lint failures on called scripts are logged and skipped."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")

        state = ProcessingState(
            processed_files=set(),
            all_issues=[],
            file_results={},
            processed_file_paths=[],
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        with patch(
            "blinter.cli.main.lint_batch_file",
            side_effect=PermissionError("Access denied"),
        ):
            processed, errors = _process_single_called_script(
                helper, config, state, "parent.bat"
            )

        assert (processed, errors) == (0, 0)
        assert helper.resolve() not in state.processed_files

    def test_process_called_scripts_stops_at_file_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Follow-calls stops enqueueing callees once MAX_FOLLOW_CALL_FILES is reached."""
        monkeypatch.setattr("blinter.cli.main.MAX_FOLLOW_CALL_FILES", 1)

        helper_a = tmp_path / "a.bat"
        helper_b = tmp_path / "b.bat"
        helper_a.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
        helper_b.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
        root_script = tmp_path / "root.bat"
        root_script.write_text(
            f'@ECHO OFF\nCALL "{helper_a.name}"\nCALL "{helper_b.name}"\n',
            encoding="utf-8",
        )

        state = ProcessingState(
            processed_files={root_script.resolve()},
            all_issues=[],
            file_results={},
            processed_file_paths=[(str(root_script), None)],
            lines_cache={
                root_script.resolve(): root_script.read_text().splitlines(keepends=True)
            },
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        processed, errors = _process_called_scripts(root_script, config, state)

        assert (processed, errors) == (0, 0)

    def test_process_single_called_script_internal_error_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """Internal errors linting a called script do not abort follow-calls."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")

        state = ProcessingState(
            processed_files=set(),
            all_issues=[],
            file_results={},
            processed_file_paths=[],
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        with patch(
            "blinter.cli.main.lint_batch_file",
            side_effect=RuntimeError("simulated internal failure"),
        ):
            processed, errors = _process_single_called_script(
                helper, config, state, "parent.bat"
            )

        assert (processed, errors) == (0, 0)
        assert helper.resolve() not in state.processed_files

    def test_process_single_called_script_passes_shared_cache(
        self, tmp_path: Path
    ) -> None:
        """Called scripts receive the shared lines_cache."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")

        state = ProcessingState(
            processed_files=set(),
            all_issues=[],
            file_results={},
            processed_file_paths=[],
            lines_cache={},
        )
        config = BlinterConfig(follow_calls=True, scan_root=str(tmp_path))

        with patch("blinter.cli.main.lint_batch_file", return_value=[]) as mock_lint:
            _process_single_called_script(
                helper,
                config,
                state,
                "parent.bat",
            )

        mock_lint.assert_called_once_with(
            str(helper),
            config=config,
            lines_cache=state.lines_cache,
        )


class TestCLIArgumentValidation:  # pylint: disable=too-few-public-methods
    """Test CLI argument validation edge cases."""

    def test_multiple_positional_paths_rejected(self) -> None:
        """Only one target path is allowed."""
        with patch.object(
            sys,
            "argv",
            ["blinter.py", "first.bat", "second.bat"],
        ):
            with patch("blinter.cli.args.print_help"):
                with pytest.raises(SystemExit) as exc_info:
                    _parse_cli_arguments()
                assert exc_info.value.code == 1

    def test_verbose_and_quiet_mutually_exclusive(self) -> None:
        """--verbose and --quiet cannot be used together."""
        with patch.object(
            sys,
            "argv",
            ["blinter.py", "test.bat", "--verbose", "--quiet"],
        ):
            with patch("blinter.cli.args.print_help"):
                with pytest.raises(SystemExit) as exc_info:
                    _parse_cli_arguments()
                assert exc_info.value.code == 1

    def test_severity_flag_emits_deprecation_warning(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--severity emits a deprecation warning and has no effect."""
        with patch.object(sys, "argv", ["blinter.py", "test.bat", "--severity"]):
            _parse_regular_arguments()
        captured = capsys.readouterr()
        assert "deprecated" in captured.err.lower()
        assert "min_severity" in captured.err

    def test_create_config_writes_default_file(self) -> None:
        """--create-config should write blinter.ini and exit early."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with patch.object(sys, "argv", ["blinter", "--create-config"]):
                    result = _parse_cli_arguments()
                assert result is None
                assert Path("blinter.ini").is_file()
            finally:
                os.chdir(original_cwd)

    def test_create_config_existing_file_requires_force(self) -> None:
        """--create-config without --force fails when blinter.ini exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                Path("blinter.ini").write_text("[general]\n", encoding="utf-8")
                with patch.object(sys, "argv", ["blinter", "--create-config"]):
                    with patch("blinter.cli.args.print_help"):
                        with pytest.raises(SystemExit) as exc_info:
                            _parse_cli_arguments()
                assert exc_info.value.code == 1
            finally:
                os.chdir(original_cwd)

    def test_config_option_requires_path(self) -> None:
        """--config without a path should exit with code 1."""
        with patch.object(sys, "argv", ["blinter", "test.bat", "--config"]):
            with patch("blinter.cli.args.print_help"):
                with pytest.raises(SystemExit) as exc_info:
                    _parse_cli_arguments()
                assert exc_info.value.code == 1


class TestCLIEdgeCases:  # pylint: disable=too-few-public-methods
    """Test CLI edge cases for additional coverage."""

    def test_cli_no_issues_multiple_files(self) -> None:
        """Test CLI with multiple clean files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple clean files
            for i in range(3):
                bat_file = os.path.join(tmpdir, f"file{i}.bat")
                with open(bat_file, "w", encoding="utf-8") as file_handle:
                    file_handle.write("@ECHO OFF\nEXIT /b 0\n")

            # Test via CLI
            with patch.object(sys, "argv", ["blinter.py", tmpdir]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_cli_with_warnings_but_no_errors(self) -> None:
        """Test CLI with warnings but no errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "test.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET VAR=value\n")  # Might trigger warnings
                file_handle.write("EXIT /b 0\n")

            # Test via CLI
            with patch.object(sys, "argv", ["blinter.py", bat_file]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                # Should exit 0 if only warnings
                assert exc_info.value.code in [0, 1]

    def test_cli_single_file_no_issues(self) -> None:
        """Test CLI with single file and no issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "clean.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nEXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter.py", bat_file]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_cli_single_file_with_issues(self) -> None:
        """Test CLI with single file that has issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "bad.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                # Create file with style issues but no errors
                file_handle.write("echo no @\n")
                file_handle.write("EXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter.py", bat_file]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                # Style issues only exit with 0
                assert exc_info.value.code == 0


class TestCliFatalExitCodes:  # pylint: disable=too-few-public-methods
    """Test CLI exit codes for ERROR and SECURITY severities."""

    def test_cli_exits_1_on_security_findings_only(self) -> None:
        """SECURITY findings must cause non-zero exit without ERROR findings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "risky.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("RMDIR /S /Q C:\\temp\\folder\n")
                file_handle.write("EXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter", bat_file]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    def test_cli_exits_1_on_error_findings(self) -> None:
        """ERROR findings must cause non-zero exit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "broken.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("IF EXIST file (\n")
                file_handle.write("EXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter", bat_file]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    def test_cli_exits_0_on_warnings_without_fatal_issues(self) -> None:
        """WARNING-only findings must not cause non-zero exit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "warn.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("DEL important.txt\n")
                file_handle.write("EXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter", bat_file]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0


class TestCliSkippedFilesExitCodes:  # pylint: disable=too-few-public-methods
    """Test CLI exit codes when some files cannot be processed."""

    def test_cli_exits_1_when_some_files_skipped_but_others_ok(self) -> None:
        """Partial skips exit 1 even when remaining files lint cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            good_bat = os.path.join(tmpdir, "good.bat")
            bad_bat = os.path.join(tmpdir, "bad.bat")
            with open(good_bat, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nEXIT /b 0\n")
            with open(bad_bat, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")

            def lint_side_effect(
                file_path: str, *args: object, **kwargs: object
            ) -> list[object]:
                if file_path.endswith("bad.bat"):
                    raise PermissionError("Access denied")
                return []

            with patch(
                "blinter.cli.main.lint_batch_file", side_effect=lint_side_effect
            ):
                with patch.object(sys, "argv", ["blinter", tmpdir]):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1

    def test_cli_exits_0_when_all_files_processed(self) -> None:
        """All files processed successfully with no fatal findings exits 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            good_bat = os.path.join(tmpdir, "good.bat")
            with open(good_bat, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nEXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter", tmpdir]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0


class TestCliUnexpectedErrorExit:  # pylint: disable=too-few-public-methods
    """Test CLI exit code for unexpected internal failures."""

    def test_cli_exits_2_on_unexpected_internal_error(self) -> None:
        """Unexpected exceptions during CLI execution must exit with code 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat_file = os.path.join(tmpdir, "test.bat")
            with open(bat_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nEXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter", bat_file]):
                with patch(
                    "blinter.cli.main.find_batch_files",
                    side_effect=RuntimeError("unexpected failure"),
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 2


class TestCliStdioAndModuleEntry:
    """Test console encoding setup and python -m blinter entry point."""

    def test_configure_stdio_utf8_handles_missing_reconfigure(self) -> None:
        """Streams without reconfigure() are skipped without error."""
        from blinter.cli.main import _configure_stdio_utf8

        class _LegacyStream:
            """Stream stub lacking reconfigure()."""

            encoding = "cp1252"

        with patch("blinter.cli.main.sys.stdout", _LegacyStream()):
            with patch("blinter.cli.main.sys.stderr", _LegacyStream()):
                _configure_stdio_utf8()

    def test_configure_stdio_utf8_handles_oserror(self) -> None:
        """OSError during reconfigure is swallowed."""
        from blinter.cli.main import _configure_stdio_utf8

        class _FailingStream:
            """Stream stub whose reconfigure() raises OSError."""

            def reconfigure(self, **_kwargs: object) -> None:
                raise OSError("not supported")

        with patch("blinter.cli.main.sys.stdout", _FailingStream()):
            with patch("blinter.cli.main.sys.stderr", _FailingStream()):
                _configure_stdio_utf8()

    def test_skipped_files_message_printed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Skipped files are reported in CLI output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            good_bat = os.path.join(tmpdir, "good.bat")
            bad_bat = os.path.join(tmpdir, "bad.bat")
            with open(good_bat, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nEXIT /b 0\n")
            with open(bad_bat, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")

            def lint_side_effect(
                file_path: str, *args: object, **kwargs: object
            ) -> list[object]:
                if file_path.endswith("bad.bat"):
                    raise PermissionError("Access denied")
                return []

            with patch(
                "blinter.cli.main.lint_batch_file", side_effect=lint_side_effect
            ):
                with patch.object(sys, "argv", ["blinter", tmpdir]):
                    with pytest.raises(SystemExit) as exit_info:
                        main()

            assert exit_info.value.code == 1
            captured = capsys.readouterr()
            assert "Skipped files" in captured.out
            assert "bad.bat" in captured.out

    def test_skipped_files_exit_one_when_all_fail(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CLI exits 1 when every file is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_bat = os.path.join(tmpdir, "bad.bat")
            with open(bad_bat, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")

            def lint_side_effect(
                file_path: str, *args: object, **kwargs: object
            ) -> list[object]:
                raise PermissionError("Access denied")

            with patch(
                "blinter.cli.main.lint_batch_file", side_effect=lint_side_effect
            ):
                with patch.object(sys, "argv", ["blinter", tmpdir]):
                    with pytest.raises(SystemExit) as exit_info:
                        main()

            assert exit_info.value.code == 1
            captured = capsys.readouterr()
            assert "Skipped files" in captured.out

    def test_python_m_blinter_module_entry(self) -> None:
        """python -m blinter runs the CLI entry point."""
        import subprocess
        import sys as sys_module

        result = subprocess.run(
            [sys_module.executable, "-m", "blinter", "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Blinter" in result.stdout or "usage" in result.stdout.lower()


from tests.corpus_support import CORPUS_DIR, CORPUS_SKIP_REASON, corpus_available


@pytest.mark.needs_corpus
@pytest.mark.skipif(not corpus_available(), reason=CORPUS_SKIP_REASON)
@pytest.mark.slow
class TestCorpusCli:
    """CLI integration against the local batch-script-examples corpus."""

    def test_cli_corpus_directory_scan_completes_without_internal_error(self) -> None:
        with patch.object(sys, "argv", ["blinter", str(CORPUS_DIR)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code in (0, 1)

    def test_cli_corpus_follow_calls_summary_completes_without_internal_error(
        self,
    ) -> None:
        with patch.object(
            sys,
            "argv",
            ["blinter", str(CORPUS_DIR), "--follow-calls", "--summary"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code in (0, 1)

    def test_find_batch_files_discovers_full_corpus(self) -> None:
        discovered = find_batch_files(str(CORPUS_DIR), recursive=True)
        names = {Path(path).name for path in discovered}
        assert len(names) >= 85
        assert "%MM%.cmd" in names
