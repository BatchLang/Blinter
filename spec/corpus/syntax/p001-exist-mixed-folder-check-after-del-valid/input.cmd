@echo off
if exist out echo 1
del /q out
if exist out\ echo 2
if exist "logs" echo 1
erase /q logs
if exist "logs\" echo 2
if exist cache\ echo 1
del /q cache
if exist cache echo 2
exit /b 0
