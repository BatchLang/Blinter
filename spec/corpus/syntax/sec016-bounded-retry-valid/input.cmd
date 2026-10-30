@echo off
set /a attempts=0
:retry
set /a attempts+=1
if %attempts% geq 5 exit /b 1
ping -n 2 127.0.0.1 >nul
goto :retry
