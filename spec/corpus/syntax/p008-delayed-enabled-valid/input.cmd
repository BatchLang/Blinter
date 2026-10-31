@echo off
REM A "!VAR!" in prose.
:: A "!VAR!" in prose.
setlocal enabledelayedexpansion
for %%i in (1 2) do echo !errorlevel!
endlocal
exit /b 0
