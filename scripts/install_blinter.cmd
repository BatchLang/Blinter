@echo off
setlocal enabledelayedexpansion

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
echo.

set BLINTER_DIR=%LOCALAPPDATA%\Programs\Blinter
set BLINTER_BIN=%BLINTER_DIR%\bin
set BLINTER_RELEASE_FILE=%BLINTER_DIR%\installed_release.txt
set BLINTER_TEMP=%TEMP%\blinter_install_%RANDOM%_%RANDOM%
set BLINTER_BACKUP=%TEMP%\blinter_backup_%RANDOM%_%RANDOM%
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

echo Latest Blinter release: !BLINTER_VERSION!
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
        echo Blinter !BLINTER_VERSION! is already installed and up to date.
        goto :end
    )
    if exist "%BLINTER_BIN%\blinter.exe" (
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

    if exist "%BLINTER_BIN%\blinter.exe" del /F /Q "%BLINTER_BIN%\blinter.exe" >nul 2>&1
)

REM Download Blinter
echo Downloading Blinter !BLINTER_VERSION! from:
echo !BLINTER_URL!
echo.
curl -L -f --progress-bar -o "%BLINTER_TEMP%.zip" "!BLINTER_URL!" 2>&1
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

REM Locate extracted executable
set BLINTER_SOURCE_EXE=
set "BLINTER_SOURCE_EXE=%BLINTER_TEMP%\Blinter-!BLINTER_VERSION!\blinter.exe"
if not exist "!BLINTER_SOURCE_EXE!" (
    set BLINTER_SOURCE_EXE=
    for /f "tokens=*" %%f in ('dir /s /b "%BLINTER_TEMP%\blinter.exe" 2^>nul') do (
        set BLINTER_SOURCE_EXE=%%f
        goto :found_exe
    )
)

if "!BLINTER_SOURCE_EXE!"=="" (
    echo ERROR: Blinter executable not found in extracted archive.
    echo.
    echo Expected layout: Blinter-!BLINTER_VERSION!\blinter.exe
    echo The archive structure may have changed or be corrupted.
    goto :error_restore
)

REM Resume install after executable path is resolved
:found_exe

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
echo $ProgressPreference = 'SilentlyContinue'
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
echo         $asset = @($release.assets^) ^| Where-Object { $_.name -like 'Blinter-v*.zip' } ^| Select-Object -First 1
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
echo $item = Get-Item -LiteralPath '%BLINTER_TEMP%.zip' -ErrorAction Stop
echo Write-Output $item.Length
) > "!PS_FILE_SIZE!"
exit /b 0

REM Write PowerShell script to verify the downloaded archive SHA256.
REM Caret-escape each closing parenthesis, and write a literal caret as ^^, so this redirect stays intact.
:write_hash_verify_script
(
echo $expected = '%BLINTER_SHA256%'
echo $sha = [System.Security.Cryptography.SHA256]::Create(^)
echo try {
echo     $stream = [System.IO.File]::OpenRead('%BLINTER_TEMP%.zip'^)
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
echo try {
echo     Expand-Archive -LiteralPath '%BLINTER_TEMP%.zip' -DestinationPath '%BLINTER_TEMP%' -Force
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
echo try {
echo     $binPath = '%BLINTER_BIN%'
echo     $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
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
echo         [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'^)
echo         Write-Host 'Blinter added to User PATH permanently'
echo     }
echo     else {
echo         Write-Host 'Blinter already in User PATH'
echo     }
echo     exit 0
echo }
echo catch {
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
