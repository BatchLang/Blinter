"""Tests for output and utility functions."""

from collections import defaultdict
import io
import queue
import sys
import threading
from typing import Callable, List, Optional, Tuple, Union

from blinter import (
    LintIssue,
    RuleSeverity,
)
from blinter.cli.main import _display_analyzed_scripts
from blinter.output.formatters import (
    _format_line_numbers_with_files,
    group_issues,
    print_detailed,
    print_help,
    print_severity_info,
    print_summary,
)
from blinter.rules.registry import RULES


class TestGroupIssues:
    """Test cases for issue grouping functionality."""

    def create_lint_issue(
        self, line_number: int, rule_code: str, context: str = ""
    ) -> LintIssue:
        """Helper method to create LintIssue objects for testing."""
        return LintIssue(
            line_number=line_number, rule=RULES[rule_code], context=context
        )

    def test_group_issues_empty(self) -> None:
        """Test grouping with no issues."""
        issues: List[LintIssue] = []
        grouped = group_issues(issues)
        assert len(grouped) == 0
        assert isinstance(grouped, defaultdict)

    def test_group_issues_single_severity(self) -> None:
        """Test grouping issues of a single severity."""
        issues = [
            self.create_lint_issue(1, "S001"),  # Style level
            self.create_lint_issue(5, "S004"),  # Style level
            self.create_lint_issue(10, "S011"),  # Style level
        ]
        grouped = group_issues(issues)
        assert len(grouped) == 1
        assert RuleSeverity.STYLE in grouped
        assert len(grouped[RuleSeverity.STYLE]) == 3

    def test_group_issues_multiple_severities(self) -> None:
        """Test grouping issues of multiple severities."""
        issues = [
            self.create_lint_issue(1, "S001"),  # Style
            self.create_lint_issue(3, "W005"),  # Warning
            self.create_lint_issue(5, "E002"),  # Error
            self.create_lint_issue(7, "SEC002"),  # Security
            self.create_lint_issue(9, "P001"),  # Performance
        ]
        grouped = group_issues(issues)
        assert len(grouped) == 5  # All 5 severity levels
        assert RuleSeverity.STYLE in grouped
        assert RuleSeverity.WARNING in grouped
        assert RuleSeverity.ERROR in grouped
        assert RuleSeverity.SECURITY in grouped
        assert RuleSeverity.PERFORMANCE in grouped

    def test_group_issues_same_severity_different_rules(self) -> None:
        """Test grouping multiple issues with same severity but different rules."""
        issues = [
            self.create_lint_issue(1, "S001"),  # Style - Missing @ECHO OFF
            self.create_lint_issue(3, "S003"),  # Style - Inconsistent capitalization
            self.create_lint_issue(5, "S004"),  # Style - Trailing whitespace
            self.create_lint_issue(7, "S011"),  # Style - Line too long
        ]
        grouped = group_issues(issues)
        assert len(grouped) == 1  # Only style severity
        assert RuleSeverity.STYLE in grouped
        assert len(grouped[RuleSeverity.STYLE]) == 4


class TestPrintFunctions:
    """Test cases for various print functions."""

    def capture_stdout(self, func: Callable[[object], None], *args: object) -> str:
        """Helper method to capture stdout output."""
        old_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()
        try:
            func(*args)
            return captured_output.getvalue()
        finally:
            sys.stdout = old_stdout

    def create_lint_issue(
        self, line_number: int, rule_code: str, context: str = ""
    ) -> LintIssue:
        """Helper method to create LintIssue objects for testing."""
        return LintIssue(
            line_number=line_number, rule=RULES[rule_code], context=context
        )

    def test_print_help(self) -> None:
        """Test help function output."""
        output = self.capture_stdout(print_help)

        assert "Blinter - Help Menu" in output
        assert "Usage:" in output
        assert "blinter <path>" in output
        assert "--summary" in output
        assert "--severity" in output
        assert "--help" in output
        assert "Examples:" in output
        assert "Rule Categories:" in output
        assert "E001-E999   Error Level" in output

    def test_print_summary_empty(self) -> None:
        """Test summary with no issues."""
        issues: List[LintIssue] = []
        output = self.capture_stdout(print_summary, issues)

        assert "SUMMARY:" in output
        assert "Total issues: 0" in output
        assert "No issues found" in output

    def test_print_summary_with_issues(self) -> None:
        """Test summary with various issues."""
        issues = [
            self.create_lint_issue(1, "S001"),  # Style
            self.create_lint_issue(3, "W005"),  # Warning
            self.create_lint_issue(5, "W005"),  # Warning (duplicate rule)
            self.create_lint_issue(7, "E002"),  # Error
        ]

        output = self.capture_stdout(print_summary, issues)

        assert "SUMMARY:" in output
        assert "Total issues: 4" in output
        assert "Most common issue: 'Unquoted variable with spaces' (W005)" in output
        assert "Issues by severity:" in output
        assert "Error: 1" in output
        assert "Warning: 2" in output
        assert "Style: 1" in output

    def test_print_detailed_empty(self) -> None:
        """Test detailed output with no issues."""
        issues: List[LintIssue] = []
        output = self.capture_stdout(print_detailed, issues)

        assert "DETAILED ISSUES:" in output
        assert "No issues found! *" in output

    def test_print_detailed_with_issues(self) -> None:
        """Test detailed output with issues."""
        issues = [
            self.create_lint_issue(1, "S001", "Script should start with @ECHO OFF"),
            self.create_lint_issue(5, "E002", "GOTO points to non-existent label"),
        ]

        output = self.capture_stdout(print_detailed, issues)

        assert "DETAILED ISSUES:" in output
        assert "ERROR LEVEL ISSUES:" in output
        assert "STYLE LEVEL ISSUES:" in output
        assert "Line 1: Missing @ECHO OFF at file start (S001)" in output
        assert "Line 5: Missing label for GOTO statement (E002)" in output
        assert "Explanation:" in output
        assert "Recommendation:" in output
        assert "Context:" in output

    def test_print_severity_info_empty(self) -> None:
        """Test severity info with no issues."""
        issues: List[LintIssue] = []
        output = self.capture_stdout(print_severity_info, issues)

        assert "SEVERITY BREAKDOWN:" in output
        assert "====================" in output

    def test_print_severity_info_with_issues(self) -> None:
        """Test severity info with various issue types."""
        issues = [
            self.create_lint_issue(1, "S001"),  # Style
            self.create_lint_issue(2, "W005"),  # Warning
            self.create_lint_issue(3, "E002"),  # Error
            self.create_lint_issue(4, "SEC003"),  # Security
            self.create_lint_issue(5, "P001"),  # Performance
        ]

        output = self.capture_stdout(print_severity_info, issues)

        assert "SEVERITY BREAKDOWN:" in output
        assert "Error: 1 issue" in output
        assert "Warning: 1 issue" in output
        assert "Style: 1 issue" in output
        assert "Security: 1 issue" in output
        assert "Performance: 1 issue" in output
        assert "Critical issues that will cause script failure" in output
        assert "Issues that may cause problems" in output


class TestOutputFormatting:
    """Test cases for output formatting and edge cases."""

    def capture_stdout(self, func: Callable[[object], None], *args: object) -> str:
        """Helper method to capture stdout output."""
        old_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()
        try:
            func(*args)
            return captured_output.getvalue()
        finally:
            sys.stdout = old_stdout

    def create_lint_issue(
        self, line_number: int, rule_code: str, context: str = ""
    ) -> LintIssue:
        """Helper method to create LintIssue objects for testing."""
        return LintIssue(
            line_number=line_number, rule=RULES[rule_code], context=context
        )

    def test_print_detailed_all_severity_levels(self) -> None:
        """Test detailed output includes all severity levels."""
        issues = [
            self.create_lint_issue(1, "E002"),  # Error
            self.create_lint_issue(2, "W005"),  # Warning
            self.create_lint_issue(3, "S001"),  # Style
            self.create_lint_issue(4, "SEC003"),  # Security
            self.create_lint_issue(5, "P001"),  # Performance
        ]

        output = self.capture_stdout(print_detailed, issues)

        assert "ERROR LEVEL ISSUES:" in output
        assert "WARNING LEVEL ISSUES:" in output
        assert "STYLE LEVEL ISSUES:" in output
        assert "SECURITY LEVEL ISSUES:" in output
        assert "PERFORMANCE LEVEL ISSUES:" in output

    def test_print_summary_single_vs_plural(self) -> None:
        """Test proper singular/plural formatting in severity info."""
        # Test single issue
        issues = [self.create_lint_issue(1, "S001")]
        output = self.capture_stdout(print_severity_info, issues)
        assert "1 issue" in output and "1 issues" not in output

        # Test multiple issues
        issues = [
            self.create_lint_issue(1, "S001"),
            self.create_lint_issue(2, "S004"),
        ]
        output = self.capture_stdout(print_severity_info, issues)
        assert "2 issues" in output

    def test_line_number_formatting_single_file(self) -> None:
        """Test proper formatting of line numbers in detailed output for single file."""
        issues = [
            self.create_lint_issue(1, "W005"),
            self.create_lint_issue(3, "W005"),
            self.create_lint_issue(5, "W005"),
            self.create_lint_issue(7, "W005"),
        ]

        output = self.capture_stdout(print_detailed, issues)

        # Should have comma-separated, sorted line numbers
        assert "Line 1, 3, 5, 7: Unquoted variable with spaces (W005)" in output

    def test_line_number_formatting_multi_file(self) -> None:
        """Test proper formatting of line numbers in detailed output for multiple files."""
        issues = [
            LintIssue(line_number=197, rule=RULES["W039"], file_path="DriveInfo.BAT"),
            LintIssue(line_number=245, rule=RULES["W039"], file_path="DriveInfo.BAT"),
            LintIssue(line_number=529, rule=RULES["W039"], file_path="SetDrive.BAT"),
            LintIssue(line_number=564, rule=RULES["W039"], file_path="SetDrive.BAT"),
            LintIssue(line_number=440, rule=RULES["W039"], file_path="StorageInfo.BAT"),
            LintIssue(line_number=643, rule=RULES["W039"], file_path="StorageInfo.BAT"),
        ]

        output = self.capture_stdout(print_detailed, issues)

        # Should have hierarchical format with file grouping
        assert "Nested FOR loops without call optimization (W039)" in output
        assert "[DriveInfo.BAT] Line 197, 245" in output
        assert "[SetDrive.BAT] Line 529, 564" in output
        assert "[StorageInfo.BAT] Line 440, 643" in output
        # Should not have the old format
        assert "Line 197 [DriveInfo.BAT]" not in output

    def test_format_line_numbers_with_files_single_file(self) -> None:
        """Test _format_line_numbers_with_files for single file."""
        issues = [
            self.create_lint_issue(1, "W005"),
            self.create_lint_issue(3, "W005"),
            self.create_lint_issue(5, "W005"),
        ]

        is_multi_file, line_data = _format_line_numbers_with_files(issues)

        assert is_multi_file is False
        assert line_data == "Line 1, 3, 5"

    def test_format_line_numbers_with_files_multi_file(self) -> None:
        """Test _format_line_numbers_with_files for multiple files."""
        issues = [
            LintIssue(line_number=100, rule=RULES["W039"], file_path="script1.bat"),
            LintIssue(line_number=200, rule=RULES["W039"], file_path="script1.bat"),
            LintIssue(line_number=50, rule=RULES["W039"], file_path="script2.bat"),
            LintIssue(line_number=150, rule=RULES["W039"], file_path="script2.bat"),
        ]

        is_multi_file, line_data = _format_line_numbers_with_files(issues)

        assert is_multi_file is True
        assert isinstance(line_data, dict)
        assert "script1.bat" in line_data
        assert "script2.bat" in line_data
        assert line_data["script1.bat"] == [100, 200]
        assert line_data["script2.bat"] == [50, 150]

    def test_special_characters_in_output(self) -> None:
        """Test handling of special characters in error messages and context."""
        issues = [
            self.create_lint_issue(
                1, "E002", "GOTO points to non-existent label 'special_label'"
            ),
        ]

        output = self.capture_stdout(print_detailed, issues)
        assert "'special_label'" in output

    def test_large_line_numbers(self) -> None:
        """Test formatting with large line numbers."""
        issues = [
            self.create_lint_issue(999, "S011"),
            self.create_lint_issue(1000, "S011"),
            self.create_lint_issue(10000, "S011"),
        ]

        output = self.capture_stdout(print_detailed, issues)
        assert "Line 999, 1000, 10000:" in output

    def test_context_information_display(self) -> None:
        """Test that context information is properly displayed."""
        issues = [
            self.create_lint_issue(
                1, "E002", "GOTO points to non-existent label 'missing_label'"
            ),
            self.create_lint_issue(5, "S001", "Script should start with @ECHO OFF"),
        ]

        output = self.capture_stdout(print_detailed, issues)
        assert "Context: GOTO points to non-existent label 'missing_label'" in output
        assert "Context: Script should start with @ECHO OFF" in output

    def test_terminal_escapes_are_stripped_from_text_output(self) -> None:
        """CSI sequences in a context are not written to the terminal."""
        issues = [
            self.create_lint_issue(1, "E002", "label \x1b[31mred\x1b[0m name"),
        ]
        output = self.capture_stdout(print_detailed, issues)
        assert "\x1b" not in output
        assert "label red name" in output

    def test_empty_context_handling(self) -> None:
        """Test proper handling when context is empty."""
        issues = [
            self.create_lint_issue(1, "S001", ""),  # Empty context
        ]

        output = self.capture_stdout(print_detailed, issues)
        # Should not show context line when empty
        assert "Context:" not in output or "Context: " not in output

    def test_output_functions_thread_safety_basic(self) -> None:
        """Basic test for thread safety of output functions."""
        issues = [
            self.create_lint_issue(1, "S001"),
            self.create_lint_issue(2, "W005"),
            self.create_lint_issue(3, "E002"),
        ]

        results_queue: queue.Queue[tuple[str, Union[int, str]]] = queue.Queue()

        def worker(
            func: Callable[[List[LintIssue]], None],
            issue_list: List[LintIssue],
        ) -> None:
            try:
                # Capture output instead of printing to console
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                func(issue_list)
                output = sys.stdout.getvalue()
                sys.stdout = old_stdout
                results_queue.put(("success", len(output)))
            except Exception as exception:
                results_queue.put(("error", str(exception)))

        # Test multiple output functions concurrently
        functions = [print_summary, print_detailed, print_severity_info]
        threads = []

        for func in functions:
            thread = threading.Thread(target=worker, args=(func, issues))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Check results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        assert len(results) == 3
        for result_type, result_data in results:
            assert result_type == "success"
            assert isinstance(result_data, int)  # Length of output
            assert result_data > 0  # Should have some output

    def test_rule_code_consistency(self) -> None:
        """Test that rule codes are consistently displayed."""
        issues = [
            self.create_lint_issue(1, "E002"),
            self.create_lint_issue(2, "W005"),
            self.create_lint_issue(3, "S001"),
            self.create_lint_issue(4, "SEC003"),
            self.create_lint_issue(5, "P001"),
        ]

        output = self.capture_stdout(print_detailed, issues)

        # Check that all rule codes are displayed
        assert "(E002)" in output
        assert "(W005)" in output
        assert "(S001)" in output
        assert "(SEC003)" in output
        assert "(P001)" in output

    def test_summary_most_common_issue_calculation(self) -> None:
        """Test that most common issue is calculated correctly."""
        issues = [
            self.create_lint_issue(1, "S003"),  # Inconsistent capitalization
            self.create_lint_issue(2, "S003"),  # Inconsistent capitalization
            self.create_lint_issue(3, "S003"),  # Inconsistent capitalization
            self.create_lint_issue(4, "W005"),  # Unquoted variable
            self.create_lint_issue(5, "W005"),  # Unquoted variable
            self.create_lint_issue(6, "E002"),  # Missing label
        ]

        output = self.capture_stdout(print_summary, issues)

        assert "Total issues: 6" in output
        assert (
            "Most common issue: 'Inconsistent command capitalization' "
            "(S003) - 3 occurrences" in output
        )


class TestDisplayAnalyzedScripts:
    """Test cases for the _display_analyzed_scripts function."""

    def capture_stdout(
        self,
        func: Callable[[List[Tuple[str, Optional[str]]], str, bool], None],
        *args: object,
    ) -> str:
        """Helper method to capture stdout output."""
        old_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()
        try:
            func(*args)
            return captured_output.getvalue()
        finally:
            sys.stdout = old_stdout

    def test_display_single_script(self) -> None:
        """Test displaying a single analyzed script."""
        processed_files = [("D:\\test\\script.bat", None)]
        target_path = "D:\\test"

        output = self.capture_stdout(
            _display_analyzed_scripts, processed_files, target_path, False
        )

        assert "Scripts Analyzed:" in output
        assert "1. script.bat" in output

    def test_display_multiple_scripts(self) -> None:
        """Test displaying multiple analyzed scripts."""
        processed_files = [
            ("D:\\test\\main.bat", None),
            ("D:\\test\\utils.bat", None),
            ("D:\\test\\config.cmd", None),
        ]
        target_path = "D:\\test"

        output = self.capture_stdout(
            _display_analyzed_scripts, processed_files, target_path, True
        )

        assert "Scripts Analyzed:" in output
        assert "1. main.bat" in output
        assert "2. utils.bat" in output
        assert "3. config.cmd" in output

    def test_display_called_scripts_with_parent(self) -> None:
        """Test displaying called scripts with parent information."""
        processed_files = [
            ("D:\\test\\main.bat", None),
            ("D:\\test\\config.bat", "D:\\test\\main.bat"),
            ("D:\\test\\other.bat", None),
        ]
        target_path = "D:\\test"

        output = self.capture_stdout(
            _display_analyzed_scripts, processed_files, target_path, True
        )

        assert "Scripts Analyzed:" in output
        assert "1. main.bat" in output
        assert "2.   ↳ config.bat (called by main.bat)" in output
        assert "3. other.bat" in output

    def test_display_empty_list(self) -> None:
        """Test displaying with no processed files."""
        processed_files: list[tuple[str, Union[str, None]]] = []
        target_path = "D:\\test"

        output = self.capture_stdout(
            _display_analyzed_scripts, processed_files, target_path, False
        )

        # Should output nothing for empty list
        assert output == ""

    def test_display_scripts_relative_path_directory(self) -> None:
        """Test displaying scripts with relative paths in directory mode."""
        processed_files = [
            ("D:\\test\\subdir\\script.bat", None),
            ("D:\\test\\main.bat", None),
        ]
        target_path = "D:\\test"

        output = self.capture_stdout(
            _display_analyzed_scripts, processed_files, target_path, True
        )

        assert "Scripts Analyzed:" in output
        assert "subdir" in output or "subdir\\script.bat" in output
        # Should show relative paths in directory mode
