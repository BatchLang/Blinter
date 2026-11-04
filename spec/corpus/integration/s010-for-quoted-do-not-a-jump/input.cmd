@echo off
for /f %%a in ("do goto %1") do echo %%a
exit /b 0
:dead
exit /b 1
