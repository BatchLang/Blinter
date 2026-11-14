@echo off
for /f "usebackq" %%A in (`echo (hello)`) do echo %%A
exit /b 0
