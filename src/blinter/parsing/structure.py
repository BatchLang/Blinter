"""Label collection, script structure, and subroutine detection."""

from contextvars import ContextVar
import re
from typing import (
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)

from blinter.constants import BUILTIN_VARS
from blinter.models import LintIssue
from blinter.parsing.context import _is_endlocal_command, _is_setlocal_command
from blinter.patterns import (
    _COMPILED_SETLOCAL_DISABLE,
)
from blinter.rules.helpers import _add_issue

_LABEL_TARGET_PATTERN = re.compile(
    r"\b(?:call|goto)\s+(:[^\s]+)",
    re.IGNORECASE,
)


def _collect_labels(lines: List[str]) -> Tuple[Dict[str, int], List[LintIssue]]:
    """Collect all labels and detect duplicates."""
    labels: Dict[str, int] = {}
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped_line = line.strip()
        if stripped_line.startswith(":"):
            # Skip comment-style lines that start with :: (double colon)
            if stripped_line.startswith("::"):
                continue

            label = stripped_line.lower()

            # Skip comment-style labels (like :::) that contain no alphanumeric characters
            # These are commonly used as decorative comments and should not be flagged as duplicates
            label_content = label[1:]  # Remove the leading ":"
            if not re.search(r"[a-zA-Z0-9]", label_content):
                # This is a comment-style label like ::::::, skip it
                continue

            if label in labels:
                _add_issue(
                    issues,
                    line_number=i,
                    rule_code="W013",
                    context=f"Label '{label}' already defined on line {labels[label]}",
                )
            else:
                labels[label] = i

    return labels, issues


def _normalize_label_target(raw_target: str) -> str:
    """Normalize CALL/GOTO label targets to match ``labels`` dict keys."""
    target = raw_target.strip().lower()
    if not target.startswith(":"):
        target = f":{target}"
    return target


_target_line_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, Dict[str, int]]]]
] = ContextVar("target_line_cache", default=None)
_sorted_labels_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, List[Tuple[str, int]]]]]
] = ContextVar("sorted_labels_cache", default=None)
_label_block_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, object, List[Optional[Tuple[str, int]]]]]]
] = ContextVar("label_block_cache", default=None)


def _begin_invocation_prefix_pass() -> None:
    """Start per-lint label-target caches for the current execution context."""
    _target_line_cache_var.set({})
    _sorted_labels_cache_var.set({})
    _label_block_cache_var.set({})


def _build_first_target_line(lines: List[str]) -> Dict[str, int]:
    """Map each CALL/GOTO target to the first 0-based line that names it."""
    first_line: Dict[str, int] = {}
    for index, line in enumerate(lines):
        for match in _LABEL_TARGET_PATTERN.finditer(line):
            name = _normalize_label_target(match.group(1))
            if name not in first_line:
                first_line[name] = index
    return first_line


def _first_target_lines_for(lines: List[str]) -> Dict[str, int]:
    """Return cached first-target lines for ``lines`` within a single lint pass."""
    return _identity_cached(
        _target_line_cache_var.get(),
        lines,
        lambda: _build_first_target_line(lines),
    )


def _sorted_labels_for(labels: Dict[str, int]) -> List[Tuple[str, int]]:
    """Return label definitions sorted by line, cached for this lint pass."""
    return _identity_cached(
        _sorted_labels_cache_var.get(),
        labels,
        lambda: sorted(labels.items(), key=_label_sort_key),
    )


def _label_was_targeted_before(
    lines: List[str], before_line: int, label_name: str
) -> bool:
    """Return True when CALL/GOTO names ``label_name`` before ``before_line``."""
    if before_line <= 1:
        return False
    first_line = _first_target_lines_for(lines).get(label_name)
    if first_line is None:
        return False
    return first_line < before_line - 1


def _build_label_block_index(
    sorted_labels: List[Tuple[str, int]], total_lines: int
) -> List[Optional[Tuple[str, int]]]:
    """Map each 1-based line to the label body that contains it.

    Label bodies span from the line after the label until the next label
    (exclusive). The label line itself is not part of the body.
    """
    blocks: List[Optional[Tuple[str, int]]] = [None] * (total_lines + 1)
    for index, (label_name, label_line) in enumerate(sorted_labels):
        next_label_line = (
            sorted_labels[index + 1][1]
            if index + 1 < len(sorted_labels)
            else total_lines + 1
        )
        block = (label_name, label_line)
        for line_number in range(label_line + 1, next_label_line):
            if 1 <= line_number <= total_lines:
                blocks[line_number] = block
    return blocks


def _label_blocks_for(
    lines: List[str], labels: Dict[str, int]
) -> List[Optional[Tuple[str, int]]]:
    """Return the per-line label-body index, cached for this lint pass."""
    sorted_labels = _sorted_labels_for(labels)
    cache = _label_block_cache_var.get()
    if cache is None:
        return _build_label_block_index(sorted_labels, len(lines))
    source_id = id(lines)
    cached = cache.get(source_id)
    if cached is None or cached[0] is not lines or cached[1] is not labels:
        blocks = _build_label_block_index(sorted_labels, len(lines))
        cache[source_id] = (lines, labels, blocks)
        return blocks
    return cached[2]


def _label_sort_key(item: tuple[str, int]) -> int:
    """Sort label entries by line number."""
    return item[1]


def _is_in_subroutine_context(
    lines: List[str], line_number: int, labels: Dict[str, int]
) -> bool:
    """
    Determine if a line is within an invoked subroutine context.

    A line is in subroutine context when it falls inside a label block that was
    reached via an earlier ``CALL :label`` or ``GOTO :label``. Main-line fall-through
    into a label without a prior transfer is not treated as subroutine context.
    """
    if not labels or line_number < 1:
        return False

    blocks = _label_blocks_for(lines, labels)
    block = blocks[line_number] if line_number < len(blocks) else None
    if block is None:
        return False

    label_name, _ = block
    return _label_was_targeted_before(lines, line_number, label_name)


_SET_VAR_NAME = r"[A-Za-z0-9_@]+"
# CALL :label varname — first argument names a variable set via SET "%1=" in :label
_CALL_LABEL_VAR_PATTERN = re.compile(
    rf"\bcall\s+:\w+\s+({_SET_VAR_NAME})\b",
    re.IGNORECASE,
)


def _collect_set_variables(lines: List[str]) -> Set[str]:
    """Collect all variables that are set in the script."""
    set_vars: Set[str] = set()
    vn = _SET_VAR_NAME
    for line in lines:
        # Match different SET patterns, including quoted variable names
        # Use re.search instead of re.match to find SET commands anywhere in the line
        # This handles cases like: if not defined VAR set "VAR=value"
        patterns = [
            rf"\bset\s+({vn})=",  # Regular set: set VAR=value
            rf'\bset\s+"({vn})=',  # Quoted set: set "VAR=value"
            rf"\bset\s+/p\s+({vn})=",  # Set with prompt: set /p VAR=
            rf'\bset\s+/p\s+"({vn})=',  # Quoted set with prompt: set /p "VAR="
            rf"\bset\s+/a\s+({vn})=",  # Arithmetic set: set /a VAR=
            rf'\bset\s+/a\s+"({vn})=',  # Quoted arithmetic set: set /a "VAR="
            rf"\bset\s+/a\s+({vn})[+\-*/%]?=",  # Compound: set /a VAR+=1
            rf'\bset\s+/a\s+"({vn})[+\-*/%]?=',  # Quoted compound set /a
        ]

        stripped_line = line.strip()
        for pattern in patterns:
            for set_match in re.finditer(pattern, stripped_line, re.IGNORECASE):
                var_name_text: str = set_match.group(1)
                set_vars.add(var_name_text.upper())

        for call_match in _CALL_LABEL_VAR_PATTERN.finditer(stripped_line):
            set_vars.add(str(call_match.group(1)).upper())

        # Handle dynamic variable assignments in FOR loops: set "%%~b=value"
        # Example: for %%a in (list) do (set "%%~a=value")
        dynamic_set_match = re.search(
            r'\bset\s+"%%~[a-zA-Z]=', line.strip(), re.IGNORECASE
        )
        if dynamic_set_match:
            # When we see dynamic variable assignment, we need to look for what values
            # the FOR loop might iterate over to determine variable names
            # For now, mark this as a script that uses dynamic variables
            # and be more lenient with undefined variable warnings
            set_vars.add("__DYNAMIC_VARS__")

    set_vars.update(BUILTIN_VARS)

    return set_vars


def _collect_empty_assigned_variables(lines: List[str]) -> Set[str]:
    """Collect variables explicitly assigned an empty value via SET."""
    empty_vars: Set[str] = set()
    vn = _SET_VAR_NAME
    empty_patterns = [
        rf'\bset\s+"?({vn})"?\s*=\s*(?:$|[&|])',
        rf'\bset\s+"({vn})="\s*(?:$|[&|])',
    ]
    for line in lines:
        stripped = line.strip()
        for pattern in empty_patterns:
            for match in re.finditer(pattern, stripped, re.IGNORECASE):
                empty_vars.add(str(match.group(1)).upper())
    return empty_vars


def _parse_suppression_comments(lines: List[str]) -> Dict[int, Set[str]]:
    """
    Parse inline suppression comments from batch file lines.

    Supports formats:
    - REM LINT:IGNORE <code> - Suppress code on the next line
    - REM LINT:IGNORE - Suppress all issues on the next line
    - REM LINT:IGNORE-LINE <code> - Suppress code on the same line
    - REM LINT:IGNORE-LINE - Suppress all issues on the same line

    Args:
        lines: List of lines from the batch file

    Returns:
        Dictionary mapping line numbers to set of rule codes to suppress.
        An empty set means suppress all rules for that line.

    Example:
        REM LINT:IGNORE E009
        ECHO '' .... Represents a " character
    """
    suppressions: Dict[int, Set[str]] = {}

    for i, line in enumerate(lines, start=1):
        stripped = line.strip().upper()

        # Check for IGNORE comment (affects next line)
        if stripped.startswith("REM ") or stripped.startswith("::"):
            # Remove REM or :: prefix
            comment_text = (
                stripped[3:].strip()
                if stripped.startswith("REM")
                else stripped[2:].strip()
            )

            # Check for LINT:IGNORE-LINE (same line suppression)
            if comment_text.startswith("LINT:IGNORE-LINE"):
                rest = comment_text[16:].strip()
                if rest:
                    # Specific rules to suppress
                    codes = {code.strip() for code in rest.split(",") if code.strip()}
                    suppressions.setdefault(i, set()).update(codes)
                else:
                    # Suppress all rules on this line
                    suppressions[i] = set()

            # Check for LINT:IGNORE (next line suppression)
            elif comment_text.startswith("LINT:IGNORE"):
                rest = comment_text[11:].strip()
                if rest:
                    # Specific rules to suppress on next line
                    codes = {code.strip() for code in rest.split(",") if code.strip()}
                    suppressions.setdefault(i + 1, set()).update(codes)
                else:
                    # Suppress all rules on next line
                    suppressions[i + 1] = set()

    return suppressions


_CacheValueT = TypeVar("_CacheValueT")

_BLOCK_CLOSE_PATTERN = re.compile(
    r"^\)(?:\s*(?:"
    r">>?\s*(?:\"[^\"]*\"|\S+)?|"
    r"[12]>&?[12]?|"
    r">\s*(?:\"[^\"]*\"|\S+)"
    r"))?",
    re.IGNORECASE,
)

_paren_depth_cache_var: ContextVar[Optional[Dict[int, tuple[object, List[int]]]]] = (
    ContextVar("paren_depth_cache", default=None)
)
_defined_vars_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, frozenset[str]]]]
] = ContextVar("defined_vars_cache", default=None)
_empty_assigned_vars_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, frozenset[str]]]]
] = ContextVar("empty_assigned_vars_cache", default=None)


def _identity_cached(
    cache: Optional[Dict[int, tuple[object, _CacheValueT]]],
    source: object,
    builder: Callable[[], _CacheValueT],
) -> _CacheValueT:
    """Return builder() cached by object identity within a lint pass."""
    if cache is None:
        return builder()
    source_id = id(source)
    cached = cache.get(source_id)
    if cached is None or cached[0] is not source:
        value = builder()
        cache[source_id] = (source, value)
        return value
    return cached[1]


def _is_bare_paren_block_open(line: str) -> bool:
    """Return True for ``( command `` groups that are not IF/FOR headers."""
    if not re.match(r"^\(", line):
        return False
    return re.search(r"\b(?:if|for)\b", line, re.IGNORECASE) is None


def _line_opens_block_depth(line: str) -> int:
    """Return how many IF/FOR/(group) blocks open on this line."""
    if _is_bare_paren_block_open(line):
        return 1
    if re.search(r"\bfor\b", line, re.IGNORECASE) and (
        re.search(r"\bdo\s*\(\s*$", line, re.IGNORECASE)
        or re.search(r"\bin\s*\(\s*$", line, re.IGNORECASE)
    ):
        return 1
    if (
        re.search(r"\bif\b", line, re.IGNORECASE)
        and re.search(r"\(\s*$", line)
        and not re.match(r"echo\b", line, re.IGNORECASE)
    ):
        return 1
    return 0


def _update_paren_depth(line: str, current_depth: int) -> int:
    """Update parentheses depth based on the line content."""
    close_match = _BLOCK_CLOSE_PATTERN.match(line)
    if close_match:
        current_depth -= 1
        remainder = line[close_match.end() :].strip()
        if re.match(r"else\b", remainder, re.IGNORECASE) and re.search(
            r"\(", remainder
        ):
            current_depth += 1
        return current_depth

    return current_depth + _line_opens_block_depth(line)


def _begin_paren_depth_pass() -> None:
    """Start a per-lint parenthesis-depth cache for the current context."""
    _paren_depth_cache_var.set({})


def _begin_empty_assigned_vars_pass() -> None:
    """Start a per-lint empty-assigned-vars cache for the current context."""
    _empty_assigned_vars_cache_var.set({})
    _defined_vars_cache_var.set({})


def _begin_structure_cache_pass() -> None:
    """Initialize per-lint caches used by checker modules."""
    _begin_invocation_prefix_pass()
    _begin_delayed_expansion_pass()
    _begin_paren_depth_pass()
    _begin_empty_assigned_vars_pass()


def _build_paren_depth_before(lines: List[str]) -> List[int]:
    """Return parenthesis block depth before each 1-based line."""
    depth = 0
    result: List[int] = []
    for line in lines:
        result.append(depth)
        depth = max(_update_paren_depth(line.strip(), depth), 0)
    return result


def _paren_depth_before_for_lines(lines: List[str]) -> List[int]:
    """Return cached parenthesis depth-before values within a single lint pass."""
    return _identity_cached(
        _paren_depth_cache_var.get(),
        lines,
        lambda: _build_paren_depth_before(lines),
    )


def _paren_depth_before_line(lines: List[str], line_num: int) -> int:
    """Return parenthesis block depth before processing line_num (1-based)."""
    if line_num < 1:
        return 0
    depths = _paren_depth_before_for_lines(lines)
    if line_num > len(depths):
        return depths[-1] if depths else 0
    return depths[line_num - 1]


_delayed_expansion_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, List[bool]]]]
] = ContextVar("delayed_expansion_cache", default=None)


def _begin_delayed_expansion_pass() -> None:
    """Start a per-lint delayed-expansion state cache for the current context."""
    _delayed_expansion_cache_var.set({})


def _build_delayed_expansion_state(lines: List[str]) -> List[bool]:
    """Return delayed-expansion active state at each 1-based line (after that line)."""
    stack: List[bool] = []
    state: List[bool] = []
    for line in lines:
        if _is_setlocal_command(line):
            stripped = line.strip().lstrip("@").strip().lower()
            if "enabledelayedexpansion" in stripped:
                stack.append(True)
            elif "disabledelayedexpansion" in stripped:
                stack.append(False)
            else:
                stack.append(stack[-1] if stack else False)
        elif _is_endlocal_command(line):
            if stack:
                stack.pop()
        state.append(stack[-1] if stack else False)
    return state


def _delayed_expansion_state_for_lines(lines: List[str]) -> List[bool]:
    """Return cached delayed-expansion state per line within a single lint pass."""
    return _identity_cached(
        _delayed_expansion_cache_var.get(),
        lines,
        lambda: _build_delayed_expansion_state(lines),
    )


def _delayed_expansion_active_at_line(lines: List[str], line_num: int) -> bool:
    """Return whether delayed expansion is active at the given 1-based line number."""
    if line_num < 1 or line_num > len(lines):
        return False
    return _delayed_expansion_state_for_lines(lines)[line_num - 1]


def _analyze_script_structure(
    lines: List[str],
) -> Tuple[bool, bool, bool, bool, bool, bool, bool]:
    """Analyze script structure for context-aware checking.

    Returns:
        Tuple of (has_setlocal, has_set_commands, has_delayed_expansion, uses_delayed_vars,
                  has_disable_delayed_expansion, has_literal_exclamations, disable_expansion_lines)
    """
    has_setlocal = any(_is_setlocal_command(line) for line in lines)
    has_set_commands = any(
        re.match(r"\s*set\s+[^=]+=.*", line, re.IGNORECASE) for line in lines
    )
    has_delayed_expansion = any(
        _is_setlocal_command(line) and "enabledelayedexpansion" in line.lower()
        for line in lines
    )
    # Match any content between exclamation marks, including special chars like @, -, #, $, etc.
    # that are commonly used in batch variable names (e.g., !@DEBUG_MODE!, !@CRLF-%~1!)
    uses_delayed_vars = any(re.search(r"![^!]+!", line) for line in lines)

    # Check for SETLOCAL DISABLEDELAYEDEXPANSION usage
    has_disable_delayed_expansion = any(
        _COMPILED_SETLOCAL_DISABLE.search(line) for line in lines
    )

    # Check for literal ! characters in strings (not delayed expansion variables)
    # Look for ! characters that are NOT part of delayed expansion !var! patterns
    # Use negative lookbehind (?<![^\s]) and negative lookahead (?![^\s!]) to match standalone !
    has_literal_exclamations = False
    for line in lines:
        # Remove all delayed expansion patterns first
        cleaned = re.sub(r"![^!\s]+!", "", line)
        # Now check if there are any remaining ! characters in echo/set statements
        if re.search(r"(echo|set\s+\w+=).*!", cleaned, re.IGNORECASE):
            has_literal_exclamations = True
            break

    # Track whether any line uses disabledelayedexpansion
    has_disable_expansion_lines = any(
        _COMPILED_SETLOCAL_DISABLE.search(line) for line in lines
    )

    return (
        has_setlocal,
        has_set_commands,
        has_delayed_expansion,
        uses_delayed_vars,
        has_disable_delayed_expansion,
        has_literal_exclamations,
        has_disable_expansion_lines,
    )
