@echo off
title ToDo - local demo
powershell.exe -NoProfile -Command "if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) { Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -WindowStyle Hidden }"
wsl.exe -d Ubuntu-24.04 --cd /home/t0mb/projects/todo bash scripts/demo.sh
if errorlevel 1 (
 echo.
 echo Startup failed. See the message above.
 pause
 exit /b 1
)
start "" "http://localhost:5173/"
