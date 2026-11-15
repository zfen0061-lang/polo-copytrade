@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m backend.credential_store --forget
pause
