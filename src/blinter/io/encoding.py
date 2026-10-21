"""File encoding detection and line-ending analysis."""

from io import StringIO
from pathlib import Path
from typing import (
    List,
    Optional,
    Tuple,
    cast,
)

from charset_normalizer import from_bytes

from blinter.constants import (
    ABSOLUTE_MAX_LINE_LENGTH,
    LARGE_FILE_WARNING_BYTES,
    MAX_FILE_SIZE_BYTES,
    MAX_LINE_LENGTH,
)
from blinter.logging_config import logger

LineEndingInfo = Tuple[str, bool, int, int, int]


def _validate_file_for_read(file_path: str) -> Path:
    """Validate path string, existence, file type, and size before reading."""
    if not file_path or not isinstance(file_path, str):
        raise ValueError("file_path must be a non-empty string")

    file_obj = Path(file_path)
    if not file_obj.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_obj.is_file():
        raise ValueError(f"Path is not a file: {file_path}")

    file_size = file_obj.stat().st_size
    if file_size > LARGE_FILE_WARNING_BYTES:
        logger.warning(
            "Large file detected (%.1fMB). Processing may take longer.",
            file_size / (1024 * 1024),
        )

    if file_size > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // 1024 // 1024
        raise ValueError(f"File exceeds maximum size of {max_mb}MB: {file_path}")

    return file_obj


def _line_ending_stats_from_bytes(content: bytes) -> LineEndingInfo:
    """Derive line-ending statistics from raw file bytes."""
    crlf_count = content.count(b"\r\n")
    lf_total = content.count(b"\n")
    lf_only_count = lf_total - crlf_count
    cr_total = content.count(b"\r")
    cr_only_count = cr_total - crlf_count

    ending_types: List[str] = []
    if crlf_count > 0:
        ending_types.append("CRLF")
    if lf_only_count > 0:
        ending_types.append("LF")
    if cr_only_count > 0:
        ending_types.append("CR")

    if not ending_types:
        dominant_type = "NONE"
        has_mixed = False
    elif len(ending_types) == 1:
        dominant_type = ending_types[0]
        has_mixed = False
    else:
        dominant_type = "MIXED"
        has_mixed = True

    return dominant_type, has_mixed, crlf_count, lf_only_count, cr_only_count


def _detect_line_endings(file_path: str) -> LineEndingInfo:
    """
    Detect line ending types in a batch file.

    This function analyzes the raw file content to determine what type of line endings
    are used, which is critical for batch file compatibility since Unix line endings
    can cause GOTO/CALL label parsing failures in Windows batch files.

    Thread-safe: Yes - uses only local variables and read-only file operations
    Performance: Single-pass full read bounded by MAX_FILE_SIZE_BYTES (50 MB)

    Args:
        file_path: Path to the file to analyze for line endings

    Returns:
        Tuple containing:
            - dominant_type: 'CRLF', 'LF', 'CR', or 'MIXED'
            - has_mixed: True if multiple line ending types found
            - crlf_count: Number of CRLF (\\r\\n) sequences found
            - lf_only_count: Number of standalone LF (\\n) found
            - cr_only_count: Number of standalone CR (\\r) found

    Raises:
        FileNotFoundError: If the specified file doesn't exist
        PermissionError: If insufficient permissions to read the file
        OSError: If file operation fails due to system issues

    Example:
        >>> ending_type, mixed, crlf, lf, cr = _detect_line_endings("script.bat")
        >>> if ending_type == 'LF':
        ...     print("WARNING: Unix line endings detected!")
    """
    try:
        with open(file_path, "rb") as file_handle:
            content = file_handle.read()
    except (FileNotFoundError, PermissionError, OSError) as file_error:
        raise OSError(f"Cannot read file '{file_path}': {file_error}") from file_error

    dominant_type, has_mixed, crlf_count, lf_only_count, cr_only_count = (
        _line_ending_stats_from_bytes(content)
    )

    logger.debug(
        "Line ending analysis for %s: %s (CRLF: %d, LF-only: %d, CR-only: %d)",
        file_path,
        dominant_type,
        crlf_count,
        lf_only_count,
        cr_only_count,
    )

    return dominant_type, has_mixed, crlf_count, lf_only_count, cr_only_count


def _detect_line_endings_from_lines(lines: List[str]) -> LineEndingInfo:
    """Derive line-ending statistics from an already-read line list."""
    if not lines:
        return "NONE", False, 0, 0, 0
    content = "\n".join(lines).encode("utf-8")
    return _line_ending_stats_from_bytes(content)


def _has_multibyte_chars(lines: List[str]) -> Tuple[bool, List[int]]:
    """
    Check for multi-byte UTF-8 characters in batch file lines.

    Multi-byte characters combined with Unix line endings can cause buffer
    parsing errors in Windows batch files due to parser boundary misalignment.

    Thread-safe: Yes - uses only local variables and immutable operations
    Performance: Processes lines efficiently without regex overhead

    Args:
        lines: List of strings representing file lines

    Returns:
        Tuple containing:
            - has_multibyte: True if any multi-byte characters found
            - affected_lines: List of line numbers (1-based) containing multi-byte chars

    Example:
        >>> has_mb, line_nums = _has_multibyte_chars(["echo Hello", "echo ═══"])
        >>> if has_mb:
        ...     print(f"Multi-byte chars found on lines: {line_nums}")
    """
    has_multibyte = False
    affected_lines: List[int] = []

    for line_num, line in enumerate(lines, start=1):
        # Check if line contains any characters that require more than 1 byte in UTF-8
        try:
            line_bytes = line.encode("utf-8")
            # If UTF-8 byte count > character count, there are multi-byte chars
            if len(line_bytes) > len(line):
                has_multibyte = True
                affected_lines.append(line_num)
        except UnicodeEncodeError:
            # If encoding fails, there are definitely non-ASCII chars
            has_multibyte = True
            affected_lines.append(line_num)

    return has_multibyte, affected_lines


def _charset_norm_match_encoding(detected_match: object) -> Optional[str]:
    """Return a validated lowercase encoding name from a charset_normalizer match."""
    if detected_match is None:
        return None

    detected_encoding_raw: object = getattr(detected_match, "encoding", None)
    detected_coherence_raw: object = getattr(detected_match, "coherence", 0.0)
    if not isinstance(detected_encoding_raw, str):
        return None
    if not isinstance(detected_coherence_raw, (int, float)):
        return None
    if detected_coherence_raw <= 0.7:
        return None

    detected_encoding: str = detected_encoding_raw.lower()
    logger.debug(
        "charset_normalizer detected encoding: %s (coherence: %.2f)",
        detected_encoding,
        float(detected_coherence_raw),
    )
    return detected_encoding


def _prioritize_detected_encoding(
    encodings_list: List[str], detected_encoding: str
) -> List[str]:
    """Move detected encoding to the front of the try list."""
    if detected_encoding not in [enc.lower() for enc in encodings_list]:
        encodings_list.insert(0, detected_encoding)
        return encodings_list

    for index, enc in enumerate(encodings_list):
        if enc.lower() == detected_encoding:
            encodings_list.insert(0, encodings_list.pop(index))
            break

    return encodings_list


def _detect_charset_norm_bytes(raw_data: bytes, encodings_list: List[str]) -> List[str]:
    """
    Detect file encoding using charset_normalizer on pre-read bytes.

    Thread-safe: Yes - uses only local variables
    """
    try:
        best_match = from_bytes(raw_data).best()
        detected_encoding = _charset_norm_match_encoding(cast(object, best_match))
        if detected_encoding is None:
            return encodings_list

        return _prioritize_detected_encoding(encodings_list, detected_encoding)

    except (OSError, ValueError, TypeError) as detection_error:
        logger.debug("Encoding detection failed: %s, using fallback", detection_error)

    return encodings_list


def _blank_overlong_lines(lines: List[str], file_path: str) -> List[int]:
    """Blank lines over MAX_LINE_LENGTH and reject lines over the absolute cap.

    A line cmd.exe cannot execute becomes an E048 finding later. Replacing it
    keeps the rest of the file lintable without feeding a huge line to regexes.
    """
    overlong: List[int] = []
    for index, line in enumerate(lines):
        length = len(line)
        line_num = index + 1
        if length > ABSOLUTE_MAX_LINE_LENGTH:
            raise ValueError(
                f"Line {line_num} exceeds absolute maximum length of "
                f"{ABSOLUTE_MAX_LINE_LENGTH} characters in file: {file_path}"
            )
        if length > MAX_LINE_LENGTH:
            logger.warning(
                "Line %d in %s has %d characters, above the %d character limit",
                line_num,
                file_path,
                length,
                MAX_LINE_LENGTH,
            )
            overlong.append(line_num)
            lines[index] = "\n"
    return overlong


def _try_decode_bytes(raw_data: bytes, encoding: str) -> Optional[List[str]]:
    """Attempt to decode bytes with a specific encoding."""
    try:
        logger.debug("Attempting to decode file with encoding: %s", encoding)
        text = raw_data.decode(encoding, errors="strict")
        # cmd.exe reads a line up to LF and drops every CR, including a CR that
        # is not part of CRLF. Splitting on a lone CR would invent lines cmd never runs.
        text = text.replace("\r", "")
        lines = StringIO(text).readlines()
        logger.debug(
            "Successfully decoded %d lines using %s encoding", len(lines), encoding
        )
        return lines
    except (UnicodeDecodeError, LookupError, ValueError) as error:
        logger.debug("Failed to decode with %s: %s", encoding, error)
        return None


_WIDE_ENCODINGS: Tuple[str, ...] = (
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
)


def _encoding_from_bom(raw_data: bytes) -> Optional[str]:
    """Return the encoding named by a leading byte-order mark, if one is present."""
    if raw_data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return "utf-32"
    if raw_data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if raw_data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return None


def _accept_decoded_lines(
    file_path: str, raw_data: bytes, encoding: str
) -> Optional[Tuple[List[str], str, List[int]]]:
    """Return decoded lines when ``encoding`` accepts ``raw_data``."""
    lines = _try_decode_bytes(raw_data, encoding)
    if lines is None:
        return None
    overlong = _blank_overlong_lines(lines, file_path)
    return lines, encoding, overlong


def _decode_wide_or_reject_nuls(
    file_path: str, raw_data: bytes
) -> Tuple[List[str], str, List[int]]:
    """Decode NUL-bearing bytes as UTF-16 or UTF-32, or raise one clear error."""
    for encoding in _WIDE_ENCODINGS:
        decoded = _accept_decoded_lines(file_path, raw_data, encoding)
        if decoded is not None:
            return decoded
    raise OSError(
        f"File '{file_path}' contains NUL bytes and is not valid "
        "UTF-8, UTF-16, or UTF-32."
    )


def _read_lines_from_bytes(
    file_path: str, raw_data: bytes
) -> Tuple[List[str], str, List[int]]:
    """Decode pre-read file bytes using charset detection and fallbacks."""
    bom_encoding = _encoding_from_bom(raw_data)
    if bom_encoding is not None:
        decoded = _accept_decoded_lines(file_path, raw_data, bom_encoding)
        if decoded is not None:
            return decoded

    has_nul = b"\x00" in raw_data
    if has_nul and _try_decode_bytes(raw_data, "utf-8") is None:
        return _decode_wide_or_reject_nuls(file_path, raw_data)

    encodings_to_try = [
        "utf-8",
        "utf-8-sig",
        "cp1252",
        "cp850",
        "iso-8859-1",
        "ascii",
        "cp437",
        "utf-16",
        "utf-32",
    ]
    encodings_to_try = _detect_charset_norm_bytes(raw_data, encodings_to_try)

    for encoding in encodings_to_try:
        decoded = _accept_decoded_lines(file_path, raw_data, encoding)
        if decoded is not None:
            return decoded

    raise OSError(
        f"All encoding attempts failed for file '{file_path}'. "
        "Could not decode file with any supported encoding"
    )


def read_file_with_encoding(file_path: str) -> Tuple[List[str], str]:
    """
    Reads a file with robust encoding detection and fallback mechanisms.

    This function implements a comprehensive encoding detection strategy:
    1. Attempts to use charset_normalizer for automatic detection (if available)
    2. Falls back to a prioritized list of common encodings
    3. Provides detailed error messages for troubleshooting

    Thread-safe: Yes - uses only local variables and immutable data
    Performance: Optimized for common cases (UTF-8 first)

    Args:
        file_path: Path to the file to read. Can be absolute or relative.

    Returns:
        Tuple containing:
            - lines: List of strings, each representing a line in the file
            - encoding_used: String indicating the encoding that was successful

    Raises:
        ValueError: If file_path is invalid or file exceeds maximum size
        FileNotFoundError: If the specified file doesn't exist
        PermissionError: If insufficient permissions to read the file
        OSError: If file operation fails or all encoding attempts fail

    Example:
        >>> lines, encoding = read_file_with_encoding("script.bat")
        >>> print(f"Read {len(lines)} lines using {encoding} encoding")
    """
    file_obj = _validate_file_for_read(file_path)
    raw_data = file_obj.read_bytes()
    lines, encoding_used, _overlong = _read_lines_from_bytes(file_path, raw_data)
    return lines, encoding_used


def _validate_and_read_file(
    file_path: str,
) -> Tuple[List[str], str, LineEndingInfo, List[int]]:
    """Validate file and read its contents in a single binary pass.

    Returns:
        Tuple of (lines, encoding_used, line_ending_info, overlong_line_numbers)
    """
    file_obj = _validate_file_for_read(file_path)

    raw_data = file_obj.read_bytes()
    line_ending_info = _line_ending_stats_from_bytes(raw_data)
    lines, encoding_used, overlong_lines = _read_lines_from_bytes(file_path, raw_data)

    # Log when we had to fall back from UTF-8, but not for pure ASCII files
    if encoding_used.lower() not in ["utf-8", "utf-8-sig", "ascii"]:
        logger.warning(
            "File '%s' was read using '%s' encoding instead of UTF-8. "
            "Consider converting the file to UTF-8 for better compatibility.",
            file_path,
            encoding_used,
        )

    return lines, encoding_used, line_ending_info, overlong_lines
