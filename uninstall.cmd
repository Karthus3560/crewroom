@echo off
rem Double-click to remove Crewroom's skill and Desktop shortcut (your data is kept).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
pause
