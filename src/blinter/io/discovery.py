"""Batch file discovery in directories and paths."""

import os
from pathlib import Path
from typing import List, Optional, Union

from blinter.constants import MAX_SCAN_FILES
from blinter.logging_config import logger

_BATCH_SUFFIXES = frozenset({".bat", ".cmd"})
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_unc_path(path: Path | str) -> bool:
    """Return True for a UNC path, including ``\\\\?\\UNC\\`` forms.

    ``Path.resolve`` on Windows calls ``GetFinalPathNameByHandle``, which opens
    the path. Callers must reject these strings before resolve or exists.
    """
    text = os.fspath(path).replace("/", "\\")
    if text.startswith("\\\\?\\UNC\\") or text.startswith("\\\\.\\UNC\\"):
        return True
    if text.startswith("\\\\?\\") or text.startswith("\\\\.\\"):
        return False
    return text.startswith("\\\\")


def _is_reparse_directory(path: Path) -> bool:
    """Return True for a symlink, junction, or other directory reparse point."""
    try:
        if path.is_symlink():
            return True
        junction_attr: object = getattr(path, "is_junction", None)
        junction_result: object = False
        if callable(junction_attr):
            junction_result = junction_attr()
        if junction_result is True:
            return True
        stat_result = path.lstat()
    except OSError:
        return True
    attributes_obj: object = getattr(stat_result, "st_file_attributes", 0)
    if isinstance(attributes_obj, int) and not isinstance(attributes_obj, bool):
        return bool(attributes_obj & _FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _resolved_is_under_root(resolved: Path, root_resolved: Path) -> bool:
    """Return True when resolved is inside root_resolved."""
    try:
        resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def is_path_under_root(path: Path, root: Path) -> bool:
    """Return True when path resolves inside root without symlink escape."""
    try:
        if is_unc_path(path) or is_unc_path(root):
            raise ValueError("UNC path")
        root_resolved = root.resolve()
        candidate = path if path.is_absolute() else Path.cwd() / path
        resolved = candidate.resolve()

        if not _resolved_is_under_root(resolved, root_resolved):
            return False

        try:
            relative = resolved.relative_to(root_resolved)
        except ValueError:
            return False

        # Only inspect symlinks on the path from root to the candidate. Ancestor
        # symlinks (e.g. macOS /var -> /private/var) must not fail containment.
        current = root_resolved
        for part in relative.parts:
            next_path = current / part
            if next_path.is_symlink():
                link_target = next_path.readlink()
                resolved_target = (
                    link_target
                    if link_target.is_absolute()
                    else (next_path.parent / link_target)
                )
                try:
                    resolved_target = resolved_target.resolve()
                except OSError:
                    return False
                if not _resolved_is_under_root(resolved_target, root_resolved):
                    return False
            current = next_path

        return True
    except (OSError, ValueError) as path_error:
        logger.debug("Path %s is not under root %s: %s", path, root, path_error)
        return False


def find_batch_files(
    path: Union[str, Path],
    recursive: bool = True,
    root: Optional[Path] = None,
    max_scan_files: int = MAX_SCAN_FILES,
) -> List[Path]:
    """
    Find all batch files (.bat and .cmd) in a directory or return single file.

    Args:
        path: Path to file or directory to search
        recursive: Whether to search subdirectories recursively (default: True)
        root: When set, only return files that resolve inside this directory
        max_scan_files: Maximum batch files returned from a directory scan (default: 1000)

    Returns:
        List of Path objects representing batch files found

    Raises:
        FileNotFoundError: If the path doesn't exist
        ValueError: If path is not a file or directory
    """
    path_obj = Path(path)

    if not path_obj.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path_obj.is_file():
        # Return single file if it's a batch file
        if path_obj.suffix.lower() in _BATCH_SUFFIXES:
            if root is not None and not is_path_under_root(path_obj, root):
                return []
            return [path_obj]
        raise ValueError(f"File '{path}' is not a batch file (.bat or .cmd)")

    if path_obj.is_dir():
        batch_files = _collect_batch_files(path_obj, recursive=recursive)

        if root is not None:
            batch_files = [
                batch_file
                for batch_file in batch_files
                if is_path_under_root(batch_file, root)
            ]

        if len(batch_files) > max_scan_files:
            raise ValueError(
                f"Directory scan found {len(batch_files)} batch files, "
                f"exceeding the limit of {max_scan_files}. "
                "Use a narrower path, disable recursive scanning, "
                "or increase max_scan_files in blinter.ini."
            )

        # Sort for consistent output
        batch_files.sort()
        return batch_files

    raise ValueError(f"Path '{path}' is neither a file nor a directory")


def _is_batch_file(path: Path) -> bool:
    """Return True for a real batch file, not a symlink to one."""
    if path.suffix.lower() not in _BATCH_SUFFIXES:
        return False
    try:
        if path.is_symlink():
            return False
    except OSError:
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def _collect_batch_files(root: Path, *, recursive: bool) -> List[Path]:
    """Return batch files under root without following symlinks or junctions."""
    batch_files: List[Path] = []
    if not recursive:
        try:
            children = list(root.iterdir())
        except OSError as scan_error:
            logger.debug("Cannot list %s: %s", root, scan_error)
            return batch_files
        for candidate in children:
            if _is_reparse_directory(candidate):
                continue
            if _is_batch_file(candidate):
                batch_files.append(candidate)
        return batch_files

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept: List[str] = []
        for name in dirnames:
            child = current / name
            if _is_reparse_directory(child):
                logger.debug("Skipping reparse directory %s", child)
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            candidate = current / name
            if _is_batch_file(candidate):
                batch_files.append(candidate)
    return batch_files
