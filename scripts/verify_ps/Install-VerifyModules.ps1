#Requires -Version 5.1
<#
.SYNOPSIS
Installs the PowerShell modules that scripts/verify.py needs when they are missing.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

foreach ($moduleName in @('PSScriptAnalyzer', 'Pester')) {
    if (Get-Module -ListAvailable -Name $moduleName) {
        Write-Output "PowerShell module $moduleName is already installed"
        continue
    }
    Write-Output "Installing PowerShell module $moduleName"
    Install-Module -Name $moduleName -Force -Scope CurrentUser -AllowClobber -Repository PSGallery
}
