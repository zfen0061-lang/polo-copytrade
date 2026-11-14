@echo off
cd /d "%~dp0"
echo Polo CopyTrade - publish committed source to GitHub
echo Target: https://github.com/zfen0061-lang/polo-copytrade
echo This does not start trading or upload runtime data.
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 goto no_repository
git diff --quiet
if errorlevel 1 goto dirty
git diff --cached --quiet
if errorlevel 1 goto dirty
git remote set-url origin https://github.com/zfen0061-lang/polo-copytrade.git
if errorlevel 1 goto failed
echo Git may open a browser for sign-in. Use the zfen0061-lang account.
git push --set-upstream origin main
if errorlevel 1 goto failed
echo Source uploaded. Check build progress:
echo https://github.com/zfen0061-lang/polo-copytrade/actions
echo A successful push does not mean the Windows build has finished.
pause
exit /b 0

:no_repository
echo Run this script in the existing local Git project, not a source ZIP extraction.
pause
exit /b 1

:dirty
echo Tracked files have uncommitted changes. Ask the maintainer to review and commit them first.
echo Nothing was uploaded.
pause
exit /b 1

:failed
echo Upload stopped. Read the Git error above. No force push was attempted.
echo Finish any browser sign-in, then run this script again.
echo Do not send passwords, API keys, or tokens to chat.
pause
exit /b 1
