@echo off
if exist out\ echo 1
move a.txt out\
if exist out\ echo 2
if exist d.txt echo 3
ren sub\c.txt d.txt
if exist d.txt echo 4
exit /b 0
