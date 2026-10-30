@echo off
if errorlevel 1 echo failed
if %ERRORLEVEL% equ 1 echo one
exit /b 0
