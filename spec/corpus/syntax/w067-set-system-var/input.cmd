@echo off
set USERNAME=demo
set "PATH=C:\only-this"
set "PATH=C:\only-this" & echo %PATH%
set "PATH=!PATH!;C:\new"
set PATH=C:\o'malley & echo %PATH%
set "PATH=C:\a^&b"
set "PATH=%PATH%;C:\tool" & set "PATH=C:\only-this"
set /p PATH=Current value: %PATH%
set /a PATH=%PATH%
set "PATH=%PATH%suffix"
if exist echo.txt set PATH=C:\only-this
set PATH="%PATH%";C:\new
for %%i in (1) do set PATH=C:\only-this
