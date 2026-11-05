# Batch Language Reference (Blinter)

Blinter analyzes Windows batch (`.bat`, `.cmd`) using a **regex and structure-aware checker
pipeline**. It does not embed the ANTLR parser at runtime.

## Authoritative sources

| Topic | Location |
|-------|----------|
| Batch grammar, expansion modifiers, builtin commands | [`vendor/batch-spec`](../vendor/batch-spec) submodule (`builtin_commands`, `common_external_tools`, deprecated/removed tables) |
| Linter rules and messages | [`spec/data/rules.yaml`](../spec/data/rules.yaml) |
| Security/style command policy | [`spec/data/commands-linter.yaml`](../spec/data/commands-linter.yaml) + batch-spec `commands.yaml` (merged; linter YAML pins W009 `older_windows_commands`) |
| Construct-to-rule mapping | [`spec/audit/reference-matrix.yaml`](../spec/audit/reference-matrix.yaml) |
| Behavioral fixtures | [`spec/corpus/`](../spec/corpus/) |

Pin updates are recorded in [`spec/batch-spec.lock`](../spec/batch-spec.lock). After changing
the pin, regenerate affected artifacts (`generate_commands.py`, `generate_expansion.py`) and run
`uv run python scripts/spec/audit_ssot.py --strict --check`. Without `--check` the audit rewrites `spec/audit/baseline-latest.md`.

## Checker pipeline (high level)

1. Read and decode source (`io/encoding.py`).
2. Build script structure: labels, SET variables, delayed expansion, subroutine prefixes
   (`parsing/structure.py`).
3. Run line-oriented and global checkers (`checkers/orchestration.py`).
4. Filter by config, inline suppressions, and severity.

All rule implementations live under `src/blinter/checkers/` and reference metadata from the
generated `rules/registry.py`.

## MS Learn and cmd-help

Batch-spec vendors captured `cmd /?` help text under `vendor/batch-spec/audit/cmd-help/`. The
reference matrix links constructs to those captures and to corpus cases.

## Further reading

- [Architecture.md](Architecture.md) — module map and SSOT split
- [Batch-File-Linter-Requirements.md](Batch-File-Linter-Requirements.md) — rule catalog and examples
- [spec/README.md](../spec/README.md) — corpus authoring and generators
