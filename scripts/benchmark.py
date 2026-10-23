#!/usr/bin/env python3
"""Benchmark Blinter install and startup paths. Standard library only.

The workflow runs this file before project dependencies are installed, so it
cannot import third-party packages. Dates are timezone-aware UTC.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
import logging
import math
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Literal, TypedDict

# Direct execution (`python scripts/benchmark.py`) puts scripts/ on sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.benchmark_release import (  # noqa: E402  # pylint: disable=wrong-import-position
    _api_headers,
    _download_verified,
    _fetch_json,
    _require_sha256,
    _require_str,
    _runner_arch,
    extract_zip,
    locate_exe,
    release_api_url,
    select_asset,
)

_LOG = logging.getLogger("scripts.benchmark")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?$")
_VERSION_IN_OUTPUT = re.compile(r"\d+(?:\.\d+)+\S*")
_INSTALL_TIMEOUT_SECONDS = 900.0
_LAUNCH_TIMEOUT_SECONDS = 300.0
_LINT_TIMEOUT_SECONDS = 120.0
_API_TIMEOUT_SECONDS = 60.0
_TOOL_TIMEOUT_SECONDS = 60.0
_DROPPED_ENV = frozenset(
    {
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "PYTHONHOME",
        "PYTHONPATH",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
        "VIRTUAL_ENV",
    }
)
WORKLOADS: dict[str, list[str]] = {
    "version": ["--version"],
    "small": ["--no-config", "small.bat"],
    "large": ["--no-config", "large.bat"],
    "tree": ["--no-config", "tree"],
}
_LINT_EXIT_CODES = frozenset({0, 1})
_Mode = Literal["python", "exe"]


class WorkloadStats(TypedDict):
    """Summary of one workload's timed samples, in milliseconds."""

    n: int
    min: float
    median: float
    mean: float
    stdev: float
    p90: float
    max: float


class FamilyResult(TypedDict):
    """Install timings and the commands those installs can run."""

    times: list[float]
    env: dict[str, str]
    first: bool
    commands: dict[str, list[str]]


class Target(TypedDict):
    """One installed command undergoing the workload loop."""

    impl: str
    command: str
    argv: list[str]
    env: dict[str, str]
    install_ms: list[float]
    measure_first: bool
    samples: dict[str, list[float]]
    errors: dict[str, str]
    version_output: str
    first_run_ms: float | None


class CommandResult(TypedDict):
    """JSON record for one installed command."""

    impl: str
    command: str
    blinter_version: str
    install_cold_ms: float
    install_warm_ms: float | None
    first_run_ms: float | None
    workloads: dict[str, WorkloadStats]
    errors: dict[str, str]


class BenchConfig(TypedDict):
    """Parsed benchmark settings."""

    mode: _Mode
    label: str
    python_label: str
    out: Path
    installs: int
    budget: float
    version: str
    runs: int
    warmup: int
    spec: str


def _configure_logging() -> None:
    """Attach one stderr handler when the process has not configured logging."""
    if _LOG.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False


def emit_progress(message: str) -> None:
    """Log a progress line and print it for the Actions log."""
    _LOG.info("%s", message)
    print(message, flush=True)


def emit_warning(message: str) -> None:
    """Log a warning and emit a one-line GitHub Actions annotation."""
    _LOG.warning("%s", message)
    print(f"::warning::{' '.join(message.split())}", flush=True)


def _positive_int(text: str) -> int:
    """Parse an integer that is at least 1."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _positive_float(text: str) -> float:
    """Parse a finite float that is greater than 0."""
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return value


def _env_int(name: str, default: int, *, minimum: int) -> int:
    """Read an integer environment variable, or return the default when unset."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise SystemExit(f"{name} must be >= {minimum}, got {value}")
    return value


def _version_from_env() -> str:
    """Return the requested Blinter version with a leading v stripped."""
    raw = os.environ.get("BLINTER_VERSION", "").strip()
    if raw[:1] in {"v", "V"}:
        raw = raw[1:]
    if raw and _VERSION_RE.fullmatch(raw) is None:
        raise SystemExit(f"BLINTER_VERSION is not a version: {raw!r}")
    return raw


def _package_spec(version: str) -> str:
    """Return the pip/uv requirement for the requested version."""
    if not version:
        return "Blinter"
    return f"Blinter=={version}"


def _mode(value: object) -> _Mode:
    """Return a supported benchmark mode."""
    if value == "python":
        return "python"
    if value == "exe":
        return "exe"
    raise SystemExit(f"unsupported mode: {value}")


def batch_text(lines: int, seed: int) -> str:
    """Return a synthetic batch file of at least ``lines`` CRLF-terminated lines."""
    out = ["@echo off", "setlocal enabledelayedexpansion"]
    index = 0
    while len(out) < lines:
        index += 1
        number = seed * 100000 + index
        out.extend(
            [
                f":step_{number}",
                f"set /p ANSWER_{number}=Value for step {number}: ",
                f'if exist "%TEMP%\\work_{number}.tmp" del "%TEMP%\\work_{number}.tmp"',
                f'for /f "tokens=1,2 delims=," %%a in (data_{number}.csv) do echo %%a %%b',
                f"set /a COUNT+={index}",
                "echo Processing !COUNT! of %TOTAL%",
                f"call :helper_{number} %COUNT%",
                "xcopy /y %SRC% %DST%",
                "if errorlevel 1 goto :fail",
                "REM filler comment to give the file some bulk",
                f"goto :step_{number + 1}",
            ]
        )
    out.extend([":fail", "exit /b 1"])
    return "\r\n".join(out) + "\r\n"


def make_corpus(root: Path) -> Path:
    """Write the small, large, and directory workloads under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "small.bat").write_text(batch_text(30, 1), encoding="utf-8", newline="")
    (root / "large.bat").write_text(batch_text(1500, 2), encoding="utf-8", newline="")
    tree = root / "tree"
    tree.mkdir(exist_ok=True)
    for index in range(15):
        (tree / f"script_{index:02d}.bat").write_text(
            batch_text(200, 10 + index),
            encoding="utf-8",
            newline="",
        )
    _LOG.info("wrote corpus at %s", root)
    return root


def make_env(**extra: str) -> dict[str, str]:
    """Return a child environment without inherited interpreters or tokens."""
    env = {key: value for key, value in os.environ.items() if key not in _DROPPED_ENV}
    env.update(
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        UV_PYTHON_DOWNLOADS="never",
        UV_NO_PROGRESS="1",
        NO_COLOR="1",
    )
    env.update(extra)
    return env


def stats(samples: list[float]) -> WorkloadStats:
    """Return min, median, mean, stdev, nearest-rank p90, and max."""
    if not samples:
        raise ValueError("cannot summarize an empty sample")
    ordered = sorted(samples)
    rank = math.ceil(0.9 * len(ordered))
    index = min(max(rank, 1), len(ordered)) - 1
    return {
        "n": len(ordered),
        "min": ordered[0],
        "median": float(statistics.median(ordered)),
        "mean": float(statistics.fmean(ordered)),
        "stdev": float(statistics.stdev(ordered)) if len(ordered) > 1 else 0.0,
        "p90": ordered[index],
        "max": ordered[-1],
    }


def _venv_paths(venv: Path) -> tuple[Path, Path]:
    """Return the Python and blinter executables inside a virtual environment."""
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return bindir / f"python{suffix}", bindir / f"blinter{suffix}"


def sh(
    command: Sequence[str],
    env: dict[str, str],
    timeout: float,
    cwd: Path | None = None,
) -> str:
    """Run a command and return its combined output, or raise RuntimeError."""
    argv = [str(part) for part in command]
    _LOG.info("running %s", argv)
    try:
        completed = subprocess.run(
            argv,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{' '.join(argv)} timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise RuntimeError(f"{' '.join(argv)} failed to start: {exc}") from exc
    if completed.returncode != 0:
        output = completed.stdout or ""
        raise RuntimeError(
            f"{' '.join(argv)} -> exit {completed.returncode}\n{output[-1500:]}"
        )
    return completed.stdout


def _time_calls(
    calls: Sequence[Sequence[str]], env: dict[str, str], cwd: Path
) -> float:
    """Return the milliseconds taken to run ``calls`` in order."""
    started = time.perf_counter()
    for command in calls:
        sh(command, env, _INSTALL_TIMEOUT_SECONDS, cwd)
    return (time.perf_counter() - started) * 1000


def _family(
    times: list[float],
    env: dict[str, str],
    first: bool,
    commands: dict[str, list[str]],
) -> FamilyResult:
    """Return a family result, refusing an install that recorded no timings."""
    if not times:
        raise RuntimeError("install timing produced no samples")
    return {"times": times, "env": env, "first": first, "commands": commands}


def _pip_calls(venv: Path, spec: str) -> list[list[str]]:
    """Return the venv creation and pip install commands."""
    python, _exe = _venv_paths(venv)
    return [
        [sys.executable, "-m", "venv", str(venv)],
        [str(python), "-m", "pip", "install", "--quiet", "--no-input", spec],
    ]


def _uv_pip_calls(
    uv: str,
    venv: Path,
    spec: str,
    *,
    compile_bytecode: bool,
) -> list[list[str]]:
    """Return the uv venv and uv pip install commands."""
    python, _exe = _venv_paths(venv)
    install = [uv, "--quiet", "pip", "install", "--python", str(python)]
    if compile_bytecode:
        install.append("--compile-bytecode")
    install.append(spec)
    return [
        [uv, "--quiet", "venv", "--python", sys.executable, str(venv)],
        install,
    ]


def _uv_tool_call(uv: str, spec: str, *, compile_bytecode: bool) -> list[str]:
    """Return one ``uv tool install`` command."""
    command = [uv, "--quiet", "tool", "install", "--python", sys.executable]
    if compile_bytecode:
        command.append("--compile-bytecode")
    command.append(spec)
    return command


def _installed_commands(root: Path, installs: int) -> dict[str, list[str]]:
    """Return the blinter commands from the last install's virtual environment."""
    python, exe = _venv_paths(root / f"venv{installs - 1}")
    return {
        "blinter": [str(exe)],
        "python -m blinter": [str(python), "-m", "blinter"],
    }


def fam_pip(root: Path, spec: str, installs: int, _uv: str) -> FamilyResult:
    """Install with ``python -m venv`` and pip. The first install has a cold cache."""
    env = make_env(PIP_CACHE_DIR=str(root / "cache"))
    times = [
        _time_calls(_pip_calls(root / f"venv{index}", spec), env, root)
        for index in range(installs)
    ]
    return _family(times, env, True, _installed_commands(root, installs))


def fam_uv_pip(compile_bytecode: bool) -> Callable[[Path, str, int, str], FamilyResult]:
    """Return an installer that uses ``uv venv`` and ``uv pip install``."""

    def run(root: Path, spec: str, installs: int, uv: str) -> FamilyResult:
        env = make_env(UV_CACHE_DIR=str(root / "cache"))
        times = [
            _time_calls(
                _uv_pip_calls(
                    uv,
                    root / f"venv{index}",
                    spec,
                    compile_bytecode=compile_bytecode,
                ),
                env,
                root,
            )
            for index in range(installs)
        ]
        return _family(times, env, True, _installed_commands(root, installs))

    return run


def fam_uv_tool(
    compile_bytecode: bool,
) -> Callable[[Path, str, int, str], FamilyResult]:
    """Return an installer that uses ``uv tool install`` in a fresh tool dir."""

    def run(root: Path, spec: str, installs: int, uv: str) -> FamilyResult:
        times: list[float] = []
        env: dict[str, str] = {}
        for index in range(installs):
            env = make_env(
                UV_CACHE_DIR=str(root / "cache"),
                UV_TOOL_DIR=str(root / f"tools{index}"),
                UV_TOOL_BIN_DIR=str(root / f"bin{index}"),
            )
            times.append(
                _time_calls(
                    [_uv_tool_call(uv, spec, compile_bytecode=compile_bytecode)],
                    env,
                    root,
                )
            )
        exe_name = "blinter.exe" if os.name == "nt" else "blinter"
        exe = root / f"bin{installs - 1}" / exe_name
        return _family(times, env, True, {"blinter": [str(exe)]})

    return run


def fam_uvx(root: Path, spec: str, installs: int, uv: str) -> FamilyResult:
    """Time ``uv tool run`` itself. The first run is the cold-cache install."""
    env = make_env(UV_CACHE_DIR=str(root / "cache"))
    base = [
        uv,
        "--quiet",
        "tool",
        "run",
        "--python",
        sys.executable,
        "--from",
        spec,
        "blinter",
    ]
    times = [
        _time_calls([base + ["--version"]], env, root) for _index in range(installs)
    ]
    return _family(times, env, False, {"blinter": base})


_FamilyRunner = Callable[[Path, str, int, str], FamilyResult]
PY_FAMILIES: tuple[tuple[str, str, _FamilyRunner], ...] = (
    ("pip venv", "pip", fam_pip),
    ("uv pip venv", "uvpip", fam_uv_pip(False)),
    ("uv pip venv +bytecode", "uvpipc", fam_uv_pip(True)),
    ("uv tool install", "uvtool", fam_uv_tool(False)),
    ("uv tool install +bytecode", "uvtoolc", fam_uv_tool(True)),
    ("uvx (ephemeral)", "uvx", fam_uvx),
)


def fam_exe(root: Path, version: str, arch: str) -> tuple[FamilyResult, str]:
    """Download, verify, and extract the standalone exe for ``arch``."""
    release = _fetch_json(
        release_api_url(version), _api_headers(), _API_TIMEOUT_SECONDS
    )
    tag = _require_str(release.get("tag_name"), "release tag_name")
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise RuntimeError("release assets must be a list")
    asset = select_asset(raw_assets, tag, arch)
    name = _require_str(asset.get("name"), "asset name")
    url = _require_str(asset.get("browser_download_url"), "asset browser_download_url")
    digest = _require_sha256(asset)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / name
    started = time.perf_counter()
    _download_verified(url, archive, digest)
    extract_zip(archive, root / "x")
    exe = locate_exe(root / "x", name)
    elapsed_ms = (time.perf_counter() - started) * 1000
    family = _family(
        [elapsed_ms],
        make_env(),
        True,
        {f"blinter.exe ({arch})": [str(exe)]},
    )
    return family, tag


def _new_target(
    impl: str, command: str, argv: list[str], family: FamilyResult
) -> Target:
    """Return an empty workload record for one installed command."""
    samples: dict[str, list[float]] = {}
    for name in WORKLOADS:
        samples[name] = []
    return {
        "impl": impl,
        "command": command,
        "argv": argv,
        "env": family["env"],
        "install_ms": family["times"],
        "measure_first": family["first"],
        "samples": samples,
        "errors": {},
        "version_output": "",
        "first_run_ms": None,
    }


def _targets_from_family(impl: str, family: FamilyResult) -> list[Target]:
    """Expand one install family into one target per command."""
    return [
        _new_target(impl, command, argv, family)
        for command, argv in family["commands"].items()
    ]


def _record_failure(
    errors: list[dict[str, str]],
    impl: str,
    exc: BaseException,
    summary: str,
) -> None:
    """Log an install or launch failure and keep it for the JSON report."""
    _LOG.exception("%s", summary)
    emit_warning(f"{summary}: {exc}")
    errors.append({"impl": impl, "error": str(exc)[-1500:]})


def _install_python_families(
    root: Path,
    config: BenchConfig,
    uv: str | None,
    errors: list[dict[str, str]],
) -> list[Target]:
    """Install every Python family. A failed family does not cancel the others."""
    if uv is None:
        emit_warning(
            f"uv not found on PATH ({config['label']} py{config['python_label']})"
        )
        errors.append({"impl": "uv", "error": "uv not found on PATH"})
        return []
    targets: list[Target] = []
    for impl, slug, install in PY_FAMILIES:
        emit_progress(f"== installing: {impl}")
        try:
            family = install(root / slug, config["spec"], config["installs"], uv)
        except Exception as exc:
            _record_failure(
                errors,
                impl,
                exc,
                f"{impl} failed on {config['label']} py{config['python_label']}",
            )
            continue
        targets.extend(_targets_from_family(impl, family))
    return targets


def _install_exe(
    root: Path,
    config: BenchConfig,
    extra_meta: dict[str, object],
    errors: list[dict[str, str]],
) -> list[Target]:
    """Download the standalone exe, recording a failure instead of aborting."""
    arch = _runner_arch()
    emit_progress(f"== downloading exe ({arch})")
    try:
        family, tag = fam_exe(root / "exe", config["version"], arch)
    except Exception as exc:
        _record_failure(
            errors, "standalone exe", exc, f"exe failed on {config['label']}"
        )
        return []
    extra_meta["release_tag"] = tag
    return _targets_from_family("standalone exe", family)


def _probe_target(target: Target, corpus: Path) -> str | None:
    """Run ``--version``. Return an error string when the command does not start."""
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [*target["argv"], "--version"],
            env=target["env"],
            cwd=corpus,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_LAUNCH_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cannot launch: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    target["version_output"] = output[0] if output else ""
    if target["measure_first"]:
        target["first_run_ms"] = elapsed_ms
    if completed.returncode == 0:
        return None
    detail = (completed.stderr or "")[-500:]
    return f"--version exit {completed.returncode}: {detail}"


def _probe_targets(
    targets: Sequence[Target],
    corpus: Path,
    errors: list[dict[str, str]],
) -> list[Target]:
    """Return the targets whose ``--version`` exits 0."""
    alive: list[Target] = []
    for target in targets:
        failure = _probe_target(target, corpus)
        if failure is None:
            alive.append(target)
            continue
        label = f"{target['impl']} / {target['command']}"
        emit_warning(f"{label}: {failure}")
        errors.append({"impl": label, "error": failure[-1500:]})
    return alive


def _budget_exhausted(
    round_index: int,
    warmup: int,
    started: float,
    budget: float,
    workload_name: str,
) -> bool:
    """Return whether this round should stop because the workload budget elapsed.

    The first three measured rounds always run so a slow machine still records
    a median instead of an empty sample.
    """
    if round_index < warmup + 3:
        return False
    if time.perf_counter() - started <= budget:
        return False
    measured = round_index - warmup
    emit_warning(
        f"workload {workload_name} stopped after {measured} measured runs "
        f"(budget {budget:.0f}s)"
    )
    return True


def run_once(argv: Sequence[str], env: dict[str, str], cwd: Path) -> float:
    """Return one lint run's duration. Exit code 1 is a finding, not a crash."""
    try:
        started = time.perf_counter()
        completed = subprocess.run(
            [str(part) for part in argv],
            env=env,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_LINT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"timed out after {_LINT_TIMEOUT_SECONDS:.0f}s") from exc
    except OSError as exc:
        raise RuntimeError(f"failed to start: {exc}") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000
    if completed.returncode not in _LINT_EXIT_CODES:
        detail = (completed.stderr or "").strip()[-300:]
        raise RuntimeError(f"exit {completed.returncode}: {detail}")
    return elapsed_ms


def _measure_round(
    live: list[Target],
    workload_name: str,
    workload_args: Sequence[str],
    corpus: Path,
    *,
    record: bool,
) -> None:
    """Time every live target once. A failed target leaves the round."""
    for target in list(live):
        try:
            elapsed_ms = run_once(
                target["argv"] + list(workload_args), target["env"], corpus
            )
        except (RuntimeError, OSError) as exc:
            target["errors"][workload_name] = str(exc)
            live.remove(target)
            emit_warning(
                f"{target['impl']} / {target['command']} {workload_name}: {exc}"
            )
            continue
        if record:
            target["samples"][workload_name].append(elapsed_ms)


def _measure_workloads(
    alive: Sequence[Target],
    corpus: Path,
    runs: int,
    warmup: int,
    budget: float,
) -> None:
    """Interleave targets so runner drift hits every command in the same order."""
    for workload_name, workload_args in WORKLOADS.items():
        emit_progress(f"== workload: {workload_name} ({len(alive)} targets)")
        started = time.perf_counter()
        live = list(alive)
        for round_index in range(warmup + runs):
            if _budget_exhausted(round_index, warmup, started, budget, workload_name):
                break
            _measure_round(
                live,
                workload_name,
                workload_args,
                corpus,
                record=round_index >= warmup,
            )


def _blinter_version(output: str) -> str:
    """Return the first version-like token in ``--version`` output."""
    match = _VERSION_IN_OUTPUT.search(output)
    if match is None:
        return output
    return match.group(0)


def _warm_median(times: list[float]) -> float | None:
    """Return the median of every install after the cold first one."""
    if len(times) < 2:
        return None
    return float(statistics.median(times[1:]))


def _command_result(target: Target) -> CommandResult:
    """Convert a measured target into the JSON result record."""
    times = target["install_ms"]
    if not times:
        raise RuntimeError(f"{target['impl']} recorded no install timing")
    workloads: dict[str, WorkloadStats] = {}
    for name, samples in target["samples"].items():
        if samples:
            workloads[name] = stats(samples)
    return {
        "impl": target["impl"],
        "command": target["command"],
        "blinter_version": _blinter_version(target["version_output"]),
        "install_cold_ms": times[0],
        "install_warm_ms": _warm_median(times),
        "first_run_ms": target["first_run_ms"],
        "workloads": workloads,
        "errors": target["errors"],
    }


def _tool_versions(uv: str | None) -> dict[str, str]:
    """Return uv and pip version strings when those commands succeed."""
    versions: dict[str, str] = {}
    if uv:
        try:
            versions["uv_version"] = sh(
                [uv, "--version"], make_env(), _TOOL_TIMEOUT_SECONDS
            ).strip()
        except (RuntimeError, OSError) as exc:
            emit_warning(f"uv --version failed: {exc}")
    try:
        pip_output = sh(
            [sys.executable, "-m", "pip", "--version"],
            make_env(),
            _TOOL_TIMEOUT_SECONDS,
        )
    except (RuntimeError, OSError) as exc:
        emit_warning(f"pip --version failed: {exc}")
        return versions
    versions["pip_version"] = pip_output.split(" from ", maxsplit=1)[0]
    return versions


def _median_cell(result: CommandResult, workload: str) -> str:
    """Return one right-aligned median, or a blank when that workload failed."""
    summary = result["workloads"].get(workload)
    if summary is None:
        return f"{'-':>9}"
    return f"{summary['median']:9.0f}"


def _print_table(results: Sequence[CommandResult]) -> None:
    """Print the median table that shows up in the Actions log."""
    header = "median ms        " + "".join(f"{name:>9}" for name in WORKLOADS)
    emit_progress(f"\n{header}   install(cold/warm)")
    for result in results:
        medians = "".join(_median_cell(result, name) for name in WORKLOADS)
        warm = result["install_warm_ms"]
        warm_text = "-" if warm is None else f"{warm:.0f}"
        label = f"{result['impl']} | {result['command']}"
        emit_progress(
            f"{label[:40]:40}{medians}   {result['install_cold_ms']:.0f}/{warm_text}"
        )


def _write_output(
    path: Path,
    meta: dict[str, object],
    results: Sequence[CommandResult],
    errors: Sequence[dict[str, str]],
) -> None:
    """Write the benchmark JSON, creating the parent directory when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "results": list(results), "errors": list(errors)}
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _LOG.info("wrote %s (%s results, %s errors)", path, len(results), len(errors))


def _base_meta(config: BenchConfig, uv: str | None) -> dict[str, object]:
    """Return the JSON metadata block, including tool versions when available."""
    meta: dict[str, object] = {
        "mode": config["mode"],
        "label": config["label"],
        "python_label": config["python_label"],
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "requested_version": config["version"] or "latest",
        "runs": config["runs"],
        "warmup": config["warmup"],
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    meta.update(_tool_versions(uv))
    return meta


def _collect(
    config: BenchConfig,
    root: Path,
) -> tuple[list[CommandResult], list[dict[str, str]], dict[str, object]]:
    """Install, probe, and measure. Family failures are returned, not raised."""
    corpus = make_corpus(root / "corpus")
    uv = shutil.which("uv")
    errors: list[dict[str, str]] = []
    extra_meta: dict[str, object] = {}
    if config["mode"] == "python":
        targets = _install_python_families(root, config, uv, errors)
    else:
        targets = _install_exe(root, config, extra_meta, errors)
    alive = _probe_targets(targets, corpus, errors)
    _measure_workloads(
        alive, corpus, config["runs"], config["warmup"], config["budget"]
    )
    return [_command_result(target) for target in targets], errors, extra_meta


def _remove_tree(root: Path) -> None:
    """Delete the temp directory. A locked file is logged and left behind."""
    try:
        shutil.rmtree(root)
    except OSError as exc:
        _LOG.warning("could not remove benchmark temp dir %s: %s", root, exc)


def _parse_config(argv: Sequence[str] | None) -> BenchConfig:
    """Parse CLI arguments and the workflow's environment variables."""
    parser = argparse.ArgumentParser(
        description="Benchmark Blinter install and run paths."
    )
    parser.add_argument("--mode", choices=["python", "exe"], required=True)
    parser.add_argument(
        "--label", required=True, help="runner label, e.g. windows-latest"
    )
    parser.add_argument("--python-label", default="")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--installs", type=_positive_int, default=3)
    parser.add_argument("--budget", type=_positive_float, default=60.0)
    args = parser.parse_args(None if argv is None else list(argv))
    version = _version_from_env()
    config: BenchConfig = {
        "mode": _mode(args.mode),
        "label": _require_str(args.label, "--label"),
        "python_label": args.python_label if isinstance(args.python_label, str) else "",
        "out": args.out if isinstance(args.out, Path) else Path(str(args.out)),
        "installs": _positive_int(str(args.installs)),
        "budget": _positive_float(str(args.budget)),
        "version": version,
        "runs": _env_int("BENCH_RUNS", 20, minimum=1),
        "warmup": _env_int("BENCH_WARMUP", 3, minimum=0),
        "spec": _package_spec(version),
    }
    return config


def _run(config: BenchConfig, root: Path) -> int:
    """Collect results, always write JSON, and return 1 when nothing was measured."""
    uv = shutil.which("uv")
    meta = _base_meta(config, uv)
    results: list[CommandResult] = []
    errors: list[dict[str, str]] = []
    exit_code = 1
    try:
        results, errors, extra_meta = _collect(config, root)
        meta.update(extra_meta)
        _print_table(results)
        exit_code = 0 if results else 1
        if exit_code != 0:
            emit_warning(f"no benchmark results for {config['label']}")
        return exit_code
    finally:
        _write_output(config["out"], meta, results, errors)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark in a temporary directory and write the JSON result."""
    _configure_logging()
    config = _parse_config(argv)
    root = Path(tempfile.mkdtemp(prefix="blinter-bench-"))
    _LOG.info("benchmark temp dir %s mode %s", root, config["mode"])
    try:
        return _run(config, root)
    finally:
        _remove_tree(root)


if __name__ == "__main__":
    sys.exit(main())
