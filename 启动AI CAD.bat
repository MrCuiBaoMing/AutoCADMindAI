@echo off
cd /d "%~dp0"
python start.py
if errorlevel 1 pause
