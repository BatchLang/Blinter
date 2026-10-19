#!/usr/bin/env python3
"""Run local quality checks for Blinter."""

from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import platform
import subprocess
import sys
import tomllib
from typing import Sequence, cast

# Portable directory names (no platform-specific separators).
_CHECK_DIRS: tuple[str, ...] = ("src", "tests", "scripts")
_VERIFY_SCRIPT = Path("scripts") / "verify.py"
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
_PACKAGE_DIR = Path("src") / "blinter"
_PYPROJECT = "pyproject.toml"
_PYLINT_OUTPUT = "pylint-output.txt"
_POWERSHELL_SCRIPT = Path("scripts") / "test_exe_smoke.ps1"
_POWERSHELL_HELPERS = Path("scripts") / "TestExeSmoke.Helpers.ps1"
_POWERSHELL_ANALYZER_SETTINGS = Path("scripts") / "PSScriptAnalyzerSettings.psd1"
_PESTER_TESTS = (
    Path("scripts") / "TestExeSmoke.Tests.ps1",
    Path("scripts") / "TestInstallerPs.Tests.ps1",
)
_INSTALLER_PS_DIR = Path("scripts") / "installer_ps"
_BLINTER_SCRIPTS_INI = Path("scripts") / "blinter.ini"
_INSTALL_SCRIPT = Path("scripts") / "install_blinter.cmd"
_UNINSTALL_SCRIPT = Path("scripts") / "uninstall_blinter.cmd"
_INSTALL_SCRIPT_TEST = Path("scripts") / "test_install_scripts.ps1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _python_m(module: str, *module_args: str) -> list[str]:
    """Build a ``sys.executable -m module`` command (works on Windows and Unix)."""
    return [sys.executable, "-m", module, *module_args]


def _run_step(name: str, args: Sequence[str], *, cwd: Path | None = None) -> None:
    """Run a subprocess step; raise SystemExit on non-zero exit code."""
    print(f"==> {name}")
    result = subprocess.run(
        list(args),
        cwd=cwd if cwd is not None else _repo_root(),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {name} (exit code {result.returncode})")


def _run_pylint_package(*, cwd: Path, package_dir: str, report_path: Path) -> None:
    """Run pylint on the package and write UTF-8 output (avoids Windows UTF-16)."""
    print("==> pylint (package)")
    result = subprocess.run(
        _python_m("pylint", package_dir),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    report_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(
            f"Step failed: pylint (package) (exit code {result.returncode})"
        )


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

    print("==> pyproject-fmt")
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


def _run_powershell_step(name: str, command: str, *, cwd: Path | None = None) -> None:
    """Run a PowerShell command on Windows."""
    print(f"==> {name}")
    result = subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=cwd if cwd is not None else _repo_root(),
        env=_windows_powershell_env(),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {name} (exit code {result.returncode})")


def _powershell_path(path: Path) -> str:
    """Return a PowerShell-friendly absolute path string."""
    return str(path.resolve()).replace("'", "''")


def _ensure_powershell_modules(root: Path) -> None:
    """Install PSScriptAnalyzer and Pester when missing."""
    ensure_modules = (
        "$ErrorActionPreference = 'Stop'; "
        "foreach ($moduleName in @('PSScriptAnalyzer', 'Pester')) { "
        "if (-not (Get-Module -ListAvailable -Name $moduleName)) { "
        "Install-Module -Name $moduleName -Force -Scope CurrentUser -AllowClobber "
        "-Repository PSGallery } }"
    )
    _run_powershell_step("PowerShell module prerequisites", ensure_modules, cwd=root)


def _psscriptanalyzer_paths(root: Path) -> list[Path]:
    """Return PowerShell files that should be analyzed."""
    scripts_dir = root / "scripts"
    paths = [
        scripts_dir / _POWERSHELL_HELPERS.name,
        scripts_dir / _POWERSHELL_SCRIPT.name,
        scripts_dir / _INSTALL_SCRIPT_TEST.name,
    ]
    installer_ps_dir = root / _INSTALLER_PS_DIR
    if installer_ps_dir.is_dir():
        paths.extend(sorted(installer_ps_dir.glob("*.ps1")))
    return paths


def _run_psscriptanalyzer(root: Path) -> None:
    """Run PSScriptAnalyzer on smoke and installer PowerShell scripts."""
    analyzer_settings = _powershell_path(root / _POWERSHELL_ANALYZER_SETTINGS)
    analyze_paths = [_powershell_path(path) for path in _psscriptanalyzer_paths(root)]
    joined_paths = ", ".join(f"'{path}'" for path in analyze_paths)
    analyzer_command = (
        "$issues = @(); "
        f"foreach ($path in @({joined_paths})) {{ "
        f"$issues += Invoke-ScriptAnalyzer -Path $path -Settings '{analyzer_settings}' "
        "-Severity Warning }; "
        "if ($issues) { $issues | Format-Table -AutoSize; exit 1 }"
    )
    _run_powershell_step(
        "PSScriptAnalyzer (PowerShell scripts)", analyzer_command, cwd=root
    )


def _run_pester_tests(root: Path) -> None:
    """Run all repository Pester test files."""
    pester_paths = [_powershell_path(root / test_path) for test_path in _PESTER_TESTS]
    joined_paths = ", ".join(f"'{path}'" for path in pester_paths)
    pester_command = (
        "Import-Module Pester -MinimumVersion 5.0 -ErrorAction Stop; "
        f"Invoke-Pester -Path @({joined_paths}) -CI"
    )
    _run_powershell_step("Pester (PowerShell tests)", pester_command, cwd=root)


def _run_blinter_install_scripts(root: Path) -> None:
    """Lint install/uninstall batch scripts with the scripts blinter.ini profile."""
    config_path = root / _BLINTER_SCRIPTS_INI
    scripts_dir = root / "scripts"
    _run_step(
        "blinter (install/uninstall scripts)",
        [
            sys.executable,
            "-m",
            "blinter",
            str(scripts_dir),
            "--no-recursive",
            "--config",
            str(config_path),
        ],
        cwd=root,
    )


def _run_windows_powershell_checks(root: Path) -> None:
    """Run PSScriptAnalyzer, Pester, and install-script lint checks."""
    _ensure_powershell_modules(root)
    _run_psscriptanalyzer(root)
    _run_pester_tests(root)
    _run_blinter_install_scripts(root)


def _run_python_checks(root: Path, *, fix: bool) -> None:
    """Run Python formatting, linting, security, and pytest checks."""
    pylint_report = root / _PYLINT_OUTPUT
    verify_script = str(_VERIFY_SCRIPT)
    corpus_lint_script = str(_CORPUS_LINT_SCRIPT)
    package_dir = str(_PACKAGE_DIR)

    subprocess_steps_before_pylint: list[tuple[str, list[str]]] = [
        ("validate spec schemas", [sys.executable, str(_SPEC_VALIDATE)]),
        ("validate SSOT corpus", [sys.executable, str(_SPEC_VALIDATE_CORPUS)]),
    ]

    if _is_windows():
        subprocess_steps_before_pylint.append(
            (
                "cmd.exe corpus oracle",
                [sys.executable, str(_SPEC_CMD_ORACLE)],
            )
        )

    subprocess_steps_before_pylint.extend(
        [
            (
                "check generated registry.py",
                [sys.executable, str(_SPEC_GENERATE_RULES), "--check"],
            ),
            (
                "check generated expansion_data.py",
                [sys.executable, str(_SPEC_GENERATE_EXPANSION), "--check"],
            ),
            (
                "check generated patterns.py",
                [sys.executable, str(_SPEC_GENERATE_COMMANDS), "--check"],
            ),
            (
                "check generated docs catalog",
                [sys.executable, str(_SPEC_GENERATE_DOCS), "--check"],
            ),
            (
                "SSOT audit (strict)",
                [sys.executable, str(_SPEC_AUDIT), "--strict", "--check"],
            ),
        ]
    )

    subprocess_steps_before_pylint.extend(
        [
            ("autopep8 (trailing whitespace)", _autopep8_args(fix=fix)),
            ("isort", _isort_args(fix=fix)),
            ("pyproject-fmt", []),
            ("black", _python_m("black", "--check", *_CHECK_DIRS)),
            (
                "mypy",
                _python_m(
                    "mypy",
                    package_dir,
                    "tests",
                    verify_script,
                    corpus_lint_script,
                    str(Path("scripts") / "corpus_baseline.py"),
                    str(Path("scripts") / "generate_corpus_baseline.py"),
                    str(Path("scripts") / "benchmark_lint.py"),
                ),
            ),
            (
                "mypy (build_exe)",
                _python_m("mypy", str(Path("scripts") / "build_exe.py")),
            ),
        ]
    )

    subprocess_steps_after_pylint: list[tuple[str, list[str]]] = [
        ("pylint (verify)", _python_m("pylint", verify_script)),
        (
            "bandit",
            _python_m("bandit", "-r", package_dir, "-c", _PYPROJECT, "-ll", "-q"),
        ),
        (
            "pip-audit",
            _python_m(
                "pip_audit", "-r", "requirements.txt", "-r", "requirements-dev.txt"
            ),
        ),
        ("pytest", _python_m("pytest")),
    ]

    for name, step_args in subprocess_steps_before_pylint:
        if name == "pyproject-fmt":
            _run_pyproject_fmt(fix=fix, cwd=root)
        else:
            _run_step(name, step_args, cwd=root)

    _run_pylint_package(cwd=root, package_dir=package_dir, report_path=pylint_report)

    for name, step_args in subprocess_steps_after_pylint:
        _run_step(name, step_args, cwd=root)


def main() -> None:
    """Execute formatting, linting, security, and test checks."""
    parser = argparse.ArgumentParser(description="Run Blinter quality checks.")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply autopep8, isort, and pyproject-fmt fixes before running checks",
    )
    parser.add_argument(
        "--powershell-only",
        action="store_true",
        help=(
            "Run only Windows PowerShell checks (PSScriptAnalyzer, Pester, "
            "and blinter install/uninstall lint)"
        ),
    )
    args = parser.parse_args()
    fix = cast(bool, args.fix)
    powershell_only = cast(bool, args.powershell_only)

    root = _repo_root()
    corpus_lint_script = str(_CORPUS_LINT_SCRIPT)

    if powershell_only:
        if not _is_windows():
            raise SystemExit("PowerShell checks require Windows.")
        _run_windows_powershell_checks(root)
        print("All PowerShell verification steps passed.")
        return

    _run_python_checks(root, fix=fix)

    if _is_windows():
        _run_windows_powershell_checks(root)
    else:
        print("Skipping PowerShell checks (Windows only).")

    corpus_dir = root / _CORPUS_DIR
    baseline_path = root / "tests" / "fixtures" / "corpus-baseline.json"
    if corpus_dir.is_dir() and baseline_path.is_file():
        _run_step(
            "corpus baseline check",
            [sys.executable, corpus_lint_script, "--check-baseline"],
            cwd=root,
        )

    print("All verification steps passed.")


if __name__ == "__main__":
    main()
