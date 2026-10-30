@echo off
setlocal enabledelayedexpansion
for %%i in (1 2) do echo !errorlevel!
endlocal
exit /b 0
