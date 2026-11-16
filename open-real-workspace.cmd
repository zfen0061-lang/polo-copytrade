@echo off
title Polo CopyTrade - Production workspace (execution off at startup)
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_real_workspace.ps1"
if errorlevel 1 pause
