@echo off
echo before
:section
echo after
goto :done
echo skipped
:done
echo reached
exit /b 0
