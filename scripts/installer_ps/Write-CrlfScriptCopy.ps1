$bytes = [System.IO.File]::ReadAllBytes($env:BLINTER_SELF)
if ($bytes -contains 13) { exit 0 }
$list = New-Object System.Collections.Generic.List[byte]
foreach ($byte in $bytes) {
    if ($byte -eq 10) { $list.Add(13) }
    $list.Add($byte)
}
[System.IO.File]::WriteAllBytes($env:BLINTER_CRLF_COPY, $list.ToArray())
exit 3
