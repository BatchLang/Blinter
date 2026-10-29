"""Tests for scripts.verify step selection and pyproject name handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify import (
    Step,
    StepKind,
    StepRequest,
    _execute_step,
    _parse_project_name,
    _require_uv,
    _set_project_name,
    select_steps,
)

pytestmark = pytest.mark.timeout(30)

_CHECK_DIRS = ("src", "scripts", "tests")


def _request(**overrides: bool) -> StepRequest:
    """Return a step request rooted at the repository, with test overrides."""
    return StepRequest(root=Path("."), uv_executable="uv", **overrides)


def _names(request: StepRequest | None = None) -> list[str]:
    """Return step names for the requested selection."""
    chosen = _request() if request is None else request
    return [step.name for step in select_steps(chosen)]


def _step(name: str) -> Step:
    """Return one selected step by name."""
    matches = [step for step in select_steps(_request()) if step.name == name]
    assert len(matches) == 1
    return matches[0]


def test_linux_default_skips_windows_steps() -> None:
    """A non-Windows run keeps pytest and drops cmd.exe and PowerShell."""
    names = _names()
    assert "pytest" in names
    assert "mypy" in names
    assert "cmd.exe corpus oracle" not in names
    assert "Pester (PowerShell tests)" not in names


def test_skip_pytest_omits_only_pytest() -> None:
    """--skip-pytest removes the test suite and keeps the quality checks."""
    names = _names(_request(skip_pytest=True))
    assert "pytest" not in names
    assert "mypy" in names
    assert "pylint" in names


def test_windows_default_includes_oracle_once() -> None:
    """A full Windows run includes the oracle once, before the type check."""
    names = _names(_request(is_windows=True))
    assert names.count("cmd.exe corpus oracle") == 1
    assert "PSScriptAnalyzer (PowerShell scripts)" in names
    assert names.index("cmd.exe corpus oracle") < names.index("mypy")


def test_windows_only_is_the_windows_subset() -> None:
    """--windows-only returns the oracle, PowerShell, and install-script lint."""
    assert _names(_request(windows_only=True, is_windows=True)) == [
        "cmd.exe corpus oracle",
        "PowerShell module prerequisites",
        "PSScriptAnalyzer (PowerShell scripts)",
        "Pester (PowerShell tests)",
        "blinter (install/uninstall scripts)",
    ]


def test_windows_only_requires_windows() -> None:
    """--windows-only exits on platforms that cannot run those checks."""
    with pytest.raises(SystemExit, match="Windows"):
        _names(_request(windows_only=True, is_windows=False))


def test_corpus_step_follows_the_snapshot() -> None:
    """The corpus baseline runs only when the corpus and snapshot are present."""
    assert "corpus baseline check" not in _names()
    assert "corpus baseline check" in _names(_request(corpus_present=True))


def test_shellcheck_runs_on_every_platform_and_covers_each_shell_script() -> None:
    """ShellCheck runs outside --windows-only and lints each installer script."""
    for is_windows in (False, True):
        assert "shellcheck (shell scripts)" in _names(_request(is_windows=is_windows))
    assert "shellcheck (shell scripts)" not in _names(
        _request(windows_only=True, is_windows=True)
    )
    command = _step("shellcheck (shell scripts)").command
    assert Path(command[0]).stem == "shellcheck"
    assert command[1:] == (
        "scripts/install_blinter.sh",
        "scripts/uninstall_blinter.sh",
        "scripts/test_install_scripts.sh",
    )


def test_yamllint_checks_the_repository_root() -> None:
    """yamllint scans every YAML file from the repository root in strict mode."""
    command = _step("yamllint").command
    assert "yamllint" in command
    assert command[-2:] == ("--strict", ".")


def test_directory_targets_are_not_file_lists() -> None:
    """mypy, pylint, and bandit target directories rather than individual files."""
    mypy = _step("mypy")
    assert mypy.command[-1:] == ("mypy",)
    assert not any(part.endswith(".py") for part in mypy.command)

    pylint = _step("pylint")
    assert pylint.kind is StepKind.PYLINT

    for name in ("black", "isort", "autopep8 (trailing whitespace)"):
        command = _step(name).command
        assert command[-3:] == _CHECK_DIRS

    bandit = _step("bandit")
    assert "src" in bandit.command
    assert "scripts" in bandit.command
    assert "tests" not in bandit.command


def test_require_uv_exits_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing uv executable fails the quality gate instead of skipping the lock check."""
    monkeypatch.setattr("scripts.verify.shutil.which", lambda _name: None)
    with pytest.raises(SystemExit, match="uv"):
        _require_uv()


def test_failed_command_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-zero command exit code stops the pipeline."""
    monkeypatch.setattr("scripts.verify._command_exit", lambda _args, _cwd: 2)
    step = Step("broken", ("python", "-c", "raise SystemExit(2)"))
    with pytest.raises(SystemExit, match="broken"):
        _execute_step(step, tmp_path)


def test_project_name_round_trip_keeps_later_tables() -> None:
    """The branded project name is restored without rewriting later name keys."""
    text = (
        '[project]\nname = "Blinter"\nversion = "1"\n\n[tool.other]\nname = "other"\n'
    )
    assert _parse_project_name(text) == "Blinter"
    updated = _set_project_name(text, "Blinter")
    assert updated.splitlines()[1] == 'name = "Blinter"'
    assert 'name = "other"' in updated
