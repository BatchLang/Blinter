#Requires -Version 5.1
<#
.SYNOPSIS
    Install and uninstall Blinter by running the real batch scripts.

.DESCRIPTION
    Used by Windows CI. Runs scripts/install_blinter.cmd and
    scripts/uninstall_blinter.cmd, then repeats with Unix line endings and the
    README "(call script || cd .)" invocation. GitHub-hosted Windows runners
    are elevated, and both scripts refuse an administrator token, so an
    elevated caller runs them in a limited scheduled task.
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

function Get-BlinterLimitedTaskResult {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][datetime]$Deadline
    )

    # 0x41301 = currently running, 0x41303 = has not run yet.
    $pendingResults = @(0x41301, 0x41303)
    $queuedSince = $null
    $finished = $false
    $state = "Unknown"
    $result = -1
    do {
        Start-Sleep -Milliseconds 250
        $task = Get-ScheduledTask -TaskName $TaskName
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        $state = [string]$task.State
        $result = [int]$info.LastTaskResult
        if ($state -eq "Queued") {
            if (-not $queuedSince) {
                $queuedSince = Get-Date
            }
            $queuedFor = ((Get-Date) - $queuedSince).TotalSeconds
            if ($queuedFor -gt 20) {
                throw "Task $TaskName stayed queued for 20 seconds (result $result)"
            }
        } else {
            $queuedSince = $null
        }
        $finished = $state -ne "Running" -and $state -ne "Queued" -and $pendingResults -notcontains $result
    } while (-not $finished -and (Get-Date) -lt $Deadline)

    if (-not $finished) {
        throw "Task $TaskName timed out in state $state (result $result)"
    }
    return $result
}

function Invoke-BlinterLimitedTask {
    param([Parameter(Mandatory)][string]$LauncherPath)

    # CreateProcessWithTokenW returns access denied on GitHub-hosted runners.
    # A limited scheduled task runs as the same user without an administrator token.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 12)
    $action = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\cmd.exe" `
        -Argument "/d /c `"$LauncherPath`"" `
        -WorkingDirectory "$env:SystemDrive\"
    $account = "$env:USERDOMAIN\$env:USERNAME"
    $whoamiAccount = (whoami).Trim()
    $candidates = @(
        @{ Name = "domain-user"; UserId = $account; LogonType = "" },
        @{ Name = "whoami"; UserId = $whoamiAccount; LogonType = "Interactive" }
    )
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $candidates) {
        $taskName = "BlinterInstallCI-" + [Guid]::NewGuid().ToString("n")
        try {
            if ($candidate.LogonType) {
                $principal = New-ScheduledTaskPrincipal `
                    -UserId $candidate.UserId `
                    -LogonType $candidate.LogonType `
                    -RunLevel Limited
            } else {
                $principal = New-ScheduledTaskPrincipal -UserId $candidate.UserId -RunLevel Limited
            }
            Register-ScheduledTask `
                -TaskName $taskName `
                -Action $action `
                -Principal $principal `
                -Settings $settings `
                -Force | Out-Null
            Write-InstallerTestLog "Starting limited scheduled task $taskName account=$($candidate.UserId) logon=$($candidate.Name)"
            Start-ScheduledTask -TaskName $taskName
            $result = Get-BlinterLimitedTaskResult -TaskName $taskName -Deadline (Get-Date).AddMinutes(12)
            Write-InstallerTestLog "Limited task $taskName result=$result"
            return $result
        } catch {
            $errors.Add("$($candidate.Name): $($_.Exception.Message)")
            Write-InstallerTestLog "Limited task via $($candidate.Name) failed: $($_.Exception.Message)"
        } finally {
            $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if ($existing -and [string]$existing.State -eq "Running") {
                Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            }
            if ($existing) {
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
            }
        }
    }

    throw "Could not start an unelevated cmd. $($errors -join '; ')"
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

    return Invoke-BlinterLimitedTask -LauncherPath $LauncherPath
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
    $versionOutput = (& $layout.Exe --version | Out-String).Trim()
    Write-InstallerTestLog "Installed version: $versionOutput"
    if ($versionOutput -notmatch '^v\d+\.\d+\.\d+$') {
        throw "Unexpected blinter --version output: $versionOutput"
    }
    $marker = ([System.IO.File]::ReadAllText($layout.ReleaseFile)).Trim()
    if ($marker -ne $versionOutput) {
        throw "Release marker '$marker' does not match blinter --version '$versionOutput'"
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
echo RAN> "$markerPath"
net session >nul 2>&1
exit /b %ERRORLEVEL%
"@
    $exitCode = Invoke-BlinterLauncher -LauncherPath $probePath
    Write-InstallerTestLog "Unelevated probe exit=$exitCode (non-zero means the scripts will accept it)"
    if (-not (Test-Path -LiteralPath $markerPath)) {
        throw "Unelevated probe did not run (exit $exitCode)."
    }
    if ($exitCode -eq 0) {
        throw "Installer process is still elevated. install_blinter.cmd refuses administrator tokens."
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
