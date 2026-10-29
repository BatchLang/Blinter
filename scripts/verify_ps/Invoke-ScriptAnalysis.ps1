#Requires -Version 5.1
<#
.SYNOPSIS
Runs PSScriptAnalyzer over every PowerShell script and module in the repository.

.DESCRIPTION
Analyzes each .ps1 and .psm1 file under scripts and tests, so a new script is
checked without registering it anywhere. Exits 1 when any warning or error is found.

.PARAMETER Root
The repository root.

.PARAMETER SettingsPath
The PSScriptAnalyzer settings file.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Root,

    [Parameter(Mandatory)]
    [string]$SettingsPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$searchRoots = @(@('scripts', 'tests') |
        ForEach-Object { Join-Path $Root $_ } |
        Where-Object { Test-Path -LiteralPath $_ })
if ($searchRoots.Count -eq 0) {
    Write-Error "No scripts or tests folder found under $Root"
    exit 1
}
# Where-Object filters instead of -Include, which Windows PowerShell 5.1 ignores with -LiteralPath.
$files = @(Get-ChildItem -LiteralPath $searchRoots -Recurse -File |
        Where-Object { $_.Extension -in '.ps1', '.psm1' } |
        Sort-Object FullName)
if ($files.Count -eq 0) {
    Write-Error "No PowerShell files found under $Root"
    exit 1
}

Write-Output "Analyzing $($files.Count) PowerShell files"
$issues = @()
foreach ($file in $files) {
    $issues += Invoke-ScriptAnalyzer -Path $file.FullName -Settings $SettingsPath -Severity Warning
}

if ($issues.Count -gt 0) {
    $issues | Format-Table RuleName, ScriptName, Line, Message -AutoSize -Wrap | Out-String -Width 200
    Write-Output "PSScriptAnalyzer found $($issues.Count) issues"
    exit 1
}
Write-Output 'PSScriptAnalyzer found no issues'
