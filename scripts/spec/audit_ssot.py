#!/usr/bin/env python3
"""Read-only SSOT audit: rules, commands, expansion, corpus coverage, drift."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

import yaml

_REPO_ROOT_BOOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT_BOOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_BOOT))

from scripts.spec._commands_data import (  # noqa: E402  # pylint: disable=wrong-import-position
    builtin_commands_union,
    merged_commands_data,
)
from scripts.spec._paths import (  # noqa: E402  # pylint: disable=wrong-import-position
    AUDIT_DIR,
    BATCH_SPEC_DIR,
    CHECKERS_DIR,
    COMMANDS_LINTER_YAML,
    CORPUS_DIR,
    EXPANSION_DATA_PY,
    EXPANSION_YAML,
    PARSING_DIR,
    PATTERNS_PY,
    REFERENCE_MATRIX_YAML,
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


@dataclass(frozen=True)
class AuditFinding:
    """One SSOT audit result."""

    level: str
    category: str
    message: str


def _load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    mapping: dict[str, object] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ValueError(f"{path} keys must be strings")
        mapping[key] = value
    return mapping


def _audit_rules(findings: list[AuditFinding]) -> set[str]:
    data = _load_yaml(RULES_YAML)
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("rules.yaml rules must be a list")
    codes: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be a mapping")
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


def _merged_commands_data() -> dict[str, object]:
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
    patterns = data.get("dangerous_command_patterns", [])
    if isinstance(patterns, list):
        for entry in patterns:
            if not isinstance(entry, dict):
                continue
            rule_code = str(entry.get("rule_code", ""))
            if rule_code and rule_code not in valid_rules:
                findings.append(
                    AuditFinding(
                        "error",
                        "commands",
                        f"dangerous_command_patterns references unknown rule {rule_code}",
                    )
                )
    builtin_commands = data.get("builtin_commands", [])
    builtins = set(builtin_commands) if isinstance(builtin_commands, list) else set()
    deprecated_commands = data.get("deprecated_commands", {})
    deprecated = (
        set(deprecated_commands) if isinstance(deprecated_commands, dict) else set()
    )
    overlap = builtins & deprecated
    for name in sorted(overlap):
        findings.append(
            AuditFinding(
                "info",
                "commands",
                f"{name} is both builtin and deprecated (intentional for W024 recognition)",
            )
        )


def _read_patterns_constants() -> dict[str, object]:
    if not PATTERNS_PY.is_file():
        return {}
    module = ast.parse(PATTERNS_PY.read_text(encoding="utf-8"))
    constants: dict[str, object] = {}
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
        if kind not in {"list", "set"}:
            continue
        if not isinstance(yaml_val, (list, set)) or not isinstance(py_val, (list, set)):
            continue
        yaml_norm = sorted(str(item) for item in yaml_val)
        py_norm = sorted(str(item) for item in py_val)
        if yaml_norm != py_norm:
            findings.append(
                AuditFinding(
                    "error",
                    "drift",
                    f"commands YAML {yaml_key} != patterns.py {py_key}",
                )
            )
    builtin_yaml = builtin_commands_union(data)
    builtin_py_value = patterns.get("BUILTIN_COMMANDS", [])
    builtin_py = (
        sorted(str(item) for item in builtin_py_value)
        if isinstance(builtin_py_value, (list, set, frozenset))
        else []
    )
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
    valid_modifiers = data.get("valid_modifiers", {})
    yaml_modifier_keys = (
        "".join(sorted(str(key) for key in valid_modifiers))
        if isinstance(valid_modifiers, dict)
        else ""
    )
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


def _matrix_entries() -> list[object] | None:
    """Return reference-matrix entries, or None when the file is missing."""
    if not REFERENCE_MATRIX_YAML.is_file():
        return None
    data = _load_yaml(REFERENCE_MATRIX_YAML)
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("reference-matrix entries must be a list")
    return list(entries)


def _audit_matrix_paths_and_rules(
    findings: list[AuditFinding], entries: list[object], valid_rules: set[str]
) -> None:
    """Check each matrix row's corpus path and rule codes."""
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        construct = str(entry.get("construct", f"entry[{index}]"))
        corpus = entry.get("corpus", [])
        if isinstance(corpus, list):
            _audit_matrix_corpus_paths(findings, construct, corpus)
        rules = entry.get("rules", [])
        if isinstance(rules, list):
            _audit_matrix_rule_refs(findings, construct, rules, valid_rules)


def _audit_matrix_corpus_paths(
    findings: list[AuditFinding], construct: str, corpus: list[object]
) -> None:
    """Report matrix corpus paths that are missing or have no input script."""
    for case_id in corpus:
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


def _audit_matrix_rule_refs(
    findings: list[AuditFinding],
    construct: str,
    rules: list[object],
    valid_rules: set[str],
) -> None:
    """Report matrix rule codes that are not in rules.yaml."""
    for rule_ref in rules:
        code = str(rule_ref).strip()
        if code and code not in valid_rules:
            findings.append(
                AuditFinding(
                    "error",
                    "reference-matrix",
                    f"{construct}: unknown rule reference {code}",
                )
            )


def _audit_matrix_rule_coverage(
    findings: list[AuditFinding], entries: list[object], valid_rules: set[str]
) -> None:
    """Require the matrix rule lists to cover rules.yaml exactly."""
    mapped_rules: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rules = entry.get("rules", [])
        if not isinstance(rules, list):
            continue
        for rule_ref in rules:
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


def _audit_matrix_artifact_rules(
    findings: list[AuditFinding], entries: list[object], valid_rules: set[str]
) -> None:
    """Warn when an artifact line names a rule the entry does not list."""
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        construct = str(entry.get("construct", f"entry[{index}]"))
        rules = entry.get("rules", [])
        explicit = (
            {str(rule_ref).strip() for rule_ref in rules}
            if isinstance(rules, list)
            else set()
        )
        artifacts = entry.get("ssot_artifacts", [])
        if not isinstance(artifacts, list):
            continue
        for artifact_line in artifacts:
            for match in _SSOT_ARTIFACT_RULE_RE.findall(str(artifact_line)):
                if match in valid_rules and match not in explicit:
                    findings.append(
                        AuditFinding(
                            "warning",
                            "reference-matrix",
                            f"{construct}: {match} in ssot_artifacts but not in rules list",
                        )
                    )


def _audit_reference_matrix(
    findings: list[AuditFinding], valid_rules: set[str]
) -> None:
    """Validate reference-matrix.yaml corpus paths and rule references."""
    try:
        entries = _matrix_entries()
    except ValueError as error:
        findings.append(AuditFinding("error", "reference-matrix", str(error)))
        return
    if entries is None:
        findings.append(
            AuditFinding(
                "error",
                "reference-matrix",
                "reference-matrix.yaml missing",
            )
        )
        return
    _audit_matrix_paths_and_rules(findings, entries, valid_rules)
    _audit_matrix_rule_coverage(findings, entries, valid_rules)
    _audit_matrix_artifact_rules(findings, entries, valid_rules)
    _audit_matrix_corpus_coverage(findings, entries)
    _audit_matrix_corpus_rule_alignment(findings, entries)


def _all_matrix_corpus_ids(entries: list[object]) -> set[str]:
    corpus_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for case_id in entry.get("corpus", []):
            corpus_ids.add(str(case_id).replace("\\", "/"))
    return corpus_ids


def _audit_matrix_corpus_coverage(
    findings: list[AuditFinding], entries: list[object]
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
    findings: list[AuditFinding], entries: list[object]
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
            if not asserted.intersection(entry_rules):
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


def run_audit() -> list[AuditFinding]:
    """Run every SSOT consistency check and return the findings."""
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
    """Audit SSOT files and optionally compare the report to the baseline."""
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
