"""Baseline files that accept known findings.

An entry matches one finding by rule code, a path relative to the baseline
file, and the trimmed text of the finding's line. Matching is a multiset, so
two identical lines need two entries. Entries for files that were not linted
in the current run are left unchanged.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import posixpath
import tempfile
from typing import cast

from blinter.engine.lines_cache import get_cached_lines
from blinter.io.encoding import read_file_with_encoding
from blinter.logging_config import logger
from blinter.models import LintIssue, ProcessingResults

_ENTRY_FIELDS = frozenset({"code", "file", "text"})
_FindingKey = tuple[str, str, str]


@dataclass(frozen=True)
class BaselineEntry:
    """One accepted finding."""

    code: str
    file: str
    text: str

    def key(self) -> _FindingKey:
        """Return the multiset key used to match this entry to a finding."""
        return (self.code.upper(), _path_key(self.file), self.text)


@dataclass(frozen=True)
class BaselineDiff:
    """Findings split by a baseline, plus entries that no longer match."""

    kept: tuple[LintIssue, ...]
    matched: tuple[LintIssue, ...]
    stale: tuple[BaselineEntry, ...]


def _path_key(relative_posix: str) -> str:
    """Normalize a stored relative path for comparison on this operating system."""
    normalized = posixpath.normpath(relative_posix.replace("\\", "/"))
    if os.name == "nt":
        return normalized.casefold()
    return normalized


def _is_absolute_baseline_file(value: str) -> bool:
    """Return True when a baseline file field is not a relative path."""
    slashed = value.replace("\\", "/")
    if slashed.startswith("/"):
        return True
    return len(slashed) >= 2 and slashed[1] == ":"


def _normalize_stored_file(file_value: str, location: str) -> str:
    """Return a POSIX relative path, or raise when the field is absolute."""
    stripped = file_value.strip()
    if not stripped or _is_absolute_baseline_file(stripped):
        raise ValueError(f"{location} field 'file' must be a relative path")
    normalized = posixpath.normpath(stripped.replace("\\", "/"))
    if normalized in {".", ""} or _is_absolute_baseline_file(normalized):
        raise ValueError(f"{location} field 'file' must be a relative path")
    return normalized


def relative_batch_path(file_path: str, baseline_dir: Path) -> str:
    """Return ``file_path`` relative to the baseline file's directory.

    Separators are POSIX so one baseline works on Windows and on POSIX.
    A file outside that directory is stored with a ``../`` prefix.
    """
    resolved_file = Path(file_path).resolve()
    resolved_dir = baseline_dir.resolve()
    try:
        relative = resolved_file.relative_to(resolved_dir)
    except ValueError:
        relative = _relative_outside(resolved_file, resolved_dir, file_path)
    posix = posixpath.normpath(relative.as_posix())
    logger.debug("Baseline relative path for %s is %s", file_path, posix)
    return posix


def _relative_outside(resolved_file: Path, resolved_dir: Path, file_path: str) -> Path:
    """Return a relative path when the file is not under the baseline directory."""
    try:
        relative_text = os.path.relpath(resolved_file, resolved_dir)
    except ValueError as error:
        raise ValueError(
            f"Cannot express '{file_path}' relative to baseline directory "
            f"'{resolved_dir}'"
        ) from error
    return Path(relative_text)


def _json_value(path: Path, text: str) -> object:
    """Parse baseline JSON into a value the caller narrows."""
    try:
        # json.loads is typed as Any. The cast is the validation boundary.
        loaded = cast(object, json.loads(text))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Baseline file '{path}' is not valid JSON: {error.msg}"
        ) from error
    return loaded


def _as_list(value: object, location: str) -> list[object]:
    """Return a JSON list, or raise when the top-level value is not a list."""
    if not isinstance(value, list):
        raise ValueError(f"{location} must contain a JSON list of entries")
    return list(cast(list[object], value))


def _as_mapping(value: object, location: str) -> dict[str, object]:
    """Return a string-keyed object, or raise when the entry is not an object."""
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    mapping: dict[str, object] = {}
    raw = cast(dict[object, object], value)
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{location} must use string keys")
        mapping[key] = item
    return mapping


def _require_text(mapping: dict[str, object], location: str) -> dict[str, str]:
    """Return the three entry strings, rejecting missing, extra, or blank fields."""
    unknown = set(mapping) - _ENTRY_FIELDS
    missing = _ENTRY_FIELDS - set(mapping)
    if unknown or missing:
        raise ValueError(f"{location} must have exactly the keys code, file, and text")
    texts: dict[str, str] = {}
    for key in ("code", "file", "text"):
        value = mapping[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{location} field '{key}' must be a non-empty string")
        texts[key] = value.strip()
    return texts


def _parse_entry(path: Path, index: int, item: object) -> BaselineEntry:
    """Validate one baseline object."""
    location = f"Baseline file '{path}' entry {index}"
    texts = _require_text(_as_mapping(item, location), location)
    return BaselineEntry(
        code=texts["code"].upper(),
        file=_normalize_stored_file(texts["file"], location),
        text=texts["text"],
    )


def load_baseline(path: Path) -> list[BaselineEntry]:
    """Load and validate a baseline file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file cannot be read or is not a list of entries.
    """
    logger.info("Loading baseline %s", path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("Baseline file not found: %s", path)
        raise
    except OSError as error:
        raise ValueError(f"Cannot read baseline file '{path}': {error}") from error
    payload = _as_list(_json_value(path, text), f"Baseline file '{path}'")
    entries = [_parse_entry(path, index, item) for index, item in enumerate(payload)]
    logger.info("Loaded %d baseline entries from %s", len(entries), path)
    return entries


def _lines_for_issue(
    issue: LintIssue,
    lines_cache: dict[Path, list[str]],
    read_cache: dict[str, list[str]],
) -> list[str]:
    """Return the source lines for a finding, using the lint cache first."""
    if issue.file_path is None:
        raise ValueError(
            f"Finding {issue.rule.code} on line {issue.line_number} has no file path"
        )
    cached = read_cache.get(issue.file_path)
    if cached is not None:
        return cached
    stored = get_cached_lines(lines_cache, Path(issue.file_path))
    if stored is None:
        logger.debug("Baseline cache miss for %s; reading the file", issue.file_path)
        stored, _encoding = read_file_with_encoding(issue.file_path)
    read_cache[issue.file_path] = stored
    return stored


def _trimmed_line(
    issue: LintIssue,
    lines_cache: dict[Path, list[str]],
    read_cache: dict[str, list[str]],
) -> str:
    """Return the trimmed source line a finding points at."""
    lines = _lines_for_issue(issue, lines_cache, read_cache)
    index = issue.line_number - 1
    if index < 0 or index >= len(lines):
        raise ValueError(
            f"Finding {issue.rule.code} on line {issue.line_number} of "
            f"'{issue.file_path}' does not match a source line"
        )
    return lines[index].strip()


def _finding_key(
    issue: LintIssue,
    baseline_dir: Path,
    lines_cache: dict[Path, list[str]],
    read_cache: dict[str, list[str]],
) -> _FindingKey:
    """Return the multiset key for one finding."""
    if issue.file_path is None:
        raise ValueError(
            f"Finding {issue.rule.code} on line {issue.line_number} has no file path"
        )
    return (
        issue.rule.code.upper(),
        _path_key(relative_batch_path(issue.file_path, baseline_dir)),
        _trimmed_line(issue, lines_cache, read_cache),
    )


def _linted_path_keys(results: ProcessingResults, baseline_dir: Path) -> set[str]:
    """Return comparison keys for every file linted in this run."""
    keys: set[str] = set()
    paths = [file_path for file_path, _parent in results.processed_file_paths]
    paths.extend(results.file_results)
    for file_path in paths:
        keys.add(_path_key(relative_batch_path(file_path, baseline_dir)))
    return keys


def entries_from_findings(
    findings: list[LintIssue],
    baseline_dir: Path,
    lines_cache: dict[Path, list[str]],
) -> list[BaselineEntry]:
    """Build baseline entries from findings, one entry per finding."""
    read_cache: dict[str, list[str]] = {}
    entries: list[BaselineEntry] = []
    for issue in findings:
        if issue.file_path is None:
            raise ValueError(
                f"Finding {issue.rule.code} on line {issue.line_number} has no file path"
            )
        text = _trimmed_line(issue, lines_cache, read_cache)
        if not text:
            raise ValueError(
                f"Finding {issue.rule.code} on line {issue.line_number} of "
                f"'{issue.file_path}' is on a blank line and cannot be baselined"
            )
        entries.append(
            BaselineEntry(
                code=issue.rule.code.upper(),
                file=relative_batch_path(issue.file_path, baseline_dir),
                text=text,
            )
        )
    logger.info("Built %d baseline entries from current findings", len(entries))
    return entries


def apply_baseline(
    results: ProcessingResults,
    entries: list[BaselineEntry],
    baseline_dir: Path,
    lines_cache: dict[Path, list[str]],
) -> BaselineDiff:
    """Hide accepted findings and report entries that no longer match.

    Only entries whose file was linted in this run can be stale. Entries for
    other files are ignored.
    """
    logger.info(
        "Applying %d baseline entries to %d findings",
        len(entries),
        len(results.all_issues),
    )
    linted = _linted_path_keys(results, baseline_dir)
    read_cache: dict[str, list[str]] = {}
    available: Counter[_FindingKey] = Counter(entry.key() for entry in entries)
    kept: list[LintIssue] = []
    matched: list[LintIssue] = []
    for issue in results.all_issues:
        key = _finding_key(issue, baseline_dir, lines_cache, read_cache)
        if available[key] > 0:
            available[key] -= 1
            matched.append(issue)
            logger.debug("Baseline accepted %s in %s", issue.rule.code, issue.file_path)
            continue
        kept.append(issue)

    matched_counts: Counter[_FindingKey] = Counter(
        _finding_key(issue, baseline_dir, lines_cache, read_cache) for issue in matched
    )
    consumed: Counter[_FindingKey] = Counter()
    stale: list[BaselineEntry] = []
    for entry in entries:
        key = entry.key()
        if _path_key(entry.file) not in linted:
            logger.debug("Baseline entry for %s is outside this scan", entry.file)
            continue
        if consumed[key] < matched_counts[key]:
            consumed[key] += 1
            continue
        stale.append(entry)
        logger.info("Stale baseline entry %s in %s", entry.code, entry.file)
    logger.info(
        "Baseline kept %d findings, accepted %d, and found %d stale entries",
        len(kept),
        len(matched),
        len(stale),
    )
    return BaselineDiff(tuple(kept), tuple(matched), tuple(stale))


def _write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` via a temporary file in the same directory."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove temporary baseline file %s", temporary_path
            )
        raise


def _entry_sort_key(entry: BaselineEntry) -> tuple[str, str, str]:
    """Sort baseline entries by file, rule code, then line text."""
    return (entry.file, entry.code, entry.text)


def write_baseline(path: Path, entries: list[BaselineEntry]) -> None:
    """Write entries as sorted JSON, replacing ``path`` atomically."""
    ordered = sorted(entries, key=_entry_sort_key)
    payload = [
        {"code": entry.code, "file": entry.file, "text": entry.text}
        for entry in ordered
    ]
    _write_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    logger.info("Wrote %d baseline entries to %s", len(ordered), path)


def update_baseline(path: Path, results: ProcessingResults) -> int:
    """Rewrite ``path`` from current findings.

    Entries whose files were not linted in this run are kept. A missing file
    is created. Returns the number of entries written.
    """
    baseline_dir = path.resolve().parent
    existing: list[BaselineEntry] = []
    if path.is_file():
        existing = load_baseline(path)
    elif path.exists():
        raise ValueError(f"Baseline path '{path}' is not a file")
    linted = _linted_path_keys(results, baseline_dir)
    preserved = [entry for entry in existing if _path_key(entry.file) not in linted]
    current = entries_from_findings(
        list(results.all_issues),
        baseline_dir,
        results.lines_cache,
    )
    combined = current + preserved
    write_baseline(path, combined)
    logger.info(
        "Updated baseline %s with %d current and %d preserved entries",
        path,
        len(current),
        len(preserved),
    )
    return len(combined)
