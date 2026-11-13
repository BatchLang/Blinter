@echo off
browstat status
inuse file.dll /Y
streams -s file.txt
exit /b 0
