"""Contract checks for the MegaLinter plugin descriptor."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib
from typing import Mapping

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DESCRIPTOR_PATH = (
    _REPO_ROOT / "mega-linter-plugin-blinter" / "blinter.megalinter-descriptor.yml"
)

_FATAL_SAMPLES = (
    "Found 1 critical issue (errors or security) that must be fixed.",
    "Found 2 critical issues (errors or security) across 1 file that must be fixed.",
)
_NONFATAL_SAMPLES = (
    "but 1 issue detected.",
    "but 3 issues detected.",
    "but 1 total issue detected across 1 file.",
    "but 4 total issues detected across 2 files.",
)


def _load_descriptor() -> Mapping[str, object]:
    """Return the plugin descriptor mapping."""
    loaded = yaml.safe_load(_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError("descriptor root must be a mapping")
    return loaded


def _project_version() -> str:
    """Return the version declared in pyproject.toml."""
    with (_REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    version = project["project"]["version"]
    if not isinstance(version, str):
        raise AssertionError("project version must be a string")
    return version


def _linter(descriptor: Mapping[str, object]) -> Mapping[str, object]:
    """Return the single linter entry."""
    linters = descriptor["linters"]
    if not isinstance(linters, list) or len(linters) != 1:
        raise AssertionError("descriptor must declare one linter")
    linter = linters[0]
    if not isinstance(linter, dict):
        raise AssertionError("linter entry must be a mapping")
    return linter


def test_descriptor_path_matches_plugin_url_rules() -> None:
    """MegaLinter rejects descriptors outside its plugin path and name rules."""
    assert "mega-linter-plugin-" in _DESCRIPTOR_PATH.as_posix()
    assert _DESCRIPTOR_PATH.name.endswith(".megalinter-descriptor.yml")


def test_descriptor_matches_megalinter_plugin_contract() -> None:
    """The descriptor uses the fields MegaLinter's plugin loader actually runs."""
    descriptor = _load_descriptor()
    assert descriptor["descriptor_id"] == "BATCH"
    assert descriptor["descriptor_type"] == "language"
    assert descriptor["file_extensions"] == [".bat", ".cmd"]

    linter = _linter(descriptor)
    assert linter["linter_name"] == "blinter"
    assert linter["name"] == "BATCH_BLINTER"
    assert linter["cli_lint_mode"] == "file"
    assert linter["supported_cli_lint_modes"] == ["file", "project"]
    assert linter["cli_lint_mode_project_extra_args_after"] == ["."]
    assert linter["can_output_sarif"] is True
    assert linter["cli_sarif_args"] == [
        "--format",
        "sarif",
        "--output",
        "{{SARIF_OUTPUT_FILE}}",
    ]

    install = linter["install"]
    if not isinstance(install, dict):
        raise AssertionError("install must be a mapping")
    dockerfile = install["dockerfile"]
    if not isinstance(dockerfile, list) or not dockerfile:
        raise AssertionError("install.dockerfile must be a non-empty list")
    assert all(isinstance(line, str) and line.startswith("RUN ") for line in dockerfile)
    assert f"Blinter=={_project_version()}" in dockerfile[0]


def test_count_regexes_match_cli_exit_lines() -> None:
    """Error and warning regexes match the CLI exit lines MegaLinter will parse."""
    linter = _linter(_load_descriptor())
    error_regex = re.compile(str(linter["cli_lint_errors_regex"]))
    warning_regex = re.compile(str(linter["cli_lint_warnings_regex"]))
    for sample in _FATAL_SAMPLES:
        match = error_regex.search(sample)
        assert match is not None
        assert match.group(1).isdigit()
    for sample in _NONFATAL_SAMPLES:
        match = warning_regex.search(sample)
        assert match is not None
        assert match.group(1).isdigit()
    assert error_regex.search("No issues found! Your batch file looks great!") is None
    assert warning_regex.search("Found 2 critical issues") is None
