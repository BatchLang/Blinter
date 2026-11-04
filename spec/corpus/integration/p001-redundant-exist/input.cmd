@echo off
if exist file.txt echo found
if exist file.txt del file.txt
if exist "file one.txt" echo one
if exist "file one.txt" del "file one.txt"
if exist closed.txt (echo yes) else (echo no)
if exist closed.txt echo again
