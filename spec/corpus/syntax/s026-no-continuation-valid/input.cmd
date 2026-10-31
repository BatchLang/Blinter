@echo off
echo one
findstr /r "^[0-9]" input.txt
REM findstr /r "^[0-9]" matches digits.
:: findstr /r "^[0-9]" matches digits.
REM a^b
:: a^b
REM note & echo x^y
REM note | echo x^y
:: note & echo x^y
exit /b 0
