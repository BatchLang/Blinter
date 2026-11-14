@echo off
set "F=%TEMP%\blinter_entry"
if exist "%F%" rmdir /s /q "%F%" 2>nul
if exist "%F%" del /f /q "%F%"
if exist "%F%" (
    echo Error: could not delete "%F%".
    exit /b 1
)
exit /b 0
