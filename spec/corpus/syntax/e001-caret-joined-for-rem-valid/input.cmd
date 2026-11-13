@echo off
for %%A in (a ^
  rem b) do set "LAST=%%A"
echo after
ver >nul 2>&1
exit /b 0
