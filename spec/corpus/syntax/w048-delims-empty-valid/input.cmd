@echo off
for /f "delims=" %%a in (file.txt) do echo %%a
exit /b 0
