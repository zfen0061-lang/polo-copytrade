@echo off
cd /d "%~dp0"
echo Polo CopyTrade - prepare v0.3.0-preview draft release
git rev-parse --verify refs/tags/v0.3.0-preview >nul 2>nul
if errorlevel 1 goto missing
git diff --quiet
if errorlevel 1 goto dirty
git diff --cached --quiet
if errorlevel 1 goto dirty
git push --set-upstream origin main
if errorlevel 1 goto failed
git push origin refs/tags/v0.3.0-preview
if errorlevel 1 goto failed
echo Preview tag uploaded. GitHub will build and test the app again, then create a draft Release.
echo https://github.com/zfen0061-lang/polo-copytrade/actions
echo The draft is not yet a published public download. No trading program was started.
pause
exit /b 0

:missing
echo Use the existing local Git project prepared by the maintainer. The preview tag is missing.
pause
exit /b 1

:dirty
echo Tracked changes need review and commit before publishing.
pause
exit /b 1

:failed
echo Push stopped. Read the Git error above. No force push was attempted.
pause
exit /b 1
