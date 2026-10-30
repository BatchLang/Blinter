@echo off
for /f "tokens=1,2 delims=," %%a in (data.csv) do echo %%a
exit /b 0
