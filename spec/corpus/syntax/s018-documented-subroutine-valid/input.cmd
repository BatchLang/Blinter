@echo off
call :greet world
exit /b 0

rem Greet prints a greeting. Args: %1 = name. Returns: 0
:greet
echo hello %1
exit /b 0
