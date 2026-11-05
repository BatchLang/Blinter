"""Conformance tests for committed spec/corpus fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from blinter import lint_batch_file
from scripts.spec.cmd_oracle import _CORPUS, _filter_runnable
from tests.spec_corpus_support import (
    SpecCorpusCase,
    assert_issues_match,
    discover_spec_corpus_cases,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "case",
    discover_spec_corpus_cases(),
    ids=lambda case: case.id,
)
def test_spec_corpus_case(case: object) -> None:
    """Each spec/corpus case must match its expect.json oracle."""
    assert isinstance(case, SpecCorpusCase)
    issues = lint_batch_file(str(case.input_path), config=case.config)
    assert_issues_match(issues, case.expect)


def test_documented_corpus_count_matches_fixtures() -> None:
    """Docs track the committed corpus size. funding.json must not.

    FLOSS/Fund crawls a submitted manifest. A case count in funding.json
    changes on every corpus update and makes that crawl fail.
    """
    count = len(discover_spec_corpus_cases())
    architecture = (_REPO_ROOT / "docs" / "Architecture.md").read_text(encoding="utf-8")
    spec_readme = (_REPO_ROOT / "spec" / "README.md").read_text(encoding="utf-8")
    funding = (_REPO_ROOT / "funding.json").read_text(encoding="utf-8")
    assert f"{count} committed fixtures" in architecture
    assert f"{count}-case conformance corpus" in spec_readme
    assert "-case conformance corpus" not in funding


def test_wmic_read_only_corpus_is_oracle_runnable() -> None:
    """Read-only WMIC queries still ship on Windows 10 and must be executable.

    Absence on Windows 11 is a fast cmd.exe error (oracle-acceptable). Skip
    only interactive or mutating WMIC, not ``wmic os get``.
    """
    skip_text = (
        _REPO_ROOT / "spec" / "corpus" / "meta" / "oracle-skip.yaml"
    ).read_text(encoding="utf-8")
    expect = (
        _REPO_ROOT
        / "spec"
        / "corpus"
        / "syntax"
        / "w024-deprecated-wmic"
        / "expect.json"
    ).read_text(encoding="utf-8")
    oracle_src = (_REPO_ROOT / "scripts" / "spec" / "cmd_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "syntax/w024-deprecated-wmic" not in skip_text
    assert '"oracle": "run"' in expect
    assert "interactive wmic prompt" in oracle_src
    assert "mutating wmic" in oracle_src
    assert "hangs or is absent on modern Windows" not in oracle_src


def test_cmd_oracle_case_filter_selects_one_fixture() -> None:
    """--case runs one corpus id, and --limit still applies after that filter."""
    case_path = _CORPUS / "syntax" / "e002-missing-label" / "input.cmd"
    other_path = _CORPUS / "syntax" / "s001-echo-off-first-valid" / "input.cmd"
    assert _filter_runnable(
        [case_path, other_path], limit=0, case="syntax/e002-missing-label"
    ) == [case_path]
    assert _filter_runnable([case_path], limit=0, case="syntax/does-not-exist") == []
    assert _filter_runnable([case_path, other_path], limit=1, case="") == [case_path]
