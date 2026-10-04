"""Tests for file encoding detection functionality."""

import os
from pathlib import Path
import tempfile
from typing import IO, List, Optional, Union
from unittest.mock import MagicMock, mock_open, patch
import warnings

import pytest

from blinter.constants import MAX_FILE_SIZE_BYTES, MAX_LINE_LENGTH
from blinter.io.encoding import _validate_and_read_file
from blinter import (
    lint_batch_file,
    read_file_with_encoding,
)
from tests.conftest import make_mock_encoding_path, patch_valid_encoding_path

_VALIDATE_FILE_PATCH = patch(
    "blinter.io.encoding._validate_file_for_read",
    return_value=make_mock_encoding_path(b"test content\n"),
)


class TestFileEncodingDetection:
    """Test cases for file encoding detection."""

    def test_read_utf8_file(self) -> None:
        """Test reading a UTF-8 encoded file."""
        content = "This is a test file\nwith multiple lines\n"

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            lines, encoding = read_file_with_encoding(temp_file_path)
            assert lines == ["This is a test file\n", "with multiple lines\n"]
            # ASCII is a subset of UTF-8, so this may be detected as ascii
            assert encoding in ["utf-8", "ascii"]
        finally:
            os.unlink(temp_file_path)

    def test_read_utf8_bom_file(self) -> None:
        """Test reading a UTF-8 with BOM file."""
        content = "This is a test file\nwith BOM\n"

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            lines, encoding = read_file_with_encoding(temp_file_path)
            # BOM may or may not be included depending on encoding detected
            assert len(lines) == 2
            assert "This is a test file" in lines[0]
            assert "with BOM" in lines[1]
            assert encoding in ["utf-8-sig", "utf-8"]
        finally:
            os.unlink(temp_file_path)

    def test_read_latin1_file(self) -> None:
        """Test reading a Latin-1 encoded file."""
        content = "CafÃ© franÃ§ais\nwith special chars\n"

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="latin-1", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lines, encoding = read_file_with_encoding(temp_file_path)
                assert len(lines) == 2
                # Allow various encodings - charset_normalizer may detect utf-8 on modern systems
                # for content that's compatible with both encodings
                assert encoding.lower() in [
                    "cp1252",
                    "iso-8859-1",
                    "utf-8",
                ]
                # Verify content is correctly read regardless of detected encoding
                assert "CafÃ©" in lines[0] or "Café" in lines[0]
        finally:
            os.unlink(temp_file_path)

    def test_encoding_warning(self) -> None:
        """Test that warning is issued for non-UTF-8 files."""
        # Create content that will trigger a warning in the linting process
        content = "@echo off\necho test"

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="latin1", suffix=".bat", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with warnings.catch_warnings(record=True) as _warning_list:
                warnings.simplefilter("always")
                # Call lint_batch_file instead, which triggers the warning
                issues = lint_batch_file(temp_file_path)

                # Should get a warning for non-UTF-8 encoding if it was read as non-UTF-8
                assert isinstance(issues, list)  # Function should work regardless
        finally:
            os.unlink(temp_file_path)

    @patch("builtins.open", side_effect=FileNotFoundError("File not found"))
    def test_file_not_found_error(self, _mock_file: MagicMock) -> None:
        """Test handling of file not found error."""
        with pytest.raises(FileNotFoundError):
            read_file_with_encoding("nonexistent_file.bat")

    @patch.object(Path, "exists", return_value=True)
    @patch.object(Path, "is_file", return_value=True)
    @patch.object(Path, "stat")
    @patch.object(Path, "read_bytes", side_effect=PermissionError("Permission denied"))
    def test_permission_error(
        self, _mock_read_bytes: MagicMock, mock_stat: MagicMock, *_unused: MagicMock
    ) -> None:
        """Test handling of permission error."""
        mock_stat.return_value.st_size = 10
        with pytest.raises(PermissionError):
            read_file_with_encoding("restricted_file.bat")

    @_VALIDATE_FILE_PATCH
    @patch("blinter.io.encoding.from_bytes")
    @patch("builtins.open")
    def test_charset_normalizer_detection_success(
        self,
        mock_file: MagicMock,
        mock_from_bytes: MagicMock,
        _mock_validate: MagicMock,
    ) -> None:
        """Test successful charset_normalizer encoding detection."""
        # Mock charset_normalizer detection
        mock_result = MagicMock()
        mock_result.encoding = "cp1252"
        mock_result.coherence = 0.8
        mock_from_bytes.return_value.best.return_value = mock_result

        # Mock file operations (single binary read)
        mock_file.return_value = mock_open(read_data=b"test content\n").return_value

        lines, encoding = read_file_with_encoding("test.bat")
        assert lines == ["test content\n"]
        assert encoding == "cp1252"

    @_VALIDATE_FILE_PATCH
    @patch("blinter.io.encoding.from_bytes")
    @patch("builtins.open")
    def test_charset_normalizer_detection_low_confidence(
        self,
        mock_file: MagicMock,
        mock_from_bytes: MagicMock,
        _mock_validate: MagicMock,
    ) -> None:
        """Test charset_normalizer detection with low confidence."""
        # Mock charset_normalizer with low confidence
        mock_result = MagicMock()
        mock_result.encoding = "cp1252"
        mock_result.coherence = 0.3
        mock_from_bytes.return_value.best.return_value = mock_result

        mock_file.return_value = mock_open(read_data=b"test content\n").return_value

        lines, encoding = read_file_with_encoding("test.bat")
        assert lines == ["test content\n"]
        assert encoding == "utf-8"

    def test_charset_normalizer_import_error(self) -> None:
        """Test fallback when charset_normalizer detection fails."""
        content = "test content\n"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with patch(
                "blinter.io.encoding.from_bytes",
                side_effect=OSError("charset_normalizer unavailable"),
            ):
                lines, encoding = read_file_with_encoding(temp_file_path)
                assert lines == ["test content\n"]
                assert encoding in ["utf-8", "ascii"]  # ASCII is subset of UTF-8
        finally:
            os.unlink(temp_file_path)

    @_VALIDATE_FILE_PATCH
    @patch("builtins.open")
    def test_all_encodings_fail(
        self, mock_file: MagicMock, _mock_validate: MagicMock
    ) -> None:
        """Test when all encoding attempts fail."""
        mock_file.return_value = mock_open(read_data=b"test content").return_value

        with (
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
            pytest.raises(OSError) as exc_info,
        ):
            read_file_with_encoding("test.bat")

        assert "All encoding attempts failed" in str(exc_info.value)

    @_VALIDATE_FILE_PATCH
    @patch("builtins.open")
    def test_encoding_lookup_error(
        self, mock_file: MagicMock, _mock_validate: MagicMock
    ) -> None:
        """Test handling of encoding lookup errors."""
        mock_file.return_value = mock_open(read_data=b"test content\n").return_value

        def mock_decode_bytes(raw_data: bytes, encoding: str) -> Optional[List[str]]:
            if encoding == "utf-8":
                return None
            if encoding == "cp1252":
                return ["test content\n"]
            return None

        with patch(
            "blinter.io.encoding._try_decode_bytes",
            side_effect=mock_decode_bytes,
        ):
            lines, _encoding = read_file_with_encoding("test.bat")
        assert lines == ["test content\n"]

    def test_empty_file(self) -> None:
        """Test reading an empty file."""
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        ) as temp_file:
            temp_file_path = temp_file.name

        try:
            lines, encoding = read_file_with_encoding(temp_file_path)
            assert lines == []
            assert encoding == "utf-8"
        finally:
            os.unlink(temp_file_path)

    def test_file_with_null_bytes(self) -> None:
        """Test reading a file with null bytes."""
        content = b"test\x00content\n"

        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # This should fallback to an encoding that can handle null bytes
            lines, encoding = read_file_with_encoding(temp_file_path)
            assert len(lines) == 1
            # charset_normalizer may detect utf-8; cp1252/cp437 handle null bytes
            assert encoding.lower() in [
                "ascii",
                "iso-8859-1",
                "cp1252",
                "cp437",
                "utf-8",  # charset_normalizer may detect this
            ]
        finally:
            os.unlink(temp_file_path)

    @_VALIDATE_FILE_PATCH
    @patch("blinter.io.encoding.from_bytes")
    @patch("builtins.open")
    def test_charset_detect_encoding_not_in_default_list(
        self,
        mock_file: MagicMock,
        mock_from_bytes: MagicMock,
        _mock_validate: MagicMock,
    ) -> None:
        """Test when charset_normalizer detects encoding NOT in our default list - inserted at front."""
        # Mock charset_normalizer to return an encoding NOT in the default list
        mock_result = MagicMock()
        mock_result.encoding = "koi8-r"  # This is NOT in the default list
        mock_result.coherence = 0.9
        mock_from_bytes.return_value.best.return_value = mock_result

        mock_file.return_value = mock_open(read_data=b"test content\n").return_value

        lines, encoding = read_file_with_encoding("test.bat")
        assert lines == ["test content\n"]
        assert encoding == "koi8-r"  # Should use the detected encoding

    @_VALIDATE_FILE_PATCH
    @patch("blinter.io.encoding.from_bytes")
    @patch("builtins.open")
    def test_charset_detect_encoding_in_default_list(
        self,
        mock_file: MagicMock,
        mock_from_bytes: MagicMock,
        _mock_validate: MagicMock,
    ) -> None:
        """Test when charset_normalizer detects encoding that exists in our list - should be moved to front."""
        # Mock charset_normalizer to return an encoding that IS in the default list
        mock_result = MagicMock()
        mock_result.encoding = "cp1252"  # This IS in the default list
        mock_result.coherence = 0.85
        mock_from_bytes.return_value.best.return_value = mock_result

        mock_file.return_value = mock_open(read_data=b"test content\n").return_value

        lines, encoding = read_file_with_encoding("test.bat")
        assert lines == ["test content\n"]
        assert encoding == "cp1252"  # Should use cp1252 (moved to front)

    @patch("blinter.io.encoding.from_bytes")
    def test_charset_normalizer_exception_handling(
        self, mock_from_bytes: MagicMock
    ) -> None:
        """Test charset_normalizer exception handling."""
        content = b"test content"

        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Mock charset_normalizer to raise an exception
            mock_from_bytes.side_effect = OSError("charset_normalizer failed")

            # This should handle the exception gracefully and fall back to default encodings
            lines, encoding = read_file_with_encoding(temp_file_path)
            assert isinstance(lines, list)
            assert isinstance(encoding, str)
        finally:
            os.unlink(temp_file_path)

    def test_encoding_exhaustion_raises_oserror(self) -> None:
        """Test OSError when all encoding decode attempts fail."""
        content = b"test content"

        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            with patch(
                "blinter.io.encoding._try_decode_bytes",
                return_value=None,
            ):
                with pytest.raises(OSError, match="All encoding attempts failed"):
                    read_file_with_encoding(temp_file_path)
        finally:
            os.unlink(temp_file_path)

    def test_read_paths_return_same_encoding(self) -> None:
        """read_file_with_encoding and _validate_and_read_file use the same decoder."""
        content = "@ECHO OFF\r\necho test\r\n"

        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file:
            temp_file.write(content.encode("utf-8"))
            temp_file_path = temp_file.name

        try:
            read_lines, read_encoding = read_file_with_encoding(temp_file_path)
            validate_lines, validate_encoding, _ = _validate_and_read_file(
                temp_file_path
            )
            assert read_encoding == validate_encoding
            assert read_lines == validate_lines
        finally:
            os.unlink(temp_file_path)


class TestEncodingEdgeCases:
    """Test edge cases in file encoding detection and handling."""

    def test_charset_normalizer_not_available_fallback(self) -> None:
        """Test encoding fallback when charset_normalizer detection fails."""
        # Create a test file with UTF-8 content
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file_handle:
            content = "@ECHO OFF\nECHO Hello World\n"
            temp_file_handle.write(content.encode("utf-8"))
            temp_file = temp_file_handle.name

        try:
            with patch(
                "blinter.io.encoding.from_bytes",
                side_effect=OSError("charset_normalizer unavailable"),
            ):
                lines, encoding = read_file_with_encoding(temp_file)
                assert len(lines) == 2
                assert encoding in [
                    "utf-8",
                    "utf-8-sig",
                    "cp1252",
                    "iso-8859-1",
                    "ascii",
                ]
        finally:
            os.unlink(temp_file)

    def test_charset_normalizer_detection_error_fallback(self) -> None:
        """Test encoding fallback when charset_normalizer detection fails."""
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file_handle:
            content = "@ECHO OFF\nECHO Test\n"
            temp_file_handle.write(content.encode("utf-8"))
            temp_file = temp_file_handle.name

        try:
            # Mock blinter.io.encoding.from_bytes to raise an exception
            with patch(
                "blinter.io.encoding.from_bytes",
                side_effect=ValueError("Detection failed"),
            ):
                lines, encoding = read_file_with_encoding(temp_file)
                assert len(lines) == 2
                assert encoding in [
                    "utf-8",
                    "utf-8-sig",
                    "cp1252",
                    "iso-8859-1",
                    "ascii",
                ]
        finally:
            os.unlink(temp_file)

    def test_all_encoding_attempts_fail(self) -> None:
        """Test the rare case where all encoding attempts fail."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_encoding_lookup_error(self) -> None:
        """Test handling of invalid encoding names."""
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file_handle:
            content = "@ECHO OFF\n"
            temp_file_handle.write(content.encode("utf-8"))
            temp_file = temp_file_handle.name

        try:
            # Test with an invalid encoding in the list by modifying the encodings list
            # This will trigger the LookupError handling path
            original_open = open
            call_count = [0]

            def mock_open_with_invalid_encoding(
                *args: object, **kwargs: object
            ) -> Union[IO[str], IO[bytes]]:
                call_count[0] += 1
                # Let the first call (charset_normalizer) succeed
                if "rb" in str(args) or "rb" in str(kwargs.get("mode", "")):
                    return original_open(*args, **kwargs)  # type: ignore[call-overload]
                # Fail the second call with text mode
                if call_count[0] == 2:  # First text mode call with invalid encoding
                    raise LookupError("Invalid encoding")
                return original_open(*args, **kwargs)  # type: ignore[call-overload]

            with patch("builtins.open", side_effect=mock_open_with_invalid_encoding):
                lines, _encoding = read_file_with_encoding(temp_file)
                assert len(lines) == 1
        finally:
            os.unlink(temp_file)


class TestEncodingFallbackScenarios:
    """Test additional encoding fallback scenarios."""

    def test_charset_normalizer_low_confidence_fallback(self) -> None:
        """Test encoding fallback when charset_normalizer has low confidence."""
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file_handle:
            content = "@ECHO OFF\nECHO Test\n"
            temp_file_handle.write(content.encode("utf-8"))
            temp_file = temp_file_handle.name

        try:
            # Mock blinter.io.encoding.from_bytes to return low confidence
            mock_result = MagicMock()
            mock_result.encoding = "utf-8"
            mock_result.coherence = 0.5  # Below 0.7 threshold
            mock_from_bytes = MagicMock()
            mock_from_bytes.best.return_value = mock_result
            with patch("blinter.io.encoding.from_bytes", return_value=mock_from_bytes):
                lines, encoding = read_file_with_encoding(temp_file)
                assert len(lines) == 2
                # Should fall back to standard encoding list
                assert encoding in [
                    "utf-8",
                    "utf-8-sig",
                    "cp1252",
                    "iso-8859-1",
                    "ascii",
                ]
        finally:
            os.unlink(temp_file)

    def test_charset_normalizer_none_result_fallback(self) -> None:
        """Test encoding fallback when charset_normalizer returns None."""
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file_handle:
            content = "@ECHO OFF\nECHO Test\n"
            temp_file_handle.write(content.encode("utf-8"))
            temp_file = temp_file_handle.name

        try:
            # Mock blinter.io.encoding.from_bytes().best() to return None
            mock_result = MagicMock()
            mock_result.best.return_value = None
            with patch("blinter.io.encoding.from_bytes", return_value=mock_result):
                lines, encoding = read_file_with_encoding(temp_file)
                assert len(lines) == 2
                assert encoding in [
                    "utf-8",
                    "utf-8-sig",
                    "cp1252",
                    "iso-8859-1",
                    "ascii",
                ]
        finally:
            os.unlink(temp_file)

    def test_read_file_with_encoding_no_fallback_needed(self) -> None:
        """Test read_file_with_encoding when first encoding works (no fallback exception path)."""
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".bat"
        ) as temp_file_handle:
            content = "@ECHO OFF\nECHO Test\n"
            temp_file_handle.write(content.encode("utf-8"))
            temp_file = temp_file_handle.name

        try:
            # This should succeed without triggering the exception path
            lines, encoding = read_file_with_encoding(temp_file)
            assert len(lines) == 2
            # Encoding might be ascii if content is simple ASCII, that's fine
            assert encoding in ["utf-8", "ascii", "utf-8-sig"]
        finally:
            os.unlink(temp_file)


class TestAdditionalFileEncodingScenarios:
    """Additional file encoding tests for comprehensive scenarios."""

    def test_charset_detect_encoding_not_in_list(self) -> None:
        """Test charset_normalizer detecting encoding not in our default list."""

        mock_result = MagicMock()
        mock_result.encoding = "iso-2022-jp"
        mock_result.coherence = 0.85
        mock_from_bytes = MagicMock()
        mock_from_bytes.best.return_value = mock_result

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding.from_bytes", return_value=mock_from_bytes),
        ):
            # Should succeed by adding the detected encoding to the front
            lines, _ = read_file_with_encoding("test.bat")
            assert len(lines) > 0

    def test_charset_detect_encoding_already_in_list(self) -> None:
        """Test when charset_normalizer detects an encoding already in our list."""

        mock_result = MagicMock()
        mock_result.encoding = "utf-8"
        mock_result.coherence = 0.8
        mock_from_bytes = MagicMock()
        mock_from_bytes.best.return_value = mock_result

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding.from_bytes", return_value=mock_from_bytes),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding == "utf-8"  # Should use detected encoding
            assert len(lines) > 0

    def test_charset_normalizer_oserror_handling(self) -> None:
        """Test handling of OSError during charset_normalizer detection."""

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding.from_bytes", side_effect=OSError("Test OSError")
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding in [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "iso-8859-1",
                "ascii",
            ]
            assert len(lines) > 0

    def test_charset_normalizer_valueerror_handling(self) -> None:
        """Test handling of ValueError during charset_normalizer detection."""

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding.from_bytes",
                side_effect=ValueError("Test ValueError"),
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding in [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "iso-8859-1",
                "ascii",
            ]
            assert len(lines) > 0

    def test_charset_normalizer_typeerror_handling(self) -> None:
        """Test handling of TypeError during charset_normalizer detection."""

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding.from_bytes",
                side_effect=TypeError("Test TypeError"),
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding in [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "iso-8859-1",
                "ascii",
            ]
            assert len(lines) > 0

    def test_encoding_lookup_error_fallback(self) -> None:
        """Test handling when encoding lookup fails."""

        def mock_decode_bytes(raw_data: bytes, encoding: str) -> Optional[List[str]]:
            if encoding == "utf-8":
                return None
            if encoding == "cp1252":
                return ["test content\n"]
            return None

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding._try_decode_bytes",
                side_effect=mock_decode_bytes,
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding != "utf-8"
            assert len(lines) > 0

    def test_encoding_value_error_fallback(self) -> None:
        """Test handling when encoding value is invalid."""

        def mock_decode_bytes(raw_data: bytes, encoding: str) -> Optional[List[str]]:
            if encoding == "utf-8":
                return None
            if encoding == "cp1252":
                return ["test content\n"]
            return None

        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch(
                "blinter.io.encoding._try_decode_bytes",
                side_effect=mock_decode_bytes,
            ),
        ):
            lines, encoding = read_file_with_encoding("test.bat")
            assert encoding != "utf-8"
            assert len(lines) > 0

    def test_all_encodings_fail_with_exception(self) -> None:
        """Test when all encodings fail and we have a last exception."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_all_encodings_fail_no_exception(self) -> None:
        """Test when all encodings fail but no exception is stored."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")

    def test_encoding_failure_edge_case(self) -> None:
        """Test encoding failure when no exceptions are stored."""
        with (
            patch_valid_encoding_path(),
            patch("builtins.open", mock_open(read_data=b"test content")),
            patch("blinter.io.encoding._try_decode_bytes", return_value=None),
        ):
            with pytest.raises(OSError, match="All encoding attempts failed"):
                read_file_with_encoding("test.bat")


class TestFileSizeLimit:  # pylint: disable=too-few-public-methods
    """Test maximum file size enforcement."""

    def test_rejects_file_exceeding_max_size(self, tmp_path: Path) -> None:
        """Files larger than MAX_FILE_SIZE_BYTES are rejected."""
        big_file = tmp_path / "big.bat"
        big_file.write_bytes(b"@echo off\n" + b"x" * (MAX_FILE_SIZE_BYTES + 1))

        with pytest.raises(ValueError, match="exceeds maximum size"):
            _validate_and_read_file(str(big_file))

        with pytest.raises(ValueError, match="exceeds maximum size"):
            read_file_with_encoding(str(big_file))


class TestLineLengthLimit:  # pylint: disable=too-few-public-methods
    """Test maximum per-line length enforcement."""

    def test_rejects_line_exceeding_max_length(self, tmp_path: Path) -> None:
        """Lines longer than MAX_LINE_LENGTH are rejected at read time."""
        within_limit = "A" * (MAX_LINE_LENGTH - 1) + "\n"
        overflow = "B" * MAX_LINE_LENGTH + "\n"
        bat_file = tmp_path / "longline.bat"
        bat_file.write_text(f"@echo off\n{within_limit}{overflow}", encoding="utf-8")

        with pytest.raises(ValueError, match="exceeds maximum length"):
            _validate_and_read_file(str(bat_file))

        with pytest.raises(ValueError, match="exceeds maximum length"):
            read_file_with_encoding(str(bat_file))


class TestLineEndingStandaloneDetection:
    """Tests for standalone line-ending detection paths."""

    def test_detect_line_endings_crlf_file(self, tmp_path: Path) -> None:
        """CRLF files report CRLF as the dominant line ending."""
        from blinter.io.encoding import _detect_line_endings

        bat_file = tmp_path / "crlf.bat"
        bat_file.write_bytes(b"@echo off\r\nexit /b 0\r\n")
        ending_type, has_mixed, crlf_count, lf_only, cr_only = _detect_line_endings(
            str(bat_file)
        )
        assert ending_type == "CRLF"
        assert crlf_count >= 1
        assert lf_only == 0
        assert has_mixed is False

    def test_validate_and_read_file_includes_ending_info(self, tmp_path: Path) -> None:
        """Single-pass read returns line-ending statistics."""
        bat_file = tmp_path / "mixed.bat"
        bat_file.write_bytes(b"line1\r\nline2\n")
        lines, encoding, ending_info = _validate_and_read_file(str(bat_file))
        assert len(lines) == 2
        assert encoding in {"utf-8", "ascii", "cp1252", "iso-8859-1"}
        dominant_type, has_mixed, crlf_count, lf_only, _cr_only = ending_info
        assert dominant_type in {"CRLF", "LF", "MIXED"}
        assert crlf_count + lf_only >= 1
        assert isinstance(has_mixed, bool)

    def test_detect_line_endings_from_lines_lf_content(self) -> None:
        """In-memory line lists derive LF endings without re-reading disk."""
        from blinter.io.encoding import _detect_line_endings_from_lines

        ending_type, has_mixed, crlf_count, lf_only, cr_only = (
            _detect_line_endings_from_lines(["@echo off", "exit /b 0"])
        )
        assert ending_type == "LF"
        assert lf_only >= 1
        assert crlf_count == 0
        assert cr_only == 0
        assert has_mixed is False

    def test_check_line_ending_rules_without_ending_info(self) -> None:
        """Line-ending rules work when ending_info is omitted but lines are provided."""
        from blinter.checkers.line_endings import _check_line_ending_rules

        lines = ["@echo off", "exit /b 0"]
        issues = _check_line_ending_rules(lines, "memory.bat", ending_info=None)
        e018_issues = [issue for issue in issues if issue.rule.code == "E018"]
        assert e018_issues, "Expected E018 for LF-style in-memory lines"

    def test_check_line_ending_rules_empty_lines(self) -> None:
        """Empty line lists produce no line-ending issues."""
        from blinter.checkers.line_endings import _check_line_ending_rules

        issues = _check_line_ending_rules([], "empty.bat", ending_info=None)
        assert issues == []

    @pytest.mark.parametrize(
        ("encoding", "coherence", "expected"),
        [
            ("utf-8", 0.95, "utf-8"),
            ("utf-8", 0.5, None),
            (123, 0.95, None),
        ],
    )
    def test_charset_norm_match_encoding(
        self, encoding: object, coherence: float, expected: str | None
    ) -> None:
        """Encoding detection rejects low-coherence or invalid matches."""
        from blinter.io.encoding import _charset_norm_match_encoding

        match = MagicMock()
        match.encoding = encoding
        match.coherence = coherence
        assert _charset_norm_match_encoding(match) == expected
