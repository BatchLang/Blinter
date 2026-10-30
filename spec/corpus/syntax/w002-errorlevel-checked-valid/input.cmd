@echo off
copy a.txt b.txt
if errorlevel 1 exit /b 1
exit /b 0
