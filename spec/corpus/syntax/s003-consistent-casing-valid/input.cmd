@echo off
set x=1
set y=2
powershell -NoProfile -Command "if ($x) { Exit 1 }; Exit 0"
echo.& REM Set the value
echo.& :: Set the value
echo.& @rem Set the value
(rem Set the value
)
dir | rem Set the value
echo %x% %y%
exit /b 0
