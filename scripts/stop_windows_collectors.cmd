@echo off
setlocal
set "ROOT_DIR=%~dp0.."
set "PYTHON_BIN=%ROOT_DIR%\.venv\Scripts\python.exe"

if not exist "%PYTHON_BIN%" (
    where python.exe >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3 was not found. Create .venv or add Python to PATH.
        exit /b 1
    )
    set "PYTHON_BIN=python.exe"
)

"%PYTHON_BIN%" "%ROOT_DIR%\scripts\run_windows_collectors.py" --stop
