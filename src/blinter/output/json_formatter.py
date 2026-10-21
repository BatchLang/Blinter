"""JSON report serialization for CLI and tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from blinter.models import LintIssue, ProcessingResults
from blinter.output.formatters import compute_most_common_rule, compute_severity_counts
from blinter.rules.registry import RULES


class SerializedIssue(TypedDict):
    """JSON representation of a single lint issue."""

    file: str | None
    line: int
    code: str
    name: str
    severity: str
    explanation: str
    recommendation: str
    context: str


class MostCommonRule(TypedDict):
    """JSON representation of the most frequently reported rule."""

    code: str
    name: str
    count: int


class StaleBaselineEntry(TypedDict):
    """JSON entry for a baseline record that no longer matches a finding."""

    code: str
    file: str
    text: str


class ReportSummary(TypedDict):
    """JSON summary section of a lint report."""

    total_issues: int
    fatal_issues: int
    baselined_issues: int
    files_processed: int
    files_with_errors: int
    severity_counts: dict[str, int]
    most_common_rule: MostCommonRule | None


class ProcessedFile(TypedDict):
    """JSON entry for an analyzed script path."""

    path: str
    called_by: str | None


class SkippedFile(TypedDict):
    """JSON entry for a file that could not be processed."""

    path: str
    reason: str


class BaselineReportInfo(TypedDict):
    """Baseline counts and stale entries included in a JSON report."""

    baselined_issues: int
    stale_baseline_entries: list[StaleBaselineEntry]


class LintReport(TypedDict):
    """Top-level JSON lint report structure."""

    blinter_version: str
    target: str
    is_directory: bool
    summary: ReportSummary
    processed_files: list[ProcessedFile]
    skipped_files: list[SkippedFile]
    stale_baseline_entries: list[StaleBaselineEntry]
    issues: list[SerializedIssue]


def _serialize_issue(issue: LintIssue) -> SerializedIssue:
    """Convert a LintIssue to a JSON-serializable dict."""
    return SerializedIssue(
        file=issue.file_path,
        line=issue.line_number,
        code=issue.rule.code,
        name=issue.rule.name,
        severity=issue.rule.severity.value,
        explanation=issue.rule.explanation,
        recommendation=issue.rule.recommendation,
        context=issue.context,
    )


def _serialize_most_common_rule(
    issues: list[LintIssue],
) -> MostCommonRule | None:
    """Return most common rule metadata, or None when there are no issues."""
    rule_code, count = compute_most_common_rule(issues)
    if not rule_code:
        return None
    rule_obj = RULES.get(rule_code)
    rule_name = rule_obj.name if rule_obj is not None else rule_code
    return MostCommonRule(code=rule_code, name=rule_name, count=count)


def _baseline_report_fields(
    baseline: BaselineReportInfo | None,
) -> tuple[int, list[StaleBaselineEntry]]:
    """Return the accepted-finding count and stale entries for a report."""
    if baseline is None:
        return 0, []
    return baseline["baselined_issues"], list(baseline["stale_baseline_entries"])


def build_report(
    results: ProcessingResults,
    target_path: str,
    version: str,
    fatal_issues: int,
    baseline: BaselineReportInfo | None = None,
) -> LintReport:
    """Build a JSON-serializable lint report from processing results."""
    issues = results.all_issues
    severity_counts = compute_severity_counts(issues)
    baselined_issues, stale = _baseline_report_fields(baseline)

    return LintReport(
        blinter_version=version,
        target=target_path,
        is_directory=Path(target_path).is_dir(),
        summary=ReportSummary(
            total_issues=len(issues),
            fatal_issues=fatal_issues,
            baselined_issues=baselined_issues,
            files_processed=results.total_files_processed,
            files_with_errors=results.files_with_errors,
            severity_counts={
                severity.value: count for severity, count in severity_counts.items()
            },
            most_common_rule=_serialize_most_common_rule(issues),
        ),
        processed_files=[
            ProcessedFile(path=file_path, called_by=called_by)
            for file_path, called_by in results.processed_file_paths
        ],
        skipped_files=[
            SkippedFile(path=file_path, reason=reason)
            for file_path, reason in results.skipped_files
        ],
        stale_baseline_entries=stale,
        issues=[_serialize_issue(issue) for issue in issues],
    )


def _dumps_report(report: LintReport) -> str:
    """Serialize a report dict to a JSON string."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def write_report(path: str, report: LintReport) -> None:
    """Write a JSON report to the given file path."""
    Path(path).write_text(_dumps_report(report), encoding="utf-8")


def print_report(report: LintReport) -> None:
    """Print a JSON report to stdout."""
    print(_dumps_report(report), end="")
