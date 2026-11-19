@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] MudaeCore is not installed yet.
    echo Run install.bat first to create the .venv environment.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0bot.py" (
    echo [ERROR] bot.py was not found in "%~dp0".
    echo Re-extract or re-clone the complete MudaeCore repository.
    echo.
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0bot.py"
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] MudaeCore stopped because of a runtime error.
    echo.
)

pause
exit /b %EXIT_CODE%
