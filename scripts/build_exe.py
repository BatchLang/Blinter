#!/usr/bin/env python3
"""Build the Windows standalone blinter.exe with Nuitka."""

from __future__ import annotations

import argparse
import importlib
import logging
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
ENTRY_MODULE = "blinter"
MAIN_FILE = Path("src") / "blinter" / "__main__.py"
PACKAGE_DIR = Path("src") / "blinter"
ICON_PATH = Path("resources") / "blinter_icon.ico"
TYPED_MARKER = Path("src") / "blinter" / "py.typed"
OUTPUT_DIR = Path("dist")
OUTPUT_FILENAME = "blinter.exe"
COMPANY_NAME = "BatchLang"
PRODUCT_NAME = "Blinter"
FILE_DESCRIPTION = "Blinter - Batch File Linter for Windows"
# Cached extract path: faster relaunch, stable path for Windows Firewall/AV.
ONEFILE_TEMPDIR_SPEC = "{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}"
PYTHON_FLAGS: tuple[str, ...] = ("-m", "no_docstrings", "no_asserts", "safe_path")
NOFOLLOW_IMPORT_TO: tuple[str, ...] = (
    "tkinter",
    "_tkinter",
    "turtle",
    "idlelib",
    "curses",
    "_curses",
    "lib2to3",
    "ensurepip",
    "venv",
    "distutils",
    "unittest",
    "doctest",
    "pydoc",
    "xmlrpc",
    "http.server",
    "sqlite3",
    "_sqlite3",
    "asyncio",
    "multiprocessing",
    "test",
    "ssl",
    "_ssl",
    "socket",
    "_socket",
    "wmi",
    "_wmi",
)
NATIVE_EXTENSION_SUFFIXES: frozenset[str] = frozenset({".pyd", ".so", ".dll"})
CHARSET_NORMALIZER_MODULE_NAMES: tuple[str, ...] = (
    "charset_normalizer",
    "charset_normalizer.md",
    "charset_normalizer.cd",
)
_UNSAFE_VERSION_CHARS: frozenset[str] = frozenset({'"', "'", "\\", "\n", "\r"})

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Send build progress to stderr without duplicating handlers."""
    if logging.getLogger().handlers:
        logger.setLevel(logging.INFO)
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _read_project_version(pyproject_path: Path) -> str:
    """Return [project].version from pyproject.toml."""
    logger.info("Reading project version from %s", pyproject_path)
    with pyproject_path.open("rb") as pyproject_file:
        data_object: object = tomllib.load(pyproject_file)
    if not isinstance(data_object, dict):
        raise ValueError("Missing [project] table in pyproject.toml")
    project_object: object = data_object.get("project")
    if not isinstance(project_object, dict):
        raise ValueError("Missing [project] table in pyproject.toml")
    version_object: object = project_object.get("version")
    if not isinstance(version_object, str) or not version_object:
        raise ValueError("Missing project.version in pyproject.toml")
    logger.info("Resolved project version %s", version_object)
    return version_object


def _build_version_path(repo_root: Path) -> Path:
    """Return the generated module path inside the package tree."""
    return repo_root / PACKAGE_DIR / "_build_version.py"


def _write_build_version(repo_root: Path, version: str) -> None:
    """Write the version constant Nuitka compiles into the executable."""
    if not version or any(char in version for char in _UNSAFE_VERSION_CHARS):
        raise ValueError(
            "Refusing to write a build version that contains quotes, "
            f"backslashes, or newlines: {version!r}"
        )
    destination = _build_version_path(repo_root)
    logger.info("Writing build version %s to %s", version, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f'VERSION = "{version}"\n', encoding="utf-8")


def _remove_build_version(repo_root: Path) -> None:
    """Delete the generated module so a later wheel cannot ship it."""
    destination = _build_version_path(repo_root)
    logger.info("Removing generated build version module %s", destination)
    destination.unlink(missing_ok=True)


def _require_file(path: Path, description: str) -> None:
    """Raise FileNotFoundError when a required build input is missing."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing {description}: {path}")
    logger.debug("Found %s at %s", description, path)


def _module_file_path(module: ModuleType) -> Path | None:
    """Return a module's __file__ path, or None when the module is namespace-only."""
    file_object: object = getattr(module, "__file__", None)
    if not isinstance(file_object, str) or not file_object:
        logger.warning(
            "Module %s has no __file__; skipping native-extension check",
            getattr(module, "__name__", type(module).__name__),
        )
        return None
    return Path(file_object)


def assert_pure_python_charset_normalizer() -> None:
    """Raise RuntimeError when charset_normalizer ships a native speedup module."""
    logger.info("Checking charset_normalizer is pure Python (no speedup extension)")
    modules: list[ModuleType] = []
    for module_name in CHARSET_NORMALIZER_MODULE_NAMES:
        try:
            modules.append(importlib.import_module(module_name))
        except ImportError as exc:
            if module_name == "charset_normalizer":
                raise RuntimeError(
                    "charset_normalizer must be installed before compiling blinter.exe"
                ) from exc
            logger.info(
                "Optional charset_normalizer submodule %s is not installed",
                module_name,
            )

    for module in modules:
        path = _module_file_path(module)
        if path is None:
            continue
        suffix = path.suffix.casefold()
        logger.info("charset_normalizer module %s -> %s", module.__name__, path)
        if suffix in NATIVE_EXTENSION_SUFFIXES:
            raise RuntimeError(
                "charset_normalizer must be installed as pure Python "
                f"(got native extension {path}). Reinstall with: "
                "uv pip install --no-binary charset-normalizer charset-normalizer"
            )
    logger.info("charset_normalizer is pure Python")


def _log_bundled_native_extensions(repo_root: Path) -> None:
    """Log leftover .pyd/.dll files under dist/ after a Nuitka onefile build."""
    dist_dir = repo_root / OUTPUT_DIR
    if not dist_dir.is_dir():
        logger.warning(
            "Nuitka output directory %s is missing; cannot inventory natives", dist_dir
        )
        return
    native_files = sorted(
        path
        for path in dist_dir.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in NATIVE_EXTENSION_SUFFIXES
        and path.name.casefold() != OUTPUT_FILENAME.casefold()
    )
    if not native_files:
        logger.info("No leftover .pyd/.dll files under %s", dist_dir)
        return
    logger.info("Nuitka dist tree contains %s native files:", len(native_files))
    for native_path in native_files:
        logger.info("  %s", native_path.relative_to(dist_dir).as_posix())


def _validate_inputs(repo_root: Path) -> Path:
    """Ensure Nuitka inputs exist and return the pyproject.toml path."""
    pyproject_path = repo_root / "pyproject.toml"
    _require_file(pyproject_path, "pyproject.toml")
    _require_file(repo_root / MAIN_FILE, "package __main__ module")
    _require_file(repo_root / ICON_PATH, "application icon")
    _require_file(repo_root / TYPED_MARKER, "py.typed marker")
    return pyproject_path


def _is_windows() -> bool:
    """Return True when this process is running on native Windows."""
    windows = os.name == "nt"
    logger.debug("Detected os.name=%s (windows=%s)", os.name, windows)
    return windows


def nuitka_environment(repo_root: Path) -> dict[str, str]:
    """Return env vars so Nuitka can import the src/ layout package."""
    env = os.environ.copy()
    src_dir = str(repo_root / "src")
    pythonpath = env.get("PYTHONPATH", "")
    if pythonpath:
        env["PYTHONPATH"] = src_dir + os.pathsep + pythonpath
    else:
        env["PYTHONPATH"] = src_dir
    logger.info("Nuitka PYTHONPATH=%s", env["PYTHONPATH"])
    return env


def _optimization_flags() -> list[str]:
    """Return size/speed flags that stay AV-safe and do not change CLI behavior."""
    flags: list[str] = [
        "--lto=yes",
        "--deployment",
        "--noinclude-default-mode=nofollow",
        f"--onefile-tempdir-spec={ONEFILE_TEMPDIR_SPEC}",
        "--onefile-cache-mode=cached",
        "--file-reference-choice=runtime",
    ]
    for python_flag in PYTHON_FLAGS:
        flags.append(f"--python-flag={python_flag}")
    for module_name in NOFOLLOW_IMPORT_TO:
        flags.append(f"--nofollow-import-to={module_name}")
    logger.info(
        "Nuitka optimizations: LTO, deployment, cached onefile extract, "
        "no docstrings/asserts, nofollow unused stdlib; UPX is not used"
    )
    return flags


def build_nuitka_command(
    *,
    version: str,
    python_executable: str,
    windows: bool,
    mingw: bool = False,
) -> list[str]:
    """Return the Nuitka CLI used to produce dist/blinter.exe."""
    command: list[str] = [
        python_executable,
        "-m",
        "nuitka",
        "--mode=onefile",
        "--assume-yes-for-downloads",
        f"--output-filename={OUTPUT_FILENAME}",
        f"--output-dir={OUTPUT_DIR.as_posix()}",
        f"--include-package={ENTRY_MODULE}",
        "--include-module=charset_normalizer",
        f"--company-name={COMPANY_NAME}",
        f"--product-name={PRODUCT_NAME}",
    ]
    command.extend(_optimization_flags())
    if windows:
        if mingw:
            logger.info("Selecting MinGW64 toolchain (experimental on Python 3.13+)")
            command.extend(["--mingw64", "--experimental=force-mingw64"])
        else:
            logger.info(
                "Selecting MSVC toolchain (--msvc=latest); "
                "Python 3.14 requires MSVC 14.3 / Visual Studio 2022 or newer"
            )
            command.append("--msvc=latest")
        command.extend(
            [
                f"--windows-icon-from-ico={ICON_PATH.as_posix()}",
                f"--file-version={version}",
                f"--product-version={version}",
                f"--file-description={FILE_DESCRIPTION}",
            ]
        )
    command.append(PACKAGE_DIR.as_posix())
    logger.info("Constructed Nuitka command with %s arguments", len(command))
    return command


def run_nuitka(command: list[str], repo_root: Path) -> int:
    """Invoke Nuitka and return its process exit code."""
    output_exe = repo_root / OUTPUT_DIR / OUTPUT_FILENAME
    logger.info("Working directory: %s", repo_root)
    logger.info("Expected output: %s", output_exe)
    logger.info("Running: %s", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        check=False,
        env=nuitka_environment(repo_root),
    )
    if completed.returncode != 0:
        logger.error("Nuitka exited with code %s", completed.returncode)
        return completed.returncode
    if not output_exe.is_file():
        logger.error("Nuitka reported success but %s is missing", output_exe)
        return 1
    logger.info("Built %s (%s bytes)", output_exe, output_exe.stat().st_size)
    _log_bundled_native_extensions(repo_root)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Compile the blinter package into dist/blinter.exe."""
    _configure_logging()
    parser = argparse.ArgumentParser(
        description="Build the Windows standalone blinter.exe with Nuitka."
    )
    parser.add_argument(
        "--mingw",
        action="store_true",
        help=(
            "Use Nuitka's MinGW64 toolchain instead of MSVC. "
            "Python 3.13+ requires --experimental=force-mingw64; CI uses MSVC."
        ),
    )
    parsed = parser.parse_args(argv)
    mingw_flag: object = parsed.mingw
    use_mingw = mingw_flag is True

    repo_root = ROOT
    try:
        pyproject_path = _validate_inputs(repo_root)
        version = _read_project_version(pyproject_path)
        assert_pure_python_charset_normalizer()
        _write_build_version(repo_root, version)
    except (OSError, ValueError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        logger.error("%s", exc)
        _remove_build_version(repo_root)
        return 2

    windows = _is_windows()
    if not windows:
        logger.warning(
            "This script targets Windows onefile builds; "
            "MSVC/icon/version resources will be omitted on %s",
            os.name,
        )
    command = build_nuitka_command(
        version=version,
        python_executable=sys.executable,
        windows=windows,
        mingw=use_mingw,
    )
    try:
        return run_nuitka(command, repo_root)
    except OSError as exc:
        logger.error("Failed to launch Nuitka: %s", exc)
        return 1
    finally:
        _remove_build_version(repo_root)


if __name__ == "__main__":
    sys.exit(main())
