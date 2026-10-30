@echo off
rem Seconds to wait for the service to start
set "START_WAIT=5"
timeout /t %START_WAIT% /nobreak >nul
exit /b 0
