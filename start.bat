@echo off
title SteelSeries OLED PC Monitor
cd /d "%~dp0"

echo Starting SteelSeries OLED Hardware Monitor...
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in your system PATH!
    echo Please install Python 3 or add it to PATH.
    pause
    exit /b 1
)

echo Stopping any existing background instances...
taskkill /f /im pythonw.exe >nul 2>&1
timeout /t 1 /nobreak >nul

python app.py
if %errorlevel% neq 0 (
    echo.
    echo [Program stopped with error code %errorlevel%]
    pause
)
