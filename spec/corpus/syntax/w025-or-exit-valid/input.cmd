@echo off
copy a.txt b.txt || exit /b 1
exit /b 0
