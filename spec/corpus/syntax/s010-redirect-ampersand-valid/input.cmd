@echo off
2>&1 >nul call :d1
dir >nul 2>&1 & call :after_nul
echo x >&2 & goto :after_gt2
exit /b 0
:d1
exit /b 0
:after_nul
exit /b 0
:after_gt2
exit /b 0
