@echo off
set a=1
set b=1
dir & cmd /c "echo hi & set p=1"
dir && cmd /k "set p=2"
dir | cmd.exe /d /c "set p=3"
if 1==1 ( cmd /c "set p=4")
if 1==1 (cmd /c "set p=5")
set c=1 & @cmd /c "set p=6"
set d=1 & C:\Windows\System32\cmd.exe /c "set p=7"
set e=1 & cmd /s /c "set p=8"
set f=1 & cmd /c"echo hi & set p=9"
set g=1&cmd /c "set p=10"
dir & echo /c "SET hidden=1"
notcmd /c "SET hidden=2"
cmd /c echo "SET hidden=3"
set h=1 & notcmd /c "SET hidden=4"
set i=1 & cmd /c "set p=11" & echo "SET hidden=5"
