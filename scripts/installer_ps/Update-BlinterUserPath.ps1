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
    if (-not $path) { $path = '' }
    $segments = @($path -split ';' | Where-Object { $_ -ne '' })
    $alreadyPresent = $false
    foreach ($segment in $segments) {
        if ($segment -eq $binPath) {
            $alreadyPresent = $true
            break
        }
    }
    if (-not $alreadyPresent) {
        if (-not $path) { $newPath = $binPath } else { $newPath = $path.TrimEnd(';') + ';' + $binPath }
        if ($kindName -eq 'ExpandString' -and $key) {
            $key.SetValue('Path', $newPath, [Microsoft.Win32.RegistryValueKind]::ExpandString)
            Write-Host 'Blinter added to User PATH permanently'
        } else {
            [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
            Write-Host 'Blinter added to User PATH permanently'
        }
    }
    else {
        Write-Host 'Blinter already in User PATH'
    }
    if ($key) { $key.Close() }
    exit 0
}
catch {
    if ($key) { $key.Close() }
    Write-Host "ERROR: $_"
    exit 1
}
