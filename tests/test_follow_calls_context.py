"""
Tests for follow_calls variable context sharing functionality.

This module tests that when --follow-calls is enabled, variables defined in called
scripts are properly recognized as "defined" in the calling script, eliminating
false positive E006 (undefined variable) errors.
"""

import logging
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from blinter import (
    BlinterConfig,
    find_batch_files,
    lint_batch_file,
)
from blinter.cli.main import main
from blinter.engine.dependencies import (
    _build_call_dependency_graph,
    _collect_called_vars,
    _collect_vars_from_dependencies,
    _collect_vars_from_script,
    _extract_called_scripts,
    _is_within_scan_root,
    _read_batch_lines,
    _resolve_script_path,
    _try_add_dependency,
)
from blinter.io.discovery import is_path_under_root

# One behavior suite: follow-calls variable context across CLI and engine paths.
# pylint: disable=too-many-lines


class TestFollowCallsVariableContext:
    """Test variable context sharing with follow_calls enabled."""

    def test_variable_defined_in_called_script_no_error(self) -> None:
        """Variable defined in called script should not trigger E006 error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script that defines HELPER_VAR
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("SET ANOTHER_VAR=another_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script that calls helper and uses HELPER_VAR
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("ECHO Using another variable: %ANOTHER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should NOT have E006 errors for HELPER_VAR or ANOTHER_VAR
            e006_issues = [i for i in issues if i.rule.code == "E006"]
            helper_var_issues = [i for i in e006_issues if "HELPER_VAR" in i.context]
            another_var_issues = [i for i in e006_issues if "ANOTHER_VAR" in i.context]

            assert (
                len(helper_var_issues) == 0
            ), "HELPER_VAR should be recognized as defined"
            assert (
                len(another_var_issues) == 0
            ), "ANOTHER_VAR should be recognized as defined"

    def test_variable_used_before_call_triggers_error(self) -> None:
        """Variable used BEFORE the CALL should still trigger E006 error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script that defines HELPER_VAR
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script that uses HELPER_VAR BEFORE the call
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(
                    "ECHO Using helper variable BEFORE call: %HELPER_VAR%\n"
                )
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write(
                    "ECHO Using helper variable AFTER call: %HELPER_VAR%\n"
                )
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should have E006 error for line 2 (before call) but NOT for line 4 (after call)
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]

            assert len(e006_issues) == 1, "Should have exactly one E006 for HELPER_VAR"
            assert (
                e006_issues[0].line_number == 2
            ), "E006 should be on line 2 (before CALL)"

    def test_cli_variable_used_before_call_triggers_error(self) -> None:
        """CLI --follow-calls keeps position-aware undefined-variable checking."""

        with tempfile.TemporaryDirectory() as tmpdir:
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(
                    "ECHO Using helper variable BEFORE call: %HELPER_VAR%\n"
                )
                file_handle.write("CALL helper.bat\n")
                file_handle.write(
                    "ECHO Using helper variable AFTER call: %HELPER_VAR%\n"
                )
                file_handle.write("EXIT /b 0\n")

            with patch.object(sys, "argv", ["blinter", main_script, "--follow-calls"]):
                with pytest.raises(SystemExit) as exit_info:
                    main()

            assert exit_info.value.code == 0

            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert len(e006_issues) == 1
            assert e006_issues[0].line_number == 2

    def test_multiple_call_statements_accumulate_variables(self) -> None:
        """Multiple CALL statements should accumulate variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create first helper script
            helper1_script = os.path.join(tmpdir, "helper1.bat")
            with open(helper1_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET VAR1=value1\n")
                file_handle.write("EXIT /b 0\n")

            # Create second helper script
            helper2_script = os.path.join(tmpdir, "helper2.bat")
            with open(helper2_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET VAR2=value2\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script that calls both helpers
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper1_script}"\n')
                file_handle.write("ECHO After first call: %VAR1%\n")
                file_handle.write(f'CALL "{helper2_script}"\n')
                file_handle.write("ECHO After second call: %VAR1% and %VAR2%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should NOT have E006 errors for VAR1 or VAR2
            e006_issues = [i for i in issues if i.rule.code == "E006"]
            var1_issues = [i for i in e006_issues if "VAR1" in i.context]
            var2_issues = [i for i in e006_issues if "VAR2" in i.context]

            assert len(var1_issues) == 0, "VAR1 should be recognized as defined"
            assert len(var2_issues) == 0, "VAR2 should be recognized as defined"

    def test_chained_calls_on_one_line_union_variables(self) -> None:
        """CALL a.bat & CALL b.bat on one line unions variables from both scripts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper1 = os.path.join(tmpdir, "helper1.bat")
            with open(helper1, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nSET VAR1=value1\nEXIT /b 0\n")

            helper2 = os.path.join(tmpdir, "helper2.bat")
            with open(helper2, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nSET VAR2=value2\nEXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper1}" & CALL "{helper2}"\n')
                file_handle.write("ECHO %VAR1% %VAR2%\n")
                file_handle.write("EXIT /b 0\n")

            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)
            e006_issues = [i for i in issues if i.rule.code == "E006"]
            assert not [i for i in e006_issues if "VAR1" in i.context]
            assert not [i for i in e006_issues if "VAR2" in i.context]

    def test_transitive_variable_from_nested_call_no_error(self) -> None:
        """Variables defined in a transitively called script are recognized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_script = os.path.join(tmpdir, "deep.bat")
            with open(deep_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET DEEP_VAR=deep_value\n")
                file_handle.write("EXIT /b 0\n")

            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{deep_script}"\n')
                file_handle.write("EXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO Using deep variable: %DEEP_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "DEEP_VAR" in i.context
            ]
            assert (
                len(e006_issues) == 0
            ), "DEEP_VAR should be recognized via transitive CALL"

    def test_transitive_variable_respects_depth_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Variables beyond MAX_FOLLOW_CALL_DEPTH remain undefined."""
        monkeypatch.setattr("blinter.engine.dependencies.MAX_FOLLOW_CALL_DEPTH", 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            deep_script = os.path.join(tmpdir, "deep.bat")
            with open(deep_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET DEEP_VAR=deep_value\n")
                file_handle.write("EXIT /b 0\n")

            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{deep_script}"\n')
                file_handle.write("EXIT /b 0\n")

            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO Using deep variable: %DEEP_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "DEEP_VAR" in i.context
            ]
            assert len(e006_issues) == 1

    def test_transitive_variable_respects_file_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transitive variable collection stops at MAX_FOLLOW_CALL_FILES."""
        monkeypatch.setattr("blinter.engine.dependencies.MAX_FOLLOW_CALL_FILES", 1)

        helper_c = tmp_path / "c.bat"
        helper_c.write_text("@ECHO OFF\nSET C_VAR=2\n", encoding="utf-8")
        helper_b = tmp_path / "b.bat"
        helper_b.write_text(
            f'@ECHO OFF\nSET B_VAR=1\nCALL "{helper_c}"\n',
            encoding="utf-8",
        )
        main_script = tmp_path / "main.bat"
        main_script.write_text(
            f'@ECHO OFF\nCALL "{helper_b}"\nECHO %B_VAR% %C_VAR%\n',
            encoding="utf-8",
        )

        config = BlinterConfig(follow_calls=True)
        issues = lint_batch_file(str(main_script), config=config)

        e006_c = [i for i in issues if i.rule.code == "E006" and "C_VAR" in i.context]
        assert len(e006_c) == 1
        e006_b = [i for i in issues if i.rule.code == "E006" and "B_VAR" in i.context]
        assert len(e006_b) == 0

    def test_nonexistent_called_script_graceful_handling(self) -> None:
        """Should handle gracefully when called script doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create main script that calls a nonexistent script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write('CALL "nonexistent.bat"\n')
                file_handle.write("ECHO Using undefined var: %UNDEFINED_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should still work and detect undefined variable
            e006_issues = [
                i
                for i in issues
                if i.rule.code == "E006" and "UNDEFINED_VAR" in i.context
            ]
            assert (
                len(e006_issues) == 1
            ), "Should detect undefined variable even when called script doesn't exist"

    def test_follow_calls_disabled_shows_undefined_error(self) -> None:
        """Without follow_calls, should show E006 for variables from called scripts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint WITHOUT follow_calls
            config = BlinterConfig(follow_calls=False)
            issues = lint_batch_file(main_script, config=config)

            # Should have E006 error for HELPER_VAR
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert (
                len(e006_issues) == 1
            ), "Should have E006 when follow_calls is disabled"

    def test_circular_call_handling(self) -> None:
        """Should handle circular calls gracefully (script calls itself)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create script that calls itself (circular reference)
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write('IF "%1"=="" EXIT /b 0\n')
                file_handle.write(f'CALL "{main_script}" done\n')
                file_handle.write("EXIT /b 0\n")

            # Should not crash or hang
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Just verify it completes without error
            assert isinstance(issues, list)

    def test_relative_path_call(self) -> None:
        """Should handle relative paths in CALL statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script with relative path call
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("CALL helper.bat\n")  # Relative path
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should NOT have E006 error for HELPER_VAR
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert len(e006_issues) == 0, "Should handle relative path calls"

    def test_percent_dp0_path_call(self) -> None:
        """Should handle %~dp0 syntax in CALL statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create subdirectory
            subdir = os.path.join(tmpdir, "scripts")
            os.makedirs(subdir, exist_ok=True)

            # Create called script in subdirectory
            helper_script = os.path.join(subdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script with %~dp0 path
            main_script = os.path.join(subdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write('CALL "%~dp0helper.bat"\n')  # %~dp0 syntax
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should NOT have E006 error for HELPER_VAR
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert len(e006_issues) == 0, "Should handle %~dp0 syntax in calls"

    def test_unicode_encoding_in_called_script(self) -> None:
        """Should handle Unicode encoding issues gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script with potential encoding issues
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("REM This is a comment with unicode: 你好\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should handle Unicode gracefully and recognize the variable
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert len(e006_issues) == 0, "Should handle Unicode in called scripts"

    def test_call_in_comment_not_processed(self) -> None:
        """CALL statements in comments should be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script with CALL in comment
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'REM CALL "{helper_script}"\n')  # CALL in comment
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should have E006 error since CALL in comment shouldn't count
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert len(e006_issues) == 1, "CALL in comment should be ignored"

    def test_multiple_variables_from_single_call(self) -> None:
        """Single called script defining multiple variables should work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script with multiple variables
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET VAR1=value1\n")
                file_handle.write("SET VAR2=value2\n")
                file_handle.write("SET VAR3=value3\n")
                file_handle.write('SET "VAR4=value with spaces"\n')
                file_handle.write("SET /A VAR5=10+20\n")
                file_handle.write("SET /P VAR6=Enter value:\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO %VAR1% %VAR2% %VAR3%\n")
                file_handle.write("ECHO %VAR4% %VAR5% %VAR6%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should NOT have E006 errors for any of these variables
            e006_issues = [i for i in issues if i.rule.code == "E006"]
            var_issues = [
                i
                for i in e006_issues
                if any(
                    var in i.context
                    for var in ["VAR1", "VAR2", "VAR3", "VAR4", "VAR5", "VAR6"]
                )
            ]

            assert (
                len(var_issues) == 0
            ), "All variables from called script should be recognized"

    def test_cmd_extension_call(self) -> None:
        """Should work with .cmd extension as well as .bat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script with .cmd extension
            helper_script = os.path.join(tmpdir, "helper.cmd")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write("SET HELPER_VAR=helper_value\n")
                file_handle.write("EXIT /b 0\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO Using helper variable: %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            # Lint with follow_calls enabled
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)

            # Should NOT have E006 error for HELPER_VAR
            e006_issues = [
                i for i in issues if i.rule.code == "E006" and "HELPER_VAR" in i.context
            ]
            assert len(e006_issues) == 0, "Should handle .cmd extension"


class TestFollowCallsEdgeCases:
    """Test edge cases and error handling for follow_calls."""

    def test_empty_called_script(self) -> None:
        """Should handle empty called scripts gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty called script
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("")  # Empty file

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO test\n")
                file_handle.write("EXIT /b 0\n")

            # Should not crash
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)
            assert isinstance(issues, list)

    def test_called_script_with_only_comments(self) -> None:
        """Should handle called scripts with only comments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script with only comments
            helper_script = os.path.join(tmpdir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("REM This is a comment\n")
                file_handle.write(":: Another comment\n")
                file_handle.write("REM More comments\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO test\n")
                file_handle.write("EXIT /b 0\n")

            # Should not crash
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)
            assert isinstance(issues, list)

    def test_permission_error_on_called_script(self) -> None:
        """Should handle permission errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create called script (we'll simulate permission error by not creating it)
            helper_script = os.path.join(tmpdir, "nonexistent_helper.bat")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO test\n")
                file_handle.write("EXIT /b 0\n")

            # Should not crash even if called script doesn't exist
            config = BlinterConfig(follow_calls=True)
            issues = lint_batch_file(main_script, config=config)
            assert isinstance(issues, list)


class TestScanRootSandbox:
    """Test scan_root limits for follow_calls file access."""

    def test_scan_root_blocks_outside_called_script_vars(self) -> None:
        """Variables from scripts outside scan_root must not be collected."""
        with tempfile.TemporaryDirectory() as outer:
            outside_dir = os.path.join(outer, "outside")
            scan_dir = os.path.join(outer, "project")
            os.makedirs(outside_dir)
            os.makedirs(scan_dir)

            outside_script = os.path.join(outside_dir, "outside.bat")
            with open(outside_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("SET OUTSIDE_VAR=outside_value\n")

            main_script = os.path.join(scan_dir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write('CALL "..\\outside\\outside.bat"\n')
                file_handle.write("ECHO %OUTSIDE_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            config = BlinterConfig(
                follow_calls=True,
                scan_root=scan_dir,
            )
            issues = lint_batch_file(main_script, config=config)

            outside_var_issues = [
                issue
                for issue in issues
                if issue.rule.code == "E006" and "OUTSIDE_VAR" in issue.context
            ]
            assert len(outside_var_issues) > 0

    def test_scan_root_allows_inside_called_script_vars(self) -> None:
        """Variables from scripts inside scan_root are still collected."""
        with tempfile.TemporaryDirectory() as scan_dir:
            helper_script = os.path.join(scan_dir, "helper.bat")
            with open(helper_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("SET HELPER_VAR=helper_value\n")

            main_script = os.path.join(scan_dir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")
                file_handle.write(f'CALL "{helper_script}"\n')
                file_handle.write("ECHO %HELPER_VAR%\n")
                file_handle.write("EXIT /b 0\n")

            config = BlinterConfig(
                follow_calls=True,
                scan_root=scan_dir,
            )
            issues = lint_batch_file(main_script, config=config)

            helper_var_issues = [
                issue
                for issue in issues
                if issue.rule.code == "E006" and "HELPER_VAR" in issue.context
            ]
            assert len(helper_var_issues) == 0

    def test_extract_called_scripts_respects_scan_root(self) -> None:
        """_extract_called_scripts skips targets outside scan_root."""
        with tempfile.TemporaryDirectory() as outer:
            outside_dir = os.path.join(outer, "outside")
            scan_dir = os.path.join(outer, "project")
            os.makedirs(outside_dir)
            os.makedirs(scan_dir)

            outside_script = os.path.join(outside_dir, "outside.bat")
            with open(outside_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")

            main_script = os.path.join(scan_dir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write('CALL "..\\outside\\outside.bat"\n')

            called = _extract_called_scripts(Path(main_script), scan_root=scan_dir)
            assert not called

            inside_script = os.path.join(scan_dir, "helper.bat")
            with open(inside_script, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\n")

            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write('CALL "helper.bat"\n')

            called_inside = _extract_called_scripts(
                Path(main_script), scan_root=scan_dir
            )
            assert len(called_inside) == 1
            assert called_inside[0].name == "helper.bat"


class TestSymlinkSandbox:  # pylint: disable=too-few-public-methods
    """Test scan_root containment against symlink escape."""

    def test_is_path_under_root_rejects_symlink_outside_scan_root(self) -> None:
        """Symlinks pointing outside scan_root must not be treated as inside."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside_dir = Path(outer) / "outside"
            scan_root.mkdir()
            outside_dir.mkdir()

            outside_file = outside_dir / "secret.bat"
            outside_file.write_text("@ECHO OFF\n", encoding="utf-8")

            real_file = scan_root / "real.bat"
            real_file.write_text("@ECHO OFF\n", encoding="utf-8")

            escape_link = scan_root / "escape.bat"
            try:
                os.symlink(outside_file, escape_link)
            except OSError:
                pytest.skip("symlink creation not supported on this platform")

            assert is_path_under_root(real_file, scan_root) is True
            assert is_path_under_root(escape_link, scan_root) is False

    def test_extract_called_scripts_skips_symlink_outside_scan_root(self) -> None:
        """CALL targets reached via symlinks outside scan_root are ignored."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside_dir = Path(outer) / "outside"
            scan_root.mkdir()
            outside_dir.mkdir()

            outside_script = outside_dir / "outside.bat"
            outside_script.write_text("@ECHO OFF\n", encoding="utf-8")

            escape_link = scan_root / "outside.bat"
            try:
                os.symlink(outside_script, escape_link)
            except OSError:
                pytest.skip("symlink creation not supported on this platform")

            main_script = scan_root / "main.bat"
            main_script.write_text('CALL "outside.bat"\n', encoding="utf-8")

            called = _extract_called_scripts(
                main_script, scan_root=str(scan_root.resolve())
            )
            assert not called

    def test_is_path_under_root_returns_false_for_path_outside_root(self) -> None:
        """Paths outside scan_root must not be treated as inside."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside_dir = Path(outer) / "outside"
            scan_root.mkdir()
            outside_dir.mkdir()
            outside_file = outside_dir / "script.bat"
            outside_file.write_text("@ECHO OFF\n", encoding="utf-8")
            assert is_path_under_root(outside_file, scan_root) is False

    def test_is_path_under_root_accepts_symlink_inside_scan_root(
        self, tmp_path: Path
    ) -> None:
        """Symlinks that resolve inside scan_root are accepted."""
        scan_root = tmp_path / "project"
        scan_root.mkdir()
        real_file = scan_root / "real.bat"
        real_file.write_text("@echo off\n", encoding="utf-8")
        link = scan_root / "link.bat"
        try:
            os.symlink(real_file.name, link)
        except OSError:
            pytest.skip("symlink creation not supported on this platform")

        assert is_path_under_root(link, scan_root) is True

    def test_find_batch_files_filters_outside_scan_root(self) -> None:
        """find_batch_files with root skips files outside scan_root."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside_dir = Path(outer) / "outside"
            scan_root.mkdir()
            outside_dir.mkdir()
            inside = scan_root / "inside.bat"
            inside.write_text("@ECHO OFF\n", encoding="utf-8")
            outside = outside_dir / "outside.bat"
            outside.write_text("@ECHO OFF\n", encoding="utf-8")

            found = find_batch_files(scan_root, root=scan_root)
            names = {path.name for path in found}
            assert "inside.bat" in names
            assert "outside.bat" not in names


class TestCallDependencyGraph:  # pylint: disable=too-few-public-methods
    """Test CALL dependency graph construction."""

    def test_build_call_dependency_graph_includes_transitive_deps(self) -> None:
        """Transitive CALL dependencies are included in the graph."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper_c = os.path.join(tmpdir, "helper_c.bat")
            with open(helper_c, "w", encoding="utf-8") as file_handle:
                file_handle.write("@ECHO OFF\nSET C_VAR=value\n")

            helper_b = os.path.join(tmpdir, "helper_b.bat")
            with open(helper_b, "w", encoding="utf-8") as file_handle:
                file_handle.write(f'CALL "{helper_c}"\n')

            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as file_handle:
                file_handle.write(f'CALL "{helper_b}"\n')

            graph = _build_call_dependency_graph(
                [Path(main_script), Path(helper_b), Path(helper_c)],
                scan_root=tmpdir,
            )
            main_resolved = Path(main_script).resolve()
            deps = graph.get(main_resolved, set())
            dep_names = {path.name for path in deps}
            assert "helper_b.bat" in dep_names
            assert "helper_c.bat" in dep_names

    def test_build_call_dependency_graph_handles_read_failure(self) -> None:
        """Unreadable batch files produce empty dependency sets."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write("@ECHO OFF\n")
            temp_path = Path(temp_file.name)

        temp_path.unlink()
        graph = _build_call_dependency_graph([temp_path])
        assert graph.get(temp_path.resolve(), set()) == set()

    def test_build_call_dependency_graph_handles_cyclic_calls(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cyclic CALL graphs include both directions of the cycle."""

        with tempfile.TemporaryDirectory() as tmpdir:
            script_a = Path(tmpdir) / "a.bat"
            script_b = Path(tmpdir) / "b.bat"
            script_a.write_text(
                f'@ECHO OFF\nCALL "{script_b.name}"\n', encoding="utf-8"
            )
            script_b.write_text(
                f'@ECHO OFF\nCALL "{script_a.name}"\n', encoding="utf-8"
            )

            with caplog.at_level(logging.WARNING, logger="blinter"):
                graph = _build_call_dependency_graph(
                    [script_a, script_b], scan_root=tmpdir
                )
            a_deps = graph[script_a.resolve()]
            b_deps = graph[script_b.resolve()]
            assert script_b.resolve() in a_deps
            assert script_a.resolve() in b_deps
            assert any(
                "Circular CALL dependency" in record.message
                for record in caplog.records
            )

    def test_extract_called_scripts_spaced_path(self) -> None:
        """CALL with extra spacing before script path is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper = Path(tmpdir) / "helper.bat"
            helper.write_text("@ECHO OFF\n", encoding="utf-8")
            main_script = Path(tmpdir) / "main.bat"
            main_script.write_text("CALL  helper.bat\n", encoding="utf-8")

            called = _extract_called_scripts(main_script, scan_root=tmpdir)
            assert len(called) == 1
            assert called[0].name == "helper.bat"


class TestFollowCallsLimits:
    """Test follow_calls traversal depth and file-count limits."""

    def test_dependency_graph_respects_depth_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transitive CALL resolution stops at MAX_FOLLOW_CALL_DEPTH."""
        monkeypatch.setattr(
            "blinter.engine.dependencies.MAX_FOLLOW_CALL_DEPTH",
            0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script_c = Path(tmpdir) / "c.bat"
            script_c.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text(f'CALL "{script_c}"\n', encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(f'CALL "{script_b}"\n', encoding="utf-8")

            graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)
            deps = graph[script_a.resolve()]
            assert script_b.resolve() in deps
            assert script_c.resolve() not in deps

    def test_dependency_graph_respects_file_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CALL graph traversal stops at MAX_FOLLOW_CALL_FILES."""
        monkeypatch.setattr(
            "blinter.engine.dependencies.MAX_FOLLOW_CALL_FILES",
            1,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_c = Path(tmpdir) / "c.bat"
            script_c.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(
                f'CALL "{script_b}"\nCALL "{script_c}"\n',
                encoding="utf-8",
            )

            graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)
            deps = graph[script_a.resolve()]
            assert len(deps) <= 1

    def test_dependency_graph_handles_mutual_circular_calls(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Mutual CALL cycles are detected and traversal stops safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_a = Path(tmpdir) / "a.bat"
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text(f'CALL "{script_a}"\n', encoding="utf-8")
            script_a.write_text(f'CALL "{script_b}"\n', encoding="utf-8")

            with caplog.at_level("WARNING", logger="blinter"):
                graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)

            assert script_b.resolve() in graph[script_a.resolve()]
            assert any(
                "Circular CALL dependency" in record.message
                for record in caplog.records
            )

    def test_dependency_graph_includes_transitive_dependencies(self) -> None:
        """CALL dependency graph includes transitive dependencies for root files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_d = Path(tmpdir) / "d.bat"
            script_d.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text(f'CALL "{script_d}"\n', encoding="utf-8")
            script_c = Path(tmpdir) / "c.bat"
            script_c.write_text(f'CALL "{script_d}"\n', encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(
                f'CALL "{script_b}"\nCALL "{script_c}"\n',
                encoding="utf-8",
            )

            graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)
            deps = graph[script_a.resolve()]
            assert script_b.resolve() in deps
            assert script_c.resolve() in deps
            assert script_d.resolve() in deps

    def test_dependency_graph_includes_direct_call_targets(self) -> None:
        """CALL dependency graph includes immediate CALL targets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(f'CALL "{script_b}"\n', encoding="utf-8")

            graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)
            deps = graph[script_a.resolve()]
            assert script_b.resolve() in deps
            assert len(deps) == 1

    def test_dependency_graph_memoizes_shared_transitive_dependencies(self) -> None:
        """Diamond CALL graphs reuse memoized transitive dependency sets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_d = Path(tmpdir) / "d.bat"
            script_d.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text(f'CALL "{script_d}"\n', encoding="utf-8")
            script_c = Path(tmpdir) / "c.bat"
            script_c.write_text(f'CALL "{script_d}"\n', encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(
                f'CALL "{script_b}"\nCALL "{script_c}"\n',
                encoding="utf-8",
            )

            graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)
            deps = graph[script_a.resolve()]
            assert deps == {
                script_b.resolve(),
                script_c.resolve(),
                script_d.resolve(),
            }

    def test_dependency_graph_lazy_resolves_transitive_callees(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transitive callees not in the initial file list are resolved lazily."""
        monkeypatch.setattr(
            "blinter.engine.dependencies.MAX_FOLLOW_CALL_DEPTH",
            2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script_c = Path(tmpdir) / "c.bat"
            script_c.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text(f'CALL "{script_c}"\n', encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(f'CALL "{script_b}"\n', encoding="utf-8")

            graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)
            deps = graph[script_a.resolve()]
            assert script_b.resolve() in deps
            assert script_c.resolve() in deps

    def test_dependency_graph_warns_when_file_limit_truncates(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CALL graph traversal logs a warning when MAX_FOLLOW_CALL_FILES is hit."""

        monkeypatch.setattr(
            "blinter.engine.dependencies.MAX_FOLLOW_CALL_FILES",
            2,
        )
        monkeypatch.setattr(
            "blinter.engine.dependencies.MAX_FOLLOW_CALL_DEPTH",
            3,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script_d = Path(tmpdir) / "d.bat"
            script_d.write_text("@ECHO OFF\nEXIT /b 0\n", encoding="utf-8")
            script_c = Path(tmpdir) / "c.bat"
            script_c.write_text(f'CALL "{script_d}"\n', encoding="utf-8")
            script_b = Path(tmpdir) / "b.bat"
            script_b.write_text(f'CALL "{script_c}"\n', encoding="utf-8")
            script_a = Path(tmpdir) / "a.bat"
            script_a.write_text(f'CALL "{script_b}"\n', encoding="utf-8")

            with caplog.at_level(logging.WARNING, logger="blinter"):
                graph = _build_call_dependency_graph([script_a], scan_root=tmpdir)

            deps = graph[script_a.resolve()]
            assert len(deps) <= 2
            assert any(
                "CALL dependency file limit" in record.message
                for record in caplog.records
            )


class TestDependenciesInternals:
    """Direct unit tests for dependency helper functions."""

    def test_is_within_scan_root_none_returns_true(self, tmp_path: Path) -> None:
        """Unset scan_root allows any path."""
        assert _is_within_scan_root(tmp_path / "script.bat", None) is True

    def test_is_within_scan_root_rejects_outside_path(self) -> None:
        """Paths outside scan_root are rejected."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside = Path(outer) / "outside.bat"
            scan_root.mkdir()
            outside.write_text("@ECHO OFF\n", encoding="utf-8")
            assert _is_within_scan_root(outside, str(scan_root)) is False

    def test_read_batch_lines_returns_supplied_lines(self, tmp_path: Path) -> None:
        """Pre-supplied lines are returned without disk read."""
        script = tmp_path / "script.bat"
        supplied = ["@ECHO OFF\n", "EXIT /b 0\n"]
        assert _read_batch_lines(script, lines=supplied) == supplied

    def test_read_batch_lines_reads_from_disk(self, tmp_path: Path) -> None:
        """Lines are read from disk when not pre-supplied."""
        script = tmp_path / "script.bat"
        script.write_text("@ECHO OFF\nSET VAR=1\n", encoding="utf-8")
        lines = _read_batch_lines(script)
        assert lines is not None
        assert "SET VAR=1" in lines[1]

    def test_read_batch_lines_returns_none_on_missing_file(
        self, tmp_path: Path
    ) -> None:
        """Unreadable paths return None instead of raising."""
        missing = tmp_path / "missing.bat"
        assert _read_batch_lines(missing) is None

    def test_resolve_script_path_relative_in_batch_dir(self, tmp_path: Path) -> None:
        """Relative CALL targets resolve against the caller directory."""
        resolved = _resolve_script_path("helper.bat", tmp_path)
        assert resolved == tmp_path / "helper.bat"

    def test_resolve_script_path_dp0_expansion(self, tmp_path: Path) -> None:
        """%~dp0 expands to the batch file directory."""
        resolved = _resolve_script_path("%~dp0helper.bat", tmp_path)
        assert resolved == tmp_path / "helper.bat"

    def test_resolve_script_path_outside_scan_root_returns_none(self) -> None:
        """Absolute paths outside scan_root are rejected."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside = Path(outer) / "outside.bat"
            scan_root.mkdir()
            outside.write_text("@ECHO OFF\n", encoding="utf-8")
            resolved = _resolve_script_path(
                str(outside), scan_root, scan_root=str(scan_root)
            )
            assert resolved is None

    def test_collect_called_vars_maps_call_line_to_script_vars(
        self, tmp_path: Path
    ) -> None:
        """Variables from called scripts are keyed by CALL line number."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nSET HELPER_VAR=value\n", encoding="utf-8")
        main_script = tmp_path / "main.bat"
        main_script.write_text(
            f'@ECHO OFF\nCALL "{helper}"\nECHO %HELPER_VAR%\n',
            encoding="utf-8",
        )

        called_vars = _collect_called_vars(main_script, scan_root=str(tmp_path))
        assert 2 in called_vars
        assert "HELPER_VAR" in called_vars[2]

    def test_follow_calls_resolves_backslash_subdirectory(self, tmp_path: Path) -> None:
        """CALL targets written with backslashes resolve in a subdirectory."""
        lib = tmp_path / "lib"
        lib.mkdir()
        helper = lib / "helper.cmd"
        helper.write_text("@ECHO OFF\nSET LIB_VAR=1\n", encoding="utf-8")
        main_script = tmp_path / "main.bat"
        main_script.write_text(
            "@ECHO OFF\nCALL lib\\helper.cmd\nCALL .\\lib\\helper.cmd\n",
            encoding="utf-8",
        )
        called_vars = _collect_called_vars(main_script, scan_root=str(tmp_path))
        assert any("LIB_VAR" in names for names in called_vars.values())

    def test_read_batch_lines_logs_warning_for_called_script(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unreadable CALL targets log warnings when follow-calls reads them."""

        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nSET HELPER_VAR=1\n", encoding="utf-8")
        main_script = tmp_path / "main.bat"
        main_script.write_text(f'CALL "{helper}"\n', encoding="utf-8")
        helper.unlink()

        with caplog.at_level(logging.WARNING, logger="blinter"):
            called_vars = _collect_called_vars(main_script, scan_root=str(tmp_path))

        assert not called_vars
        assert any("Could not read" in record.message for record in caplog.records)

    def test_collect_vars_from_script_logs_debug_on_resolve_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Path resolution failures during follow-calls are logged at DEBUG."""

        main_script = tmp_path / "main.bat"
        main_script.write_text('CALL "helper.bat"\n', encoding="utf-8")
        script_path = MagicMock()
        script_path.exists.return_value = True
        script_path.is_file.return_value = True
        script_path.resolve.side_effect = OSError("permission denied")

        with caplog.at_level(logging.DEBUG, logger="blinter"):
            collected = _collect_vars_from_script(
                script_path,
                main_script.resolve(),
                scan_root=str(tmp_path),
            )

        assert collected == set()
        assert any(
            "Could not resolve called script path" in record.message
            for record in caplog.records
        )

    def test_collect_called_vars_is_position_aware_with_call_line(
        self, tmp_path: Path
    ) -> None:
        """Variables from CALL targets are keyed by CALL line, not line 0."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\nSET GRAPH_VAR=value\n", encoding="utf-8")
        main_script = tmp_path / "main.bat"
        main_script.write_text(
            f'@ECHO OFF\nCALL "{helper}"\n',
            encoding="utf-8",
        )

        called_vars = _collect_called_vars(main_script, scan_root=str(tmp_path))
        assert 0 not in called_vars
        assert 2 in called_vars
        assert "GRAPH_VAR" in called_vars[2]

    def test_extract_called_scripts_skips_self_call(self, tmp_path: Path) -> None:
        """CALL to the same script is not listed as a dependency."""
        script = tmp_path / "loop.bat"
        script.write_text(f'@ECHO OFF\nCALL "{script}"\n', encoding="utf-8")
        called = _extract_called_scripts(script, scan_root=str(tmp_path))
        assert not called

    def test_read_batch_lines_returns_none_on_validate_error(
        self, tmp_path: Path
    ) -> None:
        """Validation failures during read return None."""
        script = tmp_path / "broken.bat"
        with patch(
            "blinter.engine.dependencies._validate_and_read_file",
            side_effect=ValueError("too large"),
        ):
            assert _read_batch_lines(script) is None

    def test_resolve_script_path_d0_expansion(self, tmp_path: Path) -> None:
        """%~d0 expands to the drive letter of the batch file directory."""
        resolved = _resolve_script_path(
            "%~d0\\subdir\\helper.bat", tmp_path / "scripts"
        )
        expected_drive = (tmp_path / "scripts").drive
        assert resolved == Path(f"{expected_drive}/subdir/helper.bat")

    def test_extract_called_scripts_deduplicates(self, tmp_path: Path) -> None:
        """Duplicate CALL targets appear only once in the result list."""
        helper = tmp_path / "helper.bat"
        helper.write_text("@ECHO OFF\n", encoding="utf-8")
        main_script = tmp_path / "main.bat"
        main_script.write_text(
            f'CALL "{helper}"\nCALL "{helper}"\n',
            encoding="utf-8",
        )
        called = _extract_called_scripts(main_script, scan_root=str(tmp_path))
        assert len(called) == 1
        assert called[0].resolve() == helper.resolve()

    def test_try_add_dependency_skips_outside_scan_root(self) -> None:
        """Dependencies outside scan_root are not added."""
        with tempfile.TemporaryDirectory() as outer:
            scan_root = Path(outer) / "project"
            outside = Path(outer) / "outside.bat"
            scan_root.mkdir()
            outside.write_text("@ECHO OFF\n", encoding="utf-8")
            deps: set[Path] = set()
            _try_add_dependency(
                outside,
                (scan_root / "main.bat").resolve(),
                deps,
                scan_root=str(scan_root),
            )
            assert deps == set()

    def test_collect_vars_from_dependencies_respects_file_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Variable collection stops at MAX_FOLLOW_CALL_FILES."""
        monkeypatch.setattr(
            "blinter.engine.dependencies.MAX_FOLLOW_CALL_FILES",
            1,
        )
        helper_b = tmp_path / "b.bat"
        helper_b.write_text("@ECHO OFF\nSET B_VAR=1\n", encoding="utf-8")
        helper_c = tmp_path / "c.bat"
        helper_c.write_text("@ECHO OFF\nSET C_VAR=2\n", encoding="utf-8")
        main_script = tmp_path / "main.bat"
        main_script.write_text(
            f'CALL "{helper_b}"\nCALL "{helper_c}"\n',
            encoding="utf-8",
        )
        graph = _build_call_dependency_graph([main_script], scan_root=str(tmp_path))
        called_vars = _collect_vars_from_dependencies(
            main_script.resolve(),
            graph,
            scan_root=str(tmp_path),
        )
        assert 0 in called_vars
        collected = called_vars[0]
        assert ("B_VAR" in collected) ^ ("C_VAR" in collected)
        assert not ("B_VAR" in collected and "C_VAR" in collected)
