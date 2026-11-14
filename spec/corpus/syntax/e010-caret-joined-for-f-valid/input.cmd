@echo off
for /f "usebackq delims=" %%F in (`echo one ^
  two`) do echo %%F
exit /b 0
