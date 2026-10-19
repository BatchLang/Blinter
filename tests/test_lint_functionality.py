"""Tests for the main batch file linting functionality."""

import os
import re
import tempfile

from blinter import (
    RuleSeverity,
    lint_batch_file,
)
from blinter.patterns import DANGEROUS_COMMAND_PATTERNS
from blinter.rules.registry import RULE_COUNT, RULES

# pylint: disable=too-many-lines


class TestLintBatchFile:
    """Test cases for batch file linting."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file with given content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_perfect_batch_file(self) -> None:
        """Test a well-formatted batch file with minimal critical issues."""
        content = """@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
SET "TEST_VAR=test value"
IF "%TEST_VAR%"=="test value" (
    ECHO Variable is set correctly
)
FOR %%i IN (1 2 3) DO (
    ECHO %%i
)
:end_label
ECHO Script completed
ENDLOCAL
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should have some issues but mostly style-related (like .bat extension)
            error_issues = [
                issue for issue in issues if issue.rule.severity == RuleSeverity.ERROR
            ]
            # Should have minimal critical errors
            assert len(error_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_missing_echo_off(self) -> None:
        """Test detection of missing @echo off."""
        content = """echo This script is missing @echo off
echo Another line
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S001" in rule_codes  # Missing @ECHO OFF at file start
        finally:
            os.unlink(temp_file)

    def test_unquoted_variables(self) -> None:
        """Test detection of unquoted variables."""
        content = """@echo off
set var=test
echo %var%
if %var%==test echo Variable matches
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W005" in rule_codes  # Unquoted variable with spaces
        finally:
            os.unlink(temp_file)

    def test_unquoted_variables_with_numeric_operators(self) -> None:
        """Test that unquoted variables with numeric comparison operators don't trigger W005."""
        content = """@echo off
set errorcode=0
if %errorcode% equ 0 echo Success
if %errorcode% neq 1 echo Not one
if %errorcode% lss 5 echo Less than five
if %errorcode% leq 10 echo Less or equal ten
if %errorcode% gtr -1 echo Greater than negative one
if %errorcode% geq 0 echo Greater or equal zero
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # W005 should NOT be triggered for numeric operators
            assert "W005" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_goto_without_label(self) -> None:
        """Test detection of goto without matching label."""
        content = """@echo off
echo Starting script
goto nonexistent_label
echo This should not be reached
:existing_label
echo This label exists
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E002" in rule_codes  # Missing label for GOTO statement
        finally:
            os.unlink(temp_file)

    def test_goto_with_existing_label(self) -> None:
        """Test goto with existing label (should not trigger error)."""
        content = """@echo off
echo Starting script
goto existing_label
echo This should not be reached
:existing_label
echo This label exists
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E002" not in rule_codes  # Should not have missing label error
        finally:
            os.unlink(temp_file)

    def test_duplicate_labels(self) -> None:
        """Test detection of duplicate labels."""
        content = """@echo off
:label1
echo First occurrence
:label1
echo Second occurrence (duplicate)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W013" in rule_codes  # Duplicate label
        finally:
            os.unlink(temp_file)

    def test_if_without_comparison_operator(self) -> None:
        """Test detection of if statements without == operator."""
        content = """@echo off
if exist file.txt echo File exists
if defined var echo Variable is defined
if "%var%" echo This is missing ==
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert len(issues) > 0
            assert any(
                code.startswith("E") or code.startswith("W") for code in rule_codes
            )
        finally:
            os.unlink(temp_file)

    def test_dangerous_commands(self) -> None:
        """Test detection of potentially dangerous commands."""
        content = """@echo off
del *.*
format c:
shutdown /s /t 0
rmdir /s /q C:\\temp
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC003" in rule_codes  # Dangerous command without confirmation
        finally:
            os.unlink(temp_file)

    def test_sec003_shutdown_false_positives(self) -> None:
        """Test SEC003 does not flag shutdown in labels, GOTO, or variable names."""
        content = """@echo off
rem Test that shutdown in various contexts doesn't trigger false positives

rem -- Label containing shutdown - should NOT flag
:ShutDown
echo In shutdown label

rem -- GOTO statement with shutdown label - should NOT flag
GOTO :ShutDown
GOTO :Abort-ShutDown

rem -- Another label with shutdown - should NOT flag
:Abort-Shutdown
echo Aborting

rem -- Variable name containing shutdown - should NOT flag
IF DEFINED @MSSHUTDOWN echo Variable defined
SET @MSSHUTDOWN=TRUE
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec003_issues = [issue for issue in issues if issue.rule.code == "SEC003"]
            # Should have NO SEC003 issues - all are false positive contexts
            assert len(sec003_issues) == 0, (
                f"Expected no SEC003 issues but found {len(sec003_issues)}: "
                f"{[issue.line_number for issue in sec003_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_sec003_shutdown_true_positives(self) -> None:
        """Test SEC003 correctly flags actual shutdown commands."""
        content = """@echo off
rem Test that actual shutdown commands are flagged

rem -- Actual SHUTDOWN command - SHOULD flag
START "Shutdown" SHUTDOWN -s -f -m \\\\SERVER -t 75 -c "Emergency"

rem -- PSSHUTDOWN command - SHOULD flag
START "Shutdown" PSSHUTDOWN -k -f -t 75 -m "Emergency" \\\\SERVER

rem -- Abort shutdown - SHOULD flag
SHUTDOWN -a -m \\\\SERVER

rem -- PSSHUTDOWN abort - SHOULD flag
PSSHUTDOWN -a \\\\SERVER
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec003_issues = [issue for issue in issues if issue.rule.code == "SEC003"]
            # Should have 4 SEC003 issues - one for each actual command
            assert len(sec003_issues) == 4, (
                f"Expected 4 SEC003 issues but found {len(sec003_issues)}: "
                f"lines {[issue.line_number for issue in sec003_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_sec003_where_dangerous_commands(self) -> None:
        """Test SEC003 flags WHERE with dangerous commands in command substitution."""
        content = """@echo off
rem Test that WHERE with dangerous commands is flagged even in SET statements

rem -- WHERE SHUTDOWN in FOR loop - SHOULD flag
SET @MSSHUTDOWN=& FOR /F %%V IN ('WHERE SHUTDOWN 2^>NUL') DO SET @MSSHUTDOWN=TRUE

rem -- WHERE FORMAT - SHOULD flag
SET @HASFORMAT=& FOR /F %%V IN ('WHERE FORMAT 2^>NUL') DO SET @HASFORMAT=TRUE

rem -- WHERE DEL - SHOULD flag
SET @HASDEL=& FOR /F %%V IN ('WHERE DEL 2^>NUL') DO SET @HASDEL=TRUE

rem -- WHERE RMDIR - SHOULD flag
SET @HASRMDIR=& FOR /F %%V IN ('WHERE RMDIR 2^>NUL') DO SET @HASRMDIR=TRUE

rem -- WHERE PSSHUTDOWN - SHOULD flag
SET @HASPSSHUTDOWN=& FOR /F %%V IN ('WHERE PSSHUTDOWN 2^>NUL') DO SET @HASPSSHUTDOWN=TRUE

rem -- WHERE REG - SHOULD flag
SET @HASREG=& FOR /F %%V IN ('WHERE REG 2^>NUL') DO SET @HASREG=TRUE
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec003_issues = [issue for issue in issues if issue.rule.code == "SEC003"]
            # Should have 6 SEC003 issues - one for each WHERE command
            assert len(sec003_issues) == 6, (
                f"Expected 6 SEC003 issues for WHERE commands but found {len(sec003_issues)}: "
                f"lines {[issue.line_number for issue in sec003_issues]}"
            )
            # Verify each dangerous command is detected
            contexts = [issue.context for issue in sec003_issues]
            assert any(
                "SHUTDOWN" in ctx for ctx in contexts
            ), "Should detect WHERE SHUTDOWN"
            assert any(
                "FORMAT" in ctx for ctx in contexts
            ), "Should detect WHERE FORMAT"
            assert any("DEL" in ctx for ctx in contexts), "Should detect WHERE DEL"
            assert any("RMDIR" in ctx for ctx in contexts), "Should detect WHERE RMDIR"
            assert any(
                "PSSHUTDOWN" in ctx for ctx in contexts
            ), "Should detect WHERE PSSHUTDOWN"
            assert any("REG" in ctx for ctx in contexts), "Should detect WHERE REG"
        finally:
            os.unlink(temp_file)

    def test_long_lines(self) -> None:
        """Test detection of lines exceeding 100 characters."""
        long_line = "echo " + "x" * 105  # Exceed 100 character limit
        content = f"""@echo off
{long_line}
echo Normal line
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S020" in rule_codes  # Long line without continuation
        finally:
            os.unlink(temp_file)

    def test_delayed_expansion_without_enablement(self) -> None:
        """Test detection of delayed expansion usage without enablement."""
        content = """@echo off
set var=test
echo !var!
set count=0
for /l %%i in (1,1,5) do (
    set /a count=!count!+1
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "P008" in rule_codes  # Delayed expansion without enablement
        finally:
            os.unlink(temp_file)

    def test_delayed_expansion_with_enablement(self) -> None:
        """Test delayed expansion with proper enablement (should not trigger error)."""
        content = """@echo off
setlocal enabledelayedexpansion
set var=test
echo !var!
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "P008" not in rule_codes  # Should not have delayed expansion error
        finally:
            os.unlink(temp_file)

    def test_unescaped_special_characters(self) -> None:
        """Test detection of unescaped special characters outside quotes."""
        content = """@echo off
set var1=test
SET var2=test2
echo This has an unescaped & character
echo "This & character is properly quoted"
echo This has unescaped | pipe
echo This has unescaped > redirect
echo This has properly escaped ^& character
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # The new system focuses on more critical issues
            # Special character escaping is not currently implemented as a specific rule
            # Just ensure the linter runs without errors
            assert isinstance(issues, list)
            # Should detect style issues like inconsistent command capitalization
            # (we now have mixed case: "set" and "SET")
            rule_codes = [issue.rule.code for issue in issues]
            assert "S003" in rule_codes  # Inconsistent command capitalization
        finally:
            os.unlink(temp_file)

    def test_malformed_for_loop(self) -> None:
        """Test detection of malformed for loops missing 'do'."""
        content = """@echo off
for %%i in (1 2 3) echo %%i
for /l %%j in (1,1,5) do echo %%j
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E010" in rule_codes  # Malformed FOR loop missing DO
        finally:
            os.unlink(temp_file)

    def test_trailing_whitespace(self) -> None:
        """Test detection of trailing whitespace."""
        content = """@echo off
echo This line has trailing spaces   
echo This line is clean
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S004" in rule_codes  # Trailing whitespace
        finally:
            os.unlink(temp_file)

    def test_unsafe_set_command(self) -> None:
        """Test detection of potentially unsafe set commands."""
        content = """@echo off
set var=unquoted value
set "quoted_var=safe value"
set /a num=5
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC002" in rule_codes  # Unsafe SET command usage
        finally:
            os.unlink(temp_file)

    def test_undefined_variable_usage(self) -> None:
        """Test detection of undefined variable usage."""
        content = """@echo off
set defined_var=value
echo %defined_var%
echo %undefined_var%
echo !another_undefined!
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E006" in rule_codes  # Undefined variable reference
        finally:
            os.unlink(temp_file)

    def test_mismatched_quotes(self) -> None:
        """Test detection of mismatched quotes."""
        content = """@echo off
echo "This string has matching quotes"
echo "This string has mismatched quotes
echo 'Single quotes are less common'
echo "Another mismatched quote
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E009" in rule_codes  # Mismatched quotes
        finally:
            os.unlink(temp_file)

    def test_empty_file(self) -> None:
        """Test linting an empty file."""
        content = ""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Empty file should not trigger the @echo off check
            assert len(issues) == 0
        finally:
            os.unlink(temp_file)

    def test_complex_realistic_scenario(self) -> None:
        """Test a complex, realistic batch file scenario."""
        content = """@echo off
setlocal enabledelayedexpansion
set "source_dir=C:\\Source"
set "backup_dir=C:\\Backup"
set "log_file=backup.log"

echo Starting backup process...

if not exist "%source_dir%" (
    echo Error: Source directory does not exist
    goto :error
)

if not exist "%backup_dir%" (
    mkdir "%backup_dir%"
    if !errorlevel! neq 0 (
        echo Failed to create backup directory
        goto :error
    )
)

for /r "%source_dir%" %%f in (*.*) do (
    set "rel_path=%%~pnxf"
    set "rel_path=!rel_path:%source_dir%=!"
    set "target_file=%backup_dir%!rel_path!"

    if not exist "%%~dpf" mkdir "%%~dpf"
    copy "%%f" "!target_file!" >> "%log_file%" 2>&1
    if !errorlevel! neq 0 (
        echo Failed to copy %%f
    )
)

echo Backup completed successfully
goto :end

:error
echo Backup process failed
exit /b 1

:end
echo Process finished
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            critical_issues = [
                issue
                for issue in issues
                if issue.rule.severity in [RuleSeverity.ERROR, RuleSeverity.WARNING]
            ]
            assert isinstance(critical_issues, list)
        finally:
            os.unlink(temp_file)

    def test_dangerous_commands_patterns(self) -> None:
        """Test that all dangerous command patterns are properly detected."""
        for pattern, expected_rule in DANGEROUS_COMMAND_PATTERNS:
            # Create content that would match this pattern
            if "reg" in pattern and "delete" in pattern:
                test_content = "@echo off\nreg delete HKLM\\Software\\Test /f\n"
            elif "del" in pattern:
                test_content = "@echo off\ndel *.*\n"
            elif "format" in pattern:
                test_content = "@echo off\nformat c:\n"
            elif "shutdown" in pattern:
                test_content = "@echo off\nshutdown /s\n"
            elif "rmdir" in pattern:
                test_content = "@echo off\nrmdir /s /q C:\\\n"
            else:
                continue

            temp_file = self.create_temp_batch_file(test_content)
            try:
                issues = lint_batch_file(temp_file)
                rule_codes = [issue.rule.code for issue in issues]
                assert (
                    expected_rule in rule_codes
                ), f"Pattern {pattern} was not detected"
            finally:
                os.unlink(temp_file)

    def test_missing_exit_simple_script(self) -> None:
        """Test W001: Simple script without EXIT statement should be flagged."""
        content = """@echo off
echo Starting script
echo Doing some work
echo Done
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_exit_no_warning(self) -> None:
        """Test W001: Script with EXIT statement should not be flagged."""
        content = """@echo off
echo Starting script
echo Doing some work
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_goto_eof_no_warning(self) -> None:
        """Test W001: Script with GOTO :EOF should not be flagged."""
        content = """@echo off
echo Starting script
echo Doing some work
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_subroutine_library_no_warning(self) -> None:
        """Test W001: Pure subroutine library (label before code) should not be flagged."""
        content = """@echo off
GOTO :EOF

:subroutine1
echo In subroutine 1
GOTO :EOF

:subroutine2
echo In subroutine 2
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_goto_label_and_exit(self) -> None:
        """Test W001: Script with GOTO to label that has EXIT should not be flagged."""
        content = """@echo off
echo Starting
GOTO end

:end
echo Ending
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_conditional_all_branches_exit(self) -> None:
        """Test W001: Script where all conditional branches have EXIT should not be flagged."""
        content = """@echo off
IF "%1"=="test" (
    echo Test mode
    EXIT /b 0
) ELSE (
    echo Normal mode
    EXIT /b 1
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # This should still be flagged because after the IF/ELSE block,
            # execution could theoretically continue (though it won't in practice)
            # Our current implementation is conservative
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_one_branch_missing_exit(self) -> None:
        """Test W001: Script where one branch can reach EOF should be flagged."""
        content = """@echo off
IF "%1"=="test" (
    echo Test mode
    EXIT /b 0
)
echo Continuing after IF
echo This can reach EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_comments_only_script_no_warning(self) -> None:
        """Test W001: Comments-only script should not be flagged."""
        content = """@echo off
REM This is a comment
REM Another comment
:: Yet another comment
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_infinite_goto_loop(self) -> None:
        """Test W001: Script with infinite GOTO loop should not be flagged."""
        content = """@echo off
:loop
echo Looping forever
GOTO loop
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_exit_inside_if_block(self) -> None:
        """Test W001: Script with EXIT only inside IF block should still be flagged."""
        content = """@echo off
echo Starting
IF EXIST somefile.txt (
    EXIT /b 0
)
echo This line can be reached if file doesn't exist
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_main_code_then_subroutines(self) -> None:
        """Test W001: Script with main code then subroutines should have EXIT before subroutines."""
        content = """@echo off
echo Main script execution
echo Doing main work
GOTO :EOF

:subroutine
echo This is a subroutine
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_main_missing_exit_before_subs(self) -> None:
        """Test W001: Script with main code but no EXIT before subroutines should be flagged."""
        content = """@echo off
echo Main script execution
echo Doing main work

:subroutine
echo This is a subroutine
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # The main code falls through into the subroutine, but we reach EOF in subroutine
            # Actually, the subroutine has GOTO :EOF, so EOF is not reached
            # This should NOT be flagged since the subroutine exits properly
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)


class TestRuleSystem:
    """Test cases for the new rule system."""

    def create_temp_batch_file(self, content: str, extension: str = ".bat") -> str:
        """Helper method to create a temporary batch file with given content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=extension, delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_rules_completeness(self) -> None:
        """Test that all rules have required fields."""
        for rule_code, rule in RULES.items():
            assert isinstance(rule.code, str), f"Rule {rule_code} has invalid code"
            assert isinstance(rule.name, str), f"Rule {rule_code} has invalid name"
            assert isinstance(
                rule.severity, RuleSeverity
            ), f"Rule {rule_code} has invalid severity"
            assert isinstance(
                rule.explanation, str
            ), f"Rule {rule_code} has invalid explanation"
            assert isinstance(
                rule.recommendation, str
            ), f"Rule {rule_code} has invalid recommendation"
            assert len(rule.explanation) > 0, f"Rule {rule_code} has empty explanation"
            assert (
                len(rule.recommendation) > 0
            ), f"Rule {rule_code} has empty recommendation"
            assert (
                rule.code == rule_code
            ), f"Rule code mismatch: {rule.code} != {rule_code}"

    def test_rule_code_categories(self) -> None:
        """Test that rule codes follow the proper categorization."""
        error_codes = [code for code in RULES if code.startswith("E")]
        warning_codes = [code for code in RULES if code.startswith("W")]
        security_codes = [code for code in RULES if code.startswith("SEC")]
        # Style codes start with S but not SEC
        style_codes = [
            code
            for code in RULES
            if code.startswith("S") and not code.startswith("SEC")
        ]
        performance_codes = [code for code in RULES if code.startswith("P")]

        # Check that Error codes have Error severity
        # Exception: E006 was downgraded to WARNING to reduce false positives from system variables
        for code in error_codes:
            if code == "E006":
                assert (
                    RULES[code].severity == RuleSeverity.WARNING
                ), f"Rule {code} should have Warning severity (downgraded from Error)"
            else:
                assert (
                    RULES[code].severity == RuleSeverity.ERROR
                ), f"Rule {code} should have Error severity"

        # Check that Warning codes have Warning severity
        for code in warning_codes:
            assert (
                RULES[code].severity == RuleSeverity.WARNING
            ), f"Rule {code} should have Warning severity"

        # Check that Style codes have Style severity
        for code in style_codes:
            assert (
                RULES[code].severity == RuleSeverity.STYLE
            ), f"Rule {code} should have Style severity"

        # Check that Security codes have Security severity
        # Note: SEC006 is an exception - it's STYLE severity (portability issue, not security)
        for code in security_codes:
            if code == "SEC006":
                assert (
                    RULES[code].severity == RuleSeverity.STYLE
                ), "SEC006 should be STYLE (portability, not security)"
            else:
                assert (
                    RULES[code].severity == RuleSeverity.SECURITY
                ), f"Rule {code} should have Security severity"

        # Check that Performance codes have Performance severity
        for code in performance_codes:
            assert (
                RULES[code].severity == RuleSeverity.PERFORMANCE
            ), f"Rule {code} should have Performance severity"

    def test_properly_quoted_set_commands_no_issues(self) -> None:
        """Test that properly quoted set commands don't trigger unsafe usage warnings."""
        content = """@echo off
set "PROPERLY_QUOTED=value with spaces"
set "ANOTHER_VAR=another safe value"
set "PATH_VAR=C:\\Program Files\\Test"
echo Done
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)

            # Filter for unsafe set command issues
            unsafe_set_issues = [
                issue for issue in issues if issue.rule.code == "SEC002"
            ]

            # Should NOT have unsafe set command issues because they're properly quoted
            assert len(unsafe_set_issues) == 0

        finally:
            os.unlink(temp_file)

    def test_quoted_set_with_variables_no_w005(self) -> None:
        """Test that variables inside quoted SET commands don't trigger W005."""
        content = """@echo off
set "VAR1=%ProgramFiles%\\Test"
set "VAR2=%SystemDrive%\\Path"
set "VAR3=%LOCALAPPDATA%\\App"
echo Done
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)

            # Filter for W005 unquoted variable warnings
            w005_issues = [issue for issue in issues if issue.rule.code == "W005"]

            # Should NOT have W005 issues for variables inside quoted SET commands
            assert len(w005_issues) == 0, (
                f"Expected no W005 issues for quoted SET commands, "
                f"but found {len(w005_issues)}: {[i.line_number for i in w005_issues]}"
            )

        finally:
            os.unlink(temp_file)

    def test_module_level_constants_validation(self) -> None:
        """Test that module-level constants are properly structured."""
        # Test DANGEROUS_COMMAND_PATTERNS structure
        assert isinstance(DANGEROUS_COMMAND_PATTERNS, list)
        assert len(DANGEROUS_COMMAND_PATTERNS) > 0
        for pattern, rule_code in DANGEROUS_COMMAND_PATTERNS:
            assert isinstance(pattern, str)
            assert isinstance(rule_code, str)
            assert len(pattern) > 0
            assert len(rule_code) > 0

        # Test RULES structure
        assert isinstance(RULES, dict)
        assert len(RULES) == RULE_COUNT

        for rule_code, rule in RULES.items():
            assert isinstance(rule_code, str)
            assert isinstance(rule, object)  # Rule dataclass instance
            assert hasattr(rule, "code")
            assert hasattr(rule, "name")
            assert hasattr(rule, "severity")
            assert hasattr(rule, "explanation")
            assert hasattr(rule, "recommendation")

        # Test RuleSeverity enum
        valid_severities = {
            RuleSeverity.ERROR,
            RuleSeverity.WARNING,
            RuleSeverity.STYLE,
            RuleSeverity.SECURITY,
            RuleSeverity.PERFORMANCE,
        }
        for rule in RULES.values():
            assert rule.severity in valid_severities

    def test_all_rules_are_emittable(self) -> None:
        """Every registered rule must be referenced by checker code."""
        from pathlib import Path

        src_root = Path(__file__).resolve().parent.parent / "src" / "blinter"
        referenced: set[str] = set()

        for pattern, rule_code in DANGEROUS_COMMAND_PATTERNS:
            referenced.add(rule_code)

        patterns_file = src_root / "patterns.py"
        patterns_text = patterns_file.read_text(encoding="utf-8")
        referenced.update(re.findall(r'"((?:E|W|S|P)\d{3}|SEC\d{3})"', patterns_text))

        rule_patterns = [
            re.compile(r'RULES\["([A-Z0-9]+)"\]'),
            re.compile(r"RULES\['([A-Z0-9]+)'\]"),
            re.compile(r'rule_code=["\']([A-Z0-9]+)["\']'),
        ]

        for py_file in src_root.rglob("*.py"):
            if py_file.name == "registry.py":
                continue
            text = py_file.read_text(encoding="utf-8")
            for compiled_pattern in rule_patterns:
                referenced.update(compiled_pattern.findall(text))

        orphan_rules = sorted(code for code in RULES if code not in referenced)
        assert not orphan_rules, (
            "Rules in registry but never emitted by checkers: "
            f"{', '.join(orphan_rules)}"
        )

    def test_complex_edge_cases(self) -> None:
        """Test various complex edge cases in batch file linting."""
        # Test file with only whitespace
        content = "   \n\t\n   \n"
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should handle gracefully
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_file)

        # Test file with very long lines
        long_content = "@echo off\n" + "echo " + "x" * 200 + "\n"
        temp_file = self.create_temp_batch_file(long_content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S020" in rule_codes  # Long line without continuation
        finally:
            os.unlink(temp_file)

    def test_variable_definition_and_usage_comprehensive(self) -> None:
        """Test comprehensive variable definition and usage scenarios."""
        content = """@echo off
set var1=value1
set VAR2=value2
set "var3=value3"
echo %var1%
echo %VAR1%
echo %var2%
echo %var3%
echo %undefined_var%
set /a numeric_var=5
echo %numeric_var%
set /p input_var=Enter value:
echo %input_var%
REM W005 now only checks IF string comparisons, so add one
if %var1%==value1 echo match
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]

            # Should detect undefined variable usage (E006)
            assert "E006" in rule_codes

            # Should detect unquoted variable usage in IF comparison (W005)
            assert (
                "W005" in rule_codes
            ), "W005 should trigger for unquoted IF string comparison"
        finally:
            os.unlink(temp_file)

    def test_comprehensive_quote_scenarios(self) -> None:
        """Test comprehensive quote handling scenarios."""
        content = """@echo off
echo "Simple quoted string"
echo "String with ""embedded"" quotes"
echo String with unmatched quote "
echo "Another unmatched quote
echo 'Single quotes'
echo Mixed "quote' types
echo "Properly closed quote"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # Should detect unmatched quotes (E009)
            assert "E009" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_special_characters_comprehensive(self) -> None:
        """Test comprehensive special character handling."""
        content = """@echo off
echo "Special & characters & in & quotes"
echo Special & character & outside & quotes
echo Escaped ^& character
echo Multiple ^& escaped ^| characters
echo "Quoted | pipe"
echo Unescaped | pipe
echo file.txt > output.txt
echo "file.txt > output.txt"
echo Escaped ^> character
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Note: The new system doesn't have a specific rule for unescaped special characters yet
            # This would be a potential enhancement
            rule_codes = [issue.rule.code for issue in issues]
            # For now, we just ensure the linter runs without crashing
            assert isinstance(rule_codes, list)
        finally:
            os.unlink(temp_file)

    def test_dangerous_commands_comprehensive_patterns(self) -> None:
        """Test that all dangerous command patterns work comprehensively."""

        # Test each pattern with multiple examples
        test_cases = [
            (r"del\s+\*/\*|\*\.?\*", ["del *.*", "DEL */*"]),
            (r"format\s+[a-z]:", ["format c:", "format a:", "format d:"]),
            (
                r"\b(ps)?shutdown\s+[/-]",
                ["shutdown /s", "SHUTDOWN -t", "psshutdown /a"],
            ),
            (r"rmdir\s+/s\s+/q\s+", ["rmdir /s /q temp", "RMDIR /S /Q folder"]),
        ]

        for pattern, examples in test_cases:
            compiled_pattern = re.compile(pattern, re.IGNORECASE)
            for example in examples:
                assert compiled_pattern.search(
                    example
                ), f"Pattern '{pattern}' should match '{example}'"

                # Test that our linter detects these
                content = f"@echo off\n{example}\n"
                temp_file = self.create_temp_batch_file(content)
                try:
                    issues = lint_batch_file(temp_file)
                    rule_codes = [issue.rule.code for issue in issues]
                    assert (
                        "SEC003" in rule_codes
                    ), f"Should detect dangerous command: {example}"
                finally:
                    os.unlink(temp_file)

    def test_bat_extension_recommendation(self) -> None:
        """Test detection of .bat extension with recommendation to use .cmd."""
        content = """@echo off
echo This is a batch file with .bat extension
exit /b 0
"""
        # Create temp file with .bat extension
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            bat_file = temp_file.name

        try:
            issues = lint_batch_file(bat_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S007" in rule_codes  # BAT extension used instead of CMD

            # Check the context message is specific about Windows versions
            s007_issues = [issue for issue in issues if issue.rule.code == "S007"]
            assert len(s007_issues) == 1
            assert "Windows 2000" in s007_issues[0].context
        finally:
            os.unlink(bat_file)

    def test_cmd_extension_no_recommendation(self) -> None:
        """Test that .cmd extension does not trigger the S007 rule."""
        content = """@echo off
echo This is a batch file with .cmd extension
exit /b 0
"""
        # Create temp file with .cmd extension
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cmd", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            cmd_file = temp_file.name

        try:
            issues = lint_batch_file(cmd_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S007" not in rule_codes  # Should NOT have BAT extension warning
        finally:
            os.unlink(cmd_file)

    def test_s007_rule_properties(self) -> None:
        """Test that the S007 rule has the correct properties."""
        rule = RULES["S007"]
        assert rule.code == "S007"
        assert rule.severity == RuleSeverity.STYLE
        assert "newer Windows" in rule.name
        assert "Windows NT" in rule.explanation or "Windows 2000" in rule.explanation
        assert "Windows 2000" in rule.recommendation
        assert "CMD files" in rule.recommendation

    def test_call_without_colon_to_label(self) -> None:
        """Test E014: Missing colon in CALL statement to label."""
        content = """@echo off
CALL mylabel
GOTO :EOF
:mylabel
ECHO In subroutine
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E014" in rule_codes  # Missing colon in CALL statement
        finally:
            os.unlink(temp_file)

    def test_call_with_colon_to_label(self) -> None:
        """Test CALL with colon to label (should not trigger E014)."""
        content = """@echo off
CALL :mylabel
GOTO :EOF
:mylabel
ECHO In subroutine
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E014" not in rule_codes  # Should not trigger missing colon error
        finally:
            os.unlink(temp_file)

    def test_call_external_program(self) -> None:
        """Test CALL to external program (should not trigger E014)."""
        content = """@echo off
CALL notepad.exe
CALL "C:\\Program Files\\MyApp\\myapp.exe"
CALL myprogram.bat
CALL dir
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E014" not in rule_codes  # Should not trigger for external programs
        finally:
            os.unlink(temp_file)

    def test_call_builtin_commands(self) -> None:
        """Test CALL to built-in commands like SET (should not trigger E014)."""
        content = """@echo off
CALL SET _result=%%%_var%%%
CALL SET "VAR=value"
CALL SETLOCAL
CALL ENDLOCAL
CALL ECHO Test
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E014" not in rule_codes  # Should not trigger for built-in commands
        finally:
            os.unlink(temp_file)

    def test_call_environment_variables(self) -> None:
        """Test CALL with environment variables (should not trigger E014)."""
        content = """@echo off
REM Test case from GitHub issue - environment variable as executable
CALL "%@EMERGENCY_JOB%"
REM Other environment variable patterns
CALL "%VARIABLE%"
CALL "%PATH_VAR%"
CALL %MY_SCRIPT%
CALL "%MY_APP%\\script.bat"
REM Mixed quotes and variables
CALL "%PROGRAM_FILES%\\app.exe" arg1 arg2
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert (
                "E014" not in rule_codes
            )  # Should not trigger for environment variables
        finally:
            os.unlink(temp_file)

    def test_call_label_still_triggers_e014(self) -> None:
        """Test that actual label calls without colon still trigger E014."""
        content = """@echo off
CALL mylabel
GOTO :EOF
:mylabel
ECHO In subroutine
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E014" in rule_codes  # Should still trigger for actual labels
        finally:
            os.unlink(temp_file)

    def test_goto_eof_without_colon(self) -> None:
        """Test E015: Missing colon in GOTO EOF statement."""
        content = """@echo off
ECHO Starting script
GOTO EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E015" in rule_codes  # Missing colon in GOTO :EOF statement
        finally:
            os.unlink(temp_file)

    def test_goto_eof_with_colon(self) -> None:
        """Test GOTO :EOF with colon (should not trigger E015)."""
        content = """@echo off
ECHO Starting script
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E015" not in rule_codes  # Should not trigger error with colon
        finally:
            os.unlink(temp_file)

    def test_consistent_goto_colon_usage(self) -> None:
        """Test S015: Consistent colon usage in GOTO statements (positive case)."""
        content = """@echo off
GOTO :label1
IF "%var%"=="test" GOTO :label2
GOTO :label3
:label1
ECHO Label 1
GOTO :EOF
:label2
ECHO Label 2
GOTO :EOF
:label3
ECHO Label 3
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S015" not in rule_codes  # Should not trigger with consistent usage
        finally:
            os.unlink(temp_file)

    def test_inconsistent_goto_colon_usage(self) -> None:
        """Test S015: Inconsistent colon usage in GOTO statements."""
        content = """@echo off
GOTO :label1
IF "%var%"=="test" GOTO label2
GOTO label3
:label1
ECHO Label 1
GOTO :EOF
:label2
ECHO Label 2
GOTO :EOF
:label3
ECHO Label 3
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "S015" in rule_codes  # Should trigger inconsistent colon usage
            s015_issues = [issue for issue in issues if issue.rule.code == "S015"]
            assert len(s015_issues) >= 1  # At least one inconsistent GOTO statement
        finally:
            os.unlink(temp_file)

    def test_mixed_goto_types_colon_rules(self) -> None:
        """Test that GOTO :EOF is handled separately from other GOTO statements."""
        content = """@echo off
GOTO label1
GOTO :EOF
GOTO label2
:label1
ECHO Label 1
GOTO :EOF
:label2
ECHO Label 2
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # Should not trigger S015 because GOTO :EOF is excluded from consistency check
            assert "S015" not in rule_codes
            # Should not trigger E015 because GOTO :EOF has colon
            assert "E015" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_dynamic_labels_ignored(self) -> None:
        """Test that dynamic labels (with variables) are ignored in colon checks."""
        content = """@echo off
SET label_suffix=test
GOTO label_%label_suffix%
GOTO :normal_label
CALL dynamic_%ERRORLEVEL%
CALL :normal_subroutine
:label_test
ECHO Dynamic label
GOTO :EOF
:normal_label
ECHO Normal label
GOTO :EOF
:normal_subroutine
ECHO Normal subroutine
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # Dynamic labels should be ignored, so no E002, E014, or S015 errors
            # for the dynamic ones, but :normal_label vs normal_label would not be consistent
            # However, since dynamic labels are mixed in, the consistency check may be affected
            # The important thing is that dynamic labels don't cause crashes
            assert (
                "E002" not in rule_codes
            )  # Dynamic labels should not trigger missing label
        finally:
            os.unlink(temp_file)

    def test_errorlevel_syntax_errors(self) -> None:
        """Test detection of invalid errorlevel comparison syntax (E016)."""
        # Test case based on user's example: if not %errorlevel% 1 should fail
        content = """@echo off
setlocal
net session >nul 2>&1
if not %errorlevel% 1 (
    echo This has invalid syntax and should trigger E016
)
endlocal
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E016" in rule_codes  # Should detect invalid errorlevel syntax

            # Find the specific E016 issue
            e016_issues = [issue for issue in issues if issue.rule.code == "E016"]
            assert len(e016_issues) > 0
            assert "missing comparison operator" in e016_issues[0].context.lower()
        finally:
            os.unlink(temp_file)

    def test_errorlevel_comparison_warnings(self) -> None:
        """Test detection of potentially confusing errorlevel comparisons (W017)."""
        # Test case based on user's example: if %errorlevel% neq 1 should warn
        content = """@echo off
setlocal
net session >nul 2>&1
if %errorlevel% neq 1 (
    echo This triggers W017 warning about semantic difference
)
endlocal
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W017" in rule_codes  # Should detect semantic difference in NEQ 1

            # Find the specific W017 issue
            w017_issues = [issue for issue in issues if issue.rule.code == "W017"]
            assert len(w017_issues) > 0
            assert (
                "behaves differently than IF NOT ERRORLEVEL 1" in w017_issues[0].context
            )
        finally:
            os.unlink(temp_file)

    def test_correct_errorlevel_syntax(self) -> None:
        """Test that correct errorlevel syntax doesn't trigger new rules."""
        # Test case showing correct usage that should NOT trigger E016 or W017
        content = """@echo off
setlocal
net session >nul 2>&1
if not errorlevel 1 (
    echo This is correct and should not trigger E016 or W017
)
if errorlevel 1 (
    echo This is also correct
)
if %errorlevel% equ 0 (
    echo This direct comparison is fine - not the problematic NEQ 1 pattern
)
if %errorlevel% neq 0 (
    echo This is also fine - checking for any error
)
endlocal
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # Should NOT trigger the new errorlevel rules
            assert "E016" not in rule_codes  # Correct syntax should not trigger error
            assert "W017" not in rule_codes  # These patterns should not trigger W017
        finally:
            os.unlink(temp_file)

    def test_edge_case_errorlevel_patterns(self) -> None:
        """Test edge cases for errorlevel checking rules."""
        content = """@echo off
if not %errorlevel% abc (
    echo This should trigger E016 for non-numeric comparison
)
if %errorlevel% neq 1 && %USER% neq "" (
    echo Complex condition with NEQ 1 should not trigger W017
)
if %errorlevel% gtr 5 (
    echo Non-NEQ-1 patterns should not trigger W017
)
endlocal
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E016" in rule_codes  # Should detect invalid syntax with non-numeric
            # Should NOT trigger W017 for complex condition or non-NEQ-1 patterns
            w017_issues = [issue for issue in issues if issue.rule.code == "W017"]
            # Should be no W017 warnings for these edge cases
            assert len(w017_issues) == 0
        finally:
            os.unlink(temp_file)

    # Enhanced rules from Wikipedia analysis (E024-E029, W026-W033, SEC014-SEC018, P015)
    def test_e024_invalid_parameter_modifier(self) -> None:
        """Test E024: Invalid parameter modifier combination."""
        content = """@ECHO OFF
echo %~q1%
echo %~xy1%
echo %~n1%
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E024" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e025_parameter_modifier_wrong_context(self) -> None:
        """Test E025: Parameter modifier on wrong context."""
        content = """@ECHO OFF
set myvar=test
echo %~nmyvar%
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E025" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e027_unc_path_cd(self) -> None:
        """Test E027: UNC path used as working directory."""
        content = """@ECHO OFF
cd \\\\server\\share\\folder
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E027" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e028_complex_quote_escaping(self) -> None:
        """Test E028: Complex quote escaping error."""
        content = """@ECHO OFF
echo "test ""bad quote"" pattern
echo \"\"\"incomplete triple quote
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E028" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e028_start_empty_title_no_error(self) -> None:
        """Test E028: START with empty window title should not trigger error."""
        content = """@ECHO OFF
START "" CMD /K %@RUNAPP% %*
START "" program.exe
START "" notepad.exe file.txt
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # Should not contain E028 for legitimate START "" patterns
            assert "E028" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e028_legitimate_empty_string_patterns(self) -> None:
        """Test E028: Legitimate empty string patterns should not trigger error."""
        content = """@ECHO OFF
REM Comparison operators with empty strings
IF "%VAR%"=="" echo Empty
IF NOT "%VAR%"=="" echo Not empty
IF "%VAR%" neq "" echo Not equal
IF "%VAR%" equ "" echo Equal
REM START with empty title
START "" notepad.exe
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # Should not contain E028 for these legitimate patterns
            assert "E028" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e028_for_f_empty_find_argument(self) -> None:
        """FOR /F find /v \"\" is an empty argument, not broken quoting."""
        content = 'for /f "delims=" %%a in (\'ver ^| find /v ""\') do echo %%a\n'
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            assert not [issue for issue in issues if issue.rule.code == "E028"]
        finally:
            os.unlink(temp_file)

    def test_e045_ver_pipe_is_not_an_argument(self) -> None:
        """A pipe after VER is the next command, not an argument."""
        content = 'ver | find "10.0" >nul\n'
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            assert not [issue for issue in issues if issue.rule.code == "E045"]
        finally:
            os.unlink(temp_file)

    def test_e002_parameter_dispatch_is_dynamic(self) -> None:
        """goto :%1 and call :%~1 cannot be resolved statically."""
        content = "goto :%1\ncall :%~1\n"
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            codes = {issue.rule.code for issue in issues}
            assert "E002" not in codes
            assert "E014" not in codes
        finally:
            os.unlink(temp_file)

    def test_e029_seta_expression_errors(self) -> None:
        """Test E029: Complex SET /A expression errors."""
        content = """@ECHO OFF
set /a result=(5+3
set /a "good=(5+3)*2"
set /a bad=5&echo
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E029" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w026_inefficient_parameter_modifiers(self) -> None:
        """Test W026: Inefficient parameter modifier usage."""
        content = """@ECHO OFF
echo %~d1% %~p1%
echo %~dpnx1%
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W026" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w027_interpreter_differences(self) -> None:
        """Test W027: Command behavior differs between interpreters."""
        content = """@ECHO OFF
append c:\\mydir
ftype txtfile=notepad.exe %1
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W027" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w028_bat_cmd_errorlevel_difference(self) -> None:
        """Test W028: .bat/.cmd errorlevel handling difference."""
        content = """@ECHO OFF
set myvar=test
if errorlevel 1 echo Error
"""
        temp_file = self.create_temp_batch_file(content, ".bat")
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W028" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w029_16bit_command(self) -> None:
        """Test W029: 16-bit command in 64-bit context."""
        content = """@ECHO OFF
call oldutil.com
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W029" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w030_non_ascii_characters(self) -> None:
        """Test W030: characters outside Code Page 437 trigger W030."""
        content = """@ECHO OFF
echo \u4f60\u597d
echo Normal text
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W030" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w030_cp437_accented_chars_no_w030(self) -> None:
        """Test W030: CP437-representable accented chars trigger W012 only."""
        content = """@ECHO OFF
echo H\u00e9llo W\u00f6rld
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W012" in rule_codes
            assert "W030" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w031_unicode_filename_operations(self) -> None:
        """Test W031: Unicode filename in batch operation."""
        content = """@ECHO OFF
copy "filé.txt" backup\\
type "résumé.doc"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W031" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w032_missing_chcp(self) -> None:
        """Test W032: Missing character set declaration."""
        content = """@ECHO OFF
echo Special chars: ñáéí
echo More content
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W032" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w032_with_chcp_no_warning(self) -> None:
        """Test W032: No warning when CHCP is present."""
        content = """@ECHO OFF
@chcp 65001 >nul
echo Special chars: ñáéí
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W032" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_w033_call_ambiguity(self) -> None:
        """Test W033: Command execution may be ambiguous."""
        content = """@ECHO OFF
call myscript
call other.bat
call :function
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W033" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec014_unc_without_elevation(self) -> None:
        """Test SEC020: UNC path without UAC elevation check."""
        content = """@ECHO OFF
copy file.txt \\\\server\\share\\
pushd \\\\server\\share\\folder
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC020" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec015_fork_bomb_detection(self) -> None:
        """Test SEC021: Fork bomb pattern detected."""
        content = """@ECHO OFF
:loop
start "" %0
goto loop
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC021" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec016_hosts_file_modification(self) -> None:
        """Test SEC022: Potential hosts file modification."""
        content = """@ECHO OFF
echo 127.0.0.1 badsite.com >> %SYSTEMROOT%\\System32\\drivers\\etc\\hosts
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC022" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec017_autorun_creation(self) -> None:
        """Test SEC023: Autorun.inf creation detected."""
        content = """@ECHO OFF
echo [Autorun] > E:\\autorun.inf
echo open=malware.exe >> E:\\autorun.inf
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC023" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec018_self_copying(self) -> None:
        """Test SEC024: Batch file copying itself to removable media."""
        content = """@ECHO OFF
copy %0 E:\\
xcopy %0 F:\\ /Y
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC024" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec021_not_flagged_in_rem_comment(self) -> None:
        """SEC021 should not fire for fork-bomb text in REM comments."""
        content = """@ECHO OFF
REM start %0 is a fork bomb pattern example
echo done
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC021" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec022_not_flagged_in_echo_documentation(self) -> None:
        """SEC022 should not fire for hosts-file text in ECHO documentation."""
        content = """@ECHO OFF
ECHO >> hosts file modification is dangerous
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC022" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_temp_path_rules_deduplicated_on_same_line(self) -> None:
        """SEC007 is suppressed when SEC012 or SEC017 fires on the same line."""
        content = """@ECHO OFF
copy x C:\\temp\\foo.tmp dest
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            line1_codes = [
                issue.rule.code for issue in issues if issue.line_number == 2
            ]
            temp_related = [
                code for code in line1_codes if code in {"SEC007", "SEC012", "SEC017"}
            ]
            assert (
                len(temp_related) == 1
            ), f"Expected one temp-path rule on line 2, got {temp_related}"
            assert temp_related[0] == "SEC012"
        finally:
            os.unlink(temp_file)

    def test_p015_inefficient_delays(self) -> None:
        """Test P015: Inefficient delay implementation."""
        content = """@ECHO OFF
ping -n 5 localhost >nul
choice /t 10 /d y >nul
timeout 5
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "P015" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_comprehensive_enhancement_functionality(self) -> None:
        """Test that all new enhancement rules can be detected."""
        content = """@ECHO OFF
REM This file tests multiple new enhancement rules
echo %~q1%
echo %~nmyvar%
cd \\\\server\\share\\
echo "bad ""quote"" pattern
set /a result=(5+3
echo %~d1% %~p1%
append c:\\mydir
call oldutil.com
echo \u4f60\u597d
copy "fil\u00e9.txt" backup\\
call myscript
copy file.txt \\\\server\\share\\
start "" %0
echo 127.0.0.1 badsite.com >> hosts
copy %0 E:\\
ping -n 5 localhost >nul
echo %1 & dir
taskkill /f /im notepad.exe
goto :retry
:retry
dir > c:\\temp\\output.txt
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = set(issue.rule.code for issue in issues)

            # Check that we detect multiple new enhancement rules
            new_rules = {
                "E024",
                "E025",
                "E027",
                "E028",
                "E029",
                "W026",
                "W027",
                "W029",
                "W030",
                "W031",
                "W033",
                "SEC014",
                "SEC015",
                "SEC016",
                "SEC018",
                "P015",
            }
            detected_new_rules = rule_codes & new_rules

            # Should detect all new rules in this comprehensive test
            assert (
                detected_new_rules == new_rules
            ), f"Missing rules: {new_rules - detected_new_rules}"

        finally:
            os.unlink(temp_file)

    def test_sec014_subroutine_parameters_no_false_positive(self) -> None:
        """Test SEC014: Parameters in subroutines should not be flagged as unescaped user input."""
        # Reproduce the issue reported on GitHub:
        # The command "SET @V1=%2& IF DEFINED @V1 SET @V1=!@V1:"=!" is part of a subroutine
        # and should NOT trigger SEC014 because %2 refers to a subroutine parameter, not user input
        content = """@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION

REM Main script
CALL :MySubroutine arg1 arg2
GOTO :EOF

:MySubroutine
REM This line should NOT trigger SEC014 because we're in a subroutine
SET @V1=%2& IF DEFINED @V1 SET @V1=!@V1:"=!
ECHO Subroutine parameter: !@V1!
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # SEC014 should NOT be triggered for parameters used in subroutines
            assert "SEC014" not in rule_codes, (
                "SEC014 should not be triggered for subroutine parameters. "
                f"Found issues: {[i for i in issues if i.rule.code == 'SEC014']}"
            )
        finally:
            os.unlink(temp_file)

    def test_sec014_main_script_parameters_should_trigger(self) -> None:
        """Test SEC014: Parameters in main script SHOULD be flagged as potential user input."""
        # Parameters used in the main script (before any labels) should still trigger SEC014
        content = """@ECHO OFF
REM Main script - parameters here are direct user input
SET VAR=%1& ECHO %VAR%
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # SEC014 SHOULD be triggered for parameters in main script
            assert (
                "SEC014" in rule_codes
            ), "SEC014 should be triggered for parameters in main script"
        finally:
            os.unlink(temp_file)

    def test_sec014_main_script_percent5_should_trigger(self) -> None:
        """Test SEC014: %5 in main script with special chars should trigger."""
        content = """@ECHO OFF
SET VAR=%5& ECHO %VAR%
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC014" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e031_invalid_multilevel_escaping(self) -> None:
        """Test E031: Invalid multilevel escaping (caret count not 2^n-1)."""
        content = """@ECHO OFF
echo test ^^& more
echo valid ^^^& more
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e031_issues = [issue for issue in issues if issue.rule.code == "E031"]
            assert len(e031_issues) == 1
            assert e031_issues[0].line_number == 2
        finally:
            os.unlink(temp_file)

    def test_e032_caret_with_trailing_spaces(self) -> None:
        """Test E032: Continuation caret must not be followed by trailing spaces."""
        content = "echo continued^ \necho done\n"
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e032_issues = [issue for issue in issues if issue.rule.code == "E032"]
            assert len(e032_issues) == 1
            assert e032_issues[0].line_number == 1
        finally:
            os.unlink(temp_file)

    def test_e033_double_percent_in_echo(self) -> None:
        """Test E033: Literal percentages in ECHO need double escaping."""
        content = """echo Progress: 50%
echo Value is %MYVAR%
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e033_issues = [issue for issue in issues if issue.rule.code == "E033"]
            assert len(e033_issues) == 1
            assert e033_issues[0].line_number == 1
        finally:
            os.unlink(temp_file)

    def test_e033_substring_and_replace_not_literal_percent(self) -> None:
        """Substring and replacement expansions are not literal percents."""
        content = "echo %date:~-4%\necho %str:~0,5%\necho %s:a=1%\n"
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            assert not [issue for issue in issues if issue.rule.code == "E033"]
        finally:
            os.unlink(temp_file)

    def test_sec014_subroutine_percent5_no_false_positive(self) -> None:
        """Test SEC014: %5 inside a subroutine should not trigger."""
        content = """@ECHO OFF
CALL :MySub fifth
GOTO :EOF

:MySub
SET @V=%5& ECHO %@V%
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC014" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_sec014_fallthrough_between_labels_should_trigger(self) -> None:
        """SEC014 fires when main code falls through into an uninvoked label block."""
        content = """@ECHO OFF
:first
echo between labels
:second
SET VAR=%1& ECHO %VAR%
GOTO :EOF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "SEC014" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_lint_empty_file_returns_no_issues(self) -> None:
        """Empty batch files produce no lint issues."""
        temp_file = self.create_temp_batch_file("")
        try:
            issues = lint_batch_file(temp_file)
            assert issues == []
        finally:
            os.unlink(temp_file)

    def test_script_with_goto_main_without_exit_should_warn(self) -> None:
        """Test W001: GOTO :main where :main lacks EXIT should still warn."""
        content = """@echo off
GOTO :main
:main
echo still running
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" in rule_codes
        finally:
            os.unlink(temp_file)

    def test_script_with_goto_main_with_exit_no_warning(self) -> None:
        """Test W001: GOTO :main where :main exits should not warn."""
        content = """@echo off
GOTO :main
:main
echo done
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W001" not in rule_codes
        finally:
            os.unlink(temp_file)

    def test_e030_for_command_string_no_false_positive(self) -> None:
        """Test E030: Carets in FOR command strings should NOT be flagged as improper escaping."""
        # Reproduces the issue found in real batch files where FOR /F IN ('command 2^>NUL')
        # was incorrectly flagged as E030
        content = """@ECHO OFF
REM Test valid caret usage in FOR command strings
FOR /F "tokens=*" %%a IN ('dir /b 2^>NUL') DO echo %%a
SET X=1& FOR /F "DELIMS=" %%d IN ('DATEINFO -t START -n END -q 2^>NUL') DO SET Y=%%d

REM Test ECHO with ASCII art (also should not trigger E030)
ECHO Test^|Test

REM Test invalid usage that SHOULD trigger E030
IF EXIST file.txt^>NUL (
    echo Found
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e030_issues = [issue for issue in issues if issue.rule.code == "E030"]
            # Should only have 1 E030 issue on line 10 (the IF statement)
            assert len(e030_issues) == 1, (
                f"Expected 1 E030 issue, but found {len(e030_issues)}. "
                f"Issues: {[(i.line_number, i.context) for i in e030_issues]}"
            )
            # Verify it's on the correct line (the IF statement with improper caret)
            assert e030_issues[0].line_number == 10, (
                f"E030 should be on line 10 (IF statement), "
                f"but was on line {e030_issues[0].line_number}"
            )
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_wmic(self) -> None:
        """Test W024: WMIC command should be flagged as deprecated."""
        content = """@ECHO OFF
WMIC os get caption
wmic process list
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            # Should detect both WMIC usages
            assert "W024" in rule_codes, "W024 should be triggered for WMIC command"
            assert (
                len(w024_issues) == 2
            ), f"Expected 2 W024 issues, got {len(w024_issues)}"
            # Check context mentions WMIC
            for issue in w024_issues:
                assert (
                    "WMIC" in issue.context.upper()
                ), f"Context should mention WMIC: {issue.context}"
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_cacls(self) -> None:
        """Test W024: CACLS command should be flagged as deprecated."""
        content = """@ECHO OFF
CACLS file.txt /E /G user:F
cacls folder /T
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            assert "W024" in rule_codes, "W024 should be triggered for CACLS command"
            assert (
                len(w024_issues) == 2
            ), f"Expected 2 W024 issues, got {len(w024_issues)}"
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_bitsadmin(self) -> None:
        """Test W024: BITSADMIN command should be flagged as deprecated."""
        content = """@ECHO OFF
BITSADMIN /transfer myDownload http://example.com/file.zip c:\\temp\\file.zip
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert (
                "W024" in rule_codes
            ), "W024 should be triggered for BITSADMIN command"
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_winrm(self) -> None:
        """Test W024: WINRM command should be flagged as deprecated."""
        content = """@ECHO OFF
WINRM quickconfig
winrm get winrm/config
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            assert "W024" in rule_codes, "W024 should be triggered for WINRM command"
            assert (
                len(w024_issues) == 2
            ), f"Expected 2 W024 issues, got {len(w024_issues)}"
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_nbtstat_not_flagged(self) -> None:
        """Test NBTSTAT is not flagged as deprecated (upstream v0.68.0 correction)."""
        content = """@ECHO OFF
NBTSTAT -n
nbtstat -c
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "W024" not in rule_codes, "NBTSTAT should not trigger W024"
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_caspol(self) -> None:
        """Test W024: CASPOL command should be flagged as deprecated."""
        content = """@ECHO OFF
CASPOL -m -ag 1 -url file://c:\\temp\\* FullTrust
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            assert "W024" in rule_codes, "W024 should be triggered for CASPOL command"
            assert "CASPOL" in w024_issues[0].context.upper()
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_commands_net_send(self) -> None:
        """Test W024: NET SEND command should be flagged as deprecated."""
        content = """@ECHO OFF
NET SEND computer "Hello"
net send * "Broadcast message"
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            assert "W024" in rule_codes, "W024 should be triggered for NET SEND command"
            assert (
                len(w024_issues) == 2
            ), f"Expected 2 W024 issues, got {len(w024_issues)}"
        finally:
            os.unlink(temp_file)

    def test_w024_deprecated_at_command(self) -> None:
        """Test W024: AT command should be flagged as deprecated."""
        content = """@ECHO OFF
AT 14:00 script.bat
at \\\\computer 10:00 backup.bat
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            assert "W024" in rule_codes, "W024 should be triggered for AT command"
            assert (
                len(w024_issues) == 2
            ), f"Expected 2 W024 issues, got {len(w024_issues)}"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_caspol_not_flagged(self) -> None:
        """Test CASPOL is deprecated (W024), not removed (E034), per upstream v0.68.0."""
        content = """@ECHO OFF
CASPOL -m -ag 1 -url file://c:\\temp\\* FullTrust
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E034" not in rule_codes, "CASPOL should not trigger E034"
            assert "W024" in rule_codes, "CASPOL should trigger W024"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_diskcomp(self) -> None:
        """Test E034: DISKCOMP command should be flagged as removed."""
        content = """@ECHO OFF
DISKCOMP A: B:
diskcomp c:\\disk1 d:\\disk2
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]
            assert "E034" in rule_codes, "E034 should be triggered for DISKCOMP command"
            assert (
                len(e034_issues) == 2
            ), f"Expected 2 E034 issues, got {len(e034_issues)}"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_append(self) -> None:
        """Test E034: APPEND command should be flagged as removed."""
        content = """@ECHO OFF
APPEND C:\\DATA
append /X:OFF
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]
            assert "E034" in rule_codes, "E034 should be triggered for APPEND command"
            assert (
                len(e034_issues) == 2
            ), f"Expected 2 E034 issues, got {len(e034_issues)}"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_browstat(self) -> None:
        """Test E034: BROWSTAT command should be flagged as removed."""
        content = """@ECHO OFF
BROWSTAT status
browstat view
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]
            assert "E034" in rule_codes, "E034 should be triggered for BROWSTAT command"
            assert (
                len(e034_issues) == 2
            ), f"Expected 2 E034 issues, got {len(e034_issues)}"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_inuse(self) -> None:
        """Test E034: INUSE command should be flagged as removed."""
        content = """@ECHO OFF
INUSE file.dll /Y
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            assert "E034" in rule_codes, "E034 should be triggered for INUSE command"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_net_print(self) -> None:
        """Test E034: NET PRINT command should be flagged as removed (but NET itself is ok)."""
        content = """@ECHO OFF
REM NET PRINT is removed
NET PRINT \\\\computer\\printer file.txt
net print \\\\server\\queue

REM But other NET commands are fine
NET USE Z: \\\\server\\share
NET VIEW \\\\computer
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]
            # Should only flag NET PRINT, not other NET commands
            assert (
                "E034" in rule_codes
            ), "E034 should be triggered for NET PRINT command"
            assert (
                len(e034_issues) == 2
            ), f"Expected 2 E034 issues (NET PRINT only), got {len(e034_issues)}"
            # Verify it's specifically for NET PRINT
            for issue in e034_issues:
                assert (
                    "PRINT" in issue.context.upper()
                ), f"Context should mention PRINT: {issue.context}"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_diskcopy(self) -> None:
        """Test E034: DISKCOPY command should be flagged as removed."""
        content = """@ECHO OFF
DISKCOPY A: B:
diskcopy c:\\source d:\\dest
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]
            assert "E034" in rule_codes, "E034 should be triggered for DISKCOPY command"
            assert (
                len(e034_issues) == 2
            ), f"Expected 2 E034 issues, got {len(e034_issues)}"
        finally:
            os.unlink(temp_file)

    def test_e034_removed_commands_streams(self) -> None:
        """Test E034: STREAMS command should be flagged as removed."""
        content = """@ECHO OFF
STREAMS -s file.txt
streams -d *.doc
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]
            assert "E034" in rule_codes, "E034 should be triggered for STREAMS command"
            assert (
                len(e034_issues) == 2
            ), f"Expected 2 E034 issues, got {len(e034_issues)}"
        finally:
            os.unlink(temp_file)

    def test_xcopy_not_deprecated(self) -> None:
        """Test that XCOPY is NOT flagged as deprecated (per requirements)."""
        content = """@ECHO OFF
XCOPY source dest /E /Y
xcopy *.txt backup\\
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # XCOPY should NOT trigger W024 or E034
            assert "W024" not in rule_codes, "XCOPY should NOT be flagged as deprecated"
            assert "E034" not in rule_codes, "XCOPY should NOT be flagged as removed"
        finally:
            os.unlink(temp_file)

    def test_net_command_not_deprecated_without_send(self) -> None:
        """Test that NET commands (other than NET SEND and NET PRINT) are not flagged."""
        content = """@ECHO OFF
NET USE Z: \\\\server\\share
NET VIEW \\\\computer
NET USER username
NET STOP servicename
net start servicename
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            # These NET commands should NOT trigger W024 or E034
            assert (
                "W024" not in rule_codes
            ), "NET (without SEND) should NOT be flagged as deprecated"
            assert (
                "E034" not in rule_codes
            ), "NET (without PRINT) should NOT be flagged as removed"
        finally:
            os.unlink(temp_file)

    def test_net_command_in_comments_not_flagged(self) -> None:
        """Test that NET commands in comments are not flagged as requiring privileges."""
        content = """@ECHO OFF
REM This script used to use NET VIEW to enumerate computers
:: We replaced NET VIEW with ADFIND
::: First we used NET VIEW, then we moved to NETDOM, but now we use ADFIND
ECHO Script completed
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            # NET commands in comments should NOT trigger SEC005
            assert "SEC005" not in rule_codes, (
                f"NET commands in comments should NOT be flagged, "
                f"but got: {[i.context for i in sec005_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_net_command_in_set_statement_not_flagged(self) -> None:
        """Test that NET commands in SET statements are not flagged as requiring privileges."""
        content = """@ECHO OFF
SET @ESSENTIAL=PRODUKEY NET PSINFO UPTIME2 SRVINFO
SET TOOLS=NET USER NET VIEW NET STOP
SET @UTILS=NETDOM NLTEST REPADMIN
ECHO Script completed
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            # NET commands in SET statements should NOT trigger SEC005
            assert "SEC005" not in rule_codes, (
                f"NET commands in SET statements should NOT be flagged, "
                f"but got: {[i.context for i in sec005_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_net_command_in_echo_not_flagged(self) -> None:
        """Test that NET commands in ECHO statements are not flagged as requiring privileges."""
        content = """@ECHO OFF
ECHO Use NET VIEW to list computers
ECHO Or use NET USER to manage users
@ECHO NET STOP servicename will stop a service
ECHO Script completed
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            rule_codes = [issue.rule.code for issue in issues]
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            # NET commands in ECHO statements should NOT trigger SEC005
            assert "SEC005" not in rule_codes, (
                f"NET commands in ECHO statements should NOT be flagged, "
                f"but got: {[i.context for i in sec005_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_actual_net_command_still_flagged(self) -> None:
        """Test that actual NET commands outside safe contexts are still flagged."""
        content = """@ECHO OFF
NET VIEW \\\\computer
NET USER username password /add
ECHO Script completed
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            # Actual NET commands should still trigger SEC005
            assert (
                len(sec005_issues) == 2
            ), f"Expected exactly 2 SEC005 issues, got {len(sec005_issues)}"
            # Check that both NET commands are flagged
            net_view_flagged = any(
                "NET command" in i.context for i in sec005_issues if i.line_number == 2
            )
            net_user_flagged = any(
                "NET command" in i.context for i in sec005_issues if i.line_number == 3
            )
            assert net_view_flagged, "NET VIEW on line 2 should be flagged"
            assert net_user_flagged, "NET USER on line 3 should be flagged"
        finally:
            os.unlink(temp_file)

    def test_sec005_no_duplicate_reports(self) -> None:
        """Privileged commands must emit exactly one SEC005 per line."""
        content = """@ECHO OFF
net user admin password /add
sc create TestService binpath=test.exe
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            assert len(sec005_issues) == 2, (
                f"Expected exactly 2 SEC005 issues, got {len(sec005_issues)}: "
                f"{[(i.line_number, i.context) for i in sec005_issues]}"
            )
            assert {issue.line_number for issue in sec005_issues} == {2, 3}
        finally:
            os.unlink(temp_file)

    def test_net_command_with_if_defined_should_be_flagged(self) -> None:
        """
        Test that NET commands wrapped in IF DEFINED are still flagged for SEC005.

        This is a regression test for GitHub issue where IF DEFINED was incorrectly
        exempting privilege-requiring commands from SEC005 warnings.
        Between v1.0.72 and v1.0.77, IF DEFINED was added to safe contexts,
        which caused NET commands after IF DEFINED to be skipped.

        IF DEFINED is just a conditional check - the actual command still needs
        admin privileges regardless of whether it's wrapped in IF DEFINED.
        """
        content = """@ECHO OFF
IF DEFINED @DLETTER NET USE %@DLETTER% /D /Y
IF DEFINED @FOLDER NET USE %@FOLDER% /D /Y
FOR /F "TOKENS=2" %%P IN ('NET USE * "!@PATH!" /PERSISTENT:NO ^| FIND /I "connected"') DO (
    SET @LETTER=%%P
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            # All three NET USE commands should trigger SEC005
            # Line 2: IF DEFINED @DLETTER NET USE
            # Line 3: IF DEFINED @FOLDER NET USE
            # Line 4: FOR loop with NET USE
            assert (
                len(sec005_issues) >= 3
            ), f"Expected at least 3 SEC005 issues, got {len(sec005_issues)}: {[(i.line_number, i.context) for i in sec005_issues]}"
            # Verify specific lines are flagged
            line_2_flagged = any(i.line_number == 2 for i in sec005_issues)
            line_3_flagged = any(i.line_number == 3 for i in sec005_issues)
            line_4_flagged = any(i.line_number == 4 for i in sec005_issues)
            assert line_2_flagged, "Line 2 (IF DEFINED ... NET USE) should be flagged"
            assert line_3_flagged, "Line 3 (IF DEFINED ... NET USE) should be flagged"
            assert line_4_flagged, "Line 4 (FOR loop with NET USE) should be flagged"
        finally:
            os.unlink(temp_file)

    def test_if_defined_with_safe_commands_not_flagged(self) -> None:
        """
        Test that IF DEFINED with truly safe commands (like ECHO) is not flagged.

        This verifies that the fix for IF DEFINED+NET USE doesn't break the
        original intent of preventing false positives for variable name checks
        with dangerous-sounding names (e.g., @MSSHUTDOWN).
        """
        content = """@ECHO OFF
REM Variable name contains "shutdown" but this is safe
IF DEFINED @MSSHUTDOWN echo Variable defined
IF DEFINED @MSFORMAT echo Another variable
SET @MSSHUTDOWN=TRUE
SET @MSFORMAT=C:\\\\Format\\\\Tool
ECHO Script completed
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # These should NOT trigger SEC003 (dangerous command without confirmation)
            # because they're just variable checks and assignments
            sec003_issues = [i for i in issues if i.rule.code == "SEC003"]
            assert (
                len(sec003_issues) == 0
            ), f"IF DEFINED with variable names should NOT trigger SEC003, got: {[(i.line_number, i.context) for i in sec003_issues]}"
        finally:
            os.unlink(temp_file)

    def test_net_use_github_issue_regression(self) -> None:
        """
        Regression test for specific GitHub issue scenario.

        Original report showed:
        v1.0.72 - Line 752, 752, 814, 814, 883, 883: Missing privilege check (SEC005)
        v1.0.77 - Line 883, 883: Missing privilege check (SEC005)

        Lines 752 and 814 were "IF DEFINED ... NET USE" and should still be flagged.
        """
        content = """@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION

REM Simulate line 752 scenario
IF DEFINED @DLETTER NET USE %@DLETTER% /D /Y
ECHO %@DIVIDER#%
ECHO:

REM Simulate line 814 scenario
IF DEFINED @DLETTER NET USE %@D_FOLDER% /D /Y
ECHO %@DIVIDER#%
ECHO:

REM Simulate line 883 scenario
FOR /F "TOKENS=2" %%P IN ('NET USE * "!@FULLPATH!" /PERSISTENT:NO ^| FIND /I "is now connected to !@FULLPATH!" ') DO (
    CALL SET %%1=%%P
    SET @DLETTER=[%%P]
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]
            # All three NET USE commands should be flagged
            line_5_flagged = any(i.line_number == 5 for i in sec005_issues)
            line_10_flagged = any(i.line_number == 10 for i in sec005_issues)
            line_15_flagged = any(i.line_number == 15 for i in sec005_issues)
            assert (
                len(sec005_issues) >= 3
            ), f"Expected at least 3 SEC005 issues, got {len(sec005_issues)}: {[(i.line_number, i.context) for i in sec005_issues]}"
            assert (
                line_5_flagged
            ), "Line 5 (IF DEFINED @DLETTER NET USE) should be flagged like in v1.0.72"
            assert (
                line_10_flagged
            ), "Line 10 (IF DEFINED @DLETTER NET USE) should be flagged like in v1.0.72"
            assert (
                line_15_flagged
            ), "Line 15 (FOR loop with NET USE) should be flagged (was always flagged)"
        finally:
            os.unlink(temp_file)

    def test_sec005_if_defined_with_echo_not_flagged(self) -> None:
        """
        Test SEC005: IF DEFINED with ECHO containing command-like text should NOT be flagged.

        This is a regression test for GitHub issue where lines like:
        "IF DEFINED @MORECMDS ECHO  Other NET USER Options ... %@MORECMDS%"
        were incorrectly flagged because "NET USER" appeared in the ECHO text.

        The ECHO command is the actual command here, not NET USER, so it should be safe.
        """
        content = """@ECHO OFF
REM These should NOT trigger SEC005 - ECHO is the actual command
IF DEFINED @MORECMDS ECHO  Other NET USER Options ... %@MORECMDS%
IF DEFINED @VAR ECHO Text with SC command mentioned
IF DEFINED @TEST ECHO NET USE information here
IF /I DEFINED @DATA ECHO REG ADD details
IF NOT DEFINED @FLAG ECHO net session check info

REM These SHOULD trigger SEC005 - actual privileged commands
IF DEFINED @DLETTER NET USE %@DLETTER% /D /Y
IF DEFINED @KEY REG ADD HKLM\\Software\\Test
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]

            # Lines 3-7 should NOT be flagged (ECHO statements)
            echo_lines_flagged = [
                i.line_number for i in sec005_issues if i.line_number in [3, 4, 5, 6, 7]
            ]
            assert (
                len(echo_lines_flagged) == 0
            ), f"ECHO statements should NOT trigger SEC005, but these lines were flagged: {echo_lines_flagged}"

            # Lines 10-11 SHOULD be flagged (actual privileged commands)
            line_10_flagged = any(i.line_number == 10 for i in sec005_issues)
            line_11_flagged = any(i.line_number == 11 for i in sec005_issues)
            assert (
                line_10_flagged
            ), "Line 10 (IF DEFINED with NET USE command) should still be flagged"
            assert (
                line_11_flagged
            ), "Line 11 (IF DEFINED with REG ADD command) should still be flagged"
        finally:
            os.unlink(temp_file)

    def test_sec005_if_defined_var_cmd_text_not_flagged(
        self,
    ) -> None:
        """
        Test SEC005: IF DEFINED with variable names containing command-like text should NOT be flagged.

        This is a regression test for GitHub issue where lines like:
        "IF DEFINED *SERVICE_SC (" were incorrectly flagged because "SC" appeared
        in the variable name.

        When IF DEFINED is followed by just a variable name and opening paren/nothing,
        it's just a variable existence check, not executing any command.
        """
        content = """@ECHO OFF
REM These should NOT trigger SEC005 - just variable name checks
IF DEFINED *SERVICE_SC (
    ECHO Service check enabled
)
IF DEFINED @NET_STATUS (
    ECHO Status available
)
IF DEFINED REG_BACKUP ECHO Backup defined
IF DEFINED NET_CONFIGURED (
    ECHO Network is configured
)

REM These SHOULD trigger SEC005 - actual privileged commands
IF DEFINED @VAR SC query service
IF DEFINED @FLAG NET USE Z: \\\\server\\share
IF DEFINED @KEY REG DELETE HKLM\\Software\\Test /f
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            sec005_issues = [i for i in issues if i.rule.code == "SEC005"]

            # Lines 3, 6, 9, 10 should NOT be flagged (just variable checks)
            var_check_lines_flagged = [
                i.line_number for i in sec005_issues if i.line_number in [3, 6, 9, 10]
            ]
            assert (
                len(var_check_lines_flagged) == 0
            ), f"IF DEFINED variable checks should NOT trigger SEC005, but these lines were flagged: {var_check_lines_flagged}"

            # Lines 15-17 SHOULD be flagged (actual privileged commands)
            line_15_flagged = any(i.line_number == 15 for i in sec005_issues)
            line_16_flagged = any(i.line_number == 16 for i in sec005_issues)
            line_17_flagged = any(i.line_number == 17 for i in sec005_issues)
            assert (
                line_15_flagged
            ), "Line 15 (IF DEFINED with SC command) should still be flagged"
            assert (
                line_16_flagged
            ), "Line 16 (IF DEFINED with NET USE command) should still be flagged"
            assert (
                line_17_flagged
            ), "Line 17 (IF DEFINED with REG DELETE command) should still be flagged"
        finally:
            os.unlink(temp_file)

    def test_deprecated_and_removed_commands_comprehensive(self) -> None:
        """Test comprehensive check of multiple deprecated and removed commands in one file."""
        content = """@ECHO OFF
REM Deprecated commands (should trigger W024)
WMIC os get caption
CACLS file.txt /E
BITSADMIN /transfer test http://test.com/file.zip c:\\file.zip
WINRM quickconfig
NET SEND computer "message"
AT 14:00 task.bat
DPATH C:\\DATA
KEYS

REM Removed commands (should trigger E034)
DISKCOMP A: B:
APPEND C:\\DATA
BROWSTAT status
INUSE file.dll
NET PRINT \\\\server\\printer file.txt
DISKCOPY A: B:
STREAMS -s file.txt

REM Valid commands (should NOT trigger W024 or E034)
NET USE Z: \\\\server\\share
XCOPY source dest /E
ROBOCOPY source dest /E
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            w024_issues = [issue for issue in issues if issue.rule.code == "W024"]
            e034_issues = [issue for issue in issues if issue.rule.code == "E034"]

            # Should have 8 deprecated command warnings (CASPOL moved from E034)
            assert len(w024_issues) == 8, (
                f"Expected 8 W024 issues (deprecated commands), got {len(w024_issues)}. "
                f"Issues: {[(i.line_number, i.context) for i in w024_issues]}"
            )

            # Should have 7 removed command errors (CASPOL no longer E034)
            assert len(e034_issues) == 7, (
                f"Expected 7 E034 issues (removed commands), got {len(e034_issues)}. "
                f"Issues: {[(i.line_number, i.context) for i in e034_issues]}"
            )
        finally:
            os.unlink(temp_file)

    def test_w035_tokens_star_is_valid(self) -> None:
        """Test W035: FOR /F with tokens=* should NOT trigger delimiter warning."""
        # GitHub issue: tokens=* is a valid pattern that doesn't need explicit delimiters
        # tokens=* means "take the entire line without tokenization"
        content = """@ECHO OFF
REM tokens=* is valid - should NOT trigger W035
FOR /F "tokens=*" %%a IN ('dir /b') DO echo %%a
FOR /F "TOKENS=*" %%b IN ('type file.txt') DO SET LINE=%%b

REM tokens=* with SKIP is also valid - should NOT trigger W035
FOR /F "SKIP=1 TOKENS=*" %%c IN ('dir /b') DO echo %%c

REM Other tokens= patterns without delims= SHOULD trigger W035
FOR /F "tokens=1,2" %%d IN ('type data.txt') DO echo %%d
FOR /F "tokens=3" %%e IN ('dir') DO SET VALUE=%%e

REM tokens= with explicit delims= should NOT trigger W035
FOR /F "tokens=1,2 delims=," %%f IN ('type csv.txt') DO echo %%f
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            w035_issues = [issue for issue in issues if issue.rule.code == "W035"]

            # Should have exactly 2 W035 issues (lines 10 and 11)
            # Lines 3, 4, and 7 use tokens=* and should NOT trigger
            # Line 14 has explicit delims= and should NOT trigger
            assert len(w035_issues) == 2, (
                f"Expected 2 W035 issues, got {len(w035_issues)}. "
                f"Issues on lines: {[i.line_number for i in w035_issues]}"
            )

            # Verify the warnings are on the correct lines
            warning_lines = sorted([i.line_number for i in w035_issues])
            assert warning_lines == [
                10,
                11,
            ], f"Expected W035 on lines [10, 11], got {warning_lines}"
        finally:
            os.unlink(temp_file)


class TestInlineSuppressions:
    """Test cases for inline lint suppression comments."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_lint_ignore_line_all_rules(self) -> None:
        """Test LINT:IGNORE-LINE suppressing all rules on same line."""
        content = """@ECHO OFF
echo lowercase  REM LINT:IGNORE-LINE
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Line 2 should have no issues because of LINT:IGNORE-LINE
            line2_issues = [i for i in issues if i.line_number == 2]
            assert len(line2_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_lint_ignore_line_specific_rules(self) -> None:
        """Test LINT:IGNORE-LINE with specific rule codes."""
        content = """@ECHO OFF
echo lowercase  REM LINT:IGNORE-LINE STY001
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should suppress STY001 but not other rules
            sty001_line2 = [
                i for i in issues if i.line_number == 2 and i.rule.code == "STY001"
            ]
            assert len(sty001_line2) == 0
        finally:
            os.unlink(temp_file)

    def test_lint_ignore_next_line_all_rules(self) -> None:
        """Test LINT:IGNORE suppressing all rules on next line."""
        content = """@ECHO OFF
REM LINT:IGNORE
echo lowercase
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Line 3 should have no issues because of LINT:IGNORE on line 2
            line3_issues = [i for i in issues if i.line_number == 3]
            assert len(line3_issues) == 0
        finally:
            os.unlink(temp_file)


class TestNestedForLoops:
    """Test cases for nested FOR loop detection."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_nested_for_loop_without_call(self) -> None:
        """Test W039: Nested FOR loop without CALL :subroutine."""
        content = """@ECHO OFF
FOR %%i IN (1 2 3) DO (
    FOR %%j IN (a b c) DO (
        ECHO %%i %%j
    )
)
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect nested FOR loop issue
            w039_issues = [i for i in issues if i.rule.code == "W039"]
            assert len(w039_issues) > 0
        finally:
            os.unlink(temp_file)


class TestRestartLogic:
    """Test cases for restart/retry logic without limits (SEC016)."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_restart_without_limit(self) -> None:
        """Test SEC016: Restart logic without failure attempt limits."""
        content = """@ECHO OFF
:retry_loop
net start MyService
IF ERRORLEVEL 1 GOTO retry_loop
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect restart without limit
            sec016_issues = [i for i in issues if i.rule.code == "SEC016"]
            assert len(sec016_issues) > 0
        finally:
            os.unlink(temp_file)

    def test_restart_with_counter(self) -> None:
        """Test restart logic with counter (safe pattern)."""
        content = """@ECHO OFF
SET counter=0
:retry_loop
SET /A counter+=1
IF %counter% GTR 5 GOTO failed
net start MyService
IF ERRORLEVEL 1 GOTO retry_loop
EXIT /b 0
:failed
ECHO Max attempts reached
EXIT /b 1
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should NOT detect SEC016 when counter is present
            sec016_issues = [i for i in issues if i.rule.code == "SEC016"]
            assert len(sec016_issues) == 0
        finally:
            os.unlink(temp_file)


class TestPerformanceRules:
    """Test cases for performance rules."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_p017_redundant_file_checks(self) -> None:
        """Test P017: Multiple redundant file existence checks."""
        content = """@ECHO OFF
IF EXIST test.txt ECHO File exists
IF EXIST test.txt ECHO Checking again
IF EXIST test.txt ECHO And again
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect redundant file checks
            p017_issues = [i for i in issues if i.rule.code == "P017"]
            assert len(p017_issues) > 0
        finally:
            os.unlink(temp_file)

    def test_p020_redundant_echo_off(self) -> None:
        """Test P020: @echo off appearing after line 1."""
        content = """REM Header comment
@ECHO OFF
ECHO This is after echo off
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect @echo off not on first line
            p020_issues = [i for i in issues if i.rule.code == "P020"]
            assert len(p020_issues) > 0
        finally:
            os.unlink(temp_file)


class TestStyleRulesExtended:
    """Test cases for extended style rules."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_s017_inconsistent_variable_case(self) -> None:
        """Test S017: Inconsistent variable name casing."""
        content = """@ECHO OFF
SET MyVar=value1
SET MYVAR=value2
SET myvar=value3
ECHO %MyVar% %MYVAR% %myvar%
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect inconsistent variable casing
            s017_issues = [i for i in issues if i.rule.code == "S017"]
            assert len(s017_issues) > 0
        finally:
            os.unlink(temp_file)

    def test_s019_magic_numbers_in_set_not_flagged(self) -> None:
        """Test S019: Numbers in SET statements should not be flagged as magic numbers."""
        content = """@ECHO OFF
SET @NMAP_TIME=00:30:00
SET @SHORT_TIME=00:10:00
SET @COREINFO_TIME=00:30:00
SET @MAX_RUN_TIME=01:00:00
SET @PRIME_LIMIT=1000000000
SET @JOBTIME=06:01:00
SET @MAX_SPAWN_TIME=00:02:00
SET @CODEPAGE_OEM=437
SET @CODEPAGE_BWCC=65001
SET /A RESULT=12345
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should NOT detect any S019 issues - these are constant definitions
            s019_issues = [i for i in issues if i.rule.code == "S019"]
            assert len(s019_issues) == 0, f"Found unexpected S019 issues: {s019_issues}"
        finally:
            os.unlink(temp_file)

    def test_s019_magic_numbers_in_other_contexts_flagged(self) -> None:
        """Test S019: Numbers in contexts other than SET statements should be flagged."""
        content = """@ECHO OFF
TIMEOUT /T 3600
PING -n 1234 localhost
IF %ERRORLEVEL% EQU 5678 GOTO error
CALL :function 9999
EXIT /b 0
:function
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect magic numbers in command arguments
            s019_issues = [i for i in issues if i.rule.code == "S019"]
            # Should flag 1234, 5678, 9999 (3600 is in common_exceptions as seconds in an hour)
            assert (
                len(s019_issues) >= 3
            ), f"Expected at least 3 S019 issues, got {len(s019_issues)}"
        finally:
            os.unlink(temp_file)

    def test_s019_magic_numbers_mixed_contexts(self) -> None:
        """Test S019: Mixed contexts - SET statements and other uses."""
        content = """@ECHO OFF
SET @TIMEOUT=3600
TIMEOUT /T 7200
SET @RETRIES=1234
PING -n 5678 localhost
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should detect magic numbers only in TIMEOUT and PING commands
            s019_issues = [i for i in issues if i.rule.code == "S019"]
            # Should flag 7200 and 5678, but NOT 3600 or 1234 (they're in SET)
            assert (
                len(s019_issues) == 2
            ), f"Expected 2 S019 issues, got {len(s019_issues)}: {s019_issues}"
            # Verify the flagged line numbers
            flagged_lines = {issue.line_number for issue in s019_issues}
            assert 3 in flagged_lines  # TIMEOUT line
            assert 5 in flagged_lines  # PING line
        finally:
            os.unlink(temp_file)

    def test_s019_set_statements_in_if_blocks(self) -> None:
        """Test S019: SET statements inside IF blocks should not flag numbers."""
        content = """@ECHO OFF
IF "%1"=="test" (
    SET @TIMEOUT=3600
    SET @RETRIES=1234
) ELSE (
    SET @TIMEOUT=7200
)
IF "%2"=="quick" (SET @DELAY=30) ELSE (SET @DELAY=300)
EXIT /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            # Should NOT detect any S019 issues - all numbers are in SET statements
            s019_issues = [i for i in issues if i.rule.code == "S019"]
            assert len(s019_issues) == 0, f"Found unexpected S019 issues: {s019_issues}"
        finally:
            os.unlink(temp_file)

    def test_w017_if_errorlevel_zero(self) -> None:
        """IF ERRORLEVEL 0 is always true and must trigger W017."""
        content = """@echo off
IF ERRORLEVEL 0 echo always true
IF ERRORLEVEL 1 echo failure
exit /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            w017 = [issue for issue in issues if issue.rule.code == "W017"]
            assert len(w017) == 1
            assert "always true" in w017[0].context.lower()
        finally:
            os.unlink(temp_file)

    def test_e036_if_exit_and_exits_typos(self) -> None:
        """IF EXIT and IF EXITS are EXISTS-family typos (E036)."""
        content = """@echo off
IF EXIT file.txt echo found
IF EXITS file.txt echo found
IF EXIST file.txt echo found
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e036 = [issue for issue in issues if issue.rule.code == "E036"]
            assert len(e036) == 2
        finally:
            os.unlink(temp_file)

    def test_e003_single_equals_and_glued_paren(self) -> None:
        """E003 flags a single = in IF and a missing space before (."""
        content = """@echo off
IF "%var%"="value" echo bad
IF 1==1(echo glued
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            e003 = [issue for issue in issues if issue.rule.code == "E003"]
            assert len(e003) >= 2
        finally:
            os.unlink(temp_file)

    def test_e003_ignores_equals_after_comparison(self) -> None:
        """A single = in the command after a valid IF comparison is not E003."""
        content = """@echo off
if "%1"=="" set X=1
if /i "%x%"=="y" echo a = b
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            codes = {issue.rule.code for issue in lint_batch_file(temp_file)}
            assert "E003" not in codes
        finally:
            os.unlink(temp_file)

    def test_e046_spaced_handle_dup_only(self) -> None:
        """E046 flags a space before & in 2> &1, not append-dup 2>>&1."""
        bad = self.create_temp_batch_file("@echo off\nDIR 2> &1\n")
        try:
            codes = {issue.rule.code for issue in lint_batch_file(bad)}
            assert "E046" in codes
        finally:
            os.unlink(bad)
        good = self.create_temp_batch_file("@echo off\nDIR 2>>&1\nDIR 2>&1\n")
        try:
            codes = {issue.rule.code for issue in lint_batch_file(good)}
            assert "E046" not in codes
        finally:
            os.unlink(good)

    def test_e043_doublecolon_inside_block(self) -> None:
        """E043 flags :: comments inside parentheses."""
        content = """@echo off
if 1==1 (
  :: bad comment
  echo ok
)
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            assert "E043" in {issue.rule.code for issue in issues}
        finally:
            os.unlink(temp_file)

    def test_w044_space_before_equals(self) -> None:
        """W044 flags SET with a space before = even without a space after."""
        content = """@echo off
set X =Hello
exit /b 0
"""
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            assert "W044" in {issue.rule.code for issue in issues}
        finally:
            os.unlink(temp_file)

    def test_w070_set_andand_bat_only(self) -> None:
        """W070 fires for SET && in .bat files and not in .cmd files."""
        bat_content = "@echo off\nset foo=bar && echo ok\n"
        bat_file = self.create_temp_batch_file(bat_content)
        try:
            bat_codes = {issue.rule.code for issue in lint_batch_file(bat_file)}
            assert "W070" in bat_codes
        finally:
            os.unlink(bat_file)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cmd", delete=False, encoding="utf-8"
        ) as cmd_file:
            cmd_file.write(bat_content)
            cmd_path = cmd_file.name
        try:
            cmd_codes = {issue.rule.code for issue in lint_batch_file(cmd_path)}
            assert "W070" not in cmd_codes
        finally:
            os.unlink(cmd_path)

    def test_w068_percent_expansion_in_block(self) -> None:
        """W068 flags %var% after SET of that var in the same block."""
        content = "@echo off\nif 1==1 (\n  set price=$350\n  echo %price%\n)\n"
        temp_file = self.create_temp_batch_file(content)
        try:
            issues = lint_batch_file(temp_file)
            w068_lines = [
                issue.line_number for issue in issues if issue.rule.code == "W068"
            ]
            assert w068_lines == [4]
        finally:
            os.unlink(temp_file)

    def test_w068_delayed_expansion_not_flagged(self) -> None:
        """W068 does not flag !var! after SET in the same block."""
        content = (
            "@echo off\n"
            "setlocal EnableDelayedExpansion\n"
            "if 1==1 (\n"
            "  set price=$350\n"
            "  echo !price!\n"
            ")\n"
            "exit /b 0\n"
        )
        temp_file = self.create_temp_batch_file(content)
        try:
            codes = {issue.rule.code for issue in lint_batch_file(temp_file)}
            assert "W068" not in codes
        finally:
            os.unlink(temp_file)
