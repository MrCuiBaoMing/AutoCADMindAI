@echo off
setlocal
cd /d "%~dp0"

set "NO_PAUSE="
if /I "%~1"=="--nopause" set "NO_PAUSE=1"

call "%~dp0build_plugin.bat" --nopause
if errorlevel 1 (
  echo [AutoCADMindAI] ERROR: package aborted because build failed.
  set "RC=10"
  goto :end
)

set "DIST=dist\AutoCADMindAI"
if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

set "DLL_SRC="
if exist "acad\bin\Release\AutoCADMindAI.Plugin.dll" set "DLL_SRC=acad\bin\Release\AutoCADMindAI.Plugin.dll"
if "%DLL_SRC%"=="" if exist "acad\bin\x64\Release\AutoCADMindAI.Plugin.dll" set "DLL_SRC=acad\bin\x64\Release\AutoCADMindAI.Plugin.dll"
if "%DLL_SRC%"=="" if exist "acad\bin\x64\Release\net8.0-windows\AutoCADMindAI.Plugin.dll" set "DLL_SRC=acad\bin\x64\Release\net8.0-windows\AutoCADMindAI.Plugin.dll"
if "%DLL_SRC%"=="" if exist "acad\bin\Release\net8.0-windows\AutoCADMindAI.Plugin.dll" set "DLL_SRC=acad\bin\Release\net8.0-windows\AutoCADMindAI.Plugin.dll"
if "%DLL_SRC%"=="" (
  echo [AutoCADMindAI] ERROR: compiled DLL not found.
  set "RC=11"
  goto :end
)

copy /y "%DLL_SRC%" "%DIST%\AutoCADMindAI.Plugin.dll" >nul
for %%I in ("%DIST%\AutoCADMindAI.Plugin.dll") do echo [AutoCADMindAI] DLL timestamp: %%~tI

copy /y "main_ai_cad.py" "%DIST%\" >nul
copy /y "start.py" "%DIST%\" >nul
copy /y "start.bat" "%DIST%\" >nul
copy /y "start_debug.bat" "%DIST%\" >nul
copy /y "ipc_bridge.py" "%DIST%\" >nul
copy /y "ai_model.py" "%DIST%\" >nul
copy /y "autocad_controller.py" "%DIST%\" >nul
copy /y "config_manager.py" "%DIST%\" >nul
copy /y "ai_config.json" "%DIST%\" >nul

if exist "ui" xcopy /e /i /y "ui" "%DIST%\ui" >nul

(
  echo AutoCADMindAI package
  echo.
  echo 1) In AutoCAD type NETLOAD
  echo 2) Load AutoCADMindAI.Plugin.dll
  echo 3) Type AIMIND to start/show AI
  echo 4) Type AICHAT to send message
  echo 5) Type AISTOP to stop
) > "%DIST%\USAGE.txt"

echo [AutoCADMindAI] Package success: %cd%\%DIST%
set "RC=0"

:end
if not defined NO_PAUSE pause
exit /b %RC%
