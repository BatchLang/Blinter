@echo off
call :ok.extra
call :paren(more)
call :entry
call :ok
exit /b 0
:ok.extra
exit /b 0
:paren(more)
exit /b 0
:entry rem text
exit /b 0
:ok:extra
exit /b 0
