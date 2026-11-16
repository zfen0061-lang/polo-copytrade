@echo off
title Polo - Demo stop test ONLY
cd /d "%~dp0"
.venv\Scripts\python.exe -m backend.demo_verify
pause
