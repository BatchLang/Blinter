#Requires -Version 5.1
$ProgressPreference = 'SilentlyContinue'
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
        $asset = @($release.assets) | Where-Object { $_.name -like 'Blinter-v*.zip' } | Select-Object -First 1
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
