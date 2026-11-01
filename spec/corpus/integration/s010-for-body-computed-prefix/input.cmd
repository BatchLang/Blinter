@echo off
for /f %%a in ("do work") do goto case_%1
:case_a
exit /b 0
:dead
exit /b 0
