@echo off
title Polo CopyTrade - local read-only account connection
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m backend.supervisor --connect-account
) else (
  python -m backend.supervisor --connect-account
)
pause
