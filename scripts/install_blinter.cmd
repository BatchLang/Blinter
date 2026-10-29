@echo off
setlocal enabledelayedexpansion
REM cmd.exe stops finding labels in an LF-only script after about 12KB.
REM Rewrite this file with CRLF and run that copy.
if defined BLINTER_CRLF_REEXEC goto :blinter_crlf_ready
set "BLINTER_CRLF_REEXEC=1"
set "BLINTER_SELF=%~f0"
set "BLINTER_CRLF_COPY=%TEMP%\blinter_crlf_%RANDOM%_%RANDOM%.cmd"
set "BLINTER_CRLF_PS=%TEMP%\blinter_crlf_%RANDOM%_%RANDOM%.ps1"
:write_crlf_script
(
echo $bytes = [System.IO.File]::ReadAllBytes($env:BLINTER_SELF^)
echo if ($bytes -contains 13^) { exit 0 }
echo $list = New-Object System.Collections.Generic.List[byte]
echo foreach ($byte in $bytes^) {
echo     if ($byte -eq 10^) { $list.Add(13^) }
echo     $list.Add($byte^)
echo }
echo [System.IO.File]::WriteAllBytes($env:BLINTER_CRLF_COPY, $list.ToArray(^)^)
echo exit 3
) > "%BLINTER_CRLF_PS%"
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%BLINTER_CRLF_PS%"
set "BLINTER_CRLF_PS_EXIT=!errorlevel!"
del /F /Q "%BLINTER_CRLF_PS%" >nul 2>&1
if errorlevel 1 set "BLINTER_CRLF_PS_EXIT=!BLINTER_CRLF_PS_EXIT!"
if !BLINTER_CRLF_PS_EXIT! equ 3 goto :blinter_crlf_reexec
if !BLINTER_CRLF_PS_EXIT! neq 0 goto :blinter_crlf_failed
goto :blinter_crlf_ready

REM Run the CRLF copy and return its exit code.
:blinter_crlf_reexec
cmd /c call "%BLINTER_CRLF_COPY%" %*
set "BLINTER_REEXEC_EXIT=!errorlevel!"
del /F /Q "%BLINTER_CRLF_COPY%" >nul 2>&1
if errorlevel 1 set "BLINTER_REEXEC_EXIT=!BLINTER_REEXEC_EXIT!"
exit /b !BLINTER_REEXEC_EXIT!

REM Stop when the line-ending rewrite fails.
:blinter_crlf_failed
echo ERROR: Could not normalize the script line endings.
exit /b 1

REM Line endings are safe for label lookup.
:blinter_crlf_ready

REM The architecture is optional. With no argument the build matches this PC. An
REM x64 or arm64 argument overrides that, and any other argument downloads nothing.
REM PROCESSOR_ARCHITEW6432 names the real CPU when a 32-bit or emulated process runs.
set "BLINTER_HOST_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "BLINTER_HOST_ARCH=%PROCESSOR_ARCHITEW6432%"
if "%~1"=="" goto :blinter_arch_detect
if /I "%~1"=="x64" (
    set "BLINTER_ARCH=x64"
    goto :blinter_arch_ready
)
if /I "%~1"=="arm64" (
    set "BLINTER_ARCH=arm64"
    goto :blinter_arch_ready
)
echo Usage: install_blinter.cmd [x64^|arm64]
echo.
echo The architecture argument was not recognized, so nothing was downloaded.
goto :error_exit

REM Choose the native build for this PC.
:blinter_arch_detect
if /I "%BLINTER_HOST_ARCH%"=="ARM64" (
    set "BLINTER_ARCH=arm64"
    goto :blinter_arch_ready
)
if /I "%BLINTER_HOST_ARCH%"=="AMD64" (
    set "BLINTER_ARCH=x64"
    goto :blinter_arch_ready
)
echo ERROR: Unsupported processor architecture: %BLINTER_HOST_ARCH%
echo.
echo Blinter is built for x64 and ARM64. Nothing was downloaded.
goto :error_exit

REM Refuse arm64 on a non-ARM PC. x64 on ARM64 is allowed and runs through emulation.
:blinter_arch_ready
if /I "%BLINTER_ARCH%"=="arm64" if /I not "%BLINTER_HOST_ARCH%"=="ARM64" (
    echo ERROR: The arm64 build cannot be installed on this PC.
    echo.
    echo Nothing was downloaded.
    goto :error_exit
)
if /I "%BLINTER_ARCH%"=="x64" if /I "%BLINTER_HOST_ARCH%"=="ARM64" (
    echo NOTE: This PC is ARM64. The x64 build runs through emulation. The arm64 argument installs the native build.
    echo.
)

REM ============================================================================
REM Blinter Installer/Updater
REM Purpose: Download and install the latest Blinter release to %LOCALAPPDATA%
REM Author: tboy1337
REM Repository: https://github.com/BatchLang/Blinter
REM ============================================================================

REM Attempt to change to system drive to avoid issues with current directory/drive
cd /d "%SystemDrive%" >nul 2>&1
if %errorlevel% neq 0 (
    echo Failed to change to %SystemDrive%. Error code: %errorlevel%
)

REM Check if running as administrator (script should run as normal user)
net session >nul 2>&1
if %errorlevel% equ 0 (
    echo ERROR: This script is intended to be run as a user. Please run without administrator privileges.
    goto :error_exit
)

REM Check if curl is installed
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Curl is not installed or in PATH.
    goto :error_exit
)

echo +===========================+
echo + Blinter Installer/Updater +
echo +===========================+
echo Selected build: !BLINTER_ARCH!
echo.

set "BLINTER_DIR=%LOCALAPPDATA%\Programs\Blinter"
set "BLINTER_BIN=%BLINTER_DIR%\bin"
set "BLINTER_RELEASE_FILE=%BLINTER_DIR%\installed_release.txt"
set "BLINTER_TEMP=%TEMP%\blinter_install_%RANDOM%_%RANDOM%"
set "BLINTER_BACKUP=%TEMP%\blinter_backup_%RANDOM%_%RANDOM%"
set /a MIN_DOWNLOAD_BYTES=500*1000

REM Detect latest Blinter version and download URL from GitHub API
set BLINTER_URL=
set BLINTER_VERSION=
set BLINTER_SHA256=
set "PS_GET_RELEASE=%BLINTER_TEMP%_get_release.ps1"

call :write_get_release_script
for /f "tokens=1,2,3" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_GET_RELEASE%"') do (
    set BLINTER_URL=%%a
    set BLINTER_VERSION=%%b
    set BLINTER_SHA256=%%c
)
if exist "!PS_GET_RELEASE!" del /F /Q "!PS_GET_RELEASE!" >nul 2>&1

if "!BLINTER_URL!"=="MISSING_DIGEST" (
    echo ERROR: GitHub release is missing a SHA256 digest. Cannot verify download.
    echo.
    echo Refusing to install an unverifiable archive.
    goto :error_exit
)

if "!BLINTER_URL!"=="NOT_FOUND" (
    echo ERROR: Failed to find Windows download URL from GitHub API.
    echo.
    echo Please check your internet connection and try again.
    goto :error_exit
)

if "!BLINTER_URL!"=="" (
    echo ERROR: Failed to detect latest Blinter version.
    echo.
    echo Please check your internet connection and try again.
    goto :error_exit
)

if "!BLINTER_VERSION!"=="" (
    echo ERROR: Failed to parse Blinter version from GitHub API response.
    echo.
    echo Cannot proceed with installation.
    goto :error_exit
)

if "!BLINTER_SHA256!"=="" (
    echo ERROR: GitHub release is missing a SHA256 digest. Cannot verify download.
    echo.
    echo Refusing to install an unverifiable archive.
    goto :error_exit
)

echo Latest Blinter !BLINTER_ARCH! release: !BLINTER_VERSION!
echo.

REM Create installation directory if it doesn't exist
if not exist "%BLINTER_BIN%" (
    mkdir "%BLINTER_BIN%" >nul 2>&1
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create installation directory: %BLINTER_BIN%
        echo Error code: !errorlevel!
        goto :error_exit
    )
)

REM Check current installation
set CURRENT_VERSION=
set NEEDS_BACKUP=0

if exist "%BLINTER_BIN%\blinter.exe" (
    set "VERSION_TEMP=%TEMP%\blinter_version_%RANDOM%_%RANDOM%.txt"
    "%BLINTER_BIN%\blinter.exe" --version > "!VERSION_TEMP!" 2>&1
    if !errorlevel! equ 0 (
        for /f "usebackq tokens=*" %%v in ("!VERSION_TEMP!") do set CURRENT_VERSION=%%v
        del /F /Q "!VERSION_TEMP!" >nul 2>&1
        if not "!CURRENT_VERSION!"=="" (
            echo Current installed version: !CURRENT_VERSION!
            echo.
        )
    ) else (
        if exist "!VERSION_TEMP!" del /F /Q "!VERSION_TEMP!" >nul 2>&1
    )
)

if exist "%BLINTER_RELEASE_FILE%" (
    REM LINT:IGNORE SEC001
    set /p INSTALLED_RELEASE=<"%BLINTER_RELEASE_FILE%"
    if not "!INSTALLED_RELEASE!"=="" (
        if /i not "!INSTALLED_RELEASE:~0,1!"=="v" set "INSTALLED_RELEASE="
    )
    if "!INSTALLED_RELEASE!"=="!BLINTER_VERSION!" (
        if exist "%BLINTER_BIN%\blinter.exe" if not "!CURRENT_VERSION!"=="" (
            echo Blinter !BLINTER_VERSION! is already installed and up to date.
            goto :end
        )
        echo Blinter !BLINTER_VERSION! is recorded as installed, but blinter.exe is missing or did not run.
        echo.
        echo Reinstalling Blinter !BLINTER_VERSION!...
        echo.
        if exist "%BLINTER_BIN%\blinter.exe" set NEEDS_BACKUP=1
    ) else if exist "%BLINTER_BIN%\blinter.exe" (
        echo Upgrading from "!INSTALLED_RELEASE!" to !BLINTER_VERSION!...
        echo.
        set NEEDS_BACKUP=1
    )
) else if exist "%BLINTER_BIN%\blinter.exe" (
    echo Existing installation found without release marker.
    echo.
    echo Upgrading to !BLINTER_VERSION!...
    echo.
    set NEEDS_BACKUP=1
) else (
    echo No existing installation found.
    echo.
    echo Installing Blinter !BLINTER_VERSION!...
    echo.
)

REM Backup existing installation if upgrading
if !NEEDS_BACKUP! equ 1 (
    echo Creating backup of existing installation...
    echo.
    mkdir "%BLINTER_BACKUP%" >nul 2>&1
    if exist "%BLINTER_BIN%\blinter.exe" copy /Y "%BLINTER_BIN%\blinter.exe" "%BLINTER_BACKUP%\" >nul 2>&1
    if exist "%BLINTER_RELEASE_FILE%" copy /Y "%BLINTER_RELEASE_FILE%" "%BLINTER_BACKUP%\" >nul 2>&1
)

REM Download Blinter
echo Downloading Blinter !BLINTER_VERSION! from:
echo !BLINTER_URL!
echo.
curl -fL --connect-timeout 30 --max-time 300 --proto =https --progress-bar -o "%BLINTER_TEMP%.zip" "!BLINTER_URL!" 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ERROR: Failed to download Blinter. Error code: !errorlevel!
    echo.
    echo This could be due to:
    echo - Network connectivity issues
    echo - Invalid download URL
    goto :error_restore
)

REM Validate downloaded file exists and has content
if not exist "%BLINTER_TEMP%.zip" (
    echo ERROR: Downloaded file not found at %BLINTER_TEMP%.zip
    goto :error_restore
)

set FILESIZE=0
set "PS_FILE_SIZE=%BLINTER_TEMP%_file_size.ps1"
call :write_file_size_script
for /f "delims=" %%S in ('powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_FILE_SIZE!" 2^>nul') do (
    set FILESIZE=%%S
)
if exist "!PS_FILE_SIZE!" del /F /Q "!PS_FILE_SIZE!" >nul 2>&1

if !FILESIZE! lss !MIN_DOWNLOAD_BYTES! (
    echo ERROR: Downloaded file is too small ^(!FILESIZE! bytes^). Download may be corrupted.
    goto :error_restore
)

REM Verify SHA256 digest from the GitHub release asset
set "PS_HASH_VERIFY=%BLINTER_TEMP%_hash_verify.ps1"
call :write_hash_verify_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_HASH_VERIFY!" 2>&1
if !errorlevel! neq 0 (
    echo ERROR: SHA256 digest mismatch. The download may be corrupted or tampered with.
    goto :error_restore
)
if exist "!PS_HASH_VERIFY!" del /F /Q "!PS_HASH_VERIFY!" >nul 2>&1

REM Extract Blinter
echo.
echo Extracting Blinter...
echo.
set "PS_EXPAND=%BLINTER_TEMP%_expand.ps1"
call :write_expand_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_EXPAND!" 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Failed to extract Blinter archive. Error code: !errorlevel!
    goto :error_restore
)
if exist "!PS_EXPAND!" del /F /Q "!PS_EXPAND!" >nul 2>&1

REM Locate extracted executable. The folder name matches the zip name.
set "BLINTER_SOURCE_EXE=%BLINTER_TEMP%\Blinter-!BLINTER_VERSION!-Windows-!BLINTER_ARCH!\blinter.exe"
if not exist "!BLINTER_SOURCE_EXE!" (
    echo ERROR: Blinter executable not found in extracted archive.
    echo.
    echo Expected layout: Blinter-!BLINTER_VERSION!-Windows-!BLINTER_ARCH!\blinter.exe
    echo The archive structure may have changed or be corrupted.
    goto :error_restore
)

REM Install Blinter executable
echo Installing Blinter executable...
echo.
copy /Y "!BLINTER_SOURCE_EXE!" "%BLINTER_BIN%\blinter.exe" >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Failed to install blinter.exe. Error code: !errorlevel!
    echo.
    echo Installation failed. Check if files are in use or if you have write permissions.
    goto :error_restore
)
echo Installed blinter.exe

REM Verify installation
echo.
echo Verifying installation...
echo.
if not exist "%BLINTER_BIN%\blinter.exe" (
    echo ERROR: blinter.exe not found after installation at %BLINTER_BIN%\blinter.exe
    goto :error_restore
)

"%BLINTER_BIN%\blinter.exe" --version 2>&1
if !errorlevel! neq 0 (
    echo ERROR: blinter.exe failed to execute. Error code: !errorlevel!
    goto :error_restore
)

REM Write release marker
echo !BLINTER_VERSION!> "%BLINTER_RELEASE_FILE%"
if !errorlevel! neq 0 (
    echo WARNING: Failed to write release marker at %BLINTER_RELEASE_FILE%
    echo.
)

REM Update PATH environment variable
echo.
echo Updating PATH environment variable...
echo.
set "PS_UPDATE_PATH=%BLINTER_TEMP%_update_path.ps1"
call :write_update_path_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_UPDATE_PATH!" 2>&1
if !errorlevel! neq 0 (
    echo WARNING: Failed to update User PATH environment variable.
    echo You may need to manually add %BLINTER_BIN% to your PATH.
    echo.
)
if exist "!PS_UPDATE_PATH!" del /F /Q "!PS_UPDATE_PATH!" >nul 2>&1

REM Update PATH for current session
set "PATH=%PATH%;%BLINTER_BIN%"

REM The install folder is appended. Warn when an earlier PATH entry still wins.
set "WHERE_TEMP=%TEMP%\blinter_where_%RANDOM%_%RANDOM%.txt"
where blinter > "!WHERE_TEMP!" 2>nul
set "FIRST_BLINTER="
for /f "usebackq delims=" %%p in ("!WHERE_TEMP!") do (
    if not defined FIRST_BLINTER set "FIRST_BLINTER=%%p"
)
if exist "!WHERE_TEMP!" del /F /Q "!WHERE_TEMP!" >nul 2>&1
if defined FIRST_BLINTER (
    if /I not "!FIRST_BLINTER!"=="!BLINTER_BIN!\blinter.exe" (
        echo.
        echo WARNING: Another blinter is earlier on PATH and will run instead:
        echo !FIRST_BLINTER!
        echo The standalone folder was appended and will not win:
        echo !BLINTER_BIN!
        echo.
    )
)

REM Success! Clean up temporary files and backup
call :cleanup
REM LINT:IGNORE SEC003
if exist "%BLINTER_BACKUP%" rmdir /S /Q "%BLINTER_BACKUP%" >nul 2>&1

echo.
echo +============================================================+
echo + SUCCESS: Blinter !BLINTER_VERSION! installed successfully! +
echo +============================================================+
echo.
echo Installation directory: %BLINTER_BIN%
echo.
echo Note: You may need to restart your terminal or IDE to use Blinter commands.
echo In the current session, Blinter commands should already be available.
echo.
goto :end

REM Write PowerShell script to fetch latest release URL and tag.
REM ProgressPreference stays silent: Windows PowerShell 5.1's progress UI throws
REM "Access is denied" when cmd captures stdout with for /f. Retry because a single
REM empty or failed response used to be reported as a missing download.
:write_get_release_script
(
echo #Requires -Version 5.1
echo $ProgressPreference = 'SilentlyContinue'
echo $arch = [string]$env:BLINTER_ARCH
echo if ($arch -ne 'x64' -and $arch -ne 'arm64'^) { Write-Output 'NOT_FOUND'; exit 0 }
echo $release = $null
echo $asset = $null
echo foreach ($attempt in 1..3^) {
echo     try {
echo         $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/BatchLang/Blinter/releases/latest'
echo     } catch {
echo         [Console]::Error.WriteLine($_.Exception.Message^)
echo         $release = $null
echo     }
echo     if ($release -and -not $release.prerelease -and -not $release.draft^) {
echo         $assetName = 'Blinter-' + $release.tag_name + '-Windows-' + $arch + '.zip'
echo         $asset = @($release.assets^) ^| Where-Object { $_.name -eq $assetName } ^| Select-Object -First 1
echo     }
echo     if ($asset^) { break }
echo     if ($attempt -lt 3^) { Start-Sleep -Seconds $attempt }
echo }
echo if (-not $release^) { Write-Output 'NOT_FOUND'; exit 0 }
echo if (-not $asset^) { Write-Output 'NOT_FOUND'; exit 0 }
echo $digest = $null
echo if ($asset.PSObject.Properties['digest']^) { $digest = [string]$asset.digest }
echo if (-not $digest^) { Write-Output 'MISSING_DIGEST'; exit 0 }
echo $line = $asset.browser_download_url + ' ' + $release.tag_name + ' ' + $digest
echo Write-Output $line
) > "!PS_GET_RELEASE!"
exit /b 0

REM Write PowerShell script to return downloaded archive size in bytes
:write_file_size_script
(
echo #Requires -Version 5.1
echo $item = Get-Item -LiteralPath "$($env:BLINTER_TEMP).zip" -ErrorAction Stop
echo Write-Output $item.Length
) > "!PS_FILE_SIZE!"
exit /b 0

REM Write PowerShell script to verify the downloaded archive SHA256.
REM Caret-escape each closing parenthesis, and write a literal caret as ^^, so this redirect stays intact.
:write_hash_verify_script
(
echo #Requires -Version 5.1
echo $expected = $env:BLINTER_SHA256
echo $sha = [System.Security.Cryptography.SHA256]::Create(^)
echo try {
echo     $stream = [System.IO.File]::OpenRead("$($env:BLINTER_TEMP).zip"^)
echo     try {
echo         $actual = [System.BitConverter]::ToString($sha.ComputeHash($stream^)^).Replace('-', ''^)
echo         $actual = $actual.ToLowerInvariant(^)
echo     } finally { $stream.Dispose(^) }
echo } finally { $sha.Dispose(^) }
echo $normalized = $expected.ToLowerInvariant(^) -replace '^^sha256:', ''
echo if ($actual -ne $normalized^) { Write-Output 'MISMATCH'; exit 1 }
echo Write-Output 'OK'
) > "!PS_HASH_VERIFY!"
exit /b 0

REM Write PowerShell script to expand the downloaded archive
:write_expand_script
(
echo #Requires -Version 5.1
echo try {
echo     Expand-Archive -LiteralPath "$($env:BLINTER_TEMP).zip" -DestinationPath $env:BLINTER_TEMP -Force
echo     exit 0
echo }
echo catch {
echo     Write-Host "ERROR: $_"
echo     exit 1
echo }
) > "!PS_EXPAND!"
exit /b 0

REM Write PowerShell script to add Blinter bin directory to user PATH
:write_update_path_script
(
echo #Requires -Version 5.1
echo try {
echo     $binPath = $env:BLINTER_BIN
echo     $kindName = 'String'
echo     $path = ''
echo     $key = $null
echo     if ($env:BLINTER_PATH_TEST_MODE -eq '1'^) {
echo         $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
echo     } else {
echo         try {
echo             $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true^)
echo             if ($key^) {
echo                 try {
echo                     $kind = $key.GetValueKind('Path'^)
echo                     $raw = $key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames^)
echo                     if ($null -ne $raw^) { $path = [string]$raw }
echo                     if ($kind -eq [Microsoft.Win32.RegistryValueKind]::ExpandString^) { $kindName = 'ExpandString' }
echo                 } catch {
echo                     $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
echo                 }
echo             } else {
echo                 $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
echo             }
echo         } catch {
echo             $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
echo         }
echo     }
echo     if (-not $path^) { $path = '' }
echo     $segments = @($path -split ';' ^| Where-Object { $_ -ne '' }^)
echo     $alreadyPresent = $false
echo     foreach ($segment in $segments^) {
echo         if ($segment -eq $binPath^) {
echo             $alreadyPresent = $true
echo             break
echo         }
echo     }
echo     if (-not $alreadyPresent^) {
echo         if (-not $path^) { $newPath = $binPath } else { $newPath = $path.TrimEnd(';'^) + ';' + $binPath }
echo         if ($kindName -eq 'ExpandString' -and $key^) {
echo             $key.SetValue('Path', $newPath, [Microsoft.Win32.RegistryValueKind]::ExpandString^)
echo             Write-Host 'Blinter added to User PATH permanently'
echo         } else {
echo             [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'^)
echo             Write-Host 'Blinter added to User PATH permanently'
echo         }
echo     }
echo     else {
echo         Write-Host 'Blinter already in User PATH'
echo     }
echo     if ($key^) { $key.Close(^) }
echo     exit 0
echo }
echo catch {
echo     if ($key^) { $key.Close(^) }
echo     Write-Host "ERROR: $_"
echo     exit 1
echo }
) > "!PS_UPDATE_PATH!"
exit /b 0

REM Subroutine: remove temporary install files and helper scripts
:cleanup
if exist "%BLINTER_TEMP%.zip" del /F /Q "%BLINTER_TEMP%.zip" >nul 2>&1
REM LINT:IGNORE SEC003
if exist "%BLINTER_TEMP%" rmdir /S /Q "%BLINTER_TEMP%" >nul 2>&1
if exist "%BLINTER_TEMP%_get_release.ps1" del /F /Q "%BLINTER_TEMP%_get_release.ps1" >nul 2>&1
if exist "%BLINTER_TEMP%_file_size.ps1" del /F /Q "%BLINTER_TEMP%_file_size.ps1" >nul 2>&1
if exist "%BLINTER_TEMP%_hash_verify.ps1" del /F /Q "%BLINTER_TEMP%_hash_verify.ps1" >nul 2>&1
if exist "%BLINTER_TEMP%_expand.ps1" del /F /Q "%BLINTER_TEMP%_expand.ps1" >nul 2>&1
if exist "%BLINTER_TEMP%_update_path.ps1" del /F /Q "%BLINTER_TEMP%_update_path.ps1" >nul 2>&1
exit /b 0

REM Restore previous installation after a failed upgrade, then clean up
:error_restore
if !NEEDS_BACKUP! equ 1 (
    if exist "%BLINTER_BACKUP%" (
        echo.
        echo Attempting to restore previous installation...
        if exist "%BLINTER_BACKUP%\blinter.exe" (
            copy /Y "%BLINTER_BACKUP%\blinter.exe" "%BLINTER_BIN%\" >nul 2>&1
            if !errorlevel! neq 0 (
                echo WARNING: Failed to restore blinter.exe from backup.
            )
        )
        if exist "%BLINTER_BACKUP%\installed_release.txt" (
            copy /Y "%BLINTER_BACKUP%\installed_release.txt" "%BLINTER_DIR%\" >nul 2>&1
            if !errorlevel! neq 0 (
                echo WARNING: Failed to restore installed_release.txt from backup.
            )
        )
        echo Previous installation restored.
        echo.
    )
)
call :cleanup
REM LINT:IGNORE SEC003
if exist "%BLINTER_BACKUP%" rmdir /S /Q "%BLINTER_BACKUP%" >nul 2>&1
goto :error_exit

REM Print failure message and exit with error code
:error_exit
echo.
echo +========================================================+
echo + Installation failed. Please review the errors above. +
echo +========================================================+
echo.
echo For help, visit: https://github.com/BatchLang/Blinter/issues
echo.
timeout /t 5 /nobreak
endlocal
exit /b 1

REM Successful completion
:end
endlocal
exit /b 0
