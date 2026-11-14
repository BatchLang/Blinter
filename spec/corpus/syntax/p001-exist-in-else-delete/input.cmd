@echo off
if exist a.txt (echo y) else (
    if exist a.txt echo 1
    del a.txt
    if exist a.txt echo 2
)
if exist b.txt (
    echo y
) else (
    if exist b.txt echo 1
    del b.txt
    if exist b.txt echo 2
)
exit /b 0
