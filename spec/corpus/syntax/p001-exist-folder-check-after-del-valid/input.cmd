@echo off
if exist out\ echo 1
del /q out
if exist out echo 2
exit /b 0
