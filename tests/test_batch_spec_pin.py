"""Verify batch-spec submodule pin and generator drift."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BATCH_SPEC_DIR = _REPO_ROOT / "vendor" / "batch-spec"
_LOCK_PATH = _REPO_ROOT / "spec" / "batch-spec.lock"
_GENERATORS = (
    "scripts/spec/generate_rules.py",
    "scripts/spec/generate_expansion.py",
    "scripts/spec/generate_commands.py",
)


def _git_fetch_tags(repo_dir: Path) -> None:
    fetch = subprocess.run(
        ["git", "-C", str(repo_dir), "fetch", "--tags", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        pytest.fail(
            "Could not fetch batch-spec tags: "
            + (fetch.stderr.strip() or fetch.stdout.strip())
        )


def _git_rev_parse(repo_dir: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", ref],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Could not resolve batch-spec ref {ref!r}: "
            + (result.stderr.strip() or result.stdout.strip())
        )
    return result.stdout.strip()


def _expected_lock_commit(lock: dict[str, object]) -> str:
    commit = lock.get("commit")
    if isinstance(commit, str) and commit:
        return commit
    ref = lock.get("ref")
    if not isinstance(ref, str) or not ref:
        pytest.fail("batch-spec.lock must include commit or ref")
    _git_fetch_tags(_BATCH_SPEC_DIR)
    return _git_rev_parse(_BATCH_SPEC_DIR, ref)


@pytest.mark.parametrize("generator", _GENERATORS)
def test_generators_check(generator: str) -> None:
    result = subprocess.run(
        [sys.executable, str(_REPO_ROOT / generator), "--check"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"{generator} --check failed:\n{result.stdout}\n{result.stderr}"


def test_batch_spec_submodule_present() -> None:
    assert (
        _BATCH_SPEC_DIR.is_dir()
    ), "vendor/batch-spec is missing. Run: git submodule update --init --recursive"
    assert (_BATCH_SPEC_DIR / "grammar" / "BatchLexer.g4").is_file()
    assert (_BATCH_SPEC_DIR / "data" / "expansion.yaml").is_file()
    assert (_BATCH_SPEC_DIR / "data" / "commands.yaml").is_file()
    assert (_BATCH_SPEC_DIR / "VERSION").is_file()


def test_batch_spec_lock_matches_checkout() -> None:
    assert _LOCK_PATH.is_file(), "spec/batch-spec.lock is missing"
    lock = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["path"] == "vendor/batch-spec"

    checkout = _git_rev_parse(_BATCH_SPEC_DIR, "HEAD")
    expected = _expected_lock_commit(lock)
    assert checkout == expected, (
        f"Checked-out batch-spec ({checkout}) does not match lock "
        f"({lock.get('ref', expected)})"
    )


def test_spec_readme_lock_ref_matches_lockfile() -> None:
    """spec/README.md must cite the pinned batch-spec lock ref."""
    lock = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    ref = lock.get("ref")
    assert isinstance(ref, str) and ref, "batch-spec.lock must include a nonempty ref"
    readme = (_REPO_ROOT / "spec" / "README.md").read_text(encoding="utf-8")
    assert f"`{ref}`" in readme
