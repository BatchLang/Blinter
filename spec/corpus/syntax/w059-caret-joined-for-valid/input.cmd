@echo off
for %%A in (x y) do (
  for %%b in (p ^
    q) do echo %%b
  echo %%A
)
echo 50%%a
exit /b 0
