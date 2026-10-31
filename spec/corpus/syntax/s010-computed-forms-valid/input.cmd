@echo off
goto a_%1
goto:b_%1
call :c_%~1
goto d_!X!
for %%a in (x) do goto e_%%a
goto F_%1
if "%1"=="" goto :g_%2
if defined X (goto h_%X%)
:a_x
:b_x
:c_x
:d_x
:e_x
:f_x
:g_x
:h_x
exit /b 0
