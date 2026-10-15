"""CALL dependency graph and cross-script variable collection."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from blinter.constants import MAX_FOLLOW_CALL_DEPTH, MAX_FOLLOW_CALL_FILES
from blinter.engine.lines_cache import get_cached_lines
from blinter.io.discovery import is_path_under_root
from blinter.io.encoding import _validate_and_read_file
from blinter.logging_config import logger
from blinter.parsing.structure import _collect_set_variables

_CALL_SCRIPT_PATTERN = re.compile(
    r'\bcall\s+(?:"([^"]+\.(?:bat|cmd))"|(\S+\.(?:bat|cmd)))',
    re.IGNORECASE,
)


@dataclass
class _CallLineContext:
    """Shared path context for resolving CALL statements on a single line."""

    batch_dir: Path
    batch_file_resolved: Path
    scan_root: Optional[str]
    lines_cache: Optional[Dict[Path, List[str]]]
    script_vars_cache: Dict[Path, Set[str]]


def _is_within_scan_root(path: Path, scan_root: Optional[str]) -> bool:
    """Return True when scan_root is unset or path is inside it."""
    if scan_root is None:
        return True
    return is_path_under_root(path, Path(scan_root))


def _read_batch_lines(
    path: Path,
    lines: Optional[List[str]] = None,
    *,
    warn_on_read_failure: bool = False,
) -> Optional[List[str]]:
    """Read batch file lines using encoding detection."""
    if lines is not None:
        return lines
    try:
        file_lines, _encoding, _ending, _overlong = _validate_and_read_file(str(path))
        return file_lines
    except (OSError, ValueError) as read_error:
        if warn_on_read_failure:
            logger.warning("Could not read batch file %s: %s", path, read_error)
        else:
            logger.debug("Could not read batch file %s: %s", path, read_error)
        return None


def _extract_called_scripts(
    batch_file: Path,
    scan_root: Optional[str] = None,
    lines: Optional[List[str]] = None,
) -> List[Path]:
    """
    Extract paths to scripts called by CALL statements in a batch file.

    Args:
        batch_file: Path to the batch file to analyze
        scan_root: Optional root directory; paths outside it are skipped

    Returns:
        List of Path objects for called scripts that exist
    """
    called_scripts: List[Path] = []
    seen_scripts: Set[Path] = set()
    batch_dir = batch_file.parent

    lines = _read_batch_lines(batch_file, lines=lines)
    if lines is None:
        return called_scripts

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("rem ") or stripped.startswith("::"):
            continue

        call_match = _CALL_SCRIPT_PATTERN.search(line)

        if not call_match:
            continue

        script_path_str = call_match.group(1) or call_match.group(2)
        script_path = _resolve_script_path(
            script_path_str, batch_dir, scan_root=scan_root
        )
        if script_path is None:
            continue

        try:
            if not (script_path.exists() and script_path.is_file()):
                continue
            resolved_script = script_path.resolve()
            if resolved_script == batch_file.resolve():
                continue
            if resolved_script in seen_scripts:
                continue
            seen_scripts.add(resolved_script)
            called_scripts.append(script_path)
        except (ValueError, OSError) as path_error:
            logger.debug("Skipping invalid called script path: %s", path_error)
            continue

    return called_scripts


def _warn_call_file_limit() -> None:
    """Log when CALL dependency traversal hits the configured file limit."""
    logger.warning(
        "CALL dependency file limit (%d) reached; stopping traversal",
        MAX_FOLLOW_CALL_FILES,
    )


def _resolve_script_path(
    script_path_str: str,
    batch_dir: Path,
    scan_root: Optional[str] = None,
) -> Optional[Path]:
    """
    Resolve a script path from a CALL statement.

    Args:
        script_path_str: The script path string from the CALL statement
        batch_dir: The directory of the batch file containing the CALL
        scan_root: Optional root directory; absolute paths outside it return None

    Returns:
        Resolved Path object, or None if resolution fails or path is outside scan_root
    """
    script_path_str = script_path_str.replace("\\", "/")
    if "%~dp0" in script_path_str:
        script_path_str = script_path_str.replace("%~dp0", "")
        resolved = batch_dir / script_path_str
    elif "%~d0" in script_path_str:
        script_path_str = script_path_str.replace("%~d0", str(batch_dir.drive))
        resolved = Path(script_path_str)
    else:
        script_path = Path(script_path_str)
        if not script_path.is_absolute():
            resolved = batch_dir / script_path_str
        else:
            resolved = script_path

    try:
        if scan_root is not None and not _is_within_scan_root(resolved, scan_root):
            logger.debug("Skipping script path outside scan root: %s", resolved)
            return None
    except (ValueError, OSError) as path_error:
        logger.debug("Skipping invalid script path: %s", path_error)
        return None

    return resolved


def _try_add_dependency(
    script_path: Path,
    batch_file_resolved: Path,
    deps: Set[Path],
    scan_root: Optional[str] = None,
) -> None:
    """
    Try to add a dependency if the script path is valid.

    Args:
        script_path: Path to the script file
        batch_file_resolved: Resolved path of the current batch file
        deps: Set to add the dependency to
        scan_root: Optional root directory; paths outside it are skipped
    """
    try:
        if not (script_path.exists() and script_path.is_file()):
            return
        resolved_script = script_path.resolve()
        if resolved_script == batch_file_resolved:
            return
        if not _is_within_scan_root(resolved_script, scan_root):
            logger.debug("Skipping dependency outside scan root: %s", resolved_script)
            return
        deps.add(resolved_script)
    except (ValueError, OSError) as dependency_error:
        logger.debug("Skipping dependency %s: %s", script_path, dependency_error)


def _extract_direct_dependencies(
    batch_file: Path,
    batch_file_resolved: Path,
    scan_root: Optional[str] = None,
    lines: Optional[List[str]] = None,
    lines_cache: Optional[Dict[Path, List[str]]] = None,
) -> Set[Path]:
    """
    Extract direct dependencies from a batch file by parsing CALL statements.

    Args:
        batch_file: Path to the batch file
        batch_file_resolved: Resolved path of the batch file
        scan_root: Optional root directory; paths outside it are skipped

    Returns:
        Set of resolved Path objects that this file directly depends on
    """
    deps: Set[Path] = set()
    cached_lines = lines
    if cached_lines is None:
        cached_lines = get_cached_lines(lines_cache, batch_file_resolved)
    file_lines = _read_batch_lines(batch_file, lines=cached_lines)
    if file_lines is None:
        return deps

    batch_dir = batch_file.parent
    for line in file_lines:
        stripped = line.strip().lower()
        if stripped.startswith("rem ") or stripped.startswith("::"):
            continue

        call_match = _CALL_SCRIPT_PATTERN.search(line)

        if not call_match:
            continue

        script_path_str = call_match.group(1) or call_match.group(2)
        script_path = _resolve_script_path(
            script_path_str, batch_dir, scan_root=scan_root
        )

        if script_path:
            _try_add_dependency(
                script_path, batch_file_resolved, deps, scan_root=scan_root
            )

    return deps


def _build_call_dependency_graph(
    batch_files: List[Path],
    scan_root: Optional[str] = None,
    lines_cache: Optional[Dict[Path, List[str]]] = None,
) -> Dict[Path, Set[Path]]:
    """
    Build a dependency graph showing which batch files call which other files.

    This function scans all provided batch files and builds a directed graph of
    CALL relationships. The graph includes transitive dependencies, so if fileA
    calls fileB and fileB calls fileC, then fileA's dependencies include both
    fileB and fileC.

    Args:
        batch_files: List of Path objects representing batch files to analyze
        scan_root: Optional root directory; paths outside it are skipped

    Returns:
        Dictionary mapping each file Path to a Set of Path objects it depends on
        (directly or transitively via CALL statements).
    """
    direct_deps: Dict[Path, Set[Path]] = {}

    for batch_file in batch_files:
        batch_file_resolved = batch_file.resolve()
        direct_deps[batch_file_resolved] = _extract_direct_dependencies(
            batch_file,
            batch_file_resolved,
            scan_root=scan_root,
            lines_cache=lines_cache,
        )

    transitive_deps: Dict[Path, Set[Path]] = {}
    memo: Dict[Path, Set[Path]] = {}

    def _direct_deps_for(file_path: Path) -> Set[Path]:
        """Return direct CALL dependencies, computing them lazily when needed."""
        if file_path not in direct_deps:
            direct_deps[file_path] = _extract_direct_dependencies(
                file_path,
                file_path,
                scan_root=scan_root,
                lines_cache=lines_cache,
            )
        return direct_deps[file_path]

    def get_all_deps(file_path: Path, visiting: Set[Path], depth: int = 0) -> Set[Path]:
        """Recursively get all dependencies (direct and transitive)."""
        if file_path in memo:
            return set(memo[file_path])
        if file_path in visiting:
            logger.warning(
                "Circular CALL dependency detected at %s; stopping traversal",
                file_path,
            )
            return set()
        if depth > MAX_FOLLOW_CALL_DEPTH:
            logger.warning(
                "CALL dependency depth exceeded %d at %s; stopping traversal",
                MAX_FOLLOW_CALL_DEPTH,
                file_path,
            )
            return set()

        visiting.add(file_path)
        all_deps: Set[Path] = set()

        for dep in sorted(_direct_deps_for(file_path), key=str):
            all_deps.add(dep)
            if len(all_deps) >= MAX_FOLLOW_CALL_FILES:
                _warn_call_file_limit()
                break
            if depth + 1 <= MAX_FOLLOW_CALL_DEPTH:
                all_deps.update(get_all_deps(dep, visiting, depth + 1))
                if len(all_deps) >= MAX_FOLLOW_CALL_FILES:
                    _warn_call_file_limit()
                    all_deps = set(sorted(all_deps, key=str)[:MAX_FOLLOW_CALL_FILES])
                    break

        visiting.remove(file_path)
        memo[file_path] = all_deps
        return all_deps

    for batch_file in batch_files:
        batch_file_resolved = batch_file.resolve()
        transitive_deps[batch_file_resolved] = get_all_deps(batch_file_resolved, set())

    return transitive_deps


def _collect_vars_from_dependencies(
    batch_file_resolved: Path,
    dependency_graph: Dict[Path, Set[Path]],
    scan_root: Optional[str] = None,
    lines_cache: Optional[Dict[Path, List[str]]] = None,
) -> Dict[int, Set[str]]:
    """
    Collect variables from all dependencies in the dependency graph.

    Args:
        batch_file_resolved: Resolved path to the batch file
        dependency_graph: Pre-built graph of file dependencies from folder scan
        scan_root: Optional root directory; paths outside it are skipped

    Returns:
        Dictionary with {0: all_vars} where all_vars includes variables from all
        dependencies in the graph.
    """
    all_vars: Set[str] = set()
    dependencies = dependency_graph.get(batch_file_resolved, set())
    files_collected = 0

    for dep_file in dependencies:
        if files_collected >= MAX_FOLLOW_CALL_FILES:
            logger.warning(
                "CALL dependency file limit (%d) reached while collecting variables",
                MAX_FOLLOW_CALL_FILES,
            )
            break
        if not _is_within_scan_root(dep_file, scan_root):
            logger.debug("Skipping dependency outside scan root: %s", dep_file)
            continue

        cached_lines = get_cached_lines(lines_cache, dep_file)
        called_lines = _read_batch_lines(
            dep_file, lines=cached_lines, warn_on_read_failure=True
        )
        if called_lines is None:
            continue

        dep_vars = _collect_set_variables(called_lines)
        dep_vars.discard("__DYNAMIC_VARS__")
        all_vars.update(dep_vars)
        files_collected += 1

    return {0: all_vars} if all_vars else {}


@dataclass
class _TransitiveVarContext:
    """Shared state for transitive SET variable collection across CALL targets."""

    batch_file_resolved: Path
    scan_root: Optional[str]
    lines_cache: Optional[Dict[Path, List[str]]]
    visiting: Set[Path]
    files_read: Set[Path]


def _var_collect_blocked(
    resolved_script: Path,
    depth: int,
    ctx: _TransitiveVarContext,
) -> bool:
    """Return True when variable collection must not proceed for resolved_script."""
    if resolved_script == ctx.batch_file_resolved:
        return True
    if not _is_within_scan_root(resolved_script, ctx.scan_root):
        logger.debug("Skipping called script outside scan root: %s", resolved_script)
        return True
    if depth > MAX_FOLLOW_CALL_DEPTH:
        logger.warning(
            "CALL dependency depth exceeded %d at %s; stopping variable collection",
            MAX_FOLLOW_CALL_DEPTH,
            resolved_script,
        )
        return True
    if resolved_script in ctx.visiting:
        logger.warning(
            "Circular CALL dependency detected at %s; stopping variable collection",
            resolved_script,
        )
        return True
    if len(ctx.files_read) >= MAX_FOLLOW_CALL_FILES:
        _warn_call_file_limit()
        return True
    return False


def _collect_script_vars_deep(
    script_path: Path,
    depth: int,
    ctx: _TransitiveVarContext,
) -> Set[str]:
    """Collect SET variables from script_path and reachable callees."""
    if not (script_path.exists() and script_path.is_file()):
        logger.warning("Could not read called script %s: file not found", script_path)
        return set()

    try:
        resolved_script = script_path.resolve()
    except (ValueError, OSError) as resolve_error:
        logger.debug(
            "Could not resolve called script path %s: %s",
            script_path,
            resolve_error,
        )
        return set()

    if _var_collect_blocked(resolved_script, depth, ctx):
        return set()

    ctx.visiting.add(resolved_script)
    ctx.files_read.add(resolved_script)

    cached_lines = get_cached_lines(ctx.lines_cache, resolved_script)
    called_lines = _read_batch_lines(
        script_path, lines=cached_lines, warn_on_read_failure=True
    )
    called_vars: Set[str] = set()
    if called_lines is not None:
        called_vars = _collect_set_variables(called_lines)
        called_vars.discard("__DYNAMIC_VARS__")

        for nested_script in _extract_called_scripts(
            script_path,
            scan_root=ctx.scan_root,
            lines=called_lines,
        ):
            if len(ctx.files_read) >= MAX_FOLLOW_CALL_FILES:
                _warn_call_file_limit()
                break
            called_vars.update(
                _collect_script_vars_deep(
                    nested_script,
                    depth + 1,
                    ctx,
                )
            )

    ctx.visiting.discard(resolved_script)
    return called_vars


def _collect_vars_from_script(
    script_path: Path,
    batch_file_resolved: Path,
    scan_root: Optional[str] = None,
    lines_cache: Optional[Dict[Path, List[str]]] = None,
    script_vars_cache: Optional[Dict[Path, Set[str]]] = None,
) -> Set[str]:
    """
    Collect variables from a called script and its reachable callees.

    Transitive collection respects ``MAX_FOLLOW_CALL_DEPTH`` and
    ``MAX_FOLLOW_CALL_FILES`` using the same limits as CLI follow-call traversal.

    Args:
        script_path: Path to the called script
        batch_file_resolved: Resolved path to the calling batch file
        scan_root: Optional root directory; paths outside it are skipped
        script_vars_cache: Optional per-lint cache of resolved script variables

    Returns:
        Set of variable names defined in the script and its reachable callees
    """
    try:
        resolved_script = script_path.resolve()
    except (ValueError, OSError) as resolve_error:
        logger.debug(
            "Could not resolve called script path %s: %s",
            script_path,
            resolve_error,
        )
        return set()

    if script_vars_cache is not None and resolved_script in script_vars_cache:
        return set(script_vars_cache[resolved_script])

    ctx = _TransitiveVarContext(
        batch_file_resolved=batch_file_resolved,
        scan_root=scan_root,
        lines_cache=lines_cache,
        visiting=set(),
        files_read=set(),
    )
    collected = _collect_script_vars_deep(script_path, 0, ctx)
    if script_vars_cache is not None:
        script_vars_cache[resolved_script] = set(collected)
    return collected


def _vars_from_call_line(
    line: str,
    _line_num: int,
    ctx: _CallLineContext,
) -> Set[str]:
    """Return variables defined by all resolvable CALL targets on a line."""
    stripped = line.strip().lower()
    if stripped.startswith("rem ") or stripped.startswith("::"):
        return set()

    merged_vars: Set[str] = set()
    for call_match in _CALL_SCRIPT_PATTERN.finditer(line):
        script_path_str = call_match.group(1) or call_match.group(2)
        script_path = _resolve_script_path(
            script_path_str, ctx.batch_dir, scan_root=ctx.scan_root
        )
        if script_path is None:
            continue

        called_vars = _collect_vars_from_script(
            script_path,
            ctx.batch_file_resolved,
            scan_root=ctx.scan_root,
            lines_cache=ctx.lines_cache,
            script_vars_cache=ctx.script_vars_cache,
        )
        merged_vars.update(called_vars)

    return merged_vars


def _collect_called_vars(
    batch_file: Path,
    scan_root: Optional[str] = None,
    lines: Optional[List[str]] = None,
    lines_cache: Optional[Dict[Path, List[str]]] = None,
) -> Dict[int, Set[str]]:
    """
    For each CALL statement in the batch file, collect variables from the called script.

    This function implements position-aware variable tracking: variables from called scripts
    are only considered "defined" for lines AFTER the CALL statement that invokes them.

    Args:
        batch_file: Path to the batch file to analyze
        scan_root: Optional root directory; paths outside it are skipped

    Returns:
        Dictionary mapping line numbers to sets of variables available after that line.
        For example, if line 10 has a CALL to a script that defines VAR1 and VAR2,
        the returned dict will have {10: {'VAR1', 'VAR2'}}.
    """
    batch_file_resolved = batch_file.resolve()

    called_vars_by_line: Dict[int, Set[str]] = {}
    script_vars_cache: Dict[Path, Set[str]] = {}
    call_ctx = _CallLineContext(
        batch_dir=batch_file.parent,
        batch_file_resolved=batch_file_resolved,
        scan_root=scan_root,
        lines_cache=lines_cache,
        script_vars_cache=script_vars_cache,
    )

    file_lines = _read_batch_lines(batch_file, lines=lines)
    if file_lines is None:
        return called_vars_by_line

    for line_num, line in enumerate(file_lines, start=1):
        call_vars = _vars_from_call_line(line, line_num, call_ctx)
        if call_vars:
            called_vars_by_line.setdefault(line_num, set()).update(call_vars)

    return called_vars_by_line
