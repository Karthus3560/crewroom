@echo off
rem Double-click to install or update Crewroom (the "team" skill, plus Desktop and Start menu shortcuts).
if not exist "%~dp0install.py" (
  echo.
  echo   Please right-click the Crewroom zip, choose "Extract All", then run install.cmd from the extracted folder.
  echo.
  pause
  exit /b 1
)
set PYTHONIOENCODING=utf-8
set PY=
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set PY=python
if not defined PY (
  echo.
  echo   Crewroom needs Python 3.10 or newer. Get it from https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" while installing. Then double-click install.cmd again.
  echo.
  pause
  exit /b 1
)
%PY% "%~dp0install.py" %*
echo.
pause
