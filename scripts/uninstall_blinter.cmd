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
cmd /c call "%BLINTER_CRLF_COPY%"
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

REM ============================================================================
REM Blinter Uninstaller
REM Purpose: Remove Blinter from %LOCALAPPDATA% and user PATH
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

set "BLINTER_DIR=%LOCALAPPDATA%\Programs\Blinter"
set "BLINTER_BIN=%BLINTER_DIR%\bin"
set "BLINTER_RELEASE_FILE=%BLINTER_DIR%\installed_release.txt"
set "BLINTER_TEMP=%TEMP%\blinter_uninstall_%RANDOM%_%RANDOM%"

echo +=====================+
echo + Blinter Uninstaller +
echo +=====================+
echo.

REM Check if Blinter is installed
if not exist "%BLINTER_BIN%" (
    echo Blinter installation not found at: %BLINTER_BIN%
    echo.
    echo Nothing to uninstall.
    goto :end
)

if not exist "%BLINTER_BIN%\blinter.exe" (
    if not exist "%BLINTER_RELEASE_FILE%" (
        echo Blinter installation not found at: %BLINTER_BIN%
        echo.
        echo Nothing to uninstall.
        goto :end
    )
)

REM Display current version if available
if exist "%BLINTER_BIN%\blinter.exe" (
    echo Current installed version:
    "%BLINTER_BIN%\blinter.exe" --version 2>nul
    echo.
)

if exist "%BLINTER_RELEASE_FILE%" (
    REM LINT:IGNORE SEC001
    set /p INSTALLED_RELEASE=<"%BLINTER_RELEASE_FILE%"
    if not "!INSTALLED_RELEASE!"=="" (
        if /i not "!INSTALLED_RELEASE:~0,1!"=="v" set "INSTALLED_RELEASE="
    )
    if not "!INSTALLED_RELEASE!"=="" (
        echo Installed release: "!INSTALLED_RELEASE!"
        echo.
    )
)

echo Removing Blinter from: %BLINTER_DIR%
echo.

REM Terminate running Blinter processes before file removal
echo.
echo Checking for running Blinter processes...
echo.

set PROCESSES_KILLED=0
set "PS_STOP_BLINTER=%BLINTER_TEMP%_stop.ps1"
set "PS_STOP_OUT=%BLINTER_TEMP%_stop.out"
call :write_stop_blinter_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_STOP_BLINTER!" > "!PS_STOP_OUT!" 2>&1
if !errorlevel! neq 0 (
    echo WARNING: Failed to stop the installed blinter.exe.
    echo.
)
for /f "usebackq delims=" %%p in ("!PS_STOP_OUT!") do (
    echo Terminated !BLINTER_BIN!\blinter.exe ^(PID %%p^)
    set PROCESSES_KILLED=1
)
if exist "!PS_STOP_BLINTER!" del /F /Q "!PS_STOP_BLINTER!" >nul 2>&1
if exist "!PS_STOP_OUT!" del /F /Q "!PS_STOP_OUT!" >nul 2>&1

if !PROCESSES_KILLED! equ 0 (
    echo No running Blinter processes found.
    echo.
) else (
    echo.
    echo Waiting for processes to fully terminate...
    timeout /t 2 /nobreak >nul 2>&1
    echo.
)

REM Remove Blinter executables and release marker
echo Removing Blinter files...
echo.

set REMOVAL_FAILED=0
if exist "%BLINTER_BIN%\blinter.exe" (
    del /F /Q "%BLINTER_BIN%\blinter.exe" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Removed blinter.exe
    ) else (
        echo ERROR: Failed to remove blinter.exe. Error code: !errorlevel!
        set REMOVAL_FAILED=1
    )
)

if exist "%BLINTER_RELEASE_FILE%" (
    del /F /Q "%BLINTER_RELEASE_FILE%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Removed installed_release.txt
    ) else (
        echo ERROR: Failed to remove installed_release.txt. Error code: !errorlevel!
        set REMOVAL_FAILED=1
    )
)

if !REMOVAL_FAILED! equ 1 (
    echo.
    echo WARNING: Some files could not be removed.
    echo This may be because they are still in use or protected.
    echo.
)

REM Remove Blinter from PATH
echo.
echo Removing Blinter from User PATH...
echo.
set "PS_REMOVE_PATH=%BLINTER_TEMP%_remove_path.ps1"
call :write_remove_path_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_REMOVE_PATH!" 2>&1
if !errorlevel! neq 0 (
    echo WARNING: Failed to remove Blinter from User PATH.
    echo You may need to manually remove it from your environment variables.
    echo.
)
if exist "!PS_REMOVE_PATH!" del /F /Q "!PS_REMOVE_PATH!" >nul 2>&1

REM Remove Blinter installation directory after file and PATH cleanup
echo.
echo Removing Blinter installation directory...
echo.
if exist "%BLINTER_DIR%" (
    REM LINT:IGNORE SEC003
    rmdir /S /Q "%BLINTER_DIR%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Installation directory removed: !BLINTER_DIR!
        echo.
    ) else (
        echo WARNING: Failed to remove installation directory. Error code: !errorlevel!
        echo.
        echo This may be because files are in use or protected.
        echo You can manually delete: !BLINTER_DIR!
        echo.
        set REMOVAL_FAILED=1
    )
)

REM Display final status
echo.
if !REMOVAL_FAILED! equ 1 (
    echo +========================================+
    echo + Uninstallation completed with warnings +
    echo +========================================+
    echo.
    echo Some files or directories could not be removed.
    echo Please review the warnings above and take manual action if needed.
) else (
    echo +============================================+
    echo + SUCCESS: Blinter uninstalled successfully! +
    echo +============================================+
)
echo.
echo Note: You may need to restart your terminal or IDE for PATH changes to take effect.
echo.
goto :end

REM Stop only the installed blinter.exe, not another copy earlier on PATH.
:write_stop_blinter_script
(
echo #Requires -Version 5.1
echo $ErrorActionPreference = 'Stop'
echo $target = Join-Path $env:BLINTER_BIN 'blinter.exe'
echo $processes = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'blinter.exe'"^)
echo foreach ($process in $processes^) {
echo     $image = [string]$process.ExecutablePath
echo     if (-not $image^) { continue }
echo     if ($image -ine $target^) { continue }
echo     try {
echo         Stop-Process -Id $process.ProcessId -Force
echo         Write-Output $process.ProcessId
echo     } catch {
echo         Write-Error $_
echo         exit 1
echo     }
echo }
echo exit 0
) > "!PS_STOP_BLINTER!"
exit /b 0

REM Write PowerShell script to remove Blinter bin directory from user PATH
:write_remove_path_script
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
echo     if (-not $path^) {
echo         if ($key^) { $key.Close(^) }
echo         Write-Host 'User PATH is empty'
echo         exit 0
echo     }
echo     $pathArray = @($path -split ';' ^| Where-Object { $_ -ne '' }^)
echo     if ($pathArray -contains $binPath^) {
echo         $newPath = (@($pathArray ^| Where-Object { $_ -ne $binPath }^) -join ';'^)
echo         if ($kindName -eq 'ExpandString' -and $key^) {
echo             $key.SetValue('Path', $newPath, [Microsoft.Win32.RegistryValueKind]::ExpandString^)
echo         } else {
echo             [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'^)
echo         }
echo         Write-Host 'Blinter removed from User PATH'
echo     }
echo     else {
echo         Write-Host 'Blinter not found in User PATH'
echo     }
echo     if ($key^) { $key.Close(^) }
echo     exit 0
echo }
echo catch {
echo     if ($key^) { $key.Close(^) }
echo     Write-Host "ERROR: $_"
echo     exit 1
echo }
) > "!PS_REMOVE_PATH!"
exit /b 0

REM Print failure message and exit with error code
:error_exit
echo.
echo +==========================================================+
echo + Uninstallation failed. Please review the errors above. +
echo +==========================================================+
echo.
timeout /t 5 /nobreak
endlocal
exit /b 1

REM Successful completion
:end
endlocal
exit /b 0
