"""FOR loop scope tracking and case-sensitivity checks (W059)."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List

from blinter.models import LintIssue
from blinter.parsing.structure import _paren_depth_deltas
from blinter.rules.registry import RULES

_FOR_HEADER_RE = re.compile(
    r"^\s*for\s+(?:/[lfdr]\s+.*?)?%%([a-zA-Z])\b",
    re.IGNORECASE,
)
_FOR_REF_RE = re.compile(r"%%(?:~[fdpnxsatz$]*)?([a-zA-Z])")
_DO_SPLIT_RE = re.compile(r"\bdo\b", re.IGNORECASE)


@dataclass(frozen=True)
class ForScope:
    """A FOR loop body region with its declared variable letter (case-preserved)."""

    var: str
    header_line: int
    start_line: int
    end_line: int


def _parse_for_header(line: str) -> str | None:
    """Return the declared FOR loop letter from a FOR header line, or None."""
    match = _FOR_HEADER_RE.match(line)
    if not match:
        return None
    return str(match.group(1))


def _line_after_do(line: str) -> str:
    """Return the portion of a line after the DO keyword, if present."""
    match = _DO_SPLIT_RE.search(line)
    if not match:
        return ""
    return line[match.end() :]


def _find_block_end_line(deltas: List[int], open_line_index: int) -> int:
    """Find the closing line of a parenthesized block opened on open_line_index."""
    depth = 0
    for index in range(open_line_index, len(deltas)):
        depth += deltas[index]
        if index > open_line_index and depth <= 0:
            return index + 1
    return len(deltas)


def _build_for_scopes(lines: List[str]) -> List[ForScope]:
    """Build FOR loop scopes with exact variable letters and body line ranges."""
    scopes: List[ForScope] = []
    deltas = _paren_depth_deltas(lines)
    for line_index, line in enumerate(lines):
        declared = _parse_for_header(line)
        if declared is None:
            continue
        header_line = line_index + 1
        after_do = _line_after_do(line)
        block_open = re.search(r"\(\s*$", after_do)
        if block_open is not None:
            start_line = header_line
            end_line = _find_block_end_line(deltas, line_index)
            scopes.append(
                ForScope(
                    var=declared,
                    header_line=header_line,
                    start_line=start_line,
                    end_line=end_line,
                )
            )
            continue
        if _DO_SPLIT_RE.search(line):
            scopes.append(
                ForScope(
                    var=declared,
                    header_line=header_line,
                    start_line=header_line,
                    end_line=header_line,
                )
            )
    return scopes


def _active_scopes_at(scopes: List[ForScope], line_num: int) -> List[ForScope]:
    """Return scopes containing line_num, outer-to-inner order."""
    return [scope for scope in scopes if scope.start_line <= line_num <= scope.end_line]


def _scan_line_for_case_mismatch(
    line: str,
    line_num: int,
    active_scopes: List[ForScope],
) -> List[LintIssue]:
    """Flag %% references that match an active scope only case-insensitively."""
    if any(line_num == scope.header_line for scope in active_scopes):
        scan_text = _line_after_do(line)
    else:
        scan_text = line
    if not scan_text.strip():
        return []

    issues: List[LintIssue] = []
    for match in _FOR_REF_RE.finditer(scan_text):
        letter = str(match.group(1))
        if any(active.var == letter for active in active_scopes):
            continue
        declared = next(
            (
                active.var
                for active in active_scopes
                if active.var.lower() == letter.lower()
            ),
            None,
        )
        if declared is None:
            continue
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["W059"],
                context=(
                    f"FOR variable %%{letter} does not match declared "
                    f"%%{declared}; FOR loop variables are case-sensitive"
                ),
            )
        )
    return issues


def _check_for_var_case_mismatch(lines: List[str]) -> List[LintIssue]:
    """Warn when a FOR loop body uses the wrong case for its loop variable (W059)."""
    scopes = _build_for_scopes(lines)
    if not scopes:
        return []
    issues: List[LintIssue] = []
    seen: set[tuple[int, str]] = set()
    for line_num, line in enumerate(lines, start=1):
        active = _active_scopes_at(scopes, line_num)
        if not active:
            continue
        for issue in _scan_line_for_case_mismatch(line, line_num, active):
            key = (issue.line_number, issue.context or "")
            if key in seen:
                continue
            seen.add(key)
            issues.append(issue)
    return issues
