@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "PYTHONPATH=%CD%"
set "YOLO_CONFIG_DIR=%CD%\.ultralytics"

if not exist "%PYTHON%" (
    echo Creating project-local Python environment in .venv ...
    python -m venv "%~dp0.venv"
    if errorlevel 1 goto failed
)

"%PYTHON%" -c "import importlib.util,sys; modules=('django','fastapi','gradio','httpx','numpy','cv2','PIL','psycopg','tensorflow','ultralytics','uvicorn','ipykernel','jupyterlab','nbformat','yaml'); sys.exit(any(importlib.util.find_spec(name) is None for name in modules))"
if errorlevel 1 (
    echo Installing missing project dependencies into WS\.venv ...
    "%PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 goto failed
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)

echo ==========================================
echo ParkVision - local development launcher
echo ==========================================
echo Local Python: %PYTHON%
echo Web:    http://127.0.0.1:8000
echo AI API: http://127.0.0.1:8001/health
echo.

"%PYTHON%" manage.py check
if errorlevel 1 goto failed

"%PYTHON%" manage.py migrate
if errorlevel 1 goto failed

start "ParkVision AI API" cmd /k ""%PYTHON%" -m uvicorn ai_api:app --host 127.0.0.1 --port 8001"
timeout /t 2 /nobreak >nul
start "ParkVision Django" cmd /k ""%PYTHON%" manage.py runserver 127.0.0.1:8000"
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8000"
echo Both services were started. Keep their terminal windows open.
exit /b 0

:failed
echo.
echo Startup failed. Review the error above and confirm dependencies are installed.
pause
exit /b 1
