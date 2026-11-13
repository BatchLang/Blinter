@echo off
setlocal enabledelayedexpansion
for /f "usebackq delims=" %%F in (`echo one ^
  two`) do set "NOW=%%F"
for %%A in (a b ^
  c) do set "LAST=%%A"
:: after the loops
set /a N=1+1
echo !NOW! !LAST! !N!
ver >nul 2>&1
shift
endlocal
exit /b 0
