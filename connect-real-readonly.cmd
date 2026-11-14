@echo off
title Polo CopyTrade - Read-only account connection
cd /d "%~dp0"
echo Enter keys in this local window only. Input is hidden.
echo This session reads your production account. Account order execution is disabled.
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m backend.connect --production-read-only --open-browser --no-runner
) else (
  python -m backend.connect --production-read-only --open-browser --no-runner
)
pause
