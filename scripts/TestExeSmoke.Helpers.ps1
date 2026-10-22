#Requires -Version 5.1
<#
.SYNOPSIS
    Helper functions for blinter.exe smoke testing.
#>
Set-StrictMode -Version Latest

$script:SmokeTestState = @{
    Passed   = 0
    Total    = 0
    Failures = [System.Collections.Generic.List[string]]::new()
}

function Initialize-SmokeTestState {
    $script:SmokeTestState.Passed = 0
    $script:SmokeTestState.Total = 0
    $script:SmokeTestState.Failures = [System.Collections.Generic.List[string]]::new()
}

function Get-SmokeTestState {
    return [PSCustomObject]@{
        Passed   = $script:SmokeTestState.Passed
        Total    = $script:SmokeTestState.Total
        Failures = $script:SmokeTestState.Failures
    }
}

function Format-CliArgument {
    param([string[]]$CliArgs)

    if (-not $CliArgs -or $CliArgs.Count -eq 0) {
        return ""
    }

    return ($CliArgs | ForEach-Object {
            if ($_ -match '\s') {
                '"' + ($_ -replace '"', '""') + '"'
            }
            else {
                $_
            }
        }) -join " "
}

function Invoke-BlinterProcess {
    param(
        [string]$Binary,
        [string[]]$CliArgs,
        [string]$WorkingDirectory
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Binary
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.Arguments = Format-CliArgument -CliArgs $CliArgs

    $process = [System.Diagnostics.Process]::Start($psi)
    if (-not $process) {
        throw "Failed to start process: $Binary"
    }

    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    return [PSCustomObject]@{
        ExitCode = $process.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
        Output   = "$stdout$stderr"
    }
}

function Test-NoRuntimeCrash {
    param([string]$Output)

    if ($Output -match 'Traceback \(most recent call last\)|ModuleNotFoundError|ImportError') {
        throw "runtime crash detected: $Output"
    }
}

function Test-LintExitCode {
    param([int]$ExitCode)

    if ($ExitCode -notin 0, 1) {
        throw "unexpected exit code $ExitCode"
    }
}

function Get-PeMachineType {
    <#
    .SYNOPSIS
        Return the COFF Machine field from a PE executable.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $header = New-Object byte[] 64
        $headerRead = $stream.Read($header, 0, $header.Length)
        if ($headerRead -lt 64) {
            throw "PE header is truncated: $Path"
        }
        if ($header[0] -ne 0x4D -or $header[1] -ne 0x5A) {
            throw "Missing MZ signature: $Path"
        }
        # e_lfanew is the offset from the start of the file to the PE signature.
        $peOffset = [System.BitConverter]::ToInt32($header, 0x3C)
        if ($peOffset -lt 0) {
            throw "Invalid PE offset: $Path"
        }
        $stream.Position = $peOffset
        $pe = New-Object byte[] 6
        $peRead = $stream.Read($pe, 0, $pe.Length)
        if ($peRead -lt 6) {
            throw "PE signature is truncated: $Path"
        }
        $signatureOk = (
            $pe[0] -eq 0x50 -and
            $pe[1] -eq 0x45 -and
            $pe[2] -eq 0 -and
            $pe[3] -eq 0
        )
        if (-not $signatureOk) {
            throw "Missing PE signature: $Path"
        }
        return [System.BitConverter]::ToUInt16($pe, 4)
    }
    finally {
        $stream.Dispose()
    }
}

function Invoke-SmokeTest {
    param(
        [string]$Name,
        [scriptblock]$Check
    )

    $script:SmokeTestState.Total++
    try {
        & $Check
        $script:SmokeTestState.Passed++
        Write-Output "PASS: $Name"
    }
    catch {
        $script:SmokeTestState.Failures.Add("$Name - $($_.Exception.Message)")
        Write-Output "FAIL: $Name - $($_.Exception.Message)"
    }
}

function Get-JsonReport {
    param([string]$Stdout)

    return $Stdout.Trim() | ConvertFrom-Json
}

function Get-IssueRuleCode {
    param($Report)

    return @($Report.issues | ForEach-Object { $_.code })
}

function New-ExeSmokeFixtureRoot {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param()

    if (-not $PSCmdlet.ShouldProcess("temporary smoke-test fixtures", "Create")) {
        throw "Fixture creation was not confirmed."
    }

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $fixtureRoot = New-Item -ItemType Directory -Path (
        Join-Path ([System.IO.Path]::GetTempPath()) ("blinter-exe-smoke-" + [guid]::NewGuid().ToString())
    )

    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "sample.bat"),
        "@echo off`r`necho hello`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "sample.cmd"),
        "@echo off`r`necho cmd test`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "good_script.bat"),
        "@echo off`r`nREM clean script`r`necho Done`r`nexit /b 0`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "bad_script.bat"),
        "echo off`r`ngoto nonexistent`r`nset UNQUOTED=value`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "utf8.bat"),
        "@echo off`r`necho cafe resume`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllBytes(
        (Join-Path $fixtureRoot "utf16.bat"),
        [byte[]](0xFF, 0xFE) + [System.Text.Encoding]::Unicode.GetBytes("@echo off`r`necho utf16`r`n")
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "readme.txt"),
        "not a batch file",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "blinter.ini"),
        "[rules]`r`ndisabled_rules = S001`r`n",
        $utf8NoBom
    )

    New-Item -ItemType Directory -Path (Join-Path $fixtureRoot "subdir") | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixtureRoot "nested\deep") -Force | Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "subdir\sub_script.bat"),
        "@echo off`r`necho sub`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "nested\deep\deep_script.bat"),
        "@echo off`r`necho deep`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "caller.bat"),
        "@echo off`r`ncall subdir\sub_script.bat`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "chain_a.bat"),
        "@echo off`r`ncall chain_b.bat`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "chain_b.bat"),
        "@echo off`r`nset VAR=1`r`necho %VAR%`r`n",
        $utf8NoBom
    )

    return $fixtureRoot.FullName
}
