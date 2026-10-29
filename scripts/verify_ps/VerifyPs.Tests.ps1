#Requires -Version 5.1
BeforeAll {
    $script:VerifyPsRoot = $PSScriptRoot
    $script:RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:AnalyzerSettings = Join-Path (Join-Path $script:RepoRoot 'scripts') 'PSScriptAnalyzerSettings.psd1'

    function Invoke-VerifyPsScript {
        param(
            [Parameter(Mandatory)]
            [string]$Name,
            [string[]]$Arguments = @()
        )

        # Pester runs with ErrorActionPreference Stop, which would turn the script's stderr into an exception.
        $ErrorActionPreference = 'Continue'
        $scriptPath = Join-Path $script:VerifyPsRoot $Name
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath @Arguments 2>&1
        return [PSCustomObject]@{
            ExitCode = $LASTEXITCODE
            Output   = ($output | Out-String)
        }
    }

    function Initialize-FakeRepository {
        param(
            [Parameter(Mandatory)]
            [string]$Path,
            [Parameter(Mandatory)]
            [string]$ScriptBody
        )

        $scriptsDir = Join-Path $Path 'scripts'
        New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $scriptsDir 'Sample.ps1') -Value $ScriptBody
        return $Path
    }
}

Describe 'Test-PowerShellSyntax.ps1' {
    It 'exits 0 for a valid script' {
        $file = Join-Path $TestDrive 'valid.ps1'
        Set-Content -LiteralPath $file -Value 'Write-Output "hello"'
        $result = Invoke-VerifyPsScript -Name 'Test-PowerShellSyntax.ps1' -Arguments @('-Path', $file)
        $result.ExitCode | Should -Be 0
    }

    It 'exits 1 and prints the error for an invalid script' {
        $file = Join-Path $TestDrive 'invalid.ps1'
        Set-Content -LiteralPath $file -Value 'if ($true { Write-Output "hello" }'
        $result = Invoke-VerifyPsScript -Name 'Test-PowerShellSyntax.ps1' -Arguments @('-Path', $file)
        $result.ExitCode | Should -Be 1
        $result.Output | Should -Not -BeNullOrEmpty
    }
}

Describe 'Invoke-ScriptAnalysis.ps1' {
    It 'exits 0 when every script is clean' {
        $root = Initialize-FakeRepository -Path (Join-Path $TestDrive 'clean') -ScriptBody 'Write-Output "hello"'
        $result = Invoke-VerifyPsScript -Name 'Invoke-ScriptAnalysis.ps1' -Arguments @('-Root', $root, '-SettingsPath', $script:AnalyzerSettings)
        $result.ExitCode | Should -Be 0 -Because $result.Output
        $result.Output | Should -Match 'found no issues'
    }

    It 'exits 1 and names the rule when a script has a warning' {
        $root = Initialize-FakeRepository -Path (Join-Path $TestDrive 'dirty') -ScriptBody '$unused = 1'
        $result = Invoke-VerifyPsScript -Name 'Invoke-ScriptAnalysis.ps1' -Arguments @('-Root', $root, '-SettingsPath', $script:AnalyzerSettings)
        $result.ExitCode | Should -Be 1
        $result.Output | Should -Match 'PSUseDeclaredVarsMoreThanAssignments'
    }

    It 'analyzes scripts in nested folders and under tests' {
        $root = Initialize-FakeRepository -Path (Join-Path $TestDrive 'nested') -ScriptBody 'Write-Output "hello"'
        $nested = Join-Path $root 'tests\deep'
        New-Item -ItemType Directory -Path $nested -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $nested 'Bad.ps1') -Value '$unused = 1'
        $result = Invoke-VerifyPsScript -Name 'Invoke-ScriptAnalysis.ps1' -Arguments @('-Root', $root, '-SettingsPath', $script:AnalyzerSettings)
        $result.ExitCode | Should -Be 1
        $result.Output | Should -Match 'Analyzing 2 PowerShell files'
    }

    It 'exits 1 when there is nothing to analyze' {
        $root = Join-Path $TestDrive 'empty'
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        $result = Invoke-VerifyPsScript -Name 'Invoke-ScriptAnalysis.ps1' -Arguments @('-Root', $root, '-SettingsPath', $script:AnalyzerSettings)
        $result.ExitCode | Should -Not -Be 0
    }
}

Describe 'Every PowerShell file in this folder' {
    It 'parses cleanly (<Name>)' -ForEach @(
        @{ Name = 'Install-VerifyModules.ps1' },
        @{ Name = 'Invoke-PesterTests.ps1' },
        @{ Name = 'Invoke-ScriptAnalysis.ps1' },
        @{ Name = 'Test-PowerShellSyntax.ps1' }
    ) {
        $file = Join-Path $script:VerifyPsRoot $Name
        $result = Invoke-VerifyPsScript -Name 'Test-PowerShellSyntax.ps1' -Arguments @('-Path', $file)
        $result.ExitCode | Should -Be 0 -Because $result.Output
    }

    It 'is covered by the parse list above' {
        $listed = @('Install-VerifyModules.ps1', 'Invoke-PesterTests.ps1', 'Invoke-ScriptAnalysis.ps1', 'Test-PowerShellSyntax.ps1')
        $actual = Get-ChildItem -LiteralPath $script:VerifyPsRoot -Filter '*.ps1' -File |
            Where-Object { $_.Name -notlike '*.Tests.ps1' } |
            Select-Object -ExpandProperty Name
        $actual | Sort-Object | Should -Be ($listed | Sort-Object)
    }
}
