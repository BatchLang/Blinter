@echo off
:parse
if "%~1"=="" goto :done
shift
goto :parse
:done
exit /b 0
