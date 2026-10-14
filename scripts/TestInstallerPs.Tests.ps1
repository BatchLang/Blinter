#Requires -Version 5.1
BeforeAll {
    . (Join-Path $PSScriptRoot 'InstallerPs.Helpers.ps1')
    $script:ScriptsRoot = $PSScriptRoot
    $script:InstallerPsRoot = Join-Path $PSScriptRoot 'installer_ps'
    $script:AnalyzerSettings = Join-Path $PSScriptRoot 'PSScriptAnalyzerSettings.psd1'
}

Describe 'Installer batch PowerShell parity' {
    It 'matches fixture content for each write_*_script block' {
        $pairs = Get-InstallerPsParityPairs -ScriptsRoot $script:ScriptsRoot -InstallerPsRoot $script:InstallerPsRoot
        $pairs.Count | Should -Be 6

        foreach ($pair in $pairs) {
            $normalizedExtracted = Normalize-InstallerPsText -Content $pair.Extracted
            $normalizedFixture = Normalize-InstallerPsText -Content $pair.FixtureBody
            $normalizedExtracted | Should -Be $normalizedFixture `
                -Because "parity failed for $($pair.CmdFile):$($pair.Label) -> $($pair.Fixture)"
        }
    }
}

Describe 'Installer PowerShell PSScriptAnalyzer' {
    It 'reports no warnings for installer fixtures and smoke scripts' {
        if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
            Set-ItResult -Inconclusive -Because 'PSScriptAnalyzer is not installed'
            return
        }

        $paths = Get-PowerShellAnalyzePaths -ScriptsRoot $script:ScriptsRoot
        $issues = Invoke-InstallerPsScriptAnalyzer -Paths $paths -SettingsPath $script:AnalyzerSettings
        if ($issues) {
            $formatted = $issues | Format-Table RuleName, ScriptName, Line, Message -Wrap | Out-String
            throw "PSScriptAnalyzer findings:`n$formatted"
        }
    }
}

Describe 'Get-LatestBlinterRelease.ps1' {
    It 'outputs NOT_FOUND when no release is available' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        Mock Invoke-RestMethod { return @() }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NOT_FOUND'
    }

    It 'outputs URL tag and digest when a matching asset exists' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        Mock Invoke-RestMethod {
            return @(
                [PSCustomObject]@{
                    prerelease = $false
                    draft      = $false
                    tag_name   = 'v1.1.6'
                    assets     = @(
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6.zip'
                            digest               = 'sha256:abc123'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'https://example.com/Blinter-v1.1.6.zip v1.1.6 sha256:abc123'
    }

    It 'outputs MISSING_DIGEST when the asset has no digest' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        Mock Invoke-RestMethod {
            return @(
                [PSCustomObject]@{
                    prerelease = $false
                    draft      = $false
                    tag_name   = 'v1.1.6'
                    assets     = @(
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6.zip'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'MISSING_DIGEST'
    }
}

Describe 'Test-BlinterArchiveHash.ps1' {
    It 'exits 0 when the archive hash matches the GitHub digest' {
        $tempFile = Join-Path $TestDrive 'archive.zip'
        Set-Content -LiteralPath $tempFile -Value 'blinter-archive' -NoNewline
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $stream = [System.IO.File]::OpenRead($tempFile)
            try {
                $hash = [System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
            } finally { $stream.Dispose() }
        } finally { $sha.Dispose() }
        $script = Get-Content -LiteralPath (Join-Path $script:InstallerPsRoot 'Test-BlinterArchiveHash.ps1') -Raw
        $script = $script.Replace('__BLINTER_TEMP__', ($tempFile -replace '\.zip$', ''))
        $script = $script.Replace('__BLINTER_SHA256__', "sha256:$hash")
        $tempScript = Join-Path $TestDrive 'verify.ps1'
        Set-Content -LiteralPath $tempScript -Value $script
        & $tempScript
        $LASTEXITCODE | Should -Be 0
    }

    It 'exits 1 when the archive hash does not match' {
        $tempFile = Join-Path $TestDrive 'archive.zip'
        Set-Content -LiteralPath $tempFile -Value 'blinter-archive' -NoNewline
        $script = Get-Content -LiteralPath (Join-Path $script:InstallerPsRoot 'Test-BlinterArchiveHash.ps1') -Raw
        $script = $script.Replace('__BLINTER_TEMP__', ($tempFile -replace '\.zip$', ''))
        $script = $script.Replace('__BLINTER_SHA256__', 'sha256:deadbeef')
        $tempScript = Join-Path $TestDrive 'verify.ps1'
        Set-Content -LiteralPath $tempScript -Value $script
        & $tempScript
        $LASTEXITCODE | Should -Be 1
    }
}

Describe 'Update-BlinterUserPath.ps1' {
    AfterEach {
        Remove-Variable -Name BlinterTestUserPath -Scope Global -ErrorAction SilentlyContinue
    }

    It 'appends the bin directory when it is missing from User PATH' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Update-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath 'C:\Existing' `
            -TempScriptPath (Join-Path $TestDrive 'update-path.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Existing;C:\Test\Blinter\bin'
    }

    It 'leaves User PATH unchanged when the bin directory is already present' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Update-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath 'C:\Test\Blinter\bin;C:\Other' `
            -TempScriptPath (Join-Path $TestDrive 'update-path-present.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Test\Blinter\bin;C:\Other'
    }

    It 'appends the bin directory when PATH only contains it as a substring' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Update-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath 'C:\Test\Blinter\bin-extra' `
            -TempScriptPath (Join-Path $TestDrive 'update-path-substring.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Test\Blinter\bin-extra;C:\Test\Blinter\bin'
    }

    It 'uses the bin directory as User PATH when the current value is empty' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Update-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath '' `
            -TempScriptPath (Join-Path $TestDrive 'update-path-empty.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Test\Blinter\bin'
    }
}

Describe 'Remove-BlinterUserPath.ps1' {
    AfterEach {
        Remove-Variable -Name BlinterTestUserPath -Scope Global -ErrorAction SilentlyContinue
    }

    It 'removes the bin directory from User PATH' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Remove-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath 'C:\Alpha;C:\Test\Blinter\bin;C:\Beta' `
            -TempScriptPath (Join-Path $TestDrive 'remove-path.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Alpha;C:\Beta'
    }

    It 'leaves User PATH unchanged when the bin directory is absent' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Remove-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath 'C:\Alpha;C:\Beta' `
            -TempScriptPath (Join-Path $TestDrive 'remove-path-absent.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Alpha;C:\Beta'
    }

    It 'exits 0 when User PATH is empty' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Remove-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath '' `
            -TempScriptPath (Join-Path $TestDrive 'remove-path-empty.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be ''
    }
}

Describe 'Expand-BlinterArchive.ps1' {
    It 'extracts the zip to the destination directory' {
        $payloadDir = Join-Path $TestDrive 'payload-src'
        New-Item -ItemType Directory -Path $payloadDir | Out-Null
        $payloadFile = Join-Path $payloadDir 'readme.txt'
        Set-Content -LiteralPath $payloadFile -Value 'blinter-payload' -NoNewline

        $tempStem = Join-Path $TestDrive 'blinter-temp'
        Compress-Archive -LiteralPath $payloadFile -DestinationPath "$tempStem.zip" -Force

        $tempScript = Join-Path $TestDrive 'expand.ps1'
        New-InstallerPsSubstitutedScript `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Expand-BlinterArchive.ps1') `
            -Replacements @{ '__BLINTER_TEMP__' = $tempStem } `
            -DestinationPath $tempScript

        & $tempScript
        $LASTEXITCODE | Should -Be 0
        $extracted = Join-Path $tempStem 'readme.txt'
        Test-Path -LiteralPath $extracted | Should -BeTrue
        (Get-Content -LiteralPath $extracted -Raw) | Should -Be 'blinter-payload'
    }

    It 'exits 1 when the archive is missing' {
        $tempScript = Join-Path $TestDrive 'expand-missing.ps1'
        New-InstallerPsSubstitutedScript `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Expand-BlinterArchive.ps1') `
            -Replacements @{ '__BLINTER_TEMP__' = (Join-Path $TestDrive 'missing-archive') } `
            -DestinationPath $tempScript

        & $tempScript
        $LASTEXITCODE | Should -Be 1
    }
}

Describe 'Get-DownloadedFileSize.ps1' {
    It 'writes the zip file length' {
        $tempStem = Join-Path $TestDrive 'size-archive'
        [System.IO.File]::WriteAllBytes("$tempStem.zip", [byte[]](1..20))

        $tempScript = Join-Path $TestDrive 'size.ps1'
        New-InstallerPsSubstitutedScript `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Get-DownloadedFileSize.ps1') `
            -Replacements @{ '__BLINTER_TEMP__' = $tempStem } `
            -DestinationPath $tempScript

        $output = & $tempScript
        $output | Should -Be 20
    }

    It 'throws when the zip is missing' {
        $tempScript = Join-Path $TestDrive 'size-missing.ps1'
        New-InstallerPsSubstitutedScript `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Get-DownloadedFileSize.ps1') `
            -Replacements @{ '__BLINTER_TEMP__' = (Join-Path $TestDrive 'missing-size') } `
            -DestinationPath $tempScript

        { & $tempScript } | Should -Throw
    }
}
