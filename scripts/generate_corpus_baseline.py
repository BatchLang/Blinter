#!/usr/bin/env python3
"""Generate tests/fixtures/corpus-baseline.json from batch-script-examples."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.corpus_baseline import (  # noqa: E402  # pylint: disable=wrong-import-position
    _DEFAULT_BASELINE,
    _DEFAULT_CORPUS_DIR,
    build_corpus_baseline,
    save_baseline,
)


def main() -> None:
    """Write the committed corpus baseline snapshot."""
    parser = argparse.ArgumentParser(
        description="Generate corpus-baseline.json from batch-script-examples."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=_DEFAULT_CORPUS_DIR,
        help="Path to batch-script-examples directory",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_BASELINE,
        help="Output baseline JSON path",
    )
    args = parser.parse_args()
    corpus_dir = cast(Path, args.corpus).resolve()
    if not corpus_dir.is_dir():
        print(f"Corpus directory not found: {corpus_dir}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Linting {corpus_dir} (default + follow-calls)...")
    baseline = build_corpus_baseline(corpus_dir)
    out_path = cast(Path, args.out)
    save_baseline(baseline, out_path)
    default_total = sum(
        entry["total"] for entry in baseline["modes"]["default"]["files"].values()
    )
    follow_total = sum(
        entry["total"] for entry in baseline["modes"]["follow_calls"]["files"].values()
    )
    print(f"Wrote {out_path}")
    print(f"Files: {baseline['file_count']}")
    print(f"Default issues: {default_total}, follow-calls issues: {follow_total}")


if __name__ == "__main__":
    main()
