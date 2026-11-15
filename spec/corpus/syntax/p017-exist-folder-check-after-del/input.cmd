@echo off
if exist out\ echo 1
del /q out
if exist out\ echo 2
if exist out\ echo 3
exit /b 0
