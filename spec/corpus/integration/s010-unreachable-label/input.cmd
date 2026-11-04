@echo off
goto :done
:jumped
echo skipped
:done
echo reached
exit /b 0
:after_exit
exit /b 1
