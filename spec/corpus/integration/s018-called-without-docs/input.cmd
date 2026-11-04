@echo off
call :worker
if "%~1"=="" call :from_if
echo x || call :from_or
exit /b 0

rem from_if takes no arguments and returns 0
:from_if
exit /b 0

:worker
exit /b 1

:from_or
exit /b 2
