# AGENTS.md

Guidance for coding agents working in this repository. Read [CONTRIBUTING.md](CONTRIBUTING.md), [docs/Architecture.md](docs/Architecture.md) and [spec/README.md](spec/README.md) for depth. This file only lists what an agent most needs to avoid mistakes.

## What this project is

Blinter is a read-only static analyzer (linter) for Windows batch files (`.bat`, `.cmd`). It parses source text and applies rule checkers; it never executes batch code. The only code that runs batch files is the test-only cmd.exe oracle in `scripts/spec/cmd_oracle.py`.

- Python `>=3.11,<3.16`, `src/blinter/` layout, one runtime dependency (`charset-normalizer`).
- License: AGPL-3.0-or-later.
- Entry point: `blinter = blinter.cli.main:main`; also `python -m blinter`.

## Setup

```bash
git clone --recurse-submodules https://github.com/BatchLang/Blinter.git
git submodule update --init --recursive   # if already cloned without submodules
uv sync --extra dev                       # or: pip install -e ".[dev]"
```

`vendor/batch-spec` is a pinned submodule (version recorded in `spec/batch-spec.lock`). Generators and the SSOT audit fail without it.

## Commands

```bash
py scripts/verify.py                  # full quality gate (requires uv on PATH)
py scripts/verify.py --fix            # apply autopep8, isort, pyproject-fmt fixes, then check
py scripts/verify.py --skip-pytest    # what the CI "quality" job runs
py scripts/verify.py --windows-only   # cmd.exe oracle, PSScriptAnalyzer, Pester, installer lint

py -m pytest                          # whole suite
py -m pytest tests/test_x.py::test_name
py -m pytest -m "not slow"

py -m blinter path\to\script.cmd      # run the linter itself
```

On Linux and macOS use `python` or `python3` in place of `py`. Run everything inside the project virtual environment (`.venv`). A global interpreter may carry other pytest plugins (for example `pytest-asyncio`) that fail under `filterwarnings = error`, and an older installed `blinter` can shadow the source tree for `python -m blinter`.

`verify.py` runs these steps in order, so the failing step name tells you which area broke: spec schema validation, corpus validation, generated-file `--check` steps, strict SSOT audit, `uv lock --check`, autopep8, isort, pyproject-fmt, black, yamllint, ShellCheck, mypy, pylint, bandit, pip-audit, benchmark baseline, pytest. On Windows it also runs the cmd.exe oracle, PSScriptAnalyzer, Pester and a blinter lint of the install scripts.

Pytest runs with a 300 second timeout, `filterwarnings = error` (any warning fails a test), `--strict-markers`, and coverage enabled. Tests marked `needs_corpus` skip unless the local, gitignored `batch-script-examples/` folder exists.

## Generated files: do not edit by hand

| File | Source | Regenerate with |
| ---- | ------ | --------------- |
| `src/blinter/rules/registry.py` | `spec/data/rules.yaml` | `py scripts/spec/generate_rules.py` |
| `src/blinter/rules/expansion_data.py` | `vendor/batch-spec/data/expansion.yaml` | `py scripts/spec/generate_expansion.py` |
| `src/blinter/patterns.py` (partly) | batch-spec `commands.yaml` + `spec/data/commands-linter.yaml` | `py scripts/spec/generate_commands.py` |
| Rule catalog block in `docs/Batch-File-Linter-Requirements.md` (between `GENERATED:rule-catalog` markers) | `spec/data/rules.yaml` | `py scripts/spec/generate_docs.py` |

Each generator supports `--check`, which `verify.py` uses to detect drift. `src/blinter/_build_version.py` is a gitignored build artifact. Do not edit `vendor/batch-spec`; language-level changes belong in `BatchLang/batch-spec`.

## Adding or changing a rule

1. Edit `spec/data/rules.yaml` (and `spec/data/commands-linter.yaml` for command policy changes).
2. Run the generators listed above.
3. Implement the check in the matching module under `src/blinter/checkers/` and wire it through `checkers/orchestration.py` if needed.
4. Add a corpus case at `spec/corpus/<category>/<case-id>/` with `input.cmd` and `expect.json` (format and oracle fields are in `spec/README.md`). Include a `*-valid` case that must not fire, to guard against false positives.
5. Run `py scripts/spec/validate_spec.py`, `py scripts/spec/validate_corpus.py` and `py scripts/spec/audit_ssot.py --strict`, then the full gate.

Every rule in `rules.yaml` must have at least one corpus assertion. `spec/corpus/**` is marked `-text` in `.gitattributes` so bytes are preserved exactly for line-ending rules; never normalize line endings in those files and do not let an editor rewrite them.

## Code conventions

- Black at 88 columns, isort (black profile, `force_sort_within_sections`), mypy strict, and `pylintrc`. `mypy.ini` also sets `disallow_any_expr` and `disallow_any_explicit` for `src`; tests and `scripts` have relaxed overrides. Do not add `Any`; use `object` and narrow.
- Imports go at the top of the module.
- Console output belongs in `cli/` and `output/`. Use the `logging` module for diagnostics elsewhere.
- The stable public API is `blinter.__all__`. Checker facades (`checkers/advanced/__init__.py`, `checkers/globals/__init__.py`) re-export symbols; when you add or move a checker function, update the facade import and its `__all__`.
- Keep linting thread-safe: per-lint state lives in a `ContextVar` reset at the start of `lint_batch_file`, `engine/lines_cache.py` is lock-protected, and `RULES` is read-only at runtime.
- Never read or lint paths outside `BlinterConfig.scan_root` (relevant to `--follow-calls`).

## Shell, PowerShell and batch files

- Keep each language in its own file so its linter can check it. Do not embed shell or PowerShell in Python strings or workflow steps beyond a plain command. New files in `scripts/verify_ps/` and `tests/unix_stubs/` are picked up automatically.
- `scripts/installer_ps/*.ps1` are mirrored as echo blocks inside `scripts/install_blinter.cmd` and `scripts/uninstall_blinter.cmd`. `tests/test_installer_script_parity.py` enforces byte parity; change both sides together.
- `.sh` scripts must pass ShellCheck (`.shellcheckrc`) and stay compatible with Bash 3.2 (macOS).
- PowerShell targets Windows PowerShell 5.1 and must pass PSScriptAnalyzer (`scripts/PSScriptAnalyzerSettings.psd1`) and Pester (`*.Tests.ps1`).
- Line endings come from `.gitattributes`: CRLF for `.bat`, `.cmd`, `.reg`, `.ps1`, `.psm1`, `.psd1`; LF for Python, Markdown, YAML, JSON, TOML and `.sh`.

## Tests

- Tests live in `tests/`. Add to the existing topical file (for example `tests/test_sarif_output.py`) rather than creating a similarly named new one.
- Corpus-driven rule tests run through `tests/test_spec_corpus.py`; add a corpus case instead of a bespoke test when the behavior is a rule diagnostic.
- Unix installer tests run the real scripts under bash with stand-ins from `tests/unix_stubs/`.
- Performance is gated by `py scripts/benchmark_lint.py --check-baseline` against `spec/benchmark/synthetic-baseline.json`.

## Versioning and releases

- A change to `[project].version` in `pyproject.toml` that lands on `main` triggers the release pipeline (`scripts/ci_release.py`, `.github/workflows/CI.yml`). Do not bump the version in ordinary changes.
- A release bump must also update the pinned version in `mega-linter-plugin-blinter/blinter.megalinter-descriptor.yml` and `docs/MegaLinter.md` (checked by `tests/test_megalinter_plugin.py`), refresh `uv.lock`, and add a dated section to `CHANGELOG.md`.
- Record user-visible changes under `## [Unreleased]` in `CHANGELOG.md`.
- Write clear, imperative commit messages, for example "Add W064 rule for X" or "Fix false positive in E019".
- Documentation belongs in `docs/`, except `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` and this file.

## Do not commit

Local artifacts: `pylint-output.txt`, `coverage.xml`, `.coverage`, `htmlcov/`, `testResults.xml`, `tests/pytest.log`, `.mypy_cache/`, `.hypothesis/`, `batch-script-examples/`, `tests/fixtures/corpus-baseline.json`, `dist/`, `build/`. Most are already gitignored. Report security issues privately per [SECURITY.md](SECURITY.md), not in public issues.
