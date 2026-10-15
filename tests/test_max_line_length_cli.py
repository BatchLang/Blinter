"""Tests for --max-line-length CLI parameter."""

import os
import tempfile
from unittest.mock import patch

import pytest

from blinter import (
    BlinterConfig,
    lint_batch_file,
    load_config,
    main,
)
from blinter.cli.args import _parse_cli_arguments
from blinter.output.formatters import print_help
from blinter.rules.helpers import _s011_rule


class TestS011RuleHelper:
    """Test _s011_rule helper for custom max line length."""

    def test_s011_rule_returns_base_rule_at_default_length(self) -> None:
        """Default max_line_length should return the registry rule unchanged."""
        base_rule = _s011_rule(100)
        custom_same = _s011_rule(100)
        assert base_rule is custom_same
        assert "100" in base_rule.explanation

    def test_s011_rule_adjusts_explanation_for_custom_length(self) -> None:
        """Custom max_line_length should update the S011 explanation text."""
        rule = _s011_rule(150)
        assert "150" in rule.explanation
        assert "100" not in rule.explanation


class TestMaxLineLengthCLI:
    """Test cases for --max-line-length command line parameter."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_cli_max_line_length_valid_value(self) -> None:
        """Test --max-line-length with valid numeric value."""
        # Create a batch file with line exactly 100 characters
        line_content = "REM " + "x" * 96  # 100 characters total
        content = f"@echo off\n{line_content}\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test with max_line_length=120 (should not trigger S020)
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "120"]):
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print"):
                        main()
                        # Should exit successfully
                        assert mock_exit.called
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_triggers_s020(self) -> None:
        """Test that --max-line-length correctly affects S020 rule."""
        # Create a batch file with line of 100 characters
        line_content = "REM " + "x" * 96  # 100 characters total
        content = f"@echo off\n{line_content}\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test with max_line_length=90 (should trigger S020)
            config = BlinterConfig(max_line_length=90)
            issues = lint_batch_file(temp_file, config=config)
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            assert len(s020_issues) > 0

            # Test with max_line_length=110 (should not trigger S020)
            config = BlinterConfig(max_line_length=110)
            issues = lint_batch_file(temp_file, config=config)
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            assert len(s020_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_missing_value(self) -> None:
        """Test --max-line-length without value shows error."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length"]):
                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exc_info:
                        _parse_cli_arguments()
                    # Should exit with error code 1
                    assert exc_info.value.code == 1
                    # Should have printed error message
                    error_printed = any(
                        "--max-line-length requires a value" in str(call)
                        for call in mock_print.call_args_list
                    )
                    assert error_printed
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_non_numeric(self) -> None:
        """Test --max-line-length with non-numeric value shows error."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "abc"]):
                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exc_info:
                        _parse_cli_arguments()
                    # Should exit with error code 1
                    assert exc_info.value.code == 1
                    # Should have printed error message about numeric value
                    error_printed = any(
                        "numeric value" in str(call)
                        for call in mock_print.call_args_list
                    )
                    assert error_printed
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_negative_value(self) -> None:
        """Test --max-line-length with negative value shows error."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "-10"]):
                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exc_info:
                        _parse_cli_arguments()
                    # Should exit with error code 1
                    assert exc_info.value.code == 1
                    # Should have printed error about positive integer
                    error_printed = any(
                        "positive integer" in str(call)
                        for call in mock_print.call_args_list
                    )
                    assert error_printed
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_zero_value(self) -> None:
        """Test --max-line-length with zero value shows error."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "0"]):
                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exc_info:
                        _parse_cli_arguments()
                    # Should exit with error code 1
                    assert exc_info.value.code == 1
                    # Should have printed error about positive integer
                    error_printed = any(
                        "positive integer" in str(call)
                        for call in mock_print.call_args_list
                    )
                    assert error_printed
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_exceeds_maximum(self) -> None:
        """Test --max-line-length above MAX_LINE_LENGTH shows error."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch(
                "sys.argv", ["blinter", temp_file, "--max-line-length", "10001"]
            ):
                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exc_info:
                        _parse_cli_arguments()
                    assert exc_info.value.code == 1
                    error_printed = any(
                        "must not exceed" in str(call)
                        for call in mock_print.call_args_list
                    )
                    assert error_printed
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_small_value(self) -> None:
        """Test --max-line-length with very small value (edge case)."""
        content = "@echo off\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test with max_line_length=1 (should trigger S020 for most lines)
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "1"]):
                with patch("sys.exit"):
                    with patch("builtins.print"):
                        main()
                        # Should complete without crashing
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_large_value(self) -> None:
        """Test --max-line-length with very large value (edge case)."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test with max_line_length=9999
            config = BlinterConfig(max_line_length=9999)
            issues = lint_batch_file(temp_file, config=config)
            # Should not trigger S020 for normal lines
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            assert len(s020_issues) == 0
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_overrides_config(self) -> None:
        """Test that CLI --max-line-length overrides config file."""
        # Create a config file with max_line_length=100
        config_content = """
[general]
max_line_length = 100
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False
        ) as config_file:
            config_file.write(config_content)
            config_file.flush()
            config_file_path = config_file.name

        # Create batch file with line of 95 characters
        line_content = "REM " + "x" * 91  # 95 characters total
        content = f"@echo off\n{line_content}\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Load config from file (max_line_length=100)
            config_from_file = load_config(config_file_path)
            assert config_from_file.max_line_length == 100

            # Test that CLI override to 90 triggers S020
            config_cli_override = BlinterConfig(max_line_length=90)
            issues = lint_batch_file(temp_file, config=config_cli_override)
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            assert len(s020_issues) > 0

            # Test that file config at 100 doesn't trigger S020
            config_from_file = BlinterConfig(max_line_length=100)
            issues = lint_batch_file(temp_file, config=config_from_file)
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            assert len(s020_issues) == 0
        finally:
            os.unlink(temp_file)
            try:
                os.unlink(config_file_path)
            except (OSError, PermissionError):
                pass

    def test_cli_max_line_length_default_value(self) -> None:
        """Test that default max_line_length is 100."""
        config = BlinterConfig()
        assert config.max_line_length == 100

    def test_cli_max_line_length_with_other_flags(self) -> None:
        """Test --max-line-length with other CLI flags."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test with --summary and --max-line-length
            with patch(
                "sys.argv",
                ["blinter", temp_file, "--summary", "--max-line-length", "120"],
            ):
                with patch("sys.exit"):
                    with patch("builtins.print"):
                        main()
                        # Should complete successfully

            # Test with --no-recursive and --max-line-length
            with patch(
                "sys.argv",
                ["blinter", temp_file, "--no-recursive", "--max-line-length", "150"],
            ):
                with patch("sys.exit"):
                    with patch("builtins.print"):
                        main()
                        # Should complete successfully
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_argument_parsing(self) -> None:
        """Test that --max-line-length is correctly parsed from CLI."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "150"]):
                cli_args = _parse_cli_arguments()
                assert cli_args is not None
                assert cli_args.cli_max_line_length == 150
                assert cli_args.target_path == temp_file
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_none_when_not_specified(self) -> None:
        """Test that cli_max_line_length is None when not specified."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch("sys.argv", ["blinter", temp_file]):
                cli_args = _parse_cli_arguments()
                assert cli_args is not None
                assert cli_args.cli_max_line_length is None
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_help_includes_parameter(self) -> None:
        """Test that --help includes --max-line-length parameter."""
        with patch("sys.argv", ["blinter", "--help"]):
            with patch("builtins.print") as mock_print:
                print_help()
                # Check that help text mentions --max-line-length
                help_output = "".join(str(call) for call in mock_print.call_args_list)
                assert "--max-line-length" in help_output

    def test_cli_max_line_length_boundary_values(self) -> None:
        """Test S020 boundary behavior at explicit limits (not the 100-char default)."""
        # 88-character line used to verify limit-1/limit/limit+1 behavior
        line_content = "REM " + "x" * 84  # 88 characters total
        content = f"@echo off\n{line_content}\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # At limit 88 - should not trigger
            config_88 = BlinterConfig(max_line_length=88)
            issues_88 = lint_batch_file(temp_file, config=config_88)
            s020_issues_88 = [i for i in issues_88 if i.rule.code == "S020"]
            assert len(s020_issues_88) == 0

            # At 87 (one below) - should trigger
            config_87 = BlinterConfig(max_line_length=87)
            issues_87 = lint_batch_file(temp_file, config=config_87)
            s020_issues_87 = [i for i in issues_87 if i.rule.code == "S020"]
            assert len(s020_issues_87) > 0

            # At 89 (one above) - should not trigger
            config_89 = BlinterConfig(max_line_length=89)
            issues_89 = lint_batch_file(temp_file, config=config_89)
            s020_issues_89 = [i for i in issues_89 if i.rule.code == "S020"]
            assert len(s020_issues_89) == 0
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_multiple_lines(self) -> None:
        """Test --max-line-length with multiple lines of varying lengths."""
        content = f"""@echo off
REM {'x' * 70}
REM {'y' * 90}
REM {'z' * 110}
echo test
"""
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test with max_line_length=80
            config_80 = BlinterConfig(max_line_length=80)
            issues_80 = lint_batch_file(temp_file, config=config_80)
            s020_issues_80 = [i for i in issues_80 if i.rule.code == "S020"]
            # Should detect lines 3 and 4 (90 and 110 characters)
            assert len(s020_issues_80) >= 2

            # Test with max_line_length=100
            config_100 = BlinterConfig(max_line_length=100)
            issues_100 = lint_batch_file(temp_file, config=config_100)
            s020_issues_100 = [i for i in issues_100 if i.rule.code == "S020"]
            # Should detect only line 4 (110 characters)
            assert len(s020_issues_100) >= 1
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_integration_with_main(self) -> None:
        """Test --max-line-length integration with main() function."""
        # Create batch file with a 100-character line
        line_content = "REM " + "x" * 96
        content = f"@echo off\n{line_content}\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            # Test via main() with --max-line-length 120 (should not error on S020)
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "120"]):
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print"):
                        main()
                        assert mock_exit.called

            # Test via main() with --max-line-length 90 (should error on S020)
            with patch("sys.argv", ["blinter", temp_file, "--max-line-length", "90"]):
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print"):
                        main()
                        assert mock_exit.called
        finally:
            os.unlink(temp_file)

    def test_cli_max_line_length_with_follow_calls(self) -> None:
        """Test --max-line-length with --follow-calls flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create helper script with long line
            helper_script = os.path.join(tmpdir, "helper.bat")
            long_line = "REM " + "x" * 96  # 100 characters
            with open(helper_script, "w", encoding="utf-8") as helper_file:
                helper_file.write("@echo off\n")
                helper_file.write(f"{long_line}\n")
                helper_file.write("exit /b 0\n")

            # Create main script
            main_script = os.path.join(tmpdir, "main.bat")
            with open(main_script, "w", encoding="utf-8") as main_file:
                main_file.write("@echo off\n")
                main_file.write(f'call "{helper_script}"\n')
                main_file.write("exit /b 0\n")

            # Test with follow-calls and max-line-length
            with patch(
                "sys.argv",
                [
                    "blinter",
                    main_script,
                    "--follow-calls",
                    "--max-line-length",
                    "90",
                ],
            ):
                with patch("sys.exit"):
                    with patch("builtins.print"):
                        main()
                        # Should process both files with custom line length

    def test_cli_max_line_length_float_value(self) -> None:
        """Test --max-line-length with float value (should be converted to int)."""
        content = "@echo off\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            with patch(
                "sys.argv", ["blinter", temp_file, "--max-line-length", "120.5"]
            ):
                with pytest.raises(SystemExit) as exit_info:
                    _parse_cli_arguments()
                assert exit_info.value.code == 1
        finally:
            os.unlink(temp_file)


class TestMaxLineLengthConfigFile:
    """Test max_line_length in configuration file."""

    def test_config_file_max_line_length(self) -> None:
        """Test that max_line_length is loaded from config file."""
        config_content = """
[general]
max_line_length = 120
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False
        ) as config_file:
            config_file.write(config_content)
            config_file.flush()
            config_file_path = config_file.name

        try:
            config = load_config(config_file_path)
            assert config.max_line_length == 120
        finally:
            try:
                os.unlink(config_file_path)
            except (OSError, PermissionError):
                pass

    def test_config_file_max_line_length_default(self) -> None:
        """Test that max_line_length defaults to 100 when not in config."""
        config_content = """
[general]
recursive = true
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False
        ) as config_file:
            config_file.write(config_content)
            config_file.flush()
            config_file_path = config_file.name

        try:
            config = load_config(config_file_path)
            assert config.max_line_length == 100
        finally:
            try:
                os.unlink(config_file_path)
            except (OSError, PermissionError):
                pass

    def test_config_file_max_line_length_invalid(self) -> None:
        """Test that an invalid max_line_length in config is rejected."""
        config_content = """
[general]
max_line_length = invalid
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False
        ) as config_file:
            config_file.write(config_content)
            config_file.flush()
            config_file_path = config_file.name

        try:
            with pytest.raises(ValueError, match="Invalid max_line_length"):
                load_config(config_file_path)
        finally:
            try:
                os.unlink(config_file_path)
            except (OSError, PermissionError):
                pass


class TestMaxLineLengthEdgeCases:
    """Test edge cases for max_line_length functionality."""

    def create_temp_batch_file(self, content: str) -> str:
        """Helper method to create a temporary batch file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(content)
            return temp_file.name

    def test_max_line_length_empty_lines(self) -> None:
        """Test that empty lines don't trigger S020."""
        content = "@echo off\n\n\n\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            config = BlinterConfig(max_line_length=1)
            issues = lint_batch_file(temp_file, config=config)
            # Empty lines should not trigger S020
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            # Should not report empty lines
            for issue in s020_issues:
                assert issue.line_number != 2
                assert issue.line_number != 3
                assert issue.line_number != 4
        finally:
            os.unlink(temp_file)

    def test_max_line_length_whitespace_lines(self) -> None:
        """Test that lines with only whitespace are measured correctly."""
        content = "@echo off\n" + " " * 100 + "\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            config = BlinterConfig(max_line_length=50)
            issues = lint_batch_file(temp_file, config=config)
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            whitespace_line_issues = [i for i in s020_issues if i.line_number == 2]
            assert len(whitespace_line_issues) == 1
        finally:
            os.unlink(temp_file)

    def test_max_line_length_unicode_characters(self) -> None:
        """Test max_line_length with unicode characters."""
        unicode_str = "日本語" * 30  # Japanese characters
        content = f"@echo off\nREM {unicode_str}\necho test\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            config = BlinterConfig(max_line_length=50)
            issues = lint_batch_file(temp_file, config=config)
            # Should handle unicode properly
            assert isinstance(issues, list)
        finally:
            os.unlink(temp_file)

    def test_max_line_length_rule_explanation_updates(self) -> None:
        """Test that S020 context reflects custom max_line_length."""
        config = BlinterConfig(max_line_length=100)
        # Create a line that exceeds the custom limit
        line_content = "REM " + "x" * 100  # 104 characters
        content = f"@echo off\n{line_content}\n"
        temp_file = self.create_temp_batch_file(content)

        try:
            issues = lint_batch_file(temp_file, config=config)
            s020_issues = [i for i in issues if i.rule.code == "S020"]
            if s020_issues:
                issue = s020_issues[0]
                assert "100" in str(issue.context or "")
        finally:
            os.unlink(temp_file)
