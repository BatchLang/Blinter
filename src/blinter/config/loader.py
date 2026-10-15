"""INI configuration loading and default config file generation."""

import configparser
from pathlib import Path
from typing import (
    Optional,
)

from blinter.constants import MAX_LINE_LENGTH, MAX_SCAN_FILES
from blinter.logging_config import logger
from blinter.models import BlinterConfig, RuleSeverity
from blinter.rules.registry import RULES


def _load_general_settings(
    config: BlinterConfig, parser: configparser.ConfigParser
) -> None:
    """Load general settings from config parser."""
    if not parser.has_section("general"):
        return

    general = parser["general"]

    config.recursive = general.getboolean("recursive", fallback=True)
    config.show_summary = general.getboolean("show_summary", fallback=False)
    try:
        max_line_length = general.getint("max_line_length", fallback=100)
    except ValueError as error:
        logger.error("Invalid max_line_length value in config: %s", error)
        raise ValueError("Invalid max_line_length value in config") from error
    if not 0 < max_line_length <= MAX_LINE_LENGTH:
        logger.error(
            "Invalid max_line_length %s in config (must be 1-%s)",
            max_line_length,
            MAX_LINE_LENGTH,
        )
        raise ValueError(
            f"Invalid max_line_length {max_line_length} in config "
            f"(must be 1-{MAX_LINE_LENGTH})"
        )
    config.max_line_length = max_line_length
    try:
        max_scan_files = general.getint("max_scan_files", fallback=MAX_SCAN_FILES)
        if max_scan_files > 0:
            config.max_scan_files = max_scan_files
        else:
            logger.warning(
                "Invalid max_scan_files %s in config (must be positive), using default",
                max_scan_files,
            )
    except ValueError:
        logger.warning("Invalid max_scan_files value in config, using default")
    config.follow_calls = general.getboolean("follow_calls", fallback=False)

    severity_str = general.get("min_severity", "").strip()
    if severity_str:
        _set_min_severity(config, severity_str)


def _set_min_severity(config: BlinterConfig, severity_str: str) -> None:
    """Set minimum severity from string value."""
    severity_map = {
        "ERROR": RuleSeverity.ERROR,
        "SECURITY": RuleSeverity.SECURITY,
        "WARNING": RuleSeverity.WARNING,
        "PERFORMANCE": RuleSeverity.PERFORMANCE,
        "STYLE": RuleSeverity.STYLE,
    }
    severity_upper = severity_str.upper()
    if severity_upper in severity_map:
        config.min_severity = severity_map[severity_upper]
        return
    logger.error("Invalid min_severity value: %s", severity_str)
    raise ValueError(f"Invalid min_severity value: {severity_str}")


def _validate_rule_codes(rule_codes: set[str], setting_name: str) -> set[str]:
    """Return validated rule codes, logging warnings for unknown entries."""
    validated: set[str] = set()
    for rule_code in rule_codes:
        if rule_code in RULES:
            validated.add(rule_code)
        else:
            logger.warning(
                "Unknown rule code '%s' in %s; ignoring this entry",
                rule_code,
                setting_name,
            )
    return validated


def _load_rule_settings(
    config: BlinterConfig, parser: configparser.ConfigParser
) -> None:
    """Load rule settings from config parser."""
    if not parser.has_section("rules"):
        return

    rules = parser["rules"]

    # Handle enabled_rules
    enabled_str = rules.get("enabled_rules", "").strip()
    if enabled_str:
        config.enabled_rules = _validate_rule_codes(
            {rule.strip() for rule in enabled_str.split(",") if rule.strip()},
            "enabled_rules",
        )

    # Handle disabled_rules
    disabled_str = rules.get("disabled_rules", "").strip()
    if disabled_str:
        config.disabled_rules = _validate_rule_codes(
            {rule.strip() for rule in disabled_str.split(",") if rule.strip()},
            "disabled_rules",
        )


def load_config(
    config_path: Optional[str] = None, use_config: bool = True
) -> BlinterConfig:
    """
    Load configuration from blinter.ini file.

    Args:
        config_path: Optional path to config file. If None, looks for blinter.ini in
            current directory
        use_config: Whether to use config file at all

    Returns:
        BlinterConfig object with loaded settings
    """
    config = BlinterConfig()

    if not use_config:
        return config

    # Determine config file path. An explicit --config path that is missing
    # is a user error. The default blinter.ini lookup may be absent.
    explicit_config = config_path is not None
    config_path = config_path or "blinter.ini"
    config_file = Path(config_path)

    if not config_file.exists():
        if explicit_config:
            logger.error("Configuration file not found: %s", config_file)
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        logger.info("No configuration file found at %s, using defaults", config_file)
        return config

    try:
        parser = configparser.ConfigParser()
        parser.read(config_file, encoding="utf-8")

        _load_general_settings(config, parser)
        _load_rule_settings(config, parser)

        logger.info("Configuration loaded from %s", config_file)

    except (configparser.Error, OSError) as error:
        logger.warning(
            "Error loading configuration from %s: %s. Using defaults.",
            config_file,
            error,
        )

    return config


def create_default_config_file(
    config_path: str = "blinter.ini", force: bool = False
) -> bool:
    """
    Create a default configuration file with all available options documented.

    Args:
        config_path: Path where to create the config file
        force: When True, overwrite an existing configuration file

    Returns:
        True when the file was written successfully, False on failure.
    """
    config_file = Path(config_path)
    if config_file.exists() and not force:
        logger.warning(
            "Configuration file already exists: %s. "
            "Use --create-config --force to overwrite, or edit the existing file.",
            config_path,
        )
        return False

    config_content = """# Blinter Configuration File
# This file configures the behavior of the blinter batch file linter.
# All settings are optional - if not specified, defaults will be used.

[general]
# Whether to recursively search directories for batch files (default: true)
recursive = true

# Whether to show summary statistics at the end (default: false)
show_summary = false

# Maximum line length before triggering S011 and S020 rules (default: 100)
max_line_length = 100

# Maximum batch files discovered when scanning a directory (default: 1000)
max_scan_files = 1000

# Whether to automatically scan scripts called by CALL statements (default: false)
# This helps analyze centralized configuration scripts that set variables
follow_calls = false

# Minimum severity level to report (default: none - show all)
# Valid values: ERROR, SECURITY, WARNING, PERFORMANCE, STYLE
# ERROR includes both ERROR and SECURITY severities (both affect CLI exit code)
# min_severity = WARNING

[rules]
# Comma-separated list of specific rules to enable (default: all rules enabled)
# If specified, ONLY these rules will be checked
# enabled_rules = E001,E002,W001,S001

# Comma-separated list of rules to disable (default: none disabled)
# These rules will be skipped even if they would normally be checked
# disabled_rules = S007,S011

# Examples:
# To only check for errors and security issues:
# enabled_rules = E001,E002,E003,E004,E005,E006,E007,E008,E009,E010,E011,E012,E013,E014,E015,E016,E017,E018,SEC001,SEC002,SEC003,SEC004,SEC005,SEC006,SEC007,SEC008,SEC009,SEC010,SEC011,SEC012,SEC013

# To disable style checks but keep everything else:
# disabled_rules = S001,S002,S003,S004,S005,S007,S008,S009,S010,S011,S012,S013,S014,S015,S016,S017,S018,S019,S020

# To only show warnings and errors (skip style, performance):
# min_severity = WARNING
"""

    try:
        config_file.write_text(config_content, encoding="utf-8")
        logger.info("Default configuration file created: %s", config_path)
        return True
    except OSError as error:
        logger.error("Error creating configuration file %s: %s", config_path, error)
        return False
