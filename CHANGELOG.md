# Changelog

All notable changes to Blinter are documented in this file. Release tags follow [Semantic Versioning](https://semver.org/).

## [1.1.33] - 2026-10-12

### Changed

- The `_build_version.pyi` type stub stays in the repository for type checking and is excluded from the wheel. It is not used at runtime

## [1.1.32] - 2026-10-12

### Changed

- Standalone `blinter.exe` compiles its version from `pyproject.toml` at build time. It no longer unpacks a bundled `pyproject.toml` to answer `--version`
- The generated version module is removed after the Nuitka compile, so a later wheel build does not ship it. pip installs still take the version from package metadata

## [1.1.31] - 2026-09-22

### Changed

- Canonical repository, installer, and security contact are the [BatchLang organization](https://github.com/BatchLang/Blinter) and BatchLang@proton.me
- Standalone `blinter.exe` reports company BatchLang and extracts native files to `%LOCALAPPDATA%\BatchLang\Blinter\<version>`

## [1.1.30] - 2026-09-20

### Fixed

- **W063** scopes FOR /F token overflow to the current loop: nested `FOR /F` (including `@` and `IF EXIST` prefixes) is not treated as outer overflow, `echo (` does not swallow the next line, and `DO` inside `IN (...)` is not the loop body
- **W049** still warns when SET assigns a space-only value to a pseudo-environment variable; `SET "errorlevel="` remains a valid clear

### Changed

- Parenthesis-depth and empty-assignment caches live in parsing with identity-safe keys, so large scripts lint without quadratic scans and without a checkers/parsing import cycle
- Coverage, mypy, pylint (`fail-under=10`), and pytest configs drop unused boilerplate; coverage still maps installed `site-packages/blinter` into `src/blinter`

## [1.1.29] - 2026-09-20

### Changed

- Windows `blinter.exe` Nuitka builds install `charset-normalizer` as pure Python and nofollow unused `ssl`/`socket`/`wmi` extensions so fewer CPython `.pyd` files unpack at runtime
- Architecture docs cover the x64 onefile extract layout; the README still warns that antivirus may false-positive the standalone exe

## [1.1.28] - 2026-09-17

### Added

- Fifteen cmd.exe rules (E043–E047, SEC025, W064–W070, S029–S030) covering `::` inside blocks, ELSE on a new line, invalid FOR/IF switches, spaced `2> &1`, unescaped FOR /F specials, unquoted `%CD%`, IF wildcards, parse-time `%var%` after SET in a block, `%TIME%` space padding, and SET/PATH/PROMPT `&&` in `.bat` files
- Corpus fixtures for those rules (274 committed cases)

### Fixed

- **E046** flags only a space before `&` in stream merges (`2> &1`); `2>>&1` is valid append-duplication on live cmd
- **W017** also flags `IF ERRORLEVEL 0` (always true for non-negative codes)
- **E036** also flags `IF EXIT` / `IF EXITS` misspellings of EXIST
- **E003** flags a single `=` in IF and a missing space before `(`
- **W044** flags `SET` with a space before `=` even without a space after
- **SEC001** / **SEC014** retargeted to unquoted SET /P dataflow and unquoted arguments

### Changed

- Pinned batch-spec language SSOT to v0.71.0 (EXIST misspellings, single-equals IF, unknown FOR switches, spaced handle duplication)
- Spec docs, Architecture, and funding metadata match the 274-case corpus; synthetic lint baseline is 25.0s for the extra cmd.exe checks

## [1.1.27] - 2026-09-09

### Added

- uv support for install (`uv tool install Blinter`, `uvx blinter`) and development (`uv sync --extra dev`); CI Python installs use uv. pip remains a first-class path.

## [1.1.26] - 2026-09-07

### Fixed

- **W036** reads a FOR /F command operand to the parenthesis that balances `IN (`, so nested `(` inside a backquoted command is not treated as a file ([#37](https://github.com/tboy1337/Blinter/issues/37), [#42](https://github.com/tboy1337/Blinter/pull/42))
- Drive-relative names such as `C:Set-Permissions` and `ForEach-Object.bat` are no longer classified as embedded PowerShell ([#38](https://github.com/tboy1337/Blinter/issues/38), [#42](https://github.com/tboy1337/Blinter/pull/42))
- **S010** ignores `CALL`/`GOTO` inside an inline `REM` or `ECHO` segment after `&` ([#39](https://github.com/tboy1337/Blinter/issues/39), [#42](https://github.com/tboy1337/Blinter/pull/42))
- **P024**/**P006** count `SETLOCAL`/`ENDLOCAL` after an `IF` predicate or `&` ([#40](https://github.com/tboy1337/Blinter/issues/40), [#42](https://github.com/tboy1337/Blinter/pull/42))

### Changed

- Pinned batch-spec language SSOT to v0.70.1 (FOR /F usebackq backtick commands keep nested parentheses as data)
- Spec docs, Architecture, and funding metadata match the 235-case corpus

## [1.1.25] - 2026-09-07

### Fixed

- PowerShell `Get-`/`Set-`/`Write-`/`New-` detection no longer backtracks into hyphenated filenames, and ignores `.psm1`/`.psd1`/`.ps1xml` script modules the same way as `.ps1`
- **P024** reports only a second real `SETLOCAL`; extra `ENDLOCAL` is left to its own rules

## [1.1.24] - 2026-09-07

### Fixed

- **P024** and **P006** no longer treat the word `setlocal`/`endlocal` inside comments as commands, and P024 reports the second real `SETLOCAL` ([#40](https://github.com/tboy1337/Blinter/issues/40))
- **S010** counts labels reached by `if ... goto`/`call` and `|| goto`, while ignoring `goto`/`call` inside comments or echo output ([#39](https://github.com/tboy1337/Blinter/issues/39))
- Hyphenated filenames such as `set-permissions.bat` are no longer classified as embedded PowerShell, so per-line rules still run ([#38](https://github.com/tboy1337/Blinter/issues/38))
- **W036** no longer treats FOR /F command operands (for example `powershell -NoProfile` under usebackq backticks) as data files ([#37](https://github.com/tboy1337/Blinter/issues/37))

### Changed

- Spec docs, Architecture, and funding metadata match the 231-case corpus

## [1.1.23] - 2026-09-07

### Changed

- Windows `blinter.exe` Nuitka build uses LTO, cached onefile extract, stripped docstrings/asserts, and unused-stdlib nofollow; UPX stays off

## [1.1.22] - 2026-09-07

### Changed

- Windows standalone `blinter.exe` is now built with Nuitka (`scripts/build_exe.py`) instead of PyInstaller

### Fixed

- Frozen `blinter.exe --version` reads the bundled `pyproject.toml` from the Nuitka extract layout

## [1.1.21] - 2026-08-31

### Changed

- Pinned batch-spec language SSOT to v0.70.0 (unquoted `)` inside a command group closes the group; leftover text is a syntax error)

## [1.1.20] - 2026-08-30

### Added

- **E042** detects text after a closing parenthesis inside a parenthesized IF/FOR/(group) block, a fatal cmd.exe parse error (fixes [#36](https://github.com/tboy1337/Blinter/issues/36))

### Changed

- Spec docs, Architecture, and funding metadata match the 226-case corpus and 176 rules

## [1.1.19] - 2026-08-29

### Fixed

- Embedded C#/JScript/VBScript skip detection: in-file JScript polyglots, tighter VBScript and C# starters, and `if`/`for` inside those blocks no longer close the skip region (`echo`-to-temp payloads and `cscript`/`wscript` invocations stay linted)

### Added

- SSOT corpus fixtures for embedded skip behavior (`embedded-csharp-skip`, `embedded-jscript-skip`, `embedded-vbscript-skip`)

### Changed

- Spec docs, Architecture, and funding metadata match the 222-case corpus
- Installer Pester tests exercise PATH update/remove, archive expand, and download-size fixtures without mutating the real User PATH

## [1.1.18] - 2026-08-29

### Added

- Standalone installer verifies the GitHub release zip SHA256 before extracting
- Compatibility and Unicode warning checks live in `warnings_compat` (W009, W010, W011, W027, W029)

### Fixed

- Installer SHA256 verification hashes with .NET so it works when Windows PowerShell inherits pwsh's `PSModulePath` (GitHub Actions Windows jobs)

### Changed

- Windows CI runs the cmd.exe corpus oracle; the Linux quality job validates the spec corpus
- cmd.exe oracle executes read-only WMIC queries (still present on Windows 10); interactive or mutating WMIC remains skipped
- Spec docs, Architecture, and funding metadata match the 219-case corpus and batch-spec lock v0.69.2
- README documents large-file handling as a 10MB warning and 50MB reject
- Removed unused SST experiment scripts (`port_rule_impl.py`, `compare_patterns.py`, `experiment_benchmark.py`)

## [1.1.17] - 2026-08-13

### Changed

- CI and release are a single Test workflow: CodeQL, dependency graph submission, and PyPI/GitHub release run in one pipeline with explicit `needs` dependencies (no `workflow_run` chaining)
- CodeQL analysis runs in CI for Python and GitHub Actions workflow files; GitHub default CodeQL setup must remain disabled (Settings > Code security)

## [1.1.16] - 2026-08-13

### Changed

- Build-Release-PYPI gated release on Test, CodeQL, and Dependency Graph (superseded by unified Test workflow pipeline)

## [1.1.15] - 2026-08-13

### Fixed

- **W004** only flags backward `goto` jumps (forward exit-handler jumps no longer reported as infinite loops)
- **W043** accepts `tasklist` verification on preceding lines in the same block, not only on the `taskkill` line
- **W014** ignores `set /p VAR=<file` file-input redirection and treats `timeout /t` as an alternative to `pause`
- **P006** skips `exit /b` returns from `call :subroutine` labels
- **SEC013** adds safe patterns for installer-style PowerShell `-File`, quoted executable redirection, and `curl` output
- **W020** and **P009** treat `delims=` as a valid `FOR /F` option for whole-line capture

### Changed

- `scripts/blinter.ini` installer profile shrinks from 21 to 10 disabled rules now that false positives are resolved
- Install and uninstall scripts include clearer comments for resume paths and user-facing messages

### Added

- SSOT corpus negative controls for the fixed rules (`w004-goto-exit-handler`, `w043-tasklist-before-taskkill`, `w014-setp-from-file-valid`, `p006-subroutine-exit-valid`, `sec013-installer-redirection-valid`, `for-f-delims-only-valid`, `p009-w020-for-f-missing-options`)

## [1.1.14] - 2026-08-13

### Changed

- README badge formatting updated from paragraph to `div` layout for presentation consistency

## [1.1.13] - 2026-08-13

### Changed

- README documents batch compatibility and encoding detection behavior more clearly
- PyPI download badges and license text formatting improved in README
- Minor formatting adjustments in `Blinter.spec`

## [1.1.12] - 2026-08-13

### Added

- OpenSSF Best Practices compliance files and README badges
- Dependabot configuration for pip and GitHub Actions updates
- `scripts/extract_release_notes.py` for release workflow changelog extraction

### Changed

- `CHANGELOG.md` moved to the repository root for OpenSSF detection

### Fixed

- `types-pyyaml` entry corrected in `requirements-dev.txt`
- Import order in `extract_release_notes.py` (isort)

## [1.1.11] - 2026-08-13

### Fixed

- SSOT audit strict-mode failures for E038, E019, and E008 negative-control corpus fixtures
- Black formatting in `tests/test_edge_cases.py`

## [1.1.10] - 2026-08-13

### Changed

- CI and quality-gate improvements

## [1.1.9] - 2026-08-12

### Changed

- Continued rule and corpus hardening

## [1.1.8] - 2026-08-12

### Added

- Application icon in the Windows executable build (`Blinter.spec`)
- Tests for icon configuration in the spec file

### Changed

- README updated for versioned standalone download naming

## [1.1.7] - 2026-08-11

### Changed

- Rule registry and checker refinements

## [1.1.0] - 2026-08-04

### Added

- Major 1.1 release line with expanded rule coverage and SSOT-driven rule generation

---

Older 1.0.x releases are available on the [GitHub Releases](https://github.com/tboy1337/Blinter/releases) page.

[1.1.33]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.33
[1.1.32]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.32
[1.1.31]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.31
[1.1.30]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.30
[1.1.29]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.29
[1.1.28]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.28
[1.1.27]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.27
[1.1.26]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.26
[1.1.25]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.25
[1.1.24]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.24
[1.1.23]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.23
[1.1.22]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.22
[1.1.21]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.21
[1.1.20]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.20
[1.1.19]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.19
[1.1.18]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.18
[1.1.17]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.17
[1.1.16]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.16
[1.1.15]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.15
[1.1.14]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.14
[1.1.13]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.13
[1.1.12]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.12
[1.1.11]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.11
[1.1.10]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.10
[1.1.9]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.9
[1.1.8]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.8
[1.1.7]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.7
[1.1.0]: https://github.com/tboy1337/Blinter/releases/tag/v1.1.0
