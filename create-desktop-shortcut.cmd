@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe scripts\install_desktop.py
) else (
  python scripts\install_desktop.py
)
pause
