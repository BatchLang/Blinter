"""pytest configuration and shared fixtures for blinter tests."""

import _io
import builtins
import io
import os
from pathlib import Path
import tempfile
import tomllib
from typing import Any, Generator
from unittest.mock import MagicMock, patch
import warnings

import pytest

from tests.corpus_support import (
    CORPUS_SKIP_REASON,
    corpus_available,
    corpus_files,
)

try:
    import coverage.misc  # pylint: disable=import-outside-toplevel

    COVERAGE_AVAILABLE = True
except ImportError:
    COVERAGE_AVAILABLE = False

_BATCH_SUFFIXES = {".bat", ".cmd"}


def _is_batch_path(path: object) -> bool:
    if not isinstance(path, (str, os.PathLike)):
        return False
    return Path(path).suffix.lower() in _BATCH_SUFFIXES


def _prepare_batch_text(data: str) -> str:
    return data.replace("\r\n", "\n")


def _apply_crlf_newline(
    mode: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Force CRLF for text-mode batch file writes without duplicate open args."""
    if "b" in mode:
        return args, kwargs

    normalized_kwargs = dict(kwargs)
    normalized_kwargs.pop("newline", None)
    if len(args) >= 4:
        return (*args[:3], "\r\n", *args[4:]), normalized_kwargs
    if len(args) == 3:
        return (*args, "\r\n"), normalized_kwargs
    normalized_kwargs["newline"] = "\r\n"
    return args, normalized_kwargs


def _is_batch_suffix(suffix: object) -> bool:
    return isinstance(suffix, str) and suffix.lower() in _BATCH_SUFFIXES


def _ensure_crlf_newline_for_batch(
    kwargs: dict[str, Any],
    *,
    mode: str,
    suffix: object,
) -> None:
    """Set newline=CRLF for text-mode temp batch files (POSIX uses LF by default)."""
    if _is_batch_suffix(suffix) and "b" not in mode:
        kwargs["newline"] = "\r\n"


def _named_temporary_file_crlf(
    original: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    mode = kwargs.get("mode", "w+b")
    suffix = kwargs.get("suffix")
    _ensure_crlf_newline_for_batch(kwargs, mode=mode, suffix=suffix)
    return original(*args, **kwargs)


@pytest.fixture(autouse=True)
def _write_batch_files_with_crlf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure generated .bat/.cmd fixtures use CRLF like real Windows batch files."""
    original_write_text = Path.write_text
    original_open = builtins.open
    original_named_temporary_file = tempfile.NamedTemporaryFile

    def write_text(
        self: Path,
        data: str,
        *args: object,
        **kwargs: object,
    ) -> int:
        if isinstance(data, str) and self.suffix.lower() in _BATCH_SUFFIXES:
            data = _prepare_batch_text(data)
            kwargs = {**kwargs, "newline": "\r\n"}
        return original_write_text(self, data, *args, **kwargs)

    def open_crlf(  # pylint: disable=keyword-arg-before-vararg
        file: str | os.PathLike[str] | int,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if _is_batch_path(file) and any(flag in mode for flag in ("w", "a", "x")):
            args, kwargs = _apply_crlf_newline(mode, args, kwargs)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(builtins, "open", open_crlf)
    monkeypatch.setattr(io, "open", open_crlf)
    monkeypatch.setattr(_io, "open", open_crlf)
    monkeypatch.setattr(
        tempfile,
        "NamedTemporaryFile",
        lambda *args, **kwargs: _named_temporary_file_crlf(
            original_named_temporary_file,
            *args,
            **kwargs,
        ),
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip corpus-dependent tests when batch-script-examples is unavailable."""
    items.sort(
        key=lambda item: 0 if item.name == "test_synthetic_lint_within_baseline" else 1
    )
    if corpus_available():
        return
    skip_marker = pytest.mark.skip(reason=CORPUS_SKIP_REASON)
    for item in items:
        if item.get_closest_marker("needs_corpus") is not None:
            item.add_marker(skip_marker)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize per-corpus-file smoke tests only when the corpus exists."""
    if "corpus_file_path" not in metafunc.fixturenames:
        return
    files = corpus_files()
    if not files:
        metafunc.parametrize(
            "corpus_file_path",
            [pytest.param(None, marks=pytest.mark.needs_corpus)],
            ids=["corpus-unavailable"],
        )
        return
    metafunc.parametrize(
        "corpus_file_path",
        files,
        ids=[path.name for path in files],
    )


def make_mock_encoding_path(read_data: bytes = b"test content\n") -> MagicMock:
    """Return a Path-like mock whose read_bytes() returns the given payload."""
    mock_path = MagicMock(spec=Path)
    mock_path.read_bytes.return_value = read_data
    return mock_path


def patch_valid_encoding_path(read_data: bytes = b"test content\n") -> Any:
    """Bypass filesystem checks for mocked encoding read tests."""
    return patch(
        "blinter.io.encoding._validate_file_for_read",
        return_value=make_mock_encoding_path(read_data),
    )


def get_project_version() -> str:
    """Return the package version from pyproject.toml."""
    project_root = Path(__file__).resolve().parent.parent
    with (project_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject_data_object: object = tomllib.load(pyproject_file)
    if not isinstance(pyproject_data_object, dict):
        raise ValueError("pyproject.toml must contain a top-level table")
    project_object: object = pyproject_data_object.get("project")
    if not isinstance(project_object, dict):
        raise ValueError("pyproject.toml must contain a [project] table")
    version_object: object = project_object.get("version")
    if not isinstance(version_object, str) or not version_object:
        raise ValueError("pyproject.toml [project].version must be a non-empty string")
    return version_object


@pytest.fixture(autouse=True)
def suppress_test_warnings() -> Generator[None, None, None]:
    """Suppress expected warnings during tests.

    These warnings are expected when testing various scenarios and
    should not clutter the test output.
    """
    # Suppress encoding warnings
    warnings.filterwarnings(
        "ignore",
        message="File .* was read using .* encoding instead of UTF-8.*",
        category=UserWarning,
    )

    # Suppress coverage warnings about configuration
    if COVERAGE_AVAILABLE:
        warnings.filterwarnings("ignore", category=coverage.misc.CoverageWarning)

    yield
    # Reset warnings after test
    warnings.resetwarnings()
