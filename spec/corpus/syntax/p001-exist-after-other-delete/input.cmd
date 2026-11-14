@echo off
if exist keep.txt del other.txt
if exist keep.txt echo again
if exist seen.txt echo one
echo del seen.txt
if exist seen.txt echo two
if exist log.txt del other.log
rem echo y| del log.txt
if exist log.txt echo two
if exist log.txt echo three
if exist a.txt (del /q a.txt.bak) else (echo a.txt missing)
if exist a.txt echo 2
if exist out\ (move a.txt out\) else (echo no folder)
if exist out\ echo 2
if exist b.txt echo 1
if defined X (del c.txt) else (echo b.txt)
if exist b.txt echo 2
if exist b.txt echo 3
if exist g.txt (del a.txt)else (echo g.txt)
if exist g.txt echo 2
if exist h.txt (echo h.txt) else (del h.txt)
if exist h.txt echo 2
exit /b 0
