@echo off
for /f "delims=" %%a in ('echo hello') do set VALUE=%%a
for /f "tokens=1-3 delims= " %%a in ("one two three") do (
    set URL=%%a
    set TAG=%%b
    set DIGEST=%%c
    set VALUE=%SOME_ENV%
)
for %%i in (1) do echo set result=!result!%%i
for %%i in (1) do echo prefix set RESULT=!RESULT!
for %%i in (1) do if 1==1 echo prefix set RESULT=!RESULT!
for %%i in (1) do rem set result=!result!
for %%i in (1) do (
    rem set result=!result!
)
exit /b 0
