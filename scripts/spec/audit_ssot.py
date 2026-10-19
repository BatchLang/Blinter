#!/usr/bin/env python3
"""Read-only SSOT audit: rules, commands, expansion, corpus coverage, drift."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _commands_data import builtin_commands_union, merged_commands_data  # noqa: E402
from _paths import (  # noqa: E402
    AUDIT_DIR,
    BATCH_SPEC_DIR,
    CHECKERS_DIR,
    COMMANDS_LANGUAGE_YAML,
    COMMANDS_LINTER_YAML,
    CORPUS_DIR,
    EXPANSION_DATA_PY,
    EXPANSION_YAML,
    PARSING_DIR,
    PATTERNS_PY,
    REFERENCE_MATRIX_YAML,
    REPO_ROOT,
    REQUIREMENTS_MD,
    RULES_HELPERS_PY,
    RULES_YAML,
)

_PREFIX_SEVERITY_ALLOWLIST = {"E006": "WARNING", "SEC006": "STYLE"}
_VALID_MODIFIER_CHARS_RE = re.compile(
    r'VALID_MODIFIER_CHARS:\s*str\s*=\s*["\']([^"\']+)["\']'
)
_VALID_MODIFIERS_FROZENSET_RE = re.compile(
    r"VALID_MODIFIERS:\s*FrozenSet\[str\]\s*=\s*frozenset\(\{([^}]*)\}\)"
)
_E_RULE_CASE_RE = re.compile(r"^e(\d{3})-", re.IGNORECASE)
_E_RULE_COVERAGE_TARGET = {f"E{index:03d}" for index in range(1, 48)}
_RULES_IN_CODE_RE = re.compile(r'RULES\[\s*["\']([A-Z]+\d+)["\']\s*\]')
_RULE_CODE_KWARG_RE = re.compile(r'rule_code\s*=\s*["\']([A-Z]+\d+)["\']')
_S011_RULE_USAGE_RE = re.compile(r"_s011_rule\s*\(")
_DANGEROUS_PATTERN_RULE_RE = re.compile(r'\(\s*"[^"]*"\s*,\s*"([A-Z]+\d+)"\s*\)')
_DOCS_RULE_COUNT_RE = re.compile(
    r"currently\s+\*\*(\d+)\*\*\s+rules",
    re.IGNORECASE,
)
_SSOT_ARTIFACT_RULE_RE = re.compile(r"\b([A-Z]{1,3}\d{3})\b")
_CATALOG_END = "<!-- GENERATED:rule-catalog:end -->"
# Corpus cases that may appear under a matrix entry without asserting its rules.
_MATRIX_CORPUS_RULE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "integration/follow-calls-e006",
        "syntax/w044-set-a-spacing-valid",
        "syntax/w049-pseudo-env-clear-valid",
        "syntax/w049-set-a-pseudo-valid",
        "syntax/w051-param-9-valid",
        "syntax/w051-for-loop-valid",
        "syntax/w050-shift-valid-boundaries",
        "syntax/w052-shift-outside-valid",
        "syntax/w054-digit-var-delayed-valid",
        "syntax/w055-if-defined-dynamic-valid",
        "syntax/w056-if-nested-valid",
        "syntax/w056-if-orange-valid",
        "syntax/w056-dash-concat-valid",
        "syntax/else-if-valid",
        "syntax/conditional-exec-valid",
        "syntax/w057-bat-with-call-valid",
        "syntax/w058-ren-valid",
        "syntax/for-case-distinct-valid",
        "syntax/w059-for-case-consistent-valid",
        "syntax/w060-setx-valid",
        "syntax/w061-pushd-popd-valid",
        "syntax/w062-cd-d-valid",
        "syntax/w063-for-f-token-valid",
        "syntax/e036-if-exist-valid",
        "syntax/e037-for-f-eol-valid",
        "syntax/e038-for-f-valid",
        "syntax/e039-if-paren-sameline-valid",
        "syntax/e040-for-do-paren-sameline-valid",
        "syntax/e041-set-p-valid",
        "syntax/e042-text-after-paren-valid",
        "syntax/w063-for-f-tokens-star-suffix-valid",
        "syntax/w017-not-errorlevel-one-valid",
        "syntax/w034-useback-synonym-valid",
        "syntax/p024-p006-setlocal-in-comment-valid",
        "syntax/s010-if-goto-call-valid",
        "syntax/w036-for-f-command-noprofile-valid",
        "syntax/w036-for-f-command-with-parens-valid",
        "syntax/exit-shift-smoke-valid",
        "syntax/if-defined-var",
        "syntax/if-else-block",
        "syntax/e043-doublecolon-outside-valid",
        "syntax/e044-else-sameline-valid",
        "syntax/e045-switch-valid",
        "syntax/e046-redir-valid",
        "syntax/e047-escaped-valid",
        "syntax/e047-echo-open-paren-valid",
        "syntax/sec014-quoted-arg-valid",
        "syntax/sec025-quoted-cd-valid",
        "syntax/sec001-setp-quoted-valid",
        "syntax/w064-allusersprofile-valid",
        "syntax/w065-if-literal-valid",
        "syntax/w066-redir-at-end-valid",
        "syntax/s029-echo-off-valid",
        "syntax/s030-nul-valid",
        "syntax/w067-set-custom-valid",
        "syntax/w068-delayed-valid",
        "syntax/w071-errorlevel-first-valid",
        "syntax/w071-single-valid",
        "syntax/w069-time-zero-valid",
        "syntax/w070-set-and-cmd-valid",
    }
)


class AuditFinding:
    def __init__(self, level: str, category: str, message: str) -> None:
        self.level = level
        self.category = category
        self.message = message


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


def _audit_rules(findings: list[AuditFinding]) -> set[str]:
    data = _load_yaml(RULES_YAML)
    rules = data.get("rules", [])
    codes: list[str] = []
    for rule in rules:
        code = str(rule["code"])
        codes.append(code)
        checker = str(rule.get("checker", "regex"))
        if checker != "regex":
            findings.append(
                AuditFinding(
                    "error",
                    "rules",
                    f"{code} has checker {checker!r}, expected 'regex'",
                )
            )
        severity = str(rule["severity"])
        prefix = "SEC" if code.startswith("SEC") else code[0]
        expected = {
            "E": "ERROR",
            "W": "WARNING",
            "S": "STYLE",
            "SEC": "SECURITY",
            "P": "PERFORMANCE",
        }.get(prefix)
        if expected and severity != expected and code not in _PREFIX_SEVERITY_ALLOWLIST:
            findings.append(
                AuditFinding(
                    "error",
                    "rules",
                    f"{code} has severity {severity}, expected {expected}",
                )
            )
    duplicates = {c for c in codes if codes.count(c) > 1}
    for dup in sorted(duplicates):
        findings.append(AuditFinding("error", "rules", f"Duplicate rule code {dup}"))
    return set(codes)


def _merged_commands_data() -> dict[str, Any]:
    return merged_commands_data()


def _audit_commands(findings: list[AuditFinding], valid_rules: set[str]) -> None:
    if not BATCH_SPEC_DIR.is_dir():
        findings.append(
            AuditFinding("error", "commands", "vendor/batch-spec submodule missing")
        )
        return
    if not COMMANDS_LINTER_YAML.is_file():
        findings.append(
            AuditFinding("error", "commands", "commands-linter.yaml missing")
        )
        return
    try:
        data = _merged_commands_data()
    except (FileNotFoundError, ValueError) as error:
        findings.append(AuditFinding("error", "commands", str(error)))
        return
    for entry in data.get("dangerous_command_patterns", []):
        rule_code = str(entry.get("rule_code", ""))
        if rule_code and rule_code not in valid_rules:
            findings.append(
                AuditFinding(
                    "error",
                    "commands",
                    f"dangerous_command_patterns references unknown rule {rule_code}",
                )
            )
    builtins = set(data.get("builtin_commands", []))
    deprecated = set(data.get("deprecated_commands", {}).keys())
    overlap = builtins & deprecated
    for name in sorted(overlap):
        findings.append(
            AuditFinding(
                "info",
                "commands",
                f"{name} is both builtin and deprecated (intentional for W024 recognition)",
            )
        )


def _read_patterns_constants() -> dict[str, Any]:
    if not PATTERNS_PY.is_file():
        return {}
    module = ast.parse(PATTERNS_PY.read_text(encoding="utf-8"))
    constants: dict[str, Any] = {}
    for node in module.body:
        name: str | None = None
        value_node = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                name = target.id
                value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value_node = node.value
        if name is None or value_node is None:
            continue
        try:
            constants[name] = ast.literal_eval(value_node)
        except (ValueError, TypeError):
            pass
    return constants


def _audit_commands_patterns_drift(findings: list[AuditFinding]) -> None:
    if not PATTERNS_PY.is_file():
        return
    try:
        data = _merged_commands_data()
    except (FileNotFoundError, ValueError) as error:
        findings.append(AuditFinding("error", "drift", str(error)))
        return
    patterns = _read_patterns_constants()
    checks: list[tuple[str, str, str]] = [
        ("dangerous_command_names", "DANGEROUS_COMMAND_NAMES", "list"),
        ("command_casing_keywords", "COMMAND_CASING_KEYWORDS", "set"),
        ("older_windows_commands", "OLDER_WINDOWS_COMMANDS", "set"),
        ("sensitive_keywords", "SENSITIVE_KEYWORDS", "list"),
    ]
    for yaml_key, py_key, kind in checks:
        yaml_val = data.get(yaml_key)
        py_val = patterns.get(py_key)
        if yaml_val is None or py_val is None:
            continue
        yaml_norm = sorted(yaml_val) if kind in {"list", "set"} else yaml_val
        py_norm = sorted(py_val) if kind in {"list", "set"} else py_val
        if yaml_norm != py_norm:
            findings.append(
                AuditFinding(
                    "error",
                    "drift",
                    f"commands YAML {yaml_key} != patterns.py {py_key}",
                )
            )
    builtin_yaml = sorted(builtin_commands_union(data))
    builtin_py = sorted(patterns.get("BUILTIN_COMMANDS", []))
    if builtin_yaml != builtin_py:
        findings.append(
            AuditFinding(
                "error",
                "drift",
                "commands YAML builtin_commands union common_external_tools "
                "!= patterns.py BUILTIN_COMMANDS",
            )
        )


def _read_expansion_data_constants() -> dict[str, str]:
    if not EXPANSION_DATA_PY.is_file():
        return {}
    text = EXPANSION_DATA_PY.read_text(encoding="utf-8")
    constants: dict[str, str] = {}
    chars_match = _VALID_MODIFIER_CHARS_RE.search(text)
    if chars_match:
        constants["valid_modifier_chars"] = chars_match.group(1)
    frozen_match = _VALID_MODIFIERS_FROZENSET_RE.search(text)
    if frozen_match:
        keys = re.findall(r'"([a-z])"', frozen_match.group(1))
        constants["valid_modifiers"] = "".join(sorted(keys))
    return constants


def _audit_expansion_drift(findings: list[AuditFinding]) -> None:
    if not EXPANSION_YAML.is_file():
        findings.append(
            AuditFinding(
                "error", "expansion", "vendor/batch-spec expansion.yaml missing"
            )
        )
        return
    if not EXPANSION_DATA_PY.is_file():
        findings.append(
            AuditFinding(
                "error",
                "expansion",
                "expansion_data.py missing — run generate_expansion.py",
            )
        )
        return
    data = _load_yaml(EXPANSION_YAML)
    yaml_mods = str(data.get("valid_modifier_chars", ""))
    yaml_modifier_keys = "".join(sorted(data.get("valid_modifiers", {}).keys()))
    generated = _read_expansion_data_constants()
    if generated.get("valid_modifier_chars") != yaml_mods:
        findings.append(
            AuditFinding(
                "error",
                "drift",
                "expansion.yaml valid_modifier_chars != expansion_data.py VALID_MODIFIER_CHARS",
            )
        )
    if (
        generated.get("valid_modifiers")
        and generated["valid_modifiers"] != yaml_modifier_keys
    ):
        findings.append(
            AuditFinding(
                "error",
                "drift",
                "expansion.yaml valid_modifiers keys != expansion_data.py VALID_MODIFIERS",
            )
        )


def _corpus_rule_coverage() -> dict[str, list[str]]:
    coverage: dict[str, list[str]] = {}
    for expect_path in sorted(CORPUS_DIR.glob("**/expect.json")):
        case_id = "/".join(expect_path.parent.relative_to(CORPUS_DIR).parts)
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
        rules: set[str] = set(expect.get("rules", []))
        for codes in expect.get("lines", {}).values():
            rules.update(codes)
        for rule in rules:
            coverage.setdefault(rule, []).append(case_id)
    return coverage


def _audit_corpus_naming(findings: list[AuditFinding]) -> None:
    for expect_path in sorted(CORPUS_DIR.glob("**/expect.json")):
        case_id = expect_path.parent.name
        if case_id.endswith("-valid"):
            continue
        match = _E_RULE_CASE_RE.match(case_id)
        if not match:
            continue
        expected_rule = f"E{match.group(1)}"
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
        asserted: set[str] = set(expect.get("rules", []))
        for codes in expect.get("lines", {}).values():
            asserted.update(codes)
        if expected_rule not in asserted:
            rel = expect_path.parent.relative_to(CORPUS_DIR)
            findings.append(
                AuditFinding(
                    "error",
                    "corpus",
                    f"{rel} is named for {expected_rule} but expect.json does not assert it",
                )
            )


def _audit_full_rule_coverage(
    findings: list[AuditFinding], valid_rules: set[str]
) -> None:
    """Require every rule in rules.yaml to appear in at least one corpus case."""
    coverage = _corpus_rule_coverage()
    missing = sorted(valid_rules - set(coverage.keys()))
    if missing:
        findings.append(
            AuditFinding(
                "error",
                "corpus",
                f"Full rule corpus coverage incomplete: missing {', '.join(missing)}",
            )
        )


def _audit_reference_matrix(
    findings: list[AuditFinding], valid_rules: set[str]
) -> None:
    """Validate reference-matrix.yaml corpus paths and rule references."""
    if not REFERENCE_MATRIX_YAML.is_file():
        findings.append(
            AuditFinding(
                "error",
                "reference-matrix",
                "reference-matrix.yaml missing",
            )
        )
        return
    data = _load_yaml(REFERENCE_MATRIX_YAML)
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        findings.append(
            AuditFinding(
                "error",
                "reference-matrix",
                "entries must be a list",
            )
        )
        return
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        construct = str(entry.get("construct", f"entry[{index}]"))
        for case_id in entry.get("corpus", []):
            case_path = CORPUS_DIR / str(case_id)
            if not case_path.is_dir():
                findings.append(
                    AuditFinding(
                        "error",
                        "reference-matrix",
                        f"{construct}: corpus path not found: {case_id}",
                    )
                )
                continue
            if not any(case_path.glob("input.*")):
                findings.append(
                    AuditFinding(
                        "error",
                        "reference-matrix",
                        f"{construct}: corpus case has no input.cmd: {case_id}",
                    )
                )
        for rule_ref in entry.get("rules", []):
            code = str(rule_ref).strip()
            if code and code not in valid_rules:
                findings.append(
                    AuditFinding(
                        "error",
                        "reference-matrix",
                        f"{construct}: unknown rule reference {code}",
                    )
                )

    mapped_rules: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for rule_ref in entry.get("rules", []):
            code = str(rule_ref).strip()
            if code:
                mapped_rules.add(code)
    missing_matrix = sorted(valid_rules - mapped_rules)
    extra_matrix = sorted(mapped_rules - valid_rules)
    if missing_matrix:
        findings.append(
            AuditFinding(
                "error",
                "reference-matrix",
                f"Rules missing from reference-matrix rules lists "
                f"({len(missing_matrix)}): {', '.join(missing_matrix)}",
            )
        )
    if extra_matrix:
        findings.append(
            AuditFinding(
                "error",
                "reference-matrix",
                f"Unknown rules in reference-matrix: {', '.join(extra_matrix)}",
            )
        )

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        construct = str(entry.get("construct", f"entry[{index}]"))
        explicit = {str(rule_ref).strip() for rule_ref in entry.get("rules", [])}
        for artifact_line in entry.get("ssot_artifacts", []):
            for match in _SSOT_ARTIFACT_RULE_RE.findall(str(artifact_line)):
                if match in valid_rules and match not in explicit:
                    findings.append(
                        AuditFinding(
                            "warning",
                            "reference-matrix",
                            f"{construct}: {match} in ssot_artifacts but not in rules list",
                        )
                    )

    _audit_matrix_corpus_coverage(findings, entries)
    _audit_matrix_corpus_rule_alignment(findings, entries)


def _all_matrix_corpus_ids(entries: list[Any]) -> set[str]:
    corpus_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for case_id in entry.get("corpus", []):
            corpus_ids.add(str(case_id).replace("\\", "/"))
    return corpus_ids


def _audit_matrix_corpus_coverage(
    findings: list[AuditFinding], entries: list[Any]
) -> None:
    """Every corpus case should appear in at least one reference-matrix entry."""
    mapped = _all_matrix_corpus_ids(entries)
    for expect_path in sorted(CORPUS_DIR.glob("**/expect.json")):
        case_id = "/".join(expect_path.parent.relative_to(CORPUS_DIR).parts)
        if case_id not in mapped:
            findings.append(
                AuditFinding(
                    "error",
                    "reference-matrix",
                    f"Corpus case not mapped in reference-matrix: {case_id}",
                )
            )


def _audit_matrix_corpus_rule_alignment(
    findings: list[AuditFinding], entries: list[Any]
) -> None:
    """Warn when a matrix corpus case does not assert any of the entry's rules."""
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        construct = str(entry.get("construct", f"entry[{index}]"))
        entry_rules = {
            str(rule_ref).strip()
            for rule_ref in entry.get("rules", [])
            if str(rule_ref).strip()
        }
        if not entry_rules:
            continue
        for case_id in entry.get("corpus", []):
            case_key = str(case_id).replace("\\", "/")
            if case_key in _MATRIX_CORPUS_RULE_ALLOWLIST:
                continue
            asserted: set[str] = set()
            expect_path = CORPUS_DIR / case_key / "expect.json"
            if expect_path.is_file():
                expect = json.loads(expect_path.read_text(encoding="utf-8"))
                asserted = set(expect.get("rules", []))
                for codes in expect.get("lines", {}).values():
                    asserted.update(codes)
            if not (asserted & entry_rules):
                findings.append(
                    AuditFinding(
                        "warning",
                        "reference-matrix",
                        f"{construct}: corpus {case_key} does not assert any of "
                        f"{sorted(entry_rules)}",
                    )
                )


def _audit_docs_rule_count(findings: list[AuditFinding], valid_rules: set[str]) -> None:
    """Ensure hand-written Requirements.md prose matches rules.yaml count."""
    if not REQUIREMENTS_MD.is_file():
        findings.append(
            AuditFinding("error", "docs", "Batch-File-Linter-Requirements.md missing")
        )
        return
    text = REQUIREMENTS_MD.read_text(encoding="utf-8")
    match = _DOCS_RULE_COUNT_RE.search(text)
    if not match:
        findings.append(
            AuditFinding(
                "error",
                "docs",
                "Requirements.md missing 'currently **N** rules' prose count",
            )
        )
        return
    documented = int(match.group(1))
    expected = len(valid_rules)
    if documented != expected:
        findings.append(
            AuditFinding(
                "error",
                "docs",
                f"Requirements.md documents {documented} rules but rules.yaml has {expected}",
            )
        )


def _grammar_nodes_from_yaml() -> set[str]:
    data = _load_yaml(RULES_YAML)
    codes: set[str] = set()
    for rule in data.get("rules", []):
        if isinstance(rule, dict) and rule.get("grammar_nodes"):
            codes.add(str(rule["code"]))
    return codes


def _grammar_codes_from_generated() -> set[str]:
    if not GRAMMAR_RULES_PY.is_file():
        return set()
    text = GRAMMAR_RULES_PY.read_text(encoding="utf-8")
    if "GRAMMAR_BACKED_RULE_CODES" not in text:
        return set()
    return set(re.findall(r'"([A-Z]+\d+)"', text))


def _audit_grammar_nodes_drift(findings: list[AuditFinding]) -> None:
    yaml_codes = _grammar_nodes_from_yaml()
    generated = _grammar_codes_from_generated()
    if not GRAMMAR_RULES_PY.is_file():
        findings.append(
            AuditFinding(
                "error",
                "grammar",
                "grammar_rules.py missing — run generate_grammar_rules.py",
            )
        )
        return
    if yaml_codes != generated:
        missing = sorted(yaml_codes - generated)
        extra = sorted(generated - yaml_codes)
        findings.append(
            AuditFinding(
                "error",
                "drift",
                "grammar_nodes in rules.yaml != grammar_rules.py "
                f"(missing in generated: {missing or 'none'}; "
                f"extra in generated: {extra or 'none'})",
            )
        )


def _audit_requirements_duplicate_catalog(findings: list[AuditFinding]) -> None:
    if not REQUIREMENTS_MD.is_file():
        return
    text = REQUIREMENTS_MD.read_text(encoding="utf-8")
    if _CATALOG_END not in text:
        return
    after = text.split(_CATALOG_END, 1)[1]
    if re.search(r"^### Error Level Rules \(E001-E999\)", after, re.MULTILINE):
        findings.append(
            AuditFinding(
                "error",
                "docs",
                "Requirements.md has duplicate hand-written rule catalog after "
                "generated block — remove stale duplicate lists",
            )
        )


def _rules_from_patterns_py() -> set[str]:
    """Extract rule codes from DANGEROUS_COMMAND_PATTERNS tuples in patterns.py."""
    if not PATTERNS_PY.is_file():
        return set()
    text = PATTERNS_PY.read_text(encoding="utf-8")
    return set(_DANGEROUS_PATTERN_RULE_RE.findall(text))


def _rules_from_helpers_py() -> set[str]:
    """S011 is emitted via _s011_rule() in rules/helpers.py."""
    if not RULES_HELPERS_PY.is_file():
        return set()
    text = RULES_HELPERS_PY.read_text(encoding="utf-8")
    if _S011_RULE_USAGE_RE.search(text) and 'RULES["S011"]' in text:
        return {"S011"}
    return set()


def _collect_rules_referenced_in_code() -> set[str]:
    referenced: set[str] = set()
    search_roots = [CHECKERS_DIR, PARSING_DIR]
    for root in search_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            referenced.update(_RULES_IN_CODE_RE.findall(text))
            referenced.update(_RULE_CODE_KWARG_RE.findall(text))
    referenced.update(_rules_from_patterns_py())
    referenced.update(_rules_from_helpers_py())
    return referenced


def _audit_checker_orphans(findings: list[AuditFinding], valid_rules: set[str]) -> None:
    """Report rules.yaml entries with no RULES[...] reference in checker code."""
    referenced = _collect_rules_referenced_in_code()
    orphans = sorted(valid_rules - referenced)
    if orphans:
        findings.append(
            AuditFinding(
                "warning",
                "checkers",
                f"Rules without checker code reference ({len(orphans)}): "
                f"{', '.join(orphans[:20])}" + (" ..." if len(orphans) > 20 else ""),
            )
        )


def _audit_corpus(findings: list[AuditFinding], valid_rules: set[str]) -> None:
    coverage = _corpus_rule_coverage()
    _audit_corpus_naming(findings)
    _audit_full_rule_coverage(findings, valid_rules)
    target_rules = _E_RULE_COVERAGE_TARGET & valid_rules
    covered_target = target_rules & set(coverage.keys())
    missing_target = sorted(target_rules - set(coverage.keys()))
    if missing_target:
        findings.append(
            AuditFinding(
                "error",
                "corpus",
                f"E001–E047 corpus coverage incomplete: missing {', '.join(missing_target)}",
            )
        )
    error_rules = {c for c in valid_rules if c.startswith("E") and c[1:].isdigit()}
    covered_errors = error_rules & set(coverage.keys())
    pct = (len(covered_errors) / len(error_rules) * 100) if error_rules else 0.0
    target_pct = (
        (len(covered_target) / len(target_rules) * 100) if target_rules else 0.0
    )
    if target_pct < 100.0:
        findings.append(
            AuditFinding(
                "warning",
                "corpus",
                f"E001–E047 coverage {target_pct:.1f}% ({len(covered_target)}/{len(target_rules)})",
            )
        )
    if pct < 100.0:
        findings.append(
            AuditFinding(
                "error",
                "corpus",
                f"E-rule corpus coverage {pct:.1f}% ({len(covered_errors)}/{len(error_rules)}) "
                f"below 100% target",
            )
        )
    missing_ast = [
        "E009",
        "E011",
        "E017",
        "E019",
        "E030",
        "E031",
        "E032",
        "E033",
    ]
    for rule in missing_ast:
        if rule in coverage:
            continue
        if rule == "E019" and any(
            "e019" in case_id or "tilde" in case_id
            for cases in coverage.values()
            for case_id in cases
        ):
            continue
        findings.append(
            AuditFinding(
                "warning",
                "corpus",
                f"Grammar-backed rule {rule} has no corpus case",
            )
        )


def _audit_legacy_mode_removed(findings: list[AuditFinding]) -> None:
    """Fail if legacy dual-parser toggles remain in production or test code."""
    roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if _LEGACY_FORBIDDEN_RE.search(text):
                findings.append(
                    AuditFinding(
                        "error",
                        "legacy",
                        f"Legacy parser toggle found in {path.relative_to(REPO_ROOT)}",
                    )
                )


def _audit_visitor_coverage(
    findings: list[AuditFinding], valid_rules: set[str]
) -> None:
    """AST rules should be referenced from visitor modules (not orphaned)."""
    visitor_roots = [VISITORS_DIR, RULE_IMPL_DIR]
    referenced: set[str] = set()
    for root in visitor_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.name.startswith("_"):
                continue
            text = path.read_text(encoding="utf-8")
            referenced.update(_RULES_IN_CODE_RE.findall(text))
    orphans = sorted(valid_rules - referenced)
    if len(orphans) > 5:
        findings.append(
            AuditFinding(
                "warning",
                "visitors",
                f"Rules without visitor code reference ({len(orphans)}): "
                f"{', '.join(orphans[:15])} ...",
            )
        )


def _grammar_coverage_notes(findings: list[AuditFinding]) -> None:
    parser_g4 = (
        Path(__file__).resolve().parents[2] / "spec" / "grammar" / "BatchParser.g4"
    )
    if not parser_g4.is_file():
        return
    text = parser_g4.read_text(encoding="utf-8")
    required_snippets = [
        ("DEFINED", "IF DEFINED"),
        ("ifErrorlevelStmt", "IF ERRORLEVEL numeric"),
        ("ifBlockStmt", "IF/ELSE blocks"),
        ("LPAREN forList RPAREN", "FOR IN (...)"),
        ("exitStmt", "EXIT /B"),
        ("shiftStmt", "SHIFT"),
        ("EOF_KW", "GOTO :EOF"),
    ]
    for snippet, label in required_snippets:
        if snippet not in text:
            findings.append(
                AuditFinding(
                    "warning",
                    "grammar",
                    f"Grammar may be missing construct: {label} ({snippet})",
                )
            )


def run_audit() -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    valid_rules = _audit_rules(findings)
    _audit_commands(findings, valid_rules)
    _audit_commands_patterns_drift(findings)
    _audit_expansion_drift(findings)
    _audit_corpus(findings, valid_rules)
    _audit_reference_matrix(findings, valid_rules)
    _audit_docs_rule_count(findings, valid_rules)
    _audit_requirements_duplicate_catalog(findings)
    _audit_checker_orphans(findings, valid_rules)
    return findings


def _format_report(findings: list[AuditFinding]) -> str:
    lines = ["# SSOT Audit Report", ""]
    by_level: dict[str, list[AuditFinding]] = {"error": [], "warning": [], "info": []}
    for finding in findings:
        by_level.setdefault(finding.level, []).append(finding)
    for level in ("error", "warning", "info"):
        items = by_level.get(level, [])
        lines.append(f"## {level.upper()} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("_None_")
        else:
            for item in items:
                lines.append(f"- **[{item.category}]** {item.message}")
        lines.append("")
    return "\n".join(lines)


def _sync_baseline(report: str, out: Path, *, check: bool) -> bool:
    """Write the baseline when it changed. --check compares and writes nothing."""
    existing = out.read_text(encoding="utf-8") if out.is_file() else None
    if existing == report:
        print(f"{out} is unchanged")
        return True
    if check:
        print(f"SSOT baseline differs from {out}. Re-run without --check to update it.")
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8", newline="\n")
    print(f"Wrote {out}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Blinter SSOT consistency")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any error-level findings",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the report differs from the tracked baseline; write nothing",
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        default=None,
        help="Write markdown report to path (default: spec/audit/baseline-latest.md)",
    )
    args = parser.parse_args()
    findings = run_audit()
    report = _format_report(findings)
    print(report)
    out = (
        AUDIT_DIR / "baseline-latest.md"
        if args.check
        else args.write_baseline or (AUDIT_DIR / "baseline-latest.md")
    )
    if not _sync_baseline(report, out, check=args.check):
        raise SystemExit(1)
    errors = [f for f in findings if f.level == "error"]
    if args.strict and errors:
        raise SystemExit(1)
    if not errors:
        print("SSOT audit passed (no error-level findings)")


if __name__ == "__main__":
    main()
