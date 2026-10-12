"""Package version resolution."""

from importlib.metadata import PackageNotFoundError, version
import logging
from pathlib import Path

__author__ = "tboy1337"

__license__ = "AGPL-3.0-or-later"

_PACKAGE_NAME = "Blinter"

logger = logging.getLogger(__name__)

# Static import so Nuitka compiles VERSION into the exe as a constant.
# scripts/build_exe.py generates the module; source checkouts do not have it.
# Pylint then reports import-error and a false cycle through blinter/__init__.py.
_BAKED_VERSION: str | None
try:
    from ._build_version import (  # pylint: disable=import-error,cyclic-import
        VERSION as _BAKED_VERSION,
    )
except ImportError:
    logger.debug("Build version module is not present")
    _BAKED_VERSION = None


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
