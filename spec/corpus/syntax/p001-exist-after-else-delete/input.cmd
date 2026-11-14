@echo off
if exist a1.txt (echo y) else (echo n & del a1.txt)
if exist a1.txt echo 2
if exist a2.txt (echo y) else (echo n && del a2.txt)
if exist a2.txt echo 2
if exist a3.txt (echo y) else (echo n | del a3.txt)
if exist a3.txt echo 2
if exist a4.txt (echo y) else (
    del a4.txt
)
if exist a4.txt echo 2
exit /b 0
