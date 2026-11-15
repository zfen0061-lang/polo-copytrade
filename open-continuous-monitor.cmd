@echo off
cd /d "%~dp0"
"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_monitor.ps1"
if errorlevel 1 pause
