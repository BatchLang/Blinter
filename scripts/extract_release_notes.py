#!/usr/bin/env python3
"""Print the latest release-notes section from CHANGELOG.md to stdout."""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os
from pathlib import Path
import re
import sys

logger = logging.getLogger(__name__)

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
_SECTION_RE = re.compile(r"^## \[[^\]]+\].*$", re.MULTILINE)
_NOTES_FILENAME = "release-notes.md"
_GITHUB_OUTPUT_FLAG = "--github-output"


def _heading_version(heading: str) -> str:
    """Return the bracketed version label from a changelog heading line."""
    start = heading.find("[")
    end = heading.find("]", start + 1)
    if start < 0 or end < 0:
        return ""
    return heading[start + 1 : end]


def extract_latest_section(changelog_path: Path = _CHANGELOG) -> str:
    """Return markdown for the most recent versioned changelog section.

    ``## [Unreleased]`` headings are skipped so GitHub Releases publish the
    latest tagged version notes rather than in-progress work.
    """
    text = changelog_path.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    versioned = [
        match
        for match in matches
        if _heading_version(text[match.start() : match.end()]).casefold()
        != "unreleased"
    ]
    if not versioned:
        raise SystemExit(f"No version sections found in {changelog_path}")

    start = versioned[0].start()
    following = [match for match in matches if match.start() > start]
    end = following[0].start() if following else len(text)
    section = text[start:end].strip()
    if not section:
        raise SystemExit("Latest changelog section is empty")
    return section


def _configure_logging() -> None:
    """Send release-note progress to stderr without duplicating handlers."""
    if logging.getLogger().handlers:
        logger.setLevel(logging.INFO)
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _append_github_output(name: str, value: str) -> None:
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


def write_github_release_notes(
    changelog_path: Path | None = None,
    notes_dir: Path | None = None,
) -> Path:
    """Write the latest changelog section and record its path for Actions.

    Returns the notes file path stored in ``GITHUB_OUTPUT``.
    """
    source = _CHANGELOG if changelog_path is None else changelog_path
    logger.info("Extracting release notes from %s", source)
    section = extract_latest_section(source)
    if notes_dir is None:
        raw_temp = os.environ.get("RUNNER_TEMP")
        if not raw_temp:
            raise SystemExit("RUNNER_TEMP is not set")
        notes_dir = Path(raw_temp)
    notes_path = notes_dir / _NOTES_FILENAME
    logger.info("Writing release notes to %s", notes_path)
    try:
        notes_path.write_text(section, encoding="utf-8", newline="\n")
    except OSError as exc:
        logger.error("Could not write release notes to %s: %s", notes_path, exc)
        raise SystemExit(f"Could not write release notes: {exc}") from exc
    _append_github_output("path", str(notes_path))
    return notes_path


def main(argv: Sequence[str] | None = None) -> None:
    """Print release notes, or write them for the GitHub Actions release step."""
    _configure_logging()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stdout.write(extract_latest_section())
        return
    if args == [_GITHUB_OUTPUT_FLAG]:
        write_github_release_notes()
        return
    raise SystemExit("usage: extract_release_notes.py [--github-output]")


if __name__ == "__main__":
    main()
