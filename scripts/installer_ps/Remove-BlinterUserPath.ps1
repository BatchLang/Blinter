#Requires -Version 5.1
try {
    $binPath = $env:BLINTER_BIN
    $kindName = 'String'
    $path = ''
    $key = $null
    if ($env:BLINTER_PATH_TEST_MODE -eq '1') {
        $path = [Environment]::GetEnvironmentVariable('Path', 'User')
    } else {
        try {
            $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
            if ($key) {
                try {
                    $kind = $key.GetValueKind('Path')
                    $raw = $key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                    if ($null -ne $raw) { $path = [string]$raw }
                    if ($kind -eq [Microsoft.Win32.RegistryValueKind]::ExpandString) { $kindName = 'ExpandString' }
                } catch {
                    $path = [Environment]::GetEnvironmentVariable('Path', 'User')
                }
            } else {
                $path = [Environment]::GetEnvironmentVariable('Path', 'User')
            }
        } catch {
            $path = [Environment]::GetEnvironmentVariable('Path', 'User')
        }
    }
    if (-not $path) {
        if ($key) { $key.Close() }
        Write-Host 'User PATH is empty'
        exit 0
    }
    if ($path -like "*$binPath*") {
        $pathArray = $path -split ';' | Where-Object { $_ -ne '' -and $_ -ne $binPath }
        $newPath = $pathArray -join ';'
        if ($kindName -eq 'ExpandString' -and $key) {
            $key.SetValue('Path', $newPath, [Microsoft.Win32.RegistryValueKind]::ExpandString)
        } else {
            [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        }
        Write-Host 'Blinter removed from User PATH'
    }
    else {
        Write-Host 'Blinter not found in User PATH'
    }
    if ($key) { $key.Close() }
    exit 0
}
catch {
    if ($key) { $key.Close() }
    Write-Host "ERROR: $_"
    exit 1
}
