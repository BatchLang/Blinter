@echo off
if exist folder (
  rmdir /s /q folder
  if %errorlevel% equ 0 echo removed
)
exit /b 0
