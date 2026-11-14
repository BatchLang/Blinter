@echo off
if exist a1.txt echo 1
for /l %%i in (1,1,3) do del a1.txt
if exist a1.txt echo 2
if exist a2.txt echo 1
call del a2.txt
if exist a2.txt echo 2
if exist a3.txt echo 1
cmd /c del a3.txt
if exist a3.txt echo 2
if exist a4.txt echo 1
2>nul del a4.txt
if exist a4.txt echo 2
set "F=%TEMP%\blinter_forms"
if exist "%F%" echo 1
del /f /q "%F%">nul 2>&1
if exist "%F%" echo 2
if exist a6.txt echo 1
del a6.txt>nul
if exist a6.txt echo 2
if exist a7.txt echo 1
echo y| del a7.txt
if exist a7.txt echo 2
if exist a8.txt echo 1
del a8.txt,b8.txt
if exist a8.txt echo 2
if exist a9.txt echo 1
rename a9.txt b9.txt
if exist a9.txt echo 2
if exist a10.txt echo 1
for %%i in (1) do @del a10.txt
if exist a10.txt echo 2
if exist a11.txt @del a11.txt
if exist a11.txt echo 2
if exist e.txt echo 1
if defined Q (echo a) else (del e.txt)
if exist e.txt echo 2
if defined Q (echo a)else (del e.txt)
if exist e.txt echo 3
if exist out echo 1
rd /s /q obj(x64) out
if exist out echo 2
if exist build(x64) echo 1
rd /s /q build(x64)
if exist build(x64) echo 2
if exist a12.txt echo 1
del x^) a12.txt
if exist a12.txt echo 2
exit /b 0
