@echo off
set a=1
set b=1
set c=1
set d=1
set e=1
set f=1
set g=1
set h=1
set i=1
set j=1
set k=1
set l=1
dir & cmd /c "echo hi & SET p=1"
dir && cmd /k "SET p=2"
dir | cmd.exe /d /c "SET p=3"
if 1==1 ( cmd /c "SET p=4")
if 1==1 (cmd /c "SET p=5")
set m=1 & @cmd /c "SET p=6"
set n=1 & C:\Windows\System32\cmd.exe /c "SET p=7"
set o=1 & cmd /s /c "SET p=8"
set q=1 & cmd /c"echo hi & SET p=9"
set r=1&cmd /c "SET p=10"
