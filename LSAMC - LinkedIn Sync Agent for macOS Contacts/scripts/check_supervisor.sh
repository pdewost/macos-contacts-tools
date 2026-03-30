#!/usr/bin/env bash
# =============================================================================
# check_supervisor.sh — LSAM Supervisor Health Check & Auto-Restart
# =============================================================================
# USAGE
#   bash scripts/check_supervisor.sh           # check status, restart if dead
#   bash scripts/check_supervisor.sh --status  # check status only, no restart
#
# EXIT CODES
#   0  — supervisor is running
#   1  — supervisor was dead; restart attempted
#   2  — supervisor not started; no restart attempted (--status mode)
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/logs/supervisor.pid"
LOG_FILE="$PROJECT_ROOT/logs/supervisor_stdout.log"
LAUNCHER="$PROJECT_ROOT/scripts/launch_supervisor.sh"
MODE="${1:-}"

is_alive() { kill -0 "$1" 2>/dev/null; }

# ── Read PID file ─────────────────────────────────────────────────────────────
pid_from_file=""
if [ -f "$PID_FILE" ]; then
    pid_from_file=$(cat "$PID_FILE" 2>/dev/null || echo "")
fi

# ── Check PID file liveness ───────────────────────────────────────────────────
if [ -n "$pid_from_file" ] && is_alive "$pid_from_file"; then
    # Cross-check: verify this PID is actually our supervisor (not a recycled PID)
    if ps -p "$pid_from_file" -o args= 2>/dev/null | grep -q "supervisor.py"; then
        echo "✅ RUNNING (PID=$pid_from_file, verified via ps)"
        exit 0
    else
        echo "⚠️  PID $pid_from_file alive but not supervisor.py (PID recycled?)"
    fi
fi

# ── Fallback: detect untracked supervisor via ps ─────────────────────────────
untracked_pid=$(pgrep -f "supervisor.py" 2>/dev/null | head -1 || echo "")
if [ -n "$untracked_pid" ]; then
    echo "✅ RUNNING_UNTRACKED (PID=$untracked_pid, detected via ps — updating PID file)"
    echo "$untracked_pid" > "$PID_FILE"
    exit 0
fi

# ── Supervisor is dead ────────────────────────────────────────────────────────
# Check when it last wrote to its log
last_log_time=""
if [ -f "$LOG_FILE" ]; then
    last_log_time=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$LOG_FILE" 2>/dev/null || echo "unknown")
fi

echo "💀 DEAD (last log activity: ${last_log_time:-unknown})"

if [ "$MODE" = "--status" ]; then
    echo "   (--status mode: no restart)"
    exit 2
fi

# ── Auto-restart ──────────────────────────────────────────────────────────────
echo "🔄 Restarting supervisor..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] check_supervisor.sh: supervisor was dead — auto-restarting" >> "$LOG_FILE"

bash "$LAUNCHER"
exit 1
