"""Package version resolution."""

import importlib
from importlib.metadata import PackageNotFoundError, version
import logging
from pathlib import Path
from typing import cast

__author__ = "tboy1337"

__license__ = "AGPL-3.0-or-later"

_PACKAGE_NAME = "Blinter"
_BUILD_VERSION_MODULE = "blinter._build_version"

logger = logging.getLogger(__name__)


def _load_baked_version() -> str | None:
    """Return the version written by scripts/build_exe.py, when that module exists."""
    try:
        module = importlib.import_module(_BUILD_VERSION_MODULE)
    except ImportError:
        logger.debug("Build version module %s is not present", _BUILD_VERSION_MODULE)
        return None
    version_raw: object = cast(object, getattr(module, "VERSION", None))
    if isinstance(version_raw, str) and version_raw:
        logger.debug("Loaded build-time version %s", version_raw)
        return version_raw
    if version_raw is not None:
        logger.warning("Ignoring invalid build version %r", version_raw)
    return None


# Generated at build time and absent from source checkouts. import_module avoids a
# pylint cycle through blinter/__init__.py when this file has not been written yet.
_BAKED_VERSION: str | None = _load_baked_version()


def _pyproject_path() -> Path:
    """Return pyproject.toml for a source checkout."""
    module_file = Path(__file__).resolve()
    package_dir = module_file.parent
    source_path = package_dir.parent.parent / "pyproject.toml"
    logger.debug("Resolved source pyproject.toml at %s", source_path)
    return source_path


def _fallback_version() -> str:
    """Read version from pyproject.toml when the package is not installed."""
    pyproject = _pyproject_path()
    if not pyproject.is_file():
        logger.debug("pyproject.toml is missing at %s", pyproject)
        return "unknown"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version = "):
            parsed = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            logger.debug("Parsed pyproject.toml version %s", parsed)
            return parsed
    logger.debug("pyproject.toml at %s has no version assignment", pyproject)
    return "unknown"


def get_version() -> str:
    """Return the package version, preferring the Nuitka build constant."""
    if isinstance(_BAKED_VERSION, str) and _BAKED_VERSION:
        logger.debug("Using build-time version %s", _BAKED_VERSION)
        return _BAKED_VERSION
    if _pyproject_path().is_file():
        pyproject_version = _fallback_version()
        if pyproject_version != "unknown":
            return pyproject_version
    try:
        installed = version(_PACKAGE_NAME)
    except PackageNotFoundError:
        logger.debug("Package metadata for %s was not found", _PACKAGE_NAME)
        return _fallback_version()
    logger.debug("Using installed metadata version %s", installed)
    return installed


__version__ = get_version()
