@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" start_app.py
  exit /b %ERRORLEVEL%
)
echo Local Python environment was not found.
echo Run BUILD_EXE.bat first.
pause
exit /b 1
