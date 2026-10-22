# Blinter

<div align="center">

[![Supported Python versions](https://img.shields.io/pypi/pyversions/Blinter.svg)](https://pypi.org/project/Blinter)
[![PyPI Downloads (month)](https://static.pepy.tech/personalized-badge/blinter?period=month&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads%20%2F%20month)](https://pepy.tech/projects/blinter)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14056/badge)](https://www.bestpractices.dev/projects/14056)
![Linux](https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black)
![macOS](https://img.shields.io/badge/macOS-333333?logo=apple&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-0078D4?logo=windows&logoColor=white)

</div>

**Blinter** is a linter for Windows batch files (`.bat` and `.cmd`). It provides static analysis to identify syntax errors, security vulnerabilities, performance issues and style problems. Blinter helps you write safer, more reliable and maintainable batch scripts on Linux, macOS or Windows.

- ✅ **Configurable Options** - Configurable rules, `--verbose`/`--quiet` logging, robust error handling
- ✅ **Unicode Support** - Support for international characters and filenames
- ✅ **Performance Optimized** - Handles large batch files efficiently

## Features ✨

### 🔍 **Rule Categories**
- **Built-in Rules** -- the registry currently ships **193** rules across 5 severity levels (see `blinter.rules.registry.RULE_COUNT`)
- **Error Level (E001-E999)**: Critical syntax errors that prevent execution
- **Warning Level (W001-W999)**: Potential runtime issues and bad practices
- **Style Level (S001-S999)**: Code formatting and readability improvements
- **Security Level (SEC001+)**: Security vulnerabilities and dangerous operations
- **Performance Level (P001-P999)**: Optimization opportunities and efficiency improvements

📖 **For complete rule descriptions with examples and implementation details, see [Batch-File-Linter-Requirements.md](https://github.com/BatchLang/Blinter/blob/main/docs/Batch-File-Linter-Requirements.md)**

### 📋 **Output Format**
- **Rule Codes**: Each issue has a unique identifier (e.g., E002, W005, SEC003)
- **Clear Explanations**: Detailed descriptions of why each issue matters
- **Actionable Recommendations**: Specific guidance on how to fix problems
- **Line-by-Line Analysis**: Precise location of every issue
- **Context Information**: Additional details about detected problems

### 🚀 **Advanced Analysis**
- **Static Code Analysis**: Detects unreachable code and logic errors
- **Variable Expansion**: Validates percent-tilde syntax (%~n1), string operations, and SET /A arithmetic
- **Command-Specific Validation**: FOR loop variations, IF statement best practices, deprecated command detection
- **Variable Tracking**: Identifies undefined variables and unsafe usage patterns
- **Security Scanning**: Path traversal attacks, command injection risks, unsafe temp file creation
- **Performance Optimization**: DIR flag optimization, unnecessary output detection, string operation efficiency
- **Cross-Platform Batch Compatibility**: Warns about Windows version issues and deprecated commands in batch scripts
- **Large File Handling**: Efficiently processes large batch files, with a warning when a file exceeds 10MB and a hard reject above 50MB
- **Encoding Detection**: Automatic detection via `charset-normalizer`, with nine built-in fallbacks (UTF-8, UTF-8 BOM, UTF-16, UTF-32, Latin-1, ASCII, CP437, CP850, CP1252)
- **Escaping Techniques**: Validates caret escape sequences, multilevel escaping, and continuation characters
- **FOR Command Analysis**: Checks for usebackq, proper tokenizing, delimiters, and skip options
- **Process Management Best Practices**: Timeout command usage, process verification, and restart patterns
- **Security Patterns**: User input validation, temporary file security, and self-modification detection

## Installation 🛠️

### 🚀 Quick Start (Recommended)

**Option 1: Install via pip**
```bash
pip install Blinter
```

**Option 2: Install via uv**
```bash
uv tool install Blinter
```

Run without installing:

```bash
uvx blinter
```

**Option 3: Standalone executable**

If you prefer a standalone `.exe` over pip or uv, use the one-line installer via cmd:

```cmd
curl -fL --proto =https https://raw.githubusercontent.com/BatchLang/Blinter/refs/heads/main/scripts/install_blinter.cmd -o install_blinter.cmd && (call install_blinter.cmd || cd .) && del install_blinter.cmd
```

This installs the latest `blinter.exe` to `%LOCALAPPDATA%\Programs\Blinter\bin`, adds it to your user `PATH`, and handles updates automatically. Restart your terminal or IDE after installation for `PATH` changes to take effect.

**Manual zip download (fallback):**
- Download the latest `Blinter-v1.x.x.zip` from [GitHub Releases](https://github.com/BatchLang/Blinter/releases)
- Extract the archive; the executable is `Blinter-v1.x.x\blinter.exe`
- The one-line installer above is preferred; it keeps `blinter` on your `PATH` without manual setup.
- ⚠️ **Note**: Some antivirus software may flag the standalone executable as a false positive. The executable is completely safe (all source code is open for inspection). If a scanner flags it, use pip installation.

### Uninstall

**Standalone executable (one-line un-installer) via cmd:**
```cmd
curl -fL --proto =https https://raw.githubusercontent.com/BatchLang/Blinter/refs/heads/main/scripts/uninstall_blinter.cmd -o uninstall_blinter.cmd && (call uninstall_blinter.cmd || cd .) && del uninstall_blinter.cmd
```

**pip installation:**
```bash
pip uninstall Blinter
```

**uv installation:**
```bash
uv tool uninstall Blinter
```

### Prerequisites
- **Python 3.11-3.15** (for the pip/uv install)
- **Windows OS 64-bit** (for the standalone executable)

## Usage 📟

### Basic Usage

**If installed via pip or uv:**
```bash
# Analyze a single batch file
blinter script.bat
# or
python -m blinter script.bat

# Analyze all batch files in a directory (recursive)
python -m blinter /path/to/batch/files

# Analyze batch files in directory only (non-recursive)
python -m blinter /path/to/batch/files --no-recursive

# Analyze with summary
python -m blinter script.bat --summary

# Analyze script and scripts it calls with shared variable context
python -m blinter script.bat --follow-calls

# Analyze with custom maximum line length
python -m blinter script.bat --max-line-length 120

# Create configuration file
python -m blinter --create-config

# Ignore configuration file
python -m blinter script.bat --no-config

# Get help
python -m blinter --help

# Get version
python -m blinter --version
```

**If using standalone executable (installer or manual download):**
```bash
# After the one-line installer, use blinter on PATH.
# Manual zip: run Blinter-v1.x.x\blinter.exe or add that folder to PATH.

# Analyze a single batch file
blinter script.bat

# Analyze all batch files in a directory (recursive)
blinter /path/to/batch/files

# Analyze batch files in directory only (non-recursive)
blinter /path/to/batch/files --no-recursive

# Analyze with summary
blinter script.bat --summary

# Analyze script and scripts it calls with shared variable context
blinter script.bat --follow-calls

# Analyze with custom maximum line length
blinter script.bat --max-line-length 120

# Get help
blinter --help

# Get version
blinter --version

# Create configuration file
blinter --create-config

# Ignore configuration file
blinter script.bat --no-config
```

### If you installed both

pip, uv, and the standalone installer can all put `blinter` on `PATH`. The installer appends `%LOCALAPPDATA%\Programs\Blinter\bin` and does not move that folder ahead of an existing copy. When another `blinter` is earlier on `PATH`, the installer prints that path and says the standalone folder will not win. `blinter --version` prints `standalone exe` or `Python 3.x` plus the package directory so you can see which copy is running. The uninstaller stops only `%LOCALAPPDATA%\Programs\Blinter\bin\blinter.exe`.

### Command Line Options

- `<path>`: Path to a batch file (`.bat` or `.cmd`) OR directory containing batch files
- `--summary`: Display summary statistics of issues found
- `--max-line-length <n>`: Set maximum line length for S011 and S020 rules (default: 100)
- `--no-recursive`: When processing directories, only analyze files in the specified directory (not subdirectories)
- `--follow-calls`: Automatically analyze scripts called by CALL statements and merge their variable context. When enabled, variables defined in called scripts (including transitively called scripts within depth and file limits) are recognized as "defined" in the calling script (position-aware: only after the CALL statement). This eliminates false positive undefined variable errors for configuration scripts. Each script's CALL list is walked once, including when scripts call each other in a cycle
- `--fail-on <level>`: Exit 1 when a finding is at or above this severity. Levels, from least to most severe: `style`, `performance`, `warning`, `security`, `error`. `none` never fails because of findings. The default is `security`, so Error and Security findings are fatal. This flag overrides `fail_on` in `blinter.ini`
- `--baseline <path>`: Accept findings recorded in a JSON file. A new finding still follows `--fail-on`. A recorded finding that no longer matches exits 1
- `--update-baseline`: Rewrite the `--baseline` file from the current findings. Requires `--baseline`. Entries for files that were not part of this run are kept
- `--config <path>`: Load settings from a custom configuration file instead of `blinter.ini` in the current directory
- `--no-config`: Don't use configuration file (blinter.ini) even if it exists
- `--create-config`: Create a default blinter.ini configuration file and exit
- `--create-config --force`: Overwrite an existing blinter.ini when creating the default configuration
- `--output <path>`: Write a structured report to the given file path. The file is JSON unless `--format sarif` is also set. Human-readable output stays on stdout unless `--format` is set
- `--format json`: Suppress human-readable stdout and emit JSON (to stdout, or only to `--output` when both flags are used)
- `--format sarif`: Suppress human-readable stdout and emit [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html) (to stdout, or only to `--output` when both flags are used). Paths are relative to the working directory, so run Blinter from the repository root when uploading to GitHub
- `--verbose`: Show detailed debug logging on stderr (DEBUG level)
- `--quiet`: Suppress non-error logging output (ERROR level only)
- `--help`: Show help menu and rule categories
- `--version`: Display version information

**Note:** Command line options override configuration file settings. Blinter automatically looks for `blinter.ini` in the current directory.

### Configuration File Options 📝

| Section | Setting | Description | Default |
|---------|---------|-------------|---------|
| `[general]` | `recursive` | Search subdirectories when analyzing folders | `true` |
| `[general]` | `show_summary` | Display summary statistics after analysis | `false` |
| `[general]` | `max_line_length` | Maximum line length for S011 and S020 rules | `100` |
| `[general]` | `max_scan_files` | Maximum batch files to scan in a directory | `1000` |
| `[general]` | `follow_calls` | Analyze scripts called by CALL statements with shared variable context | `false` |
| `[general]` | `min_severity` | Minimum severity level to report | None (all) |
| `[general]` | `fail_on` | Lowest severity that makes the process exit 1 (`style`, `performance`, `warning`, `security`, `error`, or `none`) | `security` |
| `[rules]` | `enabled_rules` | Comma-separated list of rules to enable exclusively | None (all enabled) |
| `[rules]` | `disabled_rules` | Comma-separated list of rules to disable | None |

**Configuration notes:**
- When both `enabled_rules` and `disabled_rules` are set, a rule must appear in `enabled_rules` to run; `disabled_rules` then removes matches from that allowlist.
- `max_line_length` in `blinter.ini` controls style rules S011/S020 (default `100`). A line longer than `10,000` characters is reported as E048 and skipped so the rest of the file is still linted. A line longer than 1,000,000 characters is rejected before linting.

### Command Line Override

Command line options always override configuration file settings:

```bash
# Use config file settings
python -m blinter myscript.bat

# Override config to show summary
python -m blinter myscript.bat --summary

# Analyze script and scripts it calls with shared variable context
python -m blinter myscript.bat --follow-calls

# Override config with custom line length
python -m blinter myscript.bat --max-line-length 100

# Ignore config file completely
python -m blinter myscript.bat --no-config

# Write JSON report to a file (human-readable output unchanged)
python -m blinter myscript.bat --output report.json

# Machine-readable JSON on stdout only
python -m blinter myscript.bat --format json

# JSON file only, no human-readable stdout
python -m blinter project/scripts --output results.json --format json

# SARIF 2.1.0 on stdout (GitHub Code Scanning upload)
python -m blinter myscript.bat --format sarif

# SARIF file only, no human-readable stdout
python -m blinter project/scripts --output results.sarif --format sarif
```

<a id="inline-suppression-comments"></a>

### 🔕 Inline Suppression Comments

You can suppress specific linter warnings directly in your batch files using special comments:

#### Suppress Next Line
```batch
REM LINT:IGNORE E009
ECHO '' .... Represents a " character
```

#### Suppress Current Line
```batch
REM LINT:IGNORE-LINE S013
```

#### Suppress Multiple Rules
```batch
REM LINT:IGNORE E009, W011, S004
ECHO Unmatched quotes "
```

#### Suppress All Rules on Line
```batch
REM LINT:IGNORE
REM This line and the next will be ignored for all rules
```

**Supported formats:**
- `REM LINT:IGNORE <code>` - Suppress specific rule(s) on the **next line**
- `REM LINT:IGNORE` - Suppress all rules on the **next line**
- `REM LINT:IGNORE-LINE <code>` - Suppress specific rule(s) on the **same line**
- `REM LINT:IGNORE-LINE` - Suppress all rules on the **same line**
- `:: LINT:IGNORE <code>` - Alternative comment syntax (also supported)

The directive and its rule codes match case-insensitively in ASCII only. `lınt:ıgnore` and `ſEC008` are not a directive or a rule code, so they suppress nothing.

**Use cases:**
- Suppress false positives that can't be fixed
- Ignore intentional deviations from best practices
- Handle edge cases in documentation or help text
- Temporarily ignore issues during development

### Baseline file

`--baseline` records findings a project accepts without editing the script. Each finding has its own entry, matched on the rule code, the file path relative to the baseline file, and the trimmed text of the line. Line numbers are not part of the match, so inserting a line elsewhere does not invalidate an entry. Two identical lines need two entries.

```bash
blinter scripts --baseline blinter-baseline.json
blinter scripts --baseline blinter-baseline.json --update-baseline
```

```json
[
  {"code": "SEC009", "file": "scripts/update.bat", "text": "powershell -NoProfile -ExecutionPolicy Bypass ^"}
]
```

Paths use POSIX separators and are relative to the directory that contains the baseline file, so the same file works on Windows and on POSIX. `--update-baseline` rewrites the file from the current findings and keeps entries for files that were not scanned. A new finding exits 1 only when its severity is at or above `--fail-on` (or `fail_on`). A stale entry, one that no longer matches any finding in a file that was scanned, always exits 1.

The JSON report adds `summary.baselined_issues` and `stale_baseline_entries`. Text output lists stale entries. SARIF lists the new findings; a stale entry still exits 1.

### 🐍 **Programmatic API Usage**

Blinter exposes a small public API from the top-level `blinter` package:

```python
from blinter import (
    BlinterConfig,
    RuleSeverity,
    lint_batch_file,
    load_config,
)

# Basic usage
issues = lint_batch_file("script.bat")
for issue in issues:
    print(f"Line {issue.line_number}: {issue.rule.name} ({issue.rule.code})")

# With custom configuration
config = BlinterConfig(
    max_line_length=80,
    disabled_rules={"S007", "S011"},
    min_severity=RuleSeverity.WARNING,
)
issues = lint_batch_file("script.bat", config=config)

# Process results
for issue in issues:
    print(f"Line {issue.line_number}: {issue.rule.name}")
    print(f"  {issue.rule.explanation}")
    print(f"  Fix: {issue.rule.recommendation}")

# Thread-safe design allows safe concurrent usage
from concurrent.futures import ThreadPoolExecutor

files = ["script1.bat", "script2.cmd", "script3.bat"]
with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(lint_batch_file, files))
```

### 🔧 **Configuration Options (`BlinterConfig`)**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `recursive` | `bool` | `True` | Search subdirectories when linting a folder |
| `show_summary` | `bool` | `False` | Show summary statistics in CLI output |
| `max_line_length` | `int` | `100` | Maximum line length for S011 and S020 rules |
| `max_scan_files` | `int` | `1000` | Maximum batch files to scan in a directory |
| `follow_calls` | `bool` | `False` | Lint scripts referenced by `CALL` statements |
| `scan_root` | `str` \| `None` | `None` | Root path for `--follow-calls` containment (CLI sets automatically) |
| `enabled_rules` | `Set[str]` | empty | If non-empty, only these rule codes run |
| `disabled_rules` | `Set[str]` | empty | Rule codes to skip |
| `min_severity` | `RuleSeverity` \| `None` | `None` | Minimum severity to report (via `blinter.ini`; no dedicated CLI flag) |
| `fail_on` | `RuleSeverity` \| `None` | `RuleSeverity.SECURITY` | Lowest severity that makes the CLI exit 1. `None` (`fail_on = none`) reports findings without failing |

### Supported File Types
- `.bat` files (traditional batch files)
- `.cmd` files (recommended for modern Windows)
- **Unicode filenames** and international characters supported
- **Large files** handled efficiently, with a warning above 10MB and a hard reject above 50MB

### 📁 **Directory Processing**

Blinter can analyze entire directories of batch files with powerful options:

- **Recursive Analysis**: Automatically finds and processes all `.bat` and `.cmd` files in directories and subdirectories
- **Non-Recursive Mode**: Use `--no-recursive` to analyze only files in the specified directory
- **Batch Processing**: Handles multiple files efficiently with consolidated reporting
- **Error Resilience**: Continues processing other files even if some files have encoding or permission issues
- **Progress Tracking**: Shows detailed results for each file plus combined summary statistics

**Examples:**
```cmd
# Pip installation:
blinter ./my-batch-scripts                 # Analyze all files recursively
blinter . --no-recursive                   # Current directory only
blinter ./scripts --summary               # With summary statistics

# Standalone executable (installer or manual zip):
blinter ./my-batch-scripts            # Analyze all files recursively
blinter . --no-recursive              # Current directory only
blinter ./scripts --summary           # With summary statistics

# Manual zip only (extract first):
Blinter-v1.x.x\blinter.exe ./my-batch-scripts
```

## 🔥 **Integration Example**

### CI/CD Integration
```yaml
# Example GitHub Actions workflow
- name: Lint Batch Files
  run: |
    python -c "
    from blinter import lint_batch_file
    from blinter import RuleSeverity
    import sys
    issues = lint_batch_file('deploy.bat')
    fatal = [i for i in issues if i.rule.severity in (RuleSeverity.ERROR, RuleSeverity.SECURITY)]
    if fatal:
        print(f'Found {len(fatal)} critical issues (errors or security)!')
        sys.exit(1)
    print(f'Batch file passed with {len(issues)} total issues')
    "
```

### MegaLinter

Blinter can lint `.bat` and `.cmd` files as a [MegaLinter plugin](docs/MegaLinter.md). Add the descriptor URL to `PLUGINS` in `.mega-linter.yml`.

The `blinter` CLI exit codes:

| Code | Meaning |
|------|---------|
| **0** | Success: no findings at or above the failure threshold, and every discovered primary file was processed |
| **1** | Lint failure: any finding at or above the failure threshold, CLI/path errors, no processable files, any skipped primary target files, or all discovered files failed to read |
| **2** | Unexpected internal error |

The default threshold is Security, so Error and Security findings are fatal and Warning, Performance, and Style findings are not. `--fail-on` or `fail_on` in `blinter.ini` changes that threshold. `none` never fails because of findings.

**Special thanks go out to [BrainWaveCC](https://github.com/BrainWaveCC) for all the help bug hunting.**

## License 📄

This project is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later) — see [COPYING](https://github.com/BatchLang/Blinter/blob/main/COPYING) for details.

<div align="center">

Icon by [Acidmit](https://www.flaticon.com/authors/acidmit) · [Flaticon](https://www.flaticon.com/)

[![PyPI Downloads (total)](https://static.pepy.tech/personalized-badge/blinter?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/blinter)

</div>
