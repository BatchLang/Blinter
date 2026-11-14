@echo off
for %%A in (a ^
  (b) do rem note ^
for %%B in (b) do echo %%B
exit /b 0
