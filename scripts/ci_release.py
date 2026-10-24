#!/usr/bin/env python3
"""Read the project version and decide whether CI should publish a release."""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os
from pathlib import Path
import subprocess
import sys
import tomllib

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_VERSION_COMMAND = "version"
_SHOULD_RELEASE_COMMAND = "should-release"
_WORKFLOW_DISPATCH = "workflow_dispatch"
_USAGE = "usage: ci_release.py {version,should-release}"
_GIT_SHOW_TIMEOUT_SECONDS = 30


def _configure_logging() -> None:
    """Send release decisions to stderr without duplicating handlers."""
    if logging.getLogger().handlers:
        logger.setLevel(logging.INFO)
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def read_project_version(pyproject_text: str) -> str:
    """Return ``[project].version`` from pyproject.toml text."""
    logger.info("Parsing project version from pyproject.toml text")
    try:
        data_object: object = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError as exc:
        logger.error("Invalid pyproject.toml: %s", exc)
        raise SystemExit(f"Could not parse pyproject.toml: {exc}") from exc
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


def read_version_file(pyproject_path: Path) -> str:
    """Return ``[project].version`` from a pyproject.toml file."""
    logger.info("Reading project version from %s", pyproject_path)
    if not pyproject_path.is_file():
        raise SystemExit(f"pyproject.toml not found at {pyproject_path}")
    try:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Could not read %s: %s", pyproject_path, exc)
        raise SystemExit(f"Could not read {pyproject_path}: {exc}") from exc
    return read_project_version(pyproject_text)


def read_previous_version() -> str:
    """Return ``[project].version`` from the parent commit's pyproject.toml."""
    logger.info("Reading previous version from HEAD^:pyproject.toml")
    try:
        previous_text = subprocess.check_output(
            ["git", "show", "HEAD^:pyproject.toml"],
            cwd=_REPO_ROOT,
            text=True,
            encoding="utf-8",
            timeout=_GIT_SHOW_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.error("Could not read previous pyproject.toml: %s", exc)
        raise SystemExit("Could not read previous version from pyproject.toml") from exc
    logger.info(
        "Loaded previous pyproject.toml (%d characters)",
        len(previous_text),
    )
    return read_project_version(previous_text)


def release_tag_exists(version: str) -> bool:
    """Return whether ``origin`` already has ``refs/tags/v<version>``."""
    tag_ref = f"refs/tags/v{version}"
    logger.info("Checking whether %s exists on origin", tag_ref)
    try:
        output = subprocess.check_output(
            ["git", "ls-remote", "origin", tag_ref],
            cwd=_REPO_ROOT,
            text=True,
            encoding="utf-8",
            timeout=_GIT_SHOW_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.error("Could not query %s: %s", tag_ref, exc)
        raise SystemExit(f"Could not check whether {tag_ref} exists") from exc
    published = bool(output.strip())
    logger.info("Tag %s published=%s", tag_ref, published)
    return published


def decide_release(
    event_name: str,
    current_version: str,
    previous_version: str,
    *,
    tag_exists: bool = True,
) -> bool:
    """Return whether this CI event should publish a release."""
    logger.info(
        "Release inputs: event=%s current=%s previous=%s tag_exists=%s",
        event_name,
        current_version,
        previous_version,
        tag_exists,
    )
    if event_name == _WORKFLOW_DISPATCH:
        logger.info("workflow_dispatch always releases")
        return True
    if current_version != previous_version:
        logger.info("Version comparison release=True")
        return True
    if not tag_exists:
        logger.info("Version %s has no release tag; releasing", current_version)
        return True
    logger.info("Version comparison release=False")
    return False


def append_github_output(name: str, value: str) -> None:
    """Append one single-line ``key=value`` pair to ``GITHUB_OUTPUT``."""
    if "\n" in value or "\r" in value:
        raise SystemExit(f"{name} must be a single line")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise SystemExit("GITHUB_OUTPUT is not set")
    path = Path(output_path)
    logger.info("Writing %s=%s to %s", name, value, path)
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{name}={value}\n")
    except OSError as exc:
        logger.error("Could not write GITHUB_OUTPUT at %s: %s", path, exc)
        raise SystemExit(f"Could not write GITHUB_OUTPUT: {exc}") from exc


def _release_message(
    event_name: str,
    current_version: str,
    previous_version: str,
    releasing: bool,
) -> str:
    """Return the CI log line for a release decision."""
    if event_name == _WORKFLOW_DISPATCH:
        return f"Manual workflow_dispatch; releasing version {current_version}."
    if releasing and current_version == previous_version:
        return f"Version {current_version} has no release tag; releasing."
    if releasing:
        return f"Version bumped: {previous_version} -> {current_version}"
    return f"Version unchanged ({current_version}); skipping release."


def publish_version(pyproject_path: Path | None = None) -> str:
    """Read the current version, record it, and return it."""
    path = _PYPROJECT if pyproject_path is None else pyproject_path
    project_version = read_version_file(path)
    append_github_output("version", project_version)
    print(f"Project version: {project_version}")
    return project_version


def publish_should_release() -> bool:
    """Compare versions and record ``should_release`` for the check-version job."""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    logger.info("Deciding release for event %s", event_name or "<unset>")
    current_version = read_version_file(_PYPROJECT)
    previous_version = ""
    tag_exists = True
    if event_name != _WORKFLOW_DISPATCH:
        previous_version = read_previous_version()
        if current_version == previous_version:
            tag_exists = release_tag_exists(current_version)
    releasing = decide_release(
        event_name,
        current_version,
        previous_version,
        tag_exists=tag_exists,
    )
    message = _release_message(
        event_name,
        current_version,
        previous_version,
        releasing,
    )
    logger.info(message)
    print(message)
    append_github_output("should_release", "true" if releasing else "false")
    return releasing


def main(argv: Sequence[str] | None = None) -> None:
    """Run the version or should-release subcommand."""
    _configure_logging()
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(_USAGE)
        return
    if len(args) != 1:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2)
    command = args[0]
    if command == _VERSION_COMMAND:
        publish_version()
        return
    if command == _SHOULD_RELEASE_COMMAND:
        publish_should_release()
        return
    print(_USAGE, file=sys.stderr)
    raise SystemExit(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
