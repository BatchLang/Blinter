@echo off
rem continued ^
exit /b 0
:after_rem
echo hi
echo hello^^
exit /b 0
:after_even
echo hi
rem. note ^
exit /b 0
:after_rem_dot
echo hi
rem/ note ^
exit /b 0
:after_rem_slash
echo hi
rem: note ^
exit /b 0
:after_rem_colon
echo hi
echo hi & rem note ^
exit /b 0
:after_amp_rem
echo hi
if 1==1 rem note ^
exit /b 0
:after_if_rem
echo hi
for %%i in (1) do rem note ^
exit /b 0
:after_for_rem
echo hi
echo "hello^
exit /b 0
:after_quote
echo hi
