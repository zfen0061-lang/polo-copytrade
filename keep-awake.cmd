@echo off
title Polo CopyTrade - AC idle-sleep guard
cd /d "%~dp0"
echo Keep Windows awake on AC while the read-only signal observer is active.
echo Screen-off is allowed. Manual sleep, lid close, shutdown and restart are not prevented.
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m backend.awake
) else (
  python -m backend.awake
)
pause
