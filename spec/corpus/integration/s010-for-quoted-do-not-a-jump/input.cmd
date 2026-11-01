@echo off
for /f %%a in ("do goto %1") do echo %%a
:dead
exit /b 0
