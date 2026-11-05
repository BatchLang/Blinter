#!/usr/bin/env python3
"""Build the benchmark report and append it to the GitHub step summary."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger("blinter.publish_benchmark_summary")
_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    """Run scripts/report.py and append report.md when GITHUB_STEP_SUMMARY is set."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(argv) != 3:
        logger.error("usage: publish_benchmark_summary.py RESULTS_DIR REPORT_DIR")
        return 2
    results_dir, report_dir = argv[1], argv[2]
    command = [sys.executable, "scripts/report.py", results_dir, report_dir]
    logger.info("Running %s", " ".join(command))
    completed = subprocess.run(command, cwd=_ROOT, check=False)
    if completed.returncode != 0:
        logger.error("report.py exited %s", completed.returncode)
        return completed.returncode
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    report_path = _ROOT / report_dir / "report.md"
    if not summary_path:
        logger.info("GITHUB_STEP_SUMMARY is unset; leaving %s in place", report_path)
        return 0
    if not report_path.is_file():
        logger.error("Benchmark report is missing: %s", report_path)
        return 1
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(report_path.read_text(encoding="utf-8"))
    logger.info("Appended %s to the step summary", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
