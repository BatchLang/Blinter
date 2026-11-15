@echo off
if exist tmp echo 1
del /q tmp
if exist tmp\ echo 2
if exist tmp\ echo 3
exit /b 0
