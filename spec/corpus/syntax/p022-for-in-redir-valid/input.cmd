@echo off
for /f "delims=" %%S in ('cmd /c echo 5 2^>nul') do (
    set FILESIZE=%%S
)
exit /b 0
