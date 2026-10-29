"""Shared fixtures for the Linux and macOS installer script tests.

The scripts run for real under bash. Only the outside world is replaced: ``curl``
serves a local release, and ``uname``, ``id``, ``getconf`` and ``sysctl`` report
a chosen host. The stand-in commands are the scripts in ``tests/unix_stubs``, which
ShellCheck lints with the installer scripts. Every test gets its own HOME, so nothing touches the real user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import os
from pathlib import Path
import random
import shutil
import subprocess
import tarfile

_REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL = _REPO_ROOT / "scripts" / "install_blinter.sh"
UNINSTALL = _REPO_ROOT / "scripts" / "uninstall_blinter.sh"
STUBS_DIR = _REPO_ROOT / "tests" / "unix_stubs"
_STUBBED_COMMANDS = ("curl", "uname", "id", "getconf", "sysctl", "chmod")
_BASH = "/bin/bash" if Path("/bin/bash").exists() else "bash"
RUN_TIMEOUT_SECONDS = 60
TAG = "v1.2.3"
NEWER_TAG = "v1.2.4"
START_MARKER = "# >>> blinter >>>"
END_MARKER = "# <<< blinter <<<"

# The installer rejects archives under 500,000 bytes, so the padding must not
# compress. A seeded generator keeps the bytes the same on every run.
_PADDING = random.Random(20260101).randbytes(600_000)

LINUX_X64 = {"STUB_UNAME_S": "Linux", "STUB_UNAME_M": "x86_64", "STUB_GLIBC": "2.39"}
LINUX_ARM = {"STUB_UNAME_S": "Linux", "STUB_UNAME_M": "aarch64", "STUB_GLIBC": "2.39"}
MAC_ARM = {"STUB_UNAME_S": "Darwin", "STUB_UNAME_M": "arm64", "STUB_SYSCTL_ARM64": "1"}
MAC_ROSETTA = {
    "STUB_UNAME_S": "Darwin",
    "STUB_UNAME_M": "x86_64",
    "STUB_SYSCTL_ARM64": "1",
}
MAC_INTEL = {"STUB_UNAME_S": "Darwin", "STUB_UNAME_M": "x86_64"}


@dataclass
class Run:
    """Exit status and combined output of one script run."""

    returncode: int
    output: str


@dataclass(frozen=True)
class ReleaseOptions:
    """How a published test release differs from a healthy one.

    ``digest`` is ``correct``, ``wrong``, or ``missing``. ``folder`` replaces the
    folder name inside the archive.
    """

    version_exit: int = 0
    digest: str = "correct"
    padding: bytes = _PADDING
    folder: str | None = None


def _stub_binary(tag: str, version_exit: int) -> bytes:
    """Return the stand-in blinter executable with its version and exit code filled in."""
    template = (STUBS_DIR / "blinter").read_text(encoding="utf-8")
    script = template.replace("@TAG@", tag).replace("@VERSION_EXIT@", str(version_exit))
    return script.encode("utf-8")


def _write_archive(archive_path: Path, folder_name: str, script: bytes) -> None:
    """Write a gzipped tar with one folder holding an executable ``blinter``."""
    with tarfile.open(archive_path, "w:gz") as archive:
        directory = tarfile.TarInfo(name=folder_name)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        member = tarfile.TarInfo(name=f"{folder_name}/blinter")
        member.size = len(script)
        member.mode = 0o755
        archive.addfile(member, io.BytesIO(script))


@dataclass
class Sandbox:
    """An isolated HOME, a fake release server, and stub system commands."""

    root: Path
    home: Path
    fake_bin: Path
    release_dir: Path
    host: dict[str, str] = field(default_factory=lambda: dict(LINUX_X64))
    extra_env: dict[str, str] = field(default_factory=dict)
    tag: str = TAG

    @property
    def curl_log(self) -> Path:
        """Return the file where the curl stub records requests."""
        return self.root / "curl.log"

    @property
    def data_home(self) -> Path:
        """Return the default install root under HOME."""
        return self.home / ".local" / "share" / "blinter"

    @property
    def exe(self) -> Path:
        """Return the installed binary path."""
        return self.data_home / "bin" / "blinter"

    @property
    def marker(self) -> Path:
        """Return the installed release marker path."""
        return self.data_home / "installed_release.txt"

    def requests(self) -> list[str]:
        """Return every URL the curl stub served, in order."""
        if not self.curl_log.exists():
            return []
        return self.curl_log.read_text(encoding="utf-8").splitlines()

    def environment(self) -> dict[str, str]:
        """Build the process environment for one script run."""
        system_path = [
            entry
            for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry and not (Path(entry) / "blinter").exists()
        ]
        env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join([str(self.fake_bin), *system_path]),
            "TMPDIR": str(self.root / "tmp"),
            "SHELL": "/bin/bash",
            "LC_ALL": "C",
            "STUB_TAG": self.tag,
            "STUB_RELEASE_DIR": str(self.release_dir),
            "STUB_CURL_LOG": str(self.curl_log),
        }
        env.update(self.host)
        env.update(self.extra_env)
        return env

    def publish(
        self,
        tag: str,
        os_name: str,
        arch: str,
        options: ReleaseOptions | None = None,
    ) -> Path:
        """Create a release archive and list it in SHA256SUMS."""
        chosen = options or ReleaseOptions()
        name = f"Blinter-{tag}-{os_name}-{arch}.tar.gz"
        folder_name = chosen.folder or f"Blinter-{tag}-{os_name}-{arch}"
        script = _stub_binary(tag, chosen.version_exit) + chosen.padding
        archive_path = self.release_dir / name
        _write_archive(archive_path, folder_name, script)
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        listed = "0" * 64 if chosen.digest == "wrong" else actual
        if chosen.digest != "missing":
            with (self.release_dir / "SHA256SUMS").open("a", encoding="utf-8") as sums:
                sums.write(f"{listed}  {name}\n")
        elif not (self.release_dir / "SHA256SUMS").exists():
            (self.release_dir / "SHA256SUMS").write_text("", encoding="utf-8")
        return archive_path

    def install(self, *args: str) -> Run:
        """Run the installer."""
        return _run(INSTALL, self, *args)

    def uninstall(self, *args: str) -> Run:
        """Run the uninstaller."""
        return _run(UNINSTALL, self, *args)


def _run(script: Path, sandbox: Sandbox, *args: str) -> Run:
    """Run one script under bash and return its combined output."""
    completed = subprocess.run(
        [_BASH, str(script), *args],
        env=sandbox.environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
        cwd=sandbox.root,
    )
    return Run(completed.returncode, completed.stdout)


def install_stub(destination: Path, source_name: str) -> None:
    """Copy one script from ``tests/unix_stubs`` to ``destination`` and make it executable."""
    shutil.copyfile(STUBS_DIR / source_name, destination)
    destination.chmod(0o755)


def make_sandbox(root: Path, home_name: str = "home") -> Sandbox:
    """Create the directories and stub commands for one test."""
    home = root / home_name
    fake_bin = root / "fake-bin"
    release_dir = root / "release"
    for directory in (home, fake_bin, release_dir, root / "tmp"):
        directory.mkdir(parents=True, exist_ok=True)
    for command in _STUBBED_COMMANDS:
        install_stub(fake_bin / command, command)
    return Sandbox(
        root=root,
        home=home,
        fake_bin=fake_bin,
        release_dir=release_dir,
    )
