#!/usr/bin/env python3
"""Benchmark Blinter lint performance on synthetic or real batch files."""

from __future__ import annotations

import argparse
import cProfile
import json
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import time

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_PATH = _REPO_ROOT / "spec" / "benchmark" / "synthetic-baseline.json"
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from blinter import lint_batch_file  # noqa: E402

_LABEL_HEAVY_COUNT = 2000


def _write_temp_batch(lines: list[str]) -> Path:
    """Write lines to a temporary .bat file and return its path."""
    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".bat",
        delete=False,
        encoding="utf-8",
    )
    temp_file.write("\n".join(lines))
    temp_file.close()
    return Path(temp_file.name)


def _generate_label_heavy_file(label_count: int = _LABEL_HEAVY_COUNT) -> Path:
    """Generate a file with many labels and unique CALL targets."""
    lines = ["@echo off", "setlocal"]
    for index in range(label_count):
        lines.append(f"call :label{index}")
    for index in range(label_count):
        lines.append(f":label{index}")
        lines.append("exit /b 0")
    lines.append("endlocal")
    return _write_temp_batch(lines)


def _generate_synthetic_file(line_count: int = 2838) -> Path:
    """Generate a realistic multi-section batch file for benchmarking."""
    lines = ["@echo off", "setlocal enabledelayedexpansion"]
    for index in range(line_count - 4):
        section = index % 7
        if section == 0:
            lines.append(f"set VAR{index}=C:\\temp\\value{index}.txt")
        elif section == 1:
            lines.append(f"if exist C:\\data\\file{index}.log echo found {index}")
        elif section == 2:
            lines.append(f"for %%a in (1 2 3) do echo %%a {index}")
        elif section == 3:
            lines.append(f"call :sub{index % 50} arg{index}")
        elif section == 4:
            lines.append(f"set /a TOTAL=TOTAL+{index % 10}")
        elif section == 5:
            lines.append(f"echo Processing item {index} && echo done {index}")
        else:
            lines.append(f"echo line {index} >nul")
    lines.extend(["endlocal", "exit /b 0"])
    return _write_temp_batch(lines)


def _case_int(case: dict[str, object], key: str, default: int) -> int:
    """Read an integer field from a baseline case."""
    value = case.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value)


def _case_file(case: dict[str, object]) -> Path:
    """Build the temporary batch file for one baseline case."""
    kind = str(case["kind"])
    if kind == "synthetic":
        return _generate_synthetic_file(_case_int(case, "line_count", 2838))
    if kind == "labels":
        return _generate_label_heavy_file(
            _case_int(case, "label_count", _LABEL_HEAVY_COUNT)
        )
    raise ValueError(f"Unknown benchmark kind: {kind}")


def _median_lint_seconds(file_path: Path, runs: int) -> float:
    """Return the median lint time for ``file_path``."""
    durations = [_run_timed_lint(file_path) for _ in range(runs)]
    median = statistics.median(durations)
    print(f"File: {file_path}")
    print(f"Runs: {runs}")
    print("Timings (seconds): " + ", ".join(f"{value:.3f}" for value in durations))
    print(f"Median: {median:.3f}s")
    return median


def _check_committed_baselines(runs: int) -> int:
    """Fail when any committed benchmark case exceeds its ceiling."""
    if not _BASELINE_PATH.is_file():
        print(f"Baseline file missing: {_BASELINE_PATH}", file=sys.stderr)
        return 1
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    margin = float(baseline.get("margin_ratio", 1.0))
    cases = baseline.get("cases")
    if not isinstance(cases, list) or not cases:
        print("Baseline file has no cases", file=sys.stderr)
        return 1
    failed = False
    for case in cases:
        if not isinstance(case, dict):
            print("Baseline case is not an object", file=sys.stderr)
            return 1
        name = str(case.get("name", case.get("kind", "case")))
        file_path = _case_file(case)
        try:
            print(f"Case: {name}")
            median = _median_lint_seconds(file_path, runs)
            base_median = float(case["median_seconds"])
            ceiling = base_median * (1.0 + margin)
            print(
                f"Baseline median: {base_median:.3f}s, "
                f"ceiling (+{margin * 100:.0f}%): {ceiling:.3f}s"
            )
            if median > ceiling:
                print(
                    f"PERF REGRESSION: {name} median {median:.3f}s "
                    f"exceeds ceiling {ceiling:.3f}s",
                    file=sys.stderr,
                )
                failed = True
        finally:
            file_path.unlink(missing_ok=True)
    if failed:
        return 1
    print("Performance baseline check passed")
    return 0


def _run_timed_lint(file_path: Path) -> float:
    start = time.process_time()
    lint_batch_file(str(file_path))
    return time.process_time() - start


def _print_profile(file_path: Path, top_n: int) -> None:
    profiler = cProfile.Profile()

    def _profiled_lint() -> None:
        lint_batch_file(str(file_path))

    profiler.runcall(_profiled_lint)
    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    stats.print_stats(top_n)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Blinter lint performance.")
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to a .bat/.cmd file (default: generate synthetic file)",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=2838,
        help="Line count for synthetic file when no path is given (default: 2838)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of timed runs (default: 3)",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Run cProfile and print top functions by cumulative time",
    )
    parser.add_argument(
        "--check-baseline",
        action="store_true",
        help="Fail when median exceeds committed baseline (spec/benchmark/synthetic-baseline.json)",
    )
    parser.add_argument(
        "--profile-top",
        type=int,
        default=20,
        help="Number of profile rows to print (default: 20)",
    )
    args = parser.parse_args()

    if args.check_baseline and not args.file:
        return _check_committed_baselines(args.runs)

    generated = False
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"File not found: {file_path}", file=sys.stderr)
            return 1
    else:
        file_path = _generate_synthetic_file(args.lines)
        generated = True
        print(f"Generated synthetic file: {file_path} ({args.lines} lines)")

    try:
        _median_lint_seconds(file_path, args.runs)
        if args.profile:
            print()
            _print_profile(file_path, args.profile_top)
    finally:
        if generated:
            file_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
