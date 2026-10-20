"""Tests for error handling and edge cases in real-world usage scenarios."""

import os
from pathlib import Path
import tempfile
from typing import List
from unittest.mock import mock_open, patch
import warnings

import pytest

from blinter import (
    LintIssue,
    find_batch_files,
    lint_batch_file,
    main,
    read_file_with_encoding,
)
from blinter.checkers.security import _check_security_issues
from blinter.checkers.syntax import _check_syntax_errors
from blinter.checkers.warnings import _check_warning_issues
from blinter.constants import ABSOLUTE_MAX_LINE_LENGTH, MAX_LINE_LENGTH
from blinter.io.discovery import is_path_under_root
from blinter.io.encoding import _detect_line_endings
from tests.conftest import patch_valid_encoding_path


class TestRealWorldErrorHandling:
    """Test error handling in real-world scenarios."""

    def test_file_encoding_all_fail_scenario(self) -> None:
        """Test scenario where all encoding attempts fail with different errors."""
        with (
            patch_valid_encoding_path(read_data=b"test data"),
            patch("builtins.open", mock_open(read_data=b"test data")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_empty_file_edge_case_in_context(self) -> None:
        """Test handling empty files in real linting context."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write("")  # Empty file
            temp_path = temp_file.name

        try:
            issues = lint_batch_file(temp_path)
            assert len(issues) == 0  # Empty file should have no issues
        finally:
            os.unlink(temp_path)

    def test_large_file_handling(self) -> None:
        """Test handling of large batch files."""
        # Create a large batch file with many lines
        large_content = "@ECHO OFF\n" + "REM Large file test\n" * 1000 + "EXIT /B 0\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(large_content)
            temp_path = temp_file.name

        try:
            issues = lint_batch_file(temp_path)
            # Should handle large files without issues
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_path)

    def test_binary_file_handling(self) -> None:
        """Test handling of binary files masquerading as batch files."""
        binary_content = b"\x00\x01\x02\x03" * 100  # Binary content

        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(binary_content)
            temp_path = temp_file.name

        try:
            # Should handle binary files gracefully
            lines, encoding = read_file_with_encoding(temp_path)
            assert isinstance(lines, list)
            assert isinstance(encoding, str)
        finally:
            os.unlink(temp_path)

    def test_file_with_mixed_line_endings(self) -> None:
        """Test handling of files with mixed line endings."""
        mixed_content = "@ECHO OFF\r\necho Windows line ending\necho Unix line ending\r\necho Mixed\n"

        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(mixed_content.encode("utf-8"))
            temp_path = temp_file.name

        try:
            issues = lint_batch_file(temp_path)
            # Should handle mixed line endings
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_path)

    def test_file_with_very_long_lines(self) -> None:
        """Test handling of files with extremely long lines."""
        long_line = "REM " + "A" * 500 + "\n"
        content = "@ECHO OFF\n" + long_line + "EXIT /B 0\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            issues = lint_batch_file(temp_path)
            # Should detect S020 (long line without continuation)
            long_line_issues = [i for i in issues if i.rule.code == "S020"]
            assert len(long_line_issues) >= 1
        finally:
            os.unlink(temp_path)

    def test_long_line_is_an_error_and_rest_of_file_is_linted(self) -> None:
        """A line over MAX_LINE_LENGTH is E048; later lines are still checked."""

        content = (
            "@ECHO OFF\n" + ("A" * (MAX_LINE_LENGTH + 1)) + "\necho hi\nEXIT /B 0\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            issues = lint_batch_file(temp_path)
            e048 = [issue for issue in issues if issue.rule.code == "E048"]
            assert len(e048) == 1
            assert e048[0].line_number == 2
        finally:
            os.unlink(temp_path)

    def test_rejects_line_over_absolute_maximum(self) -> None:
        """A line over the absolute cap still rejects the whole file."""

        content = "@ECHO OFF\n" + ("A" * (ABSOLUTE_MAX_LINE_LENGTH + 1)) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            with pytest.raises(ValueError, match="absolute maximum length"):
                lint_batch_file(temp_path)
        finally:
            os.unlink(temp_path)

    def test_sequential_repeated_file_access(self) -> None:
        """Test repeated linting of the same file returns consistent results."""
        content = "@ECHO OFF\necho test\nEXIT /B 0\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            issues1 = lint_batch_file(temp_path)
            issues2 = lint_batch_file(temp_path)
            assert len(issues1) == len(issues2)
        finally:
            os.unlink(temp_path)


class TestSpecificEdgeCases:
    """Test specific edge cases that may not have been covered."""

    def test_syntax_error_edge_cases(self) -> None:
        """Test specific syntax error edge cases."""
        labels = {":test": 1, ":end": 5}

        # Test GOTO with various formats
        test_cases = [
            ("goto test", 0),  # Should find :test
            ("GOTO TEST", 0),  # Case insensitive
            ("goto :test", 0),  # With colon
            ("goto missing", 1),  # Missing label
            # Note: bare "goto" without target doesn't match the regex pattern
        ]

        for command, expected_issues in test_cases:
            issues = _check_syntax_errors(command, 2, labels)
            goto_issues = [i for i in issues if i.rule.code == "E002"]
            assert len(goto_issues) == expected_issues, f"Failed for: {command}"

    def test_warning_issue_edge_cases(self) -> None:
        """Test warning level edge cases."""
        set_vars = {"DEFINED_VAR", "PATH", "TEMP"}

        # Test unquoted variables in different contexts
        # W005 now only checks IF string comparisons, not echo or set
        test_cases = [
            ("if %UNDEFINED_VAR%==value echo test", True),  # Should trigger W005
            ("echo %PATH%", False),  # Should NOT trigger W005 (echo is safe)
            ("set NEWVAR=%PATH%", False),  # Should NOT trigger W005 (set is safe)
            (
                'if "%UNDEFINED_VAR%"=="value" echo test',
                False,
            ),  # Quoted, should not trigger
        ]

        for command, should_trigger in test_cases:
            issues = _check_warning_issues(command, 1, set_vars, False)
            w005_issues = [i for i in issues if i.rule.code == "W005"]
            if should_trigger:
                assert len(w005_issues) >= 1, f"Should trigger W005 for: {command}"
            else:
                assert len(w005_issues) == 0, f"Should NOT trigger W005 for: {command}"

    def test_security_issue_comprehensive(self) -> None:
        """Test comprehensive security issue detection."""
        test_cases = [
            # Command injection patterns
            ("set /p CMD=Enter command: && %CMD%", "SEC001"),
            ("set /p INPUT=Enter: && echo %INPUT%", "SEC001"),
            # Unsafe SET commands
            ("set VAR=value with spaces", "SEC002"),
            ("set PATH=%PATH%;C:\\new", "SEC002"),
            # Registry operations
            ("reg delete HKLM\\Software\\Test /f", "SEC004"),
            (
                "regedit /s dangerous.reg",
                None,
            ),  # May or may not trigger depending on pattern
            # Privilege checks
            ("net user admin password /add", "SEC005"),
            ("sc create TestService binpath=test.exe", "SEC005"),
        ]

        for command, expected_rule in test_cases:
            issues = _check_security_issues(command, 1)
            if expected_rule:
                matching_issues = [i for i in issues if i.rule.code == expected_rule]
                assert (
                    len(matching_issues) >= 1
                ), f"Should trigger {expected_rule} for: {command}"

    def test_unicode_and_special_characters(self) -> None:
        """Test handling of Unicode and special characters."""
        test_cases = [
            "echo café",  # Unicode characters
            "echo naïve",  # Unicode with diacritics
            "echo 测试",  # Chinese characters
            "echo 🚀",  # Emoji
            'echo "quotes with spaces"',  # Quotes
            "echo 'single quotes'",  # Single quotes
            "REM Comment with émojis 💻",  # Comment with Unicode
        ]

        set_vars: set[str] = set()
        for command in test_cases:
            # Should handle Unicode gracefully
            issues = _check_warning_issues(command, 1, set_vars, False)
            # Should detect non-ASCII characters
            non_ascii_issues = [i for i in issues if i.rule.code == "W012"]
            if not all(ord(c) < 128 for c in command):
                assert (
                    len(non_ascii_issues) >= 1
                ), f"Should detect non-ASCII in: {command}"


class TestMainFunctionEdgeCases:
    """Test main function edge cases and error paths."""

    def test_main_with_invalid_file_extension(self) -> None:
        """Test main function with invalid file extensions."""
        # Create a test file with wrong extension
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as temp_file:
            temp_file.write("@ECHO OFF\necho test")
            temp_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter.py", temp_path]):
                with pytest.raises(SystemExit) as exit_info:
                    main()
                assert exit_info.value.code == 1
        finally:
            os.unlink(temp_path)

    def test_main_with_encoding_warnings(self) -> None:
        """Test main function with encoding warnings."""
        # Create a file that will trigger encoding warnings
        content = "@ECHO OFF\necho test\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="latin1"
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            with patch("sys.argv", ["blinter.py", temp_path]):
                with patch("sys.exit"):
                    with warnings.catch_warnings(record=True):
                        warnings.simplefilter("always")
                        main()
                        # May or may not have warnings depending on encoding detection
        finally:
            os.unlink(temp_path)

    def test_path_validation_comprehensive(self) -> None:
        """Test comprehensive path validation."""
        labels: dict[str, int] = {}

        # Test various invalid path patterns
        # Note: * and ? are valid wildcards in Windows batch files, so they're not flagged
        invalid_paths = [
            'copy "file<name.txt", dest',  # < character
            'copy "file>name.txt", dest',  # > character
            'copy "file|name.txt", dest',  # | character
            "copy 'path<with>invalid', dest",  # Single quotes
        ]

        for command in invalid_paths:
            issues = _check_syntax_errors(command, 1, labels)
            path_issues = [i for i in issues if i.rule.code == "E005"]
            assert len(path_issues) >= 1, f"Should detect invalid path in: {command}"

        # Test that wildcards are NOT flagged (they're valid in Windows batch files)
        valid_wildcard_paths = [
            'copy "file*name.txt", dest',  # * wildcard (valid)
            'copy "file?name.txt", dest',  # ? wildcard (valid)
            'copy "*.txt", dest',  # Common wildcard pattern
        ]

        for command in valid_wildcard_paths:
            issues = _check_syntax_errors(command, 1, labels)
            path_issues = [i for i in issues if i.rule.code == "E005"]
            assert len(path_issues) == 0, f"Should NOT flag wildcards in: {command}"


class TestPerformanceAndScalability:
    """Test performance and scalability aspects."""

    def test_large_number_of_labels(self) -> None:
        """Test handling a large number of labels."""
        lines = ["@ECHO OFF"]
        # Create many labels
        for i in range(100):
            lines.append(f":label{i}")
            lines.append(f"echo Processing {i}")
        lines.append("EXIT /B 0")

        # Should handle many labels efficiently
        issues = lint_batch_file_from_lines(lines)
        assert isinstance(issues, list)

    def test_large_number_of_variables(self) -> None:
        """Test handling a large number of variables."""
        lines = ["@ECHO OFF"]
        # Create many variables
        for i in range(100):
            lines.append(f'set "VAR{i}=value{i}"')
        lines.append("EXIT /B 0")

        # Should handle many variables efficiently
        issues = lint_batch_file_from_lines(lines)
        assert isinstance(issues, list)


def lint_batch_file_from_lines(lines: list[str]) -> List[LintIssue]:
    """Helper function to lint batch file from list of lines."""
    content = "\n".join(lines)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".bat", delete=False
    ) as temp_file:
        temp_file.write(content)
        temp_path = temp_file.name

    try:
        return lint_batch_file(temp_path)
    finally:
        os.unlink(temp_path)


class TestAdditionalErrorHandling:
    """Additional error handling tests for comprehensive scenarios."""

    def test_file_encoding_error_scenarios(self) -> None:
        """Test file encoding error scenarios."""
        # Create a file with problematic encoding
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            # Write some bytes that might cause encoding issues
            temp_file.write(b"@echo off\r\n")
            temp_file.write(b"echo \xff\xfe test\r\n")  # Invalid UTF-8 sequence
            temp_file_path = temp_file.name

        try:
            lines, encoding = read_file_with_encoding(temp_file_path)
            assert isinstance(lines, list)
            assert isinstance(encoding, str)
            assert len(lines) >= 1
        finally:
            os.unlink(temp_file_path)

    def test_line_1111_encoding_fallback(self) -> None:
        """Test encoding fallback for files with invalid UTF-8 byte sequences."""
        # Create a file that might trigger specific encoding detection failure
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            # Write content with problematic byte sequences
            temp_file.write(b"@echo off\r\n")
            temp_file.write(b"\x80\x81 Invalid UTF-8\r\n")
            temp_file_path = temp_file.name

        try:
            lines, encoding_used = read_file_with_encoding(temp_file_path)
            assert isinstance(lines, list)
            assert isinstance(encoding_used, str)
            assert len(lines) >= 2
        finally:
            os.unlink(temp_file_path)

    def test_encoding_specific_scenarios(self) -> None:
        """Test encoding scenarios for edge cases and error paths."""

        # Test file with BOM
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            # Write UTF-8 BOM + content
            temp_file.write(b"\xef\xbb\xbf@echo off\r\necho UTF-8 BOM test\r\n")
            temp_file_path = temp_file.name

        try:
            lines, encoding_used = read_file_with_encoding(temp_file_path)
            assert isinstance(lines, list)
            assert isinstance(encoding_used, str)
        finally:
            os.unlink(temp_file_path)

        # Test file with mixed encodings (problematic scenario)
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(b"@echo off\r\n")
            temp_file.write("echo Niño".encode("latin1"))  # Latin1 encoding
            temp_file.write(b"\r\n")
            temp_file_path = temp_file.name

        try:
            lines, encoding_used = read_file_with_encoding(temp_file_path)
            assert isinstance(lines, list)
            assert isinstance(encoding_used, str)
            assert any("Niño" in line or "Ni" in line for line in lines)
        finally:
            os.unlink(temp_file_path)

    def test_is_path_under_root_returns_false_when_symlink_resolve_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Symlink resolution errors fail closed to outside root."""

        root = Path("C:/scan_root")
        candidate = Path("C:/scan_root/link.bat")

        def _raise_oserror(_self: Path) -> Path:
            raise OSError("simulated resolve failure")

        monkeypatch.setattr(Path, "is_symlink", lambda _self: True)
        monkeypatch.setattr(
            Path, "readlink", lambda _self: Path("C:/outside/target.bat")
        )
        monkeypatch.setattr(Path, "resolve", _raise_oserror)

        assert is_path_under_root(candidate, root) is False

    def test_is_path_under_root_returns_false_when_candidate_resolve_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Path resolution failures fail closed to outside root."""
        root = tmp_path / "scan"
        root.mkdir()
        candidate = root / "script.bat"
        candidate.write_text("@ECHO OFF\n", encoding="utf-8")

        def _raise_oserror(_self: Path) -> Path:
            raise OSError("simulated resolve failure")

        monkeypatch.setattr(Path, "is_symlink", lambda _self: False)
        monkeypatch.setattr(Path, "resolve", _raise_oserror)

        assert is_path_under_root(candidate, root) is False

    def test_edge_case_functions_behavior(self) -> None:
        """Test various edge case functions for proper behavior."""
        # Test file finding with edge cases
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test find_batch_files with file that exists but isn't a batch file
            txt_file = os.path.join(temp_dir, "test.txt")
            with open(txt_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("not a batch file")

            try:
                files = find_batch_files(txt_file, recursive=False)
                assert len(files) == 0  # Should not include non-batch files
            except ValueError:
                # Expected - non-batch files should raise ValueError
                pass

    def test_specific_encoding_detection_scenario(self) -> None:
        """Test specific encoding detection scenario for edge cases."""
        # This targets a specific scenario in _detect_line_endings
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bat", delete=False
        ) as temp_file:
            # Create content that might trigger specific encoding paths
            temp_file.write(b"@echo off\r\n")
            temp_file.write(b"echo test\n")  # Mixed line endings
            temp_file.write(b"echo final\r")  # Just CR
            temp_file_path = temp_file.name

        try:
            ending_type, has_mixed, _, _, _ = _detect_line_endings(temp_file_path)
            assert ending_type in ["CRLF", "LF", "CR", "MIXED", "mixed"]
            assert isinstance(has_mixed, bool)
        finally:
            os.unlink(temp_file_path)

    def test_error_handling_edge_cases(self) -> None:
        """Test specific error handling edge cases and branches."""

        # Test content that might trigger different rule branches
        test_contents = [
            # Test for specific rule conditions that might be missed
            '@echo off\npowershell -Command "Get-Process"',
            "@echo off\nnet user test password /add",
            "@echo off\nreg add HKLM\\Software\\Test /v TestValue /d TestData",
            "@echo off\necho %USERPROFILE%\\..\\sensitive_file.txt",
        ]

        for content in test_contents:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".bat", delete=False, encoding="utf-8"
            ) as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name

            try:
                issues = lint_batch_file(temp_file_path)
                # Ensure we get some kind of result
                assert isinstance(issues, list)
            finally:
                os.unlink(temp_file_path)


class TestDiscoverySandbox:  # pylint: disable=too-few-public-methods
    """Test directory discovery containment."""

    def test_find_batch_files_filters_outside_root(self, tmp_path: Path) -> None:
        """Files outside the discovery root are excluded."""
        scan_dir = tmp_path / "project"
        scan_dir.mkdir()

        inside_file = scan_dir / "inside.bat"
        inside_file.write_text("@echo off\n", encoding="utf-8")

        outside_file = tmp_path / "outside.bat"
        outside_file.write_text("@echo off\n", encoding="utf-8")

        inside_results = find_batch_files(inside_file, root=scan_dir.resolve())
        assert inside_results == [inside_file]

        outside_results = find_batch_files(outside_file, root=scan_dir.resolve())
        assert outside_results == []

    def test_lint_batch_file_rejects_non_batch_extension(self, tmp_path: Path) -> None:
        """lint_batch_file rejects files that are not .bat or .cmd."""
        text_file = tmp_path / "script.txt"
        text_file.write_text("@echo off\n", encoding="utf-8")
        with pytest.raises(ValueError, match="not a batch file"):
            lint_batch_file(str(text_file))

    def test_is_path_under_root_rejects_relative_symlink_outside_root(
        self, tmp_path: Path
    ) -> None:
        """Relative symlink targets resolving outside scan_root are rejected."""
        scan_root = tmp_path / "project"
        outside_dir = tmp_path / "outside"
        scan_root.mkdir()
        outside_dir.mkdir()

        outside_file = outside_dir / "secret.bat"
        outside_file.write_text("@echo off\n", encoding="utf-8")

        escape_link = scan_root / "escape.bat"
        try:
            os.symlink("../../outside/secret.bat", escape_link)
        except OSError:
            pytest.skip("symlink creation not supported on this platform")

        assert is_path_under_root(escape_link, scan_root) is False

    def test_find_batch_files_raises_when_scan_limit_exceeded(
        self, tmp_path: Path
    ) -> None:
        """Directory scans above max_scan_files raise ValueError."""
        scan_dir = tmp_path / "many"
        scan_dir.mkdir()
        for index in range(3):
            (scan_dir / f"script{index}.bat").write_text(
                "@echo off\n", encoding="utf-8"
            )

        with pytest.raises(ValueError, match="exceeding the limit"):
            find_batch_files(scan_dir, max_scan_files=2)
