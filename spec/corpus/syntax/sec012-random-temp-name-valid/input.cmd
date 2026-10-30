@echo off
set "scratch=%TEMP%\app_%RANDOM%.tmp"
echo x > "%scratch%"
del "%scratch%"
exit /b 0
