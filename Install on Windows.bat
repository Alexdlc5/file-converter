@echo off
setlocal
cd /d "%~dp0"
title File Converter setup

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"

if not defined PY goto :nopython
%PY% install.py
echo.
pause
exit /b

:nopython
echo Python isn't installed yet. File Converter needs it.
echo.
where winget >nul 2>nul
if errorlevel 1 goto :manual
echo Installing Python 3.12 now. Accept any prompts that appear...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo Done. Close this window, then double-click "Install on Windows.bat" again.
pause
exit /b 1

:manual
echo Download Python from https://www.python.org/downloads/
echo In its installer, tick "Add python.exe to PATH". Then run this file again.
start "" https://www.python.org/downloads/
pause
exit /b 1
