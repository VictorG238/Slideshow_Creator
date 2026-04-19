@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if /I "%~1"=="--help" goto :help

set "APP_MODULE=slideshow_creator"
set "SRC_PATH=%CD%\src"
set "PYTHON_CMD="
set "PYTHON_ARGS="

if defined SLIDESHOW_PYTHON if exist "%SLIDESHOW_PYTHON%" set "PYTHON_CMD=%SLIDESHOW_PYTHON%"
if not defined PYTHON_CMD if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"
if not defined PYTHON_CMD if exist "venv\Scripts\python.exe" set "PYTHON_CMD=venv\Scripts\python.exe"
if not defined PYTHON_CMD if exist "C:\Users\Victor\AppData\Local\Python\bin\python.exe" set "PYTHON_CMD=C:\Users\Victor\AppData\Local\Python\bin\python.exe"

if not defined PYTHON_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.14 -c "import sys" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD=py"
            set "PYTHON_ARGS=-3.14"
        )
    )
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found.
    echo [INFO] Install Python 3.14 or set SLIDESHOW_PYTHON with the executable path.
    exit /b 1
)

call "%PYTHON_CMD%" %PYTHON_ARGS% -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This project requires Python 3.14 or higher.
    call "%PYTHON_CMD%" %PYTHON_ARGS% -c "import sys; print('[INFO] Detected version:', sys.version)"
    exit /b 1
)

if /I "%~1"=="--doctor" (
    call :doctor
    exit /b %errorlevel%
)

set "PYTHONPATH=%SRC_PATH%;%PYTHONPATH%"

call :ensure_deps
if errorlevel 1 exit /b %errorlevel%

call :ensure_ffmpeg
if errorlevel 1 exit /b %errorlevel%

echo [INFO] Starting application...
call "%PYTHON_CMD%" %PYTHON_ARGS% -m %APP_MODULE%
exit /b %errorlevel%

:ensure_deps
call "%PYTHON_CMD%" %PYTHON_ARGS% -c "import PySide6, requests, PIL" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Core dependencies detected.
    exit /b 0
)

echo [INFO] Installing dependencies with pip...
call "%PYTHON_CMD%" %PYTHON_ARGS% -m pip install -e ".[dev]"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo [INFO] Run manually: python -m pip install -e .[dev]
    exit /b 1
)
exit /b 0

:doctor
set "PYTHONPATH=%SRC_PATH%;%PYTHONPATH%"
echo [INFO] Checking environment...
call "%PYTHON_CMD%" %PYTHON_ARGS% -c "import sys; print('[OK] Python:', sys.version)"
if errorlevel 1 exit /b 1

call "%PYTHON_CMD%" %PYTHON_ARGS% -c "import PySide6, requests, PIL; print('[OK] Core dependencies: ready')" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Missing dependencies. Run run_app.bat to auto-install them.
    exit /b 1
)

echo [OK] Environment ready to run the app.
exit /b 0

:ensure_ffmpeg
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo [OK] FFmpeg detected in system PATH.
    exit /b 0
)

if exist "assets\ffmpeg\ffmpeg.exe" (
    echo [OK] FFmpeg found in assets\ffmpeg.
    set "SLIDESHOW_FFMPEG_PATH=%CD%\assets\ffmpeg\ffmpeg.exe"
    exit /b 0
)

echo [INFO] FFmpeg not found. Downloading FFmpeg...
set "FFMPEG_ZIP=%TEMP%\ffmpeg.zip"
set "FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

if not exist "assets\ffmpeg" mkdir "assets\ffmpeg"

powershell -Command "try { Invoke-WebRequest -Uri '%FFMPEG_URL%' -OutFile '%FFMPEG_ZIP%' -ErrorAction Stop; Write-Host '[OK] Downloaded FFmpeg'; exit 0 } catch { Write-Host '[ERROR] Failed to download FFmpeg'; exit 1 }"
if errorlevel 1 (
    echo [ERROR] Could not download FFmpeg from %FFMPEG_URL%
    echo [INFO] Please install FFmpeg manually: https://ffmpeg.org/download.html
    echo [INFO] Or set SLIDESHOW_FFMPEG_PATH environment variable.
    exit /b 1
)

echo [INFO] Extracting FFmpeg...
powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%FFMPEG_ZIP%', '%TEMP%'); Move-Item '%TEMP%\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe' -Destination 'assets\ffmpeg\ffmpeg.exe' -Force; Move-Item '%TEMP%\ffmpeg-master-latest-win64-gpl\bin\ffprobe.exe' -Destination 'assets\ffmpeg\ffprobe.exe' -Force -ErrorAction SilentlyContinue; Remove-Item '%FFMPEG_ZIP%'; Remove-Item '%TEMP%\ffmpeg-master-latest-win64-gpl' -Recurse -Force -ErrorAction SilentlyContinue"
if errorlevel 1 (
    echo [ERROR] Failed to extract FFmpeg.
    exit /b 1
)

set "SLIDESHOW_FFMPEG_PATH=%CD%\assets\ffmpeg\ffmpeg.exe"
echo [OK] FFmpeg installed to assets\ffmpeg.
exit /b 0

:help
echo Usage:
echo   run_app.bat             Run the app
echo   run_app.bat --doctor    Check version and dependencies
echo   run_app.bat --help      Show this help
echo.
echo Optional:
echo   set SLIDESHOW_PYTHON=C:\path\to\python.exe
echo   run_app.bat
exit /b 0
