#!/usr/bin/env python3
"""Generate src/blinter/patterns.py from batch-spec commands.yaml + commands-linter.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import black

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.spec._commands_data import (  # noqa: E402  # pylint: disable=wrong-import-position
    builtin_commands_union,
    merged_commands_data,
)
from scripts.spec._paths import (  # noqa: E402  # pylint: disable=wrong-import-position
    PATTERNS_PY,
)

_STATIC_FRAGMENT = _SCRIPTS_DIR / "patterns_static_fragment.py"

_HEADER = '''\
"""Regex patterns for dangerous commands and deprecated syntax.

SSOT tables (dangerous commands, builtins, typos) are generated from
vendor/batch-spec/data/commands.yaml and spec/data/commands-linter.yaml. Embedded-language detection patterns are maintained
in scripts/spec/patterns_static_fragment.py.

THIS FILE IS PARTIALLY GENERATED — run:
  py scripts/spec/generate_commands.py
"""

import re
from typing import List, Set, Tuple

'''


def _format_list(name: str, values: list[str]) -> str:
    lines = [f"{name}: List[str] = ["]
    for value in values:
        lines.append(f'    "{value}",')
    lines.append("]")
    return "\n".join(lines)


def _format_set(name: str, values: list[str]) -> str:
    lines = [f"{name}: Set[str] = {{"]
    for value in values:
        lines.append(f'    "{value}",')
    lines.append("}")
    return "\n".join(lines)


def _format_dict_str_str(name: str, values: dict[str, str]) -> str:
    lines = [f"{name} = {{"]
    for key in sorted(values.keys()):
        escaped = values[key].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    "{key}": "{escaped}",')
    lines.append("}")
    return "\n".join(lines)


def _format_dangerous_patterns(patterns: list[dict[str, str]]) -> str:
    lines = ["DANGEROUS_COMMAND_PATTERNS: List[Tuple[str, str]] = ["]
    for entry in patterns:
        pattern = entry["pattern"]
        rule_code = entry["rule_code"]
        lines.append(f"    ({repr(pattern)}, {repr(rule_code)}),")
    lines.append("]")
    return "\n".join(lines)


def _require_str_list(value: object, key: str) -> list[str]:
    """Return a YAML list of strings or raise ValueError."""
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a list of strings")
        items.append(item)
    return items


def _require_str_dict(value: object, key: str) -> dict[str, str]:
    """Return a YAML string-to-string mapping or raise ValueError."""
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping of strings")
    mapping: dict[str, str] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not isinstance(item_value, str):
            raise ValueError(f"{key} must be a mapping of strings")
        mapping[item_key] = item_value
    return mapping


def _require_pattern_list(value: object, key: str) -> list[dict[str, str]]:
    """Return dangerous-command pattern rows or raise ValueError."""
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of mappings")
    patterns: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(f"{key} entries must be mappings")
        pattern = entry.get("pattern")
        rule_code = entry.get("rule_code")
        if not isinstance(pattern, str) or not isinstance(rule_code, str):
            raise ValueError(f"{key} entries need string pattern and rule_code")
        patterns.append({"pattern": pattern, "rule_code": rule_code})
    return patterns


def generate_patterns_text() -> str:
    """Return generated patterns.py source."""
    data = merged_commands_data()
    dangerous_names = _require_str_list(
        data["dangerous_command_names"], "dangerous_command_names"
    )
    architecture_patterns = _require_str_list(
        data["architecture_specific_patterns"], "architecture_specific_patterns"
    )
    sections = [_HEADER]
    sections.append(_format_list("DANGEROUS_COMMAND_NAMES", dangerous_names))
    sections.append("")
    sections.append('_DANGEROUS_CMDS_REGEX: str = "|".join(DANGEROUS_COMMAND_NAMES)')
    sections.append("")
    sections.append(
        _format_dangerous_patterns(
            _require_pattern_list(
                data["dangerous_command_patterns"], "dangerous_command_patterns"
            )
        )
    )
    sections.append("")
    sections.append(
        _format_set(
            "COMMAND_CASING_KEYWORDS",
            _require_str_list(
                data["command_casing_keywords"], "command_casing_keywords"
            ),
        )
    )
    sections.append("")
    sections.append(
        _format_set(
            "OLDER_WINDOWS_COMMANDS",
            _require_str_list(data["older_windows_commands"], "older_windows_commands"),
        )
    )
    sections.append("")
    sections.append(
        "ARCHITECTURE_SPECIFIC_PATTERNS: List[str] = [\n"
        + "\n".join(f'    r"{v}",' for v in architecture_patterns)
        + "\n]"
    )
    sections.append("")
    sections.append(
        _format_set(
            "UNICODE_PROBLEMATIC_COMMANDS",
            _require_str_list(
                data["unicode_problematic_commands"], "unicode_problematic_commands"
            ),
        )
    )
    sections.append("")
    sections.append(
        _format_dict_str_str(
            "DEPRECATED_COMMANDS",
            _require_str_dict(data["deprecated_commands"], "deprecated_commands"),
        )
    )
    sections.append("")
    sections.append(
        _format_dict_str_str(
            "REMOVED_COMMANDS",
            _require_str_dict(data["removed_commands"], "removed_commands"),
        )
    )
    sections.append("")
    sections.append(
        _format_dict_str_str(
            "COMMON_COMMAND_TYPOS",
            _require_str_dict(data["common_command_typos"], "common_command_typos"),
        )
    )
    sections.append("")
    sections.append(
        _format_list(
            "SENSITIVE_KEYWORDS",
            _require_str_list(data["sensitive_keywords"], "sensitive_keywords"),
        )
    )
    sections.append("")
    sections.append(
        "CREDENTIAL_PATTERNS = [\n"
        '    rf"{keyword}\\s*=\\s*[\\"\\\']?[^\\s\\"\']+[\\"\\\']?" '
        "for keyword in SENSITIVE_KEYWORDS\n"
        "]"
    )
    sections.append("")
    sections.append(
        'SENSITIVE_ECHO_PATTERNS = [rf"echo.*{keyword}" for keyword in SENSITIVE_KEYWORDS]'
    )
    sections.append("")
    sections.append(_format_set("BUILTIN_COMMANDS", builtin_commands_union(data)))
    sections.append("")
    if _STATIC_FRAGMENT.is_file():
        sections.append(_STATIC_FRAGMENT.read_text(encoding="utf-8").strip())
        sections.append("")
    source = "\n".join(sections)
    return black.format_str(source, mode=black.Mode(line_length=88))


def write_patterns() -> None:
    """Write generated patterns.py."""
    PATTERNS_PY.write_text(generate_patterns_text(), encoding="utf-8", newline="\n")


def main() -> None:
    """Generate patterns.py, or check that it is already current."""
    parser = argparse.ArgumentParser(
        description="Generate patterns.py from commands.yaml"
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate_patterns_text()
    if args.check:
        existing = (
            PATTERNS_PY.read_text(encoding="utf-8") if PATTERNS_PY.is_file() else ""
        )
        if existing != generated:
            print(
                f"{PATTERNS_PY} is out of date; run generate_commands.py",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print("patterns.py is up to date")
        return
    write_patterns()
    print(f"Wrote {PATTERNS_PY}")


if __name__ == "__main__":
    main()
