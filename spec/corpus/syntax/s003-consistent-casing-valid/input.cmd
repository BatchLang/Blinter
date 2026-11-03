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
dir ^^& rem SET value
dir ^^^^& rem SET value
dir SET value
dir ^& SET value
dir ^^^& SET value
call :x SET value
if exist x dir SET value
cmd /c dir ^^^& SET value
start cmd /k dir ^^^| SET value
start C:\Windows\System32\cmd.exe /c dir ^^^& SET value
start "" cmd /c dir ^^^& SET value
start ver ^^^& SET value
for %%i in ('ver ^& SET value') do echo %%i
for /f %%a in (f.txt) do dir SET value
if exist C:\Program^ Files SET value
if x==y (dir ^& SET value)
dir (x) ^& SET value
for /f %%a in ('ver') do dir ^& SET value
set q=^" & set r=2 & dir ^"
cmd /c "echo hi & set s=2"
cmd /k "set s=3"
cmd.exe /d /c "set s=4"
set z="unclosed & SET hidden
set t=^"a" & SET u=2
set x=%p:" & SET fake "=%
set x=%p:a="% & SET q="x"
set x=%p:%"=Y% & SET q=1
set x=%p:a% & SET q=1 & echo %y%
set x=%p:a%y% & SET q=1 & set z=%w%
set x=%" & SET hidden=1%
echo %x% %y%
exit /b 0
