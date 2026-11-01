# Changelog

All notable changes to Blinter are documented in this file. Release tags follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- S010 reports no label a computed jump can reach: every label for `goto %ACTION%` or `call :%~1`, and those starting with `case_` for `goto case_%1`
- S010 still sees that jump after nested `IF` predicates and after `@`, and reads a `FOR` command from the `DO` after the input set. A `goto %` on a label line, or a `do` inside the set, does not hide other labels

## [1.1.55] - 2026-11-01

### Fixed

- S003 and W021 took time quadratic in the length of a run of spaces, such as `x &` followed by thousands of spaces, because their regular expressions rescanned the run from every space in it. S003 took about 7 seconds for 8,000 spaces. On long runs of spaces, both now run in linear time and return the same findings

### Changed

- The MegaLinter install pin is 1.1.55

## [1.1.54] - 2026-10-31

### Added

- `pymarkdownlnt` checks every Markdown file in the repository as part of `scripts/verify.py`

### Fixed

- P008, W022 and E006 ignore a `!VAR!` on a comment line
- S003 ignores double-quoted text, such as a PowerShell `-Command` argument, and a comment after a command separator
- W022 no longer treats SETLOCAL EnableDelayedExpansion as present when it appears only in a comment, an ECHO line, or a REM after a separator
- S003 still sees commands inside `cmd /c` and `cmd /k` strings, a caret-escaped quote does not hide the command between the quotes, and a comment after an even number of carets (`^^&`) is still a comment

### Changed

- The MegaLinter install pin is 1.1.54

## [1.1.53] - 2026-10-31

### Fixed

- S026 ignores a caret on a comment line or inside double quotes, such as a `findstr` pattern

### Changed

- The MegaLinter install pin is 1.1.53

## [1.1.52] - 2026-10-30

### Fixed

- W001 no longer treats a command whose name merely begins with `rem` (for example `remote.exe`) as a comment, so a script that ends on such a command is flagged for a missing exit code.
  Every checker now shares one comment test that accepts only `REM`, `@REM`, a lone `REM` and `::`, in any letter case.
  Several checkers previously missed `@REM`, a bare `REM`, or an upper-case `REM`
- The FOR-block scan behind the loop-scoped performance rules ignores parentheses inside quotes and after a caret, and its cache is reset at the start of every lint pass
- Several rules took seconds to minutes on long pathological lines because of nested wildcards in their regular expressions (the `%a%` pattern, the `>echo` command-injection pattern with its trailing space, FOR /F quoting in E047, the SEC009 and SEC022 to SEC024 patterns and others). They now run in linear time and return the same findings
- P010 flags DIR only when its output is piped or redirected to standard output and `/B` is absent, as the rule describes. It previously fired on any DIR line and suggested a `/F` switch that DIR does not have
- S008 accepts a comment directly above a block, W025 accepts `command || exit /b` on the same line, and W033 no longer reports a quoted CALL target that carries an extension
- The SARIF log reports `executionSuccessful: false` when a file could not be linted
- Standard output falls back to UTF-8 on consoles whose code page cannot encode the report, and the `--max-line-length` usage message is printed when the value is rejected
- `uninstall_blinter.cmd` removes only the exact Blinter entry from the user PATH. A directory name that merely contained the bin path, or a path with square brackets, was previously mishandled
- `scripts/verify.py` stops with a clear message when it runs on a non-CPython interpreter, because mypy does not support PyPy
- The lint-time scaling tests re-measure a failing comparison before reporting it, so a single scheduler stall on a shared runner (seen on `macos-15-intel`) no longer fails the build, while a real super-linear slowdown still fails every attempt.
  The build-script tests no longer share the generated `_build_version.py` file, which made them fail intermittently when run in parallel

### Changed

- A manual run of the release workflow now needs the `confirm_release` input when the version tag already exists, and it only replaces release assets when the tag points at the commit being built. The PyPI upload skips files that already exist, so a confirmed re-publish does not fail there. Release notes are extracted for the exact version being published
- The `dependency-graph` job no longer blocks the release version check
- The MegaLinter install pin is 1.1.52
- The documentation describes the exit codes, `--follow-calls`, `--fail-on`, `min_severity` and the SARIF semantics, and the package `Documentation` URL points at the project docs

### Added

- A negative corpus case for 120 rules that had none. `scripts/spec/audit_ssot.py` now fails when a rule has no case listing it in `must_not`, and the reference-matrix counts a `must_not` assertion as covering a construct. The corpus holds 417 cases

## [1.1.51] - 2026-10-29

### Changed

- `install_blinter.cmd` no longer needs an architecture. With no argument it installs the native build, and `x64` or `arm64` is an optional override. An unrecognized argument still downloads nothing, and `arm64` is still refused on a non-ARM64 PC
- PSScriptAnalyzer and Pester now find every PowerShell file under `scripts/` and `tests/` on their own. This brought the previously unchecked `InstallerPs.Helpers.ps1` and `TestInstallerPs.Tests.ps1` under lint, and their findings are fixed
- The PowerShell that `scripts/verify.py` ran as inline strings is now `scripts/verify_ps/*.ps1`, with Pester tests. The Unix installer test stand-ins for `curl`, `uname`, `id`, `getconf`, `sysctl` and `chmod` moved from Python strings to `tests/unix_stubs/`, where ShellCheck lints them
- The MegaLinter install pin is 1.1.51

### Added

- `scripts/install_blinter.sh` and `scripts/uninstall_blinter.sh` install and remove the standalone executable on Linux and macOS.
  The installer picks the native build, accepts an optional `x64` or `arm64` argument to override it, verifies the archive against the release `SHA256SUMS`, installs to `${XDG_DATA_HOME:-$HOME/.local/share}/blinter/bin`, and adds a marked PATH block to the shell startup files, which the uninstaller removes
- ShellCheck lints the shell scripts through `scripts/verify.py`, and the `quality-unix` CI job installs and uninstalls the real release on Linux and macOS, x64 and arm64
- `scripts/installer_ps/Write-CrlfScriptCopy.ps1` mirrors the line-ending bootstrap embedded in `install_blinter.cmd` and `uninstall_blinter.cmd`, so it is linted and covered by the batch parity checks like the other embedded PowerShell

## [1.1.50] - 2026-10-29

### Added

- Linux and macOS standalone executables. Releases include `Blinter-v1.1.50-Linux-x64.tar.gz`, `Blinter-v1.1.50-Linux-arm64.tar.gz`, `Blinter-v1.1.50-macOS-arm64.tar.gz`, and `Blinter-v1.1.50-macOS-x64.tar.gz`.
  Each archive contains a folder of the same name and a `blinter` binary.
  Linux binaries need glibc 2.39 or newer (Ubuntu 24.04 and newer). macOS binaries target macOS 15 on arm64 and x64 and are not notarized
- `SHA256SUMS` lists the SHA-256 digest of every release archive

### Changed

- The MegaLinter install pin is 1.1.50

## [1.1.49] - 2026-10-24

### Changed

- `install_blinter.cmd` downloads only `Blinter-<tag>-Windows-<arch>.zip` and expects `Blinter-<tag>-Windows-<arch>\blinter.exe`
- The MegaLinter install pin is 1.1.49

## [1.1.48] - 2026-10-24

### Added

- `yamllint` checks every YAML file in the repository as part of `scripts/verify.py`

### Fixed

- The install benchmark workflow checks out the repository, uses the matrix Python, and can upload artifacts. Release zips are verified and extracted with the same `Blinter-<tag>-Windows-<arch>/blinter.exe` layout as the installer
- A version already recorded in `pyproject.toml` still releases when its git tag does not exist, so a red release run can publish on the next green push

### Changed

- Windows release archives are `Blinter-v<version>-Windows-x64.zip` and `Blinter-v<version>-Windows-arm64.zip`. Each zip contains a folder of the same name, and `install_blinter.cmd` downloads that asset
- Until a Windows-named archive is the latest release, `install_blinter.cmd` also accepts the previous `Blinter-<tag>-<arch>.zip` name and folder. That fallback is removed in the next release
- The MegaLinter install pin is 1.1.48

## [1.1.47] - 2026-10-22

### Changed

- The installer accepts only `Blinter-<tag>-<arch>\blinter.exe` and no longer searches the archive for `blinter.exe`
- The MegaLinter install pin is 1.1.47

## [1.1.46] - 2026-10-22

### Changed

- `install_blinter.cmd` requires `x64` or `arm64`. With no argument, or any other argument, it downloads nothing. `arm64` is refused on a non-ARM64 PC. On ARM64, `x64` is allowed and the installer notes that `arm64` is the native build
- Each release zip contains a folder with the same name: `Blinter-v1.1.46-x64\blinter.exe` and `Blinter-v1.1.46-arm64\blinter.exe`
- The MegaLinter install pin is 1.1.46

## [1.1.45] - 2026-10-22

### Added

- Native Windows ARM64 `blinter.exe`, built and smoke-tested on `windows-11-arm`. Releases include `Blinter-v1.1.45-x64.zip` and `Blinter-v1.1.45-arm64.zip`

### Changed

- Nuitka builds no longer pass the default `--file-reference-choice=runtime` or a second `--include-package=blinter`. MSVC builds pass `--include-windows-runtime-dlls=yes` so a missing Visual Studio redistributable fails the build
- The MegaLinter install pin is 1.1.45

## [1.1.44] - 2026-10-21

### Added

- `--baseline` and `--update-baseline` record accepted findings and fail on a new finding or on a recorded one that no longer matches (#50)

### Fixed

- SEC012 no longer flags `REM` and `::` comments that mention a temporary path (#46)
- SEC013 no longer treats the first variable in a `FOR` set as a command (#47)
- `LINT:IGNORE` matches case-insensitively in ASCII only, so look-alike letters such as `ı` and `ſ` do not suppress rules (#48)
- Lines split only at LF, and a lone CR is dropped, matching cmd.exe (#49)

### Changed

- Pinned batch-spec to v0.72.4. A CR that is not part of CRLF is not a line break, and a caret plus CRLF stays one escaped ending
- The MegaLinter install pin is 1.1.44
- `scripts/verify.py` is the quality gate for local runs and CI.
  mypy and pylint check `src`, `scripts`, and `tests` from their config instead of a hand-maintained file list.
  bandit checks `src` and `scripts`. `--windows-only` replaces `--powershell-only` and includes the cmd.exe corpus oracle.
  `--skip-pytest` leaves the test suite to CI's matrix job.
  On Python 3.15, pylint runs in one process because parallel jobs crash while pickling the linter.

## [1.1.43] - 2026-10-19

### Added

- MegaLinter plugin descriptor for `.bat` and `.cmd` files (`mega-linter-plugin-blinter/blinter.megalinter-descriptor.yml`)
- `--fail-on` and the `fail_on` configuration key choose which severity exits 1. The default remains `security`

### Fixed

- The installer check accepts `blinter --version` output that names the standalone executable or the Python version and package directory
- `--follow-calls` walks each script's CALL list once, so cycles no longer re-expand until the depth limit
- E001, E002, E028, E033, E042, E045, and SEC013 no longer flag parenthesized command groups, dynamic `GOTO`/`CALL` parameters, empty `""` arguments, substring and replacement expansions, `PROGRAMFILES(X86)`, piped commands, or quoted variables next to operators
- A configuration file with a UTF-8 BOM is read, and a file that cannot be parsed or has an invalid boolean or integer names the file and key instead of falling back to defaults
- Long `IF` lines with many `&&` separators are checked in linear time

### Changed

- Pinned batch-spec to v0.72.3 (tooling and docs only; grammar and command catalogs unchanged)
- Package classifiers drop the Windows-only operating system entry and the code-generator topic
- `uv.lock` is tracked, and CI runs `uv lock --check`
- The SSOT audit `--check` mode fails when the tracked baseline would change
- Version lookup uses `pyproject.toml` only for a `src/` checkout named Blinter; otherwise it uses installed package metadata
- The README install and uninstall one-liners and the MegaLinter pin use v1.1.43

## [1.1.42] - 2026-10-15

### Fixed

- Command-casing checks no longer backtrack on long runs of spaces, and large files no longer rebuild delayed-expansion or label-block state for every line
- `CALL` targets that use backslashes resolve on Linux and macOS
- An explicit `--config` path that is missing or has an invalid `max_line_length` or `min_severity` fails instead of continuing with defaults
- Lines longer than 10,000 characters are reported and skipped so the rest of the file is still linted. A line over 1,000,000 characters still rejects the file
- The large-file size warning prints one decimal place
- The installer no longer deletes `blinter.exe` before a download succeeds, and an up-to-date marker is ignored when that executable is missing or will not run
- The uninstaller reads `!errorlevel!` inside parenthesized blocks and stops only its own `blinter.exe`
- Installer PowerShell reads paths from the environment and writes `REG_EXPAND_SZ` user `PATH` values back unexpanded

### Added

- E048 flags a line that exceeds the maximum length the linter will fully parse
- W071 flags parse-time `%errorlevel%`, `%random%`, `%time%`, and `%date%` inside a parenthesized block when that use is stale
- `blinter --version` names the standalone executable or the Python version and package directory
- The installer warns when another `blinter` is earlier on `PATH`
- Release jobs attest the Windows zip and the Python distributions

### Changed

- Package metadata accepts `charset-normalizer>=3.5.2,<4`. The Windows executable build still pins `charset-normalizer==3.5.2`
- Nuitka and setuptools are pinned in CI
- The README install and uninstall one-liners download the v1.1.42 scripts with `curl -fL --proto =https`
- Pinned batch-spec to v0.72.2

## [1.1.41] - 2026-10-15

### Changed

- `charset-normalizer` is pinned to 3.5.2 in package metadata and `requirements.txt`

## [1.1.40] - 2026-10-15

### Changed

- Package metadata requires Python `>=3.11,<3.16`, so installers skip Python 3.16 until that version is supported

## [1.1.39] - 2026-10-14

### Added

- Python 3.15 is supported. CI tests Python 3.11–3.15 on Ubuntu, macOS, and Windows, and the package classifiers list 3.15

### Fixed

- The Windows installer writes a SHA256 verifier that cmd does not cut short. Closing parentheses and the caret in the `sha256:` prefix are escaped, so a matching archive still verifies

### Changed

- Windows CI runs the installer and uninstaller, including Unix line endings. An elevated runner starts those scripts as a basic user

## [1.1.38] - 2026-10-14

### Changed

- Wheels and source distributions are built with uv_build. `docs/Architecture.md` and `docs/Batch-File-Linter-Requirements.md` stay in the repository and are no longer installed into `share/doc/blinter`

## [1.1.37] - 2026-10-14

### Added

- `--format sarif` emits a SARIF 2.1.0 report for GitHub Code Scanning and other SARIF consumers. Rule codes become rule IDs, and Error/Security, Warning, and Style/Performance map to SARIF levels `error`, `warning`, and `note`

### Changed

- Pinned batch-spec language SSOT to v0.72.1 (release tooling and docs; grammar and command catalogs are unchanged)

## [1.1.36] - 2026-10-14

### Fixed

- **E003** checks only the IF condition, so a valid line such as `if "%1"=="" set X=1` or `if ... echo a = b` is no longer a fatal error
- `--format json` keeps skipped-file details in the JSON report. When every file is skipped, stdout is still JSON
- **S028** leaves parentheses in place when the group chains commands with `&` or `|`
- **P022** and **P023** apply only inside a FOR block, including a one-line `for ... do`
- **W004** allows the usual `shift` loop that exits when the next argument is empty
- **P006** no longer requires ENDLOCAL before a top-level `exit /b`. Ending the batch file ends SETLOCAL
- A UTF-16 BOM is decoded as UTF-16. NUL bytes that are not valid UTF-8, UTF-16, or UTF-32 raise one encoding error instead of being read as cp1252
- Directory scans accept `.BAT` and `.CMD` on case-sensitive filesystems
- Piping output to a program that closes the pipe exits quietly
- The installer treats a PATH entry as present only when the segment matches exactly

### Changed

- CALL and GOTO checks remember the first line that targets each label, and sort label definitions once per file
- The performance gate uses the current synthetic timing and a second file with 2000 labels and unique CALL targets. A case fails when it takes more than twice that median
- Source distributions omit the `tests/` tree. Tests run from a git checkout
- GitHub Actions are pinned to commit SHAs, and PyPI publishing pins Twine 7.0.0
- Changelog links point at `BatchLang/Blinter`

## [1.1.35] - 2026-10-13

### Changed

- Pinned batch-spec language SSOT to v0.72.0 (standalone `{` `}` `[` `]` tokens; apostrophes do not pair across lines)

## [1.1.34] - 2026-10-12

### Changed

- FOR-block performance checks scan each file once instead of from line 1 on every line, so medium scripts no longer pay a quadratic cost
- **W068** compiles each variable's percent-expansion pattern once and matches the SET name once per command segment. Reported issues are unchanged

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

- **W036** reads a FOR /F command operand to the parenthesis that balances `IN (`, so nested `(` inside a backquoted command is not treated as a file ([#37](https://github.com/BatchLang/Blinter/issues/37), [#42](https://github.com/BatchLang/Blinter/pull/42))
- Drive-relative names such as `C:Set-Permissions` and `ForEach-Object.bat` are no longer classified as embedded PowerShell ([#38](https://github.com/BatchLang/Blinter/issues/38), [#42](https://github.com/BatchLang/Blinter/pull/42))
- **S010** ignores `CALL`/`GOTO` inside an inline `REM` or `ECHO` segment after `&` ([#39](https://github.com/BatchLang/Blinter/issues/39), [#42](https://github.com/BatchLang/Blinter/pull/42))
- **P024**/**P006** count `SETLOCAL`/`ENDLOCAL` after an `IF` predicate or `&` ([#40](https://github.com/BatchLang/Blinter/issues/40), [#42](https://github.com/BatchLang/Blinter/pull/42))

### Changed

- Pinned batch-spec language SSOT to v0.70.1 (FOR /F usebackq backtick commands keep nested parentheses as data)
- Spec docs, Architecture, and funding metadata match the 235-case corpus

## [1.1.25] - 2026-09-07

### Fixed

- PowerShell `Get-`/`Set-`/`Write-`/`New-` detection no longer backtracks into hyphenated filenames, and ignores `.psm1`/`.psd1`/`.ps1xml` script modules the same way as `.ps1`
- **P024** reports only a second real `SETLOCAL`; extra `ENDLOCAL` is left to its own rules

## [1.1.24] - 2026-09-07

### Fixed

- **P024** and **P006** no longer treat the word `setlocal`/`endlocal` inside comments as commands, and P024 reports the second real `SETLOCAL` ([#40](https://github.com/BatchLang/Blinter/issues/40))
- **S010** counts labels reached by `if ... goto`/`call` and `|| goto`, while ignoring `goto`/`call` inside comments or echo output ([#39](https://github.com/BatchLang/Blinter/issues/39))
- Hyphenated filenames such as `set-permissions.bat` are no longer classified as embedded PowerShell, so per-line rules still run ([#38](https://github.com/BatchLang/Blinter/issues/38))
- **W036** no longer treats FOR /F command operands (for example `powershell -NoProfile` under usebackq backticks) as data files ([#37](https://github.com/BatchLang/Blinter/issues/37))

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

- **E042** detects text after a closing parenthesis inside a parenthesized IF/FOR/(group) block, a fatal cmd.exe parse error (fixes [#36](https://github.com/BatchLang/Blinter/issues/36))

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

Older 1.0.x releases are available on the [GitHub Releases](https://github.com/BatchLang/Blinter/releases) page.

[1.1.55]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.55
[1.1.54]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.54
[1.1.53]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.53
[1.1.52]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.52
[1.1.51]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.51
[1.1.50]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.50
[1.1.49]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.49
[1.1.48]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.48
[1.1.47]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.47
[1.1.46]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.46
[1.1.45]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.45
[1.1.44]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.44
[1.1.43]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.43
[1.1.42]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.42
[1.1.41]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.41
[1.1.40]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.40
[1.1.39]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.39
[1.1.38]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.38
[1.1.37]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.37
[1.1.36]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.36
[1.1.35]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.35
[1.1.34]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.34
[1.1.33]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.33
[1.1.32]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.32
[1.1.31]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.31
[1.1.30]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.30
[1.1.29]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.29
[1.1.28]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.28
[1.1.27]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.27
[1.1.26]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.26
[1.1.25]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.25
[1.1.24]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.24
[1.1.23]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.23
[1.1.22]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.22
[1.1.21]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.21
[1.1.20]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.20
[1.1.19]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.19
[1.1.18]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.18
[1.1.17]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.17
[1.1.16]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.16
[1.1.15]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.15
[1.1.14]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.14
[1.1.13]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.13
[1.1.12]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.12
[1.1.11]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.11
[1.1.10]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.10
[1.1.9]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.9
[1.1.8]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.8
[1.1.7]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.7
[1.1.0]: https://github.com/BatchLang/Blinter/releases/tag/v1.1.0
