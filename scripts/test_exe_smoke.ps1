#Requires -Version 5.1
<#
.SYNOPSIS
    Smoke tests for the Nuitka-built blinter.exe and parity with python -m blinter.

.DESCRIPTION
    Used by CI and locally after building dist\blinter.exe. Creates ephemeral fixtures,
    runs functional exe scenarios, then compares exe output to the editable Python CLI.

.PARAMETER ExePath
    Path to blinter.exe (default: dist\blinter.exe under RepoRoot).

.PARAMETER RepoRoot
    Repository root directory (default: parent of the scripts folder).

.PARAMETER PythonPath
    Python interpreter for parity checks (default: venv\Scripts\python.exe under RepoRoot).

.PARAMETER ExpectedArch
    When set to x64 or arm64, the first check reads the executable's PE Machine field.
    Omit it for a local run that does not care which architecture was compiled.
#>
[CmdletBinding()]
param(
    [string]$ExePath = "",
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$ExpectedArch = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "TestExeSmoke.Helpers.ps1")

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if (-not $ExePath) {
    $ExePath = Join-Path $RepoRoot "dist\blinter.exe"
}

if (-not $PythonPath) {
    $PythonPath = Join-Path $RepoRoot "venv\Scripts\python.exe"
}

$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python interpreter not found for parity checks: $PythonPath"
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

$pyprojectPath = Join-Path $RepoRoot "pyproject.toml"
$versionMatch = Select-String -Path $pyprojectPath -Pattern '^version = "(.+)"'
if (-not $versionMatch) {
    throw "Could not read project version from $pyprojectPath"
}
$ExpectedVersion = $versionMatch.Matches[0].Groups[1].Value

$peMachineByArch = @{
    x64   = [uint16]0x8664
    arm64 = [uint16]0xAA64
}
if ($ExpectedArch -and -not $peMachineByArch.ContainsKey($ExpectedArch)) {
    throw "ExpectedArch must be x64 or arm64. Got: $ExpectedArch"
}

Initialize-SmokeTestState

$FixtureRoot = New-ExeSmokeFixtureRoot

try {
    if ($ExpectedArch) {
        Invoke-SmokeTest "exe 00 architecture" {
            $machine = Get-PeMachineType -Path $ExePath
            $expectedMachine = $peMachineByArch[$ExpectedArch]
            if ($machine -ne $expectedMachine) {
                throw (
                    "expected PE machine 0x{0:X4} for {1}, got 0x{2:X4}" -f
                    $expectedMachine, $ExpectedArch, $machine
                )
            }
        }
    }

    Invoke-SmokeTest "exe 01 version" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @("--version") -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if ($result.Output -notmatch [regex]::Escape($ExpectedVersion)) {
            throw "expected version $ExpectedVersion in output, got: $($result.Output)"
        }
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 02 help" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @("--help") -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if ($result.Output -notmatch "Usage:") {
            throw "expected usage text"
        }
    }

    Invoke-SmokeTest "exe 03 no args help" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @() -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if ($result.Output -notmatch "Usage:") {
            throw "expected help output"
        }
    }

    Invoke-SmokeTest "exe 04 sample summary" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "sample.bat", "--summary", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 05 missing file" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "missing.bat", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -eq 0) {
            throw "expected non-zero exit for missing file"
        }
    }

    Invoke-SmokeTest "exe 06 sample cmd" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "sample.cmd", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 07 bad script rule codes" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "bad_script.bat", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        if ($result.Output -notmatch "E[0-9]{3}|W[0-9]{3}|SEC[0-9]{3}|P[0-9]{3}|S[0-9]{3}") {
            throw "expected rule codes in output"
        }
    }

    Invoke-SmokeTest "exe 08 non-batch rejected" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "readme.txt", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -eq 0) {
            throw "expected non-zero exit"
        }
        if ($result.Output -notmatch "not a batch|Error") {
            throw "expected batch file error message"
        }
    }

    Invoke-SmokeTest "exe 09 json stdout schema" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "sample.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        $report = Get-JsonReport -Stdout $result.Stdout
        foreach ($key in @("blinter_version", "target", "issues", "summary")) {
            if (-not $report.PSObject.Properties.Name.Contains($key)) {
                throw "missing json key $key"
            }
        }
    }

    Invoke-SmokeTest "exe 10 json output file" {
        $reportPath = Join-Path $FixtureRoot "report.json"
        if (Test-Path -LiteralPath $reportPath) {
            Remove-Item -LiteralPath $reportPath -Force
        }
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "sample.bat", "--format", "json", "--output", "report.json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        if ($result.Stdout.Trim().Length -gt 0) {
            throw "expected empty stdout when writing json to file"
        }
        if (-not (Test-Path -LiteralPath $reportPath)) {
            throw "report.json was not created"
        }
        $null = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    }

    Invoke-SmokeTest "exe 11 utf8 non-ascii" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "utf8.bat", "--summary", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 12 utf16 le" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "utf16.bat", "--summary", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 13 follow calls" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "caller.bat", "--follow-calls", "--summary", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 14 config disables rule" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "bad_script.bat", "--config", "blinter.ini", "--summary"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        if ($result.Output -match "\bS001\b") {
            throw "disabled rule S001 was reported"
        }
    }

    Invoke-SmokeTest "exe 15 create config" {
        $configDir = Join-Path $FixtureRoot "create-config"
        New-Item -ItemType Directory -Path $configDir | Out-Null
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "--create-config"
        ) -WorkingDirectory $configDir
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $configDir "blinter.ini"))) {
            throw "blinter.ini was not created"
        }
    }

    Invoke-SmokeTest "exe 16 directory no recursive" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            ".", "--no-recursive", "--summary", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        if ($result.Output -match "deep_script") {
            throw "deep_script should be excluded by --no-recursive"
        }
    }

    Invoke-SmokeTest "exe 17 install script" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "scripts\install_blinter.cmd", "--summary", "--config", "scripts\blinter.ini"
        ) -WorkingDirectory $RepoRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 18 uninstall script" {
        $result = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "scripts\uninstall_blinter.cmd", "--summary", "--config", "scripts\blinter.ini"
        ) -WorkingDirectory $RepoRoot
        Test-LintExitCode -ExitCode $result.ExitCode
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "parity 01 good script" {
        $pythonResult = Invoke-BlinterProcess -Binary $PythonPath -CliArgs @(
            "-m", "blinter", "good_script.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "good_script.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
        $pythonCount = (Get-JsonReport -Stdout $pythonResult.Stdout).issues.Count
        $exeCount = (Get-JsonReport -Stdout $exeResult.Stdout).issues.Count
        if ($pythonCount -ne $exeCount) {
            throw "issue count mismatch py=$pythonCount exe=$exeCount"
        }
    }

    Invoke-SmokeTest "parity 02 bad script codes" {
        $pythonResult = Invoke-BlinterProcess -Binary $PythonPath -CliArgs @(
            "-m", "blinter", "bad_script.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "bad_script.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
        $pythonCodes = (Get-IssueRuleCode -Report (Get-JsonReport -Stdout $pythonResult.Stdout)) -join ","
        $exeCodes = (Get-IssueRuleCode -Report (Get-JsonReport -Stdout $exeResult.Stdout)) -join ","
        if ($pythonCodes -ne $exeCodes) {
            throw "rule codes differ py=$pythonCodes exe=$exeCodes"
        }
    }

    Invoke-SmokeTest "parity 03 follow calls chain" {
        $pythonResult = Invoke-BlinterProcess -Binary $PythonPath -CliArgs @(
            "-m", "blinter", "chain_a.bat", "--follow-calls", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "chain_a.bat", "--follow-calls", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
        $pythonCount = (Get-JsonReport -Stdout $pythonResult.Stdout).issues.Count
        $exeCount = (Get-JsonReport -Stdout $exeResult.Stdout).issues.Count
        if ($pythonCount -ne $exeCount) {
            throw "issue count mismatch py=$pythonCount exe=$exeCount"
        }
    }

    Invoke-SmokeTest "parity 04 utf16" {
        $pythonResult = Invoke-BlinterProcess -Binary $PythonPath -CliArgs @(
            "-m", "blinter", "utf16.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "utf16.bat", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
    }

    Invoke-SmokeTest "parity 05 sample cmd" {
        $pythonResult = Invoke-BlinterProcess -Binary $PythonPath -CliArgs @(
            "-m", "blinter", "sample.cmd", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BlinterProcess -Binary $ExePath -CliArgs @(
            "sample.cmd", "--format", "json", "--no-config"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
        $pythonCount = (Get-JsonReport -Stdout $pythonResult.Stdout).issues.Count
        $exeCount = (Get-JsonReport -Stdout $exeResult.Stdout).issues.Count
        if ($pythonCount -ne $exeCount) {
            throw "issue count mismatch py=$pythonCount exe=$exeCount"
        }
    }

    $state = Get-SmokeTestState
    Write-Output "---"
    Write-Output "RESULT: $($state.Passed) / $($state.Total) passed"

    if ($state.Failures.Count -gt 0) {
        Write-Output "FAILURES:"
        foreach ($failure in $state.Failures) {
            Write-Output "  $failure"
        }
        exit 1
    }
}
finally {
    if (Test-Path -LiteralPath $FixtureRoot) {
        Remove-Item -LiteralPath $FixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
