@echo off
net session >nul 2>&1
if errorlevel 1 (
  echo Run as administrator
  exit /b 1
)
sc stop Spooler
exit /b 0
