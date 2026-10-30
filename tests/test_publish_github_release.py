"""Tests for scripts/publish_github_release.py."""

import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
from typing import Any
import zipfile

import pytest
from pytest_mock import MockerFixture

from scripts.build_exe import OUTPUT_DIR, run_nuitka
from scripts.package_executable import archive_name, binary_name, package_executable
from scripts.publish_github_release import (
    main,
    publish_github_release,
    release_archive_names,
    release_tag,
)
from scripts.test_exe_smoke import (
    assert_binary_architecture,
    elf_machine,
    macho_cpu_type,
    pe_machine,
)

_SHA = "a" * 40
_VERSION = "1.2.3"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "CI.yml"


def _completed(
    code: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Return a finished ``gh`` process."""
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=code,
        stdout=stdout,
        stderr=stderr,
    )


def _prepare(tmp_path: Path, version: str = _VERSION) -> tuple[Path, Path]:
    """Create notes and every required release archive under ``tmp_path``."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    notes = tmp_path / "release-notes.md"
    notes.write_text("notes\n", encoding="utf-8")
    for name in release_archive_names(version):
        (build_dir / name).write_bytes(b"zip")
    return notes, build_dir


def _uploaded_assets(build_dir: Path, version: str = _VERSION) -> list[str]:
    """Return the archive and checksum paths passed to ``gh``."""
    names = [str(build_dir / name) for name in release_archive_names(version)]
    names.append(str(build_dir / "SHA256SUMS"))
    return names


def _argv(mock_call: Any) -> list[str]:
    """Return the command list from a ``subprocess.run`` call."""
    command = mock_call.args[0]
    assert isinstance(command, list)
    parts: list[str] = []
    for part in command:
        assert isinstance(part, str)
        parts.append(part)
    return parts


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authenticate the publisher without reading a real token."""
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


class TestPublishGithubRelease:
    """Create and update paths for the GitHub Release publisher."""

    def test_release_tag_rejects_empty_version(self) -> None:
        """An empty version never becomes a tag."""
        with pytest.raises(SystemExit, match="VERSION is empty"):
            release_tag("")

    def test_release_tag_rejects_path_characters(self) -> None:
        """Version text cannot change the asset directory."""
        with pytest.raises(SystemExit, match="unexpected characters"):
            release_tag("1.2.3/../evil")

    def test_missing_notes_skip_gh(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A missing notes file fails before ``gh`` is invoked."""
        notes, build_dir = _prepare(tmp_path)
        notes.unlink()
        run = mocker.patch("scripts.publish_github_release.subprocess.run")
        with pytest.raises(SystemExit, match="Release notes file not found"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        run.assert_not_called()

    def test_missing_asset_skips_gh(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A missing zip fails before ``gh`` is invoked."""
        notes, build_dir = _prepare(tmp_path)
        next(build_dir.glob("*-Windows-arm64.zip")).unlink()
        run = mocker.patch("scripts.publish_github_release.subprocess.run")
        with pytest.raises(SystemExit, match="Release asset not found"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        run.assert_not_called()

    def test_missing_token_skips_gh(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Publishing requires ``GH_TOKEN`` or ``GITHUB_TOKEN``."""
        notes, build_dir = _prepare(tmp_path)
        monkeypatch.delenv("GH_TOKEN")
        run = mocker.patch("scripts.publish_github_release.subprocess.run")
        with pytest.raises(SystemExit, match="GH_TOKEN or GITHUB_TOKEN"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        run.assert_not_called()

    def test_github_token_is_accepted(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``GITHUB_TOKEN`` alone is enough for ``gh``."""
        notes, build_dir = _prepare(tmp_path)
        monkeypatch.delenv("GH_TOKEN")
        monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0, stdout="https://example.invalid/releases/tag/v1.2.3\n"),
            ],
        )
        publish_github_release(_VERSION, notes, _SHA, build_dir)

    def test_create_pins_the_built_commit(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A new release is created at ``GITHUB_SHA`` with both zips."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0, stdout="https://example.invalid/releases/tag/v1.2.3\n"),
            ],
        )
        publish_github_release(_VERSION, notes, _SHA, build_dir)
        view, create = (_argv(call) for call in run.call_args_list)
        assert view == ["gh", "release", "view", "v1.2.3", "--json", "tagName"]
        assert create == [
            "gh",
            "release",
            "create",
            "v1.2.3",
            *_uploaded_assets(build_dir),
            "--title",
            "v1.2.3",
            "--notes-file",
            str(notes),
            "--target",
            _SHA,
        ]
        assert run.call_args_list[1].kwargs["timeout"] > (
            run.call_args_list[0].kwargs["timeout"]
        )

    def test_update_replaces_same_named_assets(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """An existing release is edited and uploaded with ``--clobber``."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(0, stdout='{"tagName":"v1.2.3"}\n'),
                _completed(0, stdout=f"{_SHA}\n"),
                _completed(0),
                _completed(0),
            ],
        )
        publish_github_release(_VERSION, notes, _SHA, build_dir)
        view, resolve, edit, upload = (_argv(call) for call in run.call_args_list)
        assert view[1:4] == ["release", "view", "v1.2.3"]
        assert resolve == [
            "gh",
            "api",
            "repos/{owner}/{repo}/commits/v1.2.3",
            "--jq",
            ".sha",
        ]
        assert edit == [
            "gh",
            "release",
            "edit",
            "v1.2.3",
            "--title",
            "v1.2.3",
            "--notes-file",
            str(notes),
        ]
        assert upload == [
            "gh",
            "release",
            "upload",
            "v1.2.3",
            *_uploaded_assets(build_dir),
            "--clobber",
        ]
        assert "--target" not in edit
        assert "--target" not in upload

    def test_edit_failure_skips_upload(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A failed edit does not delete existing assets via ``--clobber``."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(0, stdout='{"tagName":"v1.2.3"}\n'),
                _completed(0, stdout=f"{_SHA}\n"),
                _completed(1, stderr="HTTP 422: Validation Failed\n"),
            ],
        )
        with pytest.raises(SystemExit, match="Updating release v1.2.3 failed"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        assert run.call_count == 3

    def test_update_refuses_a_tag_at_another_commit(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Assets built from new code never replace a release tagged elsewhere."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(0, stdout='{"tagName":"v1.2.3"}\n'),
                _completed(0, stdout=f"{'b' * 40}\n"),
            ],
        )
        with pytest.raises(SystemExit, match="Refusing to replace its assets"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        assert run.call_count == 2

    def test_update_requires_commit_sha(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Updating a release needs the built commit to compare against its tag."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            return_value=_completed(0, stdout='{"tagName":"v1.2.3"}\n'),
        )
        with pytest.raises(SystemExit, match="GITHUB_SHA"):
            publish_github_release(_VERSION, notes, "", build_dir)
        assert run.call_count == 1

    def test_update_fails_when_the_tag_cannot_be_resolved(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """An API error while resolving the tag stops before any upload."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(0, stdout='{"tagName":"v1.2.3"}\n'),
                _completed(1, stderr="HTTP 404: Not Found\n"),
            ],
        )
        with pytest.raises(SystemExit, match="Resolving the commit of tag v1.2.3"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        assert run.call_count == 2

    def test_lookup_error_does_not_create(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Authentication and API failures are not treated as a missing release."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            return_value=_completed(1, stderr="HTTP 401: Bad credentials\n"),
        )
        with pytest.raises(SystemExit, match="Could not look up release v1.2.3"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        assert run.call_count == 1

    def test_create_requires_commit_sha(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Creating a release refuses an empty or non-commit target."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            return_value=_completed(1, stderr="release not found\n"),
        )
        with pytest.raises(SystemExit, match="GITHUB_SHA"):
            publish_github_release(_VERSION, notes, "", build_dir)
        assert run.call_count == 1

    def test_prerelease_version_uses_versioned_asset_names(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """PEP 440 pre-release labels stay inside the zip filename."""
        version = "1.2.3rc1"
        notes, build_dir = _prepare(tmp_path, version)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0),
            ],
        )
        publish_github_release(version, notes, _SHA, build_dir)
        create = _argv(run.call_args_list[1])
        assert "v1.2.3rc1" in create
        assert str(build_dir / "Blinter-v1.2.3rc1-Windows-x64.zip") in create

    def test_timeout_exits(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A hung ``gh`` process fails the publish step."""
        notes, build_dir = _prepare(tmp_path)
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=120),
        )
        with pytest.raises(SystemExit, match="timed out"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)

    def test_missing_gh_exits(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A missing ``gh`` binary fails before a release is published."""
        notes, build_dir = _prepare(tmp_path)
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=FileNotFoundError(2, "gh"),
        )
        with pytest.raises(SystemExit, match="Could not run gh"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)

    def test_main_reads_the_environment(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The CLI reads version, notes, and the built commit from the environment."""
        notes, _build_dir = _prepare(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("VERSION", _VERSION)
        monkeypatch.setenv("NOTES_FILE", str(notes))
        monkeypatch.setenv("GITHUB_SHA", _SHA)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0),
            ],
        )
        main([])
        create = _argv(run.call_args_list[1])
        assert create[3] == "v1.2.3"
        assert create[-1] == _SHA

    def test_main_help_and_unknown_args(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Help prints usage and any other argument is an error."""
        main(["--help"])
        assert "VERSION" in capsys.readouterr().out
        with pytest.raises(SystemExit, match="2"):
            main(["--version"])

    def test_workflow_calls_the_python_publisher(self) -> None:
        """The release job invokes the script instead of an inline shell step."""
        workflow = _WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("  create-release:", maxsplit=1)[1].split(
            "  publish-pypi:",
            maxsplit=1,
        )[0]
        assert "python scripts/publish_github_release.py" in job
        assert "GH_TOKEN:" in job
        assert "VERSION:" in job
        assert "NOTES_FILE:" in job
        assert "ncipollo" not in workflow
        assert "set -euo pipefail" not in job

    def test_checksum_lists_every_archive(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """SHA256SUMS covers the archives and is itself uploaded."""
        notes, build_dir = _prepare(tmp_path)
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0),
            ],
        )
        publish_github_release(_VERSION, notes, _SHA, build_dir)
        checksum = (build_dir / "SHA256SUMS").read_text(encoding="utf-8")
        digest = hashlib.sha256(b"zip").hexdigest()
        for name in release_archive_names(_VERSION):
            assert f"{digest}  {name}\n" in checksum
        assert "SHA256SUMS" not in checksum


def test_archive_names_match_the_publisher() -> None:
    """Package filenames are the archives the publisher requires."""
    expected = set(release_archive_names("1.2.3"))
    produced = {
        archive_name("1.2.3", "Windows", "x64"),
        archive_name("1.2.3", "Windows", "arm64"),
        archive_name("1.2.3", "Linux", "x64"),
        archive_name("1.2.3", "Linux", "arm64"),
        archive_name("1.2.3", "macOS", "arm64"),
        archive_name("1.2.3", "macOS", "x64"),
    }
    assert produced == expected
    assert binary_name("Windows") == "blinter.exe"
    assert binary_name("Linux") == "blinter"
    assert binary_name("macOS") == "blinter"


def test_linux_tar_keeps_the_executable_bit(tmp_path: Path) -> None:
    """A Linux archive stores blinter as mode 0755 inside the version folder."""
    binary = tmp_path / "dist" / "blinter"
    binary.parent.mkdir()
    binary.write_bytes(b"#!/bin/sh\n")
    archive = package_executable(tmp_path, "Linux", "x64", version="1.2.3")
    assert archive.name == "Blinter-v1.2.3-Linux-x64.tar.gz"
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.getmember("Blinter-v1.2.3-Linux-x64/blinter")
        assert stat_mode(member.mode) == 0o755
        assert tar.extractfile(member) is not None


def test_windows_zip_uses_the_existing_folder_layout(tmp_path: Path) -> None:
    """A Windows zip contains one folder named after the archive."""
    binary = tmp_path / "dist" / "blinter.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"MZ")
    archive = package_executable(tmp_path, "Windows", "arm64", version="1.2.3")
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.namelist() == ["Blinter-v1.2.3-Windows-arm64/blinter.exe"]
        assert zipped.read("Blinter-v1.2.3-Windows-arm64/blinter.exe") == b"MZ"


def test_package_refuses_a_missing_binary(tmp_path: Path) -> None:
    """Packaging fails before writing an archive when the executable is absent."""
    with pytest.raises(SystemExit, match="Executable not found"):
        package_executable(tmp_path, "macOS", "arm64", version="1.2.3")


def _pe_image(machine: int, pe_offset: int = 0x40) -> bytes:
    """Return a minimal PE image whose COFF Machine field is ``machine``."""
    image = bytearray(pe_offset + 6)
    image[:2] = b"MZ"
    image[0x3C:0x40] = pe_offset.to_bytes(4, "little", signed=True)
    image[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    image[pe_offset + 4 : pe_offset + 6] = machine.to_bytes(2, "little")
    return bytes(image)


def test_elf_macho_and_pe_headers() -> None:
    """Architecture checks read ELF e_machine, Mach-O cputype, and PE Machine."""
    elf = bytearray(20)
    elf[:4] = b"\x7fELF"
    elf[5] = 1
    elf[18:20] = (62).to_bytes(2, "little")
    assert elf_machine(bytes(elf)) == 62
    header = struct.pack("<II", 0xFEEDFACF, 0x0100000C)
    assert macho_cpu_type(header) == 0x0100000C
    assert pe_machine(_pe_image(0x8664)) == 0x8664
    assert pe_machine(_pe_image(0xAA64, pe_offset=0x80)) == 0xAA64


def test_pe_machine_rejects_truncated_and_unsigned_headers() -> None:
    """A PE parser rejects truncated images, a bad offset, and a missing signature."""
    with pytest.raises(ValueError, match="truncated"):
        pe_machine(b"MZ" + b"\x00" * 10)
    with pytest.raises(ValueError, match="MZ"):
        pe_machine(b"\x00" * 64)
    image = bytearray(_pe_image(0x8664))
    image[0x3C:0x40] = (-1).to_bytes(4, "little", signed=True)
    with pytest.raises(ValueError, match="offset"):
        pe_machine(bytes(image))
    short = bytearray(70)
    short[:2] = b"MZ"
    short[0x3C:0x40] = (80).to_bytes(4, "little")
    with pytest.raises(ValueError, match="truncated"):
        pe_machine(bytes(short))
    missing = bytearray(_pe_image(0x8664))
    missing[0x40:0x44] = b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="signature"):
        pe_machine(bytes(missing))


def test_assert_binary_architecture_reads_pe_machine(tmp_path: Path) -> None:
    """A Windows executable is accepted only when its Machine field matches."""
    path = tmp_path / "blinter.exe"
    path.write_bytes(_pe_image(0x8664))
    assert_binary_architecture(path, "x64")
    with pytest.raises(AssertionError, match="8664"):
        assert_binary_architecture(path, "arm64")


def test_run_nuitka_renames_bin_suffix(mocker: MockerFixture, tmp_path: Path) -> None:
    """Nuitka's onefile ``.bin`` suffix is renamed to the requested filename."""
    dist_dir = tmp_path / OUTPUT_DIR
    dist_dir.mkdir()
    (dist_dir / "blinter.bin").write_bytes(b"bin")
    mocker.patch(
        "scripts.build_exe.subprocess.run",
        return_value=mocker.Mock(returncode=0),
    )
    command = [sys.executable, "-m", "nuitka", "--output-filename=blinter"]
    assert run_nuitka(command, tmp_path) == 0
    assert (dist_dir / "blinter").read_bytes() == b"bin"
    assert not (dist_dir / "blinter.bin").exists()


def stat_mode(mode: int) -> int:
    """Return the permission bits stored on a tar member."""
    return mode & 0o777
