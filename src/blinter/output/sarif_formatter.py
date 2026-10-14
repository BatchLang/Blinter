"""SARIF 2.1.0 report serialization for CLI and tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, assert_never
from urllib.parse import quote

from blinter.logging_config import logger
from blinter.models import LintIssue, ProcessingResults, Rule, RuleSeverity

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URI = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/"
    "sarif-2.1/schema/sarif-schema-2.1.0.json"
)
_TOOL_NAME = "Blinter"
_INFORMATION_URI = "https://github.com/BatchLang/Blinter"
_SKIPPED_FILE_NOTIFICATION_ID = "BLINT001"
_START_COLUMN = 1
_MISSING_PATH_URI = "unknown"

SarifLevel = Literal["error", "warning", "note"]


class SarifText(TypedDict):
    """SARIF message or multiformat string that carries plain text."""

    text: str


class SarifConfiguration(TypedDict):
    """Default SARIF level for a rule."""

    level: SarifLevel


class SarifRuleProperties(TypedDict):
    """Extra rule metadata consumed by SARIF viewers."""

    tags: list[str]


class SarifRule(TypedDict):
    """One reportingDescriptor for a Blinter rule that produced a result."""

    id: str
    shortDescription: SarifText
    fullDescription: SarifText
    help: SarifText
    defaultConfiguration: SarifConfiguration
    properties: NotRequired[SarifRuleProperties]


class SarifRegion(TypedDict):
    """Line-scoped region. Blinter does not record a column."""

    startLine: int
    startColumn: int


class SarifArtifactLocation(TypedDict):
    """URI of the batch file that contains a result."""

    uri: str


class SarifPhysicalLocation(TypedDict):
    """File and line for one result."""

    artifactLocation: SarifArtifactLocation
    region: SarifRegion


class SarifLocation(TypedDict):
    """SARIF location wrapper around a physical location."""

    physicalLocation: SarifPhysicalLocation


class SarifResultProperties(TypedDict):
    """Blinter severity preserved beside the coarser SARIF level."""

    blinterSeverity: str


class SarifResult(TypedDict):
    """One SARIF result."""

    ruleId: str
    ruleIndex: int
    level: SarifLevel
    message: SarifText
    locations: list[SarifLocation]
    properties: SarifResultProperties


class SarifDescriptorReference(TypedDict):
    """Reference to a driver notification descriptor."""

    id: str


class SarifNotification(TypedDict):
    """Tool notification for a file the linter could not process."""

    descriptor: SarifDescriptorReference
    message: SarifText
    level: Literal["error"]


class SarifNotificationDescriptor(TypedDict):
    """Descriptor for the skipped-file notification."""

    id: str
    shortDescription: SarifText


class SarifDriver(TypedDict):
    """tool.driver object identifying Blinter and its rules."""

    name: str
    version: str
    informationUri: str
    rules: list[SarifRule]
    notifications: NotRequired[list[SarifNotificationDescriptor]]


class SarifTool(TypedDict):
    """SARIF tool object."""

    driver: SarifDriver


class SarifInvocation(TypedDict):
    """Record of one completed lint run."""

    executionSuccessful: bool
    toolExecutionNotifications: NotRequired[list[SarifNotification]]


class SarifRun(TypedDict):
    """Single SARIF run."""

    tool: SarifTool
    invocations: list[SarifInvocation]
    results: list[SarifResult]


SarifLog = TypedDict(
    "SarifLog",
    {
        "$schema": str,
        "version": str,
        "runs": list[SarifRun],
    },
)


def _sarif_level(severity: RuleSeverity) -> SarifLevel:
    """Map a Blinter severity onto a SARIF level."""
    match severity:
        case RuleSeverity.ERROR:
            return "error"
        case RuleSeverity.SECURITY:
            return "error"
        case RuleSeverity.WARNING:
            return "warning"
        case RuleSeverity.STYLE:
            return "note"
        case RuleSeverity.PERFORMANCE:
            return "note"
        case _ as unreachable:
            assert_never(unreachable)


def _artifact_uri(file_path: str | None, *, cwd: Path) -> str:
    """Return a SARIF artifact URI relative to cwd, or a file URI outside it."""
    if file_path is None or not file_path.strip():
        logger.warning(
            "SARIF result has no file path; using uri '%s'", _MISSING_PATH_URI
        )
        return _MISSING_PATH_URI

    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        resolved = candidate.resolve()
        base = cwd.resolve()
    except OSError as path_error:
        logger.warning(
            "Could not resolve %s for a SARIF URI: %s", file_path, path_error
        )
        return _MISSING_PATH_URI

    try:
        relative = resolved.relative_to(base)
    except ValueError:
        uri = resolved.as_uri()
        logger.debug(
            "Artifact path %s is outside %s; using file URI %s",
            file_path,
            base,
            uri,
        )
        return uri

    uri = quote(relative.as_posix(), safe="/")
    logger.debug("Artifact path %s encoded as %s", file_path, uri)
    return uri


def _rules_for_issues(issues: list[LintIssue]) -> list[Rule]:
    """Return each distinct rule that fired, sorted by rule code."""
    by_code: dict[str, Rule] = {}
    for issue in issues:
        by_code.setdefault(issue.rule.code, issue.rule)
    return [by_code[code] for code in sorted(by_code)]


def _serialize_rule(rule: Rule) -> SarifRule:
    """Convert a Blinter rule into a SARIF reporting descriptor."""
    serialized = SarifRule(
        id=rule.code,
        shortDescription=SarifText(text=rule.name),
        fullDescription=SarifText(text=rule.explanation),
        help=SarifText(text=rule.recommendation),
        defaultConfiguration=SarifConfiguration(level=_sarif_level(rule.severity)),
    )
    if rule.code.startswith("SEC"):
        serialized["properties"] = SarifRuleProperties(tags=["security"])
        logger.debug("Tagged SARIF rule %s as security", rule.code)
    return serialized


def _result_message(issue: LintIssue) -> str:
    """Prefer the issue context, then the rule explanation."""
    if issue.context:
        return issue.context
    return issue.rule.explanation


def _serialize_result(
    issue: LintIssue,
    rule_index: dict[str, int],
    *,
    cwd: Path,
) -> SarifResult:
    """Convert one lint issue into a SARIF result."""
    return SarifResult(
        ruleId=issue.rule.code,
        ruleIndex=rule_index[issue.rule.code],
        level=_sarif_level(issue.rule.severity),
        message=SarifText(text=_result_message(issue)),
        locations=[
            SarifLocation(
                physicalLocation=SarifPhysicalLocation(
                    artifactLocation=SarifArtifactLocation(
                        uri=_artifact_uri(issue.file_path, cwd=cwd)
                    ),
                    region=SarifRegion(
                        startLine=issue.line_number,
                        startColumn=_START_COLUMN,
                    ),
                )
            )
        ],
        properties=SarifResultProperties(blinterSeverity=issue.rule.severity.value),
    )


def _skipped_notifications(
    skipped_files: list[tuple[str, str]],
) -> list[SarifNotification]:
    """Build tool notifications for files that could not be processed."""
    notifications: list[SarifNotification] = []
    for path, reason in skipped_files:
        detail = reason if reason else "unknown reason"
        logger.debug("SARIF skipped-file notification for %s: %s", path, detail)
        notifications.append(
            SarifNotification(
                descriptor=SarifDescriptorReference(id=_SKIPPED_FILE_NOTIFICATION_ID),
                message=SarifText(text=f"Could not process {path}: {detail}"),
                level="error",
            )
        )
    return notifications


def _build_driver(
    version: str,
    rules: list[Rule],
    *,
    include_skip_notification: bool,
) -> SarifDriver:
    """Build the Blinter driver, including the skip notification when needed."""
    driver = SarifDriver(
        name=_TOOL_NAME,
        version=version,
        informationUri=_INFORMATION_URI,
        rules=[_serialize_rule(rule) for rule in rules],
    )
    if include_skip_notification:
        driver["notifications"] = [
            SarifNotificationDescriptor(
                id=_SKIPPED_FILE_NOTIFICATION_ID,
                shortDescription=SarifText(text="Batch file could not be processed"),
            )
        ]
    return driver


def _build_invocation(notifications: list[SarifNotification]) -> SarifInvocation:
    """Build the invocation record for a finished lint run."""
    invocation = SarifInvocation(executionSuccessful=True)
    if notifications:
        invocation["toolExecutionNotifications"] = notifications
    return invocation


def build_sarif_report(
    results: ProcessingResults,
    version: str,
    *,
    cwd: Path | None = None,
) -> SarifLog:
    """Build a SARIF 2.1.0 log from processing results."""
    base = Path.cwd() if cwd is None else cwd
    rules = _rules_for_issues(results.all_issues)
    rule_index = {rule.code: index for index, rule in enumerate(rules)}
    sarif_results = [
        _serialize_result(issue, rule_index, cwd=base) for issue in results.all_issues
    ]
    notifications = _skipped_notifications(results.skipped_files)
    driver = _build_driver(
        version,
        rules,
        include_skip_notification=bool(notifications),
    )
    tool: SarifTool = {"driver": driver}
    run: SarifRun = {
        "tool": tool,
        "invocations": [_build_invocation(notifications)],
        "results": sarif_results,
    }
    logger.info(
        "Built SARIF report version=%s results=%d rules=%d skipped=%d cwd=%s",
        version,
        len(sarif_results),
        len(rules),
        len(notifications),
        base,
    )
    report: SarifLog = {
        "$schema": SARIF_SCHEMA_URI,
        "version": SARIF_VERSION,
        "runs": [run],
    }
    return report


def _dumps_sarif(report: SarifLog) -> str:
    """Serialize a SARIF log to a JSON string."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def write_sarif_report(path: str, report: SarifLog) -> None:
    """Write a SARIF report to the given file path."""
    destination = Path(path)
    logger.info("Writing SARIF report to %s", destination)
    destination.write_text(_dumps_sarif(report), encoding="utf-8")


def print_sarif_report(report: SarifLog) -> None:
    """Print a SARIF report to stdout."""
    logger.debug("Printing SARIF report to stdout")
    print(_dumps_sarif(report), end="")
