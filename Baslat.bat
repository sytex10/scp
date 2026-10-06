@echo off
chcp 65001 >nul
title AI Scenepack Maker
cd /d "%~dp0"
echo ===================================================
echo     AI YouTube Scenepack Maker Baslatiliyor...
echo ===================================================
timeout /t 2 >nul
start http://localhost:5000
python app.py
pause
