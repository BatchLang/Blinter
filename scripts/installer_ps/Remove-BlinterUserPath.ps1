#Requires -Version 5.1
function Send-BlinterSettingChange {
    if (-not ('Blinter.UserPathNotify' -as [type])) {
        Add-Type -Namespace Blinter -Name UserPathNotify -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet=System.Runtime.InteropServices.CharSet.Auto, SetLastError=true)]
public static System.IntPtr SendMessageTimeout(System.IntPtr hWnd, int Msg, System.UIntPtr wParam, string lParam, int fuFlags, int uTimeout, out System.UIntPtr lpdwResult);
'@
    }
    $notifyResult = [System.UIntPtr]::Zero
    [void][Blinter.UserPathNotify]::SendMessageTimeout([System.IntPtr]0xffff, 0x001A, [System.UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$notifyResult)
}
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
                    $rawOptions = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                    $raw = $key.GetValue('Path', '', $rawOptions)
                    if ($null -ne $raw) { $path = [string]$raw }
                    $expandKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
                    if ($kind -eq $expandKind) { $kindName = 'ExpandString' }
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
    $pathArray = @($path -split ';' | Where-Object { $_ -ne '' })
    if ($pathArray -contains $binPath) {
        $newPath = (@($pathArray | Where-Object { $_ -ne $binPath }) -join ';')
        if ($kindName -eq 'ExpandString' -and $key) {
            $key.SetValue('Path', $newPath, [Microsoft.Win32.RegistryValueKind]::ExpandString)
            Send-BlinterSettingChange
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
