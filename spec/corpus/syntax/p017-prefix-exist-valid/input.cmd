@echo off
set "BLINTER_TEMP=%TEMP%\blinter_demo"
if exist "%BLINTER_TEMP%.zip" echo zip
if exist "%BLINTER_TEMP%" echo dir
if exist "%BLINTER_TEMP%_get_release.ps1" echo get
if exist "%BLINTER_TEMP%_expand.ps1" echo expand
exit /b 0
