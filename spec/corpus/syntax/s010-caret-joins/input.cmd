@echo off
echo rem ^
exit /b 0
:after_echo_rem
echo hi
if exist rem ^
exit /b 0
:after_exist
echo hi
rem) ^
exit /b 0
:after_rem_paren
echo hi
:: remark ^
exit /b 0
:after_dcolon
echo hi
remote ^
exit /b 0
:after_remote
echo hi
:lab ^
exit /b 0
:after_label
echo hi
echo "ok" ^
exit /b 0
:after_closed_quote
echo hi
