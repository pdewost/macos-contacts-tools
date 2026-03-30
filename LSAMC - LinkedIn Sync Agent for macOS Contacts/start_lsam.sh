#!/bin/bash

# LSAMC Startup Script
# Ensures environment consistency and prevents "Silent Death" due to missing deps.

echo "🚀 LSAMC Launcher v1.0"
echo "========================"

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 could not be found."
    exit 1
fi

# 2. Check/Create venv
if [ ! -d "venv" ]; then
    echo "🔨 Creating virtual environment..."
    python3 -m venv venv
else
    echo "✅ Virtual environment found."
fi

# 3. Activate venv
source venv/bin/activate

# 4. Install Dependencies
echo "📦 Checking dependencies..."
pip install --upgrade pip > /dev/null
pip install -r requirements.txt > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ Dependencies satisfied."
else
    echo "❌ Failed to install dependencies."
    exit 1
fi

# 5. Launch Supervisor
echo "🛡️  Launching Supervisor..."

if [[ "$1" == "--pro" || "$2" == "--pro" ]]; then
    echo "🧠 PRO MODE ACTIVATED: Routing to Gemini 2.0 Pro Engine"
    export LSAMC_ENGINE="PRO"
fi

LIVE_FLAG=""
if [[ "$1" == "--full" || "$2" == "--full" ]]; then
    echo "⚡ LIVE MODE ACTIVATED: Changes will be saved to Apple Contacts."
    LIVE_FLAG="--live"
fi

nohup python3 supervisor.py $LIVE_FLAG > logs/supervisor_stdout.log 2> logs/supervisor_stderr.log &
SUPERVISOR_PID=$!
echo "✅ Supervisor started with PID $SUPERVISOR_PID"

# 6. Monitor startup
echo "👀 Monitoring startup logs (5s)..."
sleep 5
tail -n 10 logs/supervisor_stdout.log
echo ""
echo "✨ System is running. Monitor with: tail -f logs/supervisor_stdout.log"
