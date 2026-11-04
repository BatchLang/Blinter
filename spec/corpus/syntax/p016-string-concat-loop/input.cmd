@echo off
setlocal enabledelayedexpansion
for %%i in (1) do (
  set result=!result!%%i
  set pair=%%i%%i
  set result="!result!%%i"
  if exist echo.txt set result=!result!%%i
)
