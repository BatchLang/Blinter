"""Tests for scripts/install_blinter.sh and scripts/uninstall_blinter.sh.

The scripts run for real under bash. Only the outside world is replaced, see
``tests/unix_installer_support.py``. Every test gets its own HOME, so nothing
touches the real user.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from tests.unix_installer_support import (
    END_MARKER,
    INSTALL,
    LINUX_ARM,
    LINUX_X64,
    MAC_ARM,
    MAC_INTEL,
    MAC_ROSETTA,
    NEWER_TAG,
    RUN_TIMEOUT_SECONDS,
    START_MARKER,
    TAG,
    UNINSTALL,
    ReleaseOptions,
    Sandbox,
    install_stub,
    make_sandbox,
)

pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32", reason="the installers target Linux and macOS"
    ),
    pytest.mark.timeout(120),
]


@pytest.fixture(name="sandbox")
def fixture_sandbox(tmp_path: Path) -> Sandbox:
    """Return a Linux x64 sandbox with a published v1.2.3 release."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "x64")
    return sb


def _block_count(path: Path) -> int:
    """Count the Blinter PATH blocks in a startup file."""
    return path.read_text(encoding="utf-8").splitlines().count(START_MARKER)


def _sourced_blinter(sandbox: Sandbox, shell: str) -> str:
    """Return what ``command -v blinter`` finds after sourcing ~/.profile."""
    completed = subprocess.run(
        [shell, "-c", '. "$HOME/.profile"; command -v blinter'],
        env=sandbox.environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _assert_nothing_installed(sandbox: Sandbox) -> None:
    """The refused or failed run left no install and no startup file changes."""
    assert not sandbox.data_home.exists()
    assert not (sandbox.home / ".profile").exists()


# ---------------------------------------------------------------------------
# Refusals that must happen before anything is downloaded
# ---------------------------------------------------------------------------


_USAGE = "Usage: install_blinter.sh [x64|arm64]"


@pytest.mark.parametrize("args", [("sparc",), ("X64",), ("--force",), ("x64", "arm64")])
def test_install_rejects_an_unknown_architecture(
    sandbox: Sandbox, args: tuple[str, ...]
) -> None:
    """An unrecognized argument prints usage and downloads nothing."""
    result = sandbox.install(*args)
    assert result.returncode == 1
    assert _USAGE in result.output
    assert "nothing was downloaded" in result.output
    assert sandbox.requests() == []
    _assert_nothing_installed(sandbox)


@pytest.mark.parametrize(
    ("host", "os_name", "arch"),
    [
        (LINUX_X64, "Linux", "x64"),
        (LINUX_ARM, "Linux", "arm64"),
        (MAC_INTEL, "macOS", "x64"),
        (MAC_ARM, "macOS", "arm64"),
        (MAC_ROSETTA, "macOS", "arm64"),
    ],
)
def test_install_without_an_argument_uses_the_native_build(
    tmp_path: Path, host: dict[str, str], os_name: str, arch: str
) -> None:
    """With no argument the script picks the build that matches the machine."""
    sb = make_sandbox(tmp_path)
    sb.host = dict(host)
    sb.publish(TAG, os_name, arch)
    result = sb.install()
    assert result.returncode == 0, result.output
    assert "using the native build" in result.output
    assert f"Selected build: {arch}" in result.output
    assert "runs through Rosetta" not in result.output
    assert sb.requests()[-1].endswith(f"Blinter-{TAG}-{os_name}-{arch}.tar.gz")


def test_install_without_an_argument_still_checks_the_host(sandbox: Sandbox) -> None:
    """Auto-detection refuses an unsupported CPU before downloading."""
    sandbox.host = {"STUB_UNAME_S": "Linux", "STUB_UNAME_M": "riscv64"}
    result = sandbox.install()
    assert result.returncode == 1
    assert "Unsupported CPU architecture: riscv64" in result.output
    assert sandbox.requests() == []


def test_an_explicit_argument_overrides_detection(tmp_path: Path) -> None:
    """On Apple Silicon, x64 selects the Rosetta build instead of the native one."""
    sb = make_sandbox(tmp_path)
    sb.host = dict(MAC_ARM)
    sb.publish(TAG, "macOS", "x64")
    result = sb.install("x64")
    assert result.returncode == 0, result.output
    assert "using the native build" not in result.output
    assert "Selected build: x64" in result.output


def test_install_help_exits_cleanly(sandbox: Sandbox) -> None:
    """--help prints usage and succeeds."""
    result = sandbox.install("--help")
    assert result.returncode == 0
    assert _USAGE in result.output
    assert sandbox.requests() == []


def test_install_refuses_root(sandbox: Sandbox) -> None:
    """The installer is for a normal user, like the Windows one."""
    sandbox.extra_env["STUB_UID"] = "0"
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "without root privileges" in result.output
    assert sandbox.requests() == []
    _assert_nothing_installed(sandbox)


def test_install_refuses_unsupported_os(sandbox: Sandbox) -> None:
    """Only Linux and macOS are supported."""
    sandbox.host = {"STUB_UNAME_S": "FreeBSD", "STUB_UNAME_M": "amd64"}
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "Unsupported operating system: FreeBSD" in result.output
    assert sandbox.requests() == []


def test_install_refuses_unsupported_cpu(sandbox: Sandbox) -> None:
    """Only x86_64 and ARM64 CPUs are supported."""
    sandbox.host = {"STUB_UNAME_S": "Linux", "STUB_UNAME_M": "riscv64"}
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "Unsupported CPU architecture: riscv64" in result.output
    assert sandbox.requests() == []


@pytest.mark.parametrize("host", [LINUX_X64, MAC_INTEL])
def test_install_refuses_arm64_on_an_x64_host(
    sandbox: Sandbox, host: dict[str, str]
) -> None:
    """The arm64 build cannot run on an Intel or AMD machine."""
    sandbox.host = dict(host)
    result = sandbox.install("arm64")
    assert result.returncode == 1
    assert "arm64 build cannot be installed on this machine" in result.output
    assert sandbox.requests() == []
    _assert_nothing_installed(sandbox)


def test_install_refuses_x64_on_arm_linux(sandbox: Sandbox) -> None:
    """Linux has no x64 emulation layer, so x64 is refused on ARM."""
    sandbox.host = dict(LINUX_ARM)
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "x64 build cannot be installed on this ARM Linux machine" in result.output
    assert sandbox.requests() == []
    _assert_nothing_installed(sandbox)


@pytest.mark.parametrize(
    ("glibc", "message"),
    [
        ("2.35", "found 2.35"),
        ("1.99", "found 1.99"),
        ("", "musl is not supported"),
    ],
)
def test_install_refuses_old_glibc_and_musl(
    sandbox: Sandbox, glibc: str, message: str
) -> None:
    """The Linux binaries need glibc 2.39 or newer."""
    sandbox.host = {
        "STUB_UNAME_S": "Linux",
        "STUB_UNAME_M": "x86_64",
        "STUB_GLIBC": glibc,
    }
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert message in result.output
    assert sandbox.requests() == []


def test_install_accepts_a_newer_glibc(sandbox: Sandbox) -> None:
    """glibc 2.43 passes the 2.39 floor."""
    sandbox.host = {**LINUX_X64, "STUB_GLIBC": "2.43"}
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output


# ---------------------------------------------------------------------------
# Release problems
# ---------------------------------------------------------------------------


def test_install_reports_a_failed_release_lookup(sandbox: Sandbox) -> None:
    """A failed redirect lookup stops before any download."""
    sandbox.extra_env["STUB_LATEST_FAIL"] = "1"
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "Failed to detect the latest Blinter version" in result.output
    _assert_nothing_installed(sandbox)


def test_install_rejects_an_unparseable_tag(sandbox: Sandbox) -> None:
    """A redirect that is not a vX.Y.Z tag is not trusted."""
    sandbox.tag = "latest"
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "Failed to parse Blinter version" in result.output
    _assert_nothing_installed(sandbox)


def test_install_refuses_a_missing_digest(tmp_path: Path) -> None:
    """An archive without a SHA256SUMS line is never installed."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "x64", ReleaseOptions(digest="missing"))
    result = sb.install("x64")
    assert result.returncode == 1
    assert "missing a SHA256 digest" in result.output
    assert "Refusing to install an unverifiable archive" in result.output
    assert not any(url.endswith(".tar.gz") for url in sb.requests())
    _assert_nothing_installed(sb)


def test_install_refuses_a_digest_mismatch(tmp_path: Path) -> None:
    """A tampered archive fails the hash check and is not extracted."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "x64", ReleaseOptions(digest="wrong"))
    result = sb.install("x64")
    assert result.returncode == 1
    assert "SHA256 digest mismatch" in result.output
    assert "Extracting Blinter" not in result.output
    _assert_nothing_installed(sb)


def test_install_refuses_an_undersized_download(tmp_path: Path) -> None:
    """A tiny archive is reported as a bad download even with a valid digest."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "x64", ReleaseOptions(padding=b""))
    result = sb.install("x64")
    assert result.returncode == 1
    assert "Downloaded file is too small" in result.output
    _assert_nothing_installed(sb)


def test_install_refuses_the_wrong_archive_layout(tmp_path: Path) -> None:
    """The binary must sit in the folder named like the archive."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "x64", ReleaseOptions(folder="elsewhere"))
    result = sb.install("x64")
    assert result.returncode == 1
    assert "Blinter executable not found in extracted archive" in result.output
    assert f"Expected layout: Blinter-{TAG}-Linux-x64/blinter" in result.output
    _assert_nothing_installed(sb)


def test_install_reports_a_missing_asset(tmp_path: Path) -> None:
    """A release without this platform's archive fails at the digest lookup."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "arm64")
    result = sb.install("x64")
    assert result.returncode == 1
    assert "missing a SHA256 digest" in result.output
    _assert_nothing_installed(sb)


def test_failed_fresh_install_leaves_nothing_behind(tmp_path: Path) -> None:
    """A binary that cannot run is removed again after a first install."""
    sb = make_sandbox(tmp_path)
    sb.publish(TAG, "Linux", "x64", ReleaseOptions(version_exit=1))
    result = sb.install("x64")
    assert result.returncode == 1
    assert "blinter failed to execute" in result.output
    assert "Removing the incomplete installation" in result.output
    assert not sb.data_home.exists()
    assert not (sb.home / ".profile").exists()


# ---------------------------------------------------------------------------
# Install, update, and restore
# ---------------------------------------------------------------------------


def test_fresh_install_creates_layout_marker_and_profile(sandbox: Sandbox) -> None:
    """A first install writes the binary, the marker, and the PATH block."""
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert "No existing installation found" in result.output
    assert f"SUCCESS: Blinter {TAG} installed successfully" in result.output
    assert sandbox.exe.is_file()
    assert os.access(sandbox.exe, os.X_OK)
    assert (sandbox.exe.stat().st_mode & 0o777) == 0o755
    assert sandbox.marker.read_text(encoding="utf-8") == f"{TAG}\n"
    profile = sandbox.home / ".profile"
    assert _block_count(profile) == 1
    assert not (sandbox.home / ".bashrc").exists()
    assert not (sandbox.home / ".zshrc").exists()
    assert not any(
        path.name.startswith(".blinter.new") for path in sandbox.exe.parent.iterdir()
    )
    version = subprocess.run(
        [str(sandbox.exe), "--version"], capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == f"{TAG} (standalone exe)"


def test_install_adds_the_block_to_existing_startup_files(sandbox: Sandbox) -> None:
    """Existing bash and zsh startup files each get one block."""
    for name in (".bashrc", ".zshrc", ".bash_profile"):
        (sandbox.home / name).write_text("export KEEP=1\n", encoding="utf-8")
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    for name in (".profile", ".bashrc", ".zshrc", ".bash_profile"):
        assert _block_count(sandbox.home / name) == 1, name
    assert (
        (sandbox.home / ".bashrc")
        .read_text(encoding="utf-8")
        .startswith("export KEEP=1\n")
    )


def test_macos_install_creates_zshrc(tmp_path: Path) -> None:
    """zsh is the macOS default, so ~/.zshrc is created when missing."""
    sb = make_sandbox(tmp_path)
    sb.host = dict(MAC_ARM)
    sb.publish(TAG, "macOS", "arm64")
    result = sb.install("arm64")
    assert result.returncode == 0, result.output
    assert _block_count(sb.home / ".zshrc") == 1
    assert _block_count(sb.home / ".profile") == 1


@pytest.mark.parametrize(
    ("host", "arch", "note"),
    [
        (MAC_ROSETTA, "x64", True),
        (MAC_ARM, "x64", True),
        (MAC_INTEL, "x64", False),
        (MAC_ROSETTA, "arm64", False),
        (MAC_ARM, "arm64", False),
    ],
)
def test_macos_architecture_selection(
    tmp_path: Path, host: dict[str, str], arch: str, note: bool
) -> None:
    """Apple Silicon, including a shell running under Rosetta, can run either build."""
    sb = make_sandbox(tmp_path)
    sb.host = dict(host)
    sb.publish(TAG, "macOS", arch)
    result = sb.install(arch)
    assert result.returncode == 0, result.output
    assert ("runs through Rosetta" in result.output) is note
    assert f"Blinter-{TAG}-macOS-{arch}.tar.gz" in "\n".join(sb.requests())


def test_arm_linux_installs_the_arm64_build(tmp_path: Path) -> None:
    """ARM Linux downloads the Linux arm64 archive."""
    sb = make_sandbox(tmp_path)
    sb.host = dict(LINUX_ARM)
    sb.publish(TAG, "Linux", "arm64")
    result = sb.install("arm64")
    assert result.returncode == 0, result.output
    assert f"Blinter-{TAG}-Linux-arm64.tar.gz" in "\n".join(sb.requests())


def test_install_requests_are_https_release_urls(sandbox: Sandbox) -> None:
    """Only the latest redirect, SHA256SUMS, and the archive are requested."""
    assert sandbox.install("x64").returncode == 0
    prefix = "https://github.com/BatchLang/Blinter/releases/"
    assert sandbox.requests() == [
        f"{prefix}latest",
        f"{prefix}download/{TAG}/SHA256SUMS",
        f"{prefix}download/{TAG}/Blinter-{TAG}-Linux-x64.tar.gz",
    ]


def test_install_twice_is_a_no_op_that_downloads_nothing(sandbox: Sandbox) -> None:
    """A second run on the latest release stops before the archive download."""
    assert sandbox.install("x64").returncode == 0
    sandbox.curl_log.unlink()
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert f"Blinter {TAG} is already installed and up to date" in result.output
    assert all(not url.endswith(".tar.gz") for url in sandbox.requests())


def test_install_upgrades_an_older_release(sandbox: Sandbox) -> None:
    """A newer latest release replaces the binary and the marker."""
    assert sandbox.install("x64").returncode == 0
    sandbox.publish(NEWER_TAG, "Linux", "x64")
    sandbox.tag = NEWER_TAG
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert f'Upgrading from "{TAG}" to {NEWER_TAG}' in result.output
    assert "Creating backup of existing installation" in result.output
    assert sandbox.marker.read_text(encoding="utf-8") == f"{NEWER_TAG}\n"
    version = subprocess.run(
        [str(sandbox.exe), "--version"], capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == f"{NEWER_TAG} (standalone exe)"
    assert _block_count(sandbox.home / ".profile") == 1


def test_install_upgrades_a_binary_without_a_marker(sandbox: Sandbox) -> None:
    """An install from before the marker existed is upgraded."""
    assert sandbox.install("x64").returncode == 0
    sandbox.marker.unlink()
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert "Existing installation found without release marker" in result.output
    assert sandbox.marker.read_text(encoding="utf-8") == f"{TAG}\n"


def test_install_reinstalls_when_the_binary_is_missing(sandbox: Sandbox) -> None:
    """A marker with no binary triggers a reinstall of the same release."""
    assert sandbox.install("x64").returncode == 0
    sandbox.exe.unlink()
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert "is recorded as installed, but blinter is missing" in result.output
    assert sandbox.exe.is_file()
    assert _block_count(sandbox.home / ".profile") == 1


def test_install_reinstalls_when_the_binary_does_not_run(sandbox: Sandbox) -> None:
    """A marker with a broken binary reinstalls and keeps a backup until success."""
    assert sandbox.install("x64").returncode == 0
    install_stub(sandbox.exe, "blinter_broken")
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert "Reinstalling Blinter" in result.output
    assert "Creating backup of existing installation" in result.output
    version = subprocess.run(
        [str(sandbox.exe), "--version"], capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == f"{TAG} (standalone exe)"


def test_failed_upgrade_restores_the_previous_install(sandbox: Sandbox) -> None:
    """A new binary that cannot run is rolled back to the old binary and marker."""
    assert sandbox.install("x64").returncode == 0
    sandbox.publish(NEWER_TAG, "Linux", "x64", ReleaseOptions(version_exit=1))
    sandbox.tag = NEWER_TAG
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "blinter failed to execute" in result.output
    assert "Previous installation restored" in result.output
    assert sandbox.marker.read_text(encoding="utf-8") == f"{TAG}\n"
    version = subprocess.run(
        [str(sandbox.exe), "--version"], capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == f"{TAG} (standalone exe)"


def test_failed_download_keeps_the_previous_install(sandbox: Sandbox) -> None:
    """A digest failure during an upgrade never touches the working install."""
    assert sandbox.install("x64").returncode == 0
    sandbox.publish(NEWER_TAG, "Linux", "x64", ReleaseOptions(digest="wrong"))
    sandbox.tag = NEWER_TAG
    result = sandbox.install("x64")
    assert result.returncode == 1
    assert "SHA256 digest mismatch" in result.output
    assert sandbox.marker.read_text(encoding="utf-8") == f"{TAG}\n"
    assert sandbox.exe.is_file()


def test_install_cleans_up_its_work_directory(sandbox: Sandbox) -> None:
    """Success and failure both remove the temporary directory."""
    sandbox.install("x64")
    sandbox.install("arm64")
    assert not list((sandbox.root / "tmp").iterdir())


def test_install_warns_when_another_blinter_wins_on_path(sandbox: Sandbox) -> None:
    """The install folder is appended, so an earlier blinter keeps winning."""
    other_bin = sandbox.root / "other-bin"
    other_bin.mkdir()
    install_stub(other_bin / "blinter", "blinter_other")
    original_environment = sandbox.environment

    def with_other() -> dict[str, str]:
        env = original_environment()
        env["PATH"] = f"{other_bin}{os.pathsep}{env['PATH']}"
        return env

    sandbox.environment = with_other  # type: ignore[method-assign]
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert "Another blinter is earlier on PATH" in result.output
    assert str(other_bin / "blinter") in result.output


def test_install_honors_an_absolute_xdg_data_home(sandbox: Sandbox) -> None:
    """XDG_DATA_HOME moves the install, and a relative value is ignored."""
    xdg = sandbox.root / "xdg"
    sandbox.extra_env["XDG_DATA_HOME"] = str(xdg)
    assert sandbox.install("x64").returncode == 0
    assert (xdg / "blinter" / "bin" / "blinter").is_file()
    assert not sandbox.data_home.exists()

    sandbox.extra_env["XDG_DATA_HOME"] = "relative/path"
    assert sandbox.uninstall().returncode == 0
    assert sandbox.install("x64").returncode == 0
    assert sandbox.exe.is_file()


# ---------------------------------------------------------------------------
# PATH block behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/bash"])
def test_profile_block_puts_blinter_on_path(sandbox: Sandbox, shell: str) -> None:
    """A fresh shell that sources ~/.profile finds the installed blinter."""
    assert sandbox.install("x64").returncode == 0
    assert _sourced_blinter(sandbox, shell) == str(sandbox.exe)


def test_home_with_space_and_apostrophe_works(tmp_path: Path) -> None:
    """The block quotes the path so awkward HOME values still resolve."""
    sb = make_sandbox(tmp_path, home_name="O'Brien (x86) home")
    sb.publish(TAG, "Linux", "x64")
    result = sb.install("x64")
    assert result.returncode == 0, result.output
    assert sb.exe.is_file()
    assert _sourced_blinter(sb, "/bin/sh") == str(sb.exe)
    assert _sourced_blinter(sb, "/bin/bash") == str(sb.exe)
    assert sb.uninstall().returncode == 0
    assert not sb.data_home.exists()


def test_profile_block_is_not_added_twice(sandbox: Sandbox) -> None:
    """Reinstalling over an existing block leaves exactly one."""
    assert sandbox.install("x64").returncode == 0
    sandbox.exe.unlink()
    result = sandbox.install("x64")
    assert result.returncode == 0, result.output
    assert "already in" in result.output
    assert _block_count(sandbox.home / ".profile") == 1


def test_profile_block_is_replaced_when_the_install_path_changes(
    sandbox: Sandbox,
) -> None:
    """Moving XDG_DATA_HOME replaces the old block instead of adding a second."""
    assert sandbox.install("x64").returncode == 0
    xdg = sandbox.root / "xdg"
    sandbox.extra_env["XDG_DATA_HOME"] = str(xdg)
    assert sandbox.install("x64").returncode == 0
    profile = sandbox.home / ".profile"
    assert _block_count(profile) == 1
    assert str(xdg) in profile.read_text(encoding="utf-8")


def test_profile_without_trailing_newline_is_kept_intact(sandbox: Sandbox) -> None:
    """The block starts on its own line and the file's content is untouched."""
    bashrc = sandbox.home / ".bashrc"
    bashrc.write_text("alias ll='ls -l'", encoding="utf-8")
    assert sandbox.install("x64").returncode == 0
    lines = bashrc.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "alias ll='ls -l'"
    assert lines[1] == START_MARKER


def test_profile_permissions_and_symlinks_survive(sandbox: Sandbox) -> None:
    """A dotfile symlink stays a symlink and its target keeps its mode."""
    target = sandbox.root / "dotfiles-bashrc"
    target.write_text("export KEEP=1\n", encoding="utf-8")
    target.chmod(0o600)
    link = sandbox.home / ".bashrc"
    link.symlink_to(target)
    assert sandbox.install("x64").returncode == 0
    assert link.is_symlink()
    assert _block_count(target) == 1
    assert (target.stat().st_mode & 0o777) == 0o600
    assert sandbox.uninstall().returncode == 0
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "export KEEP=1\n"


# ---------------------------------------------------------------------------
# Uninstaller
# ---------------------------------------------------------------------------


def test_uninstall_removes_everything_and_keeps_other_lines(sandbox: Sandbox) -> None:
    """Uninstall removes the files, the directory, and only the Blinter block."""
    bashrc = sandbox.home / ".bashrc"
    bashrc.write_text("export BEFORE=1\n", encoding="utf-8")
    zshrc = sandbox.home / ".zshrc"
    zshrc.write_text("export ZSH_KEEP=1\n", encoding="utf-8")
    assert sandbox.install("x64").returncode == 0
    with bashrc.open("a", encoding="utf-8") as handle:
        handle.write("export AFTER=1\n")

    result = sandbox.uninstall()
    assert result.returncode == 0, result.output
    assert "SUCCESS: Blinter uninstalled successfully" in result.output
    assert "completed with warnings" not in result.output
    assert not sandbox.data_home.exists()
    assert bashrc.read_text(encoding="utf-8") == "export BEFORE=1\nexport AFTER=1\n"
    assert zshrc.read_text(encoding="utf-8") == "export ZSH_KEEP=1\n"
    for name in (".profile", ".bashrc", ".zshrc"):
        assert START_MARKER not in (sandbox.home / name).read_text(encoding="utf-8")


def test_uninstall_shows_the_installed_version(sandbox: Sandbox) -> None:
    """The uninstaller prints the version and release it removes."""
    assert sandbox.install("x64").returncode == 0
    result = sandbox.uninstall()
    assert f"{TAG} (standalone exe)" in result.output
    assert f'Installed release: "{TAG}"' in result.output


def test_uninstall_with_nothing_installed_is_a_no_op(sandbox: Sandbox) -> None:
    """With no install and no block there is nothing to do, and that is success."""
    result = sandbox.uninstall()
    assert result.returncode == 0
    assert "Nothing to uninstall" in result.output
    assert not list(sandbox.home.iterdir())


def test_uninstall_cleans_a_block_left_without_an_install(sandbox: Sandbox) -> None:
    """A stale block is removed even when the install folder is already gone."""
    assert sandbox.install("x64").returncode == 0
    shutil.rmtree(sandbox.data_home)
    result = sandbox.uninstall()
    assert result.returncode == 0, result.output
    assert START_MARKER not in (sandbox.home / ".profile").read_text(encoding="utf-8")


def test_uninstall_refuses_root(sandbox: Sandbox) -> None:
    """The uninstaller refuses root like the installer."""
    sandbox.extra_env["STUB_UID"] = "0"
    result = sandbox.uninstall()
    assert result.returncode == 1
    assert "without root privileges" in result.output


def test_uninstall_rejects_arguments(sandbox: Sandbox) -> None:
    """Unknown arguments print usage and change nothing."""
    assert sandbox.install("x64").returncode == 0
    result = sandbox.uninstall("--force")
    assert result.returncode == 1
    assert "Usage: uninstall_blinter.sh" in result.output
    assert sandbox.exe.is_file()
    assert sandbox.uninstall("--help").returncode == 0


def test_uninstall_reports_an_unterminated_block_as_a_warning(
    sandbox: Sandbox,
) -> None:
    """A damaged block is left alone and reported, and the rest is still removed."""
    assert sandbox.install("x64").returncode == 0
    broken = sandbox.home / ".bashrc"
    broken.write_text(f"export KEEP=1\n{START_MARKER}\nexport LOST=1\n", "utf-8")
    result = sandbox.uninstall()
    assert result.returncode == 0, result.output
    assert "no end marker" in result.output
    assert "completed with warnings" in result.output
    assert broken.read_text(encoding="utf-8").endswith("export LOST=1\n")
    assert not sandbox.data_home.exists()


def test_uninstall_leaves_a_running_blinter_working(sandbox: Sandbox) -> None:
    """Deleting the binary is safe while a copy of it is running."""
    assert sandbox.install("x64").returncode == 0
    install_stub(sandbox.exe, "blinter_sleeping")
    with subprocess.Popen(
        [str(sandbox.exe)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as running:
        try:
            result = sandbox.uninstall()
            assert result.returncode == 0, result.output
            assert not sandbox.exe.exists()
            assert running.poll() is None
        finally:
            running.kill()
            running.wait(timeout=RUN_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# Installer and uninstaller stay in step
# ---------------------------------------------------------------------------


def _function_body(text: str, name: str) -> str:
    """Return one shell function, from its header to its closing brace."""
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"{name} not found"
    return match.group(0)


def test_both_scripts_share_the_block_markers_and_strip_logic() -> None:
    """The installer and uninstaller must agree on how a block is delimited."""
    install_text = INSTALL.read_text(encoding="utf-8")
    uninstall_text = UNINSTALL.read_text(encoding="utf-8")
    for marker_line in (
        f"readonly PATH_BLOCK_START='{START_MARKER}'",
        f"readonly PATH_BLOCK_END='{END_MARKER}'",
    ):
        assert marker_line in install_text
        assert marker_line in uninstall_text
    assert _function_body(install_text, "strip_path_block") == _function_body(
        uninstall_text, "strip_path_block"
    )


def test_scripts_use_lf_line_endings_and_a_bash_shebang() -> None:
    """CRLF would break the shebang, so the scripts must be LF."""
    for script in (INSTALL, UNINSTALL):
        data = script.read_bytes()
        assert data.startswith(b"#!/usr/bin/env bash\n")
        assert b"\r" not in data
