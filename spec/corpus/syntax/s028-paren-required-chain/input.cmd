@echo off
if /i "%~1"=="-v" (set "V=1" & shift & goto :parse)
