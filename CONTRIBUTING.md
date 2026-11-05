# Contributing to Blinter

Thank you for helping improve Blinter. This document explains how to report issues, propose changes, and meet the project's quality expectations.

## Ways to Contribute

- Report bugs or false positives via [GitHub Issues](https://github.com/BatchLang/Blinter/issues)
- Suggest new rules or features via [GitHub Issues](https://github.com/BatchLang/Blinter/issues)
- Submit pull requests with bug fixes, new rules, tests, or documentation
- Improve docs under `docs/` or the `README.md`

## Bug Reports

When filing a bug report, include:

- Blinter version (`blinter --version` or `python -m blinter --version`)
- Python version and OS
- Minimal `.bat` or `.cmd` sample that reproduces the issue
- Expected vs. actual behavior

Security issues must **not** be filed as public issues. See [SECURITY.md](SECURITY.md).

## Pull Request Process

1. Fork the repository and create a branch from `main`.
2. Clone with submodules: `git clone --recurse-submodules https://github.com/BatchLang/Blinter.git`
3. Install development dependencies: `uv sync --extra dev` (or `pip install -e ".[dev]"`)
4. Make your changes and add or update tests where appropriate.
5. Run the full local quality gate: `uv run python scripts/verify.py`. A bare `py scripts/verify.py` uses the global interpreter unless `.venv` is already activated.
6. Open a pull request against `main` with a clear description of the change and how you tested it.

Maintainers review PRs on GitHub. Address review feedback with additional commits on the same branch.

## Coding Standards

Match the existing codebase style:

| Tool | Purpose |
| ---- | ------- |
| [Black](https://black.readthedocs.io/) | Python formatting (`line-length = 88`) |
| [isort](https://pycqa.github.io/isort/) | Import sorting (Black-compatible profile) |
| [mypy](https://mypy-lang.org/) | Static type checking (`strict` mode) |
| [pylint](https://pylint.readthedocs.io/) | Linting (`pylintrc`) |
| [yamllint](https://yamllint.readthedocs.io/) | YAML files in the repository (`.yamllint.yaml`) |
| [PyMarkdown](https://pymarkdown.readthedocs.io/) | Markdown files in the repository (`.pymarkdown.yaml`) |
| [bandit](https://bandit.readthedocs.io/) | Security linting for Python |
| [ShellCheck](https://www.shellcheck.net/) | Every `.sh` file in `scripts/` and the stand-in commands in `tests/unix_stubs/` |
| [PSScriptAnalyzer](https://github.com/PowerShell/PSScriptAnalyzer) | Every `.ps1` and `.psm1` file under `scripts/` and `tests/` |
| [Pester](https://pester.dev/) | Every `*.Tests.ps1` file under `scripts/` and `tests/` |

Shell and PowerShell code lives in its own files so these tools can check it. Do not embed it in Python strings or workflow steps beyond a plain command. The PowerShell that `scripts/verify.py` runs is in `scripts/verify_ps/`, and the Unix test stand-ins are in `tests/unix_stubs/`. New files in those folders are picked up without registering them.

Auto-fix formatting before committing:

```bash
uv run python scripts/verify.py --fix
```

## Testing Policy

**Major new functionality must include automated tests.**

- Add or extend tests under `tests/` using [pytest](https://docs.pytest.org/).
- Rule changes should include corpus fixtures under `spec/corpus/` when applicable.
- Run `uv run python -m pytest` locally; CI runs the suite on Ubuntu, macOS, and Windows across Python 3.11–3.15. `pytest.ini` writes coverage reports and `tests/pytest.log` on every run. Pass `--override-ini=addopts=` and `--override-ini=log_file=` when a one-node run should not.
- A single corpus case is `uv run python -m pytest tests/test_spec_corpus.py -k <case-directory>`. `-k` matches the directory name. A docs-only prose change is `uv run python -m pymarkdown --strict-config scan <file>`. Catalog or README rule-count edits also need `uv run python scripts/spec/generate_docs.py --check`.

CI runs the same gate with `python scripts/verify.py --skip-pytest` on Ubuntu, and `python scripts/verify.py --windows-only` on Windows. pytest itself runs in a separate OS and Python matrix job (see `.github/workflows/CI.yml`). `--skip-pytest` skips only pytest.

`--windows-only` runs the cmd.exe oracle, `scripts/verify_ps/Install-VerifyModules.ps1` (which can install modules from PSGallery), PSScriptAnalyzer, Pester, and the install-script lint, including `scripts/test_install_scripts.ps1`. The `quality-unix` job runs `scripts/test_install_scripts.sh`.

## Rule and Spec Changes

Lint rules are defined in the SSOT under `spec/`. When adding or changing rules:

1. Update `spec/data/rules.yaml` and related generated artifacts as needed.
2. Run `uv run python scripts/spec/validate_spec.py`, `uv run python scripts/spec/validate_corpus.py`, `uv run python scripts/spec/audit_ssot.py --strict --check`, and the `generate_* --check` scripts (or `uv run python scripts/verify.py`). Without `--check`, the audit rewrites `spec/audit/baseline-latest.md`.
3. Add corpus cases under `spec/corpus/` with `input.cmd` and `expect.json`.

See [docs/Architecture.md](docs/Architecture.md) for module layout and extension points.

## Commit Messages

Write clear, imperative commit messages (e.g., "Add W064 rule for X", "Fix false positive in E019"). Version bumps in `pyproject.toml` are handled separately for releases.

## License

By contributing, you agree that your contributions are licensed under the same terms as the project: [AGPL-3.0-or-later](COPYING).
