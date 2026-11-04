@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    echo The block goes on.
)
echo !A!
setlocal enabledelayedexpansion
if "!A!"=="2" (
    endlocal
    find "x" "%~f0" >nul || exit /b 2
)
echo !A!
if "%A%"=="3" (
    setlocal enabledelayedexpansion
    echo !A!
    endlocal
    exit /b 3
)
echo !A!
setlocal enabledelayedexpansion
if "!A!"=="4" (
    endlocal
    goto :show
)
exit /b 0
:show
echo !A!
exit /b 4
