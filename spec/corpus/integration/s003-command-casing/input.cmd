@echo off
set x=1
set w=3
set v=5
set u=7
set t=9
set a=1
set b=1
set c=1
set d=1
echo.& SET d=4
dir a ^& rem x & SET f=6
for %%i in (rem a b) do SET g=1
set m=^" & SET n=2 & dir ^"
cmd /c "echo hi & SET p=2"
cmd /k "SET p=3"
cmd.exe /d /c "SET p=4"
dir ^^& rem SET ignored
set p=%p:"=% & SET q=1
set p=%p:"=% & SET q="x"
set x=%my var:"=% & SET y=1
set p=50% & dir c: & SET a=1 %
set x=^%p:a="% & SET q=1
SET y=2
set x=%"=Y% & SET q=1
set x=%p:%%"=Y% & SET q=1
set x=%p:a%"=Y% & SET q=1
set x=%p:a%"=Y"% & SET q=1
cmd /c echo A ^& SET e=1
start cmd /k dir ^| SET e=2
cmd /c ^"set e=3 ^& SET e=4^"
if %my var% == x SET e=5
for /f %%a in ('ver ^& SET e^=6') do echo %%a
!comspec! /c SET e=7
cmd /d/c dir ^& SET e=8
cmd /c (dir) ^& SET e=9
cmd /c (SET e=10 ^& SET e=11)
%comspec% /c (dir) ^& SET e=12
cmd /c if 1==1 (dir) ^& SET e=13
cmd /r SET e=14
set f=1
set f=2
set f=3
set f=4
set f=5
set f=6
set f=7
set f=8
set f=9
set f=10
set f=11
set f=12
set f=13
