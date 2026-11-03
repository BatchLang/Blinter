"""Tests for delayed expansion detection with special characters in variable names.

This test module verifies that the linter correctly detects delayed expansion
variables that contain special characters like @, -, #, $, etc. which are commonly
used in batch script variable naming conventions.
"""

import pathlib

import pytest

from blinter import lint_batch_file
from blinter.parsing.structure import _build_delayed_expansion_state, _ExitScan


def test_delayed_expand_at_symbol(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with @ symbol."""
    script = tmp_path / "test_at.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @DEBUG_MODE=ON\n"
        "ECHO !@DEBUG_MODE!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 (Unnecessary ENABLEDELAYEDEXPANSION) error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !@variable!"


def test_delayed_expand_hyphen(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with hyphen."""
    script = tmp_path / "test_hyphen.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @CRLF-1=test\n"
        "ECHO !@CRLF-%~1!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !@CRLF-%~1!"


def test_delayed_expand_hash(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with # symbol."""
    script = tmp_path / "test_hash.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @SCRIPT_BEG#=12345\n"
        "ECHO !@SCRIPT_BEG#!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !@SCRIPT_BEG#!"


def test_delayed_expand_dollar(tmp_path: pathlib.Path) -> None:
    """Test detection of delayed expansion variables with $ symbol."""
    script = tmp_path / "test_dollar.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET $CODEPAGE=437\n"
        "ECHO !$CODEPAGE!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should not flag P004 when using !$CODEPAGE!"


def test_no_delayed_expand_needed(tmp_path: pathlib.Path) -> None:
    """Test that P004 is still raised when no delayed expansion variables are used."""
    script = tmp_path / "test_no_delayed.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET MYVAR=test\n"
        "ECHO %MYVAR%\n"  # Using % syntax, not ! syntax
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # SHOULD have P004 error because delayed expansion is not actually used
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 1
    ), "Should flag P004 when ENABLEDELAYEDEXPANSION is unused"


def test_p008_with_special_chars(tmp_path: pathlib.Path) -> None:
    """Test P008 detection of delayed expansion without ENABLEDELAYEDEXPANSION."""
    script = tmp_path / "test_p008.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL\n"  # No ENABLEDELAYEDEXPANSION
        "SET @DEBUG_MODE=ON\n"
        "ECHO !@DEBUG_MODE!\n"  # Using delayed expansion without enabling it
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # SHOULD have P008 error
    p008_issues = [issue for issue in issues if issue.rule.code == "P008"]
    assert (
        len(p008_issues) >= 1
    ), "Should flag P008 when using !@variable! without ENABLEDELAYEDEXPANSION"


@pytest.mark.parametrize(
    ("last", "still_enabled"),
    [
        ("exit /b 1", True),
        ("EXIT", True),
        ("echo Failed. & exit/b 1", True),
        ("goto:eof", True),
        ("goto fail", True),
        ("exit.bat", False),
        ("call :check || exit /b 1", False),
        ("if errorlevel 1 exit /b 1", False),
        ("echo done | exit", False),
    ],
)
def test_p008_scope_below_block_ending_in(last: str, still_enabled: bool) -> None:
    """ENDLOCAL in a block that always ends in EXIT or GOTO keeps the scope below.

    ``exit.bat`` names a batch file, and ``||``, IF and a pipe may go on.
    """
    lines = [
        "setlocal enabledelayedexpansion",
        'if "!A!"=="1" (',
        "    endlocal",
        f"    {last}",
        ")",
        "echo !A!",
        "endlocal",
        ":fail",
        "exit /b 1",
    ]
    assert _build_delayed_expansion_state(lines)[5] is still_enabled


@pytest.mark.parametrize(
    "lines",
    [
        [
            'if "%A%"=="1" (',
            "    setlocal enabledelayedexpansion",
            "    endlocal",
            "    exit /b 1",
            ")",
            "echo !A!",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "!A!"=="1" (',
            "    endlocal",
            "    exit /b 1",
            "echo !A!",
        ],
        [
            "setlocal enabledelayedexpansion",
            "if defined A endlocal & goto :show",
            "echo !A!",
            ":show",
            "echo !A!",
        ],
        [
            'if "%A%"=="1" (',
            '    if "%B%"=="2" (',
            "        setlocal enabledelayedexpansion",
            "    )",
            "    endlocal",
            "    exit /b 1",
            ")",
            "echo !A!",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "%A%"=="1" (',
            "    endlocal",
            "    exit /b 1",
            ")",
            "goto main",
            ":sub",
            "echo !A!",
            "exit /b 0",
            ":main",
            "endlocal",
            "call :sub",
        ],
    ],
)
def test_p008_scope_closed_below_block(lines: list[str]) -> None:
    """ENDLOCAL still closes the scope below where the rule cannot tell it leaves.

    The cases are a block's own SETLOCAL, a block with no ``)``, a GOTO to
    a label that reads ``!VAR!``, a SETLOCAL in a nested block and a label
    below the block that a CALL reaches after the scope closed.
    """
    assert _build_delayed_expansion_state(lines)[lines.index("echo !A!")] is False


@pytest.mark.parametrize(
    ("before", "target", "after"),
    [
        ([":again"], "again", []),
        ([], "out", [":out", "exit /b 0", ":out", "exit /b 1"]),
        ([], "%T%", [":x", "exit /b 1"]),
        ([], "fail", [":fail", "if defined L (", "    exit /b 1", ")", "echo !B!"]),
        ([], "fail", [":fail", "goto :again", ":again", "exit /b 1"]),
        ([], "fail", [":fail", "call :log", "exit /b 1", ":log", "echo !B!"]),
        ([], "fail", [":fail", "setlocal", "echo !B!", "exit /b 1"]),
    ],
)
def test_p008_scope_closed_below_goto(
    before: list[str], target: str, after: list[str]
) -> None:
    """A GOTO that may lead back to the lines below the block does not count.

    The cases are a label above the GOTO, a label written twice, a computed
    target, and a label whose lines may read ``!VAR!``, jump again or call a
    label.
    """
    lines = [
        "setlocal enabledelayedexpansion",
        *before,
        'if "%A%"=="1" (',
        "    endlocal",
        f"    goto {target}",
        ")",
        "echo !A!",
        *after,
    ]
    assert _build_delayed_expansion_state(lines)[lines.index("echo !A!")] is False


@pytest.mark.parametrize(
    ("lines", "still_enabled"),
    [
        (
            [
                "setlocal enabledelayedexpansion",
                "setlocal disabledelayedexpansion",
                "setlocal disabledelayedexpansion",
                "(",
                "    endlocal",
                "    if 1==1 goto cont",
                "    exit /b",
                ")",
                ":cont",
                "endlocal",
                "echo !V!",
            ],
            True,
        ),
        (
            [
                "setlocal enabledelayedexpansion",
                "setlocal enabledelayedexpansion",
                'if "%1"=="a" (',
                "    endlocal",
                '    if "%2"=="b" goto cont',
                "    exit /b",
                ")",
                ":cont",
                "endlocal",
                "echo !V!",
            ],
            False,
        ),
        (
            [
                "setlocal enabledelayedexpansion",
                "setlocal enabledelayedexpansion",
                'if "%1"=="a" (',
                "    endlocal",
                '    if "%2"=="b" call :cont',
                "    exit /b",
                ")",
                ":cont",
                "endlocal",
                "echo !V!",
            ],
            False,
        ),
        (
            [
                "setlocal enabledelayedexpansion",
                'if "%1"=="" (',
                "    endlocal",
                "    echo bye ^",
                "    exit /b 1",
                ")",
                "echo !V!",
            ],
            False,
        ),
    ],
)
def test_p008_endlocal_kept_in_block_that_may_go_on(
    lines: list[str], still_enabled: bool
) -> None:
    """ENDLOCAL counts where the block may go on before its last line.

    The cases are a GOTO that would add a report, a GOTO and a CALL that would
    drop one, and a last line that a caret makes part of an ECHO.
    """
    assert _build_delayed_expansion_state(lines)[-1] is still_enabled


@pytest.mark.parametrize(
    "lines",
    [
        [
            "setlocal enabledelayedexpansion",
            'if "%1"=="" (',
            "    endlocal",
            "    exit /b 1 | more",
            ")",
            "echo !A!",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "%1"=="" (',
            "    endlocal",
            "    echo a & goto sub & exit /b",
            ")",
            ":sub",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "%1"=="" endlocal & goto sub & exit /b',
            ":sub",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "%1"=="" endlocal & exit /b 1 ^',
            "| more",
            "echo !A!",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "%1"=="" (',
            "    endlocal",
            "    g^oto sub",
            "    exit /b 1",
            ")",
            ":sub",
        ],
        [
            "setlocal enabledelayedexpansion",
            'if "%1"=="" (',
            "    endlocal",
            "    call:sub",
            "    exit /b 1",
            ")",
            ":sub",
        ],
    ],
)
def test_p008_endlocal_kept_before_jump_or_pipe(lines: list[str]) -> None:
    """No ENDLOCAL is skipped where the block may jump or its EXIT is piped.

    The cases are a piped EXIT, a GOTO earlier on the last line of a block or
    of an IF, an IF line that a caret joins to a pipe, ``g^oto`` and
    ``call:sub``.
    """
    assert not _ExitScan(lines).skipped()


def test_p008_scope_below_block_with_goto_eof() -> None:
    """``goto :eof``, an escaped caret and a blank line before EXIT still leave."""
    lines = [
        "setlocal enabledelayedexpansion",
        'if "%1"=="" (',
        "    endlocal",
        '    if "%2"=="" goto :eof',
        "    echo bye ^^",
        "",
        "    exit /b 1",
        ")",
        "echo !V!",
    ]
    assert _build_delayed_expansion_state(lines)[-1] is True


def test_p008_disabled_scope_open_below_block() -> None:
    """A skipped ENDLOCAL leaves an inner disabled scope open below the block."""
    lines = [
        "setlocal enabledelayedexpansion",
        "setlocal disabledelayedexpansion",
        'if "%A%"=="1" (',
        "    endlocal",
        "    exit /b 1",
        ")",
        "echo !A!",
    ]
    assert _build_delayed_expansion_state(lines)[6] is False


def test_comment_is_not_delayed_expansion(tmp_path: pathlib.Path) -> None:
    """A !VAR! in a comment gives no P008, W022 or E006, with no SETLOCAL at all.

    cmd.exe still expands %VAR% in a comment, so E006 reports %NOPE% there.
    """
    script = tmp_path / "test_comment.bat"
    script.write_text(
        '@echo off\nREM A "!VAR!" in prose.\n:: A "!VAR!" in prose.\n'
        "REM A %NOPE% in prose.\n:: A %NOPE% in prose.\nexit /b 0\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    codes = {issue.rule.code for issue in issues}
    assert not codes & {"P008", "W022"}
    assert [i.line_number for i in issues if i.rule.code == "E006"] == [4, 5]


def test_setaccounts_regression(tmp_path: pathlib.Path) -> None:
    """Test the specific case from SetAccounts.BAT that caused the bug report."""
    script = tmp_path / "test_setaccounts.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @DEBUG_MODE=ON\n"
        "SET @CRLF-TEST=value\n"
        "SET @CUSTOM_TITLE=MyScript\n"
        "REM Simulating the ShowStatus subroutine\n"
        "TITLE %@CUSTOM_TITLE% [%USERDOMAIN%\\%USERNAME%]   !@DEBUG_MODE!\n"
        "ECHO !@CRLF-%~1!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error - this is the regression test for the bug
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 0
    ), "Regression: Should not flag P004 for SetAccounts.BAT pattern with !@DEBUG_MODE!"


def test_complex_delayed_exprs(tmp_path: pathlib.Path) -> None:
    """Test detection of complex delayed expansion expressions."""
    script = tmp_path / "test_complex.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET arr[0]=value1\n"
        "SET arr[1]=value2\n"
        "ECHO !arr[0]!\n"
        "ECHO !arr[1]!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 0
    ), "Should detect delayed expansion in array syntax !arr[0]!"


def test_nested_delayed_expansion(tmp_path: pathlib.Path) -> None:
    """Test detection of nested/complex delayed expansion patterns."""
    script = tmp_path / "test_nested.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET var1=test\n"
        "SET var2=var1\n"
        "ECHO !!var2!!\n"  # Double delayed expansion
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert len(p004_issues) == 0, "Should detect nested delayed expansion !!var2!!"


def test_multi_special_chars_var(tmp_path: pathlib.Path) -> None:
    """Test variables with multiple special characters."""
    script = tmp_path / "test_multiple.bat"
    script.write_text(
        "@ECHO OFF\n"
        "SETLOCAL ENABLEDELAYEDEXPANSION\n"
        "SET @VAR_NAME-123#=test\n"
        "ECHO !@VAR_NAME-123#!\n"
        "ENDLOCAL\n",
        encoding="utf-8",
    )

    issues = lint_batch_file(str(script))
    # Should NOT have P004 error
    p004_issues = [issue for issue in issues if issue.rule.code == "P004"]
    assert (
        len(p004_issues) == 0
    ), "Should detect !@VAR_NAME-123#! with multiple special chars"
