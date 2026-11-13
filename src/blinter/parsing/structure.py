"""Label collection, script structure, and subroutine detection."""

from contextvars import ContextVar
from dataclasses import dataclass, field
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

from blinter.constants import BUILTIN_VARS, MAX_LINE_LENGTH
from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import (
    _command_body,
    _is_blank_or_comment,
    _is_endlocal_command,
    _is_setlocal_command,
    _split_command_separators,
    _split_pipe_stages,
    _split_tokens,
    _strip_leading_if_predicates,
    caret_joins_next_physical_line,
    jump_lookup_key,
    label_line_key,
)
from blinter.rules.helpers import _add_issue

_LABEL_TARGET_PATTERN = re.compile(
    r"\b(?:call|goto)\s+(:\S+)",
    re.IGNORECASE,
)
# ASCII-only case folding: str.upper() maps ı to I and ſ to S, so a look-alike
# directive would suppress rules that neither a reader nor a search would see.
_SUPPRESSION_DIRECTIVE = re.compile(
    r"(?:^|(?<!\^)&\s*)@?(?:rem\s|::)\s*lint:ignore(-line)?(?=\s|$)(.*)$",
    re.IGNORECASE | re.ASCII,
)
_SUPPRESSION_CODE = re.compile(r"^[A-Za-z]+[0-9]+$", re.ASCII)


def label_key_from_line(stripped_line: str) -> Optional[str]:
    """Return ``:name`` for a label line.

    The key ends at space, tab, ``+``, ``:``, ``&``, ``|``, ``<``, or ``>``.
    Comma, semicolon, and equals stay in the key. ``::`` remarks are not
    labels. A key must contain a letter, digit, or underscore, so ``:_`` is a
    label and ``:----`` is not.
    """
    if not stripped_line.startswith(":") or stripped_line.startswith("::"):
        return None
    name = label_line_key(stripped_line[1:])
    if not name or not re.search(r"[a-zA-Z0-9_]", name):
        return None
    return ":" + name.lower()


def _collect_labels(lines: List[str]) -> Tuple[Dict[str, int], List[LintIssue]]:
    """Collect all labels and detect duplicates."""
    labels: Dict[str, int] = {}
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        label = label_key_from_line(line.strip())
        if label is not None:
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
    key = jump_lookup_key(raw_target)
    if not key:
        return ""
    return f":{key}"


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
            if name and name not in first_line:
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


def _suppression_codes(rest: str, line_number: int) -> Set[str]:
    """Return ASCII rule codes from a directive, skipping malformed tokens."""
    codes: Set[str] = set()
    for raw_code in rest.split(","):
        code = raw_code.strip()
        if not code:
            continue
        if _SUPPRESSION_CODE.fullmatch(code) is None:
            logger.debug(
                "Ignoring non-ASCII or malformed suppression code %r on line %d",
                code,
                line_number,
            )
            continue
        codes.add(code.upper())
    return codes


def _record_suppression(
    suppressions: Dict[int, Set[str]],
    line_number: int,
    same_line: bool,
    rest: str,
) -> None:
    """Record one directive. A code list with no ASCII codes suppresses nothing."""
    target = line_number if same_line else line_number + 1
    if not rest:
        logger.debug(
            "Suppressing all rules on line %d from the directive on line %d",
            target,
            line_number,
        )
        suppressions[target] = set()
        return
    codes = _suppression_codes(rest, line_number)
    if not codes:
        logger.debug(
            "Directive on line %d listed no ASCII rule codes; suppressing nothing",
            line_number,
        )
        return
    logger.debug(
        "Suppressing %s on line %d from the directive on line %d",
        ",".join(sorted(codes)),
        target,
        line_number,
    )
    suppressions.setdefault(target, set()).update(codes)


def _parse_suppression_comments(lines: List[str]) -> Dict[int, Set[str]]:
    """
    Parse inline suppression comments from batch file lines.

    The directive and its rule codes match case-insensitively in ASCII only.
    ``lınt:ıgnore`` and ``ſEC008`` are not directives or codes.

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

    for line_number, line in enumerate(lines, start=1):
        match = _SUPPRESSION_DIRECTIVE.search(line.strip())
        if match is None:
            continue
        rest_raw = match.group(2)
        rest = rest_raw.strip() if isinstance(rest_raw, str) else ""
        _record_suppression(
            suppressions,
            line_number,
            match.group(1) is not None,
            rest,
        )

    return suppressions


_CacheValueT = TypeVar("_CacheValueT")

_PAREN_BLOCK_KEYWORDS = frozenset({"do", "in", "else", "if"})

_paren_depth_cache_var: ContextVar[Optional[Dict[int, tuple[object, List[int]]]]] = (
    ContextVar("paren_depth_cache", default=None)
)
_defined_vars_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, frozenset[str]]]]
] = ContextVar("defined_vars_cache", default=None)
_empty_assigned_vars_cache_var: ContextVar[
    Optional[Dict[int, tuple[object, frozenset[str]]]]
] = ContextVar("empty_assigned_vars_cache", default=None)
_for_block_cache_var: ContextVar[Optional[Dict[int, tuple[object, List[bool]]]]] = (
    ContextVar("for_block_membership", default=None)
)


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


class _ParenScan:  # pylint: disable=too-few-public-methods
    """Mutable cursor for one quote- and caret-aware parenthesis scan."""

    __slots__ = (
        "delta",
        "same_line_open",
        "command",
        "quote",
        "command_has_text",
        "paren_is_literal",
    )

    def __init__(self) -> None:
        self.delta = 0
        self.same_line_open = 0
        self.command: List[str] = []
        self.quote = ""
        self.command_has_text = False
        # True once '(' does not open a block. Further parentheses cannot add
        # a block keyword or turn the first token into echo, so later '(' and
        # ')' on this command stay literal without rebuilding the buffer.
        self.paren_is_literal = False

    def reset_command(self) -> None:
        """Drop the command buffer so the next '(' is judged from scratch."""
        self.command = []
        self.command_has_text = False
        self.paren_is_literal = False

    def append_command(self, text: str) -> None:
        """Add ``text`` to the command buffer.

        Parentheses keep a known non-block command as a non-block. Any other
        character can introduce a keyword, so the next '(' is judged again.
        """
        self.command.append(text)
        if text.strip():
            self.command_has_text = True
        if text not in ("(", ")"):
            self.paren_is_literal = False


def _is_paren_comment_line(line: str) -> bool:
    """Return True for blank lines and REM/:: comments."""
    return _is_blank_or_comment(line)


def _paren_line_has_no_block(line: str) -> bool:
    """Return True when this physical line cannot open or close a block.

    Blank lines, REM remarks, ``::`` remarks, and labels consume the line.
    A caret at the end of a label or ``::`` remark still joins the following
    physical lines into that remark.
    """
    stripped = line.strip()
    return _is_paren_comment_line(stripped) or stripped.startswith(":")


def _skip_paren_line(
    line: str, *, scan: Optional[_ParenScan], remark_joins: bool
) -> bool:
    """Return True when ``line`` contributes no block parentheses.

    A line already joined by a caret is part of the command that owns it, so
    text such as ``rem b)`` is list data, not a remark. A label or ``::`` line
    that ends in an odd caret owns the following physical lines the same way.
    """
    if scan is not None:
        return False
    if remark_joins:
        logger.debug("Caret-joined remark contributes no block depth: %s", line.strip())
        return True
    return _paren_line_has_no_block(line)


def _first_command_token(command: str) -> str:
    """Return the first command token, ignoring a leading @."""
    body = command.strip().lstrip("@").strip()
    if not body:
        return ""
    return body.split(None, 1)[0].lower()


def _paren_opens_block(command: str) -> bool:
    """Return True when '(' opens an IF, FOR, ELSE, or command group."""
    if _first_command_token(command) == "echo":
        return False
    if not command.strip():
        return True
    tokens = {token.lower() for token in command.split()}
    return bool(tokens & _PAREN_BLOCK_KEYWORDS)


def _redir_amp_end(text: str, index: int) -> Optional[int]:
    """Return the index after an ``n>&n`` or ``>&`` redirection."""
    if text[index] in "12" and text.startswith(">&", index + 1):
        end = index + 3
        if end < len(text) and text[end] in "12":
            end += 1
        return end
    if text[index] == ">" and index + 1 < len(text) and text[index + 1] == "&":
        end = index + 2
        if end < len(text) and text[end] in "12":
            end += 1
        return end
    return None


def _separator_span(text: str, index: int) -> int:
    """Return the length of an unquoted command separator at index, or 0."""
    pair = text[index : index + 2]
    if pair in ("&&", "||"):
        return 2
    if text[index] in "&|":
        return 1
    return 0


def _apply_open_paren(scan: _ParenScan) -> None:
    """Count a structural '(' or keep a literal one in the command buffer."""
    if scan.paren_is_literal or not _paren_opens_block("".join(scan.command)):
        scan.append_command("(")
        scan.paren_is_literal = True
        return
    scan.delta += 1
    scan.same_line_open += 1
    scan.reset_command()


def _apply_close_paren(scan: _ParenScan) -> None:
    """Count a structural ')' or keep a literal one in the command buffer."""
    if scan.same_line_open > 0:
        scan.same_line_open -= 1
        scan.delta -= 1
        scan.reset_command()
        return
    if not scan.command_has_text:
        scan.delta -= 1
        scan.reset_command()
        return
    scan.append_command(")")


def _block_paren_delta(line: str, scan: Optional[_ParenScan] = None) -> int:
    """Return the net IF/FOR/group parenthesis change for one line.

    ``scan`` is the state left by the line a caret joined to this one.
    """
    if scan is None:
        scan = _ParenScan()
    scan.delta = 0
    index = 0
    length = len(line)
    while index < length:
        if scan.quote:
            if line[index] == scan.quote:
                scan.quote = ""
            index += 1
            continue
        if line[index] == "^":
            index += 2 if index + 1 < length else 1
            continue
        if line[index] in '"`':
            scan.quote = line[index]
            index += 1
            continue
        redir_end = _redir_amp_end(line, index)
        if redir_end is not None:
            scan.append_command(line[index:redir_end])
            index = redir_end
            continue
        separator = _separator_span(line, index)
        if separator:
            scan.reset_command()
            index += separator
            continue
        if line[index] == "(":
            _apply_open_paren(scan)
            index += 1
            continue
        if line[index] == ")":
            _apply_close_paren(scan)
            index += 1
            continue
        scan.append_command(line[index])
        index += 1
    return scan.delta


def _update_paren_depth(line: str, current_depth: int) -> int:
    """Update parentheses depth based on the line content."""
    if _is_paren_comment_line(line):
        return current_depth
    return current_depth + _block_paren_delta(line)


def _paren_depth_deltas(lines: List[str]) -> List[int]:
    """Return the IF/FOR/group parenthesis change of each physical line.

    cmd.exe reads a caret-joined run of lines as one line, so a quote or a
    ``(`` still open at the end of one line carries into the next. Whitespace
    between those physical lines stays in the command: ``if^`` followed by
    `` 1==1 (`` is ``if 1==1 (``. One state covers at most ``MAX_LINE_LENGTH``
    characters, more than cmd.exe accepts on one line: a line that would pass
    that limit starts a new state. This bounds the cost of a long run.
    """
    deltas: List[int] = []
    depth = 0
    run_length = 0
    scan: Optional[_ParenScan] = None
    remark_joins = False
    for line in lines:
        body = line.rstrip("\r\n")
        if _skip_paren_line(body, scan=scan, remark_joins=remark_joins):
            deltas.append(0)
            remark_joins = caret_joins_next_physical_line(line, depth_before=depth)
            continue
        remark_joins = False
        if scan is None or run_length + len(body) > MAX_LINE_LENGTH:
            scan = _ParenScan()
            run_length = 0
        run_length += len(body)
        delta = _block_paren_delta(body, scan)
        deltas.append(delta)
        if not caret_joins_next_physical_line(line, depth_before=depth):
            scan = None
        depth = max(depth + delta, 0)
    return deltas


def _begin_paren_depth_pass() -> None:
    """Start a per-lint parenthesis-depth cache for the current context."""
    _paren_depth_cache_var.set({})


def _begin_empty_assigned_vars_pass() -> None:
    """Start a per-lint empty-assigned-vars cache for the current context."""
    _empty_assigned_vars_cache_var.set({})
    _defined_vars_cache_var.set({})


def _begin_for_block_pass() -> None:
    """Start a per-lint FOR-block membership cache for the current context."""
    _for_block_cache_var.set({})


def _begin_structure_cache_pass() -> None:
    """Initialize per-lint caches used by checker modules."""
    _begin_for_block_pass()
    _begin_invocation_prefix_pass()
    _begin_delayed_expansion_pass()
    _begin_paren_depth_pass()
    _begin_empty_assigned_vars_pass()


def _build_paren_depth_before(lines: List[str]) -> List[int]:
    """Return parenthesis block depth before each 1-based line."""
    depth = 0
    result: List[int] = []
    for delta in _paren_depth_deltas(lines):
        result.append(depth)
        depth = max(depth + delta, 0)
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


_LEAVES_RE = re.compile(r"exit(?:[\s/)]|$)|goto[\s:]+(?P<label>\S+)", re.I)
_MAY_RUN_NOTHING_RE = re.compile(r"(?:if|for)\s", re.IGNORECASE)
_JUMPS = r"\bgoto[\s:]+(?![\s:]|eof\b)|\bcall\s*:"
_JUMPS_RE = re.compile(_JUMPS, re.I)
_READS_OR_JUMPS_RE = re.compile(r"![^!]+!|" + _JUMPS, re.I)


def _leaving_command(body: str) -> Optional[re.Match[str]]:
    """Match the EXIT or GOTO that a command line always ends in, if any.

    The last command must follow a plain ``&``: ``x || exit /b`` goes on when
    ``x`` succeeds. A line starting with IF or FOR may run nothing at all.
    The commands before it must not jump, and it must not be piped: a piped
    EXIT runs in another cmd.exe.
    """
    parts = _split_command_separators(body)
    head = body[: len(body) - len(parts[-1])]
    if (
        head.endswith(("&&", "||"))
        or _MAY_RUN_NOTHING_RE.match(body)
        or _JUMPS_RE.search(head.replace("^", ""))
        or len(_split_pipe_stages(parts[-1])) > 1
    ):
        return None
    return _LEAVES_RE.match(parts[-1].strip().lstrip("(@").lstrip())


def _continues(line: str, *, depth_before: int = 0) -> bool:
    """Return True where this physical line joins the next one.

    A caret inside an open quote or a REM remark does not. ``rem)`` continues
    unless that ``)`` closes a group already open. A label or ``::`` line that
    ends in an odd caret does.
    """
    return caret_joins_next_physical_line(line, depth_before=depth_before)


@dataclass
class _Block:
    """A parenthesized block: its first and last lines, ENDLOCAL lines, any SETLOCAL."""

    first: int
    last: int
    endlocals: List[int] = field(default_factory=list)
    setlocal: bool = False


class _ExitScan:
    """Find the ENDLOCAL lines that close no scope for the lines below them.

    A block whose last command is an EXIT or GOTO, not piped, never falls
    through: the lines after it run only when it did not. So an ENDLOCAL in
    such a block does not close the scope they see, unless the block holds a
    SETLOCAL at any depth, or, at any depth before its last command, a
    ``call :label``, a GOTO but ``goto :eof``, or a line that ends in an odd
    run of carets. Carets are dropped before looking for a jump. Neither does
    an ENDLOCAL in ``if ... endlocal & exit /b`` on one line, unless that line
    or the one above it ends in an odd run of carets.

    A GOTO counts only where its label appears once, below the GOTO, and the
    lines from the label read no ``!VAR!`` and hold no ``call :label`` and no
    GOTO but ``goto :eof`` before an EXIT or ``goto :eof`` outside any block
    and IF or FOR. Otherwise the closed scope is still reported there. A block
    runs from a line ending in ``(`` to a line starting with ``)``; where
    these do not balance, no line is skipped.
    """

    def __init__(self, lines: List[str]) -> None:
        self.bodies = [_command_body(line) for line in lines]
        flat = [body.replace("^", "") for body in self.bodies]
        depths_before = _build_paren_depth_before(lines)
        self.goes_on = [
            _continues(line, depth_before=depths_before[index])
            for index, line in enumerate(lines)
        ]
        self.sets = [_is_setlocal_command(line) for line in lines]
        self.ends = [_is_endlocal_command(line) for line in lines]
        self.labels: Dict[str, List[int]] = {}
        self.jumps = [0]  # jump lines before each line
        depths: List[int] = []
        depth = 0
        for index, body in enumerate(self.bodies):
            depth -= body.startswith(")")
            depths.append(depth)
            depth += body.endswith("(")
            jumps = self.goes_on[index] or bool(_JUMPS_RE.search(flat[index]))
            self.jumps.append(self.jumps[-1] + jumps)
            label = label_key_from_line(body)
            if label is not None:
                self.labels.setdefault(label, []).append(index)
        self.reads = [False] * (len(lines) + 1)
        for index in range(len(lines) - 1, -1, -1):
            body = self.bodies[index]
            stops = depths[index] == 0 and _leaving_command(body) is not None
            self.reads[index] = (
                self.goes_on[index]
                or bool(_READS_OR_JUMPS_RE.search(flat[index]))
                or (not stops and self.reads[index + 1])
            )

    def leaves_for_good(self, index: int, body: str) -> bool:
        """Return True when line ``index`` ends in EXIT, or in a GOTO as above."""
        leaving = _leaving_command(body)
        if leaving is None:
            return False
        raw_label = str(leaving.group("label") or "eof")
        name = jump_lookup_key(raw_label) or "eof"
        if name == "eof":
            return True
        targets = self.labels.get(":" + name, [])
        if len(targets) != 1 or targets[0] < index:
            return False
        return not self.reads[targets[0] + 1]

    def skipped(self) -> Set[int]:
        """Return the 0-based ENDLOCAL lines described above."""
        found: Set[int] = set()
        blocks: List[_Block] = []
        for index, body in enumerate(self.bodies):
            if not body:
                continue
            if body.startswith(")"):
                if not blocks:
                    return set()
                block = blocks.pop()
                if blocks:
                    blocks[-1].setlocal |= block.setlocal
                if self.block_leaves(block):
                    found.update(block.endlocals)
            ends = self.ends[index]
            if ends and self.is_if_exit(index, body):
                found.add(index)
                ends = False
            if blocks:
                block = blocks[-1]
                block.last = index
                block.setlocal |= self.sets[index]
                if ends:
                    block.endlocals.append(index)
            if body.endswith("("):
                blocks.append(_Block(index, index))
        return set() if blocks else found

    def block_leaves(self, block: _Block) -> bool:
        """Return True when a block always leaves at its last line, as above."""
        if block.setlocal or self.jumps[block.last] > self.jumps[block.first + 1]:
            return False
        return self.leaves_for_good(block.last, self.bodies[block.last])

    def is_if_exit(self, index: int, body: str) -> bool:
        """Return True for an IF line whose command leaves for good, as above."""
        if (
            not body.lower().startswith("if ")
            or self.goes_on[index]
            or (index and self.goes_on[index - 1])
        ):
            return False
        command = " ".join(_strip_leading_if_predicates(_split_tokens(body)))
        return self.leaves_for_good(index, command)


def _read_scopes(lines: List[str], scan: _ExitScan, skipped: Set[int]) -> List[bool]:
    """Return the state after each line, reading SETLOCAL and ENDLOCAL in order."""
    stack: List[bool] = []
    state: List[bool] = []
    for index, line in enumerate(lines):
        if scan.sets[index]:
            stripped = line.strip().lstrip("@").strip().lower()
            if "enabledelayedexpansion" in stripped:
                stack.append(True)
            elif "disabledelayedexpansion" in stripped:
                stack.append(False)
            else:
                stack.append(stack[-1] if stack else False)
        elif scan.ends[index] and index not in skipped:
            if stack:
                stack.pop()
        state.append(stack[-1] if stack else False)
    return state


def _build_delayed_expansion_state(lines: List[str]) -> List[bool]:
    """Return delayed-expansion active state at each 1-based line (after that line).

    SETLOCAL and ENDLOCAL are read in file order, except the ENDLOCAL lines
    ``_ExitScan`` skips. Where a label then sees another state than with none
    skipped, a GOTO or CALL may reach it with the scope closed, so none is.
    """
    scan = _ExitScan(lines)
    state = _read_scopes(lines, scan, set())
    skipped = scan.skipped()
    if skipped:
        kept = _read_scopes(lines, scan, skipped)
        labels = [index for found in scan.labels.values() for index in found]
        if all(kept[index] == state[index] for index in labels):
            return kept
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
) -> Tuple[bool, bool, bool, bool]:
    """Analyze script structure for context-aware checking.

    Returns:
        Tuple of (has_setlocal, has_set_commands, uses_delayed_vars,
        has_literal_exclamations). Delayed-expansion enablement is decided
        per line by ``_delayed_expansion_active_at_line``.
    """
    has_setlocal = any(_is_setlocal_command(line) for line in lines)
    has_set_commands = any(
        re.match(r"\s*set\s+[^=]+=.*", line, re.IGNORECASE) for line in lines
    )
    # Match any content between exclamation marks, including special chars like @, -, #, $, etc.
    # that are commonly used in batch variable names (e.g., !@DEBUG_MODE!, !@CRLF-%~1!)
    uses_delayed_vars = any(re.search(r"![^!]+!", line) for line in lines)

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

    return (
        has_setlocal,
        has_set_commands,
        uses_delayed_vars,
        has_literal_exclamations,
    )
