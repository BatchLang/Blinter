#!/usr/bin/env python3
"""Create or update the GitHub Release for the Windows build zips.

Reads ``VERSION``, ``NOTES_FILE``, and ``GITHUB_SHA`` from the environment.
``GH_TOKEN`` or ``GITHUB_TOKEN`` authenticates the ``gh`` CLI. A missing
release is created with ``--target`` set to ``GITHUB_SHA``. An existing
release is edited, then its same-named assets are replaced with ``--clobber``.
"""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os
from pathlib import Path
import re
import subprocess
import sys

logger = logging.getLogger(__name__)

_VERSION_ENV = "VERSION"
_NOTES_ENV = "NOTES_FILE"
_SHA_ENV = "GITHUB_SHA"
_TOKEN_ENVS = ("GH_TOKEN", "GITHUB_TOKEN")
_BUILD_DIR = Path("build")
_VERSION_RE = re.compile(r"^[0-9A-Za-z._+-]+\Z")
_TARGET_RE = re.compile(r"^[0-9a-fA-F]{7,64}\Z")
_NOT_FOUND_MARKER = "release not found"
_LOOKUP_TIMEOUT_SECONDS = 120
_UPLOAD_TIMEOUT_SECONDS = 600
_USAGE = (
    "usage: publish_github_release.py\n"
    "Reads VERSION, NOTES_FILE, and GITHUB_SHA from the environment.\n"
    "GH_TOKEN or GITHUB_TOKEN authenticates gh."
)


def _configure_logging() -> None:
    """Send publish progress to stderr without duplicating handlers."""
    if logging.getLogger().handlers:
        logger.setLevel(logging.INFO)
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def release_tag(version: str) -> str:
    """Return ``v<version>`` when ``version`` is safe to embed in a filename."""
    logger.info("Validating version %r", version)
    if not version:
        raise SystemExit("VERSION is empty")
    if _VERSION_RE.fullmatch(version) is None:
        raise SystemExit(f"VERSION contains unexpected characters: {version}")
    tag = f"v{version}"
    logger.info("Release tag %s", tag)
    return tag


def _windows_assets(version: str, build_dir: Path) -> tuple[Path, Path]:
    """Return the x64 and arm64 zip paths published by the build job."""
    x64 = build_dir / f"Blinter-v{version}-Windows-x64.zip"
    arm64 = build_dir / f"Blinter-v{version}-Windows-arm64.zip"
    logger.info("Windows assets %s and %s", x64, arm64)
    return x64, arm64


def _require_files(notes_file: Path, assets: Sequence[Path]) -> None:
    """Exit when the notes file or a zip is missing."""
    logger.info("Checking release notes %s", notes_file)
    if not notes_file.is_file():
        raise SystemExit(f"Release notes file not found: {notes_file}")
    for asset in assets:
        logger.info("Checking release asset %s", asset)
        if not asset.is_file():
            raise SystemExit(f"Release asset not found: {asset}")


def _token_source() -> str:
    """Return the environment variable that holds a GitHub token."""
    for name in _TOKEN_ENVS:
        if os.environ.get(name):
            logger.info("GitHub token is set via %s", name)
            return name
    raise SystemExit("GH_TOKEN or GITHUB_TOKEN must be set")


def _output_text(completed: subprocess.CompletedProcess[str]) -> str:
    """Return stripped stderr, otherwise stripped stdout."""
    stderr = (completed.stderr or "").strip()
    if stderr:
        return stderr
    return (completed.stdout or "").strip()


def _run_gh(args: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` and return the completed process."""
    command = ["gh", *args]
    logger.info("Running %s", " ".join(command))
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("gh timed out after %s seconds: %s", timeout, command)
        raise SystemExit(f"gh timed out after {timeout} seconds") from exc
    except OSError as exc:
        logger.error("Could not run gh: %s", exc)
        raise SystemExit(f"Could not run gh: {exc}") from exc
    logger.info("gh exited %s", completed.returncode)
    detail = _output_text(completed)
    if detail:
        logger.info("gh output: %s", detail[:500])
    return completed


def _require_success(
    completed: subprocess.CompletedProcess[str],
    action: str,
) -> None:
    """Exit when ``gh`` did not succeed."""
    if completed.returncode == 0:
        return
    detail = _output_text(completed) or "no output"
    logger.error("%s failed (%s): %s", action, completed.returncode, detail)
    raise SystemExit(f"{action} failed: {detail}")


def release_exists(tag: str) -> bool:
    """Return whether GitHub already has a release for ``tag``."""
    completed = _run_gh(
        ["release", "view", tag, "--json", "tagName"],
        timeout=_LOOKUP_TIMEOUT_SECONDS,
    )
    if completed.returncode == 0:
        logger.info("Release %s already exists", tag)
        return True
    combined = f"{completed.stderr or ''}\n{completed.stdout or ''}".casefold()
    if _NOT_FOUND_MARKER in combined:
        logger.info("Release %s does not exist", tag)
        return False
    detail = _output_text(completed) or "no output"
    logger.error("Could not look up release %s: %s", tag, detail)
    raise SystemExit(f"Could not look up release {tag}: {detail}")


def _require_target(target: str) -> str:
    """Return a commit SHA suitable for ``gh release create --target``."""
    logger.info("Validating target commit %r", target)
    if _TARGET_RE.fullmatch(target) is None:
        raise SystemExit("GITHUB_SHA must be the commit that was built")
    return target


def create_release(
    tag: str,
    notes_file: Path,
    assets: tuple[Path, Path],
    target: str,
) -> None:
    """Create ``tag`` at ``target`` and upload both Windows zips."""
    commit = _require_target(target)
    x64, arm64 = assets
    logger.info("Creating release %s at %s", tag, commit)
    completed = _run_gh(
        [
            "release",
            "create",
            tag,
            str(x64),
            str(arm64),
            "--title",
            tag,
            "--notes-file",
            str(notes_file),
            "--target",
            commit,
        ],
        timeout=_UPLOAD_TIMEOUT_SECONDS,
    )
    _require_success(completed, f"Creating release {tag}")


def update_release(
    tag: str,
    notes_file: Path,
    assets: tuple[Path, Path],
) -> None:
    """Replace the title, notes, and same-named assets of an existing release."""
    x64, arm64 = assets
    logger.info("Updating existing release %s", tag)
    edited = _run_gh(
        [
            "release",
            "edit",
            tag,
            "--title",
            tag,
            "--notes-file",
            str(notes_file),
        ],
        timeout=_LOOKUP_TIMEOUT_SECONDS,
    )
    _require_success(edited, f"Updating release {tag}")
    uploaded = _run_gh(
        ["release", "upload", tag, str(x64), str(arm64), "--clobber"],
        timeout=_UPLOAD_TIMEOUT_SECONDS,
    )
    _require_success(uploaded, f"Uploading assets for {tag}")


def publish_github_release(
    version: str,
    notes_file: Path,
    target_sha: str,
    build_dir: Path = _BUILD_DIR,
) -> None:
    """Create or update the GitHub Release for ``version``."""
    logger.info(
        "Publishing version %s notes=%s build_dir=%s",
        version,
        notes_file,
        build_dir,
    )
    tag = release_tag(version)
    assets = _windows_assets(version, build_dir)
    _require_files(notes_file, assets)
    _token_source()
    if release_exists(tag):
        update_release(tag, notes_file, assets)
        return
    create_release(tag, notes_file, assets, target_sha)


def _required_env(name: str) -> str:
    """Return a non-empty environment variable."""
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is empty")
    return value


def main(argv: Sequence[str] | None = None) -> None:
    """Publish the release described by the process environment."""
    _configure_logging()
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(_USAGE)
        return
    if args:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(2)
    publish_github_release(
        version=_required_env(_VERSION_ENV),
        notes_file=Path(_required_env(_NOTES_ENV)),
        target_sha=os.environ.get(_SHA_ENV, ""),
    )


if __name__ == "__main__":
    main()
