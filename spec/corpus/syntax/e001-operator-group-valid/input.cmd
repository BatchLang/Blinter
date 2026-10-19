@echo off
cmd || (
    echo fallback
)
cmd && (
    echo ok
)
echo x & (
    echo y
)
(echo a) >> log.txt
(echo x) | find "x"
