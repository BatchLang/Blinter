@echo off
del "%LOCALAPPDATA%\Programs\App\app.exe"
copy /Y "%TEMP%\fresh\app.exe" "%LOCALAPPDATA%\Programs\App\app.exe"
del "%TEMP%\tool.dll"
exit /b 0
