@echo off
setlocal enabledelayedexpansion
set "VERDICT=%~1"
set "VERSION=%~2"
set "CURRENT=%~3"
if "!VERDICT!"=="MALFORMED" (
    echo Refusing !VERSION!: a version is digits and dots.
    endlocal
    goto :error
)
if "!VERDICT!"=="MISSING" endlocal & goto error
if "!VERDICT!"=="OLDER" (
    echo Refusing !VERSION!: it is older than !CURRENT!.
)
endlocal
exit /b 0
:error
echo Update failed.
exit /b 1
