@echo off
set "WAIT_SECONDS=5"
timeout /t %WAIT_SECONDS% /nobreak >nul
exit /b 0
