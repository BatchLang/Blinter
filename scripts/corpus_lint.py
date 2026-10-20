#!/usr/bin/env python3
"""Lint the local batch-script-examples corpus and write a summary report."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import TypedDict, cast

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORPUS_DIR = _REPO_ROOT / "batch-script-examples"
_DEFAULT_REPORT = _REPO_ROOT / "batch-examples-corpus-summary.json"
_DEFAULT_BASELINE = _REPO_ROOT / "tests" / "fixtures" / "corpus-baseline.json"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from blinter import (  # noqa: E402  # pylint: disable=wrong-import-position
    lint_batch_file,
)
from scripts.corpus_baseline import (  # noqa: E402  # pylint: disable=wrong-import-position
    check_baseline,
)


class CorpusReport(TypedDict):
    """JSON-serializable corpus lint summary."""

    file_count: int
    total_issues: int
    errors: list[str]
    severity_counts: dict[str, int]
    top_rules: list[tuple[str, int]]
    s011_s020_overlap_lines: int
    s012_count: int
    files_by_issue_count: list[tuple[str, int]]


def _collect_batch_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.glob("**/*")
        if path.is_file() and path.suffix.lower() in {".bat", ".cmd"}
    )


def _issue_count_sort_key(item: tuple[str, int]) -> int:
    return -item[1]


def _lint_corpus(corpus_dir: Path) -> CorpusReport:
    files = _collect_batch_files(corpus_dir)
    rule_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    file_counts: dict[str, int] = {}
    errors: list[str] = []

    for file_path in files:
        try:
            issues = lint_batch_file(str(file_path))
        except Exception as exc:  # noqa: BLE001 - report all corpus failures
            errors.append(f"{file_path.name}: {exc}")
            continue
        file_counts[file_path.name] = len(issues)
        for issue in issues:
            rule_counts[issue.rule.code] += 1
            severity_counts[issue.rule.severity.value] += 1

    overlap = 0
    for file_path in files:
        if file_path.name in {name.split(":")[0] for name in errors}:
            continue
        try:
            issues = lint_batch_file(str(file_path))
        except Exception:
            continue
        by_line: dict[int, set[str]] = {}
        for issue in issues:
            if issue.rule.code in {"S011", "S020"}:
                by_line.setdefault(issue.line_number, set()).add(issue.rule.code)
        overlap += sum(1 for codes in by_line.values() if codes == {"S011", "S020"})

    return CorpusReport(
        file_count=len(files),
        total_issues=sum(rule_counts.values()),
        errors=errors,
        severity_counts=dict(severity_counts),
        top_rules=rule_counts.most_common(30),
        s011_s020_overlap_lines=overlap,
        s012_count=rule_counts.get("S012", 0),
        files_by_issue_count=sorted(file_counts.items(), key=_issue_count_sort_key)[
            :20
        ],
    )


def main() -> None:
    """Lint batch-script-examples when present and write JSON summary."""
    parser = argparse.ArgumentParser(description="Lint batch-script-examples corpus.")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=_CORPUS_DIR,
        help="Path to batch-script-examples directory",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_DEFAULT_REPORT,
        help="Output JSON report path",
    )
    parser.add_argument(
        "--check-baseline",
        type=Path,
        nargs="?",
        const=_DEFAULT_BASELINE,
        default=None,
        help="Compare live results to local baseline JSON (default: tests/fixtures/corpus-baseline.json; generate with generate_corpus_baseline.py)",
    )
    args = parser.parse_args()
    corpus_dir = cast(Path, args.corpus).resolve()
    if not corpus_dir.is_dir():
        print(f"Corpus directory not found: {corpus_dir}", file=sys.stderr)
        raise SystemExit(0)

    if args.check_baseline is not None:
        baseline_path = cast(Path, args.check_baseline).resolve()
        if not baseline_path.is_file():
            print(f"Baseline file not found: {baseline_path}", file=sys.stderr)
            raise SystemExit(1)
        diffs = check_baseline(corpus_dir, baseline_path)
        if diffs:
            print("Baseline drift detected:", file=sys.stderr)
            for diff in diffs:
                print(f"  {diff}", file=sys.stderr)
            raise SystemExit(1)
        print(f"Baseline matches: {baseline_path}")
        raise SystemExit(0)

    report = _lint_corpus(corpus_dir)
    report_path = cast(Path, args.report)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Files: {report['file_count']}, issues: {report['total_issues']}")
    if report["errors"]:
        print(f"Lint errors: {len(report['errors'])}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
