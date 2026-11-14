@echo off
if exist a.txt echo 1
if exist a.txt (echo 2) else (del a.txt)
if exist a.txt echo 3
if exist b.txt echo 1
if exist b.txt (echo 2) else (
    del b.txt
)
if exist b.txt echo 3
if exist c.txt echo 1
if exist c.txt (
    echo 2
) else (
    del c.txt
)
if exist c.txt echo 3
if exist d.txt echo 1
if exist d.txt echo 2
@if exist d.txt (echo y) else (del d.txt)
if exist d.txt echo 3
if exist e.txt echo 1
if exist e.txt echo 2
echo x & if exist e.txt (echo y) else (del e.txt)
if exist e.txt echo 3
exit /b 0
