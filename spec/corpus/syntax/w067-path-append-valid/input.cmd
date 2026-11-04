@echo off
setlocal EnableDelayedExpansion
set "PATH=%PATH%;C:\new"
set "PATH=C:\new;%PATH%"
set "PATH=!PATH!;C:\new"
set "Path=%Path%;C:\New"
set "PATH=%PATH%;C:\new" & echo done
set "PATH=%PATH%;C:\tool" & set "PATH=%PATH%;C:\more"
set "PATH=%PATH%;C:\tools" & echo set USERNAME=demo
set "NOTE=Please set PATH=C:\Tools"
for %%i in (1) do set "PATH=%PATH%;C:\new"
for /f "delims=" %%a in ('echo set PATH=C:\only') do set VALUE=%%a
exit /b 0
