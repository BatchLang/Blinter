"""Byte parity between installer echo blocks and the PowerShell fixtures."""

from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
_FIXTURES = _SCRIPTS / "installer_ps"
_SYNTAX_CHECK = _SCRIPTS / "verify_ps" / "Test-PowerShellSyntax.ps1"
_ECHO_SPECIALS = set("^)|><&")
_NASTY_PATH = r"C:\Program Files\O'Brien (x86)\bin"

# Each write_* label maps to exactly one fixture. Both batch files carry the same line-ending\n# bootstrap, so that fixture is used twice.
_LABEL_FIXTURES: dict[tuple[str, str], str] = {
    ("install_blinter.cmd", "write_get_release_script"): "Get-LatestBlinterRelease.ps1",
    ("install_blinter.cmd", "write_file_size_script"): "Get-DownloadedFileSize.ps1",
    ("install_blinter.cmd", "write_hash_verify_script"): "Test-BlinterArchiveHash.ps1",
    ("install_blinter.cmd", "write_expand_script"): "Expand-BlinterArchive.ps1",
    ("install_blinter.cmd", "write_update_path_script"): "Update-BlinterUserPath.ps1",
    ("uninstall_blinter.cmd", "write_stop_blinter_script"): "Stop-InstalledBlinter.ps1",
    ("uninstall_blinter.cmd", "write_remove_path_script"): "Remove-BlinterUserPath.ps1",
    ("install_blinter.cmd", "write_crlf_script"): "Write-CrlfScriptCopy.ps1",
    ("uninstall_blinter.cmd", "write_crlf_script"): "Write-CrlfScriptCopy.ps1",
}

# The bootstrap runs before cmd.exe can find labels, so it has no exit /b 0 subroutine to call.
_NOT_CALLABLE_LABELS = frozenset({"write_crlf_script"})


def _encode_batch_echo(line: str) -> str:
    """Caret-escape cmd metacharacters that sit outside double quotes."""
    encoded: list[str] = []
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
            encoded.append(char)
            continue
        if not in_quotes and char in _ECHO_SPECIALS:
            encoded.append("^")
        encoded.append(char)
    return "".join(encoded)


def _decode_batch_echo(line: str) -> str:
    """Undo caret escapes, leaving carets inside double quotes untouched."""
    decoded: list[str] = []
    in_quotes = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            in_quotes = not in_quotes
            decoded.append(char)
            index += 1
            continue
        escaped = (not in_quotes) and char == "^" and (index + 1) < len(line)
        if escaped:
            decoded.append(line[index + 1])
            index += 2
            continue
        decoded.append(char)
        index += 1
    return "".join(decoded)


def _cmd_lines(cmd_name: str) -> list[str]:
    """Return the batch file split on universal newlines."""
    return (_SCRIPTS / cmd_name).read_text(encoding="utf-8").splitlines()


def _write_labels(cmd_name: str) -> list[str]:
    """Return write_* labels in source order."""
    labels: list[str] = []
    for line in _cmd_lines(cmd_name):
        stripped = line.strip()
        if stripped.startswith(":write_") and " " not in stripped:
            labels.append(stripped[1:])
    return labels


def _echo_payload(cmd_name: str, label: str) -> list[str]:
    """Return the raw text after ``echo `` for one parenthesized block."""
    lines = _cmd_lines(cmd_name)
    start = -1
    for index, line in enumerate(lines):
        if line.strip() == f":{label}":
            start = index
            break
    if start < 0:
        raise AssertionError(f"Missing :{label} in {cmd_name}")
    if start + 1 >= len(lines) or lines[start + 1].strip() != "(":
        raise AssertionError(f"Expected '(' after :{label}")

    payload: list[str] = []
    for line in lines[start + 2 :]:
        stripped = line.strip()
        if stripped == ")" or stripped.startswith(") >"):
            return payload
        if stripped == "echo":
            payload.append("")
            continue
        if stripped.lower().startswith("echo "):
            payload.append(stripped[5:])
            continue
        raise AssertionError(f"Unexpected line in :{label}: {stripped}")
    raise AssertionError(f":{label} block never closed")


def _decoded_script(cmd_name: str, label: str) -> bytes:
    """Decode one echo block to the CRLF bytes cmd would write."""
    decoded_lines = [
        _decode_batch_echo(line) for line in _echo_payload(cmd_name, label)
    ]
    return ("\r\n".join(decoded_lines) + "\r\n").encode("utf-8")


def _output_variable(cmd_name: str, label: str) -> str:
    """Return the variable the echo block redirects into."""
    lines = _cmd_lines(cmd_name)
    for index, line in enumerate(lines):
        if line.strip() != f":{label}":
            continue
        for follower in lines[index + 1 :]:
            stripped = follower.strip()
            if stripped.startswith(") >"):
                start = stripped.find("!")
                end = stripped.rfind("!")
                if start < 0 or end <= start:
                    raise AssertionError(f"No delayed variable in {stripped}")
                return stripped[start + 1 : end]
        break
    raise AssertionError(f"No redirect after :{label}")


def test_write_labels_match_fixtures_both_ways() -> None:
    """Every fixture belongs to a write block, and every write block has one fixture."""
    found: set[tuple[str, str]] = set()
    for cmd_name in ("install_blinter.cmd", "uninstall_blinter.cmd"):
        for label in _write_labels(cmd_name):
            found.add((cmd_name, label))
    assert found == set(_LABEL_FIXTURES)
    fixture_names = {path.name for path in _FIXTURES.glob("*.ps1")}
    assert fixture_names == set(_LABEL_FIXTURES.values())


def test_echo_blocks_match_fixture_crlf_bytes() -> None:
    """Quote-aware decoding of each echo block matches the fixture's CRLF bytes."""
    for (cmd_name, label), fixture_name in _LABEL_FIXTURES.items():
        expected = (_FIXTURES / fixture_name).read_bytes()
        actual = _decoded_script(cmd_name, label)
        assert actual == expected, f"{cmd_name}:{label} drifted from {fixture_name}"


def test_unquoted_metacharacters_are_caret_escaped() -> None:
    """Each fixture caret is ^^ in the batch file, and unquoted metacharacters are escaped."""
    for (cmd_name, label), fixture_name in _LABEL_FIXTURES.items():
        fixture_lines = (
            (_FIXTURES / fixture_name).read_text(encoding="utf-8").splitlines()
        )
        raw_lines = _echo_payload(cmd_name, label)
        assert len(raw_lines) == len(fixture_lines)
        for raw_line, fixture_line in zip(raw_lines, fixture_lines):
            assert raw_line == _encode_batch_echo(fixture_line)


def test_dropping_one_required_caret_breaks_parity() -> None:
    """Removing a caret that protects a metacharacter no longer matches the fixture."""
    raw_lines = _echo_payload("install_blinter.cmd", "write_hash_verify_script")
    fixture_lines = (
        (_FIXTURES / "Test-BlinterArchiveHash.ps1")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    mutated = False
    for raw_line, fixture_line in zip(raw_lines, fixture_lines):
        caret_at = _first_unquoted_caret(raw_line)
        if caret_at is None:
            continue
        changed = raw_line[:caret_at] + raw_line[caret_at + 1 :]
        assert changed != _encode_batch_echo(fixture_line)
        mutated = True
        break
    assert mutated


def _first_unquoted_caret(line: str) -> int | None:
    """Return the index of the first caret that is an escape, if any."""
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
            continue
        if not in_quotes and char == "^" and (index + 1) < len(line):
            return index
    return None


def _subroutine_lines(cmd_name: str, label: str) -> list[str]:
    """Copy one label through its exit /b 0, which is what cmd executes."""
    lines = _cmd_lines(cmd_name)
    start = -1
    for index, line in enumerate(lines):
        if line.strip() == f":{label}":
            start = index
            break
    if start < 0:
        raise AssertionError(f"Missing :{label}")
    collected: list[str] = []
    for line in lines[start:]:
        collected.append(line)
        if line.strip() == "exit /b 0":
            return collected
    raise AssertionError(f":{label} does not end with exit /b 0")


@pytest.mark.skipif(
    sys.platform != "win32", reason="cmd.exe writes the installer scripts"
)
def test_cmd_writes_fixture_bytes_for_nasty_paths() -> None:
    """cmd writes each fixture unchanged when env paths contain a space, apostrophe, and )."""
    for (cmd_name, label), fixture_name in _LABEL_FIXTURES.items():
        if label in _NOT_CALLABLE_LABELS:
            continue
        _assert_cmd_label_matches(cmd_name, label, fixture_name)


def _assert_cmd_label_matches(cmd_name: str, label: str, fixture_name: str) -> None:
    """Run one label and compare the file cmd wrote with the fixture."""
    output_var = _output_variable(cmd_name, label)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        out_dir = root / "O'Brien (x86)"
        out_dir.mkdir()
        out_file = out_dir / fixture_name
        harness = root / "harness.cmd"
        header = [
            "@echo off",
            "setlocal enabledelayedexpansion",
            f'set "BLINTER_BIN={_NASTY_PATH}"',
            f'set "BLINTER_TEMP={_NASTY_PATH}"',
            'set "BLINTER_SHA256=sha256:abc"',
            f'set "{output_var}={out_file}"',
            f"call :{label}",
            "exit /b %errorlevel%",
        ]
        body = header + _subroutine_lines(cmd_name, label)
        harness.write_bytes(("\r\n".join(body) + "\r\n").encode("utf-8"))
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", str(harness)],
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
        written = out_file.read_bytes()
        expected = (_FIXTURES / fixture_name).read_bytes()
        assert written == expected
        assert b"O'Brien" not in written
        _assert_powershell_parses(out_file)


def _assert_powershell_parses(script_path: Path) -> None:
    """The generated file is valid PowerShell even when its path is awkward."""
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SYNTAX_CHECK),
            "-Path",
            str(script_path),
        ],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout.decode("utf-8", "replace")
