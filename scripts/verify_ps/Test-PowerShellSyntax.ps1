#Requires -Version 5.1
<#
.SYNOPSIS
Exits 1 and prints the parse errors when a file is not valid PowerShell.

.PARAMETER Path
The PowerShell file to parse.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
if ($null -ne $errors -and $errors.Count -gt 0) {
    foreach ($parseError in $errors) {
        Write-Output $parseError.ToString()
    }
    exit 1
}
exit 0
