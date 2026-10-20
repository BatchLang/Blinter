#!/usr/bin/env python3
"""Validate Blinter spec YAML and batch-spec language YAML against JSON Schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import jsonschema
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.spec._paths import (  # noqa: E402  # pylint: disable=wrong-import-position
    BATCH_SPEC_DIR,
    BATCH_SPEC_SCHEMA_DIR,
    COMMANDS_LANGUAGE_YAML,
    COMMANDS_LINTER_YAML,
    DATA_DIR,
    EXPANSION_YAML,
    RULES_YAML,
    SCHEMA_DIR,
)

_PREFIX_SEVERITY_ALLOWLIST = {"E006", "SEC006"}


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validate(path: Path, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = _load_yaml(path)
    jsonschema.validate(instance=data, schema=schema)
    print(f"OK {path.name}")


def _validate_rule_integrity(rules_data: dict[str, object]) -> None:
    rules = rules_data.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rules.yaml must contain a rules list")
    codes: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("Each rule must be a mapping")
        code = str(rule["code"])
        codes.append(code)
        severity = str(rule["severity"])
        if code.startswith("SEC"):
            prefix = "SEC"
        else:
            prefix = code[0]
        expected = {
            "E": "ERROR",
            "W": "WARNING",
            "S": "STYLE",
            "SEC": "SECURITY",
            "P": "PERFORMANCE",
        }.get(prefix)
        if expected and severity != expected and code not in _PREFIX_SEVERITY_ALLOWLIST:
            raise ValueError(
                f"Rule {code} has severity {severity}, expected {expected}"
            )
    if len(codes) != len(set(codes)):
        duplicates = sorted({c for c in codes if codes.count(c) > 1})
        raise ValueError(f"Duplicate rule codes in rules.yaml: {duplicates}")


def _validate_commands_rule_refs(
    commands_data: dict[str, object], valid_rules: set[str]
) -> None:
    patterns = commands_data.get("dangerous_command_patterns", [])
    if not isinstance(patterns, list):
        return
    for entry in patterns:
        if not isinstance(entry, dict):
            continue
        rule_code = str(entry.get("rule_code", ""))
        if rule_code and rule_code not in valid_rules:
            raise ValueError(
                f"commands-linter.yaml references unknown rule_code {rule_code}"
            )


def _ensure_batch_spec_present() -> None:
    if not BATCH_SPEC_DIR.is_dir():
        raise SystemExit(
            "vendor/batch-spec submodule is missing. "
            "Run: git submodule update --init --recursive"
        )


def main() -> None:
    """Validate spec YAML files against their JSON schemas."""
    parser = argparse.ArgumentParser(description="Validate spec YAML against schemas")
    parser.parse_args()
    _ensure_batch_spec_present()

    _validate(RULES_YAML, SCHEMA_DIR / "rules.schema.json")
    rules_data = _load_yaml(RULES_YAML)
    if not isinstance(rules_data, dict):
        raise SystemExit("rules.yaml must be a mapping")
    _validate_rule_integrity(rules_data)
    valid_rules = {str(rule["code"]) for rule in rules_data["rules"]}

    _validate(COMMANDS_LINTER_YAML, SCHEMA_DIR / "commands-linter.schema.json")
    linter_commands = _load_yaml(COMMANDS_LINTER_YAML)
    if isinstance(linter_commands, dict):
        _validate_commands_rule_refs(linter_commands, valid_rules)

    _validate(COMMANDS_LANGUAGE_YAML, BATCH_SPEC_SCHEMA_DIR / "commands.schema.json")
    _validate(EXPANSION_YAML, BATCH_SPEC_SCHEMA_DIR / "expansion.schema.json")

    if not DATA_DIR.is_dir():
        raise SystemExit(f"Missing {DATA_DIR}")
    print("Spec validation passed")


if __name__ == "__main__":
    main()
