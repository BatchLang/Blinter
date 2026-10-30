#Requires -Version 5.1
BeforeAll {
    . (Join-Path $PSScriptRoot 'InstallerPs.Helpers.ps1')
    $script:ScriptsRoot = $PSScriptRoot
    $script:InstallerPsRoot = Join-Path $PSScriptRoot 'installer_ps'
}

Describe 'Installer batch PowerShell parity' {
    It 'matches fixture content for each write_*_script block' {
        $pairs = Get-InstallerPsParityPair -ScriptsRoot $script:ScriptsRoot -InstallerPsRoot $script:InstallerPsRoot
        $pairs.Count | Should -Be 9

        foreach ($pair in $pairs) {
            $normalizedExtracted = ConvertTo-InstallerPsNormalizedText -Content $pair.Extracted
            $normalizedFixture = ConvertTo-InstallerPsNormalizedText -Content $pair.FixtureBody
            $normalizedExtracted | Should -Be $normalizedFixture `
                -Because "parity failed for $($pair.CmdFile):$($pair.Label) -> $($pair.Fixture)"
        }
    }
}

Describe 'Get-LatestBlinterRelease.ps1' {
    BeforeAll {
        $script:SavedBlinterArch = $env:BLINTER_ARCH
    }

    AfterAll {
        if ($null -eq $script:SavedBlinterArch) {
            Remove-Item Env:BLINTER_ARCH -ErrorAction SilentlyContinue
        } else {
            $env:BLINTER_ARCH = $script:SavedBlinterArch
        }
    }

    BeforeEach {
        $env:BLINTER_ARCH = 'x64'
    }

    It 'outputs NOT_FOUND when no release is available' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        Mock Invoke-RestMethod { return @() }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NOT_FOUND'
    }

    It 'retries a failed lookup and then returns the release' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        $lookup = @{ Calls = 0 }
        $release = {
            $lookup.Calls++
            if ($lookup.Calls -lt 2) {
                throw 'temporary failure'
            }
            return @(
                [PSCustomObject]@{
                    prerelease = $false
                    draft      = $false
                    tag_name   = 'v1.1.6'
                    assets     = @(
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6-Windows-x64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-x64.zip'
                            digest               = 'sha256:abc123'
                        }
                    )
                }
            )
        }.GetNewClosure()
        Mock Invoke-RestMethod -MockWith $release

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $lookup.Calls | Should -Be 2
        $output | Should -Be 'https://example.com/Blinter-v1.1.6-Windows-x64.zip v1.1.6 sha256:abc123'
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
                            name                 = 'Blinter-v1.1.6-Windows-x64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-x64.zip'
                            digest               = 'sha256:abc123'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'https://example.com/Blinter-v1.1.6-Windows-x64.zip v1.1.6 sha256:abc123'
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
                            name                 = 'Blinter-v1.1.6-Windows-x64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-x64.zip'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'MISSING_DIGEST'
    }

    It 'selects the x64 asset when both architectures are published' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        Mock Invoke-RestMethod {
            return @(
                [PSCustomObject]@{
                    prerelease = $false
                    draft      = $false
                    tag_name   = 'v1.1.6'
                    assets     = @(
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6-Windows-arm64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-arm64.zip'
                            digest               = 'sha256:arm'
                        },
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6-Windows-x64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-x64.zip'
                            digest               = 'sha256:x64'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'https://example.com/Blinter-v1.1.6-Windows-x64.zip v1.1.6 sha256:x64'
    }

    It 'selects the arm64 asset when both architectures are published' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        $env:BLINTER_ARCH = 'arm64'
        Mock Invoke-RestMethod {
            return @(
                [PSCustomObject]@{
                    prerelease = $false
                    draft      = $false
                    tag_name   = 'v1.1.6'
                    assets     = @(
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6-Windows-x64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-x64.zip'
                            digest               = 'sha256:x64'
                        },
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6-Windows-arm64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-arm64.zip'
                            digest               = 'sha256:arm'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'https://example.com/Blinter-v1.1.6-Windows-arm64.zip v1.1.6 sha256:arm'
    }

    It 'outputs NOT_FOUND when the requested architecture was not published' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        $env:BLINTER_ARCH = 'arm64'
        Mock Invoke-RestMethod {
            return @(
                [PSCustomObject]@{
                    prerelease = $false
                    draft      = $false
                    tag_name   = 'v1.1.6'
                    assets     = @(
                        [PSCustomObject]@{
                            name                 = 'Blinter-v1.1.6-Windows-x64.zip'
                            browser_download_url = 'https://example.com/Blinter-v1.1.6-Windows-x64.zip'
                            digest               = 'sha256:x64'
                        }
                    )
                }
            )
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NOT_FOUND'
    }

    It 'outputs NOT_FOUND without calling GitHub when the architecture is unset or invalid' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBlinterRelease.ps1'
        Mock Invoke-RestMethod { throw 'should not be called' }

        Remove-Item Env:BLINTER_ARCH -ErrorAction SilentlyContinue
        $unset = & $fixturePath
        $unset | Should -Be 'NOT_FOUND'

        $env:BLINTER_ARCH = 'sparc'
        $invalid = & $fixturePath
        $invalid | Should -Be 'NOT_FOUND'
        Should -Invoke -CommandName Invoke-RestMethod -Times 0 -Exactly
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
        $env:BLINTER_TEMP = ($tempFile -replace '\.zip$', '')
        $env:BLINTER_SHA256 = "sha256:$hash"
        try {
            & (Join-Path $script:InstallerPsRoot 'Test-BlinterArchiveHash.ps1')
            $LASTEXITCODE | Should -Be 0
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
            Remove-Item Env:BLINTER_SHA256 -ErrorAction SilentlyContinue
        }
    }

    It 'exits 1 when the archive hash does not match' {
        $tempFile = Join-Path $TestDrive 'archive.zip'
        Set-Content -LiteralPath $tempFile -Value 'blinter-archive' -NoNewline
        $env:BLINTER_TEMP = ($tempFile -replace '\.zip$', '')
        $env:BLINTER_SHA256 = 'sha256:deadbeef'
        try {
            & (Join-Path $script:InstallerPsRoot 'Test-BlinterArchiveHash.ps1')
            $LASTEXITCODE | Should -Be 1
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
            Remove-Item Env:BLINTER_SHA256 -ErrorAction SilentlyContinue
        }
    }
}

Describe 'Installer batch hash helper emission' {
    It 'writes a working verifier and can goto :error_restore (<Name>)' -ForEach @(
        @{ Name = 'CRLF'; Newline = "`r`n" }
        @{ Name = 'LF'; Newline = "`n" }
    ) {
        $tempStem = Join-Path $TestDrive "hash-$Name"
        $zipPath = "$tempStem.zip"
        $payload = [byte[]](1, 2, 3, 4, 5)
        [System.IO.File]::WriteAllBytes($zipPath, $payload)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hash = [System.BitConverter]::ToString($sha.ComputeHash($payload)).Replace('-', '').ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }

        $outFile = Join-Path $TestDrive "hash-verify-$Name.ps1"
        $cmdPath = Join-Path $TestDrive "hash-verify-$Name.cmd"
        Write-InstallerBatchLabelScript `
            -CmdFilePath (Join-Path $script:ScriptsRoot 'install_blinter.cmd') `
            -LabelName 'write_hash_verify_script' `
            -DestinationPath $cmdPath `
            -Newline $Newline `
            -Variables @{
                PS_HASH_VERIFY = $outFile
                BLINTER_TEMP   = $tempStem
                BLINTER_SHA256 = "sha256:$hash"
            } | Out-Null

        $output = & cmd.exe /d /c "call `"$cmdPath`""
        $LASTEXITCODE | Should -Be 0
        $text = @($output) -join "`n"
        $text | Should -Match 'RESTORE_OK'
        $text | Should -Not -Match 'cannot find the batch label'
        $text | Should -Not -Match 'SHA256::Create'

        $fixtureLines = @(Get-Content -LiteralPath (Join-Path $script:InstallerPsRoot 'Test-BlinterArchiveHash.ps1'))
        @(Get-Content -LiteralPath $outFile) | Should -Be $fixtureLines

        $env:BLINTER_TEMP = $tempStem
        $env:BLINTER_SHA256 = "sha256:$hash"
        try {
            $verifyOutput = & $outFile
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
            Remove-Item Env:BLINTER_SHA256 -ErrorAction SilentlyContinue
        }
        $LASTEXITCODE | Should -Be 0
        $verifyOutput | Should -Be 'OK'
    }
}

Describe 'Update-BlinterUserPath.ps1' {
    AfterEach {
        Remove-Item Env:BLINTER_TEST_USER_PATH -ErrorAction SilentlyContinue
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
        Remove-Item Env:BLINTER_TEST_USER_PATH -ErrorAction SilentlyContinue
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

    It 'removes a bin directory whose path contains wildcard brackets' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Remove-BlinterUserPath.ps1') `
            -BinPath 'C:\Users\a[1]\Blinter\bin' `
            -InitialUserPath 'C:\Alpha;C:\Users\a[1]\Blinter\bin;C:\Beta' `
            -TempScriptPath (Join-Path $TestDrive 'remove-path-brackets.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Alpha;C:\Beta'
    }

    It 'does not touch a different directory that merely contains the bin path' {
        $result = Invoke-InstallerPsPathFixture `
            -FixturePath (Join-Path $script:InstallerPsRoot 'Remove-BlinterUserPath.ps1') `
            -BinPath 'C:\Test\Blinter\bin' `
            -InitialUserPath 'C:\Alpha;C:\Test\Blinter\bin2;C:\Beta' `
            -TempScriptPath (Join-Path $TestDrive 'remove-path-superstring.ps1')
        $result.ExitCode | Should -Be 0
        $result.UserPath | Should -Be 'C:\Alpha;C:\Test\Blinter\bin2;C:\Beta'
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

        $env:BLINTER_TEMP = $tempStem
        try {
            & (Join-Path $script:InstallerPsRoot 'Expand-BlinterArchive.ps1')
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
        }
        $LASTEXITCODE | Should -Be 0
        $extracted = Join-Path $tempStem 'readme.txt'
        Test-Path -LiteralPath $extracted | Should -BeTrue
        (Get-Content -LiteralPath $extracted -Raw) | Should -Be 'blinter-payload'
    }

    It 'exits 1 when the archive is missing' {
        $env:BLINTER_TEMP = Join-Path $TestDrive 'missing-archive'
        try {
            & (Join-Path $script:InstallerPsRoot 'Expand-BlinterArchive.ps1')
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
        }
        $LASTEXITCODE | Should -Be 1
    }
}

Describe 'Get-DownloadedFileSize.ps1' {
    It 'writes the zip file length' {
        $tempStem = Join-Path $TestDrive 'size-archive'
        [System.IO.File]::WriteAllBytes("$tempStem.zip", [byte[]](1..20))

        $env:BLINTER_TEMP = $tempStem
        try {
            $output = & (Join-Path $script:InstallerPsRoot 'Get-DownloadedFileSize.ps1')
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
        }
        $output | Should -Be 20
    }

    It 'throws when the zip is missing' {
        $env:BLINTER_TEMP = Join-Path $TestDrive 'missing-size'
        try {
            { & (Join-Path $script:InstallerPsRoot 'Get-DownloadedFileSize.ps1') } | Should -Throw
        } finally {
            Remove-Item Env:BLINTER_TEMP -ErrorAction SilentlyContinue
        }
    }
}
