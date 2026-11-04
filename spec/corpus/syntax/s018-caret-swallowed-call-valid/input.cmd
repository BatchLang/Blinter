@echo off
echo bye ^
call :worker
exit /b 0
:worker
exit /b 1
