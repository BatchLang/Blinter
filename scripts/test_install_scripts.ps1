#Requires -Version 5.1
<#
.SYNOPSIS
    Install and uninstall Blinter by running the real batch scripts.

.DESCRIPTION
    Used by Windows CI. Runs scripts/install_blinter.cmd and
    scripts/uninstall_blinter.cmd, then repeats with Unix line endings and the
    README "(call script || cd .)" invocation. GitHub-hosted Windows runners
    are elevated, and both scripts refuse an administrator token, so an
    elevated caller is restarted from the interactive explorer token.
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

$script:UnelevatedTypeReady = $false

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

function Initialize-BlinterUnelevatedType {
    if ($script:UnelevatedTypeReady) {
        return
    }

    $source = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class BlinterUnelevatedProcess {
    const uint TokenAssignPrimary = 0x0001;
    const uint TokenDuplicate = 0x0002;
    const uint TokenQuery = 0x0008;
    const uint TokenAdjustDefault = 0x0080;
    const int SecurityImpersonation = 2;
    const int TokenPrimary = 1;
    const int CreateUnicodeEnvironment = 0x00000400;
    const int CreateNoWindow = 0x08000000;
    const uint Infinite = 0xFFFFFFFF;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct StartupInfo {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInformation {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool OpenProcessToken(IntPtr processHandle, uint desiredAccess, out IntPtr tokenHandle);

    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool DuplicateTokenEx(
        IntPtr existingToken,
        uint desiredAccess,
        IntPtr tokenAttributes,
        int impersonationLevel,
        int tokenType,
        out IntPtr newToken);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CreateProcessWithTokenW(
        IntPtr token,
        int logonFlags,
        string applicationName,
        string commandLine,
        int creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref StartupInfo startupInfo,
        out ProcessInformation processInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr handle);

    public static int Start(IntPtr processHandle, string commandLine, string workingDirectory) {
        IntPtr token = IntPtr.Zero;
        IntPtr primary = IntPtr.Zero;
        ProcessInformation processInfo = new ProcessInformation();
        try {
            if (!OpenProcessToken(processHandle, TokenDuplicate | TokenQuery, out token)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            // Omit TOKEN_ADJUST_SESSIONID. It requires SeTcbPrivilege, which an elevated
            // administrator token on a GitHub-hosted runner does not have.
            uint access = TokenAssignPrimary | TokenDuplicate | TokenQuery | TokenAdjustDefault;
            if (!DuplicateTokenEx(token, access, IntPtr.Zero, SecurityImpersonation, TokenPrimary, out primary)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            StartupInfo startup = new StartupInfo();
            startup.cb = Marshal.SizeOf(typeof(StartupInfo));
            int flags = CreateUnicodeEnvironment | CreateNoWindow;
            if (!CreateProcessWithTokenW(primary, 0, null, commandLine, flags, IntPtr.Zero, workingDirectory, ref startup, out processInfo)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            WaitForSingleObject(processInfo.hProcess, Infinite);
            uint code;
            if (!GetExitCodeProcess(processInfo.hProcess, out code)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return unchecked((int)code);
        } finally {
            if (processInfo.hThread != IntPtr.Zero) {
                CloseHandle(processInfo.hThread);
            }
            if (processInfo.hProcess != IntPtr.Zero) {
                CloseHandle(processInfo.hProcess);
            }
            if (primary != IntPtr.Zero) {
                CloseHandle(primary);
            }
            if (token != IntPtr.Zero) {
                CloseHandle(token);
            }
        }
    }
}
'@
    Add-Type -TypeDefinition $source -Language CSharp
    $script:UnelevatedTypeReady = $true
    Write-InstallerTestLog "Compiled unelevated process starter"
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

    Initialize-BlinterUnelevatedType
    $explorers = @(Get-Process -Name explorer -ErrorAction SilentlyContinue)
    if ($explorers.Count -eq 0) {
        throw "explorer.exe is not running, so an elevated CI process cannot drop to a normal user token."
    }

    $commandLine = 'cmd.exe /d /c "{0}"' -f $LauncherPath
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($explorer in $explorers) {
        try {
            Write-InstallerTestLog "Starting unelevated cmd from explorer pid $($explorer.Id)"
            return [BlinterUnelevatedProcess]::Start($explorer.Handle, $commandLine, $env:SystemDrive + "\")
        } catch {
            $errors.Add($_.Exception.Message)
        }
    }

    throw "Could not start an unelevated cmd. $($errors -join '; ')"
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
    Initialize-BlinterLauncherFile -Destination $probePath -Body @"
@echo off
net session >nul 2>&1
exit /b %ERRORLEVEL%
"@
    $exitCode = Invoke-BlinterLauncher -LauncherPath $probePath
    Write-InstallerTestLog "Unelevated probe exit=$exitCode (non-zero means the scripts will accept it)"
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
    Initialize-BlinterUnelevatedType
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
