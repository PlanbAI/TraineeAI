@echo off
setlocal
set "ROOT_DIR=%~dp0.."
set "PYTHON_BIN=%ROOT_DIR%\.venv\Scripts\pythonw.exe"

if not exist "%PYTHON_BIN%" (
    where pythonw.exe >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_BIN=pythonw.exe"
    ) else (
        where python.exe >nul 2>nul
        if errorlevel 1 (
            echo ERROR: Python 3 was not found. Create .venv or add Python to PATH.
            exit /b 1
        )
        set "PYTHON_BIN=python.exe"
    )
)

"%PYTHON_BIN%" "%ROOT_DIR%\scripts\run_windows_collectors.py" --background %*
if errorlevel 1 (
    echo ERROR: Unable to start collectors.
    exit /b 1
)

echo TraineeAI collectors are starting in the background.
echo Logs: %ROOT_DIR%\windows-collectors.log
echo Stop: %ROOT_DIR%\scripts\stop_windows_collectors.cmd
