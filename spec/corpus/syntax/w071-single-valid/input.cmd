@echo off
setlocal EnableDelayedExpansion
if 1==1 (
  echo %time%
)
if 1==1 (
  if !errorlevel! equ 0 echo ok
)
if 1==1 (
  >&2 echo %errorlevel%
)
if 1==1 (
  echo %time% >&2
)
exit /b 0
