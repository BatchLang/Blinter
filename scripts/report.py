#!/usr/bin/env python3
"""Aggregate benchmark.py JSON results into a markdown report and a CSV.

Standard library only: the report job runs this file with a plain Python
install. Dates are timezone-aware UTC.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
import csv
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import sys
from typing import TypedDict

_LOG = logging.getLogger("scripts.report")
WORKLOADS: tuple[str, ...] = ("version", "small", "large", "tree")
_EMPTY = "\u2013"


class BenchRow(TypedDict):
    """One installed command on one platform."""

    platform: str
    py: str
    impl: str
    command: str
    mode: str
    blinter: str
    median: dict[str, float | None]
    cold: float | None
    warm: float | None
    first: float | None


class Failure(TypedDict):
    """One install, launch, or workload failure."""

    platform: str
    python: str
    impl: str
    error: str


def _configure_logging() -> None:
    """Attach one stderr handler when the process has not configured logging."""
    if _LOG.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False


def fmt(ms: float | None) -> str:
    """Format milliseconds for a markdown cell."""
    if ms is None:
        return _EMPTY
    if ms >= 100:
        return f"{ms:,.0f}"
    return f"{ms:.1f}"


def _mapping(value: object, label: str) -> dict[str, object]:
    """Return ``value`` when it is a string-keyed JSON object."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    mapped: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} has a non-string key")
        mapped[key] = item
    return mapped


def _text(value: object, label: str) -> str:
    """Return ``value`` when it is a non-empty string."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_float(value: object, label: str) -> float | None:
    """Return a finite float, or None when the JSON value is null."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number or null")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _optional_text(value: object, default: str) -> str:
    """Return a string value, or ``default`` when the field is missing or blank."""
    if not isinstance(value, str) or not value:
        return default
    return value


def _medians(value: object) -> dict[str, float | None]:
    """Return the median for each known workload. Missing workloads are None."""
    mapping = {} if value is None else _mapping(value, "workloads")
    medians: dict[str, float | None] = {}
    for name in WORKLOADS:
        stats = mapping.get(name)
        if stats is None:
            medians[name] = None
            continue
        stat_map = _mapping(stats, f"workloads.{name}")
        medians[name] = _optional_float(
            stat_map.get("median"),
            f"workloads.{name}.median",
        )
    return medians


def _row_from_result(
    result: dict[str, object],
    platform: str,
    python: str,
    mode: str,
) -> BenchRow:
    """Convert one JSON result object into a table row."""
    return {
        "platform": platform,
        "py": python,
        "impl": _text(result.get("impl"), "result.impl"),
        "command": _text(result.get("command"), "result.command"),
        "mode": mode,
        "blinter": _optional_text(result.get("blinter_version"), "?"),
        "median": _medians(result.get("workloads")),
        "cold": _optional_float(result.get("install_cold_ms"), "install_cold_ms"),
        "warm": _optional_float(result.get("install_warm_ms"), "install_warm_ms"),
        "first": _optional_float(result.get("first_run_ms"), "first_run_ms"),
    }


def _append_result_failures(
    failures: list[Failure],
    result: Mapping[str, object],
    platform: str,
    python: str,
) -> None:
    """Record per-workload errors stored on a result object."""
    raw = result.get("errors")
    if raw is None:
        return
    mapping = _mapping(raw, "result.errors")
    impl = _optional_text(result.get("impl"), "result")
    command = _optional_text(result.get("command"), "")
    label = f"{impl} / {command}" if command else impl
    for key, message in mapping.items():
        if not isinstance(message, str):
            raise ValueError(f"result.errors.{key} must be a string")
        failures.append(
            {
                "platform": platform,
                "python": python,
                "impl": f"{label} ({key})",
                "error": message,
            }
        )


def _append_top_failures(
    failures: list[Failure],
    raw: object,
    platform: str,
    python: str,
    source: Path,
) -> None:
    """Record install and launch errors from the top-level errors array."""
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ValueError(f"{source} errors must be a list")
    for index, item in enumerate(raw):
        mapping = _mapping(item, f"{source.name} errors[{index}]")
        failures.append(
            {
                "platform": platform,
                "python": python,
                "impl": _text(
                    mapping.get("impl"), f"{source.name} errors[{index}].impl"
                ),
                "error": _text(
                    mapping.get("error"),
                    f"{source.name} errors[{index}].error",
                ),
            }
        )


def _load_file(path: Path) -> tuple[list[BenchRow], list[Failure], dict[str, object]]:
    """Load one benchmark JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ValueError(f"{path} is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not JSON: {exc}") from exc
    data = _mapping(payload, path.name)
    meta = _mapping(data.get("meta"), f"{path.name} meta")
    platform = _platform(meta)
    python = _python_label(meta)
    mode = _text(meta.get("mode"), f"{path.name} meta.mode")
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise ValueError(f"{path.name} results must be a list")
    rows: list[BenchRow] = []
    failures: list[Failure] = []
    for index, item in enumerate(raw_results):
        result = _mapping(item, f"{path.name} results[{index}]")
        rows.append(_row_from_result(result, platform, python, mode))
        _append_result_failures(failures, result, platform, python)
    _append_top_failures(failures, data.get("errors"), platform, python, path)
    _LOG.info("loaded %s results from %s", len(rows), path)
    return rows, failures, meta


def _platform(meta: Mapping[str, object]) -> str:
    """Return the platform label, including the machine when it was recorded."""
    label = _text(meta.get("label"), "meta.label")
    machine = meta.get("machine")
    machine_text = machine if isinstance(machine, str) and machine else "?"
    return f"{label} ({machine_text})"


def _python_label(meta: Mapping[str, object]) -> str:
    """Return the Python matrix label, or an en dash for the standalone exe."""
    return _optional_text(meta.get("python_label"), _EMPTY)


def _load(
    folder: Path,
) -> tuple[list[BenchRow], list[Failure], list[dict[str, object]]]:
    """Load every JSON result under ``folder``."""
    rows: list[BenchRow] = []
    failures: list[Failure] = []
    metas: list[dict[str, object]] = []
    paths = sorted(folder.rglob("*.json"))
    _LOG.info("found %s JSON files in %s", len(paths), folder)
    for path in paths:
        file_rows, file_failures, meta = _load_file(path)
        rows.extend(file_rows)
        failures.extend(file_failures)
        metas.append(meta)
    return rows, failures, metas


def _name(row: BenchRow) -> str:
    """Return the install method and command, which is the ranking identity."""
    return f"{row['impl']} · {row['command']}"


def _positive(value: float | None) -> float | None:
    """Return ``value`` when it is a positive finite number."""
    if value is None or value <= 0:
        return None
    return value


def _best_medians(rows: Sequence[BenchRow]) -> dict[str, float]:
    """Return the fastest positive median for each workload."""
    best: dict[str, float] = {}
    for name in WORKLOADS:
        values = [
            median
            for row in rows
            if (median := _positive(row["median"][name])) is not None
        ]
        best[name] = min(values) if values else 0.0
    return best


def _score(row: BenchRow, best: Mapping[str, float]) -> float | None:
    """Return the geometric-mean slowdown versus the fastest median of each workload."""
    ratios: list[float] = []
    for name in WORKLOADS:
        value = _positive(row["median"][name])
        baseline = best[name]
        if value is None or baseline <= 0:
            return None
        ratios.append(value / baseline)
    if not ratios:
        return None
    return math.exp(sum(math.log(ratio) for ratio in ratios) / len(ratios))


def _partition(
    rows: Sequence[BenchRow],
) -> tuple[list[tuple[BenchRow, float]], list[BenchRow]]:
    """Split rows into scored rows (fastest first) and rows that cannot be scored."""
    best = _best_medians(rows)
    scored: list[tuple[BenchRow, float]] = []
    unscored: list[BenchRow] = []
    for row in rows:
        score = _score(row, best)
        if score is None:
            unscored.append(row)
            continue
        scored.append((row, score))
    scored.sort(key=lambda item: item[1])
    unscored.sort(key=lambda row: (row["impl"], row["command"], row["py"]))
    return scored, unscored


def _fastest(
    rows: Sequence[BenchRow],
    value_of: Callable[[BenchRow], float | None],
) -> BenchRow | None:
    """Return the row with the smallest present value."""
    found: list[tuple[float, BenchRow]] = []
    for row in rows:
        value = value_of(row)
        if value is not None:
            found.append((value, row))
    if not found:
        return None
    found.sort(key=lambda item: item[0])
    return found[0][1]


def _table(header: Sequence[str], body: Sequence[Sequence[object]]) -> str:
    """Return a GitHub-flavored markdown table."""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _column in header) + "|",
    ]
    for row in body:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _timed(row: BenchRow | None, value: float | None, label: str) -> str:
    """Return ``label (py x) – time`` or an en dash when the row is missing."""
    if row is None or value is None:
        return _EMPTY
    return f"{label} (py {row['py']}) {_EMPTY} {fmt(value)}"


def _headline_row(platform: str, rows: Sequence[BenchRow]) -> list[str] | None:
    """Return the fastest-overall summary for one platform, when any row scores."""
    ranked, _unscored = _partition(rows)
    if not ranked:
        return None
    winner = ranked[0][0]
    startup = _fastest(rows, lambda row: row["median"]["version"])
    cold = _fastest(rows, lambda row: row["cold"])
    warm = _fastest(rows, lambda row: row["warm"])
    startup_value = None if startup is None else startup["median"]["version"]
    cold_value = None if cold is None else cold["cold"]
    warm_value = None if warm is None else warm["warm"]
    return [
        platform,
        f"**{_name(winner)}** (py {winner['py']})",
        _timed(startup, startup_value, _name(startup) if startup else ""),
        _timed(cold, cold_value, cold["impl"] if cold else ""),
        _timed(warm, warm_value, warm["impl"] if warm else ""),
    ]


def _detail_body(rows: Sequence[BenchRow]) -> list[list[object]]:
    """Return the per-command ranking, including rows that could not be scored."""
    ranked, unscored = _partition(rows)
    body: list[list[object]] = []
    ordered: list[tuple[BenchRow, str]] = [
        (row, f"{score:.2f}×") for row, score in ranked
    ]
    ordered.extend((row, _EMPTY) for row in unscored)
    for index, (row, score) in enumerate(ordered, start=1):
        body.append(
            [
                index,
                row["impl"],
                row["command"],
                row["py"],
                *(fmt(row["median"][name]) for name in WORKLOADS),
                fmt(row["cold"]),
                fmt(row["warm"]),
                fmt(row["first"]),
                score,
            ]
        )
    return body


def _python_groups(rows: Sequence[BenchRow]) -> list[list[BenchRow]]:
    """Group Python legs, and let the exe compete in every group on its platform."""
    exe_rows = [row for row in rows if row["mode"] == "exe"]
    versions = sorted({row["py"] for row in rows if row["mode"] == "python"})
    if not versions:
        return [exe_rows] if exe_rows else []
    return [
        [row for row in rows if row["mode"] == "python" and row["py"] == version]
        + exe_rows
        for version in versions
    ]


def _wins(rows: Sequence[BenchRow]) -> tuple[list[tuple[str, int]], int]:
    """Count how often each command is the fastest in a platform and Python group."""
    wins: Counter[str] = Counter()
    by_platform: dict[str, list[BenchRow]] = defaultdict(list)
    for row in rows:
        by_platform[row["platform"]].append(row)
    for group_rows in by_platform.values():
        for group in _python_groups(group_rows):
            ranked, _unscored = _partition(group)
            if ranked:
                wins[_name(ranked[0][0])] += 1
    return wins.most_common(), sum(wins.values())


def _failure_item(failure: Failure) -> str:
    """Return one markdown bullet for a failure, with the message kept on one line."""
    first = failure["error"].strip().splitlines()
    summary = first[0][:200] if first else "no details"
    safe = summary.replace("`", "'")
    platform = failure["platform"]
    return (
        f"- **{platform} py{failure['python']} {_EMPTY} {failure['impl']}**: `{safe}`"
    )


def _summary_line(
    rows: Sequence[BenchRow], metas: Sequence[Mapping[str, object]]
) -> str:
    """Return the italic summary under the report title."""
    versions = sorted({row["blinter"] for row in rows if row["blinter"]})
    uv_versions = sorted(
        {uv for meta in metas if isinstance((uv := meta.get("uv_version")), str) and uv}
    )
    uv_text = ", ".join(uv_versions) if uv_versions else "uv not recorded"
    return (
        f"_{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · "
        f"Blinter {', '.join(versions) or '?'} · {uv_text} · "
        f"{len(metas)} legs · timings are medians in ms_"
    )


def _by_platform(rows: Sequence[BenchRow]) -> dict[str, list[BenchRow]]:
    """Group rows by their platform label."""
    grouped: dict[str, list[BenchRow]] = defaultdict(list)
    for row in rows:
        grouped[row["platform"]].append(row)
    return grouped


def _headline_table(grouped: Mapping[str, Sequence[BenchRow]]) -> str:
    """Return the fastest-per-platform table."""
    headline = [
        cells
        for platform, group in sorted(grouped.items())
        if (cells := _headline_row(platform, group)) is not None
    ]
    return _table(
        [
            "Platform",
            "Fastest overall (lint speed)",
            "Fastest startup (--version)",
            "Fastest cold install",
            "Fastest warm install",
        ],
        headline,
    )


def _detail_sections(grouped: Mapping[str, Sequence[BenchRow]]) -> list[str]:
    """Return one ranked table per platform."""
    sections: list[str] = []
    for platform, group in sorted(grouped.items()):
        sections.extend([f"## {platform}", ""])
        sections.append(
            _table(
                [
                    "#",
                    "Install",
                    "Command",
                    "Best py",
                    "startup",
                    "small",
                    "large",
                    "tree",
                    "install cold",
                    "install warm",
                    "1st run",
                    "score",
                ],
                _detail_body(group),
            )
        )
        sections.append("")
    return sections


def _win_section(rows: Sequence[BenchRow]) -> list[str]:
    """Return the win-count section, or nothing when no group could be scored."""
    win_rows, total = _wins(rows)
    if not total:
        return []
    return [
        f"## Win count ({total} platform × Python groups)",
        "",
        _table(["Implementation", "Wins"], win_rows),
        "",
    ]


def _failure_section(failures: Sequence[Failure]) -> list[str]:
    """Return the failure section, or nothing when every leg succeeded."""
    if not failures:
        return []
    return ["## Failures", "", *(_failure_item(failure) for failure in failures), ""]


def _render(
    rows: Sequence[BenchRow],
    failures: Sequence[Failure],
    metas: Sequence[Mapping[str, object]],
) -> str:
    """Return the full markdown report."""
    lines = ["# Blinter install & run benchmark", ""]
    if not rows:
        lines.append("No benchmark results were produced. Check the failed jobs.")
        lines.append("")
        return "\n".join(lines) + "\n"
    grouped = _by_platform(rows)
    lines.extend(
        [
            _summary_line(rows, metas),
            "",
            "## Fastest per platform",
            "",
            _headline_table(grouped),
            "",
            "_Fastest overall = lowest geometric-mean slowdown vs the best positive "
            "result per workload (version, small file, 1500-line file, 15-file folder). "
            "Cold install = empty package cache; for uvx it is the first run, for the "
            "exe it is download + extract._",
            "",
        ]
    )
    lines.extend(_detail_sections(grouped))
    lines.extend(_win_section(rows))
    lines.extend(_failure_section(failures))
    lines.extend(
        [
            "---",
            "_GitHub-hosted runners are shared VMs, so absolute numbers are noisy: "
            "compare implementations within one platform, never across platforms. "
            "Runs are interleaved round-robin to spread drift evenly._",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[BenchRow]) -> None:
    """Write every row, including timings that were not ranked."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "platform",
                "python",
                "install",
                "command",
                "blinter",
                "install_cold_ms",
                "install_warm_ms",
                "first_run_ms",
                *[f"{name}_median_ms" for name in WORKLOADS],
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["platform"],
                    row["py"],
                    row["impl"],
                    row["command"],
                    row["blinter"],
                    row["cold"],
                    row["warm"],
                    row["first"],
                    *[row["median"][name] for name in WORKLOADS],
                ]
            )
    _LOG.info("wrote %s", path)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the results directory and the output directory."""
    parser = argparse.ArgumentParser(
        description="Aggregate benchmark JSON into a markdown report and CSV."
    )
    parser.add_argument("results", help="Directory that contains benchmark JSON files")
    parser.add_argument(
        "output", help="Directory to write report.md and all-results.csv"
    )
    return parser.parse_args(None if argv is None else list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """Load benchmark JSON and write report.md plus all-results.csv."""
    _configure_logging()
    args = _parse_args(argv)
    source = Path(str(args.results))
    destination = Path(str(args.output))
    if not source.is_dir():
        _LOG.error("results directory does not exist: %s", source)
        return 1
    try:
        rows, failures, metas = _load(source)
    except (OSError, UnicodeError, ValueError) as exc:
        _LOG.error("could not read benchmark results from %s: %s", source, exc)
        return 1
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / "report.md"
    report_path.write_text(
        _render(rows, failures, metas),
        encoding="utf-8",
        newline="\n",
    )
    _write_csv(destination / "all-results.csv", rows)
    _LOG.info("wrote %s (%s rows)", report_path, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
