@echo off
for %%i in (a) do (
  echo %%i
)
if 1==1 (
  echo ok
) else (
  echo fail >nul
)
