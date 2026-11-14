@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m backend.connect
) else (
  python -m backend.connect
)
pause
