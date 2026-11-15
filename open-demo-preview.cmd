@echo off
title Polo CopyTrade - Demo preview without credentials
cd /d "%~dp0"
.venv\Scripts\python.exe -m backend.demo_connect --preview
pause
