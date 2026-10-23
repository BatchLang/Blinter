"""Download, verify, and extract Blinter release archives.

Standard library only, same constraint as scripts/benchmark.py.
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import hmac
from http.client import HTTPMessage
import json
import logging
import os
from pathlib import Path
import platform
from typing import IO
import urllib.error
import urllib.parse
import urllib.request
import zipfile

_LOG = logging.getLogger("scripts.benchmark_release")
_REPO = "BatchLang/Blinter"
_USER_AGENT = "blinter-bench"
_DOWNLOAD_TIMEOUT_SECONDS = 300.0
_MAX_ZIP_BYTES = 100 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_MAX_API_BYTES = 5 * 1024 * 1024
_DOWNLOAD_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


def _runner_arch() -> str:
    """Return ``arm64`` or ``x64`` from the Actions runner or the local machine."""
    raw = os.environ.get("RUNNER_ARCH") or platform.machine()
    lowered = raw.lower()
    if "arm" in lowered or "aarch" in lowered:
        return "arm64"
    return "x64"


def release_api_url(version: str) -> str:
    """Return the GitHub release API URL for a version, or latest when blank."""
    if version:
        return f"https://api.github.com/repos/{_REPO}/releases/tags/v{version}"
    return f"https://api.github.com/repos/{_REPO}/releases/latest"


def _require_download_url(url: str) -> str:
    """Return ``url`` when it is HTTPS on an allowlisted GitHub host."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed_host = parsed.scheme == "https" and host in _DOWNLOAD_HOSTS
    default_port = parsed.port in (None, 443)
    has_userinfo = bool(parsed.username or parsed.password)
    has_control_char = any(char in url for char in "\r\n\x00")
    if allowed_host and default_port and not has_userinfo and not has_control_char:
        return url
    raise RuntimeError(f"refusing non-allowlisted download URL: {url}")


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only when the target stays on the download allowlist."""

    def redirect_request(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Validate the next URL. The parameter list is fixed by urllib."""
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        _require_download_url(absolute)
        _LOG.info("redirect %s from %s to %s", code, req.full_url, absolute)
        redirected = super().redirect_request(req, fp, code, msg, headers, absolute)
        if redirected is None:
            return None
        original = urllib.parse.urlparse(req.full_url).hostname
        target = urllib.parse.urlparse(absolute).hostname
        if original != target:
            redirected.remove_header("Authorization")
            redirected.remove_header("Cookie")
        return redirected


def _opener() -> urllib.request.OpenerDirector:
    """Return an opener that rechecks every redirect against the allowlist."""
    return urllib.request.build_opener(_AllowlistRedirectHandler)


def _response_status(response: object) -> int:
    """Return the HTTP status from a urllib response."""
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    code = getattr(response, "code", None)
    if isinstance(code, int):
        return code
    raise RuntimeError("download response has no HTTP status")


def _response_url(response: object) -> str:
    """Return the final URL reported by a urllib response."""
    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        raise RuntimeError("download response has no final URL")
    url = geturl()
    if not isinstance(url, str) or not url:
        raise RuntimeError("download response URL is not a string")
    return url


def _read_limited(response: object, limit: int) -> bytes:
    """Read a response body, refusing anything larger than ``limit``."""
    read = getattr(response, "read", None)
    if not callable(read):
        raise RuntimeError("download response is not readable")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = read(1024 * 1024)
        if not isinstance(chunk, bytes):
            raise RuntimeError("download returned a non-byte chunk")
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise RuntimeError(f"download exceeded {limit} bytes")
        chunks.append(chunk)


def _write_hashed(response: object, dest: Path, limit: int) -> str:
    """Stream a response to ``dest`` and return its SHA-256 hex digest."""
    read = getattr(response, "read", None)
    if not callable(read):
        raise RuntimeError("download response is not readable")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    with dest.open("wb") as handle:
        while True:
            chunk = read(1024 * 1024)
            if not isinstance(chunk, bytes):
                raise RuntimeError("download returned a non-byte chunk")
            if not chunk:
                return digest.hexdigest()
            total += len(chunk)
            if total > limit:
                raise RuntimeError(f"download exceeded {limit} bytes")
            handle.write(chunk)
            digest.update(chunk)


def _translate_url_error(exc: Exception, label: str) -> RuntimeError:
    """Return a RuntimeError that names the HTTP status or URL failure."""
    if isinstance(exc, urllib.error.HTTPError):
        return RuntimeError(f"HTTP {exc.code} for {label}")
    if isinstance(exc, urllib.error.URLError):
        return RuntimeError(f"request failed for {label}: {exc.reason}")
    if isinstance(exc, TimeoutError):
        return RuntimeError(f"request timed out for {label}")
    return RuntimeError(f"request failed for {label}: {exc}")


def _open_url(url: str, headers: dict[str, str], timeout: float) -> object:
    """Open an allowlisted HTTPS URL and return the response object."""
    _require_download_url(url)
    request = urllib.request.Request(url, headers=headers)
    try:
        return _opener().open(request, timeout=timeout)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise _translate_url_error(exc, url) from exc


def _fetch_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, object]:
    """GET a JSON object from an allowlisted URL."""
    try:
        with _open_context(url, headers, timeout) as response:
            _require_download_url(_response_url(response))
            status = _response_status(response)
            if status != 200:
                raise RuntimeError(f"HTTP {status} for {url}")
            raw = _read_limited(response, _MAX_API_BYTES)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise _translate_url_error(exc, url) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"response was not JSON for {url}") from exc
    return _require_mapping(payload, "JSON object")


class _ResponseContext:
    """Close a urllib response, including when open() itself fails later."""

    def __init__(self, response: object) -> None:
        self._response = response

    def __enter__(self) -> object:
        return self._response

    def __exit__(self, *_args: object) -> None:
        close = getattr(self._response, "close", None)
        if callable(close):
            close()


def _open_context(
    url: str, headers: dict[str, str], timeout: float
) -> _ResponseContext:
    """Open ``url`` as a context manager."""
    return _ResponseContext(_open_url(url, headers, timeout))


def _download_verified(url: str, dest: Path, expected_sha256: str) -> None:
    """Download ``url`` to ``dest`` and require the SHA-256 to match."""
    headers = {"User-Agent": _USER_AGENT}
    try:
        with _open_context(url, headers, _DOWNLOAD_TIMEOUT_SECONDS) as response:
            _require_download_url(_response_url(response))
            status = _response_status(response)
            if status != 200:
                raise RuntimeError(f"HTTP {status} downloading {dest.name}")
            actual = _write_hashed(response, dest, _MAX_ZIP_BYTES)
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        dest.unlink(missing_ok=True)
        if isinstance(exc, RuntimeError):
            raise
        raise _translate_url_error(exc, dest.name) from exc
    if _digest_equal(actual, expected_sha256):
        _LOG.info("verified sha256 for %s", dest.name)
        return
    dest.unlink(missing_ok=True)
    raise RuntimeError(f"sha256 mismatch for {dest.name}")


def _digest_equal(actual: str, expected: str) -> bool:
    """Compare two hex digests without leaking the mismatch through timing."""
    if len(actual) != len(expected):
        return False
    return hmac.compare_digest(actual, expected)


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_mapping(value: object, label: str) -> dict[str, object]:
    """Return ``value`` when it is a string-keyed mapping."""
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    mapped: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise RuntimeError(f"{label} has a non-string key")
        mapped[key] = item
    return mapped


def _require_str(value: object, label: str) -> str:
    """Return ``value`` when it is a non-empty string."""
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} must be a non-empty string")
    return value


def _is_legacy_x64_zip(name: str) -> bool:
    """Return whether ``name`` is an old blinter zip with no architecture suffix."""
    lowered = name.lower()
    if not lowered.startswith("blinter") or not lowered.endswith(".zip"):
        return False
    return not lowered.endswith(("-arm64.zip", "-x64.zip"))


def _asset_name(asset: dict[str, object]) -> str:
    """Return an asset's file name."""
    return _require_str(asset.get("name"), "asset name")


def select_asset(assets: Sequence[object], tag: str, arch: str) -> dict[str, object]:
    """Return the release asset for ``tag`` and ``arch``.

    Current releases publish ``Blinter-<tag>-<arch>.zip``. Older x64 releases
    used a single zip with no architecture suffix.
    """
    mappings = [_require_mapping(item, "asset") for item in assets]
    exact_name = f"Blinter-{tag}-{arch}.zip"
    exact = [
        item for item in mappings if _asset_name(item).lower() == exact_name.lower()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError(f"multiple assets named {exact_name}")
    if arch == "x64":
        legacy = [item for item in mappings if _is_legacy_x64_zip(_asset_name(item))]
        if len(legacy) == 1:
            return legacy[0]
        if len(legacy) > 1:
            raise RuntimeError(f"multiple legacy x64 zips in release {tag}")
    names = [_asset_name(item) for item in mappings]
    raise RuntimeError(f"no {arch} exe zip in release {tag}: {names}")


def _require_sha256(asset: dict[str, object]) -> str:
    """Return the lowercase sha256 hex digest published on a release asset."""
    name = asset.get("name", "asset")
    digest = asset.get("digest")
    if not isinstance(digest, str) or not digest.lower().startswith("sha256:"):
        raise RuntimeError(f"release asset {name} is missing a sha256 digest")
    hexdigest = digest.split(":", 1)[1].strip().lower()
    if len(hexdigest) != 64 or any(
        char not in "0123456789abcdef" for char in hexdigest
    ):
        raise RuntimeError(f"release asset {name} has an invalid sha256 digest")
    return hexdigest


def _require_safe_member(name: str, dest: Path) -> None:
    """Reject zip members that escape ``dest``."""
    if not name or "\x00" in name:
        raise RuntimeError(f"unsafe zip member: {name!r}")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise RuntimeError(f"unsafe zip member: {name}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." or ":" in part for part in parts):
        raise RuntimeError(f"unsafe zip member: {name}")
    relative = Path(*parts) if parts else Path(".")
    target = (dest / relative).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise RuntimeError(f"unsafe zip member: {name}")


def extract_zip(path: Path, dest: Path) -> None:
    """Extract ``path`` into ``dest``, rejecting traversal and oversized archives."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as archive:
            total = 0
            for info in archive.infolist():
                _require_safe_member(info.filename, dest)
                total += max(info.file_size, 0)
                if total > _MAX_UNCOMPRESSED_BYTES:
                    raise RuntimeError("zip uncompressed size exceeds the limit")
            archive.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"invalid zip: {path.name}") from exc


def _exe_relative(asset_name: str) -> Path:
    """Return the in-archive path the installer expects for this zip name."""
    stem = (
        asset_name[: -len(".zip")]
        if asset_name.lower().endswith(".zip")
        else asset_name
    )
    return Path(stem) / "blinter.exe"


def locate_exe(dest: Path, asset_name: str) -> Path:
    """Return ``Blinter-<tag>-<arch>/blinter.exe`` inside the extracted zip."""
    expected = dest / _exe_relative(asset_name)
    if expected.is_file():
        return expected
    relative = _exe_relative(asset_name)
    raise RuntimeError(
        f"blinter.exe not found inside {asset_name}; expected {relative.as_posix()}"
    )


def _api_headers() -> dict[str, str]:
    """Return GitHub API headers, including a bearer token when one is set."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
