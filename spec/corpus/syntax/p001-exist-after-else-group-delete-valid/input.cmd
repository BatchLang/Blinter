@echo off
if exist a1.txt (echo y) else (echo n) & del a1.txt
if exist a1.txt echo failed
if exist a2.txt (echo y) else (echo n)&& del a2.txt
if exist a2.txt echo failed
if exist a3.txt (
    echo y
) else (
    echo n
) & del a3.txt
if exist a3.txt echo failed
if exist a4.txt (echo y) else (echo n & echo m) & del a4.txt
if exist a4.txt echo failed
exit /b 0
