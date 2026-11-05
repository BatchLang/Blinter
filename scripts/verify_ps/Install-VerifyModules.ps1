#Requires -Version 5.1
<#
.SYNOPSIS
Installs the PowerShell modules that scripts/verify.py needs when they are missing.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-MinimumModule {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [Parameter(Mandatory = $true)]
        [string] $Minimum
    )
    $required = [version] $Minimum
    $modules = @(Get-Module -ListAvailable -Name $Name)
    foreach ($module in $modules) {
        if ($module.Version -ge $required) {
            return $true
        }
    }
    return $false
}

$requirements = @(
    @{ Name = 'PSScriptAnalyzer'; Minimum = '1.0' },
    @{ Name = 'Pester'; Minimum = '5.0' }
)
foreach ($requirement in $requirements) {
    $moduleName = [string] $requirement.Name
    $minimum = [string] $requirement.Minimum
    if (Test-MinimumModule -Name $moduleName -Minimum $minimum) {
        Write-Output "PowerShell module $moduleName is already installed"
        continue
    }
    Write-Output "Installing PowerShell module $moduleName $minimum or newer"
    $installArgs = @{
        Name            = $moduleName
        Force           = $true
        Scope           = 'CurrentUser'
        AllowClobber    = $true
        Repository      = 'PSGallery'
        MinimumVersion  = $minimum
    }
    if ($moduleName -eq 'Pester') {
        $installArgs.SkipPublisherCheck = $true
    }
    Install-Module @installArgs
}
