#!/usr/bin/env python3
"""Fail when dill can pickle code objects on Python 3.15+ again.

Python 3.15 removed ``code.co_lnotab``. dill 0.4.1 still reads it, so
``dill.dumps`` crashes on any function pickled by value. Pylint serializes its
linter with dill when ``jobs`` is not 1, so parallel pylint crashes too. See
pylint-dev/pylint#11528 and uqfoundation/dill#753.

Projects work around this by forcing ``-j 1`` on 3.15+. This script is a
tripwire for removing that workaround: it exits 1 once dill works again.

Exit codes:
    0  nothing to do: Python < 3.15, dill missing, or dill is still broken
    1  dill is fixed: remove the workaround
    2  dill failed in an unexpected way: investigate
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

EXIT_OK = 0
EXIT_FIXED = 1
EXIT_UNEXPECTED = 2


def _probe(dill_module: ModuleType) -> tuple[int, str]:
    """Pickle a function by value and return an exit code and a report line."""
    version = str(getattr(dill_module, "__version__", "unknown"))

    def probe(value: int) -> int:
        return value + 1

    # A nested function cannot be pickled by reference, so dill has to serialize
    # its code object. That is the path that reads co_lnotab.
    try:
        payload: bytes = dill_module.dumps(probe)
    except Exception as error:
        if isinstance(error, AttributeError) and "co_lnotab" in str(error):
            return (
                EXIT_OK,
                f"STILL BROKEN: dill {version} reads co_lnotab; "
                "keep the -j 1 workaround",
            )
        return (
            EXIT_UNEXPECTED,
            f"UNEXPECTED: dill {version} raised {type(error).__name__}: {error}",
        )

    try:
        # The payload was produced a moment ago in this process, so it is trusted.
        works = dill_module.loads(payload)(1) == 2
    except Exception as error:
        return (
            EXIT_UNEXPECTED,
            f"UNEXPECTED: dill {version} dumped but failed to load: {error}",
        )
    if not works:
        return (
            EXIT_UNEXPECTED,
            f"UNEXPECTED: dill {version} round trip returned a wrong result",
        )

    return (
        EXIT_FIXED,
        f"FIXED: dill {version} pickles code objects again. "
        "Remove the pylint '-j 1' workaround and this check.",
    )


def main() -> int:
    """Probe dill and report whether the 3.15 workaround is still needed."""
    # Not compared as sys.version_info directly: mypy would fold the check
    # using python_version from mypy.ini and flag the rest as unreachable.
    python_version = tuple(sys.version_info[:2])
    if python_version < (3, 15):
        print(f"SKIP: Python {python_version[0]}.{python_version[1]} < 3.15")
        return EXIT_OK

    try:
        dill_module = importlib.import_module("dill")
    except ImportError:
        print("SKIP: dill is not installed")
        return EXIT_OK

    code, message = _probe(dill_module)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
