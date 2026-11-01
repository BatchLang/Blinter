@echo off
if defined A if defined B goto case_%1
:case_a
exit /b 0
:dead
exit /b 0
