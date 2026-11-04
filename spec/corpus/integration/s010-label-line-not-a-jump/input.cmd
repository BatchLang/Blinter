@echo off
:start & goto %ACTION%
echo staying
exit /b 0
:dead
exit /b 1
