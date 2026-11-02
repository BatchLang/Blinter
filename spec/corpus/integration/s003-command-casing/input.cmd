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
