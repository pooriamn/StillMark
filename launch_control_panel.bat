@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3.11+ and reopen this launcher.
  pause
  exit /b 2
)
python scripts\control_panel.py --doctor --launcher-check
if errorlevel 2 (
  echo.
  echo Control panel doctor found blocking issues. Fix the errors above before launching.
  pause
  exit /b 2
)
python scripts\control_panel.py
if errorlevel 1 (
  echo.
  echo Control panel failed to start.
  pause
)
