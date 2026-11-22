@echo off
chcp 65001 >nul
cd /d "%~dp0"
python moon_tool.py
echo.
pause
