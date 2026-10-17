#Requires -Version 5.1
<#
.SYNOPSIS
    Install and uninstall Blinter by running the real batch scripts.

.DESCRIPTION
    Used by Windows CI. Runs scripts/install_blinter.cmd and
    scripts/uninstall_blinter.cmd, then repeats with Unix line endings and the
    README "(call script || cd .)" invocation. GitHub-hosted Windows runners
    are elevated, and both scripts refuse an administrator token. RunLevel
    Limited scheduled tasks stay elevated there, so an elevated caller starts
    the scripts with runas /trustlevel:0x20000 (basic user, same account).
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Write-InstallerTestLog {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "installer-test: $Message"
}

function Get-BlinterInstallLayout {
    $root = Join-Path $env:LOCALAPPDATA "Programs\Blinter"
    $bin = Join-Path $root "bin"
    return [PSCustomObject]@{
        Root        = $root
        Bin         = $bin
        Exe         = Join-Path $bin "blinter.exe"
        ReleaseFile = Join-Path $root "installed_release.txt"
    }
}

function Test-BlinterSessionElevated {
    & cmd.exe /d /c "net session >nul 2>&1"
    return $LASTEXITCODE -eq 0
}

function ConvertTo-BlinterMediumIntegrity {
    param([Parameter(Mandatory)][string]$Path)

    # An elevated parent labels this directory High. The basic-user child cannot create files there.
    $output = & icacls.exe $Path "/setintegritylevel" "(OI)(CI)M"
    if ($LASTEXITCODE -ne 0) {
        $detail = ($output | Out-String).Trim()
        throw "Could not mark $Path medium integrity (exit $LASTEXITCODE): $detail"
    }
    Write-InstallerTestLog "Marked medium integrity: $Path"
}

function Invoke-BlinterBasicUser {
    param([Parameter(Mandatory)][string]$LauncherPath)

    # runas returns before the child exits and always reports exit code 0.
    # The wrapper records the launcher's exit code for the parent to read.
    $exitFile = "$LauncherPath.exit"
    $wrapperPath = "$LauncherPath.basic.cmd"
    $stdoutPath = "$LauncherPath.runas.out"
    $stderrPath = "$LauncherPath.runas.err"
    foreach ($path in @($exitFile, $stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    if ($wrapperPath.Contains(" ")) {
        throw "Basic-user launcher path contains spaces: $wrapperPath"
    }
    ConvertTo-BlinterMediumIntegrity -Path (Split-Path -Parent $LauncherPath)

    Initialize-BlinterLauncherFile -Destination $wrapperPath -Body @"
@echo off
call "$LauncherPath"
set "RC=%ERRORLEVEL%"
> "$exitFile" echo %RC%
exit /b %RC%
"@
    $cmd = "$env:SystemRoot\System32\cmd.exe"
    $argument = "/trustlevel:0x20000 `"$cmd /d /c $wrapperPath`""
    Write-InstallerTestLog "Starting basic-user process: $argument"
    $process = Start-Process `
        -FilePath "$env:SystemRoot\System32\runas.exe" `
        -ArgumentList $argument `
        -WorkingDirectory "$env:SystemDrive\" `
        -PassThru `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath
    if (-not $process.WaitForExit(15000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "runas.exe did not return within 15 seconds for $LauncherPath"
    }

    $runasError = ""
    if (Test-Path -LiteralPath $stderrPath) {
        $runasError = ([System.IO.File]::ReadAllText($stderrPath)).Trim()
    }
    if ($runasError) {
        Write-InstallerTestLog "runas stderr: $runasError"
    }
    if ($runasError -match "RUNAS ERROR|Unable to run") {
        throw "Could not start a basic-user process. $runasError"
    }

    $deadline = (Get-Date).AddMinutes(12)
    while (-not (Test-Path -LiteralPath $exitFile) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path -LiteralPath $exitFile)) {
        $needle = [System.Management.Automation.WildcardPattern]::Escape($wrapperPath)
        $processes = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'cmd.exe'"
        foreach ($item in $processes) {
            if ($item.CommandLine -and $item.CommandLine -like "*$needle*") {
                Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        throw "Basic-user process did not finish within 12 minutes for $LauncherPath. $runasError"
    }

    $recorded = ([System.IO.File]::ReadAllText($exitFile)).Trim()
    $childExit = 0
    if (-not [int]::TryParse($recorded, [ref]$childExit)) {
        throw "Basic-user exit file contained '$recorded'."
    }
    Write-InstallerTestLog "Basic-user exit=$childExit"
    return $childExit
}

function Invoke-BlinterLauncher {
    param([Parameter(Mandatory)][string]$LauncherPath)

    if (-not (Test-BlinterSessionElevated)) {
        Write-InstallerTestLog "Starting cmd directly: $LauncherPath"
        $output = & cmd.exe /d /c $LauncherPath
        if ($output) {
            Write-InstallerTestLog (($output | Out-String).Trim())
        }
        return $LASTEXITCODE
    }

    return Invoke-BlinterBasicUser -LauncherPath $LauncherPath
}

function Initialize-BlinterLauncherFile {
    param(
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$Body
    )

    $normalized = $Body -replace "`r`n", "`n" -replace "`r", "`n"
    $crlf = ($normalized.TrimEnd("`n") + "`n") -replace "`n", "`r`n"
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Destination, $crlf, $encoding)
}

function Invoke-BlinterBatch {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$Mode,
        [Parameter(Mandatory)][string]$TempRoot,
        [Parameter(Mandatory)][string]$Label
    )

    $logPath = Join-Path $TempRoot ($Label + ".log")
    $launcherPath = Join-Path $TempRoot ($Label + ".cmd")
    if ($Mode -eq "readme") {
        $body = @"
@echo off
(call "$ScriptPath" || cd .) > "$logPath" 2>&1
exit /b %ERRORLEVEL%
"@
    } elseif ($Mode -eq "direct") {
        $body = @"
@echo off
call "$ScriptPath" > "$logPath" 2>&1
exit /b %ERRORLEVEL%
"@
    } else {
        throw "Unknown installer invocation mode: $Mode"
    }

    Initialize-BlinterLauncherFile -Destination $launcherPath -Body $body
    Write-InstallerTestLog "Running $ScriptPath mode=$Mode"
    $exitCode = Invoke-BlinterLauncher -LauncherPath $launcherPath
    if (-not (Test-Path -LiteralPath $logPath)) {
        throw "Installer log was not created: $logPath (exit $exitCode)"
    }
    $logBytes = [System.IO.File]::ReadAllBytes($logPath)
    $log = [System.Text.Encoding]::ASCII.GetString($logBytes)
    Write-InstallerTestLog "Finished $Label exit=$exitCode"
    return [PSCustomObject]@{
        ExitCode = $exitCode
        Log      = $log
    }
}

function Assert-BlinterLog {
    param(
        [Parameter(Mandatory)][string]$Log,
        [Parameter(Mandatory)][string[]]$Required,
        [Parameter(Mandatory)][string[]]$Forbidden
    )

    foreach ($pattern in $Required) {
        if ($Log -notmatch $pattern) {
            throw "Log did not match '$pattern'.`n$Log"
        }
    }
    foreach ($pattern in $Forbidden) {
        if ($Log -match $pattern) {
            throw "Log matched forbidden pattern '$pattern'.`n$Log"
        }
    }
}

function Test-BlinterBinOnUserPath {
    param([Parameter(Mandatory)][string]$BinPath)

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) {
        return $false
    }
    $segments = @($userPath -split ";" | Where-Object { $_ -ne "" })
    foreach ($segment in $segments) {
        if ($segment -eq $BinPath) {
            return $true
        }
    }
    return $false
}

function Assert-BlinterInstalled {
    $layout = Get-BlinterInstallLayout
    if (-not (Test-Path -LiteralPath $layout.Exe)) {
        throw "blinter.exe was not installed at $($layout.Exe)"
    }
    # Width keeps a long package path on one line. The release marker stores
    # only the vX.Y.Z tag; --version also names the runtime.
    $versionOutput = (& $layout.Exe --version 2>&1 | Out-String -Width 4096).Trim()
    Write-InstallerTestLog "Installed version: $versionOutput"
    $versionPattern = '^v(\d+\.\d+\.\d+) \((standalone exe|Python \d+\.\d+, .+)\)$'
    if ($versionOutput -notmatch $versionPattern) {
        throw "Unexpected blinter --version output: $versionOutput"
    }
    $versionTag = "v$($Matches[1])"
    $marker = ([System.IO.File]::ReadAllText($layout.ReleaseFile)).Trim()
    if ($marker -ne $versionTag) {
        throw "Release marker '$marker' does not match blinter version '$versionTag' from '$versionOutput'"
    }
    if (-not (Test-BlinterBinOnUserPath -BinPath $layout.Bin)) {
        throw "User PATH does not contain $($layout.Bin)"
    }
}

function Assert-BlinterRemoved {
    $layout = Get-BlinterInstallLayout
    if (Test-Path -LiteralPath $layout.Exe) {
        throw "blinter.exe still exists at $($layout.Exe)"
    }
    if (Test-Path -LiteralPath $layout.Root) {
        throw "Install directory still exists at $($layout.Root)"
    }
    if (Test-BlinterBinOnUserPath -BinPath $layout.Bin) {
        throw "User PATH still contains $($layout.Bin)"
    }
    Write-InstallerTestLog "Install directory and User PATH entry removed"
}

function Assert-BlinterChildIsUnelevated {
    param([Parameter(Mandatory)][string]$TempRoot)

    $probePath = Join-Path $TempRoot "elevation-probe.cmd"
    $markerPath = Join-Path $TempRoot "elevation-probe-ran.txt"
    Initialize-BlinterLauncherFile -Destination $probePath -Body @"
@echo off
> "$markerPath" echo RAN
whoami /groups | findstr /c:"Mandatory Label" >> "$markerPath"
net session >nul 2>&1
exit /b %ERRORLEVEL%
"@
    $exitCode = Invoke-BlinterLauncher -LauncherPath $probePath
    $markerText = ""
    if (Test-Path -LiteralPath $markerPath) {
        $markerText = ([System.IO.File]::ReadAllText($markerPath)).Trim()
    }
    Write-InstallerTestLog "Unelevated probe exit=$exitCode marker=$markerText"
    if (-not $markerText) {
        throw "Unelevated probe did not run (exit $exitCode)."
    }
    if ($exitCode -eq 0) {
        throw "Installer process is still elevated. install_blinter.cmd refuses administrator tokens. $markerText"
    }
}

function Invoke-BlinterCleanupUninstall {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$TempRoot
    )

    $result = Invoke-BlinterBatch -ScriptPath $ScriptPath -Mode "direct" -TempRoot $TempRoot -Label "cleanup-uninstall"
    if ($result.ExitCode -ne 0) {
        Write-InstallerTestLog "Cleanup uninstall exited $($result.ExitCode)"
        Write-Host $result.Log
    }
}

function Invoke-BlinterInstallScenario {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$InstallScript,
        [Parameter(Mandatory)][string]$UninstallScript,
        [Parameter(Mandatory)][string]$Mode,
        [Parameter(Mandatory)][string]$TempRoot
    )

    Write-InstallerTestLog "Scenario $Name ($Mode)"
    $installed = Invoke-BlinterBatch -ScriptPath $InstallScript -Mode $Mode -TempRoot $TempRoot -Label "$Name-install"
    if ($installed.ExitCode -ne 0) {
        throw "Install exited $($installed.ExitCode).`n$($installed.Log)"
    }
    Assert-BlinterLog -Log $installed.Log -Required @(
        "Installing Blinter",
        "(?m)^OK\s*$",
        "SUCCESS: Blinter",
        "installed successfully"
    ) -Forbidden @(
        "Installation failed",
        "cannot find the batch label",
        "SHA256 digest mismatch",
        "does not exist. Provide the path"
    )
    Assert-BlinterInstalled

    $removed = Invoke-BlinterBatch -ScriptPath $UninstallScript -Mode $Mode -TempRoot $TempRoot -Label "$Name-uninstall"
    if ($removed.ExitCode -ne 0) {
        throw "Uninstall exited $($removed.ExitCode).`n$($removed.Log)"
    }
    Assert-BlinterLog -Log $removed.Log -Required @(
        "SUCCESS: Blinter uninstalled successfully"
    ) -Forbidden @(
        "Uninstallation failed",
        "cannot find the batch label",
        "completed with warnings",
        "Nothing to uninstall"
    )
    Assert-BlinterRemoved
    Write-InstallerTestLog "Scenario $Name passed"
}

function ConvertTo-BlinterLfScript {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    $text = [System.IO.File]::ReadAllText($Source)
    $text = $text -replace "`r`n", "`n" -replace "`r", "`n"
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Destination, $text, $encoding)
    $bytes = [System.IO.File]::ReadAllBytes($Destination)
    if ($bytes -contains 13) {
        throw "LF copy still contains CR bytes: $Destination"
    }
    Write-InstallerTestLog "Wrote LF copy $Destination"
}

# Executing the file runs the scenarios. Dot-sourcing only defines the helpers.
if ($MyInvocation.InvocationName -ne '.') {
if ($env:OS -ne "Windows_NT") {
    throw "Installer script tests require Windows."
}

$installScript = Join-Path $RepoRoot "scripts\install_blinter.cmd"
$uninstallScript = Join-Path $RepoRoot "scripts\uninstall_blinter.cmd"
foreach ($required in @($installScript, $uninstallScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required script not found: $required"
    }
}

$tempRoot = Join-Path $env:TEMP ("blinter-install-ci-" + [Guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
Write-InstallerTestLog "Work directory: $tempRoot"
Write-InstallerTestLog "Repository: $RepoRoot"
$callerElevated = Test-BlinterSessionElevated
Write-InstallerTestLog "Caller is elevated=$callerElevated"
if ($callerElevated) {
    ConvertTo-BlinterMediumIntegrity -Path $tempRoot
}

try {
    Assert-BlinterChildIsUnelevated -TempRoot $tempRoot
    Invoke-BlinterCleanupUninstall -ScriptPath $uninstallScript -TempRoot $tempRoot
    Invoke-BlinterInstallScenario `
        -Name "repository" `
        -InstallScript $installScript `
        -UninstallScript $uninstallScript `
        -Mode "direct" `
        -TempRoot $tempRoot

    $lfDir = Join-Path $tempRoot "lf"
    New-Item -ItemType Directory -Path $lfDir | Out-Null
    $lfInstall = Join-Path $lfDir "install_blinter.cmd"
    $lfUninstall = Join-Path $lfDir "uninstall_blinter.cmd"
    ConvertTo-BlinterLfScript -Source $installScript -Destination $lfInstall
    ConvertTo-BlinterLfScript -Source $uninstallScript -Destination $lfUninstall
    Invoke-BlinterInstallScenario `
        -Name "github-raw-lf" `
        -InstallScript $lfInstall `
        -UninstallScript $lfUninstall `
        -Mode "readme" `
        -TempRoot $tempRoot

    Write-InstallerTestLog "Installer and uninstaller passed"
} finally {
    try {
        Invoke-BlinterCleanupUninstall -ScriptPath $uninstallScript -TempRoot $tempRoot
    } catch {
        Write-InstallerTestLog "Cleanup uninstall failed: $($_.Exception.Message)"
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
}
