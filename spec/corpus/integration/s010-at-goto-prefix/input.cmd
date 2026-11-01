@echo off
for %%a in (x) do @goto case_%%a
echo hi & @goto case_%1
:case_x
exit /b 0
:dead
exit /b 0
