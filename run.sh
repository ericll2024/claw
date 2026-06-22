#!/bin/bash
cd "$(dirname "$0")"

echo "=== claw Startup Helper ==="

# 1. Kill any process occupying Python backend port (8765)
BACKEND_PORT=8765
PID_BACKEND=$(lsof -t -i :$BACKEND_PORT)
if [ ! -z "$PID_BACKEND" ]; then
    echo "Port $BACKEND_PORT is occupied by PID(s): $PID_BACKEND. Killing old process..."
    kill -9 $PID_BACKEND 2>/dev/null
    sleep 1 # Wait for port release
fi

# 2. Check and handle Vue frontend if it exists
if [ -f "web/package.json" ]; then
    echo "Vue project detected in web."
    # Kill common Vue/Vite development server ports
    for PORT in 5173 8080; do
        PID_FRONT=$(lsof -t -i :$PORT)
        if [ ! -z "$PID_FRONT" ]; then
            echo "Port $PORT (Vue) is occupied by PID(s): $PID_FRONT. Killing..."
            kill -9 $PID_FRONT 2>/dev/null
        fi
    done
    
    echo "Starting Vue Frontend in background..."
    cd web
    # Install dependencies and start in background
    # Redirect logs to a log file
    npm install
    npm run dev > ../vue_dev.log 2>&1 &
    cd ..
fi

# 3. Start Python Backend
echo "Starting Python Backend on port $BACKEND_PORT..."
python3 run.py serve
