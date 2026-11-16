@echo off
title Polo - Dedicated sub-account API (hidden input; no orders)
cd /d "%~dp0"
.venv\Scripts\python.exe -m backend.trading_connect --no-browser
pause
