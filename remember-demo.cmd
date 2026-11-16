@echo off
title Polo - Remember Demo connection ONLY
cd /d "%~dp0"
.venv\Scripts\python.exe -m backend.demo_connect --remember --no-browser
pause
