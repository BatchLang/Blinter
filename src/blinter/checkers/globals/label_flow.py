"""S010 reachability and S018 call-target documentation."""

import re
from typing import Dict, List, Optional

from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import (
    _call_subroutine_label_names,
    _command_body,
    _command_chain,
    _command_segments,
    _goto_and_call_label_names,
    _is_blank_or_comment,
    _is_comment_line,
    _is_comment_or_label,
    _split_pipe_stages,
    _split_tokens,
    caret_joins_next_physical_line,
    jump_lookup_key,
)
from blinter.parsing.structure import (
    _build_paren_depth_before,
    _update_paren_depth,
    label_key_from_line,
)
from blinter.rules.registry import RULES

# Optional "(" and "@" sit on the command. The operand is cut to a label key
# before looking for % or !, so "goto plus+%1" is the static key "plus".
_COMPUTED_JUMP_RE = re.compile(
    r"^(?:\(\s*)?@?(?:goto(?:\s+:?|:)|call\s+:)(\S+)",
    re.IGNORECASE,
)
_FOR_COMMAND_RE = re.compile(r"^for\b", re.IGNORECASE)


def _is_name_char(char: str) -> bool:
    """Return True for characters that continue a batch command word."""
    return char.isalnum() or char == "_"


def _word_at(text: str, index: int, word: str) -> bool:
    """Return True when ``word`` sits at ``index`` as a whole word."""
    end = index + len(word)
    if text[index:end].lower() != word:
        return False
    before_ok = index == 0 or not _is_name_char(text[index - 1])
    after_ok = end >= len(text) or not _is_name_char(text[end])
    return before_ok and after_ok


def _skip_quoted_or_caret(text: str, index: int, quote: str) -> tuple[int, str] | None:
    """Advance past a quote, quoted character, or caret escape.

    Returns None when ``index`` is ordinary command text. A caret outside
    quotes swallows the next character, matching the separator splitter.
    """
    char = text[index]
    if quote:
        if char == quote:
            return index + 1, ""
        return index + 1, quote
    if char in "'\"":
        return index + 1, char
    if char == "^":
        return min(index + 2, len(text)), ""
    return None


def _for_in_set_open(text: str) -> int | None:
    """Return the index of '(' that opens a FOR IN set, outside quotes."""
    quote = ""
    index = 0
    length = len(text)
    while index < length:
        skipped = _skip_quoted_or_caret(text, index, quote)
        if skipped is not None:
            index, quote = skipped
            continue
        if _word_at(text, index, "in"):
            cursor = index + 2
            while cursor < length and text[cursor].isspace():
                cursor += 1
            if cursor < length and text[cursor] == "(":
                return cursor
        index += 1
    return None


def _paren_group_end(text: str, open_index: int) -> int | None:
    """Return the index after the ')' matching '(' at ``open_index``."""
    depth = 0
    quote = ""
    index = open_index
    length = len(text)
    while index < length:
        skipped = _skip_quoted_or_caret(text, index, quote)
        if skipped is not None:
            index, quote = skipped
            continue
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _for_do_body(segment: str) -> str:
    """Return the command after FOR's DO, or empty when that DO is absent.

    The DO keyword follows the IN set. ``do`` inside the set, including
    ``in ("do goto %1")``, is data and is not the keyword.
    """
    open_paren = _for_in_set_open(segment)
    if open_paren is None:
        return ""
    after_set = _paren_group_end(segment, open_paren)
    if after_set is None:
        return ""
    cursor = after_set
    while cursor < len(segment) and segment[cursor].isspace():
        cursor += 1
    if not _word_at(segment, cursor, "do"):
        return ""
    return segment[cursor + 2 :].lstrip()


def _computed_jump_command(segment: str) -> str:
    """Return the GOTO or CALL text a segment can run."""
    if _FOR_COMMAND_RE.match(segment) is None:
        return segment
    return _for_do_body(segment)


def _prefix_of_computed_jump(segment: str) -> str | None:
    """Return the literal label prefix of a computed jump, or None.

    ``goto plus+%1`` searches for ``plus`` after expansion, so it is not a
    prefix match. ``goto case_%1`` still reaches labels that start with ``case_``.
    """
    match = _COMPUTED_JUMP_RE.match(_computed_jump_command(segment))
    if match is None:
        return None
    key = jump_lookup_key(str(match.group(1)))
    if "%" not in key and "!" not in key:
        return None
    return key.split("%", 1)[0].split("!", 1)[0]


def _logical_command(
    lines: List[str], index: int, depths: List[int] | None = None
) -> str:
    """Join a caret-continued command into the single line cmd runs.

    Only the caret that escapes the newline is removed. A caret inside an
    open quote or a REM remark does not continue, so a following ``exit``
    stays its own command. ``rem)`` continues unless that ``)`` closes a
    group that is already open.
    """
    if depths is None:
        depths = _build_paren_depth_before(lines)
    parts: List[str] = []
    cursor = index
    depth = depths[index] if index < len(depths) else 0
    while cursor < len(lines):
        text = lines[cursor].rstrip("\r\n")
        if not caret_joins_next_physical_line(lines[cursor], depth_before=depth):
            parts.append(text)
            break
        parts.append(text[:-1])
        logger.debug("Caret continues command onto the next line: %s", text.strip())
        depth = max(_update_paren_depth(lines[cursor].strip(), depth), 0)
        cursor += 1
    return "".join(parts)


def _computed_jump_prefixes(lines: List[str]) -> set[str]:
    """Return the literal start of each computed GOTO or CALL target, lowercased.

    ``goto %ACTION%`` can reach any label and ``goto case_%1`` any label starting
    with ``case_``. A line that is itself a label is not a jump: cmd ignores
    the rest of that line. ``@goto`` is the same jump as ``goto``. A GOTO that
    exists only because the previous line ended in ``^`` is part of that earlier
    command, not its own jump.
    """
    prefixes: set[str] = set()
    depths = _build_paren_depth_before(lines)
    continued = _continuation_mask(lines)
    for index, line in enumerate(lines):
        if continued[index]:
            continue
        if _is_comment_or_label(line):
            if "goto" in line.lower() or "call" in line.lower():
                logger.debug(
                    "Ignoring computed jump on a label or comment line: %s",
                    line.strip(),
                )
            continue
        for segment in _command_segments(_logical_command(lines, index, depths)):
            prefix = _prefix_of_computed_jump(segment)
            if prefix is None:
                continue
            logger.debug(
                "Computed jump can reach labels starting with %r in %r",
                prefix,
                segment,
            )
            prefixes.add(prefix)
    return prefixes


_LEAVE_WORD_RE = re.compile(r"^(?:exit(?:/|$)|goto(?:[:/]|$))", re.IGNORECASE)


def _defined_label_name(line: str) -> str | None:
    """Return the lookup key of a label line, without the leading colon."""
    label = label_key_from_line(line.strip())
    if label is None:
        return None
    return label[1:]


def _matches_computed_prefix(name: str, prefixes: set[str]) -> bool:
    """Return True when a computed GOTO or CALL can reach ``name``."""
    return any(name.startswith(prefix) for prefix in prefixes)


def _segment_always_leaves(segment: str) -> bool:
    """Return True when ``segment`` is an unpiped EXIT or GOTO, not under IF or FOR."""
    text = segment.strip()
    while text.startswith("("):
        text = text[1:].strip()
    if not text or len(_split_pipe_stages(text)) > 1:
        return False
    tokens = _split_tokens(text)
    while tokens and _is_leave_prefix(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return False
    word = tokens[0][1:] if tokens[0].startswith("@") else tokens[0]
    if word.lower() in {"if", "for"}:
        return False
    return _LEAVE_WORD_RE.match(word) is not None


def _is_leave_prefix(token: str) -> bool:
    """Return True for DO, ELSE, or a redirection token in front of a command."""
    lower = token.lower()
    return lower in {"do", "else"} or "<" in token or ">" in token


def _line_always_leaves(line: str, *, depth_before: int = 0) -> bool:
    """Return True when the next line cannot run after this top-level line.

    A caret-continued line is unfinished. ``&&`` and ``||`` may skip the EXIT
    or GOTO, and a pipe runs it in another cmd.exe. IF and FOR may run nothing.
    """
    if _is_comment_or_label(line) or caret_joins_next_physical_line(
        line, depth_before=depth_before
    ):
        return False
    body = _command_body(line)
    if not body:
        return False
    reached = True
    for separator, segment in _command_chain(body):
        if separator in {"&&", "||"}:
            reached = False
        if reached and _segment_always_leaves(segment):
            logger.debug("Top-level line always leaves at %r", segment.strip())
            return True
    return False


def _continuation_mask(lines: List[str]) -> List[bool]:
    """Return True for each line that a previous caret joined to the prior command."""
    depths = _build_paren_depth_before(lines)
    mask: List[bool] = []
    pending = False
    for index, line in enumerate(lines):
        mask.append(pending)
        pending = caret_joins_next_physical_line(
            line, depth_before=depths[index] if index < len(depths) else 0
        )
    return mask


def _label_restarts_path(
    name: str, reachable: bool, referenced: set[str], prefixes: set[str]
) -> bool:
    """Return True when execution can be at this label and continue below it."""
    if reachable or name in referenced:
        return True
    return _matches_computed_prefix(name, prefixes)


def _close_blocks(reachable: bool, entered: List[bool], delta: int, line: str) -> bool:
    """Restore reachability for each block this line closes."""
    for _closed in range(-delta):
        if not entered:
            logger.debug("Unbalanced ')' while tracking fall-through: %s", line.strip())
            break
        reachable = entered.pop()
    return reachable


def _step_fallthrough(
    line: str,
    depth: int,
    reachable: bool,
    entered: List[bool],
    command: str,
) -> tuple[int, bool]:
    """Advance parenthesis depth and whether the next line can be fallen into.

    Depth uses the caret-joined command. An IF that continues onto ``(`` still
    opens the block, so ``exit`` inside it does not kill the label after the
    block. ``echo hi ^`` followed by ``(`` does not open a block. ``echo hi & ^``
    plus ``exit /b`` leaves, and ``echo bye ^`` plus ``exit /b`` does not.
    """
    new_depth = max(_update_paren_depth(command.strip(), depth), 0)
    delta = new_depth - depth
    if delta > 0:
        entered.extend([reachable] * delta)
    elif delta < 0:
        reachable = _close_blocks(reachable, entered, delta, line)
    if (
        depth == 0
        and new_depth == 0
        and _line_always_leaves(command, depth_before=depth)
    ):
        reachable = False
    return new_depth, reachable


def _fallthrough_label_lines(
    lines: List[str], referenced: set[str], prefixes: set[str]
) -> set[int]:
    """Return 1-based label lines that execution can enter without a jump.

    A top-level EXIT or GOTO ends that path. A label named by GOTO, CALL, or a
    computed jump starts one again. An EXIT inside parentheses does not end the
    path after the block, because the block may belong to an IF.
    """
    fallthrough: set[int] = set()
    reachable = True
    depth = 0
    entered: List[bool] = []
    continued = _continuation_mask(lines)
    depths = _build_paren_depth_before(lines)
    for index, line in enumerate(lines, start=1):
        if continued[index - 1] or _is_blank_or_comment(line):
            continue
        name = _defined_label_name(line)
        if name is not None:
            if reachable:
                fallthrough.add(index)
            reachable = _label_restarts_path(name, reachable, referenced, prefixes)
            continue
        command = _logical_command(lines, index - 1, depths)
        depth, reachable = _step_fallthrough(line, depth, reachable, entered, command)
    return fallthrough


def _check_unused_labels(lines: List[str]) -> List[LintIssue]:
    """Report labels that nothing reaches, including by falling through (S010)."""
    issues: List[LintIssue] = []
    labels: Dict[str, int] = {}
    referenced: set[str] = set()
    computed_prefixes = _computed_jump_prefixes(lines)
    continued = _continuation_mask(lines)
    depths = _build_paren_depth_before(lines)

    for i, line in enumerate(lines, start=1):
        if continued[i - 1]:
            continue
        name = _defined_label_name(line)
        if name is not None:
            labels[name] = i
            continue
        referenced.update(
            _goto_and_call_label_names(_logical_command(lines, i - 1, depths))
        )

    fallthrough = _fallthrough_label_lines(lines, referenced, computed_prefixes)
    for label_name, line_num in labels.items():
        if _label_is_live(
            label_name, line_num, referenced, computed_prefixes, fallthrough
        ):
            continue
        logger.debug(
            "S010 reports unreachable label :%s on line %d", label_name, line_num
        )
        issues.append(
            LintIssue(
                line_number=line_num,
                rule=RULES["S010"],
                context=f"Label ':{label_name}' is never reached",
            )
        )
    return issues


def _label_is_live(
    label_name: str,
    line_num: int,
    referenced: set[str],
    prefixes: set[str],
    fallthrough: set[int],
) -> bool:
    """Return True when S010 must not report this label definition."""
    if label_name in referenced or _matches_computed_prefix(label_name, prefixes):
        return True
    if line_num in fallthrough:
        logger.debug(
            "S010 skips :%s on line %d because execution falls through",
            label_name,
            line_num,
        )
        return True
    return False


def _called_subroutine_names(lines: List[str]) -> set[str]:
    """Return label names an executable ``call :name`` invokes.

    A label line is not a call: cmd ignores the rest of that line. ``call :name``
    after IF or ``||`` still counts, because those segments are executable.
    """
    called: set[str] = set()
    continued = _continuation_mask(lines)
    depths = _build_paren_depth_before(lines)
    for index, line in enumerate(lines):
        if continued[index] or _is_comment_or_label(line):
            continue
        called.update(
            _call_subroutine_label_names(_logical_command(lines, index, depths))
        )
    logger.debug("CALL subroutine targets: %s", sorted(called))
    return called


def _check_function_docs(
    line: str,
    line_number: int,
    lines: List[str],
    called: Optional[set[str]] = None,
) -> List[LintIssue]:
    """Report a CALL target with no comment above it (S018).

    GOTO targets and labels that execution merely falls through are not
    subroutines. The label's cmd lookup key is the subroutine name, so
    ``:ok:extra`` is ``ok`` and ``:start rem entry`` is ``start``. The comment
    may sit on either of the two lines above the label.
    """
    issues: List[LintIssue] = []
    label = label_key_from_line(line.strip())
    if label is None:
        return issues
    if called is None:
        called = _called_subroutine_names(lines)
    name = label[1:]
    if name not in called:
        logger.debug("S018 skips :%s on line %d; nothing CALLs it", name, line_number)
        return issues

    doc_found = False
    for j in range(max(0, line_number - 3), line_number - 1):
        if j < len(lines) and _is_comment_line(lines[j]):
            doc_found = True
            break

    if not doc_found:
        logger.debug(
            "S018 reports undocumented CALL target :%s on line %d", name, line_number
        )
        issues.append(
            LintIssue(
                line_number=line_number,
                rule=RULES["S018"],
                context="Function/subroutine lacks documentation",
            )
        )

    return issues
