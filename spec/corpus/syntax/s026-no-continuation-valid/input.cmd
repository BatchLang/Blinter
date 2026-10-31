@echo off
echo one
findstr /r "^[0-9]" input.txt
REM findstr /r "^[0-9]" matches digits.
:: findstr /r "^[0-9]" matches digits.
REM a^b
:: a^b
exit /b 0
