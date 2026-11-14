@echo off
title Polo CopyTrade - Aoying public signal observer
cd /d "%~dp0"
echo Observe public operations only. No paper or account orders are created.
echo Keep the read-only account dashboard running before starting this observer.
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m backend.observe
) else (
  python -m backend.observe
)
pause
