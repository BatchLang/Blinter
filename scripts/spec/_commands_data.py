"""Shared merge of batch-spec commands.yaml and Blinter commands-linter.yaml."""

from __future__ import annotations

import yaml

from scripts.spec._paths import COMMANDS_LANGUAGE_YAML, COMMANDS_LINTER_YAML


def _string_key_mapping(value: object, label: str) -> dict[str, object]:
    """Narrow a YAML mapping to string keys."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    mapping: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        mapping[key] = item
    return mapping


def merged_commands_data() -> dict[str, object]:
    """Return the merged commands mapping from the language and linter YAML files."""
    if not COMMANDS_LANGUAGE_YAML.is_file():
        raise FileNotFoundError("batch-spec commands.yaml missing")
    if not COMMANDS_LINTER_YAML.is_file():
        raise FileNotFoundError("commands-linter.yaml missing")
    language = yaml.safe_load(COMMANDS_LANGUAGE_YAML.read_text(encoding="utf-8"))
    linter = yaml.safe_load(COMMANDS_LINTER_YAML.read_text(encoding="utf-8"))
    return {
        **_string_key_mapping(language, "commands.yaml"),
        **_string_key_mapping(linter, "commands-linter.yaml"),
    }


def builtin_commands_union(data: dict[str, object]) -> list[str]:
    """Union of stock/cmd builtins and common external tools for E012/E014 suppression."""
    builtins = data.get("builtin_commands", [])
    externals = data.get("common_external_tools", [])
    if not isinstance(builtins, list) or not isinstance(externals, list):
        raise ValueError("builtin_commands and common_external_tools must be lists")
    names: set[str] = set()
    for item in [*builtins, *externals]:
        if not isinstance(item, str):
            raise ValueError("command names must be strings")
        names.add(item)
    return sorted(names)
