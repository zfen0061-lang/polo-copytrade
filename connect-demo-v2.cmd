@echo off
title Polo CopyTrade - Futures Demo ONLY
cd /d "%~dp0"
.venv\Scripts\python.exe -m backend.demo_connect
pause
