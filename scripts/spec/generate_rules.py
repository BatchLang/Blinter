#!/usr/bin/env python3
"""Generate src/blinter/rules/registry.py from spec/data/rules.yaml."""

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
    REGISTRY_PY,
    RULES_YAML,
)

_HEADER = '''\
"""Rule definitions and the RULES lookup table."""

# pylint: disable=too-many-lines
# Rule catalog is intentionally centralized in one module.
# THIS FILE IS GENERATED — edit spec/data/rules.yaml and run:
#   py scripts/spec/generate_rules.py

from typing import Dict

from blinter.models import Rule, RuleSeverity

RULES: Dict[str, Rule] = {
'''

_FOOTER = """\
}

RULE_COUNT = len(RULES)
"""


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_rule(rule: dict[str, object]) -> str:
    code = str(rule["code"])
    name = _escape(str(rule["name"]))
    severity = str(rule["severity"])
    explanation = _escape(str(rule["explanation"]))
    recommendation = _escape(str(rule["recommendation"]))
    lines = [
        f'    "{code}": Rule(',
        f'        code="{code}",',
        f'        name="{name}",',
        f"        severity=RuleSeverity.{severity},",
        f'        explanation="{explanation}",',
        f'        recommendation="{recommendation}",',
        "    ),",
    ]
    return "\n".join(lines)


def _load_rules() -> list[dict[str, object]]:
    data = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("rules.yaml must be a mapping")
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rules.yaml must contain a rules list")
    typed_rules: list[dict[str, object]] = []
    for item in rules:
        if not isinstance(item, dict):
            raise ValueError("each rule must be a mapping")
        rule: dict[str, object] = {}
        for key, value in item.items():
            if not isinstance(key, str):
                raise ValueError("rule keys must be strings")
            rule[key] = value
        typed_rules.append(rule)
    return sorted(typed_rules, key=lambda item: str(item["code"]))


def _format_generated_source(source: str) -> str:
    mode = black.Mode(line_length=88)
    return black.format_str(source, mode=mode)


def generate_registry_text() -> str:
    """Return generated registry.py source."""
    rules = _load_rules()
    sections: list[str] = [_HEADER]
    current_prefix: str | None = None
    prefix_comments = {
        "E": "    # Error Level Rules (E001-E999)",
        "W": "    # Warning Level Rules (W001-W999)",
        "S": "    # Style Level Rules (S001-S999)",
        "SEC": "    # Security Level Rules (SEC001+)",
        "P": "    # Performance Level Rules (P001-P999)",
    }
    for rule in rules:
        code = str(rule["code"])
        if code.startswith("SEC"):
            prefix = "SEC"
        else:
            prefix = code[0]
        if prefix != current_prefix:
            comment = prefix_comments.get(prefix)
            if comment:
                sections.append(comment)
            current_prefix = prefix
        sections.append(_format_rule(rule))
    sections.append(_FOOTER)
    return _format_generated_source("\n".join(sections))


def write_registry() -> None:
    """Write generated registry.py."""
    REGISTRY_PY.write_text(generate_registry_text(), encoding="utf-8", newline="\n")


def main() -> None:
    """Generate registry.py, or check that it is already current."""
    parser = argparse.ArgumentParser(description="Generate registry.py from rules.yaml")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if registry.py would change",
    )
    args = parser.parse_args()
    generated = generate_registry_text()
    if args.check:
        existing = (
            REGISTRY_PY.read_text(encoding="utf-8") if REGISTRY_PY.is_file() else ""
        )
        if existing != generated:
            print(
                f"{REGISTRY_PY} is out of date; run generate_rules.py", file=sys.stderr
            )
            raise SystemExit(1)
        print("registry.py is up to date")
        return
    write_registry()
    print(f"Wrote {REGISTRY_PY}")


if __name__ == "__main__":
    main()
