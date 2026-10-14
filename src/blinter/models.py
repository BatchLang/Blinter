"""Core data models: rules, lint issues, and configuration."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

from blinter.constants import MAX_LINE_LENGTH, MAX_SCAN_FILES


class RuleSeverity(Enum):
    """Rule severity levels."""

    ERROR = "Error"
    WARNING = "Warning"
    STYLE = "Style"
    SECURITY = "Security"
    PERFORMANCE = "Performance"


class OutputFormat(Enum):
    """CLI output format."""

    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"


@dataclass
class Rule:
    """Represents a linting rule with code, explanation and recommendation."""

    code: str
    name: str
    severity: RuleSeverity
    explanation: str
    recommendation: str

    def __post_init__(self) -> None:
        """Validate rule after initialization."""
        if not self.code or not isinstance(self.code, str):
            raise ValueError("Rule code must be a non-empty string")
        if not self.name or not isinstance(self.name, str):
            raise ValueError("Rule name must be a non-empty string")
        if not isinstance(self.severity, RuleSeverity):
            raise ValueError("Rule severity must be a RuleSeverity enum")
        if not self.explanation or not isinstance(self.explanation, str):
            raise ValueError("Rule explanation must be a non-empty string")
        if not self.recommendation or not isinstance(self.recommendation, str):
            raise ValueError("Rule recommendation must be a non-empty string")


@dataclass
class LintIssue:
    """Represents a linting issue found in a batch file."""

    line_number: int
    rule: Rule
    context: str = ""  # Additional context about the issue
    file_path: Optional[str] = None  # Path to file containing the issue

    def __post_init__(self) -> None:
        """Validate issue after initialization."""
        if self.line_number < 1:
            raise ValueError("Line number must be positive")
        if not isinstance(self.rule, Rule):
            raise ValueError("Rule must be a Rule instance")


@dataclass
class BlinterConfig:  # pylint: disable=too-many-instance-attributes
    """Configuration settings for blinter."""

    # General settings
    recursive: bool = True
    show_summary: bool = False
    max_line_length: int = 100
    max_scan_files: int = MAX_SCAN_FILES
    follow_calls: bool = False
    scan_root: Optional[str] = None

    # Rule enablement - all rules enabled by default
    enabled_rules: Optional[Set[str]] = None
    disabled_rules: Optional[Set[str]] = None

    # Severity filtering
    min_severity: Optional[RuleSeverity] = None

    def __post_init__(self) -> None:
        """Initialize default values after creation."""
        if self.enabled_rules is None:
            self.enabled_rules = set()
        if self.disabled_rules is None:
            self.disabled_rules = set()

        if self.scan_root is not None:
            if not isinstance(self.scan_root, str) or not self.scan_root.strip():
                raise ValueError("scan_root must be a non-empty string path when set")

        if self.max_line_length <= 0 or self.max_line_length > MAX_LINE_LENGTH:
            raise ValueError(
                f"max_line_length must be between 1 and {MAX_LINE_LENGTH}, "
                f"got {self.max_line_length}"
            )

        if self.max_scan_files <= 0:
            raise ValueError(
                f"max_scan_files must be positive, got {self.max_scan_files}"
            )

    def is_rule_enabled(self, rule_code: str) -> bool:
        """Check if a rule is enabled based on configuration."""
        # If rule is explicitly disabled, return False
        if self.disabled_rules and rule_code in self.disabled_rules:
            return False

        # If enabled_rules is empty, all rules are enabled by default
        # If enabled_rules has items, only those rules are enabled
        if self.enabled_rules:
            return rule_code in self.enabled_rules

        return True

    def should_include_severity(self, severity: RuleSeverity) -> bool:
        """Check if issues of this severity should be included."""
        if self.min_severity is None:
            return True

        if self.min_severity == RuleSeverity.ERROR:
            return severity in (RuleSeverity.ERROR, RuleSeverity.SECURITY)

        # Define severity order (higher values = more severe)
        severity_order = {
            RuleSeverity.STYLE: 1,
            RuleSeverity.PERFORMANCE: 2,
            RuleSeverity.WARNING: 3,
            RuleSeverity.SECURITY: 4,
            RuleSeverity.ERROR: 5,
        }

        return severity_order.get(severity, 0) >= severity_order.get(
            self.min_severity, 0
        )


@dataclass
class CliArguments:  # pylint: disable=too-many-instance-attributes  # CLI argument bag
    """Parsed CLI arguments."""

    target_path: str
    use_config: bool
    cli_show_summary: Optional[bool]
    cli_recursive: Optional[bool]
    cli_follow_calls: Optional[bool]
    cli_max_line_length: Optional[int]
    cli_log_level: Optional[int]
    config_path: Optional[str] = None
    cli_output_path: Optional[str] = None
    cli_output_format: OutputFormat = OutputFormat.TEXT


@dataclass
class ProcessingResults:
    """Results from processing batch files."""

    all_issues: List[LintIssue]
    file_results: Dict[str, List[LintIssue]]
    total_files_processed: int
    files_with_errors: int
    processed_file_paths: List[
        Tuple[str, Optional[str]]
    ]  # (file_path, called_by_parent)
    skipped_files: List[Tuple[str, str]] = field(
        default_factory=list
    )  # (file_path, reason)


@dataclass
class ProcessingState:
    """State container for batch file processing."""

    processed_files: Set[Path]
    all_issues: List[LintIssue]
    file_results: Dict[str, List[LintIssue]]
    processed_file_paths: List[Tuple[str, Optional[str]]]
    lines_cache: Dict[Path, List[str]] = field(default_factory=dict)
