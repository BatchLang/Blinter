@echo off
for %%a in (1 2) do call :sub %%a
exit /b 0

:sub
echo %1
exit /b 0
