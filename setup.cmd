@echo off
setlocal
cd /d "%~dp0"
echo Polo CopyTrade 0.2.1 - prepare public/account collector
echo This installs dependencies only. It does not ask for keys or start trading.
echo [1/4] Checking Python...
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto python_failed
echo [2/4] Preparing project virtual environment...
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto failed
)
echo [3/4] Installing Playwright from the configured package index...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --timeout 15 --retries 1 -r requirements-collector.txt
if errorlevel 1 goto failed
echo [4/4] Installing Chromium. Download progress appears below.
set PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=15000
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m backend.doctor
if errorlevel 1 goto failed
echo Setup complete. Use start.cmd for the dashboard, or connect-account.cmd for account setup.
pause
exit /b 0

:python_failed
echo Python 3.10+ could not be started. Install Python and reopen this window.
pause
exit /b 1

:failed
echo Setup stopped. The error is shown above; no account was connected.
echo Check your network and Python installation, then rerun setup.cmd.
echo To inspect current local dependencies without a download, run check.cmd.
pause
exit /b 1
