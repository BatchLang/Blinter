@echo off
set "x=abc"
if defined x echo %x:~0,1%
exit /b 0
