@echo off
rmdir folder
if 1==1 (
  if %errorlevel% equ 0 echo ok
)
exit /b 0
