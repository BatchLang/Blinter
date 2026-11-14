@echo off
for %%A in (a ^
  "x) do rem note" ^
  b) do echo %%A
exit /b 0
