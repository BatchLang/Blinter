#Requires -Version 5.1
try {
    Expand-Archive -LiteralPath "$($env:BLINTER_TEMP).zip" -DestinationPath $env:BLINTER_TEMP -Force
    exit 0
}
catch {
    Write-Host "ERROR: $_"
    exit 1
}
