@echo off
setlocal
cd /d "%~dp0"

set "NO_PAUSE="
if /I "%~1"=="--nopause" set "NO_PAUSE=1"

set "PROJECT=acad\AutoCADMindAI.Plugin.csproj"
if not exist "%PROJECT%" (
  echo [AutoCADMindAI] ERROR: project not found: %PROJECT%
  set "RC=1"
  goto :end
)

set "MSBUILD_EXE="

where msbuild >nul 2>nul
if %errorlevel%==0 (
  for /f "delims=" %%i in ('where msbuild') do (
    set "MSBUILD_EXE=%%i"
    goto :found_msbuild
  )
)

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
  for /f "delims=" %%i in ('"%VSWHERE%" -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe') do (
    set "MSBUILD_EXE=%%i"
    goto :found_msbuild
  )
)

:found_msbuild
if "%MSBUILD_EXE%"=="" (
  echo [AutoCADMindAI] ERROR: MSBuild not found.
  echo Install Build Tools for Visual Studio with:
  echo - MSBuild
  echo - .NET Framework 4.8 targeting pack
  set "RC=2"
  goto :end
)

echo [AutoCADMindAI] Using MSBuild: %MSBUILD_EXE%

echo [AutoCADMindAI] Restoring NuGet assets...
"%MSBUILD_EXE%" "%PROJECT%" /t:Restore
if errorlevel 1 (
  echo [AutoCADMindAI] WARNING: restore via MSBuild failed, trying dotnet restore...
  dotnet restore "%PROJECT%"
  if errorlevel 1 (
    echo [AutoCADMindAI] ERROR: restore failed.
    set "RC=3"
    goto :end
  )
)

echo [AutoCADMindAI] Rebuilding plugin...
"%MSBUILD_EXE%" "%PROJECT%" /t:Rebuild /p:Configuration=Release /p:Platform=x64
if errorlevel 1 (
  echo [AutoCADMindAI] ERROR: build failed.
  set "RC=4"
  goto :end
)

echo [AutoCADMindAI] Build success.
if exist "acad\bin\Release\AutoCADMindAI.Plugin.dll" (
  echo [AutoCADMindAI] DLL: %cd%\acad\bin\Release\AutoCADMindAI.Plugin.dll
) else if exist "acad\bin\x64\Release\AutoCADMindAI.Plugin.dll" (
  echo [AutoCADMindAI] DLL: %cd%\acad\bin\x64\Release\AutoCADMindAI.Plugin.dll
) else if exist "acad\bin\x64\Release\net8.0-windows\AutoCADMindAI.Plugin.dll" (
  echo [AutoCADMindAI] DLL: %cd%\acad\bin\x64\Release\net8.0-windows\AutoCADMindAI.Plugin.dll
) else if exist "acad\bin\Release\net8.0-windows\AutoCADMindAI.Plugin.dll" (
  echo [AutoCADMindAI] DLL: %cd%\acad\bin\Release\net8.0-windows\AutoCADMindAI.Plugin.dll
) else (
  echo [AutoCADMindAI] WARNING: DLL not found in common output paths.
)
set "RC=0"

:end
if not defined NO_PAUSE pause
exit /b %RC%
