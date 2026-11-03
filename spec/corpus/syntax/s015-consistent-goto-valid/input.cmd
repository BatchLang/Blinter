@echo off
goto :one
:one
goto :two
:two
echo see 1>&2 goto two
exit /b 0
