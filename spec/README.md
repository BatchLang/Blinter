# Blinter Linter Specification

Blinter owns **linter** artifacts: rule catalog, security/style command policy, and the
274-case conformance corpus. The **batch language** SSOT lives in the pinned
[`batch-spec`](https://github.com/BatchLang/batch-spec) submodule at `vendor/batch-spec`.

## Submodule setup

```bash
git clone --recurse-submodules https://github.com/BatchLang/Blinter.git
# or after a plain clone:
git submodule update --init --recursive
```

The pinned release is recorded in [`batch-spec.lock`](batch-spec.lock) (currently `v0.72.0`).

## Layout

| Path | Purpose |
|------|---------|
| `data/rules.yaml` | Rule catalog (codes, severity, messages; `checker: regex`) |
| `data/commands-linter.yaml` | Linter policy: dangerous commands, casing, security patterns |
| `schema/` | JSON Schema for linter YAML validation |
| `corpus/` | Committed `.cmd` fixtures + `expect.json` oracles |
| `audit/` | Reference matrix and audit baselines |
| `benchmark/` | Synthetic lint performance baseline for CI |
| `batch-spec.lock` | Pinned batch-spec repo ref |

Language artifacts (grammar, expansion rules, command catalog, cmd-help captures) are in
`vendor/batch-spec/`. Grammar conformance is validated in that repository; Blinter uses the
regex checker pipeline only.

`generate_commands.py` merges batch-spec `commands.yaml` with `commands-linter.yaml` into
`patterns.py`. `BUILTIN_COMMANDS` is the union of upstream `builtin_commands` and
`common_external_tools` (dev-tool names that suppress E012/E014 false positives). W009's
`older_windows_commands` list is pinned in `commands-linter.yaml` so it does not follow
upstream's inverted list.

## Authoring a corpus case

Create `spec/corpus/<category>/<case-id>/`:

```
input.cmd      # Batch source under test
expect.json    # Expected diagnostics
```

Example `expect.json`:

```json
{
  "description": "Mismatched double quotes (E009)",
  "rules": ["E009"],
  "lines": { "2": ["E009"] },
  "must_not": [],
  "config": {},
  "tags": ["syntax", "quotes"]
}
```

Optional `expect.json` fields for cmd.exe oracle (`cmd_oracle.py`):

| Field | Purpose |
|-------|---------|
| `"oracle": "skip"` | Always skip execution (static-only fixture) |
| `"oracle": "run"` | Bypass content heuristics and always run |
| `"oracle_timeout_s": 10` | Per-case timeout override (seconds) |

## Code generation

```bash
py scripts/spec/generate_rules.py      # rules.yaml -> src/blinter/rules/registry.py
py scripts/spec/generate_expansion.py  # vendor/batch-spec/data/expansion.yaml -> expansion_data.py
py scripts/spec/generate_commands.py   # merge language + linter YAML -> patterns.py
py scripts/spec/generate_docs.py       # rules.yaml -> docs rule catalog sections
py scripts/spec/validate_spec.py       # Validate linter YAML + batch-spec language YAML
py scripts/spec/validate_corpus.py     # Validate corpus fixtures
py scripts/spec/audit_ssot.py --strict # SSOT drift and coverage audit
py scripts/spec/cmd_oracle.py          # Windows cmd.exe smoke oracle (safe subset only)
py scripts/benchmark_lint.py --check-baseline  # Performance regression gate
```

Run `py scripts/verify.py` for the full local verification pipeline (includes generator
`--check`, strict audit, and tests).
