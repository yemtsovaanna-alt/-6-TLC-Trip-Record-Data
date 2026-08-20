@echo off
cd /d "%~dp0"

:: Elevate if needed (Program Files sync requires Admin)
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator rights to sync into Grafana...
  powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

python _run_wait_heatmaps.py
if errorlevel 1 (
  echo.
  echo Pipeline failed.
  pause
  exit /b 1
)

echo.
echo Opening dashboard...
start "" "http://localhost:3000/d/nyc-taxi-home"
pause
