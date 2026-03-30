#!/usr/bin/env bash
# =============================================================================
# launch_supervisor.sh — LSAM Supervisor Launcher (macOS-safe, session-detached)
# =============================================================================
# PURPOSE
#   Launches supervisor.py in a fully detached OS session so it survives
#   Claude Code context compaction, terminal closure, and SIGHUP/SIGKILL sent
#   to the parent process group.
#
# HOW IT WORKS
#   Delegates to scripts/lsam_daemon.py which calls os.setsid() (POSIX syscall,
#   available on macOS) before exec'ing the supervisor. The `setsid` binary is
#   Linux-only and NOT available on macOS — never use it here.
#
# USAGE
#   bash scripts/launch_supervisor.sh           # launch if not running
#   bash scripts/launch_supervisor.sh --force   # kill existing and relaunch
#
# OUTPUT
#   PID written to:  logs/supervisor.pid
#   Logs appended to: logs/supervisor_stdout.log
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/logs/supervisor.pid"
LOG_FILE="$PROJECT_ROOT/logs/supervisor_stdout.log"
DAEMON="$PROJECT_ROOT/scripts/lsam_daemon.py"
FORCE="${1:-}"

cd "$PROJECT_ROOT"

is_alive() { kill -0 "$1" 2>/dev/null; }

# ── Check for existing supervisor ────────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    existing_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$existing_pid" ] && is_alive "$existing_pid"; then
        if [ "$FORCE" = "--force" ]; then
            echo "⚠️  Killing existing supervisor (PID $existing_pid)..."
            kill "$existing_pid" 2>/dev/null || true
            sleep 2
        else
            echo "✅ Supervisor already running (PID $existing_pid). Use --force to restart."
            exit 0
        fi
    fi
fi

# ── Fallback: detect untracked supervisor via ps ─────────────────────────────
untracked_pid=$(pgrep -f "supervisor.py" 2>/dev/null | head -1 || echo "")
if [ -n "$untracked_pid" ]; then
    if [ "$FORCE" = "--force" ]; then
        echo "⚠️  Killing untracked supervisor (PID $untracked_pid)..."
        kill "$untracked_pid" 2>/dev/null || true
        sleep 2
    else
        echo "✅ Untracked supervisor found (PID $untracked_pid). Recording PID."
        echo "$untracked_pid" > "$PID_FILE"
        exit 0
    fi
fi

# ── Launch detached supervisor via daemon wrapper ─────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === SUPERVISOR LAUNCH ===" >> "$LOG_FILE"

python3 "$DAEMON" "$PROJECT_ROOT" >> "$LOG_FILE" 2>&1 &
LAUNCHER_PID=$!

# lsam_daemon.py forks, writes PID file, then exits quickly
sleep 4

if [ -f "$PID_FILE" ]; then
    SUPERVISOR_PID=$(cat "$PID_FILE")
    if is_alive "$SUPERVISOR_PID"; then
        echo "🚀 Supervisor launched. PID=$SUPERVISOR_PID"
        echo "   Log:      $LOG_FILE"
        echo "   PID file: $PID_FILE"
    else
        echo "❌ Supervisor PID $SUPERVISOR_PID not alive. Check $LOG_FILE"
        exit 1
    fi
else
    echo "❌ PID file not created. Check $LOG_FILE"
    exit 1
fi
