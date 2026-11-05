#!/usr/bin/env python3
"""Install the pinned Nuitka build environment into ./venv."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger("blinter.install_nuitka_venv")
_ROOT = Path(__file__).resolve().parent.parent
_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "venv", "venv", "--python", "3.14"),
    ("uv", "pip", "install", "--python", "venv", "setuptools==84.2.1"),
    ("uv", "pip", "install", "--python", "venv", "nuitka==4.3.4"),
    (
        "uv",
        "pip",
        "install",
        "--python",
        "venv",
        "--upgrade",
        "-r",
        "requirements.txt",
        "--no-binary",
        "charset-normalizer",
    ),
    ("uv", "pip", "install", "--python", "venv", "-e", "."),
)


def main() -> int:
    """Create ./venv and install the pinned Nuitka build dependencies."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for command in _COMMANDS:
        logger.info("Running %s", " ".join(command))
        completed = subprocess.run(command, cwd=_ROOT, check=False)
        if completed.returncode != 0:
            logger.error("%s exited %s", command[0], completed.returncode)
            return completed.returncode
    logger.info("Nuitka build environment is ready in %s", _ROOT / "venv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
