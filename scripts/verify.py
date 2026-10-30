#!/usr/bin/env python3
"""Run local quality checks for Blinter."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
from enum import Enum
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import tomllib
from typing import Sequence, assert_never, cast

# Portable directory names (no platform-specific separators).
_CHECK_DIRS: tuple[str, ...] = ("src", "scripts", "tests")
_SECURITY_DIRS: tuple[str, ...] = ("src", "scripts")
_LOG = logging.getLogger("scripts.verify")
_SPEC_VALIDATE = Path("scripts") / "spec" / "validate_spec.py"
_SPEC_VALIDATE_CORPUS = Path("scripts") / "spec" / "validate_corpus.py"
_SPEC_GENERATE_RULES = Path("scripts") / "spec" / "generate_rules.py"
_SPEC_GENERATE_DOCS = Path("scripts") / "spec" / "generate_docs.py"
_SPEC_GENERATE_EXPANSION = Path("scripts") / "spec" / "generate_expansion.py"
_SPEC_GENERATE_COMMANDS = Path("scripts") / "spec" / "generate_commands.py"
_SPEC_AUDIT = Path("scripts") / "spec" / "audit_ssot.py"
_SPEC_CMD_ORACLE = Path("scripts") / "spec" / "cmd_oracle.py"
_CORPUS_LINT_SCRIPT = Path("scripts") / "corpus_lint.py"
_CORPUS_DIR = Path("batch-script-examples")
_PYPROJECT = "pyproject.toml"
_BENCHMARK_SCRIPT = Path("scripts") / "benchmark_lint.py"
_CORPUS_BASELINE = Path("tests") / "fixtures" / "corpus-baseline.json"
_PYLINT_OUTPUT = "pylint-output.txt"
_POWERSHELL_ANALYZER_SETTINGS = Path("scripts") / "PSScriptAnalyzerSettings.psd1"
_VERIFY_PS_DIR = Path("scripts") / "verify_ps"
_BLINTER_SCRIPTS_INI = Path("scripts") / "blinter.ini"
# Every shell script is linted: the .sh files under scripts and the extension-less
# stand-in commands the Unix installer tests put on PATH.
_SHELL_SCRIPT_GLOBS: tuple[tuple[Path, str], ...] = (
    (Path("scripts"), "*.sh"),
    (Path("tests") / "unix_stubs", "*"),
)


class StepKind(Enum):
    """How a verification step is executed."""

    COMMAND = "command"
    PYPROJECT_FMT = "pyproject_fmt"
    PYLINT = "pylint"
    POWERSHELL = "powershell"


@dataclass(frozen=True)
class Step:
    """One quality-check command."""

    name: str
    command: tuple[str, ...] = ()
    windows_only: bool = False
    kind: StepKind = StepKind.COMMAND
    fix: bool = False


@dataclass(frozen=True)
class StepRequest:
    """Inputs that choose which verification steps run."""

    root: Path
    fix: bool = False
    skip_pytest: bool = False
    windows_only: bool = False
    is_windows: bool = False
    corpus_present: bool = False
    uv_executable: str = ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _python_m(module: str, *module_args: str) -> list[str]:
    """Build a ``sys.executable -m module`` command (works on Windows and Unix)."""
    return [sys.executable, "-m", module, *module_args]


def _configure_logging() -> None:
    """Attach one stderr handler when the process has not configured logging."""
    if _LOG.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False


def _command_exit(args: Sequence[str], cwd: Path) -> int:
    """Run a command and return its exit code."""
    result = subprocess.run(list(args), cwd=cwd, check=False)
    return result.returncode


def _pylint_command() -> list[str]:
    """Return the pylint command.

    Parallel jobs pickle the linter. On Python 3.15, dill cannot pickle code
    objects (``co_lnotab`` was removed), so the pool crashes before any file
    is checked. One process avoids that.
    """
    command = _python_m("pylint", *_CHECK_DIRS)
    if sys.version_info >= (3, 15):
        command.extend(["-j", "1"])
    return command


def _run_pylint(cwd: Path) -> int:
    """Run pylint on the check directories and write a UTF-8 report."""
    result = subprocess.run(
        _pylint_command(),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    report_path = cwd / _PYLINT_OUTPUT
    report_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    return result.returncode


def _autopep8_args(*, fix: bool) -> list[str]:
    args = _python_m("autopep8", "--select=W291,W293", "-r", *_CHECK_DIRS)
    mode_flag = "--in-place" if fix else "--diff"
    args.insert(3, mode_flag)
    return args


def _parse_project_name(pyproject_text: str) -> str:
    """Return [project].name from pyproject.toml text."""
    data_object: object = tomllib.loads(pyproject_text)
    if not isinstance(data_object, dict):
        raise ValueError("pyproject.toml must contain a top-level table")
    project_object: object = data_object.get("project")
    if not isinstance(project_object, dict):
        raise ValueError("pyproject.toml must contain a [project] table")
    name_object: object = project_object.get("name")
    if not isinstance(name_object, str) or not name_object:
        raise ValueError("pyproject.toml [project].name must be a non-empty string")
    return name_object


def _set_project_name(pyproject_text: str, name: str) -> str:
    """Replace the [project] table name assignment without touching inline-table names."""
    lines = pyproject_text.splitlines()
    in_project = False
    replaced = False
    updated: list[str] = []
    for line in lines:
        if line.strip() == "[project]":
            in_project = True
            updated.append(line)
            continue
        if in_project and line.startswith("[") and line.strip() != "[project]":
            in_project = False
        if in_project and not replaced:
            stripped = line.lstrip()
            if stripped.startswith("name ="):
                prefix = line[: len(line) - len(stripped)]
                updated.append(f'{prefix}name = "{name}"')
                replaced = True
                continue
        updated.append(line)
    if not replaced:
        raise ValueError("pyproject.toml missing [project].name assignment")
    trailing_newline = "\n" if pyproject_text.endswith("\n") else ""
    return "\n".join(updated) + trailing_newline


def _normalize_pyproject_text(text: str) -> str:
    """Normalize pyproject.toml text for stable comparisons."""
    return text.rstrip("\n")


def _run_pyproject_fmt(*, fix: bool, cwd: Path) -> None:
    """Run pyproject-fmt while preserving the branded [project].name value."""
    pyproject_path = cwd / _PYPROJECT
    original = pyproject_path.read_text(encoding="utf-8")
    project_name = _parse_project_name(original)

    if fix:
        subprocess.run(
            _python_m("pyproject_fmt", _PYPROJECT),
            cwd=cwd,
            check=False,
        )
        if not pyproject_path.is_file():
            raise SystemExit("Step failed: pyproject-fmt (pyproject.toml missing)")
        formatted = pyproject_path.read_text(encoding="utf-8")
        pyproject_path.write_text(
            _set_project_name(formatted, project_name),
            encoding="utf-8",
            newline="\n",
        )
        return

    result = subprocess.run(
        _python_m("pyproject_fmt", "--stdout", _PYPROJECT),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not result.stdout.strip():
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(f"Step failed: pyproject-fmt (exit code {result.returncode})")

    expected = _set_project_name(result.stdout, project_name)
    if _normalize_pyproject_text(expected) != _normalize_pyproject_text(original):
        diff = difflib.unified_diff(
            original.splitlines(),
            expected.splitlines(),
            fromfile=_PYPROJECT,
            tofile=_PYPROJECT,
        )
        for line in diff:
            print(line)
        raise SystemExit("Step failed: pyproject-fmt (formatting required)")


def _isort_args(*, fix: bool) -> list[str]:
    args = _python_m("isort", *_CHECK_DIRS)
    if not fix:
        args.insert(3, "--check-only")
    return args


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _powershell_executable() -> str:
    return "powershell"


def _windows_powershell_env() -> dict[str, str]:
    """Environment for Windows PowerShell 5.1 child processes.

    GitHub Actions Windows jobs default to pwsh. ``python`` then ``powershell.exe``
    inherits pwsh's ``PSModulePath``, so 5.1 loads Core ``Microsoft.PowerShell.Utility``
    and cmdlets such as ``Get-FileHash`` raise CommandNotFoundException.
    """
    env = os.environ.copy()
    env.pop("PSModulePath", None)
    return env


def _powershell_exit(script: Path, script_args: tuple[str, ...], cwd: Path) -> int:
    """Run a PowerShell script file and return its exit code."""
    result = subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *script_args,
        ],
        cwd=cwd,
        env=_windows_powershell_env(),
        check=False,
    )
    return result.returncode


def _verify_ps_step(root: Path, script_name: str, *script_args: str) -> tuple[str, ...]:
    """Return a PowerShell step command: the script path, then its arguments."""
    return (str(root / _VERIFY_PS_DIR / script_name), *script_args)


def _blinter_install_command(root: Path) -> tuple[str, ...]:
    """Return the blinter command for the install and uninstall scripts."""
    return (
        sys.executable,
        "-m",
        "blinter",
        str(root / "scripts"),
        "--no-recursive",
        "--config",
        str(root / _BLINTER_SCRIPTS_INI),
    )


def _script_command(script: Path, *script_args: str) -> tuple[str, ...]:
    """Return a ``python path/to/script.py`` command."""
    return (sys.executable, str(script), *script_args)


def _shell_scripts(root: Path) -> tuple[str, ...]:
    """Return every shell script to lint, as sorted POSIX paths relative to ``root``."""
    found = {
        path.relative_to(root).as_posix()
        for directory, pattern in _SHELL_SCRIPT_GLOBS
        for path in (root / directory).glob(pattern)
        if path.is_file() and not path.name.startswith(".")
    }
    return tuple(sorted(found))


def _shellcheck_command(root: Path) -> tuple[str, ...]:
    """Return the ShellCheck command for every shell script in the repository.

    The shellcheck-py wheel installs the binary beside the interpreter. Looking there
    first means an unactivated virtual environment works. A bare name is the fallback,
    so a missing binary fails loudly when the step runs. A repository with no shell
    scripts is an error too, so the step cannot pass by checking nothing.
    """
    scripts = _shell_scripts(root)
    if not scripts:
        raise FileNotFoundError(f"No shell scripts found under {root}")
    binary_name = "shellcheck.exe" if _is_windows() else "shellcheck"
    candidate = Path(sys.executable).parent / binary_name
    executable = str(candidate) if candidate.is_file() else "shellcheck"
    return (executable, *scripts)


def _quality_steps(*, fix: bool, uv_executable: str, root: Path) -> tuple[Step, ...]:
    """Return the platform-neutral quality checks, in run order."""
    return (
        Step("validate spec schemas", _script_command(_SPEC_VALIDATE)),
        Step("validate SSOT corpus", _script_command(_SPEC_VALIDATE_CORPUS)),
        Step(
            "cmd.exe corpus oracle",
            _script_command(_SPEC_CMD_ORACLE),
            windows_only=True,
        ),
        Step(
            "check generated registry.py",
            _script_command(_SPEC_GENERATE_RULES, "--check"),
        ),
        Step(
            "check generated expansion_data.py",
            _script_command(_SPEC_GENERATE_EXPANSION, "--check"),
        ),
        Step(
            "check generated patterns.py",
            _script_command(_SPEC_GENERATE_COMMANDS, "--check"),
        ),
        Step(
            "check generated docs catalog",
            _script_command(_SPEC_GENERATE_DOCS, "--check"),
        ),
        Step(
            "SSOT audit (strict)",
            _script_command(_SPEC_AUDIT, "--strict", "--check"),
        ),
        Step("uv lock", (uv_executable, "lock", "--check")),
        Step("autopep8 (trailing whitespace)", tuple(_autopep8_args(fix=fix))),
        Step("isort", tuple(_isort_args(fix=fix))),
        Step("pyproject-fmt", kind=StepKind.PYPROJECT_FMT, fix=fix),
        Step("black", tuple(_python_m("black", "--check", *_CHECK_DIRS))),
        Step("yamllint", tuple(_python_m("yamllint", "--strict", "."))),
        Step("shellcheck (shell scripts)", _shellcheck_command(root)),
        Step("mypy", tuple(_python_m("mypy"))),
        Step("pylint", kind=StepKind.PYLINT),
        Step(
            "bandit",
            tuple(
                _python_m(
                    "bandit",
                    "-r",
                    *_SECURITY_DIRS,
                    "-c",
                    _PYPROJECT,
                    "-ll",
                    "-q",
                )
            ),
        ),
        Step(
            "pip-audit",
            tuple(
                _python_m(
                    "pip_audit",
                    "-r",
                    "requirements.txt",
                    "-r",
                    "requirements-dev.txt",
                )
            ),
        ),
        Step(
            "benchmark baseline",
            _script_command(_BENCHMARK_SCRIPT, "--runs", "3", "--check-baseline"),
        ),
    )


def _windows_steps(root: Path) -> tuple[Step, ...]:
    """Return cmd.exe, PowerShell, and install-script checks."""
    return (
        Step(
            "cmd.exe corpus oracle",
            _script_command(_SPEC_CMD_ORACLE),
            windows_only=True,
        ),
        Step(
            "PowerShell module prerequisites",
            _verify_ps_step(root, "Install-VerifyModules.ps1"),
            windows_only=True,
            kind=StepKind.POWERSHELL,
        ),
        Step(
            "PSScriptAnalyzer (PowerShell scripts)",
            _verify_ps_step(
                root,
                "Invoke-ScriptAnalysis.ps1",
                "-Root",
                str(root),
                "-SettingsPath",
                str(root / _POWERSHELL_ANALYZER_SETTINGS),
            ),
            windows_only=True,
            kind=StepKind.POWERSHELL,
        ),
        Step(
            "Pester (PowerShell tests)",
            _verify_ps_step(root, "Invoke-PesterTests.ps1", "-Root", str(root)),
            windows_only=True,
            kind=StepKind.POWERSHELL,
        ),
        Step(
            "blinter (install/uninstall scripts)",
            _blinter_install_command(root),
            windows_only=True,
        ),
    )


def _corpus_present(root: Path) -> bool:
    """Return whether the optional corpus and its baseline snapshot exist."""
    return (root / _CORPUS_DIR).is_dir() and (root / _CORPUS_BASELINE).is_file()


def _require_uv() -> str:
    """Return the uv executable, or exit when it is not on PATH."""
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        raise SystemExit(
            "uv is required for `uv lock --check` but was not found on PATH"
        )
    return uv_executable


def _require_cpython() -> None:
    """Exit with a clear message when not running under CPython.

    mypy and several other gate tools do not support alternative interpreters
    such as PyPy, and fail with obscure errors midway through the gate.
    """
    implementation = platform.python_implementation()
    if implementation != "CPython":
        raise SystemExit(
            f"verify.py must run under CPython, not {implementation}. "
            "Recreate the virtual environment with "
            "`uv venv --python cpython-3.14 --clear` and `uv sync --extra dev`."
        )


def select_steps(request: StepRequest) -> tuple[Step, ...]:
    """Choose verification steps for the requested flags and platform."""
    if request.windows_only:
        if not request.is_windows:
            raise SystemExit("Windows checks require Windows.")
        return _windows_steps(request.root)

    selected = [
        step
        for step in _quality_steps(
            fix=request.fix, uv_executable=request.uv_executable, root=request.root
        )
        if request.is_windows or not step.windows_only
    ]
    if request.corpus_present:
        selected.append(
            Step(
                "corpus baseline check",
                _script_command(_CORPUS_LINT_SCRIPT, "--check-baseline"),
            )
        )
    if not request.skip_pytest:
        selected.append(Step("pytest", tuple(_python_m("pytest"))))
    if request.is_windows:
        selected.extend(
            step
            for step in _windows_steps(request.root)
            if step.name != "cmd.exe corpus oracle"
        )
    return tuple(selected)


def _execute_step(step: Step, root: Path) -> None:
    """Run one step and log its command, duration, and exit code."""
    print(f"==> {step.name}")
    started = time.perf_counter()
    exit_code = 0
    try:
        match step.kind:
            case StepKind.PYPROJECT_FMT:
                _run_pyproject_fmt(fix=step.fix, cwd=root)
            case StepKind.PYLINT:
                exit_code = _run_pylint(root)
            case StepKind.POWERSHELL:
                exit_code = _powershell_exit(
                    Path(step.command[0]), step.command[1:], root
                )
            case StepKind.COMMAND:
                exit_code = _command_exit(step.command, root)
            case _ as unreachable:
                assert_never(unreachable)
    except SystemExit:
        elapsed = time.perf_counter() - started
        _LOG.error(
            "step=%s exit=1 seconds=%.2f command=%s",
            step.name,
            elapsed,
            step.command,
        )
        raise
    elapsed = time.perf_counter() - started
    _LOG.info(
        "step=%s exit=%s seconds=%.2f command=%s",
        step.name,
        exit_code,
        elapsed,
        step.command,
    )
    if exit_code != 0:
        raise SystemExit(f"Step failed: {step.name} (exit code {exit_code})")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse verify.py command-line arguments."""
    parser = argparse.ArgumentParser(description="Run Blinter quality checks.")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply autopep8, isort, and pyproject-fmt fixes before running checks",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip pytest. CI runs the suite in a separate matrix job.",
    )
    parser.add_argument(
        "--windows-only",
        action="store_true",
        help=(
            "Run only Windows checks: cmd.exe oracle, PSScriptAnalyzer, Pester, "
            "and blinter install/uninstall lint"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Execute formatting, linting, security, and test checks."""
    _configure_logging()
    args = _parse_args(argv)
    _require_cpython()
    fix = cast(bool, args.fix)
    skip_pytest = cast(bool, args.skip_pytest)
    windows_only = cast(bool, args.windows_only)
    root = _repo_root()
    uv_executable = "" if windows_only else _require_uv()
    steps = select_steps(
        StepRequest(
            root=root,
            fix=fix,
            skip_pytest=skip_pytest,
            windows_only=windows_only,
            is_windows=_is_windows(),
            corpus_present=_corpus_present(root),
            uv_executable=uv_executable,
        )
    )
    for step in steps:
        _execute_step(step, root)
    print("All verification steps passed.")


if __name__ == "__main__":
    main()
