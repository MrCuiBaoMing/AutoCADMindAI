@echo off
setlocal
cd /d "%~dp0"

set "LOG_FILE=%~dp0bridge_start.log"
echo ==== [%date% %time%] start.bat begin ==== > "%LOG_FILE%"
echo CWD=%cd% >> "%LOG_FILE%"

if exist "venv\Scripts\python.exe" (
  echo Using venv python >> "%LOG_FILE%"
  "venv\Scripts\python.exe" start.py >> "%LOG_FILE%" 2>&1
  echo ExitCode=%errorlevel% >> "%LOG_FILE%"
  exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
  echo Using py launcher >> "%LOG_FILE%"
  py start.py >> "%LOG_FILE%" 2>&1
  echo ExitCode=%errorlevel% >> "%LOG_FILE%"
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  echo Using system python >> "%LOG_FILE%"
  python start.py >> "%LOG_FILE%" 2>&1
  echo ExitCode=%errorlevel% >> "%LOG_FILE%"
  exit /b %errorlevel%
)

echo Python not found. >> "%LOG_FILE%"
exit /b 9009
