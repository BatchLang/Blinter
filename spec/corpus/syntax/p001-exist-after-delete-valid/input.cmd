@echo off
set "F=%TEMP%\blinter_f"
if exist "%F%" del /f /q "%F%"
if exist "%F%" (
    echo Error: could not delete "%F%".
    exit /b 1
)
if exist old.log erase old.log
if exist old.log echo still there
if exist "%TEMP%\blinter_d" rd /s /q "%TEMP%\blinter_d"
if exist "%TEMP%\blinter_d" echo still there
if exist build rmdir /s /q build
if exist build echo still there
if exist a.txt move /y a.txt b.txt
if exist a.txt echo not moved
if exist c.txt ren c.txt d.txt
if exist c.txt echo not renamed
if exist e.txt (
    del e.txt
)
if exist e.txt echo still there
exit /b 0
