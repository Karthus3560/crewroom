@echo off
rem Double-click to install Crewroom (sets up the "team" skill and a Desktop shortcut).
if not exist "%~dp0install.ps1" (
  echo.
  echo   Please right-click the Crewroom zip, choose "Extract All", then run install.cmd from the extracted folder.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
