@echo off
set "target_pid=%~1"
if not defined target_pid exit /b 1
taskkill /pid %target_pid%
exit /b 0
