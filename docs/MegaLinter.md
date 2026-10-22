# MegaLinter plugin

Blinter runs inside [MegaLinter](https://megalinter.io/) as an external plugin. MegaLinter does not ship it in the image. Each run downloads the descriptor and installs the pinned PyPI release.

The descriptor lives at `mega-linter-plugin-blinter/blinter.megalinter-descriptor.yml`. MegaLinter only loads a plugin whose URL contains `/mega-linter-plugin-*/` and whose file name ends in `.megalinter-descriptor.yml`.

## Enable it

Add this to `.mega-linter.yml`:

```yaml
PLUGINS:
  - https://raw.githubusercontent.com/BatchLang/Blinter/main/mega-linter-plugin-blinter/blinter.megalinter-descriptor.yml
```

That URL is the one to give MegaLinter. The plugin id is `BATCH`, and the linter key is `BATCH_BLINTER`. It matches `.bat` and `.cmd`.

On startup MegaLinter runs the descriptor install line:

```dockerfile
RUN pip install --no-cache-dir "Blinter==1.1.46"
```

Plugins can only install with `dockerfile` instructions that start with `RUN`. Bump that pin in the descriptor when a new Blinter release is published.

## What the run does

MegaLinter calls `blinter` once per file (`cli_lint_mode: file`) and passes `--summary`. One file at a time matches Blinter's CLI, which accepts a single path, and it keeps MegaLinter's include and exclude filters.

When `blinter.ini` is in the repository root, MegaLinter passes it with `--config`. Otherwise Blinter uses its defaults.

Exit code 1 (any Error or Security finding) fails the MegaLinter run. Warning, Style, and Performance findings do not. Inline suppression is unchanged: `REM LINT:IGNORE` comments in the batch file.

## SARIF

Blinter writes SARIF 2.1.0 when MegaLinter's SARIF reporter is on. Error and Security map to `error`, Warning maps to `warning`, and Style and Performance map to `note`.

```yaml
SARIF_REPORTER: true
```

## One scan for the whole repository

Set project mode when you want a single recursive `blinter .` instead of one process per file:

```yaml
BATCH_BLINTER_CLI_LINT_MODE: project
```

Project mode does not apply MegaLinter file filters. Blinter still only reads `.bat` and `.cmd` files. Skip paths with `blinter.ini`, or stay on the default file mode when MegaLinter should choose the file list.

## Extra arguments

`BATCH_BLINTER_ARGUMENTS` is appended to the Blinter command. Use it for flags such as `--follow-calls` or `--max-line-length`.
