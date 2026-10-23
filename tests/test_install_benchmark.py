"""Tests for the install benchmark, its report, and the benchmark workflow."""

from __future__ import annotations

from email.message import Message
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

from hypothesis import given, settings, strategies as st
import pytest
import yaml

from scripts import benchmark, benchmark_release, report
from scripts.benchmark import (
    _budget_exhausted,
    _measure_workloads,
    _new_target,
    _package_spec,
    _probe_target,
    _time_calls,
    _version_from_env,
)
from scripts.benchmark_release import (
    _AllowlistRedirectHandler,
    _digest_equal,
    _require_download_url,
    _require_sha256,
    _runner_arch,
    _sha256_file,
)

pytestmark = pytest.mark.timeout(30)

_ROOT = Path(__file__).resolve().parents[1]


def test_workload_names_match() -> None:
    """The benchmark and the report agree on workload order."""
    assert list(benchmark.WORKLOADS) == list(report.WORKLOADS)


def test_batch_text_is_crlf_and_corpus_has_three_workloads(tmp_path: Path) -> None:
    """Synthetic batch files use CRLF and the corpus has the expected shape."""
    text = benchmark.batch_text(30, 1)
    assert text.startswith("@echo off\r\n")
    assert text.endswith("exit /b 1\r\n")
    assert "\n" not in text.replace("\r\n", "")
    root = benchmark.make_corpus(tmp_path / "corpus")
    assert (root / "small.bat").read_bytes().startswith(b"@echo off\r\n")
    assert (root / "large.bat").stat().st_size > (root / "small.bat").stat().st_size
    assert len(list((root / "tree").glob("*.bat"))) == 15


def test_stats_nearest_rank_p90() -> None:
    """p90 uses nearest rank, and a single sample has no spread."""
    summary = benchmark.stats([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert summary["n"] == 10
    assert summary["min"] == 1
    assert summary["max"] == 10
    assert summary["median"] == 5.5
    assert summary["p90"] == 9
    single = benchmark.stats([4.0])
    assert single["stdev"] == 0.0
    assert single["p90"] == 4.0
    with pytest.raises(ValueError, match="empty"):
        benchmark.stats([])


@given(
    st.lists(
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        min_size=1,
        max_size=40,
    )
)
@settings(max_examples=25, deadline=None)
def test_stats_stay_inside_the_sample(samples: list[float]) -> None:
    """Every summary value stays inside the sample's range."""
    summary = benchmark.stats(samples)
    assert summary["n"] == len(samples)
    assert summary["min"] <= summary["p90"] <= summary["max"]
    assert summary["min"] <= summary["median"] <= summary["max"]
    assert summary["min"] <= summary["mean"] <= summary["max"]
    assert summary["stdev"] >= 0


def test_make_env_drops_tokens_and_interpreter_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Child processes do not inherit credentials or another interpreter."""
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "injected")
    monkeypatch.setenv("VIRTUAL_ENV", "injected")
    monkeypatch.setenv("UV_PYTHON", "injected")
    env = benchmark.make_env(PIP_CACHE_DIR="cache")
    assert "GITHUB_TOKEN" not in env
    assert "GH_TOKEN" not in env
    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
    assert "UV_PYTHON" not in env
    assert env["PIP_CACHE_DIR"] == "cache"
    assert env["UV_PYTHON_DOWNLOADS"] == "never"


def test_timed_install_creates_its_working_directory(tmp_path: Path) -> None:
    """Install commands start in the family directory, so that directory must exist."""
    workspace = tmp_path / "pip"
    marker = workspace / "cwd.txt"
    elapsed = _time_calls(
        [
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('cwd.txt').write_text('ok', encoding='utf-8')",
            ]
        ],
        benchmark.make_env(),
        workspace,
    )
    assert elapsed >= 0
    assert marker.read_text(encoding="utf-8") == "ok"


def test_version_and_package_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """The version env var accepts a release number and rejects shell syntax."""
    monkeypatch.setenv("BLINTER_VERSION", "v1.2.3")
    assert _version_from_env() == "1.2.3"
    assert _package_spec("1.2.3") == "Blinter==1.2.3"
    assert _package_spec("") == "Blinter"
    monkeypatch.setenv("BLINTER_VERSION", "1.2.3 && calc")
    with pytest.raises(SystemExit, match="BLINTER_VERSION"):
        _version_from_env()


def test_release_url_and_runner_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Release lookup and architecture follow the installer naming."""
    assert benchmark_release.release_api_url("") == (
        "https://api.github.com/repos/BatchLang/Blinter/releases/latest"
    )
    assert benchmark_release.release_api_url("1.2.3").endswith("/releases/tags/v1.2.3")
    monkeypatch.setenv("RUNNER_ARCH", "ARM64")
    assert _runner_arch() == "arm64"
    monkeypatch.delenv("RUNNER_ARCH")
    monkeypatch.setattr("scripts.benchmark_release.platform.machine", lambda: "x86_64")
    assert _runner_arch() == "x64"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/BatchLang/Blinter/releases/latest",
        "https://evil.example/payload",
        "https://github.com.evil.com/payload",
        "https://user:pass@github.com/payload",
        "https://github.com:444/payload",
        "https://github.com/payload\n",
    ],
)
def test_download_url_rejects_untrusted_targets(url: str) -> None:
    """Downloads stay on GitHub's HTTPS hosts, with no credentials or odd ports."""
    with pytest.raises(RuntimeError, match="allowlisted"):
        _require_download_url(url)


def test_download_url_accepts_release_hosts() -> None:
    """The API and the public release download host are allowlisted."""
    api = "https://api.github.com/repos/BatchLang/Blinter/releases/latest"
    asset = "https://github.com/BatchLang/Blinter/releases/download/v1.2.3/file.zip"
    cdn = "https://release-assets.githubusercontent.com/github-production-release-asset/file"
    assert _require_download_url(api) == api
    assert _require_download_url(asset) == asset
    assert _require_download_url(cdn) == cdn


def test_redirect_handler_rejects_off_host() -> None:
    """A redirect off the allowlist is refused before it is followed."""
    handler = _AllowlistRedirectHandler()
    request = urllib.request.Request(
        "https://api.github.com/repos/BatchLang/Blinter/releases/latest"
    )
    with pytest.raises(RuntimeError, match="allowlisted"):
        handler.redirect_request(
            request,
            BytesIO(),
            302,
            "Found",
            Message(),
            "https://evil.example/payload",
        )


def test_select_asset_prefers_the_installer_name() -> None:
    """The current zip name wins, and a legacy x64 zip is only a fallback."""
    tag = "v1.2.3"
    x64 = {"name": "Blinter-v1.2.3-x64.zip"}
    arm = {"name": "Blinter-v1.2.3-arm64.zip"}
    legacy = {"name": "Blinter-v1.0.0.zip"}
    assert benchmark_release.select_asset([arm, x64], tag, "x64") == x64
    assert benchmark_release.select_asset([x64, arm], tag, "arm64") == arm
    assert benchmark_release.select_asset([legacy], "v1.0.0", "x64") == legacy
    with pytest.raises(RuntimeError, match="arm64"):
        benchmark_release.select_asset([legacy], "v1.0.0", "arm64")
    with pytest.raises(RuntimeError, match="multiple"):
        benchmark_release.select_asset([x64, dict(x64)], tag, "x64")


def test_sha256_digest_is_required_and_checked(tmp_path: Path) -> None:
    """A release asset without a real sha256 digest is refused."""
    digest = hashlib.sha256(b"blinter").hexdigest()
    asset = {"name": "Blinter-v1.2.3-x64.zip", "digest": f"sha256:{digest}"}
    assert _require_sha256(asset) == digest
    with pytest.raises(RuntimeError, match="missing"):
        _require_sha256({"name": "Blinter-v1.2.3-x64.zip"})
    with pytest.raises(RuntimeError, match="invalid"):
        _require_sha256({"name": "x.zip", "digest": "sha256:abcd"})
    path = tmp_path / "blob"
    path.write_bytes(b"blinter")
    assert _sha256_file(path) == digest
    assert _digest_equal(digest, digest)
    assert not _digest_equal(digest, "0" * 64)


def test_extract_rejects_traversal_and_finds_the_installer_layout(
    tmp_path: Path,
) -> None:
    """Zip members cannot escape the destination, and the exe path is exact."""
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../evil.txt", "nope")
    with pytest.raises(RuntimeError, match="unsafe"):
        benchmark_release.extract_zip(bad, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()

    good = tmp_path / "Blinter-v1.2.3-x64.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("Blinter-v1.2.3-x64/blinter.exe", b"MZ")
    dest = tmp_path / "extracted"
    benchmark_release.extract_zip(good, dest)
    exe = benchmark_release.locate_exe(dest, good.name)
    assert exe.read_bytes() == b"MZ"
    with pytest.raises(RuntimeError, match="blinter.exe"):
        benchmark_release.locate_exe(dest, "Blinter-v9.9.9-x64.zip")


def test_budget_keeps_three_measured_rounds() -> None:
    """The budget can stop a workload only after three measured rounds."""
    assert (
        _budget_exhausted(2, warmup=0, started=0.0, budget=0.01, workload_name="large")
        is False
    )
    assert _budget_exhausted(
        3,
        warmup=0,
        started=0.0,
        budget=0.01,
        workload_name="large",
    )


def _installed(measure_first: bool) -> benchmark.FamilyResult:
    """Return a fake install family for one local command."""
    return {
        "times": [1.0],
        "env": benchmark.make_env(),
        "first": measure_first,
        "commands": {},
    }


def test_probe_and_measurements_accept_lint_exit_codes(tmp_path: Path) -> None:
    """Exit 0 and exit 1 are successful runs. Exit 2 drops the target."""
    ok = _new_target(
        "fake",
        "blinter",
        [sys.executable, "-c", "print('blinter 1.2.3')"],
        _installed(True),
    )
    assert _probe_target(ok, tmp_path) is None
    assert ok["version_output"] == "blinter 1.2.3"
    assert ok["first_run_ms"] is not None

    findings = _new_target(
        "fake",
        "blinter",
        [sys.executable, "-c", "raise SystemExit(1)"],
        _installed(False),
    )
    _measure_workloads([findings], tmp_path, runs=1, warmup=0, budget=30)
    assert not findings["errors"]
    assert len(findings["samples"]["version"]) == 1
    assert len(findings["samples"]["tree"]) == 1

    crashed = _new_target(
        "fake",
        "blinter",
        [sys.executable, "-c", "raise SystemExit(2)"],
        _installed(False),
    )
    _measure_workloads([crashed], tmp_path, runs=2, warmup=1, budget=30)
    assert "version" in crashed["errors"]
    assert crashed["samples"]["version"] == []
    assert crashed["samples"]["small"] == []


def _command(
    impl: str,
    command: str,
    median: float | dict[str, float | None],
) -> dict[str, object]:
    """Return one benchmark result object with default install timings."""
    if isinstance(median, dict):
        workloads: dict[str, object] = {
            name: None if value is None else {"median": value}
            for name, value in median.items()
        }
    else:
        workloads = {name: {"median": median} for name in report.WORKLOADS}
    return {
        "impl": impl,
        "command": command,
        "blinter_version": "1.2.3",
        "install_cold_ms": 1000.0,
        "install_warm_ms": 100.0,
        "first_run_ms": 20.0,
        "workloads": workloads,
        "errors": {},
    }


def _write_result(
    folder: Path,
    results: list[dict[str, object]],
    *,
    name: str = "result.json",
    errors: list[dict[str, str]] | None = None,
    meta: dict[str, object] | None = None,
) -> None:
    """Write one benchmark JSON file."""
    payload = {
        "meta": meta
        or {
            "mode": "python",
            "label": "windows-latest",
            "machine": "AMD64",
            "python_label": "3.14",
            "uv_version": "uv 0.9.0",
        },
        "results": results,
        "errors": errors or [],
    }
    (folder / name).write_text(json.dumps(payload), encoding="utf-8")


def test_report_ranks_geometric_mean_and_writes_csv(tmp_path: Path) -> None:
    """The fastest command scores 1, and a uniformly slower one scores its ratio."""
    source = tmp_path / "in"
    source.mkdir()
    _write_result(
        source,
        [
            _command("pip venv", "blinter", 10),
            _command("uv pip venv", "blinter", 20),
        ],
    )
    destination = tmp_path / "out"
    assert report.main([str(source), str(destination)]) == 0
    text = (destination / "report.md").read_text(encoding="utf-8")
    assert "1.00×" in text
    assert "2.00×" in text
    assert "**pip venv · blinter**" in text
    csv_text = (destination / "all-results.csv").read_text(encoding="utf-8")
    assert "uv pip venv" in csv_text
    assert "version_median_ms" in csv_text


def test_report_keeps_partial_rows_and_failures(tmp_path: Path) -> None:
    """A zero median is shown, and workload errors are listed."""
    source = tmp_path / "in"
    source.mkdir()
    partial = _command(
        "pip venv",
        "blinter",
        {"version": 0, "small": 10, "large": 10, "tree": 10},
    )
    partial["install_cold_ms"] = None
    partial["install_warm_ms"] = None
    partial["errors"] = {"large": "exit `2`: boom"}
    _write_result(
        source,
        [partial],
        errors=[{"impl": "uv tool install", "error": "resolver failed"}],
    )
    destination = tmp_path / "out"
    assert report.main([str(source), str(destination)]) == 0
    text = (destination / "report.md").read_text(encoding="utf-8")
    assert "uv tool install" in text
    assert "exit '2': boom" in text
    assert "Fastest per platform" in text


def test_report_lets_the_exe_compete_in_each_python_group(tmp_path: Path) -> None:
    """One exe result is ranked against every Python leg on the same platform."""
    source = tmp_path / "in"
    source.mkdir()
    exe_meta = {
        "mode": "exe",
        "label": "windows-latest",
        "machine": "AMD64",
        "python_label": "",
    }
    _write_result(source, [_command("pip venv", "blinter", 20)], name="py.json")
    _write_result(
        source,
        [_command("standalone exe", "blinter.exe (x64)", 10)],
        name="exe.json",
        meta=exe_meta,
    )
    destination = tmp_path / "out"
    assert report.main([str(source), str(destination)]) == 0
    text = (destination / "report.md").read_text(encoding="utf-8")
    assert "Win count (1 platform" in text
    assert "standalone exe · blinter.exe (x64)" in text


def test_report_rejects_missing_or_invalid_input(tmp_path: Path) -> None:
    """A missing directory or corrupt JSON fails instead of writing a partial report."""
    missing = tmp_path / "missing"
    assert report.main([str(missing), str(tmp_path / "out")]) == 1
    source = tmp_path / "in"
    source.mkdir()
    (source / "bad.json").write_text("{", encoding="utf-8")
    assert report.main([str(source), str(tmp_path / "bad-out")]) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    destination = tmp_path / "empty-out"
    assert report.main([str(empty), str(destination)]) == 0
    assert "No benchmark results" in (destination / "report.md").read_text(
        encoding="utf-8"
    )


def _workflow(name: str) -> dict[str, object]:
    """Return a parsed workflow document."""
    loaded = yaml.safe_load(
        (_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


def _job(document: dict[str, object], name: str) -> dict[str, object]:
    """Return one job mapping."""
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[name]
    assert isinstance(job, dict)
    return job


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    """Return a job's steps."""
    steps = job["steps"]
    assert isinstance(steps, list)
    assert steps
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _step_named(job: dict[str, object], name: str) -> dict[str, object]:
    """Return the step with this name."""
    matches = [step for step in _steps(job) if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_benchmark_script_imports_when_run_as_a_file() -> None:
    """CI runs this file directly, so the scripts package must still import."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "benchmark.py"), "--help"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Benchmark Blinter" in result.stdout


def test_benchmark_workflow_checks_out_and_can_upload_artifacts() -> None:
    """Every job checks out first, and artifact upload is permitted."""
    document = _workflow("blinter-benchmark.yml")
    permissions = document["permissions"]
    assert isinstance(permissions, dict)
    assert permissions["contents"] == "read"
    assert permissions["actions"] == "write"
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    for job in jobs.values():
        assert isinstance(job, dict)
        first = _steps(job)[0]
        uses = first["uses"]
        assert isinstance(uses, str)
        assert uses.startswith("actions/checkout@")
        with_values = first["with"]
        assert isinstance(with_values, dict)
        assert with_values["persist-credentials"] is False


def _matrix_values(job: dict[str, object], key: str) -> list[str]:
    """Return one axis of a job's strategy matrix as strings."""
    strategy = job["strategy"]
    assert isinstance(strategy, dict)
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict)
    values = matrix[key]
    assert isinstance(values, list)
    return [str(item) for item in values]


def test_benchmark_python_matrix_matches_ci() -> None:
    """The timed OS and Python matrix is the CI pytest matrix."""
    benchmark_doc = _workflow("blinter-benchmark.yml")
    ci_doc = _workflow("CI.yml")
    python_job = _job(benchmark_doc, "bench-python")
    ci_job = _job(ci_doc, "test-python")
    assert _matrix_values(python_job, "os") == _matrix_values(ci_job, "os")
    assert _matrix_values(python_job, "python") == _matrix_values(
        ci_job, "python-version"
    )
    runners = _matrix_values(python_job, "os")
    assert set(_matrix_values(_job(benchmark_doc, "bench-exe"), "os")) == {
        runner for runner in runners if runner.startswith("windows")
    }


def test_python_benchmark_disables_the_uv_cache() -> None:
    """A restored uv cache would make the cold install warm."""
    job = _job(_workflow("blinter-benchmark.yml"), "bench-python")
    options = _step_named(job, "Install uv and Python")["with"]
    assert isinstance(options, dict)
    assert options["python-version"] == "${{ matrix.python }}"
    assert options["enable-cache"] is False
    assert options["activate-environment"] is True


def test_exe_job_uses_the_token_and_report_merges_artifacts() -> None:
    """The exe download can authenticate, and the report reads every result."""
    document = _workflow("blinter-benchmark.yml")
    bench = _step_named(_job(document, "bench-exe"), "Benchmark standalone exe")
    env = bench["env"]
    assert isinstance(env, dict)
    assert "github.token" in str(env.get("GITHUB_TOKEN"))
    report_job = _job(document, "report")
    assert "cancelled" in str(report_job["if"])
    build = _step_named(report_job, "Build report")
    assert "scripts/report.py" in str(build["run"])
    download_with = _step_named(report_job, "Download results")["with"]
    assert isinstance(download_with, dict)
    assert download_with["merge-multiple"] is True
