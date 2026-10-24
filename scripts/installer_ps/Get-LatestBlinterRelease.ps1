#Requires -Version 5.1
$ProgressPreference = 'SilentlyContinue'
$arch = [string]$env:BLINTER_ARCH
if ($arch -ne 'x64' -and $arch -ne 'arm64') { Write-Output 'NOT_FOUND'; exit 0 }
$release = $null
$asset = $null
foreach ($attempt in 1..3) {
    try {
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/BatchLang/Blinter/releases/latest'
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        $release = $null
    }
    if ($release -and -not $release.prerelease -and -not $release.draft) {
        # Previous name stays until a Windows-named release is the latest one.
        $preferredName = 'Blinter-' + $release.tag_name + '-Windows-' + $arch + '.zip'
        $previousName = 'Blinter-' + $release.tag_name + '-' + $arch + '.zip'
        $asset = @($release.assets) | Where-Object { $_.name -eq $preferredName } | Select-Object -First 1
        if (-not $asset) {
            $asset = @($release.assets) | Where-Object { $_.name -eq $previousName } | Select-Object -First 1
        }
    }
    if ($asset) { break }
    if ($attempt -lt 3) { Start-Sleep -Seconds $attempt }
}
if (-not $release) { Write-Output 'NOT_FOUND'; exit 0 }
if (-not $asset) { Write-Output 'NOT_FOUND'; exit 0 }
$digest = $null
if ($asset.PSObject.Properties['digest']) { $digest = [string]$asset.digest }
if (-not $digest) { Write-Output 'MISSING_DIGEST'; exit 0 }
$line = $asset.browser_download_url + ' ' + $release.tag_name + ' ' + $digest
Write-Output $line
