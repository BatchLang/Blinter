#!/usr/bin/env python3
"""Smoke-test a Nuitka onefile blinter binary on Windows, Linux, and macOS."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile
import tomllib
from typing import Literal

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARCH_ENV = "BLINTER_EXPECTED_ARCH"
_PROCESS_TIMEOUT_SECONDS = 180
_ELF_MAGIC = b"\x7fELF"
_ELF_MACHINE_X64 = 62
_ELF_MACHINE_ARM64 = 183
_PE_MACHINE_X64 = 0x8664
_PE_MACHINE_ARM64 = 0xAA64
_MH_MAGIC_64 = 0xFEEDFACF
_MH_CIGAM_64 = 0xCFFAEDFE
_CPU_TYPE_X86_64 = 0x01000007
_CPU_TYPE_ARM64 = 0x0100000C
_ELF_BY_ARCH = {"x64": _ELF_MACHINE_X64, "arm64": _ELF_MACHINE_ARM64}
_MACHO_BY_ARCH = {"x64": _CPU_TYPE_X86_64, "arm64": _CPU_TYPE_ARM64}
_PE_BY_ARCH = {"x64": _PE_MACHINE_X64, "arm64": _PE_MACHINE_ARM64}
_RULE_CODE = re.compile(r"E[0-9]{3}|W[0-9]{3}|SEC[0-9]{3}|P[0-9]{3}|S[0-9]{3}")
_CRASH_MARKERS = (
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "ImportError",
)
_JSON_KEYS = ("blinter_version", "target", "issues", "summary")
_USAGE = (
    "usage: test_exe_smoke.py\n"
    "BLINTER_EXPECTED_ARCH=x64|arm64 checks the ELF or Mach-O header when set."
)


def _configure_logging() -> None:
    """Send smoke-test progress to stderr without duplicating handlers."""
    if logging.getLogger().handlers:
        logger.setLevel(logging.INFO)
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def read_project_version(pyproject_path: Path) -> str:
    """Return ``[project].version`` from pyproject.toml."""
    logger.info("Reading project version from %s", pyproject_path)
    try:
        with pyproject_path.open("rb") as handle:
            data_object: object = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"Could not read project version: {exc}") from exc
    if not isinstance(data_object, dict):
        raise SystemExit("Missing [project] table in pyproject.toml")
    project_object: object = data_object.get("project")
    if not isinstance(project_object, dict):
        raise SystemExit("Missing [project] table in pyproject.toml")
    version_object: object = project_object.get("version")
    if not isinstance(version_object, str) or not version_object:
        raise SystemExit("Missing project.version in pyproject.toml")
    logger.info("Resolved project version %s", version_object)
    return version_object


def pe_machine(data: bytes) -> int:
    """Return the COFF Machine field from a PE executable."""
    if len(data) < 64:
        raise ValueError("PE header is truncated")
    if data[:2] != b"MZ":
        raise ValueError("Missing MZ signature")
    pe_offset = int.from_bytes(data[0x3C:0x40], "little", signed=True)
    if pe_offset < 0:
        raise ValueError("Invalid PE offset")
    signature_end = pe_offset + 6
    if signature_end > len(data):
        raise ValueError("PE signature is truncated")
    if data[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("Missing PE signature")
    return int.from_bytes(data[pe_offset + 4 : pe_offset + 6], "little")


def elf_machine(header: bytes) -> int:
    """Return the ELF ``e_machine`` field from the start of a binary."""
    if len(header) < 20 or header[:4] != _ELF_MAGIC:
        raise ValueError("not an ELF binary")
    encoding = header[5]
    byte_order: Literal["little", "big"]
    if encoding == 1:
        byte_order = "little"
    elif encoding == 2:
        byte_order = "big"
    else:
        raise ValueError(f"unknown ELF data encoding {encoding}")
    return int.from_bytes(header[18:20], byte_order)


def macho_cpu_type(header: bytes) -> int:
    """Return the Mach-O 64-bit ``cputype`` field."""
    if len(header) < 8:
        raise ValueError("Mach-O header is truncated")
    magic = struct.unpack("<I", header[:4])[0]
    byte_order: Literal["<", ">"]
    if magic == _MH_MAGIC_64:
        byte_order = "<"
    elif magic == _MH_CIGAM_64:
        byte_order = ">"
    else:
        raise ValueError(f"not a Mach-O 64-bit binary (magic {magic:#x})")
    cpu_type: int = struct.unpack(byte_order + "I", header[4:8])[0]
    return cpu_type


def _machine_for_binary(path: Path, arch: str) -> tuple[int, int]:
    """Return the actual and expected machine id for a PE, ELF, or Mach-O file."""
    header = path.read_bytes()[:64]
    if header.startswith(b"MZ"):
        return pe_machine(path.read_bytes()), _PE_BY_ARCH[arch]
    if header.startswith(_ELF_MAGIC):
        return elf_machine(header), _ELF_BY_ARCH[arch]
    if len(header) >= 4 and struct.unpack("<I", header[:4])[0] in {
        _MH_MAGIC_64,
        _MH_CIGAM_64,
    }:
        return macho_cpu_type(header), _MACHO_BY_ARCH[arch]
    raise AssertionError(f"unsupported executable format: {path}")


def assert_binary_architecture(path: Path, arch: str) -> None:
    """Raise AssertionError when ``path`` is not the expected PE, ELF, or Mach-O arch."""
    if arch not in _ELF_BY_ARCH:
        raise AssertionError(f"Expected arch must be x64 or arm64. Got: {arch}")
    logger.info("Checking architecture of %s", path)
    actual, expected = _machine_for_binary(path, arch)
    if actual != expected:
        raise AssertionError(
            f"expected machine {expected:#x} for {arch}, got {actual:#x}"
        )
    logger.info("Architecture %s matches machine %#x", arch, actual)


class _ProcessResult:
    """Captured output from one blinter invocation."""

    def __init__(self, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def output(self) -> str:
        """Return stdout and stderr joined, matching the PowerShell smoke test."""
        return self.stdout + self.stderr

    def has_runtime_crash(self) -> bool:
        """Return whether the output shows a Python import or traceback failure."""
        return any(marker in self.output for marker in _CRASH_MARKERS)


def run_blinter(binary: Path, args: list[str], cwd: Path) -> _ProcessResult:
    """Run ``binary`` and return its exit code and captured output."""
    command = [str(binary), *args]
    logger.info("Running %s in %s", command, cwd)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"timed out after {_PROCESS_TIMEOUT_SECONDS}s: {command}"
        ) from exc
    except OSError as exc:
        raise AssertionError(f"failed to start {binary}: {exc}") from exc
    logger.info("%s exited %s", binary.name, completed.returncode)
    return _ProcessResult(completed.returncode, completed.stdout, completed.stderr)


def assert_no_crash(result: _ProcessResult) -> None:
    """Reject output that shows a Python import or traceback failure."""
    if result.has_runtime_crash():
        raise AssertionError(f"runtime crash detected: {result.output}")


def assert_lint_exit(exit_code: int) -> None:
    """Accept the success and findings exit codes used by the CLI."""
    if exit_code not in (0, 1):
        raise AssertionError(f"unexpected exit code {exit_code}")


def parse_report(stdout: str) -> dict[str, object]:
    """Return a JSON report object and require the stable top-level keys."""
    try:
        payload: object = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"stdout is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AssertionError("JSON report is not an object")
    for key in _JSON_KEYS:
        if key not in payload:
            raise AssertionError(f"missing json key {key}")
    report: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(key, str):
            report[key] = value
    return report


def issue_codes(report: dict[str, object]) -> list[str]:
    """Return rule codes from a parsed JSON report."""
    issues = report.get("issues")
    if not isinstance(issues, list):
        raise AssertionError("JSON report is missing issues")
    codes: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise AssertionError("JSON issue is not an object")
        code = issue.get("code")
        if not isinstance(code, str):
            raise AssertionError("JSON issue is missing code")
        codes.append(code)
    return codes


def _write_text(path: Path, text: str) -> None:
    """Write a UTF-8 fixture without a byte-order mark."""
    path.write_text(text, encoding="utf-8", newline="")


def create_fixture(root: Path) -> None:
    """Create the batch fixtures shared with the Windows executable smoke test."""
    logger.info("Creating smoke fixtures in %s", root)
    _write_text(root / "sample.bat", "@echo off\r\necho hello\r\n")
    _write_text(root / "sample.cmd", "@echo off\r\necho cmd test\r\n")
    _write_text(
        root / "good_script.bat",
        "@echo off\r\nREM clean script\r\necho Done\r\nexit /b 0\r\n",
    )
    _write_text(
        root / "bad_script.bat",
        "echo off\r\ngoto nonexistent\r\nset UNQUOTED=value\r\n",
    )
    _write_text(root / "utf8.bat", "@echo off\r\necho cafe resume\r\n")
    (root / "utf16.bat").write_bytes(
        b"\xff\xfe" + "@echo off\r\necho utf16\r\n".encode("utf-16-le")
    )
    _write_text(root / "readme.txt", "not a batch file")
    _write_text(root / "blinter.ini", "[rules]\r\ndisabled_rules = S001\r\n")
    (root / "subdir").mkdir()
    deep = root / "nested" / "deep"
    deep.mkdir(parents=True)
    _write_text(root / "subdir" / "sub_script.bat", "@echo off\r\necho sub\r\n")
    _write_text(deep / "deep_script.bat", "@echo off\r\necho deep\r\n")
    _write_text(root / "caller.bat", "@echo off\r\ncall subdir\\sub_script.bat\r\n")
    _write_text(root / "chain_a.bat", "@echo off\r\ncall chain_b.bat\r\n")
    _write_text(root / "chain_b.bat", "@echo off\r\nset VAR=1\r\necho %VAR%\r\n")


class ExeSmoke:
    """Functional checks for one compiled blinter binary."""

    def __init__(
        self,
        exe: Path,
        python: Path,
        fixture: Path,
        version: str,
        arch: str,
    ) -> None:
        self.exe = exe
        self.python = python
        self.fixture = fixture
        self.version = version
        self.arch = arch

    def check_architecture(self) -> None:
        """The binary header must match the runner architecture."""
        if not self.arch:
            logger.info("BLINTER_EXPECTED_ARCH is unset; skipping architecture check")
            return
        assert_binary_architecture(self.exe, self.arch)

    def check_version(self) -> None:
        """``--version`` must print the project version and exit 0."""
        result = run_blinter(self.exe, ["--version"], self.fixture)
        if result.exit_code != 0:
            raise AssertionError(f"exit {result.exit_code}: {result.output}")
        if self.version not in result.output:
            raise AssertionError(
                f"expected version {self.version} in output, got: {result.output}"
            )
        assert_no_crash(result)

    def check_help(self) -> None:
        """``--help`` must print usage text."""
        result = run_blinter(self.exe, ["--help"], self.fixture)
        if result.exit_code != 0:
            raise AssertionError(f"exit {result.exit_code}: {result.output}")
        if "Usage:" not in result.output:
            raise AssertionError("expected usage text")

    def check_no_args_help(self) -> None:
        """Invoking the binary with no arguments must print usage text."""
        result = run_blinter(self.exe, [], self.fixture)
        if result.exit_code != 0:
            raise AssertionError(f"exit {result.exit_code}: {result.output}")
        if "Usage:" not in result.output:
            raise AssertionError("expected help output")

    def check_sample_summary(self) -> None:
        """A small batch file must lint without a runtime crash."""
        result = run_blinter(
            self.exe, ["sample.bat", "--summary", "--no-config"], self.fixture
        )
        assert_lint_exit(result.exit_code)
        assert_no_crash(result)

    def check_missing_file(self) -> None:
        """A missing target must be a non-zero exit."""
        result = run_blinter(self.exe, ["missing.bat", "--no-config"], self.fixture)
        if result.exit_code == 0:
            raise AssertionError("expected non-zero exit for missing file")

    def check_sample_cmd(self) -> None:
        """``.cmd`` files must lint without a runtime crash."""
        result = run_blinter(self.exe, ["sample.cmd", "--no-config"], self.fixture)
        assert_lint_exit(result.exit_code)
        assert_no_crash(result)

    def check_bad_script_rule_codes(self) -> None:
        """A broken script must report at least one rule code."""
        result = run_blinter(self.exe, ["bad_script.bat", "--no-config"], self.fixture)
        assert_lint_exit(result.exit_code)
        if _RULE_CODE.search(result.output) is None:
            raise AssertionError("expected rule codes in output")

    def check_non_batch_rejected(self) -> None:
        """A text file must be rejected as a batch target."""
        result = run_blinter(self.exe, ["readme.txt", "--no-config"], self.fixture)
        if result.exit_code == 0:
            raise AssertionError("expected non-zero exit")
        folded = result.output.casefold()
        if "not a batch" not in folded and "error" not in folded:
            raise AssertionError("expected batch file error message")

    def check_json_stdout_schema(self) -> None:
        """JSON stdout must include the stable report keys."""
        result = run_blinter(
            self.exe,
            ["sample.bat", "--format", "json", "--no-config"],
            self.fixture,
        )
        assert_lint_exit(result.exit_code)
        parse_report(result.stdout)

    def check_json_output_file(self) -> None:
        """``--output`` must write the report and leave stdout empty."""
        report_path = self.fixture / "report.json"
        if report_path.exists():
            report_path.unlink()
        result = run_blinter(
            self.exe,
            [
                "sample.bat",
                "--format",
                "json",
                "--output",
                "report.json",
                "--no-config",
            ],
            self.fixture,
        )
        assert_lint_exit(result.exit_code)
        if result.stdout.strip():
            raise AssertionError("expected empty stdout when writing json to file")
        if not report_path.is_file():
            raise AssertionError("report.json was not created")
        parse_report(report_path.read_text(encoding="utf-8"))

    def check_utf8(self) -> None:
        """A UTF-8 batch file must lint without a runtime crash."""
        result = run_blinter(
            self.exe, ["utf8.bat", "--summary", "--no-config"], self.fixture
        )
        assert_lint_exit(result.exit_code)
        assert_no_crash(result)

    def check_utf16(self) -> None:
        """A UTF-16 LE batch file must lint without a runtime crash."""
        result = run_blinter(
            self.exe, ["utf16.bat", "--summary", "--no-config"], self.fixture
        )
        assert_lint_exit(result.exit_code)
        assert_no_crash(result)

    def check_follow_calls(self) -> None:
        """``--follow-calls`` must lint a caller without a runtime crash."""
        result = run_blinter(
            self.exe,
            ["caller.bat", "--follow-calls", "--summary", "--no-config"],
            self.fixture,
        )
        assert_lint_exit(result.exit_code)
        assert_no_crash(result)

    def check_config_disables_rule(self) -> None:
        """A disabled rule must not appear in the summary."""
        result = run_blinter(
            self.exe,
            ["bad_script.bat", "--config", "blinter.ini", "--summary"],
            self.fixture,
        )
        assert_lint_exit(result.exit_code)
        if re.search(r"\bS001\b", result.output):
            raise AssertionError("disabled rule S001 was reported")

    def check_create_config(self) -> None:
        """``--create-config`` must write blinter.ini in the working directory."""
        config_dir = self.fixture / "create-config"
        config_dir.mkdir()
        result = run_blinter(self.exe, ["--create-config"], config_dir)
        if result.exit_code != 0:
            raise AssertionError(f"exit {result.exit_code}: {result.output}")
        if not (config_dir / "blinter.ini").is_file():
            raise AssertionError("blinter.ini was not created")

    def check_directory_no_recursive(self) -> None:
        """``--no-recursive`` must ignore batch files in nested directories."""
        result = run_blinter(
            self.exe,
            [".", "--no-recursive", "--summary", "--no-config"],
            self.fixture,
        )
        assert_lint_exit(result.exit_code)
        if "deep_script" in result.output:
            raise AssertionError("deep_script should be excluded by --no-recursive")

    def _lint_repo_script(self, relative_path: str) -> None:
        """Lint one repository script with the executable and the repo config."""
        result = run_blinter(
            self.exe,
            [relative_path, "--summary", "--config", "scripts/blinter.ini"],
            _REPO_ROOT,
        )
        assert_lint_exit(result.exit_code)
        assert_no_crash(result)

    def check_install_script(self) -> None:
        """The Windows installer script must lint without a runtime crash."""
        self._lint_repo_script("scripts/install_blinter.cmd")

    def check_uninstall_script(self) -> None:
        """The Windows uninstaller script must lint without a runtime crash."""
        self._lint_repo_script("scripts/uninstall_blinter.cmd")

    def _parity(
        self,
        args: list[str],
        *,
        compare_codes: bool,
    ) -> None:
        """Compare the executable with ``python -m blinter`` on one fixture."""
        python_result = run_blinter(self.python, ["-m", "blinter", *args], self.fixture)
        exe_result = run_blinter(self.exe, args, self.fixture)
        if python_result.exit_code != exe_result.exit_code:
            raise AssertionError(
                "exit mismatch "
                f"py={python_result.exit_code} exe={exe_result.exit_code}"
            )
        python_report = parse_report(python_result.stdout)
        exe_report = parse_report(exe_result.stdout)
        python_codes = issue_codes(python_report)
        exe_codes = issue_codes(exe_report)
        if compare_codes and python_codes != exe_codes:
            raise AssertionError(f"rule codes differ py={python_codes} exe={exe_codes}")
        if len(python_codes) != len(exe_codes):
            raise AssertionError(
                f"issue count mismatch py={len(python_codes)} exe={len(exe_codes)}"
            )

    def check_parity_good_script(self) -> None:
        """A clean script must yield the same exit code and issue count."""
        self._parity(
            ["good_script.bat", "--format", "json", "--no-config"], compare_codes=False
        )

    def check_parity_bad_script(self) -> None:
        """A broken script must yield the same rule codes."""
        self._parity(
            ["bad_script.bat", "--format", "json", "--no-config"],
            compare_codes=True,
        )

    def check_parity_follow_calls(self) -> None:
        """Followed calls must yield the same exit code and issue count."""
        self._parity(
            ["chain_a.bat", "--follow-calls", "--format", "json", "--no-config"],
            compare_codes=False,
        )

    def check_parity_utf16(self) -> None:
        """UTF-16 input must yield the same exit code."""
        python_result = run_blinter(
            self.python,
            ["-m", "blinter", "utf16.bat", "--format", "json", "--no-config"],
            self.fixture,
        )
        exe_result = run_blinter(
            self.exe, ["utf16.bat", "--format", "json", "--no-config"], self.fixture
        )
        if python_result.exit_code != exe_result.exit_code:
            raise AssertionError(
                "exit mismatch "
                f"py={python_result.exit_code} exe={exe_result.exit_code}"
            )

    def check_parity_sample_cmd(self) -> None:
        """A ``.cmd`` file must yield the same exit code and issue count."""
        self._parity(
            ["sample.cmd", "--format", "json", "--no-config"], compare_codes=False
        )

    def cases(self) -> list[tuple[str, Callable[[], None]]]:
        """Return the ordered smoke cases."""
        return [
            ("exe 00 architecture", self.check_architecture),
            ("exe 01 version", self.check_version),
            ("exe 02 help", self.check_help),
            ("exe 03 no args help", self.check_no_args_help),
            ("exe 04 sample summary", self.check_sample_summary),
            ("exe 05 missing file", self.check_missing_file),
            ("exe 06 sample cmd", self.check_sample_cmd),
            ("exe 07 bad script rule codes", self.check_bad_script_rule_codes),
            ("exe 08 non-batch rejected", self.check_non_batch_rejected),
            ("exe 09 json stdout schema", self.check_json_stdout_schema),
            ("exe 10 json output file", self.check_json_output_file),
            ("exe 11 utf8 non-ascii", self.check_utf8),
            ("exe 12 utf16 le", self.check_utf16),
            ("exe 13 follow calls", self.check_follow_calls),
            ("exe 14 config disables rule", self.check_config_disables_rule),
            ("exe 15 create config", self.check_create_config),
            ("exe 16 directory no recursive", self.check_directory_no_recursive),
            ("exe 17 install script", self.check_install_script),
            ("exe 18 uninstall script", self.check_uninstall_script),
            ("parity 01 good script", self.check_parity_good_script),
            ("parity 02 bad script codes", self.check_parity_bad_script),
            ("parity 03 follow calls chain", self.check_parity_follow_calls),
            ("parity 04 utf16", self.check_parity_utf16),
            ("parity 05 sample cmd", self.check_parity_sample_cmd),
        ]


def run_cases(smoke: ExeSmoke) -> int:
    """Run every case and return 0 when all of them pass."""
    passed = 0
    failures: list[str] = []
    cases = smoke.cases()
    for name, check in cases:
        try:
            check()
        except (AssertionError, OSError, ValueError) as exc:
            failures.append(f"{name} - {exc}")
            print(f"FAIL: {name} - {exc}")
            continue
        passed += 1
        print(f"PASS: {name}")
    print("---")
    print(f"RESULT: {passed} / {len(cases)} passed")
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    return 0


def default_executable(repo_root: Path) -> Path:
    """Return the onefile path for this operating system."""
    name = "blinter.exe" if os.name == "nt" else "blinter"
    return repo_root / "dist" / name


def main(argv: list[str] | None = None) -> int:
    """Smoke-test the executable and compare it with ``python -m blinter``."""
    _configure_logging()
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(_USAGE)
        return 0
    if args:
        print(_USAGE, file=sys.stderr)
        return 2
    exe = default_executable(_REPO_ROOT)
    logger.info("Smoke testing %s", exe)
    if not exe.is_file():
        raise SystemExit(f"Executable not found: {exe}")
    if os.name != "nt":
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    version = read_project_version(_REPO_ROOT / "pyproject.toml")
    arch = os.environ.get(_ARCH_ENV, "")
    logger.info("Expected architecture %r", arch or "<unset>")
    with tempfile.TemporaryDirectory(prefix="blinter-exe-smoke-") as temporary:
        fixture = Path(temporary)
        create_fixture(fixture)
        smoke = ExeSmoke(exe, Path(sys.executable), fixture, version, arch)
        return run_cases(smoke)


if __name__ == "__main__":
    sys.exit(main())
