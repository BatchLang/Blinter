#Requires -Version 5.1
$expected = '__BLINTER_SHA256__'
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $stream = [System.IO.File]::OpenRead('__BLINTER_TEMP__.zip')
    try {
        $actual = [System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
        $actual = $actual.ToLowerInvariant()
    } finally { $stream.Dispose() }
} finally { $sha.Dispose() }
$normalized = $expected.ToLowerInvariant() -replace '^sha256:', ''
if ($actual -ne $normalized) { Write-Output 'MISMATCH'; exit 1 }
Write-Output 'OK'
