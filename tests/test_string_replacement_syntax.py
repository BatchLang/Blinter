"""
Test cases for batch string replacement syntax detection.

These tests validate that the linter correctly handles string replacement syntax
in both delayed expansion (!VAR:"=!) and percent-style (%VAR:"=%) formats,
which were previously incorrectly flagged as mismatched quotes (E009).

Tests added based on real-world batch script analysis from batch-script-examples folder.
"""

from pathlib import Path
from typing import List

from blinter import (
    LintIssue,
    lint_batch_file,
)


class TestStringReplacementSyntax:
    """Test that string replacement syntax is not incorrectly flagged as E009."""

    # pylint: disable=invalid-name  # Test method names are descriptive
    def test_delayed_expansion_string_replacement_remove_quotes(
        self, tmp_path: Path
    ) -> None:
        """Test !VAR:"=! syntax (remove quotes from variable)."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            'SET VAR="test value"\n'
            'SET VAR=!VAR:"=!\n'
            "echo !VAR!\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), f'E009 should not be triggered for !VAR:"=! syntax, but found: {e009_issues}'

    def test_delayed_expansion_string_replacement_with_text(
        self, tmp_path: Path
    ) -> None:
        """Test !VAR:searchString=replaceString! syntax with quotes."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "SET PATH_VAR=C:\\Program Files\\App\n"
            'SET PATH_VAR=!PATH_VAR:" "=_!\n'
            "echo !PATH_VAR!\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "E009 should not be triggered for string replacement with quotes"

    def test_percent_style_string_replacement_remove_quotes(
        self, tmp_path: Path
    ) -> None:
        """Test %VAR:"=% syntax (old-style remove quotes)."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            + 'SET @TARGET="C:\\temp"\n'
            + 'SET @TARGET=%@TARGET:"=%\n'
            + "echo %@TARGET%\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), f'E009 should not be triggered for %VAR:"=% syntax, but found: {e009_issues}'

    def test_percent_style_string_replacement_with_text(self, tmp_path: Path) -> None:
        """Test %VAR:searchString=replaceString% syntax with quotes."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "SET PATH_VAR=C:\\Program Files\\App\n"
            'SET PATH_VAR=%PATH_VAR:" "=_%\n'
            "echo %PATH_VAR%\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "E009 should not be triggered for old-style string replacement"

    def test_multiple_string_replacements_in_sequence(self, tmp_path: Path) -> None:
        """Test multiple string replacement operations in sequence."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "SET V1=%2\n"
            "SET V2=%3\n"
            "SET V3=%4\n"
            'IF DEFINED V1 SET V1=!V1:"=!\n'
            'IF DEFINED V2 SET V2=!V2:"=!\n'
            'IF DEFINED V3 SET V3=!V3:"=!\n'
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert len(e009_issues) == 0, (
            f"E009 should not be triggered for multiple string replacements, "
            f"but found {len(e009_issues)} issues"
        )

    def test_mixed_delayed_and_percent_string_replacement(self, tmp_path: Path) -> None:
        """Test mixing delayed expansion and percent-style string replacement."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "SET @TARGET=%~1\n"
            'SET @TARGET_S=%@TARGET:"=%\n'
            "SET @CURRENT_RECURSION=%~2\n"
            'IF DEFINED @CURRENT_RECURSION SET @CURRENT_RECURSION=!@CURRENT_RECURSION:"=!\n'
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "E009 should not be triggered for mixed string replacement styles"

    def test_real_world_pattern_from_replicate_files(self, tmp_path: Path) -> None:
        """Test pattern found in Replicate-Files.BAT."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "SET @CURRENT_SOURCE=%~1\n"
            "SET @CURRENT_RECURSION=%~2\n"
            'IF DEFINED @CURRENT_RECURSION SET @CURRENT_RECURSION=!@CURRENT_RECURSION:"=!\n'
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert len(e009_issues) == 0, "Real-world pattern should not trigger E009"

    def test_real_world_pattern_from_zipfiles(self, tmp_path: Path) -> None:
        """Test pattern found in ZipFiles.BAT."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "SET @TARGET_S=%~s1\n"
            "SET @TARGET_D=%~1\n"
            'SET @TARGET=%@TARGET:"=%\n'
            "SET @DEST=%@TARGET_S%\\Zips\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert len(e009_issues) == 0, "ZipFiles.BAT pattern should not trigger E009"

    def test_legitimate_mismatched_quote_still_detected(self, tmp_path: Path) -> None:
        """Test that legitimate mismatched quotes are still detected."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            'ECHO *** SKIPPING %@FOLDER%" ***\n'  # Missing opening quote
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 1
        ), "Legitimate mismatched quote should still be detected"


class TestDocumentationCommentSyntax:
    """Test that ::: documentation comments are properly ignored."""

    def test_triple_colon_comment_with_quotes(self, tmp_path: Path) -> None:
        """Test that ::: comments with quotes are not checked."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            ':::  escape character for quotation marks.  (e.g. \\" )\n'
            ":::  For more details, see: http://example.com\n"
            "echo Done\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "::: documentation comments should not trigger E009"

    def test_triple_colon_vs_double_colon_comments(self, tmp_path: Path) -> None:
        """Test that ::: comments are treated like REM comments."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            ':::  This has an "unmatched quote\n'
            '::  This also has an "unmatched quote\n'
            'REM This also has an "unmatched quote\n'
            "echo Done\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        # None of the comment lines should trigger E009
        assert len(e009_issues) == 0, "Comment lines should not trigger E009"

    def test_real_world_documentation_pattern(self, tmp_path: Path) -> None:
        """Test real-world documentation pattern from ZipFiles.BAT."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            ":::  The issue of supporting long path names via SCHTASKS was a vexing one\n"
            ":::  until I came across a KB article that outlines the \\ character as the\n"
            ':::  escape character for quotation marks.  (e.g. \\" )\n'
            ":::  For more details, see: http://support.microsoft.com/kb/823093\n"
            ":::\n"
            "echo Done\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert len(e009_issues) == 0, "Real-world documentation should not trigger E009"


class TestCombinedScenarios:
    """Test combined scenarios with both string replacement and documentation."""

    def test_complete_real_world_scenario(self, tmp_path: Path) -> None:
        """Test a complete scenario combining multiple patterns."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            ":::\n"
            ":::  Script Purpose: Demonstrate string manipulation\n"
            ':::  Note: Use \\" for escaped quotes in SCHTASKS\n'
            ":::\n"
            "\n"
            "REM Get parameters and clean quotes\n"
            "SET @V1=%2\n"
            "SET @V2=%3\n"
            "SET @V3=%4\n"
            "\n"
            "REM Remove quotes from all parameters\n"
            'IF DEFINED @V1 SET @V1=!@V1:"=!\n'
            'IF DEFINED @V2 SET @V2=!@V2:"=!\n'
            'IF DEFINED @V3 SET @V3=!@V3:"=!\n'
            "\n"
            "REM Process target path\n"
            "SET @TARGET=%~1\n"
            'SET @TARGET=%@TARGET:"=%\n'
            "\n"
            "echo Processing: !@V1! !@V2! !@V3!\n"
            "echo Target: %@TARGET%\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert len(e009_issues) == 0, (
            f"Complete real-world scenario should not trigger E009, "
            f"but found {len(e009_issues)} issues"
        )

    def test_string_replacement_variants(self, tmp_path: Path) -> None:
        """Test various string replacement patterns."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "\n"
            "REM Pattern 1: Remove quotes (delayed expansion)\n"
            'SET VAR1=!VAR1:"=!\n'
            "\n"
            "REM Pattern 2: Remove quotes (percent style)\n"
            'SET VAR2=%VAR2:"=%\n'
            "\n"
            "REM Pattern 3: Replace spaces with underscores (delayed)\n"
            "SET VAR3=!VAR3: =_!\n"
            "\n"
            "REM Pattern 4: Replace text with quotes (delayed)\n"
            'SET VAR4=!VAR4:" "=_!\n'
            "\n"
            "REM Pattern 5: Replace text with quotes (percent)\n"
            'SET VAR5=%VAR5:" "=_%\n'
            "\n"
            "REM Pattern 6: Complex replacement with quotes\n"
            'SET VAR6=!VAR6:"Program Files"=ProgramFiles!\n'
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "Various string replacement patterns should not trigger E009"


class TestEdgeCasesAndRegressions:
    """Test edge cases to ensure fixes don't cause regressions."""

    # pylint: disable=invalid-name  # Test method names are descriptive
    def test_actual_quote_error_with_string_replacement_present(
        self, tmp_path: Path
    ) -> None:
        """Ensure legitimate errors are still caught even with valid string replacement."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            'SET VAR1=!VAR1:"=!\n'  # Valid string replacement
            'ECHO This has a problem" quote\n'  # Invalid - should be detected
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert len(e009_issues) == 1, "Legitimate quote error should still be detected"
        assert e009_issues[0].line_number == 4, "Error should be on line 4"

    def test_string_replacement_in_if_statement(self, tmp_path: Path) -> None:
        """Test string replacement within IF statements."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            'IF DEFINED @END_DEBUG_MODE %@END_DEBUG_MODE:"=%\n'
            'IF DEFINED @RECURSION SET @RECURSION=!@RECURSION:"=!\n'
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "String replacement in IF statements should not trigger E009"

    def test_nested_string_replacements(self, tmp_path: Path) -> None:
        """Test complex nested scenarios."""
        test_file = tmp_path / "test.cmd"
        test_file.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "FOR %%F IN (*.txt) DO (\n"
            "    SET FILE=%%F\n"
            '    SET FILE=!FILE:"=!\n'
            "    echo !FILE!\n"
            ")\n"
        )

        issues: List[LintIssue] = lint_batch_file(str(test_file))
        e009_issues = [issue for issue in issues if issue.rule.code == "E009"]

        assert (
            len(e009_issues) == 0
        ), "Nested string replacement should not trigger E009"


class TestE009LegitimateQuoteContexts:
    """E009 should not flag known legitimate single-quote patterns."""

    def test_powershell_here_string_closer(self, tmp_path: Path) -> None:
        content = '@echo off\n$xml = @"\nline\n"@\n'
        test_file = tmp_path / "ps.cmd"
        test_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(test_file))
        e009 = [i for i in issues if i.rule.code == "E009"]
        assert not [i for i in e009 if i.line_number == 3]

    def test_echo_decorative_leading_quote(self, tmp_path: Path) -> None:
        content = '@echo off\nECHO   " MONTHLY Archive: %@MAKE_MONTHLY%\n'
        test_file = tmp_path / "help.cmd"
        test_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(test_file))
        assert not [i for i in issues if i.rule.code == "E009"]

    def test_echo_ansi_color_art(self, tmp_path: Path) -> None:
        content = '@echo off\necho %lyel% foo %lred% bar %lyel%,=".%def%\n'
        test_file = tmp_path / "art.cmd"
        test_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(test_file))
        assert not [i for i in issues if i.rule.code == "E009"]

    def test_echo_usage_delayed_expansion_trailing_quote(self, tmp_path: Path) -> None:
        content = '@echo off\nECHO  %~n0 SpecialBackups!@SS_EXT!"\n'
        test_file = tmp_path / "usage.cmd"
        test_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(test_file))
        assert not [i for i in issues if i.rule.code == "E009"]

    def test_real_extra_quote_still_flagged(self, tmp_path: Path) -> None:
        content = '@echo off\nECHO *** SKIPPING %@FOLDER%" ***\n'
        test_file = tmp_path / "bad.cmd"
        test_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(test_file))
        assert [i for i in issues if i.rule.code == "E009"]

    def test_for_f_findstr_line_anchor_quotes(self, tmp_path: Path) -> None:
        content = (
            "@echo off\n"
            'for /f "tokens=1,* delims=:" %%a in (\'findstr /N "^" "%fixture%"\') do (\n'
            "    echo %%a\n"
            ")\n"
        )
        test_file = tmp_path / "findstr_for.cmd"
        test_file.write_text(content, encoding="utf-8")
        issues = lint_batch_file(str(test_file))
        assert not [i for i in issues if i.rule.code == "E009"]
