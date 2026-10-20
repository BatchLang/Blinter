#!/usr/bin/env python3
"""Generate src/blinter/rules/expansion_data.py from vendor/batch-spec/data/expansion.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import black
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.spec._paths import (  # noqa: E402  # pylint: disable=wrong-import-position
    EXPANSION_DATA_PY,
    EXPANSION_YAML,
)

_HEADER = '''\
"""Batch expansion constants generated from vendor/batch-spec/data/expansion.yaml.

THIS FILE IS GENERATED — edit vendor/batch-spec/data/expansion.yaml and run:
  py scripts/spec/generate_expansion.py
"""

from __future__ import annotations

from typing import FrozenSet, Tuple

'''


def _as_mapping(value: object, label: str) -> dict[str, object]:
    """Narrow a YAML value to a string-keyed mapping."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    mapping: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        mapping[key] = item
    return mapping


def _load_expansion() -> dict[str, object]:
    data = yaml.safe_load(EXPANSION_YAML.read_text(encoding="utf-8"))
    return _as_mapping(data, "expansion.yaml")


def _quoted(value: object) -> str:
    """Escape a YAML string for a generated Python literal."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _tuple_lines(header: str, values: list[object]) -> list[str]:
    """Render a generated Tuple[str, ...] assignment."""
    lines = [header]
    for value in values:
        lines.append(f'    "{_quoted(value)}",')
    lines.append(")")
    return lines


def _modifier_lines(data: dict[str, object]) -> list[str]:
    """Render modifier character and modifier-name constants."""
    valid_modifiers = _as_mapping(data.get("valid_modifiers", {}), "valid_modifiers")
    lines = [
        f'VALID_MODIFIER_CHARS: str = "{data["valid_modifier_chars"]}"',
        "VALID_MODIFIERS: FrozenSet[str] = frozenset({",
    ]
    for key in sorted(valid_modifiers):
        lines.append(f'    "{key}",')
    lines.append("})")
    return lines


def _delayed_lines(data: dict[str, object]) -> list[str]:
    """Render delayed-expansion constants."""
    delayed = _as_mapping(data.get("delayed_expansion", {}), "delayed_expansion")
    enable_keywords = delayed.get("enable_keywords", [])
    if not isinstance(enable_keywords, list):
        raise ValueError("enable_keywords must be a list")
    pattern = delayed.get("pattern", "!VAR!")
    requires_setlocal = bool(delayed.get("requires_setlocal", True))
    lines = [
        f'DELAYED_EXPANSION_PATTERN: str = "{pattern}"',
        f"DELAYED_EXPANSION_REQUIRES_SETLOCAL: bool = {requires_setlocal!r}",
    ]
    lines.extend(
        _tuple_lines(
            "DELAYED_EXPANSION_ENABLE_KEYWORDS: Tuple[str, ...] = (",
            enable_keywords,
        )
    )
    return lines


def _string_operation_lines(data: dict[str, object]) -> list[str]:
    """Render substring and replacement pattern constants."""
    string_operations = _as_mapping(
        data.get("string_operations", {}), "string_operations"
    )
    substring = string_operations.get("substring_pattern", "%var:~0,1%")
    replacement = string_operations.get("replacement_pattern", "%var:old=new%")
    return [
        f'STRING_SUBSTRING_PATTERN: str = "{substring}"',
        f'STRING_REPLACEMENT_PATTERN: str = "{replacement}"',
    ]


def generate_expansion_text() -> str:
    """Return generated expansion_data.py source."""
    data = _load_expansion()
    examples = data.get("valid_combined_examples", [])
    invalid = data.get("invalid_combinations", [])
    if not isinstance(examples, list):
        raise ValueError("valid_combined_examples must be a list")
    if not isinstance(invalid, list):
        raise ValueError("invalid_combinations must be a list")
    reasons: list[object] = []
    for entry in invalid:
        if not isinstance(entry, dict):
            raise ValueError("invalid_combinations entries must be mappings")
        reasons.append(entry.get("reason", ""))
    lines = [_HEADER, *_modifier_lines(data), "", *_delayed_lines(data), ""]
    lines.extend(
        _tuple_lines("VALID_COMBINED_TILDE_EXAMPLES: Tuple[str, ...] = (", examples)
    )
    lines.append("")
    lines.extend(
        _tuple_lines("INVALID_TILDE_COMBINATION_REASONS: Tuple[str, ...] = (", reasons)
    )
    lines.append("")
    lines.extend(_string_operation_lines(data))
    lines.append("")
    return black.format_str("\n".join(lines), mode=black.Mode(line_length=88))


def write_expansion_data() -> None:
    """Write generated expansion_data.py."""
    EXPANSION_DATA_PY.parent.mkdir(parents=True, exist_ok=True)
    EXPANSION_DATA_PY.write_text(
        generate_expansion_text(), encoding="utf-8", newline="\n"
    )


def main() -> None:
    """Generate expansion_data.py, or check that it is already current."""
    parser = argparse.ArgumentParser(description="Generate expansion_data.py")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate_expansion_text()
    if args.check:
        existing = (
            EXPANSION_DATA_PY.read_text(encoding="utf-8")
            if EXPANSION_DATA_PY.is_file()
            else ""
        )
        if existing != generated:
            print(
                f"{EXPANSION_DATA_PY} is out of date; run generate_expansion.py",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print("expansion_data.py is up to date")
        return
    write_expansion_data()
    print(f"Wrote {EXPANSION_DATA_PY}")


if __name__ == "__main__":
    main()
