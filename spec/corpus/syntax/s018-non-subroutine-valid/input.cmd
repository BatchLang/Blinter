@echo off
echo before
:section
echo after
goto :done
:done
echo reached
exit /b 0
