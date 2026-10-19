"""Blinter - Batch file linter for Windows.

Public API
----------
Import the symbols below from ``blinter`` for normal library and CLI use.

Advanced / internal APIs live in subpackages, for example::

    from blinter.rules.registry import RULES
    from blinter.patterns import DANGEROUS_COMMAND_PATTERNS
    from blinter.checkers.syntax import _check_syntax_errors
"""

from blinter._version import __author__, __license__, __version__
from blinter.cli.main import main
from blinter.config.loader import create_default_config_file, load_config
from blinter.engine.linter import lint_batch_file
from blinter.io.discovery import find_batch_files
from blinter.io.encoding import read_file_with_encoding
from blinter.models import BlinterConfig, LintIssue, Rule, RuleSeverity

__all__ = [
    "__author__",
    "__license__",
    "__version__",
    "BlinterConfig",
    "LintIssue",
    "Rule",
    "RuleSeverity",
    "create_default_config_file",
    "find_batch_files",
    "lint_batch_file",
    "load_config",
    "main",
    "read_file_with_encoding",
]
