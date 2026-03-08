@echo off
setlocal
cd /d "%~dp0"

echo [AutoCADMindAI] Working dir: %cd%

echo [AutoCADMindAI] Trying venv python...
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" start.py
  echo [AutoCADMindAI] ExitCode: %errorlevel%
  pause
  exit /b %errorlevel%
)

echo [AutoCADMindAI] venv not found, trying py...
where py >nul 2>nul
if %errorlevel%==0 (
  py start.py
  echo [AutoCADMindAI] ExitCode: %errorlevel%
  pause
  exit /b %errorlevel%
)

echo [AutoCADMindAI] py not found, trying python...
where python >nul 2>nul
if %errorlevel%==0 (
  python start.py
  echo [AutoCADMindAI] ExitCode: %errorlevel%
  pause
  exit /b %errorlevel%
)

echo [AutoCADMindAI] 未找到 Python，请先安装 Python 或创建 venv。
pause
exit /b 9009
