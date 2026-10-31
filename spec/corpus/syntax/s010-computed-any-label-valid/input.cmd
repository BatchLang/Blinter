@echo off
set "ACTION=%~1"
if "%ACTION%"=="" exit /b 0
shift /1
goto %ACTION%

:x
echo x
exit /b 0
