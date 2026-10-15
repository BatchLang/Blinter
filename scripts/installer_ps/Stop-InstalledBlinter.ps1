#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$target = Join-Path $env:BLINTER_BIN 'blinter.exe'
$processes = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'blinter.exe'")
foreach ($process in $processes) {
    $image = [string]$process.ExecutablePath
    if (-not $image) { continue }
    if ($image -ine $target) { continue }
    try {
        Stop-Process -Id $process.ProcessId -Force
        Write-Output $process.ProcessId
    } catch {
        Write-Error $_
        exit 1
    }
}
exit 0
