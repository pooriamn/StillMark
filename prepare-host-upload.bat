@echo off
cd /d "%~dp0"
python build_site.py
if errorlevel 1 (
  echo Build failed. See the messages above.
  pause
  exit /b 1
)
echo.
echo Upload the contents of the dist folder to your host.
pause
