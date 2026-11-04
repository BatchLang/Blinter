@echo off
if "a"=="b" (
    if exist file.txt echo same
) else if exist file.txt (
    echo different
)
if exist "file one.txt" echo one
if exist "file two.txt" echo two
echo else if exist other.txt
if exist other.txt echo found
if exist branch.txt (
    echo yes
) else (
    if exist branch.txt echo missing
)
if exist same.txt (echo yes) else (
    if exist same.txt echo no
)
exit /b 0
