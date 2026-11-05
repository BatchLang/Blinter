"""Tests for package version resolution and the published source distribution."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import warnings
import zipfile

import pytest
from pytest_mock import MockerFixture

from blinter._version import _fallback_version, _pyproject_path, get_version
from blinter.rules.registry import RULE_COUNT
from tests.conftest import CHECKOUT_ONLY_TEST_MODULES, get_project_version

_REPO_ROOT = Path(__file__).resolve().parent.parent
_UV_EXECUTABLE = shutil.which("uv")
_SDIST_PATHS = (
    ".coveragerc",
    "pytest.ini",
    "src/blinter/__init__.py",
    "tests/conftest.py",
)
_WHEEL_EXCLUDED_PREFIXES = ("scripts/", "spec/", "tests/")
_SDIST_OMITTED_PREFIXES = (
    ".github/",
    "mega-linter-plugin-blinter/",
    "scripts/",
    "vendor/",
)


def _sdist_relative_name(member_name: str) -> str:
    """Return a source-tree path from an sdist member name."""
    normalized = member_name.replace("\\", "/")
    separator = normalized.find("/")
    if separator == -1:
        return normalized
    return normalized[separator + 1 :]


def _corpus_byte_sample() -> Path:
    """Return a corpus file, preferring one that carries CRLF bytes."""
    corpus = _REPO_ROOT / "spec" / "corpus"
    fallback: Path | None = None
    for path in sorted(corpus.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\r\n" in data:
            return path
        if fallback is None:
            fallback = path
    if fallback is None:
        raise AssertionError("spec/corpus has no files")
    return fallback


def _build_distributions(output_dir: Path) -> tuple[Path, Path]:
    """Build an sdist and a wheel into ``output_dir``."""
    assert _UV_EXECUTABLE is not None
    result = subprocess.run(
        [
            _UV_EXECUTABLE,
            "build",
            "--sdist",
            "--wheel",
            "--out-dir",
            str(output_dir),
        ],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    sdists = sorted(output_dir.glob("*.tar.gz"))
    wheels = sorted(output_dir.glob("*.whl"))
    assert len(sdists) == 1
    assert len(wheels) == 1
    return sdists[0], wheels[0]


def _assert_sdist_members(archive: Path) -> None:
    """The sdist carries the suite and corpus, and preserves corpus bytes."""
    sample = _corpus_byte_sample()
    sample_name = sample.relative_to(_REPO_ROOT).as_posix()
    with tarfile.open(archive, "r:gz") as tar:
        names = {
            _sdist_relative_name(member.name)
            for member in tar.getmembers()
            if member.isfile()
        }
        missing = [path for path in _SDIST_PATHS if path not in names]
        assert missing == []
        assert any(name.startswith("spec/corpus/") for name in names)
        leaked = [
            name
            for name in names
            if name.startswith(_SDIST_OMITTED_PREFIXES) or name == "tests/pytest.log"
        ]
        assert leaked == []
        archived = tar.extractfile(
            next(
                member
                for member in tar.getmembers()
                if _sdist_relative_name(member.name) == sample_name
            )
        )
        assert archived is not None
        assert archived.read() == sample.read_bytes()


def _assert_wheel_is_package_only(archive: Path) -> None:
    """Wheels install the package. Tests and dev scripts stay out."""
    with zipfile.ZipFile(archive) as wheel:
        names = wheel.namelist()
    assert any(name.startswith("blinter/") for name in names)
    leaked = [name for name in names if name.startswith(_WHEEL_EXCLUDED_PREFIXES)]
    assert leaked == []


def _extract_sdist(archive: Path, destination: Path) -> Path:
    """Unpack an sdist and return its top-level directory."""
    with tarfile.open(archive, "r:gz") as tar:
        # Python 3.12+ warns when extractall is called without a filter.
        # This archive was just built in the same test.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tar.extractall(destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    assert len(roots) == 1
    return roots[0]


def _assert_sdist_collects_library_tests(unpacked: Path) -> None:
    """Collection from the sdist reaches library tests and skips dev scripts."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--override-ini=addopts=",
            "--override-ini=log_file=",
        ],
        cwd=unpacked,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    collected = result.stdout
    assert "tests/test_lint_functionality.py::" in collected
    assert "tests/test_spec_corpus.py::" in collected
    for module_name in sorted(CHECKOUT_ONLY_TEST_MODULES):
        assert f"tests/{module_name}::" not in collected


class TestVersion:
    """Tests for get_version and fallback parsing."""

    @pytest.fixture(autouse=True)
    def _ignore_baked_version(self, mocker: MockerFixture) -> None:
        """Keep fallback tests on metadata and pyproject.toml."""
        mocker.patch("blinter._version._BAKED_VERSION", None)

    def test_get_version_uses_installed_metadata_without_pyproject(
        self, mocker: MockerFixture
    ) -> None:
        """Test installed metadata is used when pyproject.toml is not present."""
        mocker.patch("blinter._version._source_checkout_pyproject", return_value=None)
        try:
            installed = version("Blinter")
        except PackageNotFoundError:
            pytest.skip("Blinter is not installed")
        assert get_version() == installed

    def test_pyproject_path_points_at_repo_root(self) -> None:
        """Test pyproject path resolves beside the repository root."""
        assert _pyproject_path().name == "pyproject.toml"
        assert _pyproject_path().is_file()

    def test_fallback_reads_pyproject(self, mocker: MockerFixture) -> None:
        """Test fallback parses pyproject.toml when metadata is missing."""
        mocker.patch(
            "blinter._version.version",
            side_effect=PackageNotFoundError("Blinter"),
        )
        mocker.patch("blinter._version._source_checkout_pyproject", return_value=None)
        version_value = get_version()
        assert version_value == "unknown"

    def test_get_version_reads_pyproject_in_source_tree(self) -> None:
        """Test source checkouts resolve version from pyproject.toml."""

        assert get_version() == get_project_version()

    def test_fallback_unknown_when_pyproject_missing(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Test fallback returns unknown when pyproject.toml is absent."""
        missing = tmp_path / "missing.toml"
        mocker.patch("blinter._version._pyproject_path", return_value=missing)
        assert _fallback_version() == "unknown"

    def test_fallback_unknown_without_version_key(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Test fallback returns unknown when pyproject has no version field."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        mocker.patch("blinter._version._pyproject_path", return_value=pyproject)
        assert _fallback_version() == "unknown"

    def test_get_version_prefers_baked_build_version(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Generated build versions win without reading pyproject.toml."""
        mocker.patch("blinter._version._BAKED_VERSION", "9.9.9")
        mocker.patch(
            "blinter._version._pyproject_path",
            return_value=tmp_path / "missing.toml",
        )
        assert get_version() == "9.9.9"

    def test_empty_baked_version_uses_pyproject(self, mocker: MockerFixture) -> None:
        """An empty generated version falls through to pyproject.toml."""

        mocker.patch("blinter._version._BAKED_VERSION", "")
        assert get_version() == get_project_version()

    def test_stray_pyproject_prefers_installed_metadata(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """A pyproject.toml outside a src/ Blinter checkout does not win."""
        package_dir = tmp_path / "vendor" / "blinter"
        package_dir.mkdir(parents=True)
        module_file = package_dir / "_version.py"
        module_file.write_text("", encoding="utf-8")
        stray = tmp_path / "pyproject.toml"
        stray.write_text(
            '[project]\nname = "Other"\nversion = "9.9.9"\n',
            encoding="utf-8",
        )
        mocker.patch("blinter._version.__file__", str(module_file))
        mocker.patch("blinter._version.version", return_value="1.2.3")
        assert get_version() == "1.2.3"

    def test_src_checkout_with_other_name_prefers_metadata(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """A src/ layout whose project name is not Blinter uses metadata."""
        package_dir = tmp_path / "src" / "blinter"
        package_dir.mkdir(parents=True)
        module_file = package_dir / "_version.py"
        module_file.write_text("", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "Other"\nversion = "9.9.9"\n',
            encoding="utf-8",
        )
        mocker.patch("blinter._version.__file__", str(module_file))
        mocker.patch("blinter._version.version", return_value="1.2.3")
        assert get_version() == "1.2.3"

    def test_readme_rule_count_matches_registry(self) -> None:
        """README should reference the live RULE_COUNT from the registry."""
        readme = (_pyproject_path().parent / "README.md").read_text(encoding="utf-8")
        assert "RULE_COUNT" in readme
        assert re.search(
            rf"\*\*{RULE_COUNT}\*\* rules",
            readme,
        ), f"README must state **{RULE_COUNT}** rules explicitly"


class TestUvSupport:
    """Tests that uv remains a documented, resolvable install path."""

    def test_readme_documents_uv_tool_and_uvx(self) -> None:
        """README must document persistent and one-shot uv install commands."""
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "uv tool install Blinter" in readme
        assert "uvx blinter" in readme

    @pytest.mark.skipif(
        not (_REPO_ROOT / "CONTRIBUTING.md").is_file(),
        reason="CONTRIBUTING.md is part of the git checkout",
    )
    def test_contributing_documents_uv_sync(self) -> None:
        """CONTRIBUTING must document uv sync with the dev extra."""
        contributing = (_REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "uv sync --extra dev" in contributing

    def test_pyproject_declares_package_extras_and_sdist_inputs(self) -> None:
        """pyproject.toml publishes a test extra and the sdist file set."""
        with (_REPO_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject_data: object = tomllib.load(pyproject_file)
        assert isinstance(pyproject_data, dict)
        tool_object: object = pyproject_data.get("tool")
        assert isinstance(tool_object, dict)
        uv_object: object = tool_object.get("uv")
        assert isinstance(uv_object, dict)
        assert uv_object.get("package") is True
        backend_object: object = uv_object.get("build-backend")
        assert isinstance(backend_object, dict)
        source_include: object = backend_object.get("source-include")
        assert source_include == [
            ".coveragerc",
            "pytest.ini",
            "spec/corpus/**",
            "tests/**",
        ]
        project_object: object = pyproject_data.get("project")
        assert isinstance(project_object, dict)
        extras_object: object = project_object.get("optional-dependencies")
        assert isinstance(extras_object, dict)
        dev_extra: object = extras_object.get("dev")
        test_extra: object = extras_object.get("test")
        assert isinstance(dev_extra, list)
        assert isinstance(test_extra, list)
        assert "blinter[test]" in dev_extra
        assert "pytest" in test_extra

    @pytest.mark.skipif(_UV_EXECUTABLE is None, reason="uv is not installed")
    def test_uv_resolves_dev_extra(self) -> None:
        """uv must be able to compile pyproject.toml with the dev extra."""
        assert _UV_EXECUTABLE is not None
        result = subprocess.run(
            [
                _UV_EXECUTABLE,
                "pip",
                "compile",
                "pyproject.toml",
                "--extra",
                "dev",
                "--quiet",
            ],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        compiled = result.stdout.casefold()
        assert "charset-normalizer" in compiled or "charset_normalizer" in compiled
        assert "pytest" in compiled

    @pytest.mark.skipif(_UV_EXECUTABLE is None, reason="uv is not installed")
    def test_sdist_includes_tests_and_wheel_does_not(self, tmp_path: Path) -> None:
        """Packagers can collect the suite from the sdist. The wheel is the package."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()
        sdist, wheel = _build_distributions(output_dir)
        _assert_sdist_members(sdist)
        _assert_wheel_is_package_only(wheel)
        unpacked = _extract_sdist(sdist, tmp_path / "unpacked")
        _assert_sdist_collects_library_tests(unpacked)
