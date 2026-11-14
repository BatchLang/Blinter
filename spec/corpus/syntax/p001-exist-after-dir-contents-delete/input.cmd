@echo off
if exist "cache\" echo 1
del /q "cache\"
if exist "cache\" echo 2
if exist out echo 1
erase /q out\
if exist out echo 2
if exist tmp\ echo 1
rd /s /q tmp\
if exist tmp\ echo 2
exit /b 0
