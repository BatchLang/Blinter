#!/usr/bin/env python3
"""Package a smoke-tested blinter binary into a release archive."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import tarfile
import tomllib
import zipfile

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OS_ENV = "BLINTER_OS_NAME"
_ARCH_ENV = "BLINTER_ARCH"
_WINDOWS = "Windows"
_LINUX = "Linux"
_MACOS = "macOS"
_ARCHIVE_SUFFIXES: dict[str, str] = {
    _WINDOWS: "zip",
    _LINUX: "tar.gz",
    _MACOS: "tar.gz",
}
_ARCHITECTURES: frozenset[str] = frozenset({"x64", "arm64"})
_EXECUTABLE_MODE = 0o755
_USAGE = (
    "usage: package_executable.py\n"
    "Reads BLINTER_OS_NAME (Windows, Linux, macOS) and BLINTER_ARCH (x64, arm64)."
)


def _configure_logging() -> None:
    """Send packaging progress to stderr without duplicating handlers."""
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
    if not pyproject_path.is_file():
        raise SystemExit(f"pyproject.toml not found: {pyproject_path}")
    try:
        with pyproject_path.open("rb") as handle:
            data_object: object = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"Could not parse {pyproject_path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Could not read {pyproject_path}: {exc}") from exc
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


def archive_name(version: str, os_name: str, arch: str) -> str:
    """Return the release archive filename for one OS and architecture."""
    suffix = _ARCHIVE_SUFFIXES.get(os_name)
    if suffix is None:
        raise SystemExit(
            "BLINTER_OS_NAME must be Windows, Linux, or macOS, " f"got {os_name!r}"
        )
    if arch not in _ARCHITECTURES:
        raise SystemExit(f"BLINTER_ARCH must be x64 or arm64, got {arch!r}")
    if not version or any(char in version for char in "/\\"):
        raise SystemExit(f"Refusing unsafe version {version!r}")
    name = f"Blinter-v{version}-{os_name}-{arch}.{suffix}"
    logger.info("Release archive name %s", name)
    return name


def binary_name(os_name: str) -> str:
    """Return ``blinter.exe`` on Windows and ``blinter`` elsewhere."""
    if os_name == _WINDOWS:
        return "blinter.exe"
    return "blinter"


def _write_zip(archive_path: Path, folder_name: str, binary: Path, name: str) -> None:
    """Write a zip whose only member is ``folder_name/name``."""
    logger.info("Writing zip %s", archive_path)
    member = f"{folder_name}/{name}"
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.write(binary, arcname=member)


def _write_tar(archive_path: Path, folder_name: str, binary: Path, name: str) -> None:
    """Write a gzipped tar that keeps the executable bit on ``name``."""
    logger.info("Writing tar.gz %s with mode %o", archive_path, _EXECUTABLE_MODE)
    directory = tarfile.TarInfo(name=folder_name)
    directory.type = tarfile.DIRTYPE
    directory.mode = _EXECUTABLE_MODE
    member = tarfile.TarInfo(name=f"{folder_name}/{name}")
    member.size = binary.stat().st_size
    member.mode = _EXECUTABLE_MODE
    member.type = tarfile.REGTYPE
    with tarfile.open(archive_path, "w:gz") as archive, binary.open("rb") as handle:
        archive.addfile(directory)
        archive.addfile(member, handle)


def package_executable(
    repo_root: Path,
    os_name: str,
    arch: str,
    *,
    version: str | None = None,
) -> Path:
    """Package ``dist/<binary>`` and return the archive path."""
    resolved_version = (
        read_project_version(repo_root / "pyproject.toml")
        if version is None
        else version
    )
    name = binary_name(os_name)
    binary = repo_root / "dist" / name
    logger.info(
        "Packaging %s for %s %s version %s",
        binary,
        os_name,
        arch,
        resolved_version,
    )
    if not binary.is_file():
        raise SystemExit(f"Executable not found: {binary}")
    filename = archive_name(resolved_version, os_name, arch)
    suffix = ".zip" if os_name == _WINDOWS else ".tar.gz"
    folder_name = filename.removesuffix(suffix)
    archive_path = repo_root / "dist" / filename
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        logger.info("Replacing existing archive %s", archive_path)
        archive_path.unlink()
    if os_name == _WINDOWS:
        _write_zip(archive_path, folder_name, binary, name)
    else:
        _write_tar(archive_path, folder_name, binary, name)
    logger.info("Packaged %s (%s bytes)", archive_path, archive_path.stat().st_size)
    return archive_path


def _required_env(name: str) -> str:
    """Return a non-empty environment variable."""
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is empty")
    logger.info("%s=%s", name, value)
    return value


def main(argv: list[str] | None = None) -> None:
    """Package the executable described by the process environment."""
    _configure_logging()
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(_USAGE)
        return
    if args:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2)
    package_executable(
        _REPO_ROOT,
        _required_env(_OS_ENV),
        _required_env(_ARCH_ENV),
    )


if __name__ == "__main__":
    main()
