@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo              MUDAECORE
echo            Windows Installer
echo ========================================
echo.

echo [1/4] Checking Python...
set "PYTHON_CMD="

where py >nul 2>nul
if not errorlevel 1 (
    py -3.14 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.14"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] Stage 1 - Python 3.14 was not found in PATH or by the py launcher.
    echo Install a compatible Python 3.14 release, then run this installer again.
    echo.
    pause
    exit /b 1
)

echo Python 3.14 found.

if not exist "%~dp0requirements.txt" (
    echo [ERROR] Stage 1 - requirements.txt was not found in "%~dp0".
    echo.
    pause
    exit /b 1
)

echo.
echo [2/4] Preparing environment...
if not exist "%~dp0.venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo [ERROR] Stage 2 - Could not create the local .venv environment.
        echo.
        pause
        exit /b 1
    )
) else (
    echo Existing .venv environment found.
)

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Stage 2 - The virtual environment Python executable is missing.
    echo.
    pause
    exit /b 1
)

echo.
echo [3/4] Installing dependencies...
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] Stage 3 - Dependency installation failed.
    echo Review the pip output above and run install.bat again.
    echo.
    pause
    exit /b 1
)

echo.
echo [4/4] Verifying installation...
"%~dp0.venv\Scripts\python.exe" -c "import discord, inquirer"
if errorlevel 1 (
    echo [ERROR] Stage 4 - The installed dependencies could not be imported.
    echo.
    pause
    exit /b 1
)

echo.
echo Installation completed successfully.
echo.
pause
exit /b 0
