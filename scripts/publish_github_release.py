#!/usr/bin/env python3
"""Create or update the GitHub Release for the standalone build archives.

Reads ``VERSION``, ``NOTES_FILE``, and ``GITHUB_SHA`` from the environment.
``GH_TOKEN`` or ``GITHUB_TOKEN`` authenticates the ``gh`` CLI. A missing
release is created with ``--target`` set to ``GITHUB_SHA``. An existing
release is updated only when its tag already points at ``GITHUB_SHA``; it is
then edited and its same-named assets are replaced with ``--clobber``.
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
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
_CHECKSUM_NAME = "SHA256SUMS"
_ARCHIVE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("Windows", "x64", "zip"),
    ("Windows", "arm64", "zip"),
    ("Linux", "x64", "tar.gz"),
    ("Linux", "arm64", "tar.gz"),
    ("macOS", "arm64", "tar.gz"),
    ("macOS", "x64", "tar.gz"),
)
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


def release_archive_names(version: str) -> tuple[str, ...]:
    """Return the archive filenames required for one release."""
    names = tuple(
        f"Blinter-v{version}-{os_name}-{arch}.{suffix}"
        for os_name, arch, suffix in _ARCHIVE_SPECS
    )
    logger.info("Expected release archives: %s", ", ".join(names))
    return names


def _sha256(path: Path) -> str:
    """Return the lowercase SHA-256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    value = digest.hexdigest()
    logger.info("SHA-256 %s %s", value, path.name)
    return value


def write_sha256sums(build_dir: Path, archives: Sequence[Path]) -> Path:
    """Write ``SHA256SUMS`` for ``archives`` and return its path."""
    lines = [f"{_sha256(archive)}  {archive.name}\n" for archive in archives]
    destination = build_dir / _CHECKSUM_NAME
    logger.info("Writing %s", destination)
    destination.write_text("".join(lines), encoding="utf-8", newline="\n")
    return destination


def _require_files(notes_file: Path, assets: Sequence[Path]) -> None:
    """Exit when the notes file or an archive is missing."""
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


def _asset_arguments(assets: Sequence[Path]) -> list[str]:
    """Return archive paths in the order ``gh`` should upload them."""
    return [str(asset) for asset in assets]


def create_release(
    tag: str,
    notes_file: Path,
    assets: Sequence[Path],
    target: str,
) -> None:
    """Create ``tag`` at ``target`` and upload the release archives."""
    commit = _require_target(target)
    logger.info("Creating release %s at %s", tag, commit)
    completed = _run_gh(
        [
            "release",
            "create",
            tag,
            *_asset_arguments(assets),
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


def require_tag_at_commit(tag: str, target: str) -> None:
    """Exit unless ``tag`` already points at the commit that was built.

    Replacing the assets of a release whose tag names a different commit would
    publish binaries that do not match the tagged source.
    """
    commit = _require_target(target).lower()
    completed = _run_gh(
        ["api", f"repos/{{owner}}/{{repo}}/commits/{tag}", "--jq", ".sha"],
        timeout=_LOOKUP_TIMEOUT_SECONDS,
    )
    _require_success(completed, f"Resolving the commit of tag {tag}")
    tagged = (completed.stdout or "").strip().lower()
    logger.info("Tag %s resolves to %s; built commit is %s", tag, tagged, commit)
    if not tagged or not tagged.startswith(commit):
        raise SystemExit(
            f"Release {tag} already exists at commit {tagged[:12] or 'unknown'}, "
            f"but this run built {commit[:12]}. Refusing to replace its assets; "
            "bump the project version to publish new code."
        )


def update_release(
    tag: str,
    notes_file: Path,
    assets: Sequence[Path],
) -> None:
    """Replace the title, notes, and same-named assets of an existing release."""
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
        ["release", "upload", tag, *_asset_arguments(assets), "--clobber"],
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
    archives = tuple(build_dir / name for name in release_archive_names(version))
    _require_files(notes_file, archives)
    assets = (*archives, write_sha256sums(build_dir, archives))
    _token_source()
    if release_exists(tag):
        require_tag_at_commit(tag, target_sha)
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
