"""Performance regression gate for synthetic lint benchmark."""

from __future__ import annotations

from pathlib import Path
import platform
import subprocess
import sys
import time

import pytest

from blinter import lint_batch_file

_REPO = Path(__file__).resolve().parent.parent


def _skips_absolute_cpu_baseline() -> bool:
    """Intel macOS is slower than the hosts that recorded the ceiling."""
    return sys.platform == "darwin" and platform.machine().lower() == "x86_64"


_BENCHMARK_RUNNER = (
    "import runpy, sys; "
    "sys.argv = ['benchmark_lint.py', '--runs', '3', '--check-baseline']; "
    "runpy.run_path('scripts/benchmark_lint.py', run_name='__main__')"
)


@pytest.mark.skipif(
    _skips_absolute_cpu_baseline(),
    reason="Intel macOS CPU time is several times the committed ceiling",
)
def test_synthetic_lint_within_baseline() -> None:
    # Use runpy.run_path instead of executing scripts/benchmark_lint.py directly:
    # on Windows, `python scripts/foo.py` puts scripts/ on sys.path[0] and can
    # make the benchmark subprocess much slower than an equivalent runpy launch.
    result = subprocess.run(
        [sys.executable, "-c", _BENCHMARK_RUNNER],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"benchmark baseline check failed:\n{result.stdout}\n{result.stderr}"


_SCALING_ATTEMPTS = 3


def _cpu_seconds(script: Path) -> float:
    """Return process CPU time spent linting ``script``."""
    start = time.process_time()
    lint_batch_file(str(script))
    return time.process_time() - start


def _assert_scales_within(small_script: Path, large_script: Path, factor: int) -> None:
    """Assert the larger input costs at most ``factor`` times the smaller one.

    One scheduler stall on a shared CI runner can inflate either timing, so a
    failing comparison is measured again. A real super-linear regression fails
    every attempt, because each attempt keeps the least time seen so far for
    both inputs, while a one-off spike clears on the next attempt.
    """
    small = large = float("inf")
    for _ in range(_SCALING_ATTEMPTS):
        small = min(small, _cpu_seconds(small_script))
        large = min(large, _cpu_seconds(large_script))
        if large <= max(small, 0.05) * factor:
            return
    assert large <= max(small, 0.05) * factor, (
        f"large input took {large:.3f}s against {small:.3f}s for the small one "
        f"(limit {factor}x) in all {_SCALING_ATTEMPTS} attempts"
    )


def test_scaling_check_tolerates_one_spike_but_not_a_regression(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A single slow sample is re-measured, while a consistent slowdown still fails."""
    small, large = tmp_path / "small.bat", tmp_path / "large.bat"

    def _fake(samples: dict[Path, list[float]]) -> None:
        monkeypatch.setattr(
            sys.modules[__name__],
            "_cpu_seconds",
            lambda script: samples[script].pop(0),
        )

    _fake({small: [1.0, 1.0, 1.0], large: [30.0, 5.0, 5.0]})
    _assert_scales_within(small, large, 8)

    _fake({small: [1.0, 1.0, 1.0], large: [30.0, 30.0, 30.0]})
    with pytest.raises(AssertionError, match="in all 3 attempts"):
        _assert_scales_within(small, large, 8)


@pytest.mark.parametrize(
    "template",
    ["for /f %a in ({}) do echo %a", "x &{}x"],
)
def test_long_whitespace_line_scales_linearly(tmp_path: Path, template: str) -> None:
    """A run of spaces lints in near-linear time between 2,000 and 8,000 spaces.

    The S003 and W021 patterns used to rescan a long space run. S003 skips
    a one-line file, so each script has two lines. The line-length cap blanks
    anything over 10,000 characters, so both cases stay under that cap. Four
    times the spaces costs sixteen times as much when the time is quadratic,
    and the limit is 8 times the shorter run, matching the IF-chain check.
    """
    warmup = tmp_path / "warmup_spaces.bat"
    warmup.write_text("@echo off\r\necho hi\r\n", encoding="utf-8")
    lint_batch_file(str(warmup))

    def _write(spaces: int) -> Path:
        script = tmp_path / f"spaces_{spaces}.bat"
        script.write_text(
            "@echo off\r\n" + template.format(" " * spaces) + "\r\n",
            encoding="utf-8",
        )
        return script

    _assert_scales_within(_write(2000), _write(8000), 8)


def test_absolute_baseline_skip_is_intel_macos_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apple Silicon and other hosts still enforce the committed CPU-time ceiling."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert _skips_absolute_cpu_baseline()
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert not _skips_absolute_cpu_baseline()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert not _skips_absolute_cpu_baseline()


def test_if_chain_scales_linearly(tmp_path: Path) -> None:
    """A long chain of IF commands stays near-linear between 2,500 and 8,000 characters.

    The line-length cap blanks anything over 10,000 characters, so the large
    case stays under that cap.
    """
    chunk = "if exist file.txt echo ok && "
    warmup = tmp_path / "warmup_if.bat"
    warmup.write_text("@echo off\r\necho hi\r\n", encoding="utf-8")
    lint_batch_file(str(warmup))

    def _write(length: int) -> Path:
        line = (chunk * ((length // len(chunk)) + 1))[:length]
        script = tmp_path / f"if_{length}.bat"
        script.write_text("@echo off\r\n" + line + "\r\n", encoding="utf-8")
        return script

    _assert_scales_within(_write(2500), _write(8000), 8)


def test_line_count_scales_linearly(tmp_path: Path) -> None:
    """Eight thousand simple lines must stay within 10x the two-thousand-line run."""
    warmup = tmp_path / "warmup.bat"
    warmup.write_text("@echo off\r\necho hi\r\n", encoding="utf-8")
    lint_batch_file(str(warmup))

    def _write_echo_file(count: int) -> Path:
        script = tmp_path / f"echo_{count}.bat"
        lines = ["@echo off", *[f"echo hi {index}" for index in range(count)]]
        script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return script

    _assert_scales_within(_write_echo_file(2000), _write_echo_file(8000), 10)


@pytest.mark.parametrize(
    "fragment",
    ["%a%", "for /f usebackq ", ">echo ", "for /f ", "if "],
)
def test_pathological_long_line_stays_bounded(tmp_path: Path, fragment: str) -> None:
    """A repeated-fragment line at the length cap cannot stall the linter.

    Each fragment once drove a checker pattern into cubic backtracking, taking
    from several seconds to over a minute for one 10,000 character line. The
    ceiling is generous for slow CI hosts but far below those regressions.
    """
    script = tmp_path / "pathological.bat"
    line = (fragment * (9990 // len(fragment) + 1))[:9990]
    script.write_text(f"@echo off\r\n{line}\r\n", encoding="utf-8")
    assert _cpu_seconds(script) < 6.0
