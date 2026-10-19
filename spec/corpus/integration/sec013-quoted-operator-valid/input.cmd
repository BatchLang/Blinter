@echo off
findstr /i "x" "%f%" >nul && echo found
md "%TEMP%\a" || echo exists
