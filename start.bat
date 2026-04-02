@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "LOG_FILE=%~dp0bridge_start.log"
echo ==== [%date% %time%] start.bat begin ==== >> "%LOG_FILE%"
echo CWD=%cd% >> "%LOG_FILE%"

echo ====================================================
echo   AI CAD - AutoCAD智能助手 启动程序
echo ====================================================
echo.

echo [1/3] 检测 Python 环境...
echo.

set "PYTHON_EXE="

if exist "venv\Scripts\python.exe" (
  set "PYTHON_EXE=venv\Scripts\python.exe"
  echo [OK] 检测到虚拟环境: venv\Scripts\python.exe
  goto :found_python
)

where py >nul 2>&1
if %errorlevel%==0 (
  for /f "delims=" %%i in ('where py') do (
    set "PYTHON_EXE=%%i"
    goto :found_python
  )
)

where python >nul 2>&1
if %errorlevel%==0 (
  for /f "delims=" %%i in ('where python') do (
    set "PYTHON_EXE=%%i"
    goto :found_python
  )
)

echo.
echo [错误] 未检测到 Python 环境！
echo.
echo 请先安装 Python 3.8 或更高版本：
echo   下载地址: https://www.python.org/downloads/
echo   安装时请勾选 "Add Python to PATH"
echo.
pause
exit /b 9009

:found_python
echo [OK] Python 路径: %PYTHON_EXE%
echo.

echo [2/3] 检测 pip 包管理器...
echo.

"%PYTHON_EXE%" -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
  echo [错误] pip 不可用！
  echo.
  echo 请重新安装 Python，确保勾选 pip 组件。
  echo.
  pause
  exit /b 9009
)

echo [OK] pip 可用
echo.

echo [3/3] 检测依赖包并自动安装...
echo.
echo 正在启动环境检测和依赖安装...
echo ====================================================
echo.

"%PYTHON_EXE%" start.py

set "EXIT_CODE=%errorlevel%"
echo. >> "%LOG_FILE%"
echo ExitCode=%EXIT_CODE% >> "%LOG_FILE%"

if %EXIT_CODE% neq 0 (
  echo.
  echo ====================================================
  echo [错误] 程序启动失败，错误代码: %EXIT_CODE%
  echo 请查看日志文件: %LOG_FILE%
  echo ====================================================
  echo.
  pause
  exit /b %EXIT_CODE%
)
