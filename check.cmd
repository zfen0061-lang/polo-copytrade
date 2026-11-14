@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m backend.doctor
) else (
  python -m backend.doctor
)
pause
