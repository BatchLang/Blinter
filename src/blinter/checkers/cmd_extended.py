"""Extra cmd.exe checks kept out of syntax.py and warnings.py so those stay smaller."""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Dict, List, Optional, Set

from blinter.constants import MAX_LINE_LENGTH, SYSTEM_ENV_VARS
from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import (
    _command_body,
    _is_comment_line,
    _is_echo_statement,
    _split_pipe_stages,
    _split_tokens,
    _split_unquoted,
)
from blinter.parsing.structure import _paren_depth_before_line
from blinter.rules.registry import RULES

_USER_ARG_PERCENT_RE = re.compile(
    r"(?<!%)%~?[fdpnxsatz]*[1-9]|(?<!%)%\*",
    re.IGNORECASE,
)
_USER_ARG_DELAYED_RE = re.compile(
    r"!~?[fdpnxsatz]*[1-9]!|!\*!",
    re.IGNORECASE,
)
_CD_EXPANSION_RE = re.compile(
    r"%__CD__%|%CD%|!CD!",
    re.IGNORECASE,
)
_ALLUSERPROFILE_RE = re.compile(
    r"%ALLUSERPROFILE%|!ALLUSERPROFILE!|A\+L\+USERPROFILE",
    re.IGNORECASE,
)
_TIME_RAW_PERCENT_RE = re.compile(r"%TIME%", re.IGNORECASE)
_TIME_RAW_DELAYED_RE = re.compile(r"!TIME!", re.IGNORECASE)
_TIME_SAFE_RE = re.compile(r"[%!]TIME: =0[%!]", re.IGNORECASE)
_DEVICE_COLON_RE = re.compile(r"(?<![A-Za-z])(NUL|CON|PRN):", re.IGNORECASE)
_MALFORMED_REDIR_RE = re.compile(
    r"[12]\s*(?:>>|>|<)\s+&",
)
_STREAM_MERGE_RE = re.compile(r"[12]>&[12]")
_SET_NAME_RE = re.compile(
    r'set\s+(?:/[a-z]\s+)?"?([A-Za-z_][\w]*)\s*=',
    re.IGNORECASE,
)
_SET_P_NAME_RE = re.compile(
    r'set\s+/p\s+"?([A-Za-z_][\w]*)\s*=',
    re.IGNORECASE,
)
_FOR_F_HEAD_RE = re.compile(r"for\s+/f\b", re.IGNORECASE)
_FOR_F_IN_WORD_RE = re.compile(r"\bin\b", re.IGNORECASE)
_FOR_F_SINGLE_QUOTE_BODY_RE = re.compile(r"\s*\(\s*'([^']*)'")
_FOR_F_USEBACKQ_WORD_RE = re.compile(r"usebackq", re.IGNORECASE)
_FOR_F_BACKTICK_IN_RE = re.compile(r"\bin\s*\(\s*`([^`]*)`", re.IGNORECASE)
_UNARY_IF_RE = re.compile(
    r"\bif\s+(?:/i\s+)?(?:not\s+)?(?:exist|defined|errorlevel|cmdextversion)\b",
    re.IGNORECASE,
)
_IF_COMPARE_OP_RE = re.compile(r"==|equ|neq|lss|leq|gtr|geq", re.IGNORECASE)
_ECHO_OFF_ON_RE = re.compile(r"echo\s+(off|on)\s*$", re.IGNORECASE)
_REDIR_TOKEN_RE = re.compile(r"(?:\d+)?(?:>>|>|<)(?:&\d+|\S+)")
_SWITCH_TOKEN_RE = re.compile(r"^/[A-Za-z0-9]+$")
_PLAIN_SET_RE = re.compile(r"^set\s+(?!/)", re.IGNORECASE)
_PATH_CMD_RE = re.compile(r"^path(?:\s|$)", re.IGNORECASE)
_PROMPT_CMD_RE = re.compile(r"^prompt(?:\s|$)", re.IGNORECASE)
_TITLE_RE = re.compile(r"^title(?:\s|$)", re.IGNORECASE)
_SYSTEM_VAR_ALT = "|".join(
    sorted((re.escape(name) for name in SYSTEM_ENV_VARS), key=len, reverse=True)
)
_SET_SYSTEM_RE = re.compile(
    rf'set\s+(?:/[a-z]\s+)*"?({_SYSTEM_VAR_ALT})\s*=',
    re.IGNORECASE,
)

_ALLOWED_SWITCHES: Dict[str, Optional[frozenset[str]]] = {
    "if": frozenset({"i"}),
    "for": frozenset({"d", "f", "l", "r"}),
    "set": frozenset({"a", "p"}),
    "exit": frozenset({"b"}),
    "cd": frozenset({"d"}),
    "chdir": frozenset({"d"}),
    "date": frozenset({"t"}),
    "time": frozenset({"t"}),
    "shift": None,
}
_NO_SWITCH_COMMANDS = frozenset(
    {
        "goto",
        "md",
        "mkdir",
        "setlocal",
        "endlocal",
        "cls",
        "pause",
        "ver",
        "popd",
    }
)
_NO_ARG_COMMANDS = frozenset({"cls", "pause", "ver", "popd", "endlocal"})
_EXTENDED_RULES = {
    "E043": RULES["E043"],
    "E044": RULES["E044"],
    "E045": RULES["E045"],
    "E046": RULES["E046"],
    "E047": RULES["E047"],
    "S029": RULES["S029"],
    "S030": RULES["S030"],
    "SEC001": RULES["SEC001"],
    "SEC025": RULES["SEC025"],
    "W064": RULES["W064"],
    "W065": RULES["W065"],
    "W066": RULES["W066"],
    "W067": RULES["W067"],
    "W068": RULES["W068"],
    "W069": RULES["W069"],
    "W070": RULES["W070"],
    "W071": RULES["W071"],
    "E048": RULES["E048"],
}
_SPECIALS_IN_FOR_F = frozenset("&<>|")


def _strip_double_quoted_strings(text: str) -> str:
    """Replace double-quoted spans with empty quotes so unquoted forms remain."""
    return re.sub(r'"[^"]*"', '""', text)


def _is_caret_escaped(text: str, index: int) -> bool:
    """Return True when the character at index is escaped by an odd caret run."""
    caret_count = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "^":
        caret_count += 1
        pos -= 1
    return caret_count % 2 == 1


def _split_amp_commands(text: str) -> List[str]:
    """Split on unquoted ``&`` / ``&&`` / ``||`` without breaking ``2>&1``."""
    return _split_unquoted(text, andand_only=False)


def _split_andand_pairs(text: str) -> List[tuple[str, str]]:
    """Return (left, right) pairs for each unquoted ``&&`` chain."""
    parts = _split_unquoted(text, andand_only=True)
    stripped_parts = [part.strip() for part in parts]
    return [
        (left, right) for left, right in zip(stripped_parts, stripped_parts[1:]) if left
    ]


def _strip_redirections(text: str) -> str:
    """Remove redirection tokens so leftover words are real arguments."""
    return _REDIR_TOKEN_RE.sub(" ", text).strip()


def _issue(line_num: int, code: str, context: str) -> LintIssue:
    """Build a lint issue and log the decision point."""
    logger.debug("Rule %s on line %s: %s", code, line_num, context)
    return LintIssue(line_number=line_num, rule=_EXTENDED_RULES[code], context=context)


def _skip_comment_or_echo(stripped: str) -> bool:
    """True for REM/:: comments or ECHO output lines."""
    return _is_comment_line(stripped) or _is_echo_statement(stripped)


def check_extended_syntax_line(
    line: str, line_num: int, lines: Optional[List[str]] = None
) -> List[LintIssue]:
    """Line-level extra syntax errors (E043-E047)."""
    stripped = line.strip()
    if stripped.startswith("::"):
        return _check_e043_colon_block(stripped, line_num, lines)
    issues: List[LintIssue] = []
    if not stripped or _is_comment_line(stripped):
        return issues
    issues.extend(_check_e044_else_newline(stripped, line_num))
    issues.extend(_check_e045_switches(stripped, line_num))
    issues.extend(_check_e046_malformed_redir(stripped, line_num))
    issues.extend(_check_e047_for_f_unescaped(stripped, line_num))
    issues.extend(_check_e047_echo_parens(stripped, line_num, lines))
    return issues


def _check_e043_colon_block(
    stripped: str, line_num: int, lines: Optional[List[str]]
) -> List[LintIssue]:
    """E043: ``::`` used as a comment inside a parenthesized block."""
    if not stripped.startswith("::"):
        return []
    if lines is None:
        return []
    if _paren_depth_before_line(lines, line_num) <= 0:
        return []
    return [
        _issue(
            line_num,
            "E043",
            "Double-colon comments inside parentheses are parsed as labels and break the block",
        )
    ]


def _check_e044_else_newline(stripped: str, line_num: int) -> List[LintIssue]:
    """E044: ELSE as the first token on a new line is not paired with IF."""
    body = _command_body(stripped)
    if not body:
        return []
    tokens = _split_tokens(body.lstrip(")").lstrip())
    if not tokens:
        tokens = _split_tokens(body)
    first = tokens[0].lower() if tokens else ""
    # A valid close is ") ELSE"; a bare ELSE (optionally after stray whitespace) is the bug.
    if stripped.lower().startswith(")") and re.search(
        r"\)\s*else\b", stripped, re.IGNORECASE
    ):
        return []
    if first != "else":
        return []
    return [
        _issue(
            line_num,
            "E044",
            "ELSE must share the line with the closing parenthesis of the IF block",
        )
    ]


def _leading_switch_tokens(tokens: List[str]) -> List[str]:
    """Return slash-switches that appear immediately after the command word."""
    switches: List[str] = []
    for token in tokens[1:]:
        if token == "/?":
            continue
        if _SWITCH_TOKEN_RE.match(token):
            switches.append(token)
            continue
        break
    return switches


def _shift_switch_is_invalid(token: str) -> bool:
    """True when SHIFT uses a non-digit switch (numeric range is W050)."""
    body = token[1:]
    return not body.isdigit()


def _e045_switch_issues(
    command: str, leading: List[str], line_num: int
) -> List[LintIssue]:
    """Return E045 issues for invalid leading slash-switches."""
    issues: List[LintIssue] = []
    if command in _NO_SWITCH_COMMANDS:
        for token in leading:
            issues.append(
                _issue(
                    line_num,
                    "E045",
                    f"{command.upper()} does not accept switch {token}",
                )
            )
        return issues
    if command not in _ALLOWED_SWITCHES:
        return issues
    allowed = _ALLOWED_SWITCHES[command]
    for token in leading:
        if command == "shift":
            if _shift_switch_is_invalid(token):
                issues.append(
                    _issue(
                        line_num,
                        "E045",
                        f"SHIFT does not accept switch {token}",
                    )
                )
            continue
        if allowed is None:
            continue
        if token[1:].lower() not in allowed:
            issues.append(
                _issue(
                    line_num,
                    "E045",
                    f"{command.upper()} does not accept switch {token}",
                )
            )
    return issues


def _check_e045_switches(stripped: str, line_num: int) -> List[LintIssue]:
    """E045: unknown slash-switches or extra args on internals."""
    if _skip_comment_or_echo(stripped):
        return []
    issues: List[LintIssue] = []
    body = _command_body(stripped) or stripped
    for raw_segment in _split_amp_commands(body):
        for raw_stage in _split_pipe_stages(raw_segment):
            _collect_e045_stage_issues(raw_stage, line_num, issues)
    return issues


def _collect_e045_stage_issues(
    raw_stage: str, line_num: int, issues: List[LintIssue]
) -> None:
    """Record E045 findings for one pipe stage."""
    segment = _strip_redirections(raw_stage).strip().lstrip("@").lstrip("(").strip()
    if not segment:
        return
    tokens = _split_tokens(segment)
    if not tokens:
        return
    command = tokens[0].lower()
    issues.extend(
        _e045_switch_issues(command, _leading_switch_tokens(tokens), line_num)
    )
    if command not in _NO_ARG_COMMANDS:
        return
    remainder = [
        tok for tok in tokens[1:] if not _SWITCH_TOKEN_RE.match(tok) and tok != "/?"
    ]
    if not remainder:
        return
    issues.append(
        _issue(
            line_num,
            "E045",
            f"{command.upper()} does not take arguments",
        )
    )


def _check_e046_malformed_redir(stripped: str, line_num: int) -> List[LintIssue]:
    """E046: space between ``>``/``>>``/``<`` and ``&`` splits handle duplication."""
    if _MALFORMED_REDIR_RE.search(stripped):
        return [
            _issue(
                line_num,
                "E046",
                "Malformed stream merge; write 2>&1 or 1>&2 with no space before &",
            )
        ]
    return []


def _unescaped_specials(command_text: str) -> bool:
    """True when ``& < > |`` appear unescaped in a FOR /F command string."""
    for index, char in enumerate(command_text):
        if char in _SPECIALS_IN_FOR_F and not _is_caret_escaped(command_text, index):
            return True
    return False


def _for_f_single_quote_commands(text: str) -> List[str]:
    """Return ``IN ('command')`` bodies of each FOR /F, scanning once.

    Each FOR /F is paired with the first following ``in`` word, as in
    ``for /f ... in ('cmd')``. A single forward pass keeps this linear on long
    lines, where a lazy ``.*`` pattern would rescan the line for every FOR /F.
    """
    commands: List[str] = []
    position = 0
    while True:
        head = _FOR_F_HEAD_RE.search(text, position)
        if head is None:
            break
        in_word = _FOR_F_IN_WORD_RE.search(text, head.end())
        if in_word is None:
            break
        body = _FOR_F_SINGLE_QUOTE_BODY_RE.match(text, in_word.end())
        if body is None:
            position = in_word.end()
            continue
        commands.append(body.group(1))
        position = body.end()
    return commands


def _for_f_usebackq_commands(text: str) -> List[str]:
    """Return the backtick ``IN (`command`)`` body that follows ``usebackq``.

    Mirrors one greedy match per FOR /F: the last ``in (`...`)`` after the first
    ``usebackq`` that follows the FOR /F keyword, found without nested scans.
    """
    commands: List[str] = []
    position = 0
    while True:
        head = _FOR_F_HEAD_RE.search(text, position)
        if head is None:
            break
        option = _FOR_F_USEBACKQ_WORD_RE.search(text, head.end())
        if option is None:
            break
        bodies = list(_FOR_F_BACKTICK_IN_RE.finditer(text, option.end()))
        if not bodies:
            break
        commands.append(bodies[-1].group(1))
        position = bodies[-1].end()
    return commands


def _check_e047_for_f_unescaped(stripped: str, line_num: int) -> List[LintIssue]:
    """E047: unescaped specials inside FOR /F ``IN ('command')`` / usebackq ticks."""
    snippets: List[str] = []
    if "usebackq" not in stripped.lower():
        snippets.extend(_for_f_single_quote_commands(stripped))
    snippets.extend(_for_f_usebackq_commands(stripped))
    for snippet in snippets:
        if _unescaped_specials(snippet):
            return [
                _issue(
                    line_num,
                    "E047",
                    "Unescaped & < > | inside FOR /F IN ('command'); escape as ^& ^< ^> ^|",
                )
            ]
    return []


def _echo_body(stripped: str) -> Optional[str]:
    """Return ECHO output text, or None when the line is not ECHO."""
    match = re.match(r"@?echo(?:\s+|(\())", stripped, re.IGNORECASE)
    if match is None:
        return None
    if match.group(1):
        return stripped[match.end() - 1 :]
    return stripped[match.end() :]


def _echo_has_unescaped_paren(body: str) -> bool:
    """True when ECHO text has an unquoted, unescaped closing parenthesis.

    An opening parenthesis in ECHO text does not end a parenthesized block.
    Only an unescaped ``)`` does.
    """
    unquoted = _strip_double_quoted_strings(body)
    for index, char in enumerate(unquoted):
        if char == ")" and not _is_caret_escaped(unquoted, index):
            return True
    return False


def _check_e047_echo_parens(
    stripped: str, line_num: int, lines: Optional[List[str]]
) -> List[LintIssue]:
    """E047: unescaped parentheses in ECHO inside a parenthesized block."""
    if lines is None:
        return []
    body = _echo_body(stripped)
    if body is None:
        return []
    depth = _paren_depth_before_line(lines, line_num)
    if depth <= 0:
        if re.search(r"\(\s*@?echo\b", stripped, re.IGNORECASE):
            depth = 1
        else:
            return []
    if not _echo_has_unescaped_paren(body):
        return []
    return [
        _issue(
            line_num,
            "E047",
            "Unescaped ) in ECHO inside a block; escape the closing parenthesis as ^)",
        )
    ]


def check_extended_warning_line(
    line: str,
    line_num: int,
    lines: Optional[List[str]] = None,
    file_path: str = "",
) -> List[LintIssue]:
    """Line-level extra warnings (W064-W067, W069-W070)."""
    issues: List[LintIssue] = []
    stripped = line.strip()
    if not stripped or _is_comment_line(stripped):
        return issues
    issues.extend(_check_w064_alluserprofile(stripped, line_num))
    issues.extend(_check_w065_if_wildcard(stripped, line_num))
    issues.extend(_check_w066_redir_not_at_end(stripped, line_num))
    issues.extend(_check_w067_set_system_var(stripped, line_num))
    issues.extend(_check_w069_time_leading_space(stripped, line_num, lines))
    issues.extend(_check_w070_set_andand(stripped, line_num, file_path))
    return issues


def check_extended_warning_file(
    lines: List[str], file_path: str = ""
) -> List[LintIssue]:
    """File-level warnings that need block state (W068, W071)."""
    del file_path
    issues = _check_w068_block_percent(lines)
    issues.extend(_check_w071_block_pseudo(lines))
    return issues


def issues_for_overlong_lines(line_numbers: List[int]) -> List[LintIssue]:
    """E048 for lines blanked because they exceed MAX_LINE_LENGTH."""
    return [
        _issue(
            line_number,
            "E048",
            f"Line exceeds {MAX_LINE_LENGTH} characters; "
            "the rest of the file was still linted",
        )
        for line_number in line_numbers
    ]


_W071_ERRORLEVEL_RE = re.compile(r"%errorlevel(?:%|:)", re.IGNORECASE)
_W071_VOLATILE_RE = re.compile(r"%(random|time|date)(?:%|:)", re.IGNORECASE)


def _w071_command_segments(stripped: str) -> List[str]:
    """Return command pieces on a line, skipping comments and labels."""
    segments: List[str] = []
    for segment in _split_amp_commands(stripped):
        text = segment.strip().lstrip("@")
        if not text or _is_comment_line(text) or text.startswith(":"):
            continue
        segments.append(segment)
    return segments


def _w071_issues_for_segment(
    line_num: int, segment: str, prior_commands: int, command_count: int
) -> List[LintIssue]:
    """Flag stale pseudo-variables in one command segment."""
    issues: List[LintIssue] = []
    if prior_commands > 0 and _W071_ERRORLEVEL_RE.search(segment):
        issues.append(
            _issue(
                line_num,
                "W071",
                "%errorlevel% is expanded when the block is parsed and does not "
                "see earlier commands in the block; use !errorlevel! or IF ERRORLEVEL",
            )
        )
    if command_count > 1:
        seen: Set[str] = set()
        for match in _W071_VOLATILE_RE.finditer(segment):
            captured = match.group(1)
            if not isinstance(captured, str):
                continue
            name = captured.lower()
            if name in seen:
                continue
            seen.add(name)
            issues.append(
                _issue(
                    line_num,
                    "W071",
                    f"%{name}% is expanded once when the block is parsed; "
                    f"use !{name}! with EnableDelayedExpansion",
                )
            )
    return issues


def _w071_flush_block(
    block: List[tuple[int, List[str]]],
) -> List[LintIssue]:
    """Emit W071 for one parenthesized block."""
    command_count = sum(len(segments) for _line_num, segments in block)
    issues: List[LintIssue] = []
    prior = 0
    for line_num, segments in block:
        for segment in segments:
            issues.extend(
                _w071_issues_for_segment(line_num, segment, prior, command_count)
            )
            prior += 1
    return issues


def _check_w071_block_pseudo(lines: List[str]) -> List[LintIssue]:
    """W071: parse-time %errorlevel%, %random%, %time%, and %date% inside a block."""
    issues: List[LintIssue] = []
    block: List[tuple[int, List[str]]] = []
    for line_num, line in enumerate(lines, 1):
        depth_before = _paren_depth_before_line(lines, line_num)
        if depth_before <= 0:
            if block:
                issues.extend(_w071_flush_block(block))
                block = []
            continue
        stripped = line.strip()
        if not stripped or _is_comment_line(stripped) or stripped.startswith(")"):
            continue
        block.append((line_num, _w071_command_segments(stripped)))
    if block:
        issues.extend(_w071_flush_block(block))
    return issues


def _check_w064_alluserprofile(stripped: str, line_num: int) -> List[LintIssue]:
    """W064: ALLUSERPROFILE misspelling of ALLUSERSPROFILE."""
    if not _ALLUSERPROFILE_RE.search(stripped):
        return []
    return [
        _issue(
            line_num,
            "W064",
            "ALLUSERPROFILE is a typo; use %ALLUSERSPROFILE%",
        )
    ]


def _check_w065_if_wildcard(stripped: str, line_num: int) -> List[LintIssue]:
    """W065: ``*`` / ``?`` in IF == comparisons are literal, not globs."""
    if not re.match(r"@?if\b", stripped, re.IGNORECASE):
        return []
    if _UNARY_IF_RE.search(stripped):
        return []
    if _IF_COMPARE_OP_RE.search(stripped) is None:
        return []
    if "*" not in stripped and "?" not in stripped:
        return []
    return [
        _issue(
            line_num,
            "W065",
            "IF == does not glob; * and ? are literal characters",
        )
    ]


def _check_w066_redir_not_at_end(stripped: str, line_num: int) -> List[LintIssue]:
    """W066: ``2>&1`` / ``1>&2`` should be the last token of the command."""
    for segment in _split_amp_commands(stripped):
        match = _STREAM_MERGE_RE.search(segment)
        if match is None:
            continue
        after = segment[match.end() :].strip()
        if after:
            return [
                _issue(
                    line_num,
                    "W066",
                    "Place 2>&1 at the end of the command so stderr is captured",
                )
            ]
    return []


def _regex_group(match: re.Match[str], index: int = 1) -> str:
    """Return a regex capture as ``str`` so mypy does not see ``str | Any``."""
    captured = match.group(index)
    return "" if captured is None else str(captured)


def _check_w067_set_system_var(stripped: str, line_num: int) -> List[LintIssue]:
    """W067: SET of a real system environment variable."""
    match = _SET_SYSTEM_RE.search(stripped)
    if match is None:
        return []
    name = _regex_group(match).upper()
    return [
        _issue(
            line_num,
            "W067",
            f"SET {name}= overwrites a system environment variable",
        )
    ]


def _check_w069_time_leading_space(
    stripped: str, line_num: int, lines: Optional[List[str]]
) -> List[LintIssue]:
    """W069: raw %TIME% keeps a leading space before 10:00."""
    if _is_echo_statement(stripped) or _TITLE_RE.match(stripped):
        return []
    if _TIME_SAFE_RE.search(stripped):
        return []
    if lines is not None:
        start = max(0, line_num - 6)
        nearby = "".join(lines[start:line_num])
        if _TIME_SAFE_RE.search(nearby):
            return []
    if _TIME_RAW_PERCENT_RE.search(stripped) or _TIME_RAW_DELAYED_RE.search(stripped):
        return [
            _issue(
                line_num,
                "W069",
                "Replace the leading space in %TIME% with %TIME: =0% before concatenating",
            )
        ]
    return []


def _is_errorlevel_sensitive_cmd(segment: str) -> bool:
    """True for SET (not /A /P), PATH, or PROMPT commands."""
    body = segment.strip().lstrip("@").lstrip("(").strip()
    if _PLAIN_SET_RE.match(body):
        return True
    if _PATH_CMD_RE.match(body) or _PROMPT_CMD_RE.match(body):
        return True
    return False


def _check_w070_set_andand(
    stripped: str, line_num: int, file_path: str
) -> List[LintIssue]:
    """W070: SET/PATH/PROMPT chained with && in a .bat file."""
    if not file_path.lower().endswith(".bat"):
        return []
    for left, _right in _split_andand_pairs(stripped):
        if _is_errorlevel_sensitive_cmd(left):
            return [
                _issue(
                    line_num,
                    "W070",
                    "In .bat files SET/PATH/PROMPT do not reset ERRORLEVEL, so && is unreliable",
                )
            ]
    return []


# typeshed types the lru_cache wrapper as Any under disallow_any_expr.
@lru_cache(maxsize=4096)  # type: ignore[misc]
def _percent_expansion_pattern(name: str) -> re.Pattern[str]:
    """Compiled ``%name%`` / ``%name:...%`` matcher.

    Callers pass lowercased names. The cache is bounded so a long-running
    process does not keep a pattern for every name it has ever seen.
    """
    return re.compile(rf"%{re.escape(name)}(?:%|:)", re.IGNORECASE)


def _percent_expansion_of(name: str, text: str) -> bool:
    """True when ``%name%`` or ``%name:...%`` appears (not delayed ``!name!``)."""
    return _percent_expansion_pattern(name).search(text) is not None


def _effective_block_depth(stripped: str, depth_before: int) -> int:
    """Depth for commands that sit after an opening ``(`` on this line."""
    if depth_before > 0:
        return depth_before
    if re.search(r"\(\s*set\s+", stripped, re.IGNORECASE):
        return depth_before + 1
    return depth_before


def _set_name_at_segment_start(segment: str) -> Optional[str]:
    """Lowercased SET variable at the start of a command segment, if any."""
    set_match = _SET_NAME_RE.match(segment.strip().lstrip("@"))
    if set_match is None:
        return None
    return _regex_group(set_match).lower()


def _drop_deeper_assignments(assigned: Dict[int, Set[str]], depth_before: int) -> None:
    """Forget variables assigned inside blocks that have already closed."""
    for depth_key in [key for key in assigned if key > depth_before]:
        del assigned[depth_key]


def _w068_expansions_in_segment(
    line_num: int,
    segment: str,
    assigned: Dict[int, Set[str]],
    depth: int,
) -> List[LintIssue]:
    """W068 hits for ``%name%`` of a variable already SET in this block."""
    if "%" not in segment:
        return []
    set_on_segment = _set_name_at_segment_start(segment)
    issues: List[LintIssue] = []
    for depth_key, names in assigned.items():
        if depth_key > depth:
            continue
        for name in names:
            if set_on_segment == name:
                continue
            if not _percent_expansion_of(name, segment):
                continue
            issues.append(
                _issue(
                    line_num,
                    "W068",
                    f"%{name}% is expanded when the block is parsed; "
                    f"use !{name}! with EnableDelayedExpansion",
                )
            )
    return issues


def _record_segment_assignment(
    assigned: Dict[int, Set[str]], depth: int, segment: str
) -> None:
    """Remember a SET name found anywhere in this command segment."""
    set_match = _SET_NAME_RE.search(segment)
    if set_match is None:
        return
    assigned.setdefault(depth, set()).add(_regex_group(set_match).lower())


def _check_w068_block_percent(lines: List[str]) -> List[LintIssue]:
    """W068: %var% after SET of that var inside the same parenthesized block."""
    issues: List[LintIssue] = []
    assigned: Dict[int, Set[str]] = {}
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        depth_before = _paren_depth_before_line(lines, line_num)
        _drop_deeper_assignments(assigned, depth_before)
        if depth_before == 0:
            assigned.clear()
        if not stripped or _is_comment_line(stripped):
            continue
        depth = _effective_block_depth(stripped, depth_before)
        if depth <= 0:
            continue
        for segment in _split_amp_commands(stripped):
            issues.extend(
                _w068_expansions_in_segment(line_num, segment, assigned, depth)
            )
            _record_segment_assignment(assigned, depth, segment)
    return issues


def check_extended_style_line(line: str, line_num: int) -> List[LintIssue]:
    """S029 @command after line 1 and S030 redundant device colon."""
    issues: List[LintIssue] = []
    stripped = line.strip()
    if not stripped or _is_comment_line(stripped):
        issues.extend(_check_s030_device_colon(stripped, line_num) if stripped else [])
        return issues
    issues.extend(_check_s029_at_prefix(stripped, line_num))
    issues.extend(_check_s030_device_colon(stripped, line_num))
    return issues


def _check_s029_at_prefix(stripped: str, line_num: int) -> List[LintIssue]:
    """S029: ``@command`` after the first line except ``@ECHO OFF`` / ``ON``."""
    if line_num <= 1 or not stripped.startswith("@"):
        return []
    rest = stripped[1:].lstrip()
    if _ECHO_OFF_ON_RE.match(rest):
        return []
    return [
        _issue(
            line_num,
            "S029",
            "Use @ECHO OFF on the first line instead of prefixing later commands with @",
        )
    ]


def _check_s030_device_colon(stripped: str, line_num: int) -> List[LintIssue]:
    """S030: NUL:/CON:/PRN: redundant trailing colon."""
    if not stripped or _is_comment_line(stripped):
        return []
    match = _DEVICE_COLON_RE.search(stripped)
    if match is None:
        return []
    device = _regex_group(match).upper()
    return [
        _issue(
            line_num,
            "S030",
            f"{device}: is redundant; write {device} without a colon",
        )
    ]


def check_sec025_unquoted_cd(line: str, line_num: int) -> List[LintIssue]:
    """SEC025: unquoted %CD% / %__CD__% / !CD!."""
    stripped = line.strip()
    if not stripped or _is_comment_line(stripped):
        return []
    unquoted = _strip_double_quoted_strings(stripped)
    if _CD_EXPANSION_RE.search(unquoted) is None:
        return []
    return [
        _issue(
            line_num,
            "SEC025",
            'Quote current-directory expansion, for example "%CD%"',
        )
    ]


def _var_used_unquoted(text: str, name: str) -> bool:
    """True when %name% or !name! remains outside double quotes."""
    unquoted = _strip_double_quoted_strings(text)
    percent = rf"%{re.escape(name)}(?:%|:)"
    delayed = rf"!{re.escape(name)}(?:!|:)"
    if re.search(percent, unquoted, re.IGNORECASE):
        return True
    if re.search(delayed, unquoted, re.IGNORECASE):
        return True
    return False


def _is_defined_check_only(text: str, name: str) -> bool:
    """True when the only mention is IF DEFINED name (not an unquoted expansion)."""
    if re.search(
        rf"\bif\s+(?:/i\s+)?(?:not\s+)?defined\s+{re.escape(name)}\b",
        text,
        re.IGNORECASE,
    ):
        return not _var_used_unquoted(text, name)
    return False


def check_sec001_same_line(stripped: str, line_num: int) -> Optional[LintIssue]:
    """SEC001 when SET /P and an unquoted use share the same line (e.g. ``&&``)."""
    match = _SET_P_NAME_RE.search(stripped)
    if match is None:
        return None
    name = _regex_group(match)
    after = stripped[match.end() :]
    if not _var_used_unquoted(after, name):
        return None
    return _issue(
        line_num,
        "SEC001",
        f"SET /P {name} is used unquoted on the same line and can inject commands",
    )


def check_sec001_setp_dataflow(lines: List[str]) -> List[LintIssue]:
    """SEC001: SET /P names later used unquoted in a command."""
    issues: List[LintIssue] = []
    pending: Dict[str, int] = {}
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or _is_comment_line(stripped):
            continue
        setp_match = _SET_P_NAME_RE.search(stripped)
        for match in _SET_P_NAME_RE.finditer(stripped):
            pending[_regex_group(match).lower()] = line_num
        for name in list(pending):
            if _is_defined_check_only(stripped, name):
                continue
            if setp_match is not None:
                after = stripped[setp_match.end() :]
                if _var_used_unquoted(after, name):
                    continue
            if setp_match is None and _var_used_unquoted(stripped, name):
                issues.append(
                    _issue(
                        line_num,
                        "SEC001",
                        f"SET /P {name} is later used unquoted and can inject commands",
                    )
                )
    return issues


def has_unquoted_user_args(stripped: str) -> bool:
    """True when unquoted %1-%9, %*, %~1 or delayed equivalents appear."""
    unquoted = _strip_double_quoted_strings(stripped)
    if _USER_ARG_PERCENT_RE.search(unquoted):
        return True
    if _USER_ARG_DELAYED_RE.search(unquoted):
        return True
    return False
