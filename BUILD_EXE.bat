@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo       Electric Shovel Control Console Builder
echo ==============================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo Build failed. Error code: %ERR%
  echo Please copy the error message and send it back for diagnosis.
) else (
  echo Build succeeded.
  echo You can now run START_UI.bat.
)
echo.
pause
exit /b %ERR%
