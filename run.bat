@echo off
cd /d %~dp0
echo ====================================
echo Starting claw...
echo ====================================

:: 1. Clean up Python backend port (8765)
echo Checking port 8765...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr LISTENING ^| findstr :8765') do (
    echo Port 8765 is occupied by PID %%a. Killing...
    taskkill /F /PID %%a >nul 2>&1
)

:: 2. Clean up Vue ports if Vue project exists
if exist "web\package.json" (
    echo Vue project detected in web.
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr LISTENING ^| findstr :5173') do (
        echo Port 5173 is occupied by PID %%a. Killing...
        taskkill /F /PID %%a >nul 2>&1
    )
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr LISTENING ^| findstr :8080') do (
        echo Port 8080 is occupied by PID %%a. Killing...
        taskkill /F /PID %%a >nul 2>&1
    )
    
    echo Starting Vue Frontend in background...
    cd web
    :: Install dependencies and start in background
    call npm install
    start /b npm run dev
    cd ..
)

:: 3. Start Python Backend
echo Starting Python Backend...
where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo Error: Python is not installed or not added to your PATH environment variable.
        echo Please install Python 3.9+ and try again.
        pause
        exit /b 1
    ) else (
        py run.py serve --host 0.0.0.0
    )
) else (
    python run.py serve --host 0.0.0.0
)
