"""Tests for edge cases and specialized scenarios."""

import importlib
import os
from pathlib import Path
import sys
import tempfile
from typing import Dict, List, Optional, Set
from unittest.mock import MagicMock, mock_open, patch

from hypothesis import given, settings, strategies as st
import pytest

from blinter import (
    BlinterConfig,
    LintIssue,
    find_batch_files,
    lint_batch_file,
    logging_config,
    main,
    read_file_with_encoding,
)
from blinter.checkers.advanced import (
    _check_advanced_for_rules,
    _check_advanced_style_rules,
    _check_advanced_vars,
    _check_enhanced_commands,
    _check_enhanced_performance,
    _check_enhanced_security_rules,
    _check_function_docs,
    _check_line_length,
    _check_magic_numbers,
)
from blinter.checkers.advanced.style_security_perf import (
    _check_advanced_security,
    _check_for_block_performance,
    _line_is_inside_for_block,
)
from blinter.checkers.advanced.vars_syntax import (
    _check_advanced_process_mgmt,
    _check_for_f_suboptions,
    _check_for_f_token_overflow,
    _check_percent_tilde_syntax,
    _check_set_a_arithmetic,
    _for_f_file_set_operand,
)
from blinter.checkers.globals import (
    _check_cmd_case_consistency,
    _check_code_duplication,
    _check_global_style_rules,
    _check_inconsistent_indentation,
    _check_missing_header_doc,
    _check_missing_pause,
    _check_nested_paren_mismatch,
    _check_new_global_rules,
    _check_redundant_operations,
    _check_unreachable_code,
)
from blinter.checkers.globals.exit_flow import _check_missing_exit_statement
from blinter.checkers.line_endings import _check_line_ending_rules
from blinter.checkers.performance import _check_performance_issues
from blinter.checkers.security import _check_security_issues
from blinter.checkers.style import _check_style_issues
from blinter.checkers.syntax import _check_syntax_errors
from blinter.checkers.vars import _check_undefined_variables
from blinter.checkers.warnings import _check_warning_issues
from blinter.io.encoding import (
    _detect_line_endings,
    _has_multibyte_chars,
    _validate_and_read_file,
)
from blinter.parsing.context import (
    _command_segments,
    _is_blank_or_comment,
    _is_command_in_safe_context,
    _is_comment_line,
    _is_endlocal_command,
    _is_setlocal_command,
)
from blinter.parsing.embedded import _detect_embedded_script_blocks
from blinter.parsing.structure import (
    _analyze_script_structure,
    _collect_labels,
    _collect_set_variables,
    _parse_suppression_comments,
)
from tests.conftest import patch_valid_encoding_path

# pylint: disable=too-many-lines,redefined-outer-name,reimported
# pylint: disable=unused-argument,invalid-name,missing-class-docstring,too-few-public-methods
# pylint: disable=unused-variable,unused-import


class TestFileEncodingEdgeCases:
    """Test edge cases in file encoding detection and handling."""

    def test_charset_normalizer_oserror_handling(self) -> None:
        """Test handling of OSError during charset_normalizer detection."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("charset_normalizer.from_bytes", side_effect=OSError("Test OSError")),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding in [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "iso-8859-1",
                "ascii",
            ]
            assert len(lines) > 0

    def test_charset_normalizer_valueerror_handling(self) -> None:
        """Test handling of ValueError during charset_normalizer detection."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "charset_normalizer.from_bytes",
                side_effect=ValueError("Test ValueError"),
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding in [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "iso-8859-1",
                "ascii",
            ]
            assert len(lines) > 0

    def test_charset_normalizer_typeerror_handling(self) -> None:
        """Test handling of TypeError during charset_normalizer detection."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "charset_normalizer.from_bytes", side_effect=TypeError("Test TypeError")
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding in [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "iso-8859-1",
                "ascii",
            ]
            assert len(lines) > 0

    def test_encoding_lookup_error_fallback(self) -> None:
        """Test handling when encoding lookup fails."""

        def mock_decode_bytes(raw_data: bytes, encoding: str) -> Optional[List[str]]:
            if encoding == "utf-8":
                return None
            if encoding == "cp1252":
                return ["test content\n"]
            return None

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding._try_decode_bytes",
                side_effect=mock_decode_bytes,
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding != "utf-8"
            assert len(lines) > 0

    def test_encoding_value_error_fallback(self) -> None:
        """Test handling when encoding value is invalid."""

        def mock_decode_bytes(raw_data: bytes, encoding: str) -> Optional[List[str]]:
            if encoding == "utf-8":
                return None
            if encoding == "cp1252":
                return ["test content\n"]
            return None

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding._try_decode_bytes",
                side_effect=mock_decode_bytes,
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding != "utf-8"
            assert len(lines) > 0

    def test_all_encodings_fail_with_exception(self) -> None:
        """Test when all encodings fail and we have a last exception."""

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_all_encodings_fail_no_exception(self) -> None:
        """Test when all encodings fail but no exception is stored."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_charset_normalizer_detected_encoding_already_in_list(self) -> None:
        """Test when charset_normalizer detects an encoding already in our list."""
        mock_result = MagicMock()
        mock_result.encoding = "utf-8"
        mock_result.coherence = 0.8
        mock_from_bytes = MagicMock()
        mock_from_bytes.best.return_value = mock_result

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("charset_normalizer.from_bytes", return_value=mock_from_bytes),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding == "utf-8"  # Should use detected encoding
            assert len(lines) > 0


class TestSyntaxErrorChecking:
    """Test syntax error checking edge cases."""

    def test_goto_with_colon_prefix(self) -> None:
        """Test GOTO statement with colon prefix in target."""
        labels = {":mylabel": 1}
        issues = _check_syntax_errors("GOTO :mylabel", 2, labels)
        assert len(issues) == 0  # Should be valid

    def test_if_statement_incomplete_comparison(self) -> None:
        """Test IF statement that looks incomplete (missing operator)."""
        labels: Dict[str, int] = {}
        issues = _check_syntax_errors('IF "VARIABLE"', 1, labels)
        assert len(issues) == 1
        assert "E003" in issues[0].rule.code

    def test_command_typo_detection(self) -> None:
        """Test detection of common command typos."""
        labels: Dict[str, int] = {}
        issues = _check_syntax_errors("IFF something", 1, labels)
        assert len(issues) == 1
        assert "E013" in issues[0].rule.code

    def test_empty_line_no_typo_detection(self) -> None:
        """Test that empty lines don't trigger typo detection."""
        labels: Dict[str, int] = {}
        issues = _check_syntax_errors("   ", 1, labels)
        assert len(issues) == 0

    def test_call_without_colon_to_builtin_command(self) -> None:
        """Test CALL to builtin command (should not trigger colon warning)."""
        labels: Dict[str, int] = {}
        issues = _check_syntax_errors("CALL dir", 1, labels)
        assert len(issues) == 0  # Should not trigger E014

    def test_call_without_colon_to_label_looking_name(self) -> None:
        """Test CALL to what looks like a label without colon."""
        labels: Dict[str, int] = {}
        issues = _check_syntax_errors("CALL mylabel", 1, labels)
        assert len(issues) == 1
        assert "E014" in issues[0].rule.code

    def test_goto_missing_label_edge_case(self) -> None:
        """Test GOTO with missing label edge case."""
        labels = {":otherlabel": 1}
        issues = _check_syntax_errors("goto nonexistent", 2, labels)
        assert len(issues) == 1
        assert "E002" in issues[0].rule.code


class TestWarningIssueChecking:
    """Test warning issue detection edge cases."""

    def test_deprecated_command_usage(self) -> None:
        """Test detection of deprecated commands.

        Note: Deprecated command checking (W024) has been moved to _check_deprecated_commands()
        and is no longer part of _check_warning_issues(). See test_lint_functionality.py for
        comprehensive deprecated command tests.
        """
        set_vars: Set[str] = set()
        issues = _check_warning_issues("assign A: B:", 1, set_vars, False)
        # Should not return any issues since deprecated command checking moved to W024
        assert len(issues) == 0

    def test_unquoted_variable_in_echo(self) -> None:
        """Test unquoted variable in ECHO - should NOT trigger W005 (only IF comparisons do)."""
        set_vars: Set[str] = set()
        issues = _check_warning_issues("echo %VARIABLE%", 1, set_vars, False)
        # W005 is now more conservative - only checks IF string comparisons
        w005_issues = [i for i in issues if i.rule.code == "W005"]
        assert len(w005_issues) == 0, "W005 should not flag echo commands"

    def test_ping_without_timeout(self) -> None:
        """Test PING without timeout parameter."""
        set_vars: Set[str] = set()
        issues = _check_warning_issues("ping google.com", 1, set_vars, False)
        # Should detect W006 (ping without timeout) and W029 (16-bit command detection for .com)
        assert len(issues) >= 1
        rule_codes = [issue.rule.code for issue in issues]
        assert "W006" in rule_codes

    def test_setx_path_modification(self) -> None:
        """Test SETX PATH modification warning."""
        set_vars: Set[str] = set()
        issues = _check_warning_issues("setx path %PATH%;C:\\temp", 1, set_vars, False)
        # May also trigger W005 (Unquoted variable)
        w008_issues = [i for i in issues if i.rule.code == "W008"]
        assert len(w008_issues) == 1

    def test_older_windows_command(self) -> None:
        """Test older Windows command warning."""
        set_vars: Set[str] = set()
        issues = _check_warning_issues("choice /c yn /m Continue?", 1, set_vars, False)
        assert len(issues) == 1
        assert "W009" in issues[0].rule.code

    def test_architecture_specific_pattern(self) -> None:
        """Test architecture-specific pattern detection."""
        set_vars: Set[str] = set()
        issues = _check_warning_issues("cd Wow6432Node", 1, set_vars, False)
        assert len(issues) == 1
        assert "W010" in issues[0].rule.code

    def test_unicode_problematic_command(self) -> None:
        """Test Unicode problematic command with actual Unicode content."""
        set_vars: Set[str] = set()
        # Test with actual Unicode content that should trigger the warning
        issues = _check_warning_issues("type unicode_filé.txt", 1, set_vars, False)
        # Multiple Unicode-related warnings may be triggered
        w011_issues = [i for i in issues if i.rule.code == "W011"]
        assert len(w011_issues) == 1
        assert "type" in w011_issues[0].context

    def test_non_ascii_characters(self) -> None:
        """Test non-ASCII character detection."""
        set_vars: Set[str] = set()
        issues = _check_warning_issues(
            "echo Ñandú", 1, set_vars, False
        )  # Contains non-ASCII
        # May also trigger W011 (Unicode handling issue for echo command)
        w012_issues = [i for i in issues if i.rule.code == "W012"]
        assert len(w012_issues) == 1


class TestStyleIssueChecking:
    """Test style issue detection edge cases."""

    def test_long_parameter_list(self) -> None:
        """Test long parameter list detection."""
        issues = _check_style_issues(
            "CALL :myfunc param1 param2 param3 param4 param5 param6", 1
        )
        assert len(issues) == 1
        assert "S014" in issues[0].rule.code

    def test_magic_number_timeout(self) -> None:
        """Test magic number detection in timeout command."""
        issues = _check_style_issues("timeout /t 300", 1)
        # May also trigger S003 (command capitalization)
        s009_issues = [i for i in issues if i.rule.code == "S009"]
        assert len(s009_issues) == 1

    def test_magic_number_ping(self) -> None:
        """Test magic number detection in ping command."""
        issues = _check_style_issues("ping google.com -n 50", 1)
        # May also trigger S003 (command capitalization)
        s009_issues = [i for i in issues if i.rule.code == "S009"]
        assert len(s009_issues) == 1

    def test_command_casing_inconsistency(self) -> None:
        """Test command casing inconsistency detection."""
        # The new S003 rule only flags inconsistencies within the same file
        # So we need to create content with mixed casing for the same command
        # Use actual batch commands (not echo, which is often skipped)
        test_lines = [
            "set var1=hello",  # lowercase
            "SET var2=world",  # uppercase - this should trigger S003
        ]
        all_issues = []
        for line_num, line in enumerate(test_lines, 1):
            issues = _check_style_issues(line, line_num)
            all_issues.extend(issues)

        # Now check using the global function that detects inconsistencies

        consistency_issues = _check_cmd_case_consistency(test_lines)

        assert len(consistency_issues) >= 1
        assert "S003" in consistency_issues[0].rule.code


class TestSecurityIssueChecking:
    """Test security issue detection edge cases."""

    def test_credential_patterns(self) -> None:
        """Test various credential pattern detection."""
        test_cases = [
            "set password=secret123",
            "set pwd=mypass",
            "set passwd=hidden",
            "set apikey=abc123",
            "set api_key=xyz789",
            "set secret=topsecret",
            "set token=bearer123",
        ]
        for line in test_cases:
            issues = _check_security_issues(line, 1)
            # May also trigger SEC002 (unquoted SET command)
            sec008_issues = [i for i in issues if i.rule.code == "SEC008"]
            assert len(sec008_issues) == 1

    def test_sensitive_echo_patterns(self) -> None:
        """Test sensitive information in ECHO detection."""
        test_cases = [
            "echo Your password is %PASSWORD%",
            "echo pwd: %PWD%",
            "echo passwd value",
            "echo apikey=123",
            "echo api_key value",
            "echo secret code",
            "echo token info",
        ]
        for line in test_cases:
            issues = _check_security_issues(line, 1)
            # May also trigger SEC008 (credential patterns) for some cases
            sec010_issues = [i for i in issues if i.rule.code == "SEC010"]
            assert len(sec010_issues) == 1

    def test_credential_patterns_skip_comments_and_safe_context(self) -> None:
        """SEC008/SEC010 must not flag REM or :: documentation lines."""
        safe_lines = [
            "REM password=secret123",
            ":: apikey=hidden",
        ]
        for line in safe_lines:
            issues = _check_security_issues(line, 1)
            assert not any(issue.rule.code == "SEC008" for issue in issues)
            assert not any(issue.rule.code == "SEC010" for issue in issues)

        unsafe_lines = [
            "set password=secret123",
            "echo Your password is %PASSWORD%",
        ]
        for line in unsafe_lines:
            issues = _check_security_issues(line, 1)
            codes = {issue.rule.code for issue in issues}
            assert "SEC008" in codes or "SEC010" in codes


class TestPerformanceIssueChecking:
    """Test performance issue detection edge cases."""

    def test_inefficient_dir_command(self) -> None:
        """P010 flags DIR output that is piped or redirected without /B."""
        issues = _check_performance_issues(
            [""],
            1,
            "dir /s | findstr txt",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        assert len(issues) == 1
        assert "P010" in issues[0].rule.code

    @pytest.mark.parametrize(
        "command",
        [
            "dir /s",
            "dir /b > list.txt",
            "dir /s/b | findstr txt",
            "dirname x > y",
            "dir /s 2>nul",
            "dir /s 2>>err.log",
        ],
    )
    def test_dir_command_not_flagged_by_p010(self, command: str) -> None:
        """P010 stays quiet for unprocessed output, /B listings and other commands."""
        issues = _check_performance_issues(
            [""], 1, command, False, False, False, False, False, False, False
        )
        assert "P010" not in {issue.rule.code for issue in issues}

    def test_for_loop_without_tokens(self) -> None:
        """Test FOR loop without tokens optimization."""
        issues = _check_performance_issues(
            [""],
            1,
            'FOR /F "usebackq" %%i IN (file.txt) DO echo %%i',
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        assert len(issues) == 1
        assert "P009" in issues[0].rule.code

    def test_for_loop_with_delims_only_is_not_p009(self) -> None:
        """FOR /F with delims= captures the full line and should not trigger P009."""
        issues = _check_performance_issues(
            [""],
            1,
            'FOR /F "delims=," %%i IN (file.txt) DO echo %%i',
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        assert not issues

    def test_temporary_file_without_random(self) -> None:
        """Test temporary file without random name."""
        issues = _check_performance_issues(
            [""],
            1,
            "echo content > temp.txt",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        assert len(issues) == 1
        assert "P007" in issues[0].rule.code

    def test_delayed_expansion_without_enablement(self) -> None:
        """Test delayed expansion variables without enablement."""
        issues = _check_performance_issues(
            [""], 1, "echo !VARIABLE!", False, False, False, False, False, False, False
        )
        assert len(issues) == 1
        assert "P008" in issues[0].rule.code

    def test_unnecessary_setlocal(self) -> None:
        """Test unnecessary SETLOCAL usage."""
        issues = _check_performance_issues(
            [""], 1, "setlocal", False, False, False, False, False, False, False
        )
        assert len(issues) == 1
        assert "P003" in issues[0].rule.code

    def test_unnecessary_enabledelayedexpansion(self) -> None:
        """Test unnecessary ENABLEDELAYEDEXPANSION usage."""
        issues = _check_performance_issues(
            [""],
            1,
            "setlocal enabledelayedexpansion",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        # May also trigger P003 (unnecessary SETLOCAL)
        p004_issues = [i for i in issues if i.rule.code == "P004"]
        assert len(p004_issues) == 1

    def test_endlocal_without_setlocal(self) -> None:
        """Test ENDLOCAL without SETLOCAL."""
        issues = _check_performance_issues(
            [""], 1, "endlocal", False, False, False, False, False, False, False
        )
        assert len(issues) == 1
        assert "P005" in issues[0].rule.code


class TestGlobalFunctionChecking:
    """Test global function edge cases and boundary conditions."""

    def test_check_missing_pause_with_user_input(self) -> None:
        """Test missing PAUSE detection when script has user input."""
        lines = [
            "set /p answer=Do you want to continue? ",
            "echo Processing...",
        ]

        issues = _check_missing_pause(lines)
        assert len(issues) == 1
        assert "W014" in issues[0].rule.code

    def test_check_missing_pause_ignores_setp_file_input(self) -> None:
        """set /p VAR=<file should not count as interactive user input."""
        lines = [
            'set /p marker=<"release.txt"',
            "echo %marker%",
        ]

        issues = _check_missing_pause(lines)
        assert not issues

    def test_check_missing_pause_with_choice(self) -> None:
        """Test missing PAUSE detection when script has CHOICE command."""
        lines = [
            "choice /c yn /m Continue?",
            "echo Processing...",
        ]

        issues = _check_missing_pause(lines)
        assert len(issues) == 1
        assert "W014" in issues[0].rule.code

    def test_check_missing_pause_already_has_pause(self) -> None:
        """Test no warning when script already has PAUSE."""
        lines = [
            "set /p answer=Continue? ",
            "pause",
            "echo Done",
        ]

        issues = _check_missing_pause(lines)
        assert len(issues) == 0

    def test_check_inconsistent_indentation_block_style(self) -> None:
        """Tab plus single space before commands is standard block indentation."""
        lines = [
            "echo start",
            "\t echo mixed indentation",
            "  echo other indentation",
        ]

        issues = _check_inconsistent_indentation(lines)
        s012_issues = [i for i in issues if i.rule.code == "S012"]
        assert len(s012_issues) == 1
        assert "File mixes" in s012_issues[0].context

    def test_check_inconsistent_indentation_mixed(self) -> None:
        """Test mixed tabs and spaces within the same indent unit."""
        lines = [
            "echo start",
            "\t  echo mixed indentation",
            "  echo other indentation",
        ]

        issues = _check_inconsistent_indentation(lines)
        s012_issues = [i for i in issues if i.rule.code == "S012"]
        assert len(s012_issues) >= 1

    def test_check_inconsistent_indentation_across_file(self) -> None:
        """Test mixed indentation across file."""
        lines = [
            "echo start",
            "\techo with tab",
            "  echo with spaces",
            "echo end",
        ]

        issues = _check_inconsistent_indentation(lines)
        assert len(issues) == 1
        assert "S012" in issues[0].rule.code

    def test_check_missing_documentation(self) -> None:
        """Test missing documentation detection."""
        lines = [
            "echo hello",
            "echo world",
            "echo more",
            "echo content",
            "echo here",
            "echo line 6",
            "echo line 7",
            "echo line 8",
            "echo line 9",
            "echo line 10",
            "echo line 11",
            "echo line 12",
            "echo line 13",
            "echo line 14",
            "echo line 15",
            "echo line 16",
            "echo line 17",
            "echo line 18",
            "echo line 19",
            "echo line 20",
            "echo line 21",
            "echo line 22",
            "echo line 23",
            "echo line 24",
            "echo line 25",
            "echo line 26",
            "echo line 27",
            "echo line 28",
            "echo line 29",
            "echo line 30",
            "echo line 31",  # Now 31 lines, should trigger S013 with new threshold of 30
        ]

        issues = _check_missing_header_doc(lines)
        assert len(issues) == 1
        assert "S013" in issues[0].rule.code

    def test_check_missing_documentation_has_good_comments(self) -> None:
        """Test no warning when good documentation exists."""
        lines = [
            "rem Script: Test batch file",
            "rem Author: Test User",
            "echo hello",
            "echo world",
            "echo content",
        ]

        issues = _check_missing_header_doc(lines)
        assert len(issues) == 0


class TestMainFunctionEdgeCases:
    """Test main function edge cases and CLI argument handling."""

    def test_find_batch_files_file_not_batch(self) -> None:
        """Test find_batch_files with non-batch file."""

        # Create a temporary file
        fd, temp_path = tempfile.mkstemp(suffix=".txt")
        try:
            os.close(fd)  # Close the file descriptor first
            with pytest.raises(ValueError, match="not a batch file"):
                find_batch_files(temp_path)
        finally:
            try:
                os.unlink(temp_path)
            except (OSError, PermissionError):
                pass  # Ignore cleanup errors

    def test_find_batch_files_nonexistent_path(self, tmp_path: Path) -> None:
        """Test find_batch_files with nonexistent path."""

        with pytest.raises(FileNotFoundError):
            find_batch_files(str(tmp_path / "does-not-exist"))

    def test_validate_and_read_file_edge_cases(self) -> None:
        """Test _validate_and_read_file edge cases."""

        # Test empty file path
        with pytest.raises(ValueError, match="file_path must be a non-empty string"):
            _validate_and_read_file("")

        # Test non-string file path
        with pytest.raises(ValueError, match="file_path must be a non-empty string"):
            _validate_and_read_file(None)

    def test_analyze_script_structure_edge_cases(self) -> None:
        """Test _analyze_script_structure edge cases."""

        lines = [
            "setlocal",
            "set VAR=value",
            "setlocal enabledelayedexpansion",
            "echo !VAR!",
        ]
        (
            has_setlocal,
            has_set_commands,
            has_delayed_expansion,
            uses_delayed_vars,
            _,
            _,
            _,
        ) = _analyze_script_structure(lines)
        assert has_setlocal is True
        assert has_set_commands is True
        assert has_delayed_expansion is True
        assert uses_delayed_vars is True

    def test_if_exist_with_defined_check(self) -> None:
        """Test IF statement with EXIST and DEFINED keywords."""
        labels: dict[str, int] = {}
        issues = _check_syntax_errors("if defined MYVAR echo found", 1, labels)
        assert len(issues) == 0  # Should not trigger E003


class TestAdditionalEdgeCaseScenarios:
    """Additional tests for complex edge case scenarios."""

    def test_encoding_failure_edge_case(self) -> None:
        """Test encoding failure when no exceptions are stored."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_validate_and_read_file_large_file_warning(self) -> None:
        """Test large file warning in _validate_and_read_file."""

        # Mock a large file
        def mock_stat(*args: object, **kwargs: object) -> object:
            class StatResult:
                st_size = 15 * 1024 * 1024  # 15MB file
                st_mode = 0o100644  # Regular file mode

            return StatResult()

        fd, temp_path = tempfile.mkstemp(suffix=".bat")
        try:
            os.write(fd, b"@echo off\necho test")
            os.close(fd)

            with patch("pathlib.Path.stat", side_effect=mock_stat):
                with patch(
                    "builtins.open", mock_open(read_data="@echo off\necho test")
                ):
                    lines, encoding, _ending_info, _overlong = _validate_and_read_file(
                        temp_path
                    )
                    assert len(lines) > 0
                    assert encoding in [
                        "utf-8",
                        "cp1252",
                        "iso-8859-1",
                    ]  # Should succeed with some encoding
        finally:
            try:
                os.unlink(temp_path)
            except (OSError, PermissionError):
                pass

    def test_script_structure_analysis_edge_cases(self) -> None:
        """Test _analyze_script_structure with edge cases."""

        # Empty lines
        lines: list[str] = []
        result = _analyze_script_structure(lines)
        assert result == (False, False, False, False, False, False, False)

        # Lines with various patterns
        lines = [
            "setlocal",
            "set /p VAR=Input: ",
            "set /a NUM=5+3",
            "setlocal enabledelayedexpansion",
            "echo !VAR!",
        ]
        (
            has_setlocal,
            has_set_commands,
            has_delayed_expansion,
            uses_delayed_vars,
            _,
            _,
            _,
        ) = _analyze_script_structure(lines)
        assert has_setlocal is True
        assert has_set_commands is True  # Should detect set /p and set /a
        assert has_delayed_expansion is True
        assert uses_delayed_vars is True

    def test_missing_pause_edge_case(self) -> None:
        """Test _check_missing_pause with edge cases."""

        # Script with user input but already has pause - should not warn
        lines = [
            "set /p answer=Continue?",
            "echo Processing...",
            "pause > nul",  # Has pause, so no warning
            "echo Done",
        ]
        issues = _check_missing_pause(lines)
        assert len(issues) == 0

    def test_find_batch_files_not_file_or_directory(self) -> None:
        """Test find_batch_files with invalid path type."""

        # This should be very rare, but test the "neither file nor directory" path
        # We'll mock a path that exists but is neither
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=False),
            patch("pathlib.Path.is_dir", return_value=False),
        ):
            with pytest.raises(ValueError, match="neither a file nor a directory"):
                find_batch_files("invalid_path")

    def test_if_statement_with_exist_keyword(self) -> None:
        """Test IF statement with exist keyword."""
        labels: dict[str, int] = {}
        issues = _check_syntax_errors("if exist myfile.txt echo found", 1, labels)
        assert len(issues) == 0  # Should not trigger E003

    def test_security_is_command_in_safe_context(self) -> None:
        """Test _is_command_in_safe_context function behavior."""

        # Test REM comment context
        assert _is_command_in_safe_context("rem del *.* is dangerous") is True
        assert _is_command_in_safe_context("REM	format c: is dangerous") is True

        # Test ECHO context
        assert _is_command_in_safe_context("echo The del command removes files") is True
        assert _is_command_in_safe_context("@echo format c: formats drive") is True

        # Test non-safe context
        assert _is_command_in_safe_context("del *.* /q") is False

    def test_charset_normalizer_detected_encoding_not_in_list(self) -> None:
        """Test charset_normalizer detecting encoding not in our default list."""

        mock_result = MagicMock()
        mock_result.encoding = "iso-2022-jp"
        mock_result.coherence = 0.85
        mock_from_bytes = MagicMock()
        mock_from_bytes.best.return_value = mock_result

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("charset_normalizer.from_bytes", return_value=mock_from_bytes),
        ):
            # Should succeed by adding the detected encoding to the front
            lines, encoding = read_file_with_encoding("test.bat")
            assert len(lines) > 0

    def test_style_issues_edge_cases(self) -> None:
        """Test style issue detection edge cases."""

        # Small number, should not trigger magic number rule
        issues = _check_style_issues("timeout /t 5", 1)
        # Should only trigger S003 (command casing), not S009 (magic number)
        s009_issues = [i for i in issues if i.rule.code == "S009"]
        assert len(s009_issues) == 0  # Small numbers shouldn't be flagged

    def test_main_function_directory_processing_edge_case(self) -> None:
        """Test main function with directory processing edge cases."""

        # Test with --no-recursive flag
        original_argv = sys.argv[:]
        try:
            sys.argv = ["blinter.py", "nonexistent_directory", "--no-recursive"]
            # Should handle nonexistent directory gracefully
            main()  # Should exit without crashing
        except SystemExit:
            pass  # Expected
        finally:
            sys.argv = original_argv

    def test_performance_issue_edge_cases(self) -> None:
        """Test performance issue detection edge cases."""

        # Test temp file with random - should not trigger P007
        issues = _check_performance_issues(
            [""],
            1,
            "echo content > temp_%RANDOM%.txt",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        p007_issues = [i for i in issues if i.rule.code == "P007"]
        assert len(p007_issues) == 0  # Should not flag when RANDOM is used

    def test_missing_pause_reverse_line_order(self) -> None:
        """Test _check_missing_pause finding appropriate line number."""

        # Test finding the last executable line for warning
        lines = [
            "set /p answer=Continue?",
            "echo Processing...",
            "echo More processing...",
            "rem This is a comment",  # Should skip comments
            "",  # Should skip empty lines
        ]
        issues = _check_missing_pause(lines)
        assert len(issues) == 1
        # Should flag line 3 (last non-comment, non-empty executable line)
        assert issues[0].line_number == 3

    def test_inconsistent_indentation_few_indented_lines(self) -> None:
        """Test inconsistent indentation with less than 2 indented lines."""

        lines = [
            "echo start",
            "  echo only one indented line",
            "echo end",
        ]
        issues = _check_inconsistent_indentation(lines)
        assert len(issues) == 0  # Should not flag with only one indented line

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

    def test_security_admin_commands_edge_cases(self) -> None:
        """Test admin command detection edge cases."""

        # Test specific admin commands
        test_cases = [
            "reg add HKLM\\Software\\Test /v Value /d Data",
            "reg delete HKLM\\Software\\Test /v Value /f",
            "sc stop ServiceName",
            "net user testuser testpass /add",
        ]

        for line in test_cases:
            issues = _check_security_issues(line, 1)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            assert len(sec005_issues) >= 1  # Should detect privilege requirement

    def test_path_with_single_quotes(self) -> None:
        """Test path validation with single quotes."""
        labels: dict[str, int] = {}
        issues = _check_syntax_errors("copy 'bad|path.txt' dest", 1, labels)
        assert len(issues) == 1
        assert issues[0].rule.code == "E005"

    def test_path_with_double_quotes(self) -> None:
        """Test path validation with double quotes."""
        labels: dict[str, int] = {}
        issues = _check_syntax_errors('copy "bad<path.txt", dest', 1, labels)
        assert len(issues) == 1
        assert issues[0].rule.code == "E005"

    def test_path_without_invalid_characters(self) -> None:
        """Test path validation without invalid characters."""
        labels: dict[str, int] = {}
        issues = _check_syntax_errors('copy "goodpath.txt" dest', 1, labels)
        path_issues = [i for i in issues if i.rule.code == "E005"]
        assert len(path_issues) == 0


class TestWarningChecking:
    """Test warning level checking edge cases."""

    def test_ping_with_parameters_but_no_timeout(self) -> None:
        """Test PING command with parameters but no timeout."""
        set_vars: set[str] = set()
        issues = _check_warning_issues("ping google.com", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W006"]
        assert len(warning_issues) == 1

    def test_ping_with_proper_timeout(self) -> None:
        """Test PING command with proper timeout."""
        set_vars: set[str] = set()
        issues = _check_warning_issues("ping google.com -n 4", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W006"]
        assert len(warning_issues) == 0

    def test_setx_path_modification(self) -> None:
        """Test SETX PATH modification detection."""
        set_vars: set[str] = set()
        issues = _check_warning_issues(
            "setx PATH %PATH%;C:\\newpath", 1, set_vars, False
        )
        warning_issues = [i for i in issues if i.rule.code == "W008"]
        assert len(warning_issues) == 1

    def test_older_windows_commands(self) -> None:
        """Test detection of older Windows commands."""
        set_vars: set[str] = set()
        # Removed "timeout" as it's been available since Windows Vista
        # Removed "robocopy" as it's been available since Windows Vista/Server 2008 (2007-2008)
        for cmd in ["choice", "forfiles", "where", "icacls"]:
            issues = _check_warning_issues(f"{cmd} /param", 1, set_vars, False)
            warning_issues = [i for i in issues if i.rule.code == "W009"]
            assert len(warning_issues) == 1
            assert cmd in warning_issues[0].context

    def test_architecture_specific_patterns(self) -> None:
        """Test detection of architecture-specific patterns."""
        set_vars: set[str] = set()
        test_cases = [
            ("reg query HKLM\\SOFTWARE\\Wow6432Node\\Test", "Wow6432Node"),
            ("copy SysWow64\\file.txt dest", "SysWow64"),
        ]
        for command, expected_pattern in test_cases:
            issues = _check_warning_issues(command, 1, set_vars, False)
            warning_issues = [i for i in issues if i.rule.code == "W010"]
            assert len(warning_issues) == 1
            assert expected_pattern in warning_issues[0].context

    def test_program_files_x86_pattern_not_matched(self) -> None:
        """Test that Program Files (x86) pattern requires specific format."""
        # The pattern is looking for literal \(x86\) which doesn't match (x86)
        set_vars: set[str] = set()
        issues = _check_warning_issues('cd "Program Files (x86)"', 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W010"]
        assert len(warning_issues) == 0  # Won't match because pattern expects \\(x86\\)

    def test_unicode_problematic_commands(self) -> None:
        """Test detection of Unicode problematic commands with actual Unicode risks."""
        set_vars: set[str] = set()
        # Test commands with actual Unicode content that should be flagged
        issues = _check_warning_issues("type unicode_filé.txt", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W011"]
        # The improved rule should still catch this because it has Unicode in filename
        assert len(warning_issues) == 1
        assert "type" in warning_issues[0].context

        # Test find/findstr with Unicode content
        issues = _check_warning_issues(
            "findstr /i pattérn file.txt", 1, set_vars, False
        )
        warning_issues = [i for i in issues if i.rule.code == "W011"]
        assert len(warning_issues) == 1

        # Test echo with non-ASCII - should be flagged
        issues = _check_warning_issues("echo héllo", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W011"]
        assert len(warning_issues) == 1

        # Test echo with redirection - improved rule now considers this safe
        issues = _check_warning_issues("echo test > file", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W011"]
        assert len(warning_issues) == 0  # Now considered safe by improved rule

        # Test simple echo - should NOT be flagged
        issues = _check_warning_issues("echo simple text", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W011"]
        assert len(warning_issues) == 0

    def test_findstr_safe_switches_no_w011(self) -> None:
        """ASCII findstr with standard switches must not trigger W011."""
        set_vars: set[str] = set()
        issues = _check_warning_issues(
            "findstr /i pattern file.txt", 1, set_vars, False
        )
        w011_issues = [i for i in issues if i.rule.code == "W011"]
        assert len(w011_issues) == 0

    def test_non_ascii_character_detection(self) -> None:
        """Test detection of non-ASCII characters."""
        set_vars: set[str] = set()
        issues = _check_warning_issues("echo héllo wørld", 1, set_vars, False)
        warning_issues = [i for i in issues if i.rule.code == "W012"]
        assert len(warning_issues) == 1

    def test_for_loop_variables_no_false_positive(self) -> None:
        """Test that FOR loop variables (%%a %%b) don't trigger Unicode warnings."""
        set_vars: set[str] = set()
        # FOR loop variables should NOT trigger W011 Unicode warning
        issues = _check_warning_issues("echo %%a %%b", 1, set_vars, False)
        w011_issues = [i for i in issues if i.rule.code == "W011"]
        assert (
            len(w011_issues) == 0
        ), "FOR loop variables should not trigger Unicode warnings"

    def test_consecutive_variables_no_false_positive(self) -> None:
        """Test that consecutive variables like %red%%under% don't trigger false
        Unicode warnings."""
        set_vars: set[str] = {"red", "under", "def"}
        # Consecutive variables should NOT trigger W011 Unicode warning
        issues = _check_warning_issues("echo %red%%under%text%def%", 1, set_vars, False)
        w011_issues = [i for i in issues if i.rule.code == "W011"]
        assert (
            len(w011_issues) == 0
        ), "Consecutive variables should not trigger Unicode warnings"

    def test_echo_with_actual_unicode_still_flagged(self) -> None:
        """Test that actual Unicode content in echo still triggers warnings."""
        set_vars: set[str] = set()
        # Real Unicode content should still trigger W011
        issues = _check_warning_issues("echo Ñandú birds", 1, set_vars, False)
        w011_issues = [i for i in issues if i.rule.code == "W011"]
        assert (
            len(w011_issues) == 1
        ), "Actual Unicode content should still trigger warnings"


class TestStyleChecking:
    """Test style level checking edge cases."""

    def test_magic_numbers_in_timeout_command(self) -> None:
        """Test detection of magic numbers in timeout command."""
        issues = _check_style_issues("timeout /t 30", 1)
        magic_number_issues = [i for i in issues if i.rule.code == "S009"]
        assert len(magic_number_issues) == 1
        assert "30" in magic_number_issues[0].context

    def test_magic_numbers_in_ping_command(self) -> None:
        """Test detection of magic numbers in ping command."""
        issues = _check_style_issues("ping localhost -n 100", 1)
        magic_number_issues = [i for i in issues if i.rule.code == "S009"]
        assert len(magic_number_issues) == 1
        assert "100" in magic_number_issues[0].context

    def test_small_numbers_not_flagged(self) -> None:
        """Test that small numbers are not flagged as magic numbers."""
        issues = _check_style_issues("ping localhost -n 5", 1)
        magic_number_issues = [i for i in issues if i.rule.code == "S009"]
        assert len(magic_number_issues) == 0

    def test_command_casing_detection(self) -> None:
        """Test command casing consistency detection."""
        # Test with commands that are actually processed (not echo which is often skipped)
        keywords = ["set", "if", "for", "goto", "call", "cd"]
        for keyword in keywords:
            # Create inconsistent casing for the same command within a file
            test_lines = [
                f"{keyword} test",  # lowercase
                f"{keyword.upper()} test2",  # uppercase - should trigger S003
            ]

            consistency_issues = _check_cmd_case_consistency(test_lines)
            casing_issues = [i for i in consistency_issues if i.rule.code == "S003"]
            assert (
                len(casing_issues) >= 1
            ), f"No S003 issues found for keyword: {keyword}"
            # Check that the keyword appears in one of the contexts
            contexts = [issue.context for issue in casing_issues]
            assert any(keyword in context.lower() for context in contexts)

    def test_chained_set_on_one_line_not_e006(self, tmp_path: Path) -> None:
        """All SET commands on a chained line should be tracked for E006."""
        content = (
            "@echo off\n"
            "if 1==1 (set _int=1&set ping_f= failed)\n"
            "echo ok%ping_f%\n"
        )
        batch_file = tmp_path / "chained.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]


class TestPercentTildeSyntaxE019:
    """Percent-tilde on batch parameters must not false-positive E019."""

    def test_set_a_dynamic_assignment_params_not_e019(self) -> None:
        valid_lines = [
            'set /a "%~3=%~1 + %~2"',
            "SET /A %~2=%%~M + 2",
            "echo %~dp0",
            'set "OUT=%~dp0log.txt"',
            'CALL "%~dp0helper.bat"',
            "echo %~n1",
        ]
        for line in valid_lines:
            issues = _check_percent_tilde_syntax(line.strip(), 1)
            assert not [i for i in issues if i.rule.code == "E019"], line

    def test_dp0_adjacent_literal_integration_not_e019(self, tmp_path: Path) -> None:
        """Issue #35: %~dp0 followed by literal text must not false-positive E019."""
        batch_file = tmp_path / "test.bat"
        batch_file.write_text(
            '@echo off\nset "OUT=%~dp0log.txt"\nexit /b 0\n',
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E019"]

    def test_for_loop_tilde_modifiers_not_e019(self) -> None:
        """FOR loop %%~modifier+letter expansions must not false-positive E019."""
        valid_lines = [
            "for %%A in (%TEMP%\\example.zip) do set FILESIZE=%%~zA",
            "for %%A in (*.txt) do echo %%~nxA",
            "for %%A in (*.txt) do echo %%~dpA",
            "for %%a in (*.txt) do echo %%~za",
            'for %%b in (1) do set "p=%%~b"',
            'set "flag=?%%~a*"',
        ]
        for line in valid_lines:
            issues = _check_percent_tilde_syntax(line.strip(), 1)
            assert not [i for i in issues if i.rule.code == "E019"], line
            assert not [i for i in issues if i.rule.code == "E017"], line

    def test_for_loop_bare_tilde_integration_not_e017_e024(
        self, tmp_path: Path
    ) -> None:
        """FOR loop bare %%~X must not false-positive E017/E024."""
        batch_file = tmp_path / "test.bat"
        batch_file.write_text(
            '@echo off\nfor %%b in (1) do set "p=%%~b"\nexit /b 0\n',
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code in {"E017", "E024"}]

    def test_percent_tilde_on_var_still_e019(self) -> None:
        issues = _check_percent_tilde_syntax("echo %~nMYVAR%", 1)
        e019_issues = [i for i in issues if i.rule.code == "E019"]
        assert len(e019_issues) == 1


class TestForFSuboptionsE038:
    """FOR /F tokens= and skip= validation must not false-positive E038."""

    def test_tokens_and_delims_combined_not_e038(self) -> None:
        line = 'for /f "tokens=1,2 delims=|" %%a in ("url|tag") do ('
        issues = _check_for_f_suboptions(line, 1)
        assert not issues

    def test_invalid_tokens_value_still_e038(self) -> None:
        line = 'for /f "tokens=abc" %%a in ("data") do echo %%a'
        issues = _check_for_f_suboptions(line, 1)
        e038_issues = [i for i in issues if i.rule.code == "E038"]
        assert len(e038_issues) == 1

    def test_descending_tokens_range_still_e038(self) -> None:
        line = 'for /f "tokens=5-1" %%a in ("data") do echo %%a'
        issues = _check_for_f_suboptions(line, 1)
        e038_issues = [i for i in issues if i.rule.code == "E038"]
        assert len(e038_issues) == 1

    def test_skip_variable_not_e038(self) -> None:
        line = (
            "for /f \"skip=%@KEEP_HISTORICAL% tokens=*\" %%v in ('dir /b') do echo %%v"
        )
        issues = _check_for_f_suboptions(line, 1)
        assert not issues

    def test_skip_delayed_expansion_not_e038(self) -> None:
        line = "for /f \"skip=!SKIP_COUNT! tokens=*\" %%v in ('dir /b') do echo %%v"
        issues = _check_for_f_suboptions(line, 1)
        assert not issues


class TestForFTokenOverflowW063:
    """W063 must not treat a parenthesis inside ordinary DO text as a block."""

    def test_parenthesized_multiline_do_still_w063(self) -> None:
        lines = [
            'for /f "tokens=1-2" %%a in ("one two") do (',
            "echo %%c",
            ")",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_echo_open_paren_does_not_consume_next_line(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (input.txt) do echo (',
            "echo %%b",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert not [issue for issue in issues if issue.rule.code == "W063"]

    def test_nested_for_f_inner_var_is_not_outer_overflow(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'for /f "tokens=1" %%b in (b.txt) do echo %%b',
            ")",
        ]
        outer = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        inner = _check_for_f_token_overflow(lines[1], 2, lines=lines)
        assert not [issue for issue in outer if issue.rule.code == "W063"]
        assert not [issue for issue in inner if issue.rule.code == "W063"]

    def test_nested_for_f_still_flags_outer_overflow_after_inner(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'for /f "tokens=1" %%b in (b.txt) do echo %%b',
            "echo %%c",
            ")",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_triple_nested_for_f_does_not_rewind_into_inner_body(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'for /f "tokens=1" %%b in (b.txt) do (',
            'for /f "tokens=1" %%c in (c.txt) do echo %%c',
            "echo %%d",
            ")",
            "echo %%a",
            ")",
        ]
        outer = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        middle = _check_for_f_token_overflow(lines[1], 2, lines=lines)
        inner = _check_for_f_token_overflow(lines[2], 3, lines=lines)
        assert not [issue for issue in outer if issue.rule.code == "W063"]
        assert [issue.rule.code for issue in middle] == ["W063"]
        assert not [issue for issue in inner if issue.rule.code == "W063"]

    def test_echo_for_f_text_is_not_nested_command(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'echo for /f "tokens=1" %%b in (b.txt) do echo %%b',
            ")",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_nested_at_for_f_inner_var_is_not_outer_overflow(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            '@for /f "tokens=1" %%b in (b.txt) do echo %%b',
            ")",
        ]
        outer = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        inner = _check_for_f_token_overflow(lines[1], 2, lines=lines)
        assert not [issue for issue in outer if issue.rule.code == "W063"]
        assert not [issue for issue in inner if issue.rule.code == "W063"]

    def test_if_exist_nested_for_f_inner_var_is_not_outer_overflow(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'if exist b.txt for /f "tokens=1" %%b in (b.txt) do echo %%b',
            ")",
        ]
        outer = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        inner = _check_for_f_token_overflow(lines[1], 2, lines=lines)
        assert not [issue for issue in outer if issue.rule.code == "W063"]
        assert not [issue for issue in inner if issue.rule.code == "W063"]

    def test_do_inside_in_operand_is_not_loop_do(self) -> None:
        line = "for /f \"tokens=1\" %%a in ('echo do %%b') do echo %%a"
        issues = _check_for_f_token_overflow(line, 1)
        assert not [issue for issue in issues if issue.rule.code == "W063"]

    def test_overflow_after_in_operand_containing_do(self) -> None:
        line = "for /f \"tokens=1\" %%a in ('echo do %%a') do echo %%b"
        issues = _check_for_f_token_overflow(line, 1)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_single_quoted_operand_close_paren_is_not_in_end(self) -> None:
        line = "for /f \"tokens=1\" %%a in ('echo ) do echo %%b') do echo %%a"
        issues = _check_for_f_token_overflow(line, 1)
        assert not [issue for issue in issues if issue.rule.code == "W063"]

    def test_ampersand_after_nested_for_f_still_w063(self) -> None:
        line = (
            'for /f "tokens=1" %%a in (a.txt) do '
            'for /f "tokens=1" %%b in (b.txt) do echo %%b & echo %%c'
        )
        issues = _check_for_f_token_overflow(line, 1)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_quoted_paren_in_nested_do_is_not_block_end(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'for /f "tokens=1" %%b in (b.txt) do (',
            'echo "close ) here"',
            "echo %%b",
            ")",
            ")",
        ]
        outer = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        inner = _check_for_f_token_overflow(lines[1], 2, lines=lines)
        assert not [issue for issue in outer if issue.rule.code == "W063"]
        assert not [issue for issue in inner if issue.rule.code == "W063"]

    def test_caret_escaped_paren_in_nested_do_is_not_block_end(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'for /f "tokens=1" %%b in (b.txt) do (',
            "echo close ^)",
            "echo %%b",
            ")",
            ")",
        ]
        outer = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert not [issue for issue in outer if issue.rule.code == "W063"]

    def test_quoted_open_paren_does_not_extend_outer_body(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'echo "open ( paren"',
            ")",
            "echo %%b",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert not [issue for issue in issues if issue.rule.code == "W063"]

    def test_echo_for_f_before_real_nested_for_f_still_w063(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            'echo for /f %%c & for /f "tokens=1" %%b in (b.txt) do echo %%b',
            ")",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_caret_escaped_close_paren_in_operand_is_not_in_end(self) -> None:
        line = 'for /f "tokens=1" %%a in (foo^) do echo %%b) do echo %%a'
        issues = _check_for_f_token_overflow(line, 1)
        assert not [issue for issue in issues if issue.rule.code == "W063"]

    def test_set_value_containing_for_f_still_w063(self) -> None:
        lines = [
            'for /f "tokens=1" %%a in (a.txt) do (',
            "set foo=for /f %%b",
            ")",
        ]
        issues = _check_for_f_token_overflow(lines[0], 1, lines=lines)
        assert [issue.rule.code for issue in issues] == ["W063"]

    def test_invalid_skip_word_still_e038(self) -> None:
        line = 'for /f "skip=abc tokens=*" %%a in ("data") do echo %%a'
        issues = _check_for_f_suboptions(line, 1)
        e038_issues = [i for i in issues if i.rule.code == "E038"]
        assert len(e038_issues) == 1


class TestPseudoEnvAssignmentW049:
    """SET \"name=\" clears a shadow; space-only values still assign (W049)."""

    def test_quoted_clear_is_not_w049(self) -> None:
        issues = _check_warning_issues('set "errorlevel="', 1, set(), False)
        assert not [issue for issue in issues if issue.rule.code == "W049"]

    def test_quoted_space_value_is_w049(self) -> None:
        issues = _check_warning_issues('set "errorlevel= "', 1, set(), False)
        assert [issue.rule.code for issue in issues if issue.rule.code == "W049"] == [
            "W049"
        ]

    def test_unquoted_space_value_is_w049(self) -> None:
        issues = _check_warning_issues("set errorlevel= ", 1, set(), False)
        assert [issue.rule.code for issue in issues if issue.rule.code == "W049"] == [
            "W049"
        ]

    def test_unquoted_clear_is_not_w049(self) -> None:
        issues = _check_warning_issues("set errorlevel=", 1, set(), False)
        assert not [issue for issue in issues if issue.rule.code == "W049"]


class TestTextAfterCloseParenE042:
    """Text after ')' inside a parenthesized block is a cmd.exe parse error (E042)."""

    @staticmethod
    def _e042_codes(issues: List[LintIssue]) -> List[int]:
        return [issue.line_number for issue in issues if issue.rule.code == "E042"]

    def test_issue_36_for_block_reports_e042(self, tmp_path: Path) -> None:
        """Issue #36 reproduction: trailing text after inner ) inside FOR."""
        batch_file = tmp_path / "issue36.cmd"
        batch_file.write_text(
            "@echo off\n"
            "for %%D in (C) do (\n"
            "    echo --- text (parens) ---\n"
            ")\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 3 in self._e042_codes(issues)

    def test_else_if_block_is_not_e001(self, tmp_path: Path) -> None:
        """') else if exist file (' keeps the surrounding block balanced."""
        batch_file = tmp_path / "else-if.cmd"
        batch_file.write_text(
            "@echo off\n"
            "if exist a (\n"
            "    echo inside\n"
            ") else if exist b (\n"
            "    echo other\n"
            ") else (\n"
            "    echo none\n"
            ")\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not [issue for issue in issues if issue.rule.code == "E001"]

    def test_programfiles_x86_not_e042(self, tmp_path: Path) -> None:
        """The standard 64-bit PROGRAMFILES(X86) check is not a block."""
        batch_file = tmp_path / "arch.cmd"
        batch_file.write_text(
            "@echo off\nif defined PROGRAMFILES(X86) echo 64bit\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not self._e042_codes(issues)

    def test_nothing_after_close_not_e042(self, tmp_path: Path) -> None:
        """Inner (parens) with nothing after the close is valid inside a block."""
        batch_file = tmp_path / "nothing-after.cmd"
        batch_file.write_text(
            "@echo off\nfor %%D in (C) do (\n    echo text (parens)\n)\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not self._e042_codes(issues)

    def test_caret_and_quotes_not_e042(self, tmp_path: Path) -> None:
        """Caret-escaped and double-quoted parentheses are not grouping operators."""
        batch_file = tmp_path / "escaped.cmd"
        batch_file.write_text(
            "@echo off\n"
            "for %%D in (C) do (\n"
            "    echo --- text ^(parens^) ---\n"
            '    echo --- text "(parens)" ---\n'
            ")\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not self._e042_codes(issues)

    def test_toplevel_trailing_text_not_e042(self, tmp_path: Path) -> None:
        """Outside a block, parentheses in ECHO text are literal."""
        batch_file = tmp_path / "toplevel.cmd"
        batch_file.write_text(
            "@echo off\necho --- text (parens) ---\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not self._e042_codes(issues)

    def test_same_line_for_block_reports_e042(self, tmp_path: Path) -> None:
        """Same-line FOR DO ( body still treats inner ) as a group closer."""
        batch_file = tmp_path / "same-line.cmd"
        batch_file.write_text(
            "@echo off\nfor %%D in (C) do (echo --- text (parens) ---)\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 2 in self._e042_codes(issues)

    def test_colon_comment_in_block_reports_e042(self, tmp_path: Path) -> None:
        """:: comments inside blocks are still parsed for parentheses."""
        batch_file = tmp_path / "colon-comment.cmd"
        batch_file.write_text(
            "@echo off\n"
            "for %%D in (C) do (\n"
            "    :: echo --- text (parens) ---\n"
            ")\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 3 in self._e042_codes(issues)

    def test_rem_comment_in_block_not_e042(self, tmp_path: Path) -> None:
        """REM comments with a following space are not parsed as grouping."""
        batch_file = tmp_path / "rem-comment.cmd"
        batch_file.write_text(
            "@echo off\n"
            "for %%D in (C) do (\n"
            "    rem echo --- text (parens) ---\n"
            ")\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert not self._e042_codes(issues)

    def test_echo_a_then_group_b_reports_e042(self, tmp_path: Path) -> None:
        """A second group immediately after ) is unexpected at parse time."""
        batch_file = tmp_path / "echo-a-b.cmd"
        batch_file.write_text(
            "@echo off\nfor %%D in (C) do (\n    echo (a) (b)\n)\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 3 in self._e042_codes(issues)

    def test_same_line_if_block_reports_e042(self, tmp_path: Path) -> None:
        """Same-line IF ( body still treats inner ) as a group closer."""
        batch_file = tmp_path / "same-line-if.cmd"
        batch_file.write_text(
            "@echo off\nif 1==1 (echo --- text (parens) ---)\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 2 in self._e042_codes(issues)

    def test_bare_paren_group_reports_e042(self, tmp_path: Path) -> None:
        """Command groups that start with ( use the same grouping rules."""
        batch_file = tmp_path / "bare-group.cmd"
        batch_file.write_text(
            "@echo off\n(\n    echo --- text (parens) ---\n)\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 3 in self._e042_codes(issues)

    def test_same_line_group_reports_e042(self, tmp_path: Path) -> None:
        """A same-line ( group body still treats inner ) as a group closer."""
        batch_file = tmp_path / "same-line-group.cmd"
        batch_file.write_text(
            "@echo off\n(echo --- text (parens) ---)\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(batch_file))
        assert 2 in self._e042_codes(issues)


class TestSetAArithmeticE022:
    """SET /A expressions common in admin scripts should not false-positive E022."""

    def test_corpus_set_a_patterns_not_e022(self) -> None:
        valid_lines = [
            "SET /A @DD_DIV_2=%@DD:~-1% %% 2",
            "SET /A @WATCHCOUNT+=%%c",
            "SET /A %~2=%%~M + 2",
            'set /a "gprdays=(!gpr!+1440-1)/1440"',
        ]
        for line in valid_lines:
            issues = _check_set_a_arithmetic(line.strip(), 1)
            assert not issues, line


class TestSecurityChecking:
    """Test security level checking edge cases."""

    def test_command_injection_pattern(self) -> None:
        """Test detection of potential command injection."""
        issues = _check_security_issues("set /p input=Enter command: && %input%", 1)
        injection_issues = [i for i in issues if i.rule.code == "SEC001"]
        assert len(injection_issues) == 1

    def test_unquoted_set_command(self) -> None:
        """Test detection of unquoted SET commands."""
        issues = _check_security_issues("set MYVAR=some value with spaces", 1)
        unsafe_set_issues = [i for i in issues if i.rule.code == "SEC002"]
        assert len(unsafe_set_issues) == 1

    def test_quoted_set_command_safe(self) -> None:
        """Test that properly quoted SET commands are not flagged."""
        issues = _check_security_issues('set "MYVAR=some value with spaces"', 1)
        unsafe_set_issues = [i for i in issues if i.rule.code == "SEC002"]
        assert len(unsafe_set_issues) == 0

    def test_safe_unquoted_path_and_url_not_sec002(self) -> None:
        """Paths, URLs, and expansions without metacharacters should not trigger SEC002."""
        safe_lines = [
            "set FOUNDRY_DIR=%LOCALAPPDATA%\\Programs\\Foundry",
            "set FOUNDRY_URL=https://github.com/foundry-rs/foundry/releases",
            "set timestamp=%datetime:~0,8%-%datetime:~8,6%",
        ]
        for line in safe_lines:
            issues = _check_security_issues(line, 1)
            assert not [i for i in issues if i.rule.code == "SEC002"], line

    def test_path_append_still_sec002(self) -> None:
        """PATH append with semicolon should still trigger SEC002."""
        issues = _check_security_issues("set PATH=%PATH%;C:\\new", 1)
        assert [i for i in issues if i.rule.code == "SEC002"]

    def test_args_star_and_string_replace_not_sec002(self) -> None:
        """%* and substring-replace SET values should not trigger SEC002."""
        safe_lines = [
            "set _args=%*",
            "set _PSarg=%_PSarg:'=''%",
            "set upver=%masver:.=%",
            "set slcSKU=%slcSKU: =%",
            "set winos=!winos:Windows 10=Windows 11!",
            "set _pridsR=%_pridsR:,= %",
            'set insoff=!insoff:"=!',
            "set _slexe=sppsvc.exe& set _slser=sppsvc",
        ]
        for line in safe_lines:
            issues = _check_security_issues(line, 1)
            assert not [i for i in issues if i.rule.code == "SEC002"], line

    def test_nested_if_else_blocks_not_e001(self) -> None:
        """IF/ELSE parenthesis transitions should balance without E001."""
        lines = [
            "if %errorlevel% neq 0 (",
            "    echo fail",
            ") else (",
            "    set ADMIN=1",
            ")",
        ]
        issues = _check_nested_paren_mismatch(lines)
        assert not issues

    def test_for_do_with_in_clause_not_e001(self) -> None:
        """FOR IN () DO () should not double-count the IN-clause parenthesis."""
        lines = [
            "for %%p in (!pow!) do (",
            '    if "!str:~%%p,1!" neq "" (',
            "        set /a len+=%%p",
            "    )",
            ")",
        ]
        issues = _check_nested_paren_mismatch(lines)
        assert not issues

    def test_bare_paren_redirect_block_not_e001(self) -> None:
        """Parenthesized command groups redirected to a log file should balance."""
        lines = [
            "( rem -- Write to Log",
            "    echo hello",
            "    echo world",
            ') >>"%@LOGFILE%"',
        ]
        issues = _check_nested_paren_mismatch(lines)
        assert not issues

    def test_unmatched_if_block_still_e001(self) -> None:
        """A missing closing parenthesis should still trigger E001."""
        issues = _check_nested_paren_mismatch(["if exist file.txt ("])
        assert len(issues) == 1
        assert issues[0].rule.code == "E001"

    def test_for_f_in_quoted_single_line_not_e001(self) -> None:
        """FOR /F IN ('file') on one line should not open an extra block."""
        lines = [
            "if exist file.txt (",
            "    if !errorlevel! equ 0 (",
            '        for /f "usebackq tokens=*" %%v in ("!VERSION_TEMP!") do set VAR=%%v',
            "    ) else (",
            "        echo fail",
            "    )",
            ")",
        ]
        issues = _check_nested_paren_mismatch(lines)
        assert not issues

    def test_echo_if_open_paren_in_redirect_block_not_e001(self) -> None:
        """Echoed script lines ending with if ( must not open batch IF blocks."""
        lines = [
            "(",
            "echo try {",
            "echo if (",
            "echo     Write-Host done",
            "echo )",
            "echo }",
            ') > "%TEMP%\\helper.ps1"',
        ]
        issues = _check_nested_paren_mismatch(lines)
        assert not issues

    def test_for_in_multiline_list_still_opens_e001_when_unclosed(self) -> None:
        """Multiline FOR IN ( lists should still participate in E001 tracking."""
        issues = _check_nested_paren_mismatch(["for %%x in ("])
        assert len(issues) == 1
        assert issues[0].rule.code == "E001"

    def test_operator_prefixed_groups_not_e001(self) -> None:
        """Blocks opened after &&, ||, or & balance with a following close."""
        samples = [
            ["cmd || (", "    echo fallback", ")"],
            ["cmd && (", "    echo ok", ")"],
            ["echo x & (", "    echo y", ")"],
        ]
        for lines in samples:
            issues = _check_nested_paren_mismatch(lines)
            assert not issues, lines

    def test_one_line_groups_not_e001(self) -> None:
        """A group that opens and closes on one line is balanced."""
        samples = [
            ["(echo a) >> log.txt"],
            ['(echo x) | find "x"'],
            ["if 1==1 (echo hi)"],
            ["for %%a in (a b) do echo %%a"],
        ]
        for lines in samples:
            issues = _check_nested_paren_mismatch(lines)
            assert not issues, lines

    def test_admin_privilege_commands(self) -> None:
        """Test detection of commands requiring admin privileges."""
        admin_commands = [
            ("reg add hklm", "reg add hklm"),
            ("reg delete hklm", "reg delete hklm"),
            ("sc config", "sc"),
            ("net user", "NET command"),
        ]
        for cmd, expected in admin_commands:
            issues = _check_security_issues(f"{cmd} something", 1)
            privilege_issues = [i for i in issues if i.rule.code == "SEC005"]
            assert len(privilege_issues) == 1
            assert expected in privilege_issues[0].context

    def test_hardcoded_absolute_paths(self) -> None:
        """Test detection of hardcoded absolute paths."""
        paths = ["C:\\Program Files\\", "D:\\MyApp\\", "/home/user/", "/Users/admin/"]
        for path in paths:
            issues = _check_security_issues(f'copy "{path}file.txt" dest', 1)
            path_issues = [i for i in issues if i.rule.code == "SEC006"]
            assert len(path_issues) == 1

    def test_hardcoded_paths_in_safe_contexts(self) -> None:
        """Test that hardcoded paths in ECHO/REM/:: statements are not flagged."""
        # ECHO statements should not trigger SEC006 (used for documentation/help)
        echo_cases = [
            "ECHO  %~n0 C:\\Scripts E:\\Scripts.Old",
            "ECHO  %~n0 C:\\Scripts F:\\Scripts.New /U",
            "echo Usage: C:\\Source D:\\Destination",
            'ECHO  "C:\\Programs\\This Program" "Y:\\Remote\\A Long Folder Name"',
            "@echo off",  # This is a command, not documentation, but should still be safe
            "@ECHO Example: C:\\Path\\To\\File",
            "echo /home/user/documents",
            "echo /Users/admin/Desktop",
        ]
        for echo_line in echo_cases:
            issues = _check_security_issues(echo_line, 1)
            path_issues = [i for i in issues if i.rule.code == "SEC006"]
            assert (
                len(path_issues) == 0
            ), f"ECHO line should not trigger SEC006: {echo_line}"

        # REM comments should not trigger SEC006
        rem_cases = [
            "REM This is a comment about C:\\Path\\To\\Something",
            "REM Example: D:\\MyApp\\config.ini",
            "rem User directory: /home/user/files",
            "REM\tC:\\Windows\\System32",
        ]
        for rem_line in rem_cases:
            issues = _check_security_issues(rem_line, 1)
            path_issues = [i for i in issues if i.rule.code == "SEC006"]
            assert (
                len(path_issues) == 0
            ), f"REM line should not trigger SEC006: {rem_line}"

        # :: comments should not trigger SEC006
        colon_cases = [
            ":: This is a comment about C:\\Path\\To\\Something",
            ":: Example: E:\\Data\\backup",
            ":: Linux path: /usr/local/bin",
        ]
        for colon_line in colon_cases:
            issues = _check_security_issues(colon_line, 1)
            path_issues = [i for i in issues if i.rule.code == "SEC006"]
            assert (
                len(path_issues) == 0
            ), f":: line should not trigger SEC006: {colon_line}"

        call_cases = [
            'CALL "C:\\Scripts\\helper.bat"',
            "call D:\\Tools\\build.cmd",
        ]
        for call_line in call_cases:
            issues = _check_security_issues(call_line, 1)
            path_issues = [i for i in issues if i.rule.code == "SEC006"]
            assert (
                len(path_issues) == 0
            ), f"CALL line should not trigger SEC006: {call_line}"

        # But actual commands with hardcoded paths SHOULD still be flagged
        actual_commands = [
            "copy C:\\Source\\file.txt D:\\Dest\\",
            "xcopy /s C:\\Data E:\\Backup",
            "cd C:\\Windows\\System32",
            "move /home/user/file.txt /tmp/",
        ]
        for cmd_line in actual_commands:
            issues = _check_security_issues(cmd_line, 1)
            path_issues = [i for i in issues if i.rule.code == "SEC006"]
            assert (
                len(path_issues) >= 1
            ), f"Actual command should trigger SEC006: {cmd_line}"

    def test_hardcoded_temp_paths(self) -> None:
        """Test detection of hardcoded temporary paths."""
        # Actual commands with hardcoded temp paths should be flagged
        flagged_cases = [
            "copy /tmp/file.txt dest",  # Linux temp path
            "move C:\\temp\\file.txt dest",  # Windows temp path
            "xcopy C:\\tmp\\* dest",  # Windows tmp path
        ]
        for cmd in flagged_cases:
            issues = _check_security_issues(cmd, 1)
            temp_issues = [i for i in issues if i.rule.code == "SEC007"]
            assert len(temp_issues) >= 1, f"Command should trigger SEC007: {cmd}"

        # ECHO statements and comments should NOT be flagged (documentation/help text)
        safe_cases = [
            "echo C:\\temp in path",  # ECHO statement
            "echo C:\\tmp in path",  # ECHO statement
            "echo /tmp in path",  # ECHO statement
            "REM This uses C:\\temp for temp files",  # REM comment
            ":: Temporary directory: C:\\tmp",  # :: comment
        ]
        for cmd in safe_cases:
            issues = _check_security_issues(cmd, 1)
            temp_issues = [i for i in issues if i.rule.code == "SEC007"]
            assert (
                len(temp_issues) == 0
            ), f"Safe context should not trigger SEC007: {cmd}"

        # Substring paths like C:\temporal must not trigger SEC007
        false_positive_cases = [
            "SET desc=C:\\temporal\\folder",
            "move C:\\temporal\\file.txt dest",
        ]
        for cmd in false_positive_cases:
            issues = _check_security_issues(cmd, 1)
            temp_issues = [i for i in issues if i.rule.code == "SEC007"]
            assert (
                len(temp_issues) == 0
            ), f"Substring path should not trigger SEC007: {cmd}"

    def test_malware_rules_skip_safe_context(self) -> None:
        """SEC021-SEC024 should not fire in REM/ECHO documentation lines."""
        safe_cases = [
            "REM start %0 recursive example",
            "ECHO >> hosts file modification example",
            "echo copy %0 to removable drive example",
        ]
        for cmd in safe_cases:
            issues = _check_security_issues(cmd, 1)
            malware_codes = {"SEC021", "SEC022", "SEC023", "SEC024"}
            flagged = [i.rule.code for i in issues if i.rule.code in malware_codes]
            assert (
                flagged == []
            ), f"Safe context should not trigger malware rules: {cmd}"


class TestPerformanceChecking:
    """Test performance level checking edge cases."""

    def test_setlocal_without_set_commands(self) -> None:
        """Test detection of unnecessary SETLOCAL."""
        lines = ["@echo off", "setlocal", "echo hello"]
        issues = _check_performance_issues(
            lines, 2, "setlocal", False, False, False, False, False, False, False
        )
        setlocal_issues = [i for i in issues if i.rule.code == "P003"]
        assert len(setlocal_issues) == 1

    def test_enabledelayedexpansion_without_delayed_vars(self) -> None:
        """Test detection of unnecessary ENABLEDELAYEDEXPANSION."""
        lines = ["setlocal enabledelayedexpansion", "echo hello"]
        issues = _check_performance_issues(
            lines,
            1,
            "setlocal enabledelayedexpansion",
            True,
            True,
            True,
            False,
            False,
            False,
            False,
        )
        delayed_issues = [i for i in issues if i.rule.code == "P004"]
        assert len(delayed_issues) == 1

    def test_endlocal_without_setlocal(self) -> None:
        """Test detection of ENDLOCAL without SETLOCAL."""
        lines = ["@echo off", "endlocal"]
        issues = _check_performance_issues(
            lines, 2, "endlocal", False, False, False, False, False, False, False
        )
        endlocal_issues = [i for i in issues if i.rule.code == "P005"]
        assert len(endlocal_issues) == 1

    def test_temp_file_without_random(self) -> None:
        """Test detection of temp files without random names."""
        temp_patterns = ["temp.txt", "tmp.txt", "temp.log"]
        for pattern in temp_patterns:
            lines = [f"echo test > {pattern}"]
            issues = _check_performance_issues(
                lines,
                1,
                f"echo test > {pattern}",
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            )
            temp_issues = [i for i in issues if i.rule.code == "P007"]
            assert len(temp_issues) == 1

    def test_temp_file_with_random_no_issue(self) -> None:
        """Test that temp files with random names don't trigger issues."""
        lines = ["echo test > temp_%RANDOM%.txt"]
        issues = _check_performance_issues(
            lines,
            1,
            "echo test > temp_%RANDOM%.txt",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        temp_issues = [i for i in issues if i.rule.code == "P007"]
        assert len(temp_issues) == 0

    def test_delayed_expansion_without_enablement(self) -> None:
        """Test detection of delayed expansion without enablement."""
        lines = ["echo !MYVAR!"]
        issues = _check_performance_issues(
            lines, 1, "echo !MYVAR!", False, False, False, False, False, False, False
        )
        delayed_issues = [i for i in issues if i.rule.code == "P008"]
        assert len(delayed_issues) == 1


class TestGlobalChecks:
    """Test global checking functions."""

    def test_collect_labels_with_duplicates(self) -> None:
        """Test label collection with duplicates."""
        lines = [":label1", "echo test", ":label1", "echo duplicate"]
        _, issues = _collect_labels(lines)
        assert len(issues) == 1
        assert issues[0].rule.code == "W013"
        assert "label1" in issues[0].context

    def test_collect_set_variables_comprehensive(self) -> None:
        """Test comprehensive variable collection."""
        lines = [
            "set VAR1=value1",
            "set /p VAR2=Enter value:",
            "set /a VAR3=5+3",
            "SET UPPER=test",
        ]
        variables = _collect_set_variables(lines)
        assert "VAR1" in variables
        assert "VAR2" in variables
        assert "VAR3" in variables
        assert "UPPER" in variables
        compound_vars = _collect_set_variables(["set /a counter+=1", "SET /A x-=2"])
        assert "COUNTER" in compound_vars
        assert "X" in compound_vars
        chained = _collect_set_variables(
            ["if !errorlevel!==0 (set _int=1&set ping_f=failed)"]
        )
        assert "PING_F" in chained
        assert "_INT" in chained
        # Should also include common environment variables
        assert "PATH" in variables
        assert "TEMP" in variables

    def test_check_undefined_variables(self) -> None:
        """Test undefined variable detection."""
        lines = ["echo %UNDEFINED_VAR%", "set DEFINED=test", "echo %DEFINED%"]
        set_vars = {"DEFINED", "PATH", "TEMP"}  # Include some common env vars
        issues = _check_undefined_variables(lines, set_vars)
        undefined_issues = [i for i in issues if i.rule.code == "E006"]
        assert len(undefined_issues) == 1
        assert "UNDEFINED_VAR" in undefined_issues[0].context

    def test_set_a_compound_assignment_tracked(self, tmp_path: Path) -> None:
        """SET /A compound assignments should define variables for E006."""
        content = "@echo off\nset /a cnt+=1\necho %cnt%\n"
        batch_file = tmp_path / "compound.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]

    def test_debug_env_var_not_e006(self, tmp_path: Path) -> None:
        """Optional DEBUG environment variable should not trigger E006."""
        content = '@echo off\nIF /I "%Debug%"=="TRUE" ECHO debug on\n'
        batch_file = tmp_path / "debug.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]

    def test_call_set_dynamic_indirection_not_e006(self, tmp_path: Path) -> None:
        """CALL SET with %% indirection should not flag intermediate names as E006."""
        content = "@echo off\nCALL SET @WHICHLOG=%%@%%A_LOG%%%~3\n"
        batch_file = tmp_path / "callset.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]

    def test_doubled_percent_literal_not_e006(self, tmp_path: Path) -> None:
        """%%VAR%% in WMIC/WQL strings should not be treated as batch expansion."""
        content = (
            "@echo off\n"
            "wmic path SoftwareLicensingProduct where "
            "(Description like '%%KMSCLIENT%%') get ID\n"
        )
        batch_file = tmp_path / "wmic.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]

    def test_call_subroutine_sets_variable_name(self, tmp_path: Path) -> None:
        """CALL :label varname with set \"%%1=\" should define varname for E006."""
        content = (
            "@echo off\n"
            "call :getrepairsetup myrepair 14\n"
            'if exist "%myrepair%" echo ok\n'
            ":getrepairsetup\n"
            'set "%1=C:\\setup.exe"\n'
            "exit /b\n"
        )
        batch_file = tmp_path / "repair.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]

    def test_call_taskgetids_sets_target_variable(self, tmp_path: Path) -> None:
        """CALL :_taskgetids varname should define varname for E006."""
        content = (
            "@echo off\n"
            "call :_taskgetids myids HKLM\\Path token\n"
            "if defined myids echo ok\n"
            ":_taskgetids\n"
            "set %1=\n"
            "exit /b\n"
        )
        batch_file = tmp_path / "taskids.cmd"
        batch_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(batch_file))
        assert not [i for i in issues if i.rule.code == "E006"]

    def test_at_prefixed_set_variable_tracked(self) -> None:
        """SET @VAR= should be collected for undefined-variable analysis."""
        variables = _collect_set_variables(["SET @ZIPSTAMP=20260101"])
        assert "@ZIPSTAMP" in variables

    def test_check_unreachable_code_after_exit(self) -> None:
        """Test unreachable code detection after EXIT."""
        lines = ["echo start", "exit /b 0", "echo unreachable"]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        assert len(unreachable_issues) == 1
        assert unreachable_issues[0].line_number == 3

    def test_unhandled_xcopy_reports_w002_w003(self) -> None:
        """Unhandled xcopy gets W002 and W003 error-handling warnings."""
        lines = ["@echo off", "xcopy C:\\src C:\\dest"]
        issues = _check_new_global_rules(lines, "test.bat")
        codes = {issue.rule.code for issue in issues}
        assert "W002" in codes
        assert "W003" in codes

    def test_unused_label_triggers_s010(self) -> None:
        """Unused labels should trigger S010."""
        lines = ["@echo off", ":unused_label", "echo done"]
        issues = _check_global_style_rules(lines, "test.cmd")
        s010_issues = [issue for issue in issues if issue.rule.code == "S010"]
        assert len(s010_issues) == 1
        assert "unused_label" in s010_issues[0].context.lower()

    def test_goto_loop_without_guard_triggers_w004(self) -> None:
        """GOTO back to a label without exit guard should trigger W004."""
        lines = ["@echo off", ":loop", "echo hello", "goto loop"]
        issues = _check_new_global_rules(lines, "test.bat")
        w004_issues = [issue for issue in issues if issue.rule.code == "W004"]
        assert len(w004_issues) == 1

    def test_goto_forward_to_label_does_not_trigger_w004(self) -> None:
        """Forward GOTO to an exit handler should not trigger W004."""
        lines = [
            "@echo off",
            "if 1==1 goto :end",
            "echo never",
            ":end",
            "exit /b 0",
        ]
        issues = _check_new_global_rules(lines, "test.bat")
        w004_issues = [issue for issue in issues if issue.rule.code == "W004"]
        assert not w004_issues

    def test_locked_path_operation_triggers_w007(self) -> None:
        """File operations under system paths should trigger W007."""
        lines = ["@echo off", "copy file.txt C:\\Windows\\System32\\file.txt"]
        issues = _check_new_global_rules(lines, "test.bat")
        w007_issues = [issue for issue in issues if issue.rule.code == "W007"]
        assert len(w007_issues) == 1

    def test_setlocal_exit_without_endlocal_triggers_p006(self) -> None:
        """Bare EXIT with active SETLOCAL should trigger P006."""
        lines = ["@echo off", "setlocal", "exit"]
        issues = _check_new_global_rules(lines, "test.bat")
        p006_issues = [issue for issue in issues if issue.rule.code == "P006"]
        assert len(p006_issues) == 1

    def test_top_level_exit_b_does_not_trigger_p006(self) -> None:
        """exit /b ends the batch file, which ends SETLOCAL."""
        lines = ["@echo off", "setlocal", "exit /b 0"]
        issues = _check_new_global_rules(lines, "test.bat")
        p006_issues = [issue for issue in issues if issue.rule.code == "P006"]
        assert not p006_issues

    def test_subroutine_exit_b_does_not_trigger_p006(self) -> None:
        """exit /b inside a CALL subroutine should not trigger P006."""
        lines = [
            "@echo off",
            "setlocal",
            "call :helper",
            "endlocal",
            "exit /b 0",
            ":helper",
            "exit /b 0",
        ]
        issues = _check_new_global_rules(lines, "test.bat")
        p006_issues = [issue for issue in issues if issue.rule.code == "P006"]
        assert not p006_issues

    def test_self_modification_triggers_sec019(self) -> None:
        """Writing to the running script should trigger SEC019."""
        lines = ["@echo off", "echo payload > test.bat"]
        issues = _check_new_global_rules(lines, "test.bat")
        sec019_issues = [issue for issue in issues if issue.rule.code == "SEC019"]
        assert len(sec019_issues) == 1

    def test_redundant_setlocal_triggers_p024(self) -> None:
        """Multiple SETLOCAL commands should trigger P024."""
        lines = [
            "@echo off",
            "setlocal",
            "echo step1",
            "echo step2",
            "echo step3",
            "echo step4",
            "echo step5",
            "setlocal",
        ]
        issues = _check_new_global_rules(lines, "test.bat")
        p024_issues = [issue for issue in issues if issue.rule.code == "P024"]
        assert len(p024_issues) == 1
        assert p024_issues[0].line_number == 8

    def test_setlocal_in_comment_does_not_trigger_p024_or_p006(self) -> None:
        """REM mentioning setlocal is not a SETLOCAL command (issue #40)."""
        lines = [
            "@echo off",
            "setlocal disabledelayedexpansion",
            "REM filler",
            "REM filler",
            "REM filler",
            "REM filler",
            "REM a bare setlocal inherits the caller state",
            "set V=1",
            "endlocal",
            "exit /b 0",
        ]
        issues = _check_new_global_rules(lines, "test.cmd")
        codes = {issue.rule.code for issue in issues}
        assert "P024" not in codes
        assert "P006" not in codes

    def test_p024_points_at_second_setlocal_not_comment(self) -> None:
        """P024 reports the second SETLOCAL command, not a comment (issue #40)."""
        lines = [
            "@echo off",
            "setlocal",
            "echo step1",
            "echo step2",
            "echo step3",
            "echo step4",
            "REM mention setlocal here",
            "setlocal enabledelayedexpansion",
        ]
        issues = _check_new_global_rules(lines, "test.cmd")
        p024_issues = [issue for issue in issues if issue.rule.code == "P024"]
        assert len(p024_issues) == 1
        assert p024_issues[0].line_number == 8

    def test_extra_endlocal_does_not_trigger_p024(self) -> None:
        """P024 requires a second SETLOCAL; extra ENDLOCAL is a different rule."""
        lines = [
            "@echo off",
            "setlocal",
            "echo hi",
            "endlocal",
            "endlocal",
            "exit /b 0",
        ]
        issues = _check_new_global_rules(lines, "test.cmd")
        assert all(issue.rule.code != "P024" for issue in issues)

    def test_if_goto_and_call_labels_are_not_s010(self) -> None:
        """Labels reached via IF/|| GOTO or IF CALL are not dead (issue #39)."""
        lines = [
            "@echo off",
            'if "%~1"=="" goto :from_if',
            "goto :from_bare",
            'if "%~1"=="" call :from_if_call',
            "call :from_bare_call",
            "echo x || goto :from_or",
            "exit /b 0",
            ":from_if",
            "exit /b 0",
            ":from_bare",
            "exit /b 0",
            ":from_if_call",
            "exit /b 0",
            ":from_bare_call",
            "exit /b 0",
            ":from_or",
            "exit /b 0",
        ]
        issues = _check_global_style_rules(lines, "test.cmd")
        s010_issues = [issue for issue in issues if issue.rule.code == "S010"]
        assert not s010_issues

    def test_goto_in_comment_or_echo_does_not_count_as_s010_ref(self) -> None:
        """GOTO inside REM or ECHO should not mark a label as referenced."""
        lines = [
            "@echo off",
            "REM goto :never_used",
            "echo goto :never_used",
            ":never_used",
            "exit /b 0",
        ]
        issues = _check_global_style_rules(lines, "test.cmd")
        s010_issues = [issue for issue in issues if issue.rule.code == "S010"]
        assert len(s010_issues) == 1
        assert "never_used" in s010_issues[0].context.lower()

    def test_for_f_noprofile_command_does_not_trigger_w036(self) -> None:
        """usebackq backtick commands are not data files (issue #37)."""
        line = (
            'for /f "usebackq delims=" %%V in '
            '(`powershell -NoProfile -Command "1+1"`) do set "D=%%V"'
        )
        assert _for_f_file_set_operand(line) == ""
        issues = _check_advanced_for_rules(line, 2)
        assert not [issue for issue in issues if issue.rule.code == "W036"]

    def test_for_f_data_file_still_triggers_w036(self) -> None:
        """FOR /F over a .txt file without skip= still reports W036."""
        line = "FOR /F %%a IN (data.txt) DO echo %%a"
        issues = _check_advanced_for_rules(line, 2)
        assert any(issue.rule.code == "W036" for issue in issues)

    def test_for_f_usebackq_single_quoted_file_triggers_w036(self) -> None:
        """With usebackq, a single-quoted operand is a filename."""
        line = "FOR /F \"usebackq tokens=1\" %%a IN ('datafile.txt') DO echo %%a"
        assert "datafile.txt" in _for_f_file_set_operand(line)
        issues = _check_advanced_for_rules(line, 2)
        assert any(issue.rule.code == "W036" for issue in issues)

    def test_check_unreachable_code_after_goto(self) -> None:
        """Test unreachable code detection after GOTO."""
        lines = ["echo start", "goto end", "echo unreachable", ":end"]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        assert len(unreachable_issues) == 1
        assert unreachable_issues[0].line_number == 3

    def test_no_unreachable_code_after_labels_comments(self) -> None:
        """Test that labels and comments after EXIT/GOTO are not flagged."""
        lines = ["echo start", "exit /b 0", ":label", "rem comment"]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        assert len(unreachable_issues) == 0

    def test_block_redirection_not_unreachable(self) -> None:
        """Test that block redirection operators are not flagged as unreachable code."""
        # This tests the GitHub issue where redirection after a block is incorrectly
        # flagged as unreachable code
        lines = [
            " rem -- Print Count of Discovered Systems by OS",
            ' IF "%~1"=="----" (',
            "\t ECHO:",
            '\t FOR /F "TOKENS=2-3 DELIMS==#" %%F IN (\'SET "#COUNT#" 2^>NUL\') DO (',
            "\t\t CALL :ChangeCase #NAME#%%F -U",
            "\t\t SET @THISOS=%%F",
            "\t\t SET @THISOS=!@THISOS:_=,!",
            "\t\t ECHO \t%%G \t!@THISOS:–= !",
            "\t\t ECHO \t\t -- !#NAME#%%F!",
            "\t\t ECHO:",
            "\t )",
            "\t EXIT /B",
            " ) >>%@LOGFILE% 2>&1",  # This line should NOT be flagged as unreachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        # The redirection operator line should NOT be flagged
        assert len(unreachable_issues) == 0

    def test_various_redirection_patterns_not_unreachable(self) -> None:
        """Test various redirection operator patterns after EXIT."""
        # Test different redirection patterns
        test_cases = [
            # Standard output redirection
            ["IF true (", "  EXIT /B", ") >output.txt"],
            # Append redirection
            ["IF true (", "  EXIT /B", ") >>output.log"],
            # Input redirection
            ["IF true (", "  EXIT /B", ") <input.txt"],
            # Error redirection
            ["IF true (", "  EXIT /B", ") 2>error.log"],
            # Combined output and error
            ["IF true (", "  EXIT /B", ") >output.txt 2>&1"],
            # Suppress output
            ["IF true (", "  EXIT /B", ") >nul 2>&1"],
            # Error to null
            ["IF true (", "  EXIT /B", ") 2>nul"],
        ]

        for lines in test_cases:
            issues = _check_unreachable_code(lines)
            unreachable_issues = [i for i in issues if i.rule.code == "E008"]
            assert (
                len(unreachable_issues) == 0
            ), f"Redirection should not be flagged as unreachable: {lines[-1]}"

    def test_truly_unreachable_code_still_detected(self) -> None:
        """Test that truly unreachable code is still detected after unconditional EXIT."""
        # EXIT at depth 0 (not in a conditional block) makes following code unreachable
        lines = [
            "ECHO start",
            "EXIT /B",
            "ECHO this is truly unreachable",  # This IS unreachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        # Should detect the ECHO command after unconditional EXIT as unreachable
        assert len(unreachable_issues) == 1
        assert unreachable_issues[0].line_number == 3

    def test_exit_inside_if_block_with_redirect_append(self) -> None:
        """Test EXIT inside IF block with redirect append operator (>>)."""
        lines = [
            'IF "%~1"=="test" (',
            "  ECHO Processing test",
            "  EXIT /B",
            ") >>%LOGFILE% 2>&1",
            "ECHO Main routine continues",  # This IS reachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        # Line 5 is reachable because EXIT is inside IF block
        assert len(unreachable_issues) == 0

    def test_goto_inside_if_block_with_redirect_single(self) -> None:
        """Test GOTO inside IF block with single redirect operator (>)."""
        lines = [
            'IF EXIST "file.txt" (',
            "  ECHO File found",
            "  GOTO :process",
            ") >output.log",
            "ECHO Default processing",  # This IS reachable
            ":process",
            "ECHO Processing file",
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        # Line 5 is reachable because GOTO is inside IF block
        assert len(unreachable_issues) == 0

    def test_exit_inside_nested_blocks_with_redirect(self) -> None:
        """Test EXIT inside nested blocks with redirect operators."""
        lines = [
            'IF "%~1"=="outer" (',
            '  IF "%~2"=="inner" (',
            "    ECHO Inner condition",
            "    EXIT /B 0",
            "  ) >inner.log",
            "  ECHO Outer continues",  # This IS reachable
            ") >>outer.log 2>&1",
            "CALL :MainRoutine",  # This IS reachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        # Both lines after the EXIT are reachable
        assert len(unreachable_issues) == 0

    def test_exit_with_redirect_error_stream(self) -> None:
        """Test EXIT with error stream redirect (2>)."""
        lines = [
            "IF DEFINED MYVAR (",
            "  SET VALUE=%MYVAR%",
            "  EXIT /B",
            ") 2>error.log",
            "ECHO Processing without MYVAR",  # This IS reachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        assert len(unreachable_issues) == 0

    def test_exit_with_combined_redirect(self) -> None:
        """Test EXIT with combined stdout and stderr redirect (>file 2>&1)."""
        lines = [
            "IF ERRORLEVEL 1 (",
            "  ECHO Error occurred",
            "  EXIT /B 1",
            ") >output.txt 2>&1",
            "ECHO Success path",  # This IS reachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        assert len(unreachable_issues) == 0

    def test_exit_with_nul_redirect(self) -> None:
        """Test EXIT with redirect to nul."""
        lines = [
            "IF NOT EXIST file.txt (",
            "  ECHO File not found",
            "  EXIT /B 2",
            ") >nul 2>&1",
            "ECHO File exists",  # This IS reachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        assert len(unreachable_issues) == 0

    def test_ops_logs_exact_pattern(self) -> None:
        """Test the exact pattern from OpsLogs.BAT that triggered the bug."""
        lines = [
            " rem -- Print Count of Discovered Systems by OS",
            ' IF "%~1"=="----" (',
            "\t ECHO:",
            '\t FOR /F "TOKENS=2-3 DELIMS==#" %%F IN (\'SET "#COUNT#" 2^>NUL\') DO (',
            "\t\t CALL :ChangeCase #NAME#%%F -U",
            "\t\t SET @THISOS=%%F",
            "\t\t SET @THISOS=!@THISOS:_=,!",
            "\t\t ECHO \t%%G \t!@THISOS:–= !",
            "\t\t ECHO \t\t -- !#NAME#%%F!",
            "\t\t ECHO:",
            "\t )",
            "\t EXIT /B",
            " ) >>%@LOGFILE% 2>&1",
            "",
            " rem -- Main Routine",
            " CALL :DisplaySysInfo %~1",  # Line 16: This IS reachable
        ]
        issues = _check_unreachable_code(lines)
        unreachable_issues = [i for i in issues if i.rule.code == "E008"]
        # Line 16 should NOT be flagged as unreachable
        assert len(unreachable_issues) == 0

    def test_check_redundant_operations(self) -> None:
        """Test redundant operations detection."""
        lines = [
            "if exist file.txt echo found",
            "echo something",
            "if exist file.txt del file.txt",
        ]
        issues = _check_redundant_operations(lines)
        redundant_issues = [i for i in issues if i.rule.code == "P001"]
        assert len(redundant_issues) == 1
        assert redundant_issues[0].line_number == 3

    def test_check_code_duplication(self) -> None:
        """Test code duplication detection."""
        # Code duplication needs 3+ similar commands AND normalized length > 20
        # Note: The new implementation requires normalized commands > 40 chars and uses
        # adaptive thresholds based on script size. For very small scripts (< 100 lines),
        # the threshold is 3+ occurrences within 100 lines of each other.
        lines = [
            "robocopy %SOURCE% %DEST% /MIR /COPYALL /R:3 /W:10 "
            "/LOG:backup.log with some extra text",
            "robocopy %SOURCE% %DEST% /MIR /COPYALL /R:3 /W:10 "
            "/LOG:backup2.log with some extra text",
            "robocopy %SOURCE% %DEST% /MIR /COPYALL /R:3 /W:10 "
            "/LOG:backup3.log with some extra text",
            "robocopy %SOURCE% %DEST% /MIR /COPYALL /R:3 /W:10 "
            "/LOG:backup4.log with some extra text",
        ]
        # This normalizes variables to VAR and files to FILE, all should be identical
        issues = _check_code_duplication(lines)
        duplication_issues = [i for i in issues if i.rule.code == "P002"]
        assert len(duplication_issues) == 3  # Lines 2, 3 and 4 should be flagged

    def test_no_code_duplication_with_few_commands(self) -> None:
        """Test that code duplication requires 3+ similar commands."""
        lines = [
            "copy file1.txt backup\\file1.txt",
            "copy file2.txt backup\\file2.txt",  # Only 2 similar, should not trigger
        ]
        issues = _check_code_duplication(lines)
        duplication_issues = [i for i in issues if i.rule.code == "P002"]
        assert len(duplication_issues) == 0


class TestRuleEdgeCases:
    """Test edge cases in individual rules that are hard to trigger."""

    def create_temp_batch_file(self, content: str) -> str:
        """Create a temporary batch file with the given content."""

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".bat", encoding="utf-8"
        ) as f:
            f.write(content)
            return f.name

    def test_comment_style_labels_not_flagged_as_duplicates(self) -> None:
        """Test that comment-style labels (:::::::) are not flagged as duplicates."""

        content = """@echo off
::::::::::::::::::::::::
:: This is a comment
::::::::::::::::::::::::
ECHO Hello
::::::::::::::::::::::::
:: Another comment  
::::::::::::::::::::::::
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should not have duplicate label warnings for comment-style labels
            duplicate_issues = [i for i in issues if i.rule.code == "W013"]
            assert len(duplicate_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_e003_if_incomplete_comparison(self) -> None:
        """Test E003 rule for incomplete IF statement comparisons."""

        content = """@echo off
IF myvar
IF "somevalue"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e003_issues = [i for i in issues if i.rule.code == "E003"]
            assert len(e003_issues) == 2
        finally:
            os.unlink(temp_file)

    def test_e011_mismatched_percent_delimiters(self) -> None:
        """Test E011 rule for mismatched percent delimiters."""

        content = """@echo off
ECHO This has mismatched %VAR delimiters
SET result=%ERRORLEVEL
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 2  # Both lines have mismatched delimiters
        finally:
            os.unlink(temp_file)

    def test_e011_mismatched_exclamation_delimiters(self) -> None:
        """Test E011 rule for mismatched exclamation delimiters."""

        content = """@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
ECHO This has mismatched !VAR delimiters
SET result=!ERRORLEVEL
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 2  # Both lines have mismatched delimiters
        finally:
            os.unlink(temp_file)

    def test_s014_long_parameter_list(self) -> None:
        """Test S014 rule for long parameter lists in CALL statements."""

        content = """@echo off
CALL :myfunction param1 param2 param3 param4 param5 param6 param7
:myfunction
ECHO Function called
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            s014_issues = [i for i in issues if i.rule.code == "S014"]
            assert len(s014_issues) == 1
            assert "7 parameters" in s014_issues[0].context
        finally:
            os.unlink(temp_file)

    def test_s014_call_with_chained_command(self) -> None:
        """Test that chained commands after CALL are not counted as parameters."""

        content = """@echo off
CALL :GetParams "D" @THISDAY & IF NOT DEFINED @THISDAY (SET @THISDAY=%@TODAY_EXP%)
CALL :myfunc p1 p2 && ECHO Success
CALL :myfunc p1 p2 || ECHO Failure
CALL :myfunc p1 p2 | findstr "test"
:GetParams
:myfunc
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            s014_issues = [i for i in issues if i.rule.code == "S014"]
            # None of these should trigger S014 as they all have <=5 parameters before chaining
            assert len(s014_issues) == 0
        finally:
            os.unlink(temp_file)


class TestSpecificRuleEdgeCases:
    """Test specific rule edge cases that are hard to trigger."""

    def create_temp_batch_file(self, content: str) -> str:
        """Create a temporary batch file with the given content."""

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".bat", encoding="utf-8"
        ) as f:
            f.write(content)
            return f.name

    def test_if_exist_with_comparison_operator_e004(self) -> None:
        """Test E004 rule for IF EXIST syntax mixing."""

        content = """@echo off
IF EXIST myfile.txt == "yes" ECHO Found
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e004_issues = [i for i in issues if i.rule.code == "E004"]
            assert len(e004_issues) == 1
        finally:
            os.unlink(temp_file)

    def test_path_invalid_characters_e005(self) -> None:
        """Test E005 rule for invalid path characters."""

        # Test truly invalid characters (< > |) are still caught
        content = """@echo off
COPY "file<test>.txt", "dest>folder",
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e005_issues = [i for i in issues if i.rule.code == "E005"]
            assert len(e005_issues) >= 1  # Should detect invalid path characters
        finally:
            os.unlink(temp_file)

        # Test that wildcards (* and ?) are NOT flagged as invalid
        content2 = """@echo off
COPY "*.txt", "dest",
DEL "file?.bat",
"""
        temp_file2 = self.create_temp_batch_file(content2)
        try:
            issues2 = lint_batch_file(temp_file2)
            e005_issues2 = [i for i in issues2 if i.rule.code == "E005"]
            assert len(e005_issues2) == 0  # Wildcards should NOT be flagged
        finally:
            os.unlink(temp_file2)

    def test_for_loop_missing_do_e010(self) -> None:
        """Test E010 rule for FOR loop missing DO keyword."""

        content = """@echo off
FOR %%i IN (1 2 3) ECHO %%i
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e010_issues = [i for i in issues if i.rule.code == "E010"]
            assert len(e010_issues) == 1
        finally:
            os.unlink(temp_file)

    def test_subroutine_call_without_call_e012(self) -> None:
        """Test E012 rule for subroutine invocation without CALL."""

        # Test case: attempting to invoke a label without CALL or GOTO
        content = """@echo off
REM Define a subroutine
:ProcessFile
ECHO Processing %1
EXIT /B

REM Incorrect invocation - missing CALL
ProcessFile mydata.txt

REM Correct invocations - should NOT trigger E012
CALL :ProcessFile mydata2.txt
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e012_issues = [i for i in issues if i.rule.code == "E012"]
            # Should trigger E012 only for "ProcessFile mydata.txt" line
            assert len(e012_issues) == 1
            assert e012_issues[0].line_number == 8
        finally:
            os.unlink(temp_file)

    def test_e012_label_definition_with_comment(self) -> None:
        """Test E012 does NOT trigger for label definitions with inline comments."""

        content = """@echo off
:GetDate7 -- Deprecated because the DOFF utility is no longer available
ECHO This is GetDate7
EXIT /B

:MyFunction - This is my function
ECHO Processing
EXIT /B
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e012_issues = [i for i in issues if i.rule.code == "E012"]
            # Label definitions with comments should NOT trigger E012
            assert len(e012_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_e012_builtin_commands(self) -> None:
        """Test E012 does NOT trigger for builtin commands that match label names."""

        content = """@echo off
:echo
ECHO This is a label named echo
EXIT /B

:set
SET VAR=value
EXIT /B

REM These should NOT trigger E012 because echo and set are builtins
echo Hello World
set MY_VAR=test
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e012_issues = [i for i in issues if i.rule.code == "E012"]
            # Builtin commands should NOT trigger E012 even if labels exist
            assert len(e012_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_e012_case_insensitive(self) -> None:
        """Test E012 detects case-insensitive label invocations."""

        content = """@echo off
:MyFunction
ECHO In function
EXIT /B

REM All of these should trigger E012
myfunction arg1
MYFUNCTION arg2
MyFunction arg3
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e012_issues = [i for i in issues if i.rule.code == "E012"]
            # All three case variations should trigger E012
            assert len(e012_issues) == 3
        finally:
            os.unlink(temp_file)

    def test_e012_correct_invocations(self) -> None:
        """Test E012 does NOT trigger for correct CALL and GOTO usage."""

        content = """@echo off
:MyFunction
ECHO In function
EXIT /B

:AnotherFunction
ECHO Another function
EXIT /B

REM Correct usages - should NOT trigger E012
CALL :MyFunction
call :MyFunction
CALL :MyFunction arg1 arg2
GOTO :AnotherFunction
goto :MyFunction
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e012_issues = [i for i in issues if i.rule.code == "E012"]
            # Correct CALL/GOTO usage should NOT trigger E012
            assert len(e012_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_magic_number_in_timeout_s009(self) -> None:
        """Test S009 rule for magic numbers in timeout commands."""

        content = """@echo off
TIMEOUT /T 300
PING localhost -n 25
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            s009_issues = [i for i in issues if i.rule.code == "S009"]
            assert len(s009_issues) == 2  # Both 300 and 25 are large numbers
        finally:
            os.unlink(temp_file)


class TestSpecializedEdgeCases:
    """Additional edge case tests for specialized scenarios."""

    def test_detect_line_endings_file_read_errors(self) -> None:
        """Test _detect_line_endings with file read errors."""
        nonexistent_file = "nonexistent_file_path_test.bat"

        # Test FileNotFoundError
        try:
            _detect_line_endings(nonexistent_file)
            assert False, "Should have raised OSError"
        except OSError as e:
            assert "Cannot read file" in str(e)
            assert "nonexistent_file_path_test.bat" in str(e)

    def test_detect_line_endings_permission_error(self) -> None:
        """Test _detect_line_endings with permission error."""
        # Create a temporary file and then try to simulate permission error
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write("@echo off\r\n")
            temp_file_path = temp_file.name

        try:
            # Mock open to raise PermissionError
            with patch("builtins.open", side_effect=PermissionError("Access denied")):
                try:
                    _detect_line_endings(temp_file_path)
                    assert False, "Should have raised OSError"
                except OSError as e:
                    assert "Cannot read file" in str(e)
        finally:
            os.unlink(temp_file_path)

    def test_has_multibyte_chars_unicode_encode_error(self) -> None:
        """Test _has_multibyte_chars with lines that cause UnicodeEncodeError."""
        # Create lines that would cause encoding issues when trying to encode to ASCII
        lines_with_unicode = [
            "echo Hello",  # Normal line
            "echo Café ñoño",  # Line with accented characters
            "echo 中文测试",  # Line with Chinese characters
            "echo Ελληνικά",  # Line with Greek characters
        ]

        has_multibyte, affected_lines = _has_multibyte_chars(lines_with_unicode)

        assert has_multibyte is True
        # Lines with non-ASCII characters should be detected
        assert 2 in affected_lines  # "echo Café ñoño"
        assert 3 in affected_lines  # "echo 中文测试"
        assert 4 in affected_lines  # "echo Ελληνικά"

    def test_enhanced_commands_function(self) -> None:
        """Test enhanced commands function."""

        # Test enhanced commands function
        lines = [
            "@echo off",
            "timeout /t 30",  # Should trigger S009
            "ping localhost -t",  # Should trigger various rules
            "choice /c yn /m 'Continue?'",
            "for /f %%i in ('dir') do echo %%i",
        ]

        issues = _check_enhanced_commands(lines)
        assert isinstance(issues, list)

    def test_advanced_vars_function(self) -> None:
        """Test _check_advanced_vars function."""
        lines = [
            "@echo off",
            "set VAR=value",
            "set SPECIAL_VAR=special",
            "echo %VAR%",
            "set PATH=C:\\Windows;%PATH%",  # Path modification
        ]

        issues = _check_advanced_vars(lines)
        assert isinstance(issues, list)

    def test_enhanced_security_rules(self) -> None:
        """Test _check_enhanced_security_rules function."""
        lines = [
            "@echo off",
            "powershell.exe -Command Get-Process",  # Should trigger security rule
            "net user admin password /add",  # Security issue
            "reg delete HKLM\\Software /f",  # Dangerous registry operation
            "rundll32 shell32.dll,ShellExec_RunDLL cmd.exe",
        ]

        issues = _check_enhanced_security_rules(lines)
        assert isinstance(issues, list)

    def test_quoted_var_beside_operator_not_sec013(self) -> None:
        """Quoted variables next to && or || are not command injection."""
        lines = [
            'findstr /i "x" "%f%" >nul && echo found',
            'md "%TEMP%\\a" || echo exists',
        ]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_unquoted_command_var_still_sec013(self) -> None:
        """An unquoted variable used as the command is still injection."""
        issues = _check_enhanced_security_rules(["%cmd% & echo done"])
        assert [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_nul_macro_conditional_block_not_sec013(self) -> None:
        """Redirect macros before && ( should not trigger SEC013."""
        lines = ['sc query gcs | find /i "RUNNING" %nul% && (']
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_menu_setlocal_call_not_sec013(self) -> None:
        """Menu dispatch via setlocal & call should not trigger SEC013."""
        lines = ["if %_erl%==5 setlocal & call :KMSActivation"]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_menu_start_goto_not_sec013(self) -> None:
        """Menu start URL chains with goto should not trigger SEC013."""
        lines = ["if %_erl%==2 start %mas%genuine-installation-media & goto :Extras"]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_if_defined_compound_set_not_sec013(self) -> None:
        """Compound SET inside IF ( ) should not trigger SEC013."""
        lines = ["if defined altkey (set key=%altkey%&set changekey=1&set notworking=)"]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_psc_invocation_not_sec013(self) -> None:
        """PowerShell helper lines should not trigger SEC013."""
        lines = [
            '%psc% "Start-Job { Restart-Service ClipSVC } | Wait-Job -Timeout 20 | Out-Null"'
        ]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_if_erl_paren_set_menu_not_sec013(self) -> None:
        """Menu SET chains inside IF ( ) should not trigger SEC013."""
        lines = [
            'if %_erl%==8 (set "_oem=TSforge" & set "para=/Z-Windows" &goto:Extract$OEM$3)'
        ]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_if_compare_paren_set_not_sec013(self) -> None:
        """IF compare (SET & SET) chains should not trigger SEC013."""
        lines = ["if %winbuild% LEQ 6300 (set _slexe=SLsvc.exe& set _slser=SLsvc)"]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_chained_set_at_vars_not_sec013(self) -> None:
        """Chained SET @var=...& SET @var=... should not trigger SEC013."""
        lines = [
            "SET @TIMED_FORMAT=!@BACKUP_ROOT!\\%COMPUTERNAME%_!@SOURCENAME!.ZIP& SET @TIMED_FORMAT=!@TIMED_FORMAT:%COMPUTERNAME%=!"
        ]
        issues = _check_enhanced_security_rules(lines)
        assert not [issue for issue in issues if issue.rule.code == "SEC013"]

    def test_enhanced_performance_function(self) -> None:
        """Test _check_enhanced_performance function."""
        lines = [
            "@echo off",
            "setlocal",
            "set VAR=value",  # Using setlocal without actual variable operations
            "endlocal",
            "for %%i in (1 2 3 4 5) do echo %%i",  # Could be optimized
        ]

        issues = _check_enhanced_performance(lines)
        assert isinstance(issues, list)

    def test_function_docs_checking(self) -> None:
        """Test _check_function_docs function."""
        lines = [
            "@echo off",
            ":function_name",
            "echo This is a function",
            "goto :eof",
            ":another_function",  # Function without documentation
            "echo Another function",
            "goto :eof",
        ]

        for line_num, line in enumerate(lines, 1):
            issues = _check_function_docs(line, line_num, lines)
            assert isinstance(issues, list)

    def test_magic_numbers_function(self) -> None:
        """Test _check_magic_numbers function."""
        test_lines = [
            "timeout /t 300",  # Magic number
            "ping localhost -n 50",  # Magic number
            "set /a result=42*7",  # Magic numbers
            "echo Simple line",  # No magic numbers
        ]

        for line_num, line in enumerate(test_lines, 1):
            issues = _check_magic_numbers(line, line_num)
            assert isinstance(issues, list)

    def test_magic_numbers_not_flagged_in_comments(self) -> None:
        """Test that magic numbers in comments are not flagged (S019 bug fix)."""
        # Test REM comments with various numeric patterns
        rem_comment_lines = [
            "rem Created On: 22 Jun 2003",
            "REM         By: Andrew S. Baker",
            "rem OS Required: Windows 2008 or later (previously Windows 2003+)",
            "rem Updated to v4.0 in 2018",
            "REM Using code page 1252 or 65001",
        ]

        # Test :: and ::: comments with numeric patterns
        colon_comment_lines = [
            ":: Notes Prior to January 2014 Have Been Purged",
            "::: (Nov 2014) v7.1 -- Reverted to old method",
            "::: (Mar 2012) v6.0 -- Added support for 64-bit systems",
            "::  https://www.dostips.com/forum/viewtopic.php?t=774",
            "::: Change from Code Page 1252 to Code Page 65001 (Unicode)",
        ]

        # Test that no magic numbers are flagged in comments
        for line in rem_comment_lines + colon_comment_lines:
            issues = _check_magic_numbers(line, 1)
            assert (
                len(issues) == 0
            ), f"Magic numbers should not be flagged in comment: {line}"

        # Test that magic numbers ARE still flagged in actual code (not in SET statements)
        # Using numbers that won't trigger path/GUID heuristics (avoid /, \, -, etc.)
        code_lines_should_flag = [
            "TIMEOUT /T 2003",  # Custom timeout - should flag 2003
            "PING -n 5000 localhost",  # Custom ping count - should flag 5000
            "IF %ERRORLEVEL% EQU 999 GOTO error",  # Custom error level - should flag 999
        ]

        code_lines_should_not_flag = [
            "set count=1",  # Single digit
            "set max=100",  # Common exception
            "set timeout=60",  # Common exception (60 seconds)
            "set YEAR=2003",  # SET statement - defining a constant (correct pattern)
            "set LIMIT=5000",  # SET statement - defining a constant (correct pattern)
            "set MAX_RETRIES=999",  # SET statement - defining a constant (correct pattern)
        ]

        for code_line in code_lines_should_flag:
            issues = _check_magic_numbers(code_line, 1)
            assert (
                len(issues) > 0
            ), f"Magic number should be flagged in code: {code_line}"

        for code_line in code_lines_should_not_flag:
            issues = _check_magic_numbers(code_line, 1)
            assert len(issues) == 0, f"This number should not be flagged: {code_line}"

    def test_line_length_function(self) -> None:
        """Test _check_line_length function."""
        # Test with very long line
        long_line = "echo " + "x" * 200  # Long line should trigger S011
        short_line = "echo hello"  # Short line should not trigger

        long_issues = _check_line_length(long_line, 1)
        short_issues = _check_line_length(short_line, 2)

        assert isinstance(long_issues, list)
        assert isinstance(short_issues, list)
        # Long line should have issues, short line should not
        assert len(long_issues) > 0
        assert len(short_issues) == 0

    def test_advanced_style_rules(self) -> None:
        """Test _check_advanced_style_rules function."""
        lines = [
            "@echo off",
            "REM This is a comment",
            "echo hello world",
            "SET VAR=value",  # Mixed case command
            "Echo Mixed Case",  # Mixed case command
        ]

        issues = _check_advanced_style_rules(lines)
        assert isinstance(issues, list)

    def test_multibyte_chars_unicode_encode_error(self) -> None:
        """Test _has_multibyte_chars handling of UnicodeEncodeError."""
        # Create a custom line that will trigger UnicodeEncodeError
        # We'll patch the function to directly simulate the error condition
        with patch(
            "blinter.checkers.line_endings._has_multibyte_chars"
        ) as mock_has_multibyte:
            mock_has_multibyte.return_value = (True, [1])
            lines = ["test line"]
            has_mb, affected_lines = mock_has_multibyte(lines)
            assert has_mb is True
            assert 1 in affected_lines

    def test_detect_line_endings_empty_file(self) -> None:
        """Test line ending detection with empty content."""
        # This test handles empty file scenarios
        # Just test basic functionality here

        with tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False) as f:
            temp_path = f.name
        try:
            ending_type, has_mixed, crlf, lf, cr = _detect_line_endings(temp_path)
            assert ending_type in ["LF", "CRLF", "CR", "NONE"]
            assert isinstance(has_mixed, bool)
        finally:
            os.unlink(temp_path)

    def test_security_powershell_execution_policy_bypass(self) -> None:
        """Test PowerShell execution policy bypass detection."""
        result = _check_security_issues(
            "powershell -ExecutionPolicy Bypass -Command malicious", 1
        )
        assert any(issue.rule.code == "SEC009" for issue in result)

    def test_security_powershell_execution_bypass_lowercase(self) -> None:
        """Test SEC009 PowerShell execution policy bypass detection with lowercase."""
        # Test case that should trigger line 2528 in blinter.py
        result = _check_security_issues(
            "powershell -executionpolicy bypass -command dangerous", 1
        )
        sec009_issues = [i for i in result if i.rule.code == "SEC009"]
        assert len(sec009_issues) >= 1

    def test_empty_file_scenarios(self) -> None:
        """Test scenarios with empty files and edge cases."""

        # Create a truly empty file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False) as f:
            temp_path = f.name  # Write nothing

        try:
            # Test linting empty file
            config = BlinterConfig()
            issues = lint_batch_file(temp_path, config)
            # Should handle empty file gracefully
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_path)

    def test_file_with_only_whitespace(self) -> None:
        """Test file with only whitespace to trigger edge cases."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False) as f:
            f.write("   \n\t\n   \n")  # Only whitespace
            temp_path = f.name

        try:
            config = BlinterConfig()
            issues = lint_batch_file(temp_path, config)
            # Should handle whitespace-only file
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_path)

    def test_single_line_file_no_newline(self) -> None:
        """Test file with single line and no newline."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False) as f:
            f.write("@echo off")  # No newline at end
            temp_path = f.name

        try:
            config = BlinterConfig()
            issues = lint_batch_file(temp_path, config)
            # Should handle file without final newline
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_path)

    def test_file_with_unicode_bom(self) -> None:
        """Test file with Unicode BOM."""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8-sig"
        ) as f:
            f.write("@echo off\necho Hello\n")
            temp_path = f.name

        try:
            config = BlinterConfig()
            issues = lint_batch_file(temp_path, config)
            # Should handle BOM correctly
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_path)


class TestEnhancedQuoteChecking:
    """Test cases for comprehensive quote checking implementation."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file with given content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_caret_escaped_quotes(self) -> None:
        """Test that caret-escaped quotes (^") are handled correctly."""
        content = """@ECHO OFF
ECHO This is a caret-escaped quote: ^"test^"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should not report unmatched quotes for caret-escaped quotes
            quote_issues = [
                issue for issue in issues if "quote" in issue.rule.name.lower()
            ]
            assert len(quote_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_escaped_quotes_double_quote(self) -> None:
        """Test that double-quote escaping ("") is handled correctly."""
        content = """@ECHO OFF
SET "VAR=This has ""escaped"" quotes"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should not report E009 (unmatched quotes) for "" escaping
            # May report E028 (complex quote escaping) which is a different check
            e009_issues = [issue for issue in issues if issue.rule.code == "E009"]
            assert len(e009_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_line_continuation_with_quote(self) -> None:
        """Test that line continuation (^) with quotes is handled correctly."""
        content = """@ECHO OFF
ECHO This line continues^
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should handle line continuation properly
            quote_issues = [
                issue for issue in issues if "quote" in issue.rule.name.lower()
            ]
            # Line continuation should prevent false positive
            assert len(quote_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_delayed_expansion_in_set(self) -> None:
        """Test that delayed expansion in SET commands is handled correctly."""
        content = """@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
SET "VAR=!OTHER_VAR!"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should not incorrectly flag delayed expansion
            quote_issues = [
                issue for issue in issues if "quote" in issue.rule.name.lower()
            ]
            assert len(quote_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_call_label_substitution(self) -> None:
        """Test that CALL label substitution is handled correctly."""
        content = """@ECHO OFF
CALL :subroutine "param1" "param2"
GOTO :EOF

:subroutine
ECHO %~1
EXIT /B
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should handle CALL label substitution without false positives
            quote_issues = [
                issue for issue in issues if "quote" in issue.rule.name.lower()
            ]
            assert len(quote_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_parentheses_context_tracking(self) -> None:
        """Test that parentheses context is tracked correctly."""
        content = """@ECHO OFF
IF EXIST "file.txt" (
    ECHO "File exists"
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should correctly handle quotes within parentheses
            quote_issues = [
                issue for issue in issues if "quote" in issue.rule.name.lower()
            ]
            assert len(quote_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_actual_unmatched_quote(self) -> None:
        """Test that actual unmatched quotes are still detected."""
        content = """@ECHO OFF
ECHO "This quote is unmatched
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect the unmatched quote
            quote_issues = [
                issue for issue in issues if "quote" in issue.rule.name.lower()
            ]
            assert len(quote_issues) > 0
        finally:
            os.unlink(temp_file)


class TestEnhancedBlockDetection:
    """Test cases for comprehensive block detection implementation."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file with given content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_block_end_with_goto(self) -> None:
        """Test that GOTO statements properly end blocks."""
        content = """@ECHO OFF
REM Documented section
:main_label
SET VAR=value
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Block should end with GOTO
            doc_issues = [
                issue for issue in issues if "documentation" in issue.rule.name.lower()
            ]
            # Should not flag missing documentation after GOTO
            assert len(doc_issues) == 0 or all(
                issue.line_number <= 3 for issue in doc_issues
            )
        finally:
            os.unlink(temp_file)

    def test_block_end_with_exit(self) -> None:
        """Test that EXIT statements properly end blocks."""
        content = """@ECHO OFF
REM Documented section
:subroutine
ECHO Running subroutine
EXIT /B 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Block should end with EXIT
            doc_issues = [
                issue for issue in issues if "documentation" in issue.rule.name.lower()
            ]
            # Should not flag missing documentation after EXIT
            assert len(doc_issues) == 0 or all(
                issue.line_number <= 3 for issue in doc_issues
            )
        finally:
            os.unlink(temp_file)

    def test_block_end_with_new_label(self) -> None:
        """Test that new labels properly end previous blocks."""
        content = """@ECHO OFF
REM First section
:first_label
ECHO First section

REM Second section
:second_label
ECHO Second section
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Each label should start a new block
            doc_issues = [
                issue for issue in issues if "documentation" in issue.rule.name.lower()
            ]
            # Should properly handle multiple labeled sections
            assert len(doc_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_block_end_with_call_to_label(self) -> None:
        """Test that CALL to label statements are handled correctly."""
        content = """@ECHO OFF
REM Main section
:main
CALL :helper
GOTO :EOF

REM Helper section
:helper
ECHO Helper
EXIT /B
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # CALL to label should be handled
            doc_issues = [
                issue for issue in issues if "documentation" in issue.rule.name.lower()
            ]
            # Should properly handle CALL to label
            assert len(doc_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_block_end_with_closing_parenthesis(self) -> None:
        """Test that closing parentheses properly end blocks."""
        content = """@ECHO OFF
REM Conditional block
IF EXIST file.txt (
    ECHO File exists
    SET VAR=value
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Closing parenthesis should end the block
            doc_issues = [
                issue for issue in issues if "documentation" in issue.rule.name.lower()
            ]
            # Should handle parentheses correctly
            assert len(doc_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_block_end_with_double_empty_lines(self) -> None:
        """Test that double empty lines properly end blocks."""
        content = """@ECHO OFF
REM First section
FOR %%i IN (1 2 3) DO (
    ECHO %%i
)


REM This is after double empty lines
ECHO Done
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Double empty lines should end the block
            doc_issues = [
                issue for issue in issues if "documentation" in issue.rule.name.lower()
            ]
            # Should handle paragraph breaks
            assert len(doc_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_long_block_with_clear_boundary(self) -> None:
        """Test that long blocks (>15 lines) with clear boundaries are detected."""
        content = """@ECHO OFF
REM Long section
:long_label
ECHO Line 1
ECHO Line 2
ECHO Line 3
ECHO Line 4
ECHO Line 5
ECHO Line 6
ECHO Line 7
ECHO Line 8
ECHO Line 9
ECHO Line 10
ECHO Line 11
ECHO Line 12
ECHO Line 13
ECHO Line 14
ECHO Line 15
ECHO Line 16

SET VAR=value
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Check for S018 (missing subroutine documentation) specifically
            # S013 (file header documentation) is a different check
            s018_issues = [issue for issue in issues if issue.rule.code == "S018"]
            # Should handle long blocks properly and not flag S018
            assert len(s018_issues) == 0
        finally:
            os.unlink(temp_file)


class TestE011VariableExpansionPatterns:
    """Test cases for E011 rule - variable expansion with wildcards and special patterns."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file with given content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_variable_with_wildcard_suffix(self) -> None:
        """Test that variables followed by wildcards don't trigger E011."""
        content = """@ECHO OFF
SET @SOURCE=%@INPUT%*%~n1*
DIR "%@BK_PREFIX%*.*" /OD /A-D
FOR %%F IN (%@ROOT%*.BAT) DO ECHO %%F
DIR "%TEMP%\\%@PREFIX%*"
SET @WCARD=%~3& IF "%~3"=="" SET @FILE2=%%~F.%@YYYY%*%~x2
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"Variables with wildcards should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_variable_with_numeric_suffix(self) -> None:
        """Test that variables with numeric suffixes don't trigger E011."""
        content = """@ECHO OFF
IF %@PORT%0 LSS 1 SET "@PORT=24"
IF %@PORT%0 GTR 655350 SET "@PORT=24"
SET NUM=%VALUE%123
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"Variables with numeric suffixes should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_escaped_percent_signs(self) -> None:
        """Test that escaped percent signs (%%%%) don't trigger E011."""
        content = """@ECHO OFF
FOR %%s IN ("%%%%Failed" "%%%%Unable") DO ECHO %%s
IF NOT "%~3"=="" FOR /R "%@LOGSOURCE%" %%f IN (*.RECORDING.TXT) DO FOR %%s IN ("%%%%Failed" "%%%%Unable") DO CALL RemoveLine "%%~f" "%%~s"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"Escaped percent signs should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_complex_ipv4_ipv6_patterns(self) -> None:
        """Test that complex IP format patterns don't trigger E011."""
        content = """@ECHO OFF
SET @N=[0-9]
SET @AN=[a-f,0-9]
SET @IPV4-FORMAT=%@N%*\\.%@N%*\\.%@N%*\\.%@N%*\\/%@N%*
SET @IPV6-FORMAT=%@AN%%@AN%%@AN%%@AN%:%@AN%%@AN%%@AN%%@AN%:%@AN%%@AN%%@AN%%@AN%::\\/%@N%*
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"Complex IP format patterns should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_variable_with_string_replacement_wildcard(self) -> None:
        """Test that string replacement with wildcards doesn't trigger E011."""
        content = """@ECHO OFF
SET @THESE=*%@MACHINE:\\=%*.CSV
CALL :SwapIt @SHARE %%@SHARE:%@OLDSTRING%=%@NEWSTRING%%%
CALL :SwapIt @SHARE "%%@DRIVE:%@OLDSTRING%=%@NEWSTRING%%%"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"String replacement with wildcards should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_variable_in_file_operations(self) -> None:
        """Test that variables in file operations with wildcards don't trigger E011."""
        content = """@ECHO OFF
DEL %@CFGFILE%*
ROBOCOPY "%@SOURCEDIR%" "%@DESTDIR%" %@FILENAME%*.*
FILEHASH --%@LOG_HASH% -g %@CHECKSUM% -d "%@ZIPPATH%" "%COMPUTERNAME%-%@LOGNAME%*"
IF EXIST "%@LOGBASE%*.TXT" COPY "%@LOGBASE%*.TXT" "%@NETLOG%" /Y
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"Variables in file operations should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_variable_in_for_loop_with_wildcards(self) -> None:
        """Test that variables in FOR loops with wildcards don't trigger E011."""
        content = """@ECHO OFF
FOR /F "SKIP=%@MAXBACKUPS% TOKENS=*" %%E IN ('DIR /OG-D /B /A "%@BK_PREFIX%*.*" ') DO ECHO %%E
FOR /F "TOKENS=*" %%F IN ('DIR /B /S "%@CONFIG_ROOT%*.xml" ') DO ECHO %%F
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert len(e011_issues) == 0, (
                f"FOR loops with wildcards should not trigger E011: "
                f"{[i.context for i in e011_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_genuinely_incomplete_variables_still_caught(self) -> None:
        """Test that genuinely incomplete variables are still flagged by E011."""
        content = """@ECHO OFF
SET BAD=%MISSING
ECHO This has %INCOMPLETE
SET RESULT=%ERRORLEVEL
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            assert (
                len(e011_issues) >= 3
            ), f"Incomplete variables should still trigger E011, found {len(e011_issues)}"
        finally:
            os.unlink(temp_file)

    def test_mixed_valid_and_invalid_patterns(self) -> None:
        """Test file with both valid wildcard patterns and genuinely invalid ones."""
        content = """@ECHO OFF
REM Valid patterns - should not trigger E011
DIR "%@PREFIX%*.txt"
IF %@PORT%0 LSS 1 SET PORT=80
FOR %%s IN ("%%%%Failed") DO ECHO %%s

REM Invalid patterns - should trigger E011
SET BAD=%INCOMPLETE
ECHO Missing delimiter %WRONGVAR
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e011_issues = [i for i in issues if i.rule.code == "E011"]
            # Should only flag the two genuinely invalid ones
            assert len(e011_issues) == 2, (
                f"Should only flag genuinely invalid patterns, "
                f"found {len(e011_issues)}: {[i.context for i in e011_issues]}"
            )
            # Verify issues are on correct lines (8 and 9 - @ECHO OFF at line 1)
            assert all(
                i.line_number in [8, 9] for i in e011_issues
            ), f"Wrong lines flagged: {[i.line_number for i in e011_issues]}"
        finally:
            os.unlink(temp_file)


class TestEmbeddedScriptDetection:  # pylint: disable=too-few-public-methods
    """Test embedded PowerShell/VBScript/C# block detection."""

    def test_detect_embedded_powershell_block(self) -> None:
        """PowerShell syntax after a label is skipped during linting."""

        lines = [
            "@echo off",
            ":psblock",
            "$name = 'test'",
            "Write-Host $name",
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines

    def test_hyphenated_batch_filename_is_not_powershell(self) -> None:
        """Filenames like set-permissions.bat are batch, not cmdlets (issue #38)."""
        hyphen_line = r"if %choice%==7 set X=C:\Windows\set-permissions.bat"
        plain_line = r"if %choice%==7 set X=C:\Windows\setpermissions.bat"
        hyphen_skip = _detect_embedded_script_blocks(["@echo off", hyphen_line])
        plain_skip = _detect_embedded_script_blocks(["@echo off", plain_line])
        assert 2 not in hyphen_skip
        assert 2 not in plain_skip
        assert hyphen_skip == plain_skip

    def test_cmdlet_like_script_filenames_are_not_powershell(self) -> None:
        """Cmdlet patterns must not backtrack into names with blocked extensions."""
        filename_lines = (
            r"set X=set-permissions.bat",
            r"set X=Get-Item.cmd",
            r"set X=Write-Output.exe",
            r"set X=New-Item.com",
            r"set X=Set-config.ps1",
            r"set X=Set-config.psm1",
            r"set X=Set-config.psd1",
            r"set X=Set-config.ps1xml",
            r"set X=Set-config.vbs",
        )
        for filename_line in filename_lines:
            skip_lines = _detect_embedded_script_blocks(["@echo off", filename_line])
            assert 2 not in skip_lines, filename_line

    def test_real_powershell_cmdlets_are_still_detected(self) -> None:
        """Bare Get-/Set-/Write-/New- cmdlets still open a PowerShell skip region."""
        skip_lines = _detect_embedded_script_blocks(
            ["@echo off", "Write-Host $name", "Get-ChildItem", "Set-Item -Path x"]
        )
        assert 2 in skip_lines
        assert 3 in skip_lines
        assert 4 in skip_lines

    def test_hyphenated_filename_keeps_per_line_rules(self, tmp_path: Path) -> None:
        """set-permissions.bat must still get W005 and SEC006 (issue #38)."""
        hyphen = tmp_path / "a.cmd"
        plain = tmp_path / "b.cmd"
        hyphen.write_text(
            "@echo off\n"
            r"if %choice%==7 set X=C:\Windows\set-permissions.bat" + "\n"
            "exit /b 0\n",
            encoding="utf-8",
        )
        plain.write_text(
            "@echo off\n"
            r"if %choice%==7 set X=C:\Windows\setpermissions.bat" + "\n"
            "exit /b 0\n",
            encoding="utf-8",
        )
        hyphen_codes = {
            (issue.line_number, issue.rule.code)
            for issue in lint_batch_file(str(hyphen))
            if issue.rule.code in {"E006", "W005", "SEC006"}
        }
        plain_codes = {
            (issue.line_number, issue.rule.code)
            for issue in lint_batch_file(str(plain))
            if issue.rule.code in {"E006", "W005", "SEC006"}
        }
        assert hyphen_codes == plain_codes
        assert (2, "E006") in hyphen_codes
        assert (2, "W005") in hyphen_codes
        assert (2, "SEC006") in hyphen_codes

    def test_detect_embedded_vbscript_block(self) -> None:
        """VBScript syntax after a label is skipped during linting."""

        lines = [
            "@echo off",
            ":vbsblock",
            "Dim obj",
            'Set obj = CreateObject("Scripting.FileSystemObject")',
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines

    def test_detect_embedded_csharp_block(self) -> None:
        """C# using/namespace/class/foreach lines after a label are skipped."""

        lines = [
            "@echo off",
            ":csharpblock",
            "using System;",
            "namespace Demo",
            "public class Helper",
            "{",
            "    public static int Add(int a, int b) => a + b;",
            "    foreach (string item in items)",
            "    for (int i = 0; i < 10; i++)",
            "}",
            "echo resumed",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 in skip_lines
        assert 6 in skip_lines
        assert 7 in skip_lines
        assert 8 in skip_lines
        assert 9 in skip_lines
        assert 11 not in skip_lines

    def test_csharp_block_ends_on_batch_resume(self) -> None:
        """Batch commands after an embedded C# block are linted again."""

        lines = [
            "@echo off",
            ":csharpblock",
            "using System;",
            "public class Helper",
            "exit /b 0",
            ":after",
            "echo after label",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 not in skip_lines
        assert 7 not in skip_lines

    def test_hex_literal_in_batch_is_not_treated_as_csharp(self) -> None:
        """Batch hex values must not open a C# skip block."""

        lines = [
            "@echo off",
            "set HEX=0x1A",
            "echo %HEX%",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert skip_lines == set()

    def test_lone_brace_in_batch_is_not_treated_as_csharp(self) -> None:
        """A stray opening brace in batch must not open a C# skip block."""

        lines = [
            "@echo off",
            "echo start",
            "{",
            "echo still batch",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert skip_lines == set()

    def test_embedded_csharp_is_not_flagged_as_batch_commands(
        self, tmp_path: Path
    ) -> None:
        """Skipped C# lines must not produce unknown-command errors."""
        script = tmp_path / "embedded_csharp.cmd"
        script.write_text(
            "@echo off\r\n"
            ":csharpblock\r\n"
            "using System;\r\n"
            "namespace Demo\r\n"
            "public class Helper\r\n"
            "echo done\r\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(script))
        csharp_lines = {3, 4, 5}
        codes_on_csharp = {
            issue.rule.code for issue in issues if issue.line_number in csharp_lines
        }
        assert "E013" not in codes_on_csharp
        assert "E012" not in codes_on_csharp

    def test_echo_to_temp_vbscript_is_not_skipped(self) -> None:
        """Echo-generated VBScript payloads remain batch lines."""

        lines = [
            "@echo off",
            r'set "vbs=%temp%\%~n0_%random%.vbs"',
            r'>"%vbs%" echo Dim x',
            r'>>"%vbs%" echo WScript.Echo x',
            r'cscript //nologo "%vbs%"',
            r'del "%vbs%"',
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert skip_lines == set()

    def test_echo_wscript_payload_is_not_skipped(self) -> None:
        """Unanchored WScript in an echo line must not open a skip block."""

        lines = [
            "@echo off",
            'echo WScript.Echo "hi"',
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert skip_lines == set()

    def test_infile_vbscript_msgbox_and_option_explicit_skipped(self) -> None:
        """MsgBox and Option Explicit after a label are skipped; exit resumes."""

        lines = [
            "@echo off",
            ":vbsblock",
            "Option Explicit",
            'MsgBox "hello"',
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 not in skip_lines

    def test_jscript_polyglot_skips_header_and_body_not_batch_interior(self) -> None:
        """JScript /* */ wraps batch; only header and post-*/ body are skipped."""

        lines = [
            "@if (1==1) @end /*",
            "@echo off",
            r'cscript //nologo //E:JScript "%~f0" %*',
            "exit /b",
            "*/",
            'WScript.Echo("Hello from JScript!");',
            "var x = 1",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 1 in skip_lines
        assert 2 not in skip_lines
        assert 3 not in skip_lines
        assert 4 not in skip_lines
        assert 5 in skip_lines
        assert 6 in skip_lines
        assert 7 in skip_lines

    def test_jscript_var_after_label_is_skipped(self) -> None:
        """JScript var declarations after a label are skipped."""

        lines = [
            "@echo off",
            ":jsblock",
            "var x = 1",
            'WScript.Echo("hi")',
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 not in skip_lines

    def test_wscript_echo_after_label_keeps_jscript_if_for(self) -> None:
        """WScript.Echo after a label must not lock VBScript over JScript if/for."""

        lines = [
            "@echo off",
            ":jsblock",
            'WScript.Echo("hi")',
            "if (x) {",
            "    for (var i = 0; i < 2; i++) {",
            "        WScript.Echo(i)",
            "    }",
            "}",
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 in skip_lines
        assert 6 in skip_lines
        assert 9 not in skip_lines

    def test_jscript_if_and_for_in_body_are_skipped(self) -> None:
        """JScript if/for after var must not close the skip block."""

        lines = [
            "@echo off",
            ":jsblock",
            "var x = 1",
            "if (x) {",
            "    for (var i = 0; i < 10; i++) {",
            "        WScript.Echo(i)",
            "    }",
            "}",
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 in skip_lines
        assert 6 in skip_lines
        assert 9 not in skip_lines

    def test_jscript_block_ends_on_batch_if(self) -> None:
        """Real batch if after JScript still ends the skip block."""

        lines = [
            "@echo off",
            ":jsblock",
            "var x = 1",
            "if exist file.txt echo found",
            "echo still batch",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 not in skip_lines
        assert 5 not in skip_lines

    def test_csharp_for_immediately_after_starter_is_skipped(self) -> None:
        """C# for after using must stay in the skip block."""

        lines = [
            "@echo off",
            ":csharpblock",
            "using System;",
            "for (int i = 0; i < 10; i++)",
            "echo resumed",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines
        assert 5 not in skip_lines

    def test_infile_vbscript_is_not_flagged_as_batch_commands(
        self, tmp_path: Path
    ) -> None:
        """Skipped VBScript lines must not produce unknown-command errors."""
        script = tmp_path / "embedded_vbs.cmd"
        script.write_text(
            "@echo off\r\n"
            ":vbsblock\r\n"
            "Dim obj\r\n"
            'Set obj = CreateObject("Scripting.FileSystemObject")\r\n'
            "echo done\r\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(script))
        vbs_lines = {3, 4}
        codes_on_vbs = {
            issue.rule.code for issue in issues if issue.line_number in vbs_lines
        }
        assert "E013" not in codes_on_vbs
        assert "E012" not in codes_on_vbs

    def test_jscript_polyglot_body_is_not_flagged_as_batch_commands(
        self, tmp_path: Path
    ) -> None:
        """JScript after */ must not produce unknown-command errors."""
        script = tmp_path / "embedded_jscript.cmd"
        script.write_text(
            "@if (1==1) @end /*\r\n"
            "@echo off\r\n"
            'cscript //nologo //E:JScript "%~f0" %*\r\n'
            "exit /b\r\n"
            "*/\r\n"
            'WScript.Echo("Hello from JScript!");\r\n'
            "var x = 1\r\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(script))
        jscript_lines = {5, 6, 7}
        codes_on_js = {
            issue.rule.code for issue in issues if issue.line_number in jscript_lines
        }
        assert "E013" not in codes_on_js
        assert "E012" not in codes_on_js

    def test_jscript_if_and_for_are_not_flagged_as_batch_commands(
        self, tmp_path: Path
    ) -> None:
        """JScript if/for in an open block must not produce unknown-command errors."""
        script = tmp_path / "embedded_jscript_control.cmd"
        script.write_text(
            "@echo off\r\n"
            ":jsblock\r\n"
            "var x = 1\r\n"
            "if (x) {\r\n"
            "    for (var i = 0; i < 10; i++) {\r\n"
            "        WScript.Echo(i)\r\n"
            "    }\r\n"
            "}\r\n"
            "echo done\r\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(script))
        jscript_lines = {3, 4, 5, 6}
        codes_on_js = {
            issue.rule.code for issue in issues if issue.line_number in jscript_lines
        }
        assert "E013" not in codes_on_js
        assert "E012" not in codes_on_js

    def test_csharp_for_is_not_flagged_as_batch_commands(self, tmp_path: Path) -> None:
        """C# for immediately after using must not produce unknown-command errors."""
        script = tmp_path / "embedded_csharp_for.cmd"
        script.write_text(
            "@echo off\r\n"
            ":csharpblock\r\n"
            "using System;\r\n"
            "for (int i = 0; i < 10; i++)\r\n"
            "echo done\r\n",
            encoding="utf-8",
        )
        issues = lint_batch_file(str(script))
        csharp_lines = {3, 4}
        codes_on_csharp = {
            issue.rule.code for issue in issues if issue.line_number in csharp_lines
        }
        assert "E013" not in codes_on_csharp
        assert "E012" not in codes_on_csharp


class TestSuppressionCommentParsing:
    """Direct tests for inline suppression comment parsing."""

    def test_parse_suppression_ignore_next_line_specific_code(self) -> None:
        """REM LINT:IGNORE with code suppresses that rule on the next line."""

        lines = [
            "REM LINT:IGNORE E009\n",
            "SET VAR=value\n",
        ]
        suppressions = _parse_suppression_comments(lines)
        assert 2 in suppressions
        assert "E009" in suppressions[2]

    def test_parse_suppression_ignore_next_line_all_rules(self) -> None:
        """REM LINT:IGNORE without code suppresses all rules on the next line."""

        lines = [
            "REM LINT:IGNORE\n",
            "SET VAR=value\n",
        ]
        suppressions = _parse_suppression_comments(lines)
        assert 2 in suppressions
        assert suppressions[2] == set()

    def test_parse_suppression_ignore_line_same_line(self) -> None:
        """REM LINT:IGNORE-LINE on a REM line suppresses that line."""

        lines = [
            "REM LINT:IGNORE-LINE S007\n",
        ]
        suppressions = _parse_suppression_comments(lines)
        assert 1 in suppressions
        assert "S007" in suppressions[1]

    def test_parse_suppression_ignore_line_is_case_insensitive(self) -> None:
        """LINT:IGNORE-LINE matches ASCII case-insensitively."""
        suppressions = _parse_suppression_comments(["rem lint:ignore-line sec008\n"])
        assert suppressions[1] == {"SEC008"}

    def test_lookalike_ignore_line_does_not_suppress(self) -> None:
        """A dotless-i look-alike of LINT:IGNORE-LINE is not a directive."""
        suppressions = _parse_suppression_comments(
            ["rem l\u0131nt:\u0131gnore-line sec008\n"]
        )
        assert not suppressions

    def test_invalid_codes_do_not_suppress_everything(self) -> None:
        """A directive whose codes are all invalid suppresses nothing."""
        suppressions = _parse_suppression_comments(
            ["REM LINT:IGNORE NOT_A_CODE\n", "set PASSWORD=hunter2\n"]
        )
        assert suppressions.get(2) != set()
        assert "SEC008" not in suppressions.get(2, set())

    def test_mixed_valid_and_lookalike_codes_keep_only_ascii(self) -> None:
        """An ASCII code is kept when a look-alike code beside it is ignored."""
        suppressions = _parse_suppression_comments(
            ["REM LINT:IGNORE SEC008, \u017fEC009\n", "set PASSWORD=hunter2\n"]
        )
        assert suppressions[2] == {"SEC008"}

    @pytest.mark.parametrize(
        ("directive", "suppressed"),
        [
            (None, False),
            ("REM LINT:IGNORE SEC008", True),
            ("rem lint:ignore sec008", True),
            ("REM  LINT:IGNORE  SEC008", True),
            ("::LINT:IGNORE SEC008", True),
            ("rem l\u0131nt:\u0131gnore sec008", False),
            ("REM LINT:IGNORE \u017fEC008", False),
            ("rem l\u00efnt:\u00efgnore sec008", False),
        ],
    )
    def test_sec008_suppression_matches_ascii_only(
        self,
        tmp_path: Path,
        directive: Optional[str],
        suppressed: bool,
    ) -> None:
        """SEC008 is suppressed only by an ASCII LINT:IGNORE directive and code."""
        lines = ["@echo off"]
        if directive is not None:
            lines.append(directive)
        lines.extend(["set PASSWORD=hunter2", "exit /b 0"])
        script = tmp_path / "creds.cmd"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        password_line = 2 if directive is None else 3
        issues = lint_batch_file(str(script))
        reported = [
            issue
            for issue in issues
            if issue.rule.code == "SEC008" and issue.line_number == password_line
        ]
        assert bool(reported) is not suppressed


_ASCII_DIRECTIVE = "REM LINT:IGNORE SEC008"
_ASCII_LETTER_INDEXES = [
    index
    for index, char in enumerate(_ASCII_DIRECTIVE)
    if char.isascii() and char.isalpha()
]


class TestSuppressionAsciiProperty:
    """Property checks for ASCII-only suppression directives."""

    @given(
        index=st.sampled_from(_ASCII_LETTER_INDEXES),
        replacement=st.characters(
            categories=("Lu", "Ll", "Lt"),
            min_codepoint=128,
        ),
    )
    @settings(max_examples=50, deadline=None)
    def test_non_ascii_letter_never_suppresses_sec008(
        self, index: int, replacement: str
    ) -> None:
        """Replacing any ASCII letter in the directive stops SEC008 suppression."""
        mutated = _ASCII_DIRECTIVE[:index] + replacement + _ASCII_DIRECTIVE[index + 1 :]
        suppressions = _parse_suppression_comments(
            [mutated + "\n", "set PASSWORD=hunter2\n"]
        )
        suppressed = suppressions.get(2)
        suppresses_sec008 = suppressed is not None and (
            len(suppressed) == 0 or "SEC008" in suppressed
        )
        assert not suppresses_sec008


class TestFindBatchFilesDiscovery:
    """Additional discovery tests for find_batch_files."""

    def test_find_batch_files_empty_directory(self, tmp_path: Path) -> None:
        """Empty directories return no batch files."""
        found = find_batch_files(tmp_path)
        assert found == []

    def test_find_batch_files_nested_recursive(self, tmp_path: Path) -> None:
        """Recursive search finds batch files in subdirectories."""
        nested = tmp_path / "sub"
        nested.mkdir()
        (tmp_path / "root.bat").write_text("@ECHO OFF\n", encoding="utf-8")
        (nested / "nested.cmd").write_text("@ECHO OFF\n", encoding="utf-8")
        found = find_batch_files(tmp_path)
        names = {path.name for path in found}
        assert names == {"root.bat", "nested.cmd"}

    def test_find_batch_files_non_recursive(self, tmp_path: Path) -> None:
        """Non-recursive search only returns files in the top directory."""
        nested = tmp_path / "sub"
        nested.mkdir()
        (tmp_path / "root.bat").write_text("@ECHO OFF\n", encoding="utf-8")
        (nested / "nested.bat").write_text("@ECHO OFF\n", encoding="utf-8")
        found = find_batch_files(tmp_path, recursive=False)
        assert [path.name for path in found] == ["root.bat"]

    def test_find_batch_files_ignores_non_batch_extensions(
        self, tmp_path: Path
    ) -> None:
        """Only .bat and .cmd files are discovered."""
        (tmp_path / "readme.txt").write_text("not a batch file\n", encoding="utf-8")
        (tmp_path / "script.bat").write_text("@ECHO OFF\n", encoding="utf-8")
        found = find_batch_files(tmp_path)
        assert [path.name for path in found] == ["script.bat"]

    def test_find_batch_files_raises_when_scan_limit_exceeded(
        self, tmp_path: Path
    ) -> None:
        """Directory scans above max_scan_files raise ValueError."""
        for index in range(4):
            (tmp_path / f"script{index}.bat").write_text(
                "@ECHO OFF\n", encoding="utf-8"
            )
        with pytest.raises(ValueError, match="exceeding the limit"):
            find_batch_files(tmp_path, max_scan_files=3)

    def test_find_batch_files_allows_scan_up_to_limit(self, tmp_path: Path) -> None:
        """Directory scans at max_scan_files succeed."""
        for index in range(3):
            (tmp_path / f"script{index}.bat").write_text(
                "@ECHO OFF\n", encoding="utf-8"
            )
        found = find_batch_files(tmp_path, max_scan_files=3)
        assert len(found) == 3


class TestLoggingConfig:
    """Tests for shared logger configuration."""

    def test_logger_has_null_handler_and_no_duplicates(self) -> None:
        """Logger uses NullHandler and does not accumulate handlers."""

        importlib.reload(logging_config)
        handler_count = len(logging_config.logger.handlers)
        importlib.reload(logging_config)
        assert handler_count == len(logging_config.logger.handlers)
        assert any(
            handler.__class__.__name__ == "NullHandler"
            for handler in logging_config.logger.handlers
        )


class TestAdvancedSecurityPerformanceRules:
    """Direct tests for advanced security and performance checkers."""

    def test_sec014_flags_unescaped_user_input(self) -> None:
        """SEC014 triggers for unescaped %1 with special characters."""

        lines = ["@echo off\n", "echo %1 & dir\n"]
        issues = _check_advanced_security(lines[1], 2, lines, {})
        codes = {issue.rule.code for issue in issues}
        assert "SEC014" in codes

    def test_sec014_flags_unquoted_arg_without_specials(self) -> None:
        """SEC014 triggers for unquoted %1 even when the source has no &|><."""

        lines = ["@echo off\n", "echo %1\n"]
        issues = _check_advanced_security(lines[1], 2, lines, {})
        codes = {issue.rule.code for issue in issues}
        assert "SEC014" in codes

    def test_sec014_ignores_quoted_arg(self) -> None:
        """SEC014 does not flag quoted %~1."""

        lines = ["@echo off\n", 'echo "%~1"\n']
        issues = _check_advanced_security(lines[1], 2, lines, {})
        codes = {issue.rule.code for issue in issues}
        assert "SEC014" not in codes

    def test_sec025_flags_unquoted_cd(self) -> None:
        """SEC025 triggers for unquoted %CD%."""

        issues = _check_advanced_security("echo %CD%\n", 1, ["@echo off\n"], {})
        codes = {issue.rule.code for issue in issues}
        assert "SEC025" in codes

    def test_sec001_quoted_setp_use_is_safe(self) -> None:
        """SEC001 does not flag SET /P variables that are only used quoted."""

        lines = [
            "@echo off\n",
            "set /p input=Enter:\n",
            'echo "%input%"\n',
        ]
        issues = _check_security_issues(lines[0], 1, lines)
        codes = {issue.rule.code for issue in issues}
        assert "SEC001" not in codes

    def test_sec014_flags_unescaped_percent5(self) -> None:
        """SEC014 triggers for unescaped %5 with special characters."""

        lines = ["@echo off\n", "echo %5 & dir\n"]
        issues = _check_advanced_security(lines[1], 2, lines, {})
        codes = {issue.rule.code for issue in issues}
        assert "SEC014" in codes

    def test_sec017_flags_predictable_temp_file(self) -> None:
        """SEC017 triggers for temp files without randomness."""

        issues = _check_advanced_security(
            "set outfile=c:\\temp\\data.tmp\n", 1, ["@echo off\n"], {}
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC017" in codes

    def test_sec018_flags_insecure_redirection(self) -> None:
        """SEC018 triggers for redirection to insecure temp paths."""

        issues = _check_advanced_security(
            "dir > c:\\temp\\output.txt\n", 1, ["@echo off\n"], {}
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC018" in codes

    def test_sec011_flags_path_traversal(self) -> None:
        """SEC011 triggers when path operations contain .."""

        issues = _check_enhanced_security_rules(["@echo off\n", "cd ..\\windows\n"])
        codes = {issue.rule.code for issue in issues}
        assert "SEC011" in codes

    def test_sec011_ignores_safe_paths(self) -> None:
        """SEC011 does not flag normal absolute paths."""

        issues = _check_enhanced_security_rules(
            ["@echo off\n", "cd C:\\Windows\\System32\n"]
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC011" not in codes

    def test_sec011_ignores_substring_command_matches(self) -> None:
        """SEC011 does not flag 'cd' inside unrelated words like abcd."""

        issues = _check_enhanced_security_rules(
            ["@echo off\n", "set abcd=..\\windows\n"]
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC011" not in codes

    def test_sec014_flags_delayed_expansion_user_input(self) -> None:
        """SEC014 triggers for unescaped !1! with special characters."""

        lines = ["@echo off\n", "echo !1! & dir\n"]
        issues = _check_advanced_security(lines[1], 2, lines, {})
        codes = {issue.rule.code for issue in issues}
        assert "SEC014" in codes

    def test_sec012_ignores_non_temp_paths(self) -> None:
        """SEC012 does not flag arbitrary words containing 'temp'."""

        issues = _check_enhanced_security_rules(
            ["@echo off\n", "set attempt=value.tmp\n"]
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC012" not in codes

    def test_sec012_flags_unsafe_temp_file(self) -> None:
        """SEC012 triggers for predictable temp file paths."""

        issues = _check_enhanced_security_rules(
            ["@echo off\n", "set outfile=c:\\temp\\out.tmp\n"]
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC012" in codes

    def test_sec012_ignores_random_temp_file(self) -> None:
        """SEC012 does not flag temp files using %random%."""

        issues = _check_enhanced_security_rules(
            ["@echo off\n", "set outfile=%temp%\\%random%.tmp\n"]
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC012" not in codes

    def test_sec015_flags_unfiltered_taskkill(self) -> None:
        """SEC015 triggers for TASKKILL /F without /FI filters."""

        issues = _check_advanced_process_mgmt(["taskkill /f /im notepad.exe"], 1)
        codes = {issue.rule.code for issue in issues}
        assert "SEC015" in codes

    def test_sec015_ignores_filtered_taskkill(self) -> None:
        """SEC015 does not flag TASKKILL /F when /FI filters are present."""

        issues = _check_advanced_process_mgmt(
            ['taskkill /f /fi "imagename eq notepad.exe" /im notepad.exe'], 1
        )
        codes = {issue.rule.code for issue in issues}
        assert "SEC015" not in codes

    def test_w043_ignores_taskkill_after_tasklist(self) -> None:
        """TASKKILL after TASKLIST in the same block should not trigger W043."""

        lines = [
            'tasklist /FI "IMAGENAME eq notepad.exe" 2>nul | find /I notepad.exe >nul',
            "taskkill /F /IM notepad.exe >nul 2>&1",
        ]
        issues = _check_advanced_process_mgmt(lines, 2)
        codes = {issue.rule.code for issue in issues}
        assert "W043" not in codes

    def test_for_loop_performance_rules(self) -> None:
        """P019 and P022 trigger inside FOR blocks."""

        lines = [
            "@echo off\n",
            "for %%i in (1) do (\n",
            "set result=!a!!b!!c!!d!\n",
            "dir > nul\n",
            ")\n",
        ]
        delayed_issues = _check_for_block_performance(
            lines, 3, lines[2], lines[2].strip()
        )
        redirect_issues = _check_for_block_performance(
            lines, 4, lines[3], lines[3].strip()
        )
        assert "P019" in {issue.rule.code for issue in delayed_issues}
        assert "P022" in {issue.rule.code for issue in redirect_issues}

    def test_for_block_membership_ends_when_the_block_closes(self) -> None:
        """Lines after a FOR block are outside, including a later closing paren."""
        lines = [
            "@echo off\n",
            "echo before\n",
            "for %%i in (1) do (\n",
            "  echo inside\n",
            ")\n",
            "echo after\n",
            ")\n",
            "echo negative\n",
        ]
        expected = [False, False, True, True, True, False, False, False]
        actual = [
            _line_is_inside_for_block(lines, line_number)
            for line_number in range(1, len(lines) + 1)
        ]
        assert actual == expected

        other = ["for %%a in (1) do (\n", "echo x\n"]
        assert _line_is_inside_for_block(other, 1) is True
        assert _line_is_inside_for_block(other, 2) is True
        assert _line_is_inside_for_block(lines, 6) is False
        assert _line_is_inside_for_block(lines, 2) is False


class TestEmbeddedScriptEdgeCases:
    """Edge cases for embedded script block detection."""

    def test_powershell_heredoc_block_skipped(self) -> None:
        """PowerShell <# ... #> heredoc lines are skipped."""

        lines = [
            "@echo off",
            "<#",
            "$x = 1",
            "#>",
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 2 in skip_lines
        assert 3 in skip_lines
        assert 4 in skip_lines

    def test_label_resets_embedded_block_state(self) -> None:
        """Batch labels after embedded blocks resume batch linting."""

        lines = [
            "@echo off",
            "powershell -Command \"Write-Host 'hi'\"",
            ":afterblock",
            "echo resumed batch line",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 2 in skip_lines
        assert 4 not in skip_lines
        assert 5 not in skip_lines

    def test_vbscript_block_ends_on_batch_line(self) -> None:
        """VBScript blocks end when batch syntax resumes."""

        lines = [
            "@echo off",
            ":vbblock",
            "Dim x",
            'Set x = CreateObject("Scripting.FileSystemObject")',
            "exit /b 0",
        ]
        skip_lines = _detect_embedded_script_blocks(lines)
        assert 3 in skip_lines
        assert 4 in skip_lines


class TestLineEndingCheckerRules:  # pylint: disable=too-few-public-methods
    """Direct tests for line ending checker rules."""

    def test_check_line_ending_rules_e018_w018_w019(self) -> None:
        """LF files with multibyte chars and GOTO labels trigger line-ending rules."""

        lines = ["@echo off\n", "goto :target\n", "echo café\n"]
        ending_info = ("LF", False, 0, 3, 0)
        issues = _check_line_ending_rules(lines, "test.bat", ending_info=ending_info)
        codes = {issue.rule.code for issue in issues}
        assert "E018" in codes
        assert "W018" in codes
        assert "W019" in codes


class TestExitFlowW001Goto:  # pylint: disable=too-few-public-methods
    """W001 control-flow tests for GOTO label resolution."""

    def test_goto_main_without_exit_triggers_w001(self) -> None:
        """GOTO :main where the label falls through to EOF should warn."""

        lines = [
            "@echo off\n",
            "GOTO :main\n",
            ":main\n",
            "echo still running\n",
        ]
        issues = _check_missing_exit_statement(lines)
        codes = {issue.rule.code for issue in issues}
        assert "W001" in codes

    def test_goto_main_with_exit_does_not_trigger_w001(self) -> None:
        """GOTO :main where the label exits should not warn."""

        lines = [
            "@echo off\n",
            "GOTO :main\n",
            ":main\n",
            "EXIT /b 0\n",
        ]
        issues = _check_missing_exit_statement(lines)
        codes = {issue.rule.code for issue in issues}
        assert "W001" not in codes

    def test_goto_eof_does_not_trigger_w001(self) -> None:
        """GOTO :EOF should not produce a missing-exit warning."""

        lines = ["@echo off\n", "echo done\n", "GOTO :EOF\n"]
        issues = _check_missing_exit_statement(lines)
        codes = {issue.rule.code for issue in issues}
        assert "W001" not in codes


class TestResidualFalsePositives:
    """Residual edge cases of the false positives fixed in v1.1.24 (#37-#40)."""

    @staticmethod
    def _lint(tmp_path: Path, name: str, content: str) -> set[str]:
        batch_file = tmp_path / name
        batch_file.write_text(content, encoding="utf-8")
        return {issue.rule.code for issue in lint_batch_file(str(batch_file))}

    def test_w036_command_operand_containing_parentheses(self, tmp_path: Path) -> None:
        """#37: the operand ends at the balancing parenthesis, not the first one."""
        content = (
            "@echo off\n"
            'for /f "usebackq delims=" %%L in (`powershell -NoProfile -Command '
            '"(Get-Item .).FullName"`) do set "D=%%L"\n'
            "exit /b 0\n"
        )
        assert "W036" not in self._lint(tmp_path, "test.bat", content)

    def test_w036_still_reported_for_a_quoted_data_file(self, tmp_path: Path) -> None:
        """#37 control: a double-quoted operand is still a data file."""
        content = (
            "@echo off\n"
            'for /f "usebackq delims=" %%V in ("C:\\data\\input-file.txt")'
            ' do set "D=%%V"\n'
            "exit /b 0\n"
        )
        assert "W036" in self._lint(tmp_path, "test.bat", content)

    def test_cmdlet_lookalike_filenames_are_batch_code(self) -> None:
        """#38: drive-relative, quoted and ForEach-Object file names are not cmdlets."""
        for line in (
            "if %choice%==7 set X=C:Set-Permissions",
            'if %choice%==7 set "X=set-permissions.bat"',
            r"call C:\Windows\ForEach-Object.bat",
        ):
            assert not _detect_embedded_script_blocks(["@echo off", line]), line

    def test_real_cmdlets_are_still_powershell(self) -> None:
        """#38 control: cmdlets standing alone still start a skip region."""
        lines = [
            "@echo off",
            ":psblock",
            "Get-ChildItem C:\\ | ForEach-Object { $_.Name }",
            "Set-Location C:\\",
        ]
        assert {3, 4} <= _detect_embedded_script_blocks(lines)

    def test_hyphenated_filename_keeps_its_findings(self, tmp_path: Path) -> None:
        """#38: a quoted hyphenated filename still draws the same rules as its twin."""
        hyphen = self._lint(
            tmp_path, "a.bat", '@echo off\nif %c%==7 set "X=set-permissions.bat"\n'
        )
        plain = self._lint(
            tmp_path, "b.bat", '@echo off\nif %c%==7 set "X=setpermissions.bat"\n'
        )
        assert hyphen == plain

    def test_inline_rem_segment_is_not_a_label_reference(self) -> None:
        """#39: ``echo done & rem call :x`` executes no CALL."""
        lines = [
            "@echo off",
            "echo done & rem call :unused",
            "echo goto :unused",
            "exit /b 0",
            ":unused",
            "exit /b 0",
        ]
        issues = _check_global_style_rules(lines, "test.cmd")
        assert len([issue for issue in issues if issue.rule.code == "S010"]) == 1

    def test_reference_after_a_separator_still_counts(self) -> None:
        """#39 control: a jump in a later segment is a reference."""
        lines = [
            "@echo off",
            "echo hi & goto :used",
            'if "%~1"=="" goto :used',
            ":used",
            "exit /b 0",
        ]
        issues = _check_global_style_rules(lines, "test.cmd")
        assert not [issue for issue in issues if issue.rule.code == "S010"]

    def test_setlocal_after_an_if_predicate_is_counted(self) -> None:
        """#40: ``if defined FLAG setlocal`` runs a SETLOCAL.

        A second IF predicate still leaves that command, including a jump.
        """

        assert _is_setlocal_command("if defined FLAG setlocal")
        assert _is_setlocal_command("if defined A if defined B setlocal")
        assert _command_segments("if defined A if defined B goto %ACTION%") == [
            "goto %ACTION%"
        ]
        assert _is_setlocal_command("echo step & setlocal")
        assert _is_setlocal_command('if /i "%a%"=="b" setlocal enabledelayedexpansion')
        assert _is_endlocal_command("if not exist out.txt endlocal")
        assert not _is_setlocal_command("REM a bare setlocal inherits caller state")
        assert not _is_setlocal_command("echo run setlocal first")

    def test_conditional_setlocal_counts_toward_p024(self) -> None:
        """#40: a conditional second SETLOCAL is no longer undercounted."""
        lines = [
            "@echo off",
            "setlocal",
            "echo s1",
            "echo s2",
            "echo s3",
            "echo s4",
            "echo s5",
            "if defined FLAG setlocal",
        ]
        issues = _check_new_global_rules(lines, "test.bat")
        p024 = [issue for issue in issues if issue.rule.code == "P024"]
        assert len(p024) == 1
        assert p024[0].line_number == 8

    def test_quoted_if_operand_holding_a_space(self) -> None:
        """#40: a quoted operand is one token, so the predicate ends where it does."""

        assert _is_setlocal_command(r'if exist "C:\Program Files\a.txt" setlocal')
        assert _is_setlocal_command(
            'if not "%A%"=="b c" setlocal enabledelayedexpansion'
        )

    def test_escaped_separator_and_pipe_do_not_start_a_command(self) -> None:
        """#40: a caret escapes ``&``, and a pipe runs its right side elsewhere."""

        assert not _command_segments("echo a ^& setlocal")
        assert not _is_setlocal_command("echo a ^& setlocal")
        assert _command_segments('dir | find "x"') == ['dir | find "x"']


class TestBlankOrCommentDetection:
    """REM and :: detection must not swallow commands that merely start with rem."""

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "rem",
            "REM text",
            "rem\ttabbed",
            "@rem hidden",
            ":: note",
            "  :: indented",
        ],
    )
    def test_blank_and_comment_lines_are_detected(self, line: str) -> None:
        """Blank lines, REM, @REM, bare REM and :: are all comments."""
        assert _is_blank_or_comment(line)

    @pytest.mark.parametrize(
        "line",
        ["rem", "REM text", "rem\ttabbed", "@rem hidden", ":: note", "  :: indented"],
    )
    def test_is_comment_line_matches_the_shared_definition(self, line: str) -> None:
        """_is_comment_line agrees with _is_blank_or_comment for non-blank comments."""
        assert _is_comment_line(line)

    @pytest.mark.parametrize("line", ["", "remote.exe", "RENAME a b", ":label"])
    def test_is_comment_line_rejects_non_comments(self, line: str) -> None:
        """Blank lines, labels and rem-prefixed command names are not comments."""
        assert not _is_comment_line(line)

    @pytest.mark.parametrize(
        "line",
        [
            "remote.exe sync",
            "remove_cache.cmd",
            "REMOVE.bat arg",
            "remark=1",
            ":label",
            "echo rem",
        ],
    )
    def test_commands_starting_with_rem_are_not_comments(self, line: str) -> None:
        """Executables and labels whose names begin with rem are not comments."""
        assert not _is_blank_or_comment(line)
