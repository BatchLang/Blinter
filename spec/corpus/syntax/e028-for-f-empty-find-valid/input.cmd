@echo off
for /f "delims=" %%a in ('ver ^| find /v ""') do echo %%a
