#Requires -Version 5.1
<#
.SYNOPSIS
Runs every Pester test file in the repository.

.DESCRIPTION
Runs each *.Tests.ps1 file under scripts and tests, so a new test file runs without
being registered anywhere. Pester exits non-zero when a test fails.

.PARAMETER Root
The repository root.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Root
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
$testFiles = @(Get-ChildItem -LiteralPath $searchRoots -Recurse -File |
        Where-Object { $_.Name -like '*.Tests.ps1' } |
        Sort-Object FullName |
        Select-Object -ExpandProperty FullName)
if ($testFiles.Count -eq 0) {
    Write-Error "No Pester test files found under $Root"
    exit 1
}

Import-Module Pester -MinimumVersion 5.0 -ErrorAction Stop
Write-Output "Running $($testFiles.Count) Pester test files"
Invoke-Pester -Path $testFiles -CI
