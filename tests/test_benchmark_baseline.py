"""Performance regression gate for synthetic lint benchmark."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

from blinter import lint_batch_file

_REPO = Path(__file__).resolve().parent.parent


_BENCHMARK_RUNNER = (
    "import runpy, sys; "
    "sys.argv = ['benchmark_lint.py', '--runs', '3', '--check-baseline']; "
    "runpy.run_path('scripts/benchmark_lint.py', run_name='__main__')"
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
    )
    assert (
        result.returncode == 0
    ), f"benchmark baseline check failed:\n{result.stdout}\n{result.stderr}"


def _cpu_seconds(script: Path) -> float:
    """Return process CPU time spent linting ``script``."""
    start = time.process_time()
    lint_batch_file(str(script))
    return time.process_time() - start


def test_long_whitespace_line_lints_quickly(tmp_path: Path) -> None:
    """S003 must not backtrack on a long run of spaces."""
    script = tmp_path / "spaces.bat"
    script.write_text(
        "for /f %a in (" + (" " * 5000) + ") do echo %a\r\n",
        encoding="utf-8",
    )
    assert _cpu_seconds(script) < 1.0


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

    small = _cpu_seconds(_write(2500))
    large = _cpu_seconds(_write(8000))
    assert large <= max(small, 0.05) * 8


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

    small = _cpu_seconds(_write_echo_file(2000))
    large = _cpu_seconds(_write_echo_file(8000))
    assert large <= max(small, 0.05) * 10
