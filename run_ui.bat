@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py
  exit /b %ERRORLEVEL%
)
py -3.11 app.py
