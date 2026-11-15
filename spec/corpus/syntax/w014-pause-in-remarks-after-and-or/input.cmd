@echo off
set /p answer=Continue?
echo one && ^
rem pause is not used here.
echo two || ^
:: timeout /t 5 is not used either.
echo Done
