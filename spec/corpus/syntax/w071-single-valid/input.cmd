@echo off
setlocal EnableDelayedExpansion
if 1==1 (
  echo %time%
)
if 1==1 (
  if !errorlevel! equ 0 echo ok
)
exit /b 0
