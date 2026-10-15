#Requires -Version 5.1
$item = Get-Item -LiteralPath "$($env:BLINTER_TEMP).zip" -ErrorAction Stop
Write-Output $item.Length
