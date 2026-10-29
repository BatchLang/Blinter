"""Tests for package version resolution."""

from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from types import ModuleType

import pytest
from pytest_mock import MockerFixture

from blinter._version import _fallback_version, _pyproject_path, get_version
from blinter.rules.registry import RULE_COUNT
from scripts.build_exe import (
    COMPANY_NAME,
    FILE_DESCRIPTION,
    ICON_PATH,
    MAIN_FILE,
    NATIVE_EXTENSION_SUFFIXES,
    NOFOLLOW_IMPORT_TO,
    ONEFILE_TEMPDIR_SPEC,
    OUTPUT_DIR,
    OUTPUT_FILENAME,
    PACKAGE_DIR,
    PRODUCT_NAME,
    PYTHON_FLAGS,
    TYPED_MARKER,
    _is_windows,
    _log_bundled_native_extensions,
    _read_project_version,
    _validate_inputs,
    _write_build_version,
    assert_pure_python_charset_normalizer,
    build_nuitka_command,
    main,
    nuitka_environment,
    run_nuitka,
)
from scripts.ci_release import (
    append_github_output,
    decide_release,
    main as ci_release_main,
    publish_should_release,
    publish_version,
    read_previous_version,
    read_project_version,
    read_version_file,
    release_tag_exists,
)
from scripts.extract_release_notes import (
    extract_latest_section,
    main as extract_release_notes_main,
    write_github_release_notes,
)
from tests.conftest import get_project_version

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD_VERSION_PATH = _REPO_ROOT / "src" / "blinter" / "_build_version.py"
_UV_EXECUTABLE = shutil.which("uv")
_NETWORK_WMI_NOFOLLOW: tuple[str, ...] = (
    "ssl",
    "_ssl",
    "socket",
    "_socket",
    "wmi",
    "_wmi",
)


def _module_with_file(name: str, path: Path) -> ModuleType:
    """Return a module-like object whose __file__ points at path."""
    module = ModuleType(name)
    module.__file__ = str(path)
    return module


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


def _assert_build_version_present_for_nuitka(
    command: list[str], repo_root: Path
) -> int:
    """Nuitka must be able to compile the generated module."""
    del command

    project_version = get_project_version()
    generated = repo_root / PACKAGE_DIR / "_build_version.py"
    assert generated.read_text(encoding="utf-8") == f'VERSION = "{project_version}"\n'
    return 0


@pytest.fixture
def cleanup_build_version() -> Iterator[None]:
    """Remove the version module main() writes into the real source tree."""
    yield
    _BUILD_VERSION_PATH.unlink(missing_ok=True)


class TestBuildExe:
    """Tests for the Nuitka Windows executable build script."""

    def test_read_project_version_matches_pyproject(self) -> None:
        """Script should read the same version as test helpers."""

        repo_root = Path(__file__).resolve().parent.parent
        assert (
            _read_project_version(repo_root / "pyproject.toml") == get_project_version()
        )

    def test_write_build_version_emits_constant(self, tmp_path: Path) -> None:
        """The Nuitka build stamps a single VERSION assignment."""
        _write_build_version(tmp_path, "1.2.3")
        generated = tmp_path / "src" / "blinter" / "_build_version.py"
        assert generated.read_text(encoding="utf-8") == 'VERSION = "1.2.3"\n'

    def test_write_build_version_rejects_unsafe_characters(
        self, tmp_path: Path
    ) -> None:
        """Quotes, backslashes, and newlines must not become generated Python."""
        with pytest.raises(ValueError, match="quotes"):
            _write_build_version(tmp_path, '1.2.3"\n')
        assert not (tmp_path / "src" / "blinter" / "_build_version.py").exists()

    def test_validate_inputs_requires_pyproject(self, tmp_path: Path) -> None:
        """Build validation should fail loudly when pyproject.toml is missing."""
        with pytest.raises(FileNotFoundError, match="pyproject.toml"):
            _validate_inputs(tmp_path)

    def test_nuitka_environment_prepends_src(self, tmp_path: Path) -> None:
        """Nuitka must import the src/ layout package during compilation."""
        env = nuitka_environment(tmp_path)
        src_dir = str(tmp_path / "src")
        pythonpath = env["PYTHONPATH"]
        assert pythonpath == src_dir or pythonpath.startswith(src_dir + os.pathsep)

    def test_build_command_includes_windows_metadata(self) -> None:
        """Nuitka command must embed icon, version, and the blinter package."""

        project_version = get_project_version()
        command = build_nuitka_command(
            version=project_version,
            python_executable=sys.executable,
            windows=True,
            mingw=False,
        )
        joined = " ".join(command)
        assert command[:3] == [sys.executable, "-m", "nuitka"]
        assert "--mode=onefile" in command
        assert "--assume-yes-for-downloads" in command
        assert "--msvc=latest" in command
        assert "--mingw64" not in command
        assert f"--output-filename={OUTPUT_FILENAME}" in command
        assert f"--output-dir={OUTPUT_DIR.as_posix()}" in command
        assert "--include-package=blinter" not in command
        assert "--include-package-data=blinter" not in command
        assert "--include-module=charset_normalizer" in command
        assert (
            "--include-data-files=pyproject.toml=blinter/pyproject.toml" not in command
        )
        assert "--python-flag=-m" in command
        assert "--file-reference-choice=runtime" not in command
        assert "--include-windows-runtime-dlls=yes" in command
        assert f"--windows-icon-from-ico={ICON_PATH.as_posix()}" in command
        assert f"--company-name={COMPANY_NAME}" in command
        assert f"--product-name={PRODUCT_NAME}" in command
        assert f"--file-version={project_version}" in command
        assert f"--product-version={project_version}" in command
        assert f"--file-description={FILE_DESCRIPTION}" in command
        assert command[-1] == PACKAGE_DIR.as_posix()
        assert "blinter.exe" in joined

    def test_build_command_applies_size_and_speed_flags(self) -> None:
        """Onefile builds must stay compressed, cached, LTO-enabled, and UPX-free."""
        command = build_nuitka_command(
            version="1.2.3",
            python_executable=sys.executable,
            windows=True,
        )
        assert "--lto=yes" in command
        assert "--deployment" in command
        assert "--noinclude-default-mode=nofollow" in command
        assert f"--onefile-tempdir-spec={ONEFILE_TEMPDIR_SPEC}" in command
        assert "--onefile-cache-mode=cached" in command
        assert "--onefile-no-compression" not in command
        assert "--upx" not in command
        assert not any(part.startswith("--upx") for part in command)
        for python_flag in PYTHON_FLAGS:
            assert f"--python-flag={python_flag}" in command
        for module_name in NOFOLLOW_IMPORT_TO:
            assert f"--nofollow-import-to={module_name}" in command
        for module_name in _NETWORK_WMI_NOFOLLOW:
            assert module_name in NOFOLLOW_IMPORT_TO

    def test_ci_installs_charset_normalizer_without_binary_wheels(self) -> None:
        """Both compile jobs install charset-normalizer from source."""
        ci_text = (_REPO_ROOT / ".github" / "workflows" / "CI.yml").read_text(
            encoding="utf-8"
        )
        assert ci_text.count("--no-binary charset-normalizer") == 2
        assert ci_text.count('CHARSET_NORMALIZER_USE_MYPYC: "0"') == 2
        assert "install_nuitka_build.py" not in ci_text
        assert "run_venv.py" not in ci_text
        assert "test_exe_smoke.ps1" not in ci_text
        assert ci_text.count("scripts/test_exe_smoke.py") == 2
        assert "ubuntu-24.04" in ci_text
        assert "ubuntu-24.04-arm" in ci_text
        assert "ubuntu-22.04" not in ci_text
        assert "macos-15-intel" in ci_text
        assert "needs: [check-version, test-windows-exe]" in ci_text
        assert "needs: [check-version, test-unix-exe]" in ci_text
        assert "needs: [check-version, build-windows, build-unix]" in ci_text
        assert 'pattern: "*-build-*"' in ci_text
        windows_package = ci_text.split("  build-windows:", maxsplit=1)[1].split(
            "  build-unix:",
            maxsplit=1,
        )[0]
        unix_package = ci_text.split("  build-unix:", maxsplit=1)[1].split(
            "  build-wheels:",
            maxsplit=1,
        )[0]
        assert "build_exe.py" not in windows_package
        assert "build_exe.py" not in unix_package
        assert "python scripts/package_executable.py" in windows_package
        assert "python scripts/package_executable.py" in unix_package

    def test_preflight_rejects_native_charset_normalizer(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """A charset_normalizer .pyd speedup must abort the Nuitka build."""
        init_py = tmp_path / "__init__.py"
        init_py.write_text("# package\n", encoding="utf-8")
        md_pyd = tmp_path / "md.pyd"
        md_pyd.write_bytes(b"native")
        cd_py = tmp_path / "cd.py"
        cd_py.write_text("# cd\n", encoding="utf-8")
        imported = {
            "charset_normalizer": _module_with_file("charset_normalizer", init_py),
            "charset_normalizer.md": _module_with_file("charset_normalizer.md", md_pyd),
            "charset_normalizer.cd": _module_with_file("charset_normalizer.cd", cd_py),
        }

        def fake_import(name: str) -> ModuleType:
            module = imported.get(name)
            if module is None:
                raise ImportError(name)
            return module

        mocker.patch(
            "scripts.build_exe.importlib.import_module", side_effect=fake_import
        )
        with pytest.raises(RuntimeError, match="pure Python"):
            assert_pure_python_charset_normalizer()

    def test_preflight_accepts_pure_python_charset_normalizer(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Pure-Python charset_normalizer modules must pass the Nuitka preflight."""
        init_py = tmp_path / "__init__.py"
        init_py.write_text("# package\n", encoding="utf-8")
        md_py = tmp_path / "md.py"
        md_py.write_text("# md\n", encoding="utf-8")
        cd_py = tmp_path / "cd.py"
        cd_py.write_text("# cd\n", encoding="utf-8")
        imported = {
            "charset_normalizer": _module_with_file("charset_normalizer", init_py),
            "charset_normalizer.md": _module_with_file("charset_normalizer.md", md_py),
            "charset_normalizer.cd": _module_with_file("charset_normalizer.cd", cd_py),
        }

        def fake_import(name: str) -> ModuleType:
            module = imported.get(name)
            if module is None:
                raise ImportError(name)
            return module

        mocker.patch(
            "scripts.build_exe.importlib.import_module", side_effect=fake_import
        )
        assert_pure_python_charset_normalizer()

    def test_preflight_fails_when_charset_normalizer_missing(
        self, mocker: MockerFixture
    ) -> None:
        """The Nuitka build must fail loudly if charset_normalizer is not installed."""
        mocker.patch(
            "scripts.build_exe.importlib.import_module",
            side_effect=ImportError("missing"),
        )
        with pytest.raises(RuntimeError, match="must be installed"):
            assert_pure_python_charset_normalizer()

    def test_preflight_skips_optional_submodule_and_namespace_module(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Optional md/cd ImportError and missing __file__ must not abort the build."""
        init_py = tmp_path / "__init__.py"
        init_py.write_text("# package\n", encoding="utf-8")
        package = _module_with_file("charset_normalizer", init_py)
        namespace = ModuleType("charset_normalizer.md")

        def fake_import(name: str) -> ModuleType:
            if name == "charset_normalizer":
                return package
            if name == "charset_normalizer.md":
                return namespace
            raise ImportError(name)

        mocker.patch(
            "scripts.build_exe.importlib.import_module", side_effect=fake_import
        )
        assert_pure_python_charset_normalizer()

    def test_log_bundled_native_extensions_lists_pyds(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Post-build inventory must log leftover .pyd files under dist/."""
        dist_dir = tmp_path / OUTPUT_DIR
        nested = dist_dir / "blinter.dist"
        nested.mkdir(parents=True)
        (nested / "_ssl.pyd").write_bytes(b"pyd")
        (dist_dir / OUTPUT_FILENAME).write_bytes(b"exe")
        caplog.set_level("INFO")
        _log_bundled_native_extensions(tmp_path)
        assert "_ssl.pyd" in caplog.text

    def test_log_bundled_native_extensions_handles_missing_dist(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Inventory must warn when dist/ was not created."""
        caplog.set_level("WARNING")
        _log_bundled_native_extensions(tmp_path)
        assert "cannot inventory natives" in caplog.text

    def test_log_bundled_native_extensions_when_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Inventory must log when the dist tree has no leftover natives."""
        (tmp_path / OUTPUT_DIR).mkdir()
        caplog.set_level("INFO")
        _log_bundled_native_extensions(tmp_path)
        assert "No leftover native extension files" in caplog.text

    def test_build_command_uses_mingw_when_requested(self) -> None:
        """Local MinGW builds must opt into the experimental 3.13+ flag."""
        command = build_nuitka_command(
            version="1.2.3",
            python_executable=sys.executable,
            windows=True,
            mingw=True,
        )
        assert "--mingw64" in command
        assert "--experimental=force-mingw64" in command
        assert "--msvc=latest" not in command
        assert "--include-windows-runtime-dlls=yes" not in command

    def test_build_command_omits_windows_flags_off_windows(self) -> None:
        """Non-Windows invocations should not pass MSVC or PE resource flags."""
        command = build_nuitka_command(
            version="1.2.3",
            python_executable=sys.executable,
            windows=False,
        )
        assert "--msvc=latest" not in command
        assert "--mingw64" not in command
        assert "--include-windows-runtime-dlls=yes" not in command
        assert not any(part.startswith("--windows-icon-from-ico=") for part in command)
        assert not any(part.startswith("--file-description=") for part in command)
        assert "--macos-sign-identity" not in " ".join(command)
        assert "--output-filename=blinter" in command
        assert "--file-version=1.2.3" in command
        assert "--product-version=1.2.3" in command
        assert f"--company-name={COMPANY_NAME}" in command
        assert "--lto=yes" in command
        assert command[-1] == PACKAGE_DIR.as_posix()
        assert ".dylib" in NATIVE_EXTENSION_SUFFIXES
        assert ".so" in NATIVE_EXTENSION_SUFFIXES

    def test_application_icon_asset_exists(self) -> None:
        """The ICO referenced by the Nuitka build must be present."""
        repo_root = Path(__file__).resolve().parent.parent
        assert (repo_root / ICON_PATH).is_file(), "Application icon asset is missing"
        assert (repo_root / MAIN_FILE).is_file(), "package __main__ module is missing"
        assert (repo_root / TYPED_MARKER).is_file(), "py.typed marker is missing"
        _validate_inputs(repo_root)

    def test_read_project_version_rejects_missing_version(self, tmp_path: Path) -> None:
        """Invalid pyproject.toml must fail before Nuitka is launched."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'Blinter'\n", encoding="utf-8")
        with pytest.raises(ValueError, match="project.version"):
            _read_project_version(pyproject)

    def test_run_nuitka_returns_subprocess_exit_code(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """A Nuitka compiler failure should surface its exit code."""
        mocker.patch(
            "scripts.build_exe.subprocess.run",
            return_value=mocker.Mock(returncode=7),
        )
        assert run_nuitka([sys.executable, "-m", "nuitka"], tmp_path) == 7

    def test_run_nuitka_fails_when_output_missing(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Success from Nuitka without dist/blinter.exe is still a build failure."""
        mocker.patch(
            "scripts.build_exe.subprocess.run",
            return_value=mocker.Mock(returncode=0),
        )
        assert run_nuitka([sys.executable, "-m", "nuitka"], tmp_path) == 1

    def test_run_nuitka_succeeds_when_exe_exists(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """A completed onefile build must leave dist/blinter.exe in place."""
        dist_dir = tmp_path / OUTPUT_DIR
        dist_dir.mkdir()
        (dist_dir / OUTPUT_FILENAME).write_bytes(b"exe")
        mocker.patch(
            "scripts.build_exe.subprocess.run",
            return_value=mocker.Mock(returncode=0),
        )
        output_flag = f"--output-filename={OUTPUT_FILENAME}"
        assert run_nuitka([sys.executable, "-m", "nuitka", output_flag], tmp_path) == 0

    def test_main_returns_2_when_inputs_missing(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """CLI should exit 2 when required build inputs are absent."""
        mocker.patch("scripts.build_exe.ROOT", tmp_path)
        assert main([]) == 2

    def test_is_windows_matches_os_name(self) -> None:
        """Platform detection must follow os.name without mutating the process."""
        assert _is_windows() is (os.name == "nt")

    @pytest.mark.usefixtures("cleanup_build_version")
    def test_main_invokes_nuitka_with_mingw_flag(self, mocker: MockerFixture) -> None:
        """--mingw must reach the Nuitka command line."""
        repo_root = Path(__file__).resolve().parent.parent
        mocker.patch("scripts.build_exe.ROOT", repo_root)
        mocker.patch("scripts.build_exe._is_windows", return_value=True)
        mocker.patch(
            "scripts.build_exe.assert_pure_python_charset_normalizer",
            return_value=None,
        )
        run = mocker.patch(
            "scripts.build_exe.run_nuitka",
            side_effect=_assert_build_version_present_for_nuitka,
        )
        assert main(["--mingw"]) == 0
        assert not _BUILD_VERSION_PATH.is_file()
        command = run.call_args[0][0]
        assert "--mingw64" in command
        assert "--experimental=force-mingw64" in command
        assert run.call_args[0][1] == repo_root

    @pytest.mark.usefixtures("cleanup_build_version")
    def test_main_omits_windows_flags_when_not_windows(
        self, mocker: MockerFixture
    ) -> None:
        """POSIX hosts must not receive MSVC or MinGW flags even with --mingw."""
        repo_root = Path(__file__).resolve().parent.parent
        mocker.patch("scripts.build_exe.ROOT", repo_root)
        mocker.patch("scripts.build_exe._is_windows", return_value=False)
        mocker.patch(
            "scripts.build_exe.assert_pure_python_charset_normalizer",
            return_value=None,
        )
        run = mocker.patch(
            "scripts.build_exe.run_nuitka",
            side_effect=_assert_build_version_present_for_nuitka,
        )
        assert main(["--mingw"]) == 0
        assert not _BUILD_VERSION_PATH.is_file()
        command = run.call_args[0][0]
        assert "--mingw64" not in command
        assert "--msvc=latest" not in command
        assert not any(part.startswith("--windows-icon-from-ico=") for part in command)
        assert "--output-filename=blinter" in command
        assert any(part.startswith("--file-version=") for part in command)
        assert "--lto=yes" in command

    @pytest.mark.usefixtures("cleanup_build_version")
    def test_main_reports_launch_failures(self, mocker: MockerFixture) -> None:
        """OS errors starting Nuitka should return exit code 1."""

        def _fail_after_version_is_present(command: list[str], repo_root: Path) -> int:
            _assert_build_version_present_for_nuitka(command, repo_root)
            raise OSError("nuitka missing")

        repo_root = Path(__file__).resolve().parent.parent
        mocker.patch("scripts.build_exe.ROOT", repo_root)
        mocker.patch(
            "scripts.build_exe.assert_pure_python_charset_normalizer",
            return_value=None,
        )
        mocker.patch(
            "scripts.build_exe.run_nuitka",
            side_effect=_fail_after_version_is_present,
        )
        assert main([]) == 1
        assert not _BUILD_VERSION_PATH.is_file()

    def test_main_returns_2_when_charset_normalizer_is_native(
        self, mocker: MockerFixture
    ) -> None:
        """A native charset_normalizer wheel must fail before Nuitka starts."""
        repo_root = Path(__file__).resolve().parent.parent
        mocker.patch("scripts.build_exe.ROOT", repo_root)
        mocker.patch(
            "scripts.build_exe.assert_pure_python_charset_normalizer",
            side_effect=RuntimeError("native speedup"),
        )
        run = mocker.patch("scripts.build_exe.run_nuitka", return_value=0)
        assert main([]) == 2
        run.assert_not_called()


class TestUvSupport:
    """Tests that uv remains a documented, resolvable install path."""

    def test_readme_documents_uv_tool_and_uvx(self) -> None:
        """README must document persistent and one-shot uv install commands."""
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "uv tool install Blinter" in readme
        assert "uvx blinter" in readme

    def test_contributing_documents_uv_sync(self) -> None:
        """CONTRIBUTING must document uv sync with the dev extra."""
        contributing = (_REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "uv sync --extra dev" in contributing

    def test_pyproject_declares_uv_package_and_dev_extra(self) -> None:
        """pyproject.toml must keep the uv package flag and pip dev extra."""
        with (_REPO_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject_data: object = tomllib.load(pyproject_file)
        assert isinstance(pyproject_data, dict)
        tool_object: object = pyproject_data.get("tool")
        assert isinstance(tool_object, dict)
        uv_object: object = tool_object.get("uv")
        assert isinstance(uv_object, dict)
        assert uv_object.get("package") is True
        project_object: object = pyproject_data.get("project")
        assert isinstance(project_object, dict)
        extras_object: object = project_object.get("optional-dependencies")
        assert isinstance(extras_object, dict)
        dev_extra: object = extras_object.get("dev")
        assert isinstance(dev_extra, list)
        assert len(dev_extra) > 0

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


class TestExtractReleaseNotes:
    """Tests for changelog section extraction used by GitHub Releases."""

    def test_skips_unreleased_and_returns_latest_version(self, tmp_path: Path) -> None:
        """Unreleased notes must not replace the latest versioned section."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "- In-progress work\n\n"
            "## [1.2.3] - 2026-01-01\n\n"
            "### Fixed\n\n"
            "- Released fix\n\n"
            "## [1.2.2] - 2025-12-01\n\n"
            "### Added\n\n"
            "- Older change\n",
            encoding="utf-8",
        )
        section = extract_latest_section(changelog)
        assert "[1.2.3]" in section
        assert "Released fix" in section
        assert "Unreleased" not in section
        assert "In-progress work" not in section

    def test_extracts_first_section_when_no_unreleased(self, tmp_path: Path) -> None:
        """The newest versioned heading is used when Unreleased is absent."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## [9.9.9] - 2026-09-01\n\nOnly this.\n",
            encoding="utf-8",
        )
        assert "9.9.9" in extract_latest_section(changelog)

    def test_repo_changelog_latest_versioned_section_is_non_empty(self) -> None:
        """The repository changelog must yield a versioned release section."""
        section = extract_latest_section(_REPO_ROOT / "CHANGELOG.md")
        assert section.startswith("## [")
        assert not section.lower().startswith("## [unreleased]")
        assert len(section) > 20

    def test_github_output_writes_notes_file_and_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """--github-output stores the notes path and the same section text."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## [1.2.3] - 2026-01-01\n\n### Fixed\n\n- Released fix\n",
            encoding="utf-8",
        )
        notes_dir = tmp_path / "runner"
        notes_dir.mkdir()
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        notes_path = write_github_release_notes(changelog, notes_dir)
        assert notes_path == notes_dir / "release-notes.md"
        assert notes_path.read_text(encoding="utf-8") == extract_latest_section(
            changelog
        )
        assert output_file.read_text(encoding="utf-8") == f"path={notes_path}\n"

    def test_github_output_cli_uses_runner_temp(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The CLI flag reads RUNNER_TEMP and the default changelog."""
        notes_dir = tmp_path / "runner"
        notes_dir.mkdir()
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("RUNNER_TEMP", str(notes_dir))
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        extract_release_notes_main(["--github-output"])
        notes_path = notes_dir / "release-notes.md"
        assert notes_path.read_text(encoding="utf-8") == extract_latest_section()
        assert output_file.read_text(encoding="utf-8") == f"path={notes_path}\n"
        assert output_file.read_text(encoding="utf-8").count("\n") == 1

    def test_github_output_requires_runner_temp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing RUNNER_TEMP is an error when the notes directory is not passed."""
        monkeypatch.delenv("RUNNER_TEMP", raising=False)
        with pytest.raises(SystemExit, match="RUNNER_TEMP is not set"):
            write_github_release_notes(_REPO_ROOT / "CHANGELOG.md")


class TestCiRelease:
    """Tests for the CI version and release-decision script."""

    def test_reads_version_from_pyproject_text(self) -> None:
        """A quoted project.version is returned without quotes."""
        text = '[project]\nname = "Blinter"\nversion = "1.2.3"\n'
        assert read_project_version(text) == "1.2.3"

    def test_missing_version_exits(self) -> None:
        """pyproject.toml without project.version fails the release step."""
        with pytest.raises(SystemExit, match="Missing project.version"):
            read_project_version('[project]\nname = "Blinter"\n')

    def test_invalid_toml_exits(self) -> None:
        """Unparseable pyproject.toml fails with the parse error."""
        with pytest.raises(SystemExit, match="Could not parse pyproject.toml"):
            read_project_version("version = ")

    def test_missing_file_exits(self, tmp_path: Path) -> None:
        """A missing pyproject.toml path fails before git or Actions output."""
        missing = tmp_path / "pyproject.toml"
        with pytest.raises(SystemExit, match="pyproject.toml not found"):
            read_version_file(missing)

    def test_windows_ci_runs_installer_and_uninstaller(self) -> None:
        """Windows CI must execute the install and uninstall batch scripts."""
        ci_text = (_REPO_ROOT / ".github" / "workflows" / "CI.yml").read_text(
            encoding="utf-8"
        )
        windows_job = ci_text.split("quality-windows:", maxsplit=1)[1].split(
            "test-python:", maxsplit=1
        )[0]
        assert "test_install_scripts.ps1" in windows_job

    def test_workflow_dispatch_releases_even_when_version_is_unchanged(self) -> None:
        """Manual runs publish the current version without a bump."""
        assert decide_release("workflow_dispatch", "1.2.3", "1.2.3") is True

    def test_unchanged_version_skips_release(self) -> None:
        """A push with the same version does not publish."""
        assert decide_release("push", "1.2.3", "1.2.3") is False

    def test_version_bump_releases(self) -> None:
        """A push with a new version publishes."""
        assert decide_release("push", "1.2.4", "1.2.3") is True

    def test_same_version_releases_when_its_tag_is_missing(self) -> None:
        """A failed release is published again when the version tag does not exist."""
        assert decide_release("push", "1.2.3", "1.2.3", tag_exists=False) is True

    def test_version_command_writes_single_output_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The version subcommand appends one version= line."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nversion = "9.8.7"\n',
            encoding="utf-8",
        )
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        parsed_version = publish_version(pyproject)
        assert parsed_version == "9.8.7"
        assert output_file.read_text(encoding="utf-8") == "version=9.8.7\n"
        assert capsys.readouterr().out.strip() == "Project version: 9.8.7"

    def test_should_release_skips_when_git_version_matches(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unchanged parent version writes should_release=false."""
        current = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        mocker.patch(
            "scripts.ci_release.subprocess.check_output",
            return_value=current,
        )
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        assert publish_should_release() is False
        assert output_file.read_text(encoding="utf-8") == "should_release=false\n"
        assert "skipping release" in capsys.readouterr().out

    def test_should_release_when_the_version_tag_is_missing(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unpublished tag writes should_release=true without a version bump."""
        current = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        def fake_check_output(args: list[str], **_kwargs: object) -> str:
            if args[1] == "show":
                return current
            if args[1] == "ls-remote":
                return ""
            raise AssertionError(args)

        mocker.patch(
            "scripts.ci_release.subprocess.check_output",
            side_effect=fake_check_output,
        )
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        assert publish_should_release() is True
        assert output_file.read_text(encoding="utf-8") == "should_release=true\n"
        assert "no release tag" in capsys.readouterr().out

    def test_missing_tag_lookup_exits(self, mocker: MockerFixture) -> None:
        """A failed tag query stops the release decision."""
        mocker.patch(
            "scripts.ci_release.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(128, ["git", "ls-remote"]),
        )
        with pytest.raises(SystemExit, match="refs/tags/v1.2.3"):
            release_tag_exists("1.2.3")

    def test_should_release_when_git_version_changes(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A parent version bump writes should_release=true."""
        mocker.patch(
            "scripts.ci_release.subprocess.check_output",
            return_value='[project]\nversion = "0.0.1"\n',
        )
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        assert publish_should_release() is True
        assert output_file.read_text(encoding="utf-8") == "should_release=true\n"
        assert "Version bumped:" in capsys.readouterr().out

    def test_workflow_dispatch_does_not_read_git(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Manual dispatch releases without calling git show."""
        git_show = mocker.patch(
            "scripts.ci_release.subprocess.check_output",
            side_effect=AssertionError("git show should not run"),
        )
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
        assert publish_should_release() is True
        git_show.assert_not_called()
        assert output_file.read_text(encoding="utf-8") == "should_release=true\n"
        assert "workflow_dispatch" in capsys.readouterr().out

    def test_previous_version_git_failure(self, mocker: MockerFixture) -> None:
        """A missing parent commit fails the release decision."""
        mocker.patch(
            "scripts.ci_release.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(128, ["git", "show"]),
        )
        with pytest.raises(
            SystemExit,
            match="Could not read previous version from pyproject.toml",
        ):
            read_previous_version()

    def test_append_rejects_multiline_values(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """GITHUB_OUTPUT values stay on one line."""
        monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github_output.txt"))
        with pytest.raises(SystemExit, match="must be a single line"):
            append_github_output("version", "1.0.0\n2.0.0")

    def test_append_requires_github_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local runs without the Actions env var fail loudly."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        with pytest.raises(SystemExit, match="GITHUB_OUTPUT is not set"):
            append_github_output("version", "1.0.0")

    def test_cli_version_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The version CLI writes the repository version as one output line."""
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        ci_release_main(["version"])
        expected = read_project_version(
            (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert output_file.read_text(encoding="utf-8") == f"version={expected}\n"
        assert output_file.read_text(encoding="utf-8").count("\n") == 1

    def test_cli_unknown_command_exits(self) -> None:
        """An unknown subcommand is a usage error."""
        with pytest.raises(SystemExit, match="Unknown command"):
            ci_release_main(["nope"])
