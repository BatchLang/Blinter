"""Tests for scripts/publish_github_release.py."""

from pathlib import Path
import subprocess
from typing import Any

import pytest
from pytest_mock import MockerFixture

from scripts.publish_github_release import main, publish_github_release, release_tag

_SHA = "a" * 40
_VERSION = "1.2.3"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "CI.yml"


def _completed(
    code: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Return a finished ``gh`` process."""
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=code,
        stdout=stdout,
        stderr=stderr,
    )


def _prepare(tmp_path: Path, version: str = _VERSION) -> tuple[Path, Path]:
    """Create notes and both Windows zips under ``tmp_path``."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    notes = tmp_path / "release-notes.md"
    notes.write_text("notes\n", encoding="utf-8")
    for arch in ("x64", "arm64"):
        asset = build_dir / f"Blinter-v{version}-Windows-{arch}.zip"
        asset.write_bytes(b"zip")
    return notes, build_dir


def _argv(mock_call: Any) -> list[str]:
    """Return the command list from a ``subprocess.run`` call."""
    command = mock_call.args[0]
    assert isinstance(command, list)
    parts: list[str] = []
    for part in command:
        assert isinstance(part, str)
        parts.append(part)
    return parts


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authenticate the publisher without reading a real token."""
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


class TestPublishGithubRelease:
    """Create and update paths for the GitHub Release publisher."""

    def test_release_tag_rejects_empty_version(self) -> None:
        """An empty version never becomes a tag."""
        with pytest.raises(SystemExit, match="VERSION is empty"):
            release_tag("")

    def test_release_tag_rejects_path_characters(self) -> None:
        """Version text cannot change the asset directory."""
        with pytest.raises(SystemExit, match="unexpected characters"):
            release_tag("1.2.3/../evil")

    def test_missing_notes_skip_gh(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A missing notes file fails before ``gh`` is invoked."""
        notes, build_dir = _prepare(tmp_path)
        notes.unlink()
        run = mocker.patch("scripts.publish_github_release.subprocess.run")
        with pytest.raises(SystemExit, match="Release notes file not found"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        run.assert_not_called()

    def test_missing_asset_skips_gh(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A missing zip fails before ``gh`` is invoked."""
        notes, build_dir = _prepare(tmp_path)
        next(build_dir.glob("*-Windows-arm64.zip")).unlink()
        run = mocker.patch("scripts.publish_github_release.subprocess.run")
        with pytest.raises(SystemExit, match="Release asset not found"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        run.assert_not_called()

    def test_missing_token_skips_gh(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Publishing requires ``GH_TOKEN`` or ``GITHUB_TOKEN``."""
        notes, build_dir = _prepare(tmp_path)
        monkeypatch.delenv("GH_TOKEN")
        run = mocker.patch("scripts.publish_github_release.subprocess.run")
        with pytest.raises(SystemExit, match="GH_TOKEN or GITHUB_TOKEN"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        run.assert_not_called()

    def test_github_token_is_accepted(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``GITHUB_TOKEN`` alone is enough for ``gh``."""
        notes, build_dir = _prepare(tmp_path)
        monkeypatch.delenv("GH_TOKEN")
        monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0, stdout="https://example.invalid/releases/tag/v1.2.3\n"),
            ],
        )
        publish_github_release(_VERSION, notes, _SHA, build_dir)

    def test_create_pins_the_built_commit(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A new release is created at ``GITHUB_SHA`` with both zips."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0, stdout="https://example.invalid/releases/tag/v1.2.3\n"),
            ],
        )
        publish_github_release(_VERSION, notes, _SHA, build_dir)
        view, create = (_argv(call) for call in run.call_args_list)
        assert view == ["gh", "release", "view", "v1.2.3", "--json", "tagName"]
        assert create == [
            "gh",
            "release",
            "create",
            "v1.2.3",
            str(build_dir / "Blinter-v1.2.3-Windows-x64.zip"),
            str(build_dir / "Blinter-v1.2.3-Windows-arm64.zip"),
            "--title",
            "v1.2.3",
            "--notes-file",
            str(notes),
            "--target",
            _SHA,
        ]
        assert run.call_args_list[1].kwargs["timeout"] > (
            run.call_args_list[0].kwargs["timeout"]
        )

    def test_update_replaces_same_named_assets(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """An existing release is edited and uploaded with ``--clobber``."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(0, stdout='{"tagName":"v1.2.3"}\n'),
                _completed(0),
                _completed(0),
            ],
        )
        publish_github_release(_VERSION, notes, "", build_dir)
        view, edit, upload = (_argv(call) for call in run.call_args_list)
        assert view[1:4] == ["release", "view", "v1.2.3"]
        assert edit == [
            "gh",
            "release",
            "edit",
            "v1.2.3",
            "--title",
            "v1.2.3",
            "--notes-file",
            str(notes),
        ]
        assert upload == [
            "gh",
            "release",
            "upload",
            "v1.2.3",
            str(build_dir / "Blinter-v1.2.3-Windows-x64.zip"),
            str(build_dir / "Blinter-v1.2.3-Windows-arm64.zip"),
            "--clobber",
        ]
        assert "--target" not in edit
        assert "--target" not in upload

    def test_edit_failure_skips_upload(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A failed edit does not delete existing assets via ``--clobber``."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(0, stdout='{"tagName":"v1.2.3"}\n'),
                _completed(1, stderr="HTTP 422: Validation Failed\n"),
            ],
        )
        with pytest.raises(SystemExit, match="Updating release v1.2.3 failed"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        assert run.call_count == 2

    def test_lookup_error_does_not_create(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Authentication and API failures are not treated as a missing release."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            return_value=_completed(1, stderr="HTTP 401: Bad credentials\n"),
        )
        with pytest.raises(SystemExit, match="Could not look up release v1.2.3"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)
        assert run.call_count == 1

    def test_create_requires_commit_sha(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Creating a release refuses an empty or non-commit target."""
        notes, build_dir = _prepare(tmp_path)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            return_value=_completed(1, stderr="release not found\n"),
        )
        with pytest.raises(SystemExit, match="GITHUB_SHA"):
            publish_github_release(_VERSION, notes, "", build_dir)
        assert run.call_count == 1

    def test_prerelease_version_uses_versioned_asset_names(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """PEP 440 pre-release labels stay inside the zip filename."""
        version = "1.2.3rc1"
        notes, build_dir = _prepare(tmp_path, version)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0),
            ],
        )
        publish_github_release(version, notes, _SHA, build_dir)
        create = _argv(run.call_args_list[1])
        assert "v1.2.3rc1" in create
        assert str(build_dir / "Blinter-v1.2.3rc1-Windows-x64.zip") in create

    def test_timeout_exits(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A hung ``gh`` process fails the publish step."""
        notes, build_dir = _prepare(tmp_path)
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=120),
        )
        with pytest.raises(SystemExit, match="timed out"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)

    def test_missing_gh_exits(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """A missing ``gh`` binary fails before a release is published."""
        notes, build_dir = _prepare(tmp_path)
        mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=FileNotFoundError(2, "gh"),
        )
        with pytest.raises(SystemExit, match="Could not run gh"):
            publish_github_release(_VERSION, notes, _SHA, build_dir)

    def test_main_reads_the_environment(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The CLI reads version, notes, and the built commit from the environment."""
        notes, _build_dir = _prepare(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("VERSION", _VERSION)
        monkeypatch.setenv("NOTES_FILE", str(notes))
        monkeypatch.setenv("GITHUB_SHA", _SHA)
        run = mocker.patch(
            "scripts.publish_github_release.subprocess.run",
            side_effect=[
                _completed(1, stderr="release not found\n"),
                _completed(0),
            ],
        )
        main([])
        create = _argv(run.call_args_list[1])
        assert create[3] == "v1.2.3"
        assert create[-1] == _SHA

    def test_main_help_and_unknown_args(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Help prints usage and any other argument is an error."""
        main(["--help"])
        assert "VERSION" in capsys.readouterr().out
        with pytest.raises(SystemExit, match="2"):
            main(["--version"])

    def test_workflow_calls_the_python_publisher(self) -> None:
        """The release job invokes the script instead of an inline shell step."""
        workflow = _WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("  create-release:", maxsplit=1)[1].split(
            "  publish-pypi:",
            maxsplit=1,
        )[0]
        assert "python scripts/publish_github_release.py" in job
        assert "GH_TOKEN:" in job
        assert "VERSION:" in job
        assert "NOTES_FILE:" in job
        assert "ncipollo" not in workflow
        assert "set -euo pipefail" not in job
