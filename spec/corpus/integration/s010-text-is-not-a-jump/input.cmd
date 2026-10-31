@echo off
REM goto %ACTION%
set "MSG=call :%~1"
set MSG=goto %1
findstr /c:"goto %1" x.txt
title call :%1
call foo.bat goto %1
>out.txt echo goto %1
call :sub %1
call %FN%
for %%a in (x) do echo do goto %1
exit /b 0
:sub
exit /b 0
:dead
exit /b 0
