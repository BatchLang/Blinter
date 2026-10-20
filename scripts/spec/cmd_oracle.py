#!/usr/bin/env python3
"""Run safe corpus fixtures through cmd.exe for behavioral smoke checks (Windows).

Part of the verification pipeline (see scripts/verify.py). Only fixtures that pass
strict static safety checks are executed. Destructive, interactive, or unbounded
corpus cases are listed in spec/corpus/meta/oracle-skip.yaml.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import platform
import re
import subprocess
from typing import Literal

import yaml

_REPO = Path(__file__).resolve().parent.parent.parent
_CORPUS = _REPO / "spec" / "corpus"
_ORACLE_SKIP_YAML = _CORPUS / "meta" / "oracle-skip.yaml"
_DEFAULT_TIMEOUT_S = 3.0
# Smoke oracle: any exit code is acceptable if cmd.exe finishes (fixtures are often
# intentional error cases). Only timeouts count as failures.


def _corpus_inputs() -> list[Path]:
    """Return corpus primary inputs (input.cmd, or input.bat when no .cmd)."""
    inputs: list[Path] = []
    seen_dirs: set[Path] = set()
    for input_path in sorted(_CORPUS.glob("**/input.cmd")):
        inputs.append(input_path)
        seen_dirs.add(input_path.parent)
    for input_path in sorted(_CORPUS.glob("**/input.bat")):
        if input_path.parent in seen_dirs:
            continue
        inputs.append(input_path)
    return inputs


def _load_skip_ids() -> dict[str, str]:
    if not _ORACLE_SKIP_YAML.is_file():
        return {}
    data = yaml.safe_load(_ORACLE_SKIP_YAML.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    skip: dict[str, str] = {}
    for entry in data.get("cases", []):
        if not isinstance(entry, dict):
            continue
        case_id = str(entry.get("id", "")).strip().replace("\\", "/")
        reason = str(entry.get("reason", "listed in oracle-skip.yaml"))
        if case_id:
            skip[case_id] = reason
    return skip


def _expect_oracle_settings(
    case_dir: Path,
) -> tuple[Literal["run", "skip"] | None, float | None]:
    """Return (oracle mode override, per-case timeout override)."""
    expect_path = case_dir / "expect.json"
    if not expect_path.is_file():
        return None, None
    try:
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    mode = expect.get("oracle")
    oracle_mode: Literal["run", "skip"] | None = None
    if mode in {"run", "skip"}:
        oracle_mode = mode
    timeout_raw = expect.get("oracle_timeout_s")
    timeout_s: float | None = None
    if isinstance(timeout_raw, (int, float)) and float(timeout_raw) > 0:
        timeout_s = float(timeout_raw)
    return oracle_mode, timeout_s


def _call_unsafe_reason(text: str, case_dir: Path) -> str | None:
    """Flag CALL targets that may invoke external or uncontrolled scripts."""
    if not re.search(r"\bcall\b", text, re.IGNORECASE):
        return None
    for match in re.finditer(r"\bcall\s+(\S+)", text, re.IGNORECASE):
        target = str(match.group(1)).strip('"')
        if target.startswith(":"):
            continue
        if "%" in target or "!" in target:
            return "call with dynamic target"
        if re.search(r"[\\/]", target):
            return "call to path script"
        if re.search(r"\.[a-z]{1,4}$", target, re.IGNORECASE):
            if (case_dir / target).is_file():
                continue
            if target.lower().endswith((".com", ".exe", ".bat", ".cmd")):
                continue
            return "call may invoke external scripts"
        continue
    return None


def _regex_reason(pattern: str, reason: str) -> Callable[[str, Path], str | None]:
    """Return a check that matches one case-insensitive pattern."""

    def check(text: str, _case_dir: Path) -> str | None:
        if re.search(pattern, text, re.IGNORECASE):
            return reason
        return None

    return check


def _ping_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip unbounded or long ping delays."""
    if not re.search(r"\bping\b", text, re.IGNORECASE):
        return None
    count_match = re.search(r"ping\s+[^\n]*-n\s+(\d+)", text, re.IGNORECASE)
    if count_match is None:
        return "unbounded ping"
    if int(count_match.group(1)) > 3:
        return f"long ping delay (-n {count_match.group(1)})"
    return None


def _timeout_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip timeout commands longer than a smoke-test budget."""
    timeout_match = re.search(r"timeout\s+/t\s+(\d+)", text, re.IGNORECASE)
    if timeout_match and int(timeout_match.group(1)) > 2:
        return f"long timeout ({timeout_match.group(1)}s)"
    return None


def _net_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip net commands that change users or drive mappings."""
    if not re.search(r"\bnet\b", text, re.IGNORECASE):
        return None
    if re.search(r"\bnet\s+user\b", text, re.IGNORECASE) and re.search(
        r"/add", text, re.IGNORECASE
    ):
        return "net user /add"
    if re.search(r"\bnet\s+use\b", text, re.IGNORECASE):
        return "net use"
    return None


def _del_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip wildcard and recursive deletions."""
    if not re.search(r"\bdel\b", text, re.IGNORECASE):
        return None
    if re.search(r"\bdel\s+[^\n]*[*?]", text, re.IGNORECASE):
        return "del with wildcards"
    if re.search(r"\bdel\s+/[qs]", text, re.IGNORECASE):
        return "del with /q or /s"
    return None


def _reg_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip registry deletions."""
    if re.search(r"\breg\b", text, re.IGNORECASE) and re.search(
        r"\breg\s+delete\b", text, re.IGNORECASE
    ):
        return "reg delete"
    return None


def _wmic_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip interactive or mutating WMIC. Read-only get/list queries may run.

    WMIC still ships on Windows 10 (deprecated since 21H1, not removed).
    Missing binaries fail fast, and the oracle accepts any exit code.
    """
    if not re.search(r"\bwmic\b", text, re.IGNORECASE):
        return None
    if re.search(r"^\s*wmic\s*$", text, re.IGNORECASE | re.MULTILINE):
        return "interactive wmic prompt"
    if re.search(
        r"\bwmic\b[^\n]*\b(?:delete|call|create)\b",
        text,
        re.IGNORECASE,
    ):
        return "mutating wmic"
    return None


def _goto_loop_unsafe(text: str, _case_dir: Path) -> str | None:
    """Skip fixtures that jump backward to a loop label."""
    if re.search(r":\s*(loop|retry)\b", text, re.IGNORECASE) and re.search(
        r"goto\s+(loop|retry)", text, re.IGNORECASE
    ):
        return "backward goto loop"
    lowered = text.lower()
    if ":retry_loop" in lowered and "goto retry_loop" in lowered:
        return "infinite retry loop"
    return None


_UNSAFE_CHECKS: tuple[Callable[[str, Path], str | None], ...] = (
    _regex_reason(r"\bstart\b", "start command may spawn child processes/windows"),
    _regex_reason(r"%~f0|%0\b", "self-referential script path"),
    _regex_reason(r"\bchoice\b", "interactive choice"),
    _regex_reason(r"\bpause\b", "interactive pause"),
    _ping_unsafe,
    _regex_reason(r"\brobocopy\b", "robocopy may perform long file copy operations"),
    _timeout_unsafe,
    _call_unsafe_reason,
    _regex_reason(r"\bpowershell\b", "powershell"),
    _regex_reason(r"\bcmd\s+/c\b", "nested cmd"),
    _net_unsafe,
    _regex_reason(r"\btaskkill\b", "taskkill"),
    _del_unsafe,
    _regex_reason(r"\brmdir\b", "rmdir"),
    _reg_unsafe,
    _wmic_unsafe,
    _regex_reason(r"\bshutdown\b", "shutdown"),
    _goto_loop_unsafe,
)


def _content_unsafe_reason(text: str, case_dir: Path) -> str | None:
    """Return a reason when fixture content must not be executed."""
    for check in _UNSAFE_CHECKS:
        reason = check(text, case_dir)
        if reason:
            return reason
    return None


def _skip_reason(
    input_path: Path, case_id: str, skip_ids: dict[str, str]
) -> str | None:
    oracle_mode, _ = _expect_oracle_settings(input_path.parent)
    if oracle_mode == "skip":
        return "expect.json oracle=skip"

    if oracle_mode == "run":
        return None

    if case_id in skip_ids:
        return skip_ids[case_id]

    text = input_path.read_text(encoding="utf-8", errors="replace")
    unsafe = _content_unsafe_reason(text, input_path.parent)
    if unsafe:
        return unsafe

    return None


def _case_timeout_s(input_path: Path, default_timeout_s: float) -> float:
    _, override = _expect_oracle_settings(input_path.parent)
    if override is not None:
        return override
    return default_timeout_s


def _hidden_window_args() -> tuple[int, object]:
    """Return creation flags and startup info that hide the cmd.exe console.

    ``platform.system`` is used instead of ``sys.platform`` so mypy still
    type-checks the Windows branch on Linux, where ``STARTUPINFO`` is absent.
    """
    if platform.system() != "Windows":
        return 0, None
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if isinstance(create_no_window, int) and create_no_window:
        return create_no_window, None
    startup_type = getattr(subprocess, "STARTUPINFO", None)
    if not callable(startup_type):
        return 0, None
    startupinfo = startup_type()
    show_flag = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    hide_flag = getattr(subprocess, "SW_HIDE", 0)
    current_flags = getattr(startupinfo, "dwFlags", 0)
    if isinstance(show_flag, int) and isinstance(current_flags, int):
        startupinfo.dwFlags = current_flags | show_flag
    if isinstance(hide_flag, int):
        startupinfo.wShowWindow = hide_flag
    return 0, startupinfo


def _kill_process_tree(pid: int) -> None:
    creationflags, startupinfo = _hidden_window_args()
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )


def _run_case(input_path: Path, timeout_s: float) -> int | Literal["TIMEOUT"]:
    """Run one fixture with cmd.exe and return its exit code or TIMEOUT."""
    creationflags, startupinfo = _hidden_window_args()
    with subprocess.Popen(
        ["cmd", "/c", input_path.name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(input_path.parent),
        creationflags=creationflags,
        startupinfo=startupinfo,
    ) as proc:
        try:
            return proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            proc.kill()
            return "TIMEOUT"


def classify_corpus_cases() -> tuple[list[Path], list[tuple[str, str]]]:
    """Return runnable inputs and skipped (case_id, reason) pairs without cmd.exe."""
    skip_ids = _load_skip_ids()
    runnable: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for input_path in _corpus_inputs():
        case_id = "/".join(input_path.parent.relative_to(_CORPUS).parts)
        reason = _skip_reason(input_path, case_id, skip_ids)
        if reason:
            skipped.append((case_id, reason))
            continue
        runnable.append(input_path)
    return runnable, skipped


def main() -> None:
    """Classify corpus fixtures and execute the ones that are safe to run."""
    parser = argparse.ArgumentParser(description="cmd.exe oracle for corpus fixtures")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max runnable cases (0 = all safe cases)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT_S,
        help=f"Per-case timeout in seconds (default {_DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List runnable and skipped cases without executing cmd.exe",
    )
    args = parser.parse_args()
    if platform.system() != "Windows":
        print("cmd.exe oracle is Windows-only; skipping")
        return

    runnable, skipped = classify_corpus_cases()

    if args.limit:
        runnable = runnable[: args.limit]

    print(
        f"cmd_oracle: {len(runnable)} runnable, {len(skipped)} skipped "
        f"(timeout={args.timeout}s)",
        flush=True,
    )

    if args.dry_run:
        for case_id, reason in skipped:
            print(f"SKIP {case_id} ({reason})", flush=True)
        for input_path in runnable:
            case_id = "/".join(input_path.parent.relative_to(_CORPUS).parts)
            print(f"RUN {case_id}", flush=True)
        return

    failures = 0
    for input_path in runnable:
        case_id = "/".join(input_path.parent.relative_to(_CORPUS).parts)
        timeout_s = _case_timeout_s(input_path, args.timeout)
        code = _run_case(input_path, timeout_s)
        if code == "TIMEOUT":
            failures += 1
            print(f"FAIL {case_id} exit=TIMEOUT", flush=True)
            continue
        print(f"OK {case_id} exit={code}", flush=True)

    print(f"cmd_oracle: skipped {len(skipped)} unsafe/static-only cases", flush=True)
    if failures:
        raise SystemExit(f"{failures} cmd.exe oracle failures")


if __name__ == "__main__":
    main()
