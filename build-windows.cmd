@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\build_windows.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\smoke_windows.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\archive_windows.py
if errorlevel 1 goto failed
echo Ready: dist\PoloCopyTrade-Windows-x64.zip
pause
exit /b 0
:failed
echo Build stopped. Read the error above. No account was connected.
pause
exit /b 1
