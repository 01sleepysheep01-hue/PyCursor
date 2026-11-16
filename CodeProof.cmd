@echo off
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" pythonw -m codeproof
) else (
  start "" python -m codeproof
)
