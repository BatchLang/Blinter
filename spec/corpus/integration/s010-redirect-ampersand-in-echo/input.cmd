@echo off
echo see 2>&1 call :after_2to1
echo see 1>&2 goto :after_1to2
echo see >&2 call :after_gt2
exit /b 0
:after_2to1
exit /b 0
:after_1to2
exit /b 0
:after_gt2
exit /b 0
