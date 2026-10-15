"""Shared numeric and string constants for checker modules."""

from typing import FrozenSet, Set

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
LARGE_FILE_WARNING_BYTES = 10 * 1024 * 1024
MAX_LINE_LENGTH = 10_000
ABSOLUTE_MAX_LINE_LENGTH = 1_000_000
MAX_FOLLOW_CALL_FILES = 100
MAX_FOLLOW_CALL_DEPTH = 20
MAX_SCAN_FILES = 1000
LARGE_FILE_LINE_THRESHOLD = 2500

BUILTIN_VARS: Set[str] = {
    "DATE",
    "TIME",
    "CD",
    "ERRORLEVEL",
    "RANDOM",
    "CMDCMDLINE",
    "CMDEXTVERSION",
    "COMPUTERNAME",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOGONSERVER",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_ARCHITEW6432",  # WOW64 - native architecture on 64-bit when running 32-bit
    "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
    "PROMPT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERDNSDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",  # 64-bit program files folder
    "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)",
    "ALLUSERSPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PUBLIC",
    "SESSIONNAME",
    "CLIENTNAME",
    # Optional environment variables that may or may not be set
    "SUDO_USER",  # Set by newer Windows sudo command
    "ORIGINAL_USER",  # Sometimes set by scripts for elevation tracking
    "DRIVERDATA",  # Driver data directory (Windows 10+)
    "ONEDRIVE",  # OneDrive directory if configured
    "ONEDRIVECONSUMER",  # Consumer OneDrive
    "ONEDRIVECOMMERCIAL",  # Business OneDrive
    # Optional script-control environment variables (often passed by callers)
    "DEBUG",
    "COMMONPROGRAMW6432",  # 64-bit common files on 64-bit Windows
    "SAFEBOOT_OPTION",  # Set when Windows is in Safe Mode
}

# cmd.exe dynamic pseudo-environment variables (W049). Assigning to these breaks
# expected dynamic semantics; see MS Learn and cmd SET /? behavior.
PSEUDO_ENV_VARS: Set[str] = {
    "CD",
    "CMDCMDLINE",
    "CMDEXTVERSION",
    "DATE",
    "ERRORLEVEL",
    "HIGHESTNUMANODENUMBER",
    "RANDOM",
    "TIME",
}

# Real process environment variables (not cmd.exe pseudo-env). SET of these
# changes the rest of the process; distinct from W049 pseudo-env assignment.
SYSTEM_ENV_VARS: FrozenSet[str] = frozenset(
    name.upper() for name in BUILTIN_VARS if name.upper() not in PSEUDO_ENV_VARS
)

MAGIC_NUMBER_EXCEPTIONS: Set[str] = {
    # Basic numbers
    "0",
    "1",
    "10",
    "100",
    "256",
    "60",
    "24",
    "365",
    # Conversion factors
    "1024",  # Bytes to KB
    "1000",  # Bytes to MB (decimal), Hz to kHz
    "1000000",  # Bytes to MB, Hz to MHz
    "1073741824",  # GB in bytes (1024^3)
    # Common system values
    "65536",  # 64KB, 16-bit limit
    "32768",  # 32KB, signed 16-bit limit
    "255",  # Byte limit, RGB values
    "127",  # Signed byte limit
    "255.255.255.255",  # IP address limit (partial match will work)
    # Time constants
    "3600",  # Seconds in hour
    "86400",  # Seconds in day
    "604800",  # Seconds in week
    # File size constants
    "512",  # Common block size
    "4096",  # Common page size
    # HTTP/networking
    "80",
    "443",
    "8080",
    "3389",  # Common ports
    # Windows-specific
    "260",  # MAX_PATH in Windows
    "32767",  # MAX_SHORT
    # ANSI color codes (foreground)
    *[str(i) for i in range(30, 38)],
    # ANSI color codes (background)
    *[str(i) for i in range(40, 48)],
    # ANSI bright color codes (foreground)
    *[str(i) for i in range(90, 98)],
    # ANSI bright color codes (background)
    *[str(i) for i in range(100, 108)],
    # Common exit codes and small numbers
    *[str(i) for i in range(11, 26)],
    # Single and double digit numbers commonly used in scripts
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "21",
    "22",
    "23",
    "25",
    "26",
    "27",
    "28",
    "29",
    "38",
    "39",  # Additional ANSI codes
    "48",
    "49",  # Additional ANSI codes
    "50",
    "51",
    "52",
    "53",
    "54",
    "55",
    "56",
    "57",
    "58",
    "59",
    "61",
    "62",
    "63",
    "64",
    "65",
    "66",
    "67",
    "68",
    "69",
    "70",
    "71",
    "72",
    "73",
    "74",
    "75",
    "76",
    "77",
    "78",
    "79",
    "81",
    "82",
    "83",
    "84",
    "85",
    "86",
    "87",
    "88",
    "89",
    "99",
}
