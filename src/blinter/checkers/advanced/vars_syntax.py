"""FOR-loop, variable, and string-operation syntax checks."""

import re
from typing import List

from blinter.logging_config import logger
from blinter.models import LintIssue
from blinter.parsing.context import (
    _split_command_separators,
    _split_tokens,
    _strip_if_predicate,
)
from blinter.rules.expansion_data import VALID_MODIFIERS
from blinter.rules.helpers import (
    PERCENT_TILDE_TOKEN_RE,
    REPLACEMENT_OP_RE,
    SUBSTRING_OP_RE,
    strip_for_metavar_tilde_tokens,
)
from blinter.rules.registry import RULES

_FOR_F_OPTIONS_RE = re.compile(
    r'for\s+/f\s+(?:"([^"]*)"|([^"\s]+))',
    re.IGNORECASE,
)
_FOR_LOOP_VAR_RE = re.compile(r"%%([a-zA-Z])", re.IGNORECASE)
_FOR_BODY_VAR_RE = re.compile(r"%%([a-zA-Z])")
_SKIP_VARIABLE_RE = re.compile(r"(?:%[^%]+%|![^!]+!)")
_INNER_FOR_F_RE = re.compile(r"\bfor\s+/f\b", re.IGNORECASE)


def _is_valid_for_f_skip_value(skip_value: str) -> bool:
    """Return True when skip= is a positive literal or expandable variable."""
    if re.fullmatch(r"\d+", skip_value):
        return int(skip_value) >= 1
    return _SKIP_VARIABLE_RE.fullmatch(skip_value) is not None


def _for_f_options_string(line: str) -> str:
    match = _FOR_F_OPTIONS_RE.search(line)
    if not match:
        return ""
    return str(match.group(1) or match.group(2) or "")


def _for_f_token_slot_count(tokens_value: str) -> int:
    """Return how many implicit FOR /F loop variables tokens= assigns."""
    value = tokens_value.strip()
    if not value or value == "*":
        return 1
    count = 0
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if part.endswith("*"):
            prefix = part[:-1].strip()
            if prefix and re.fullmatch(r"\d+", prefix):
                count += 2
            elif prefix and re.fullmatch(r"\d+-\d+", prefix):
                range_match = re.fullmatch(r"(\d+)-(\d+)", prefix)
                if range_match:
                    start = int(range_match.group(1))
                    end = int(range_match.group(2))
                    count += max(end - start + 1, 0) + 1
            else:
                count += 1
            continue
        range_match = re.fullmatch(r"(\d+)-(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            count += max(end - start + 1, 0)
            continue
        if re.fullmatch(r"\d+", part):
            count += 1
    return max(count, 1)


def _check_for_f_suboptions(line: str, line_number: int) -> List[LintIssue]:
    """Check FOR /F skip= and tokens= suboptions (E038)."""
    options = _for_f_options_string(line)
    if not options:
        return []

    issues: List[LintIssue] = []

    skip_match = re.search(r"skip=(\S+)", options, re.IGNORECASE)
    if skip_match:
        skip_value = skip_match.group(1)
        if not _is_valid_for_f_skip_value(skip_value):
            issues.append(
                LintIssue(
                    line_number,
                    RULES["E038"],
                    context="FOR /F skip= must be a positive integer per FOR /?",
                )
            )

    tokens_match = re.search(r"tokens=([^\s\"']+)", options, re.IGNORECASE)
    if tokens_match:
        tokens_value = tokens_match.group(1)
        if re.search(r"[a-zA-Z]", tokens_value, re.IGNORECASE):
            issues.append(
                LintIssue(
                    line_number,
                    RULES["E038"],
                    context="FOR /F tokens= contains invalid non-numeric characters",
                )
            )
        else:
            for range_match in re.finditer(r"(\d+)-(\d+)", tokens_value):
                start = int(range_match.group(1))
                end = int(range_match.group(2))
                if start > end:
                    issues.append(
                        LintIssue(
                            line_number,
                            RULES["E038"],
                            context="FOR /F tokens= range must be ascending (for example 1-5)",
                        )
                    )
                    break

    return issues


def _for_in_close_index(text: str) -> int | None:
    """Return the index of the ')' that closes FOR IN (, if present."""
    open_match = re.search(r"\bin\s*\(", text, re.IGNORECASE)
    if not open_match:
        return None
    start = open_match.end()
    depth = 1
    quote = ""
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char == "^":
            index += 2
            continue
        if char in ('"', "'", "`"):
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    fallback = re.search(r"\bin\s*\(([^)]*)\)", text, re.IGNORECASE)
    if fallback:
        logger.debug(
            "FOR /F parentheses did not balance; using first-close fallback: %s",
            text.strip(),
        )
        return fallback.end() - 1
    return None


def _for_do_span(text: str) -> tuple[int, int] | None:
    """Return start/end of the FOR DO token after IN (...)."""
    close_at = _for_in_close_index(text)
    search_from = close_at + 1 if close_at is not None else 0
    match = re.search(r"\bdo\b", text[search_from:], re.IGNORECASE)
    if match is None:
        return None
    start = search_from + match.start()
    return start, search_from + match.end()


def _prefix_allows_for_f_command(prefix: str) -> bool:
    """Return True when prefix is only IF/@/DO/ELSE, not another command."""
    parts = _split_command_separators(prefix)
    tail = parts[-1] if parts else prefix
    tokens = _split_tokens(tail.strip().lstrip("(").strip())
    while tokens and tokens[0] == "@":
        tokens = tokens[1:]
    while tokens and tokens[0].lower() in ("do", "else"):
        tokens = tokens[1:]
    while True:
        stripped = _strip_if_predicate(tokens)
        if stripped == tokens:
            break
        tokens = stripped
    return not tokens


def _for_do_body_text(lines: list[str], line_number: int) -> str:
    """Return FOR DO body text for same-line or multiline parenthesized blocks."""
    if line_number < 1 or line_number > len(lines):
        return ""
    current = lines[line_number - 1]
    do_span = _for_do_span(current)
    if do_span is None:
        return ""
    after_do = current[do_span[1] :]
    if not re.match(r"\s*\(", after_do):
        return after_do
    parts = [after_do]
    combined = after_do
    idx = line_number
    while True:
        end = _parenthesized_do_body_end(combined)
        if end >= 0:
            return combined[:end]
        if idx >= len(lines):
            return combined
        nxt = lines[idx].strip()
        idx += 1
        if not nxt or nxt.startswith("rem ") or nxt.startswith("::"):
            continue
        parts.append(nxt)
        combined = "\n".join(parts)


def _for_f_do_body(line: str, line_number: int, lines: list[str] | None) -> str:
    """Return the FOR DO body from a multi-line block or the rest of this line."""
    do_span = _for_do_span(line)
    remainder = line[do_span[1] :] if do_span is not None else ""
    if lines is not None and re.match(r"\s*\(", remainder):
        return _for_do_body_text(lines, line_number)
    return remainder


def _check_for_f_token_overflow(
    line: str, line_number: int, *, lines: list[str] | None = None
) -> List[LintIssue]:
    """Warn when DO body references FOR /F vars beyond tokens= count (W063)."""
    lowered = line.lower()
    if "/f" not in lowered or " do " not in lowered:
        return []

    options = _for_f_options_string(line)
    tokens_match = re.search(r"tokens=([^\"'\s]+)", options, re.IGNORECASE)
    tokens_value = tokens_match.group(1) if tokens_match else "1"
    slot_count = _for_f_token_slot_count(tokens_value)

    loop_var_match = _FOR_LOOP_VAR_RE.search(line)
    if not loop_var_match:
        return []
    start_letter = str(loop_var_match.group(1)).lower()

    body = _for_f_do_body(line, line_number, lines)
    if not body:
        return []

    return _for_f_token_overflow_issues(body, line_number, start_letter, slot_count)


def _line_span_containing(text: str, index: int) -> str:
    """Return the single line of text that contains index."""
    line_start = text.rfind("\n", 0, index) + 1
    line_end = text.find("\n", index)
    if line_end == -1:
        return text[line_start:]
    return text[line_start:line_end]


def _parenthesized_do_body_end(after_do: str) -> int:
    """Return the end index of a parenthesized DO body, or -1 if unclosed."""
    open_at = after_do.find("(")
    if open_at < 0:
        return 0
    depth = 0
    index = open_at
    in_double_quote = False
    while index < len(after_do):
        char = after_do[index]
        if char == "^":
            index += 2
            continue
        if char == '"':
            in_double_quote = not in_double_quote
            index += 1
            continue
        if in_double_quote:
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return -1


def _nested_for_f_end(body: str, match_start: int, match_end: int) -> int:
    """Return the index in body after a nested FOR /F starting at match_start."""
    rest = body[match_start:]
    do_span = _for_do_span(rest)
    if do_span is None:
        return match_end
    after_do = rest[do_span[1] :]
    if after_do.lstrip().startswith("("):
        consumed = _parenthesized_do_body_end(after_do)
        if consumed < 0:
            consumed = len(after_do)
        return match_start + do_span[1] + consumed
    newline_at = after_do.find("\n")
    if newline_at == -1:
        parts = _split_command_separators(after_do)
        first = parts[0] if parts else after_do
        return match_start + do_span[1] + len(first)
    return match_start + do_span[1] + newline_at


def _without_nested_for_f_commands(body: str) -> str:
    """Remove nested FOR /F commands so W063 only sees the current loop body."""
    pieces: List[str] = []
    pos = 0
    for match in _INNER_FOR_F_RE.finditer(body):
        if match.start() < pos:
            continue
        line = _line_span_containing(body, match.start())
        rel = match.start() - (body.rfind("\n", 0, match.start()) + 1)
        if not _prefix_allows_for_f_command(line[:rel]):
            logger.debug(
                "Skipping FOR /F mention that is not a nested command: %s",
                line.strip(),
            )
            continue
        pieces.append(body[pos : match.start()])
        pos = _nested_for_f_end(body, match.start(), match.end())
    pieces.append(body[pos:])
    return "".join(pieces)


def _for_f_token_overflow_issues(
    body: str, line_number: int, start_letter: str, slot_count: int
) -> List[LintIssue]:
    """Build W063 issues for FOR /F body variables past tokens= slots."""
    scan_body = _without_nested_for_f_commands(body)
    max_index = slot_count - 1
    issues: List[LintIssue] = []
    for ref_match in _FOR_BODY_VAR_RE.finditer(scan_body):
        ref_letter = str(ref_match.group(1)).lower()
        ref_index = ord(ref_letter) - ord(start_letter)
        if ref_index < 0 or ref_index > max_index:
            issues.append(
                LintIssue(
                    line_number,
                    RULES["W063"],
                    context=(
                        f"FOR /F tokens= assigns {slot_count} variable(s) from "
                        f"%%{start_letter}; %%{ref_letter} is out of range"
                    ),
                )
            )
            break
    return issues


def _for_f_uses_usebackq(line: str) -> bool:
    """Return True when FOR /F options include usebackq (or the useback synonym)."""
    lowered = line.lower()
    return "usebackq" in lowered or "useback" in lowered


def _for_f_operand_text(line: str) -> str:
    """Return the text inside FOR /F's ``IN ( ... )``, honouring quoting.

    A backquoted command can contain parentheses of its own, so the operand
    ends at the parenthesis that balances the opener outside quoting.
    """
    open_match = re.search(r"\bin\s*\(", line, re.IGNORECASE)
    if not open_match:
        return ""
    close_at = _for_in_close_index(line)
    if close_at is None:
        return ""
    return line[open_match.end() : close_at]


def _for_f_operand_looks_like_tabular_file(file_operand: str) -> bool:
    """Return True when a FOR /F file operand looks like a headered data file."""
    lowered = file_operand.lower()
    return "file" in lowered or ".txt" in lowered or ".csv" in lowered


def _for_f_file_set_operand(line: str) -> str:
    """Return the FOR /F IN (...) operand text when it names a data file.

    Backtick-quoted operands are commands (with usebackq) or invalid command
    forms (without it), never files. Without usebackq, a single-quoted operand
    is a command. With usebackq, single-quoted operands are filenames.
    """
    lowered = line.lower()
    if "/f" not in lowered:
        return ""
    operand = _for_f_operand_text(line).strip()
    if not operand:
        return ""
    if operand.startswith("`") and operand.endswith("`"):
        logger.debug(
            "FOR /F operand is backtick-quoted command, skipping file checks: %s",
            operand,
        )
        return ""
    if (
        not _for_f_uses_usebackq(line)
        and operand.startswith("'")
        and operand.endswith("'")
    ):
        logger.debug(
            "FOR /F operand is single-quoted command, skipping file checks: %s",
            operand,
        )
        return ""
    return operand


def _check_advanced_for_rules(
    line: str, line_number: int, *, lines: list[str] | None = None
) -> List[LintIssue]:
    """Check for advanced FOR command patterns."""
    issues: List[LintIssue] = []
    stripped = line.strip().lower()
    file_operand = _for_f_file_set_operand(line)

    if not stripped.startswith("for"):
        return issues

    issues.extend(_check_for_f_suboptions(line, line_number))
    issues.extend(_check_for_f_token_overflow(line, line_number, lines=lines))

    # E037: FOR /F eol= accepts only one character (FOR /?)
    if "/f" in stripped and re.search(r"eol=(\S)\S", line, re.IGNORECASE):
        issues.append(
            LintIssue(
                line_number,
                RULES["E037"],
                context="FOR /F eol= accepts only one character per FOR /?",
            )
        )

    # W034: FOR /F missing usebackq option
    if "/f" in stripped:
        if "useback" not in stripped:
            if "`" in line:
                issues.append(
                    LintIssue(
                        line_number,
                        RULES["W034"],
                        context="FOR /F with command execution needs usebackq",
                    )
                )
            elif re.search(r'in\s*\(\s*"[^"]*\s+[^"]*"\s*\)', line, re.IGNORECASE):
                issues.append(
                    LintIssue(
                        line_number,
                        RULES["W034"],
                        context="FOR /F with spaces in filename needs usebackq",
                    )
                )

    # W035: FOR /F tokenizing without proper delimiters
    # Skip if tokens=* is used (means take entire line, no tokenization needed)
    if (
        "/f" in stripped
        and "delims=" not in stripped
        and "tokens=" in stripped
        and "tokens=*" not in stripped
    ):
        issues.append(
            LintIssue(
                line_number,
                RULES["W035"],
                context="FOR /F tokenizing should specify delimiters",
            )
        )

    # W036: FOR /F missing skip option for headers
    if (
        "/f" in stripped
        and file_operand
        and "skip=" not in stripped
        and _for_f_operand_looks_like_tabular_file(file_operand)
    ):
        issues.append(
            LintIssue(
                line_number,
                RULES["W036"],
                context="FOR /F on data files should consider skip= for headers",
            )
        )

    # W037: FOR /F missing eol option for comments
    if (
        "/f" in stripped
        and file_operand
        and "eol=" not in stripped
        and ".txt" in file_operand.lower()
    ):
        issues.append(
            LintIssue(
                line_number,
                RULES["W037"],
                context="FOR /F should specify eol= for comment handling",
            )
        )

    # W038: FOR /R with literal filename (style — wildcards broaden matching)
    if "/r" in stripped and not ("*" in stripped or "?" in stripped):
        filename_match = re.search(r"\bin\s*\(\s*([^\s*)]+\.\w+)\s*\)", stripped)
        if filename_match:
            issues.append(
                LintIssue(
                    line_number,
                    RULES["W038"],
                    context=(
                        f"FOR /R with literal '{filename_match.group(1)}' "
                        "matches only that exact name; wildcards broaden results"
                    ),
                )
            )

    return issues


def _has_recent_tasklist_verification(lines: List[str], line_number: int) -> bool:
    """Return True when a recent line verifies process existence before TASKKILL."""
    start = max(0, line_number - 6)
    for prior_line in lines[start : line_number - 1]:
        prior = prior_line.strip().lower()
        if prior.startswith("tasklist") or ("tasklist" in prior and "find" in prior):
            return True
    return False


def _check_advanced_process_mgmt(lines: List[str], line_number: int) -> List[LintIssue]:
    """Check for process management best practices."""
    issues: List[LintIssue] = []
    line = lines[line_number - 1]
    stripped = line.strip().lower()

    # W042: Timeout command without /NOBREAK option
    if (
        stripped.startswith("timeout")
        and "/nobreak" not in stripped
        and "/t" in stripped
    ):
        issues.append(
            LintIssue(
                line_number,
                RULES["W042"],
                context="TIMEOUT should use /NOBREAK for uninterruptible delays",
            )
        )

    # W043: Process management without proper verification
    if stripped.startswith("taskkill") and "tasklist" not in stripped:
        if not _has_recent_tasklist_verification(lines, line_number):
            issues.append(
                LintIssue(
                    line_number,
                    RULES["W043"],
                    context="TASKKILL should verify process existence first",
                )
            )

    # SEC015: Process killing without authentication
    if "taskkill" in stripped and "/f" in stripped and "/fi" not in stripped:
        issues.append(
            LintIssue(
                line_number,
                RULES["SEC015"],
                context="TASKKILL /F should include filters to avoid system processes",
            )
        )

    return issues


# Match bounded percent-tilde tokens (delimited %~n1% or undelimited %~3 / %~dp0).
_PERCENT_TILDE_TOKEN_RE = PERCENT_TILDE_TOKEN_RE


def _split_percent_tilde_interior(interior: str) -> tuple[str, str]:
    if len(interior) == 1 and interior.isalpha():
        return "", interior
    if len(interior) > 1 and not re.search(r"\d", interior) and interior[-1].isalpha():
        potential_modifiers = interior[:-1]
        if all(
            char == "$" or char.lower() in VALID_MODIFIERS
            for char in potential_modifiers
        ):
            return potential_modifiers, interior[-1]

    modifiers: list[str] = []
    index = 0
    while index < len(interior):
        char = interior[index]
        lowered = char.lower()
        if char == "$" or lowered in VALID_MODIFIERS:
            modifiers.append(char)
            index += 1
            continue
        break
    parameter = interior[index:]
    has_path_search = "$" in modifiers
    while (
        modifiers
        and parameter
        and not _is_valid_percent_tilde_parameter(
            parameter,
            has_path_search=has_path_search,
        )
    ):
        recovered = modifiers.pop()
        if recovered == "$":
            parameter = "$" + parameter
            break
        parameter = recovered + parameter
    return "".join(modifiers), parameter


def _is_valid_percent_tilde_parameter(parameter: str, *, has_path_search: bool) -> bool:
    if has_path_search and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*:\d+", parameter):
        return True
    return parameter.isdigit() or (len(parameter) == 1 and parameter.isalpha())


def _check_percent_tilde_syntax(stripped: str, line_number: int) -> List[LintIssue]:
    """Check for percent-tilde syntax issues (E017, E019)."""
    issues: List[LintIssue] = []
    scan_line = strip_for_metavar_tilde_tokens(stripped)

    for match in _PERCENT_TILDE_TOKEN_RE.finditer(scan_line):
        interior = str(match.group(1))
        modifiers, parameter = _split_percent_tilde_interior(interior)
        has_path_search = "$" in modifiers
        invalid_chars = _invalid_percent_tilde_modifier_chars(interior)

        if invalid_chars:
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["E017"],
                    context=(
                        "Invalid modifier in %~"
                        f"{interior}%: {', '.join(sorted(invalid_chars))}"
                    ),
                )
            )

        if not parameter:
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["E019"],
                    context="Percent-tilde syntax is missing a parameter",
                )
            )
            continue

        numeric_parameter = re.sub(r"^[a-z]+", "", parameter, flags=re.IGNORECASE)
        if numeric_parameter and numeric_parameter[0].isdigit():
            parameter = numeric_parameter

        if not _is_valid_percent_tilde_parameter(
            parameter,
            has_path_search=has_path_search,
        ):
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["E019"],
                    context=(
                        f"Percent-tilde syntax used on invalid parameter: {parameter}"
                    ),
                )
            )

    return issues


def _invalid_percent_tilde_modifier_chars(interior: str) -> set[str]:
    valid_modifiers = VALID_MODIFIERS
    invalid: set[str] = set()
    index = 0
    while index < len(interior):
        char = interior[index]
        lowered = char.lower()
        if char == "$" or lowered in valid_modifiers:
            index += 1
            continue
        if char.isalpha():
            invalid.add(lowered)
            index += 1
            continue
        break
    parameter = interior[index:]
    prefix_match = re.match(r"^([a-z]+)(\d.*)$", parameter, re.IGNORECASE)
    if prefix_match:
        for char in str(prefix_match.group(1)).lower():
            if char not in valid_modifiers:
                invalid.add(char)
    return invalid


def _check_for_loop_var_syntax(stripped: str, line_number: int) -> List[LintIssue]:
    """Check FOR loop variable syntax (E020)."""
    issues: List[LintIssue] = []
    for_pattern = r"for\s+%%?([a-zA-Z])\s+in\s*\("

    for match in re.finditer(for_pattern, stripped, re.IGNORECASE):
        # In batch files, should use %%i, on command line %i
        var_syntax = match.group(0)
        if "%%" not in var_syntax:
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["E020"],
                    context="FOR loop variable should use %% in batch files",
                )
            )

    return issues


def _substring_indices_are_valid(spec: str) -> bool:
    if not spec:
        return False
    if spec.startswith("-"):
        spec = spec[1:]
    parts = spec.split(",", 1)
    for part in parts:
        token = part.strip()
        if not token:
            continue
        if token.startswith("-"):
            token = token[1:]
        if not token.isdigit():
            return False
    return True


def _check_string_operation_syntax(stripped: str, line_number: int) -> List[LintIssue]:
    """Check string operations syntax (E021)."""
    issues: List[LintIssue] = []

    for match in SUBSTRING_OP_RE.finditer(stripped):
        matched_text = match.group(0)
        if not _substring_indices_are_valid(match.group(2)):
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["E021"],
                    context=f"Invalid substring indices in {matched_text}",
                )
            )

    for match in REPLACEMENT_OP_RE.finditer(stripped):
        matched_text = match.group(0)
        body = match.group(2)
        if "=" not in body or matched_text.count("%") != 2:
            issues.append(
                LintIssue(
                    line_number=line_number,
                    rule=RULES["E021"],
                    context=f"Malformed string replacement: {matched_text}",
                )
            )

    return issues


def _check_set_a_quoting(stripped: str, line_number: int) -> List[LintIssue]:
    """Check SET /A syntax (E023)."""
    issues: List[LintIssue] = []

    if re.match(r"\s*set\s+/a\s+", stripped, re.IGNORECASE):
        # Check for special characters that need quoting
        if any(char in stripped for char in "^&|<>()"):
            if not ('"' in stripped or "'" in stripped):
                issues.append(
                    LintIssue(
                        line_number=line_number,
                        rule=RULES["E023"],
                        context="SET /A with special characters should be quoted",
                    )
                )

    return issues


def _check_advanced_vars(lines: List[str]) -> List[LintIssue]:
    """Check for advanced variable expansion syntax issues (E017-E022)."""
    issues: List[LintIssue] = []

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        issues.extend(_check_percent_tilde_syntax(stripped, i))
        issues.extend(_check_for_loop_var_syntax(stripped, i))
        issues.extend(_check_string_operation_syntax(stripped, i))
        issues.extend(_check_set_a_quoting(stripped, i))
        issues.extend(_check_set_a_arithmetic(stripped, i))

    return issues


_VALID_SET_A_OPERATOR_PAIRS: frozenset[str] = frozenset(
    {
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "==",
        "!=",
        ">=",
        "<=",
        "&&",
        "||",
        "<<",
        ">>",
    }
)


_SET_A_ASSIGN_SPLIT = re.compile(
    r"^(?P<lhs>.+?)(?P<op>=|[+\-*/%]?=)(?P<rhs>.+)$",
    re.IGNORECASE,
)


def _normalize_set_a_rhs(rhs: str) -> str:
    """Normalize SET /A RHS before operator validation."""
    normalized = rhs
    normalized = re.sub(r"%%[~]?[a-zA-Z0-9]+", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"![^!]+!", "0", normalized)
    normalized = re.sub(r"%[^%]*%", "0", normalized)
    normalized = re.sub(r"%~[0-9a-zA-Z]+", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"%%", "%", normalized)
    return normalized


def _set_a_has_bad_ops(expression: str) -> bool:
    """Return True when expression contains an invalid adjacent operator pair."""
    operator_chars = "=+-*/%<>!&|"
    for index in range(len(expression) - 1):
        first = expression[index]
        second = expression[index + 1]
        if first in operator_chars and second in operator_chars:
            pair = first + second
            if pair not in _VALID_SET_A_OPERATOR_PAIRS:
                return True
    return False


def _check_set_a_arithmetic(stripped: str, line_number: int) -> List[LintIssue]:
    """Check SET /A arithmetic syntax (E022)."""
    issues: List[LintIssue] = []
    seta_match = re.match(r"set\s+/a\s+(.+)", stripped, re.IGNORECASE)
    if not seta_match:
        return issues

    expression = str(seta_match.group(1)).strip().strip('"')
    assign_match = _SET_A_ASSIGN_SPLIT.match(expression)
    rhs = assign_match.group("rhs") if assign_match else expression
    rhs = re.sub(r"^\s*(?:[^\\^]|^)[&|].*$", "", rhs).strip()

    if _set_a_has_bad_ops(_normalize_set_a_rhs(rhs)):
        issues.append(
            LintIssue(
                line_number=line_number,
                rule=RULES["E022"],
                context="Invalid operator sequence in SET /A expression",
            )
        )

    return issues
