## Summary

<!-- What does this change do, and why? Keep it to a few sentences. -->

Fixes #

## Type of change

<!-- Tick all that apply. -->

- [ ] Bug fix (including a false positive or false negative)
- [ ] New or changed lint rule
- [ ] New feature or CLI/config option
- [ ] Output format change (text, JSON, SARIF, baseline)
- [ ] Installer, packaging or CI change
- [ ] Documentation only
- [ ] Refactor or tests only (no behavior change)

## How was this tested?

<!-- Commands you ran, the batch sample that shows the fix, before/after output. -->

## Checklist

- [ ] I ran `py scripts/verify.py` (or `python scripts/verify.py` on Linux/macOS) and it passes. It needs `uv` on `PATH`.
- [ ] I added or updated tests under `tests/`, extending an existing topical file where one fits.
- [ ] I recorded user-visible changes under `## [Unreleased]` in `CHANGELOG.md`.
- [ ] I did **not** bump `[project].version` in `pyproject.toml` (a version change on `main` triggers the release pipeline).
- [ ] I did not edit generated files by hand (`src/blinter/rules/registry.py`, `src/blinter/rules/expansion_data.py`, the generated parts of `src/blinter/patterns.py`, or the `GENERATED:rule-catalog` block in `docs/Batch-File-Linter-Requirements.md`).
- [ ] I did not edit `vendor/batch-spec`. Language-level fixes belong in [BatchLang/batch-spec](https://github.com/BatchLang/batch-spec).
- [ ] My commit messages are clear and imperative (for example "Fix false positive in E019").
- [ ] I have the right to contribute this code, and I agree it is licensed under AGPL-3.0-or-later.

## Rule changes

<!-- Complete this section only if you added, changed or removed a rule. Otherwise delete it. -->

- [ ] I updated `spec/data/rules.yaml` (and `spec/data/commands-linter.yaml` if command policy changed).
- [ ] I regenerated derived files with the `scripts/spec/generate_*.py` scripts, and their `--check` runs are clean.
- [ ] I implemented the check in the matching module under `src/blinter/checkers/` and wired it through `checkers/orchestration.py` where needed.
- [ ] I added a corpus case at `spec/corpus/<category>/<case-id>/` with `input.cmd` and `expect.json`.
- [ ] I included a `*-valid` case that must not fire, to guard against false positives.
- [ ] I did not normalize line endings in `spec/corpus/**` (those files are `-text` on purpose).
- [ ] `py scripts/spec/validate_spec.py`, `py scripts/spec/validate_corpus.py` and `py scripts/spec/audit_ssot.py --strict` pass.
- [ ] For a rule that scans every line, I checked it against pathological long lines and the benchmark baseline (`py scripts/benchmark_lint.py --check-baseline`).

**Rule code(s):**
**Behavior in cmd.exe (with a link or test result if possible):**

## Installer or script changes

<!-- Delete this section if you did not touch anything under scripts/. -->

- [ ] I changed `scripts/installer_ps/*.ps1` and the mirrored echo blocks in `scripts/install_blinter.cmd` and `scripts/uninstall_blinter.cmd` together (parity is enforced by `tests/test_installer_script_parity.py`).
- [ ] New shell code is in its own `.sh` file and passes ShellCheck. New PowerShell is in its own `.ps1`/`.psm1` file and passes PSScriptAnalyzer and Pester.
- [ ] `py scripts/verify.py --windows-only` passes on Windows (cmd.exe oracle, PSScriptAnalyzer, Pester, installer lint).

## Notes for reviewers

<!-- Anything that needs extra attention: trade-offs, follow-ups, known limitations, platforms you could not test. -->
