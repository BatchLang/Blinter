@echo off
if exist "file.txt" echo found
if "%1"=="yes" echo yes
exit /b 0
