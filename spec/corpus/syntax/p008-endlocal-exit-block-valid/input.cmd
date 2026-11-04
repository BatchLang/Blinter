@echo off
setlocal enabledelayedexpansion
set "VERDICT=%~1"
set "VERSION=%~2"
set "CURRENT=%~3"
if "!VERDICT!"=="MALFORMED" (
    echo Refusing !VERSION!: a version is digits and dots.
    endlocal
    exit /b 1
)
if "!VERDICT!"=="MISSING" endlocal & exit /b 2
if "!VERDICT!"=="OLDER" (
    echo Refusing !VERSION!: it is older than !CURRENT!.
) else (
    echo Refusing !VERSION!: it cannot be compared with !CURRENT!.
)
endlocal
exit /b 3
