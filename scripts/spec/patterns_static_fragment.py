# Compiled helpers and embedded-language detection (not in commands.yaml SSOT).

_COMPILED_IF_PATTERN = re.compile(r"if\s+(.+)", re.IGNORECASE)

_COMPILED_SETLOCAL_DISABLE = re.compile(
    r"setlocal\s+disabledelayedexpansion", re.IGNORECASE
)

_COMPILED_SET_PATTERN = re.compile(r"\bset\s+", re.IGNORECASE)

_COMPILED_GOTO_PATTERN = re.compile(r"goto\s+(:?\S+)", re.IGNORECASE)

_COMPILED_VAR_EXPANSION = re.compile(r"%[^%]+%|!\w+!")

_COMPILED_ECHO_DOTS = re.compile(r"\s*echo\s+.*\.\.\.\.", re.IGNORECASE)

_COMPILED_NON_ASCII = re.compile(r"[\x00-\x1f\x7f-\xff]")

_COMPILED_NET_SESSION = re.compile(r"net\s+session\s*(>|$)", re.IGNORECASE)

_COMPILED_NET_COMMAND = re.compile(r"\bnet\s+", re.IGNORECASE)

_COMPILED_DELAYED_VAR = re.compile(r"![^!]+!")

POWERSHELL_PATTERNS: List[str] = [
    r"\$\w+\s*=",
    r"\$\w+\.\w+",
    r"\[.*::\w+\]",
    r"-match\s+",
    r"-eq\s+",
    r"-ne\s+",
    r"-ge\s+",
    r"-le\s+",
    r"-gt\s+",
    r"-lt\s+",
    r"(?<![\w.\\/:-])Get-\w+(?![\w.\\/:-])",
    r"(?<![\w.\\/:-])Set-\w+(?![\w.\\/:-])",
    r"(?<![\w.\\/:-])Write-\w+(?![\w.\\/:-])",
    r"(?<![\w.\\/:-])New-\w+(?![\w.\\/:-])",
    r"foreach\s*\(",
    r"(?<![\w.\\/:-])ForEach-Object(?![\w.\\/:-])",
    r"\|\s*%\s*{",
    r"\.Get\(\)",
    r"\.OpenSubKey\(",
    r"\.GetSubKeyNames\(\)",
    r"\[Microsoft\.Win32\.",
    r"\[System\.",
    r"\[Convert\]::\w+",
    r"\[Math\]::\w+",
]

VBSCRIPT_PATTERNS: List[str] = [
    r"^\s*Dim\s+",
    r"^\s*Set\s+\w+\s*=\s*CreateObject",
    r"^\s*WScript\.",
    r"^\s*On\s+Error\s+Resume\s+Next",
    r"^\s*Function\s+\w+\(",
    r"^\s*Sub\s+\w+\(",
    r"^\s*End\s+Function",
    r"^\s*End\s+Sub",
    r"^\s*MsgBox\b",
    r"^\s*InputBox\b",
    r"^\s*Option\s+Explicit",
    r"^\s*ReDim\b",
    r"^\s*CreateObject\s*\(",
    r"^\s*'",
]

# In-file JScript hybrids (polyglot header + body after */). Do not match
# echo-to-temp payloads; those lines are still batch.
JSCRIPT_PATTERNS: List[str] = [
    r"^\s*@if\s*\(.+\)\s*@end\s*/\*",
    r"^\s*\*/\s*$",
    r"^\s*var\s+\w+",
    r"^\s*new\s+ActiveXObject\s*\(",
    r"^\s*WScript\.",
]

# Opening braces and hex literals are skipped as continuation once a real
# C# starter line has opened a block. Matching them on their own
# false-positives on batch `set HEX=0x..` and stray `{` lines.
CSHARP_PATTERNS: List[str] = [
    r"^\s*using\s+System",
    r"^\s*(public|private|protected|internal)\s+(class|static|void|string|int|bool)",
    r"^\s*namespace\s+",
    r"\bforeach\s*\(\s*\w+\s+\w+\s+in\s+",
    r"\bfor\s*\(\s*int\s+\w+\s*=",
    r"\bfor\s*\(\s*uint\s+\w+\s*=",
    r"\bfor\s*\(\s*long\s+\w+\s*=",
    r"byte\s+\w+\s+in\s+",
    r"\b(uint|byte|long|ushort|ulong)\s+",
]

BATCH_INDICATORS: List[str] = [
    r"^@?echo\s+",
    r"^setlocal\b",
    r"^endlocal\b",
    r"^set\s+[A-Z_]+=",
    r"^if\s+",
    r"^FOR\s+",
    r"^goto\s+",
    r"^call\s+",
    r"^exit\s+",
    r"^pause\s*$",
    r"^timeout\s+",
    r"^@?cscript(?:\.exe)?(?:\s|/|$)",
    r"^@?wscript(?:\.exe)?(?:\s|/|$)",
]

SAFE_COMMAND_INJECTION_PATTERNS: List[str] = [
    r'cd\s+/d\s+"%[a-zA-Z_][a-zA-Z0-9_]*%"',
    r"echo\s+.*>\s*nul",
    r'echo\s+.*>>\s*"[^"]*"',
    r'echo\s+.*>\s*"[^"]*"',
    r'%[a-zA-Z_][a-zA-Z0-9_]*%"\s*>[^&|]*$',
    r"^(?>[^&|]*?\b(?:del|copy|move|type|xcopy)\s+)(?>[^&|]*?%[a-zA-Z_][a-zA-Z0-9_]*%)(?>[^&|]*?>)[^&|]*$",
    r"^(?>[^&|]*?\b(?:rd|md|mkdir|rmdir)\s+)(?>[^&|]*?%[a-zA-Z_][a-zA-Z0-9_]*%)(?>[^&|]*?>)[^&|]*$",
    r"^(?>[^&|]*?%[a-zA-Z_][a-zA-Z0-9_]*%)(?>[^&|]*?%[a-zA-Z_][a-zA-Z0-9_]*%)(?>[^&|]*?>)[^&|]*$",
    r"%[a-zA-Z_][a-zA-Z0-9_]*%\s*(?:&&|\|\|)\s*\(\s*$",
    r"^if\s+%[^%]+%==\S+\s+setlocal\s*&\s*call\s+:\w+",
    r"^if\s+%[^%]+%==\S+\s+start\s+.*&\s*goto\s*:",
    r"^if\s+defined\s+\S+\s+\(set\s+",
    r"findstr\b.*%nul\d*%.*&&\s*set\b",
    r"^if\s+%[^%]+%==\S+\s+\(set\s+",
    r"^if\s+%[^%]+%==\S+\s+\(start\s+.*&\s*(?:goto|exit)\b",
    r"^if\s+!errorlevel!==\d+\s+\(start\s+.*&\s*exit\b",
    r"^if\s+defined\s+\S+\s+echo\s+\".*\"\s*\|\s*find\b",
    r"^%psc%\s+\"",
    r"^for\s+.*\bdo\s+\(%psc%\s+\"",
    r"reg\s+query\b.*%nul\d+%\s*\|\s*find\b.*%nul\d+%\s*&&\s*\(",
    r"^if\s+%[^%]+%\s+(?:EQU|NEQ|LSS|LEQ|GEQ|GTR)\s+\S+\s+\(set\s+",
    r"^if\s+%[^%]+%\s+(?:LSS|LEQ|GEQ|GTR)\s+\d+\s+if\s+exist\s+",
    r"^if\s+%[^%]+%\s+(?:LSS|LEQ)\s+\d+\s+\(set\s+.*&exit\b",
    r"^if\s+/i\s+\"%[^%]+%\"==\"\S+\"\s+\(set\s+",
    r"^if\s+defined\s+\S+\s+\(call\s+:",
    r"^if\s+defined\s+\S+\s+\(if\s+exist\s+",
    r"^%nul%\s+reg\s+query\b",
    r"^find\b.*/i\b.*%nul\d+%\s*&&\s*set\b",
    r"^if\s+%[^%]+%==\d+\s+timeout\b.*&\s*exit\b",
    r"^if\s+![^!]+!==\d+\s+start\b.*&\s*goto\b",
    r"^if\s+%[^%]+%\s+(?:EQU|NEQ)\s+\d+\s+set\s+\"\w+=for\s+/f",
    r"^(?:if\s+%[^%]+%\s+(?:EQU|NEQ)\s+\d+\s+)?wmic\b.*%nul\d+%\s*\|\s*find\b",
    r"^set\s+\"\w+=[^\"]*&(?:call|echo)\b",
    r"^set\s+@\w+=.*&\s*set\s+@",
    r"powershell\b.*-file\s+[\"']?%[a-zA-Z_][a-zA-Z0-9_]*%",
    r"^for\s+/f\b.*\bpowershell\b.*-file\b",
    r'^"[^"]*%[a-zA-Z_][a-zA-Z0-9_]*%[^"]*\.exe"[^&|]*>',
]
