#!/usr/bin/env python3
"""
🛡️ LSAMC Supervisor
===================
"Let it crash."

This script manages the lifecycle of the LinkedIn Sync Agent.
It is responsible for:
1. Calculating the "Smart Resume" offset from today's logs.
2. Launching the agent in a subprocess.
3. Monitoring the process.
4. Restarting it cleanly if it crashes (Exit Code != 0).
5. Stopping if it fails too many times (Circuit Breaker).

⚠️ OPERATIONAL SAFETY:
- RUN ONLY ONE SUPERVISOR AT A TIME.
- DO NOT USE LSAMC_IGNORE_LOCK=1 unless for isolated debugging.
- Reference: docs/OPERATIONAL_SAFETY.md
"""

import subprocess
import time
import os
import sys
import logging
import glob
import re
from datetime import datetime
from pathlib import Path
import signal
import requests
import json
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/supervisor.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- CONFIG ---
BaselineAgent = "src/agent/sync_agent.py"
FastAgent = "src/agent/fast_sync_agent.py"

# Gemini 2.0 Pro Routing
if os.environ.get("LSAMC_ENGINE") == "PRO":
    print("🧠 PRO MODE DETECTED: Routing entirely to Gemini 2.0 Pro ('pro_sync_agent.py')")
    BaselineAgent = "src/agent/pro_sync_agent.py"
    FastAgent = "src/agent/pro_sync_agent.py"

# v3.0 Group Queue
# v5.0: Simplified group taxonomy (PLAN_2026-03-29 Part 5)
# Legacy names kept as fallback until migration is confirmed complete.
GroupQueue = [
    "LSAM-Birthday",                      # Phase 0: Birthday T-2 (auto-populated, auto-drained)
    "LSAM-Queue",                         # Phase 1: Main processing queue (promoted, refresh, unprocessed)
    "LSAM-Review",                        # Phase 2: Manual triage needed (skipped in auto mode)
    # Legacy fallbacks (remove after migration verified):
    "script-LSAM-Priority",
    "script-LSAM-Force-Refresh",
    "script-LSAM-Tier3-NeedAttention",
    "script-LSAM-LinkedIn to Review",
]
STATE_FILE = "logs/.supervisor_state"

MaxConsecutiveCrashes = 20
MaxFastFailures = 3      # v4.9.1 B1: 1→3 (AUDIT_2026-03-11) — allow 2 transient failures before downshift
CrashResetTime = 600     # If running for > 10 mins, reset crash counter
RestartDelay = 60        # Seconds to wait before restarting
# v3.5.9: Watchdog - Dashboard Monitor Configuration
MONITOR_SCRIPT = "monitor_overnight.py"
MONITOR_OUTPUT = "SYNC_PROGRESS.md"
MONITOR_STALL_TIMEOUT = 900  # 15 minutes of silence in SYNC_PROGRESS.md
# --------------

def _collect_session_summary() -> str:
    """v5.0 Sprint 6: Parse today's session logs to collect per-contact outcomes.
    Returns a compact summary string for MBP Dev Monitor calendar event notes."""
    import re
    today = datetime.now().strftime("%Y-%m-%d")
    pattern = f"logs/sessions/run_{today}_*"
    log_dirs = sorted(glob.glob(pattern))

    synced = []
    failed = []
    total = 0

    for log_dir in log_dirs:
        log_file = os.path.join(log_dir, "session.log")
        if not os.path.exists(log_file):
            continue
        try:
            with open(log_file, "r") as f:
                for line in f:
                    if "update_contact SUCCESS" in line or "VAULT WRITTEN" in line:
                        # Extract contact name from log context
                        m = re.search(r"Syncing: (?:M |Mme |Mr )?(.+?)(?:\s*\(LSAMC|\s*$)", line)
                        if not m:
                            m = re.search(r"VAULT WRITTEN: .*/([^/]+?)(?::ABPerson)?/?$", line)
                        name = m.group(1).strip() if m else "?"
                        if name not in [s for s in synced]:
                            synced.append(name)
                        total += 1
                    elif "FAILED" in line and "Syncing:" in line:
                        m = re.search(r"Syncing: (?:M |Mme |Mr )?(.+?)(?:\s*\(LSAMC|\s*$)", line)
                        name = m.group(1).strip() if m else "?"
                        if name not in failed:
                            failed.append(name)
        except Exception:
            continue

    lines = []
    lines.append(f"Contacts: {len(synced)} synced, {len(failed)} failed")
    if synced:
        preview = synced[:10]
        lines.append(f"Synced: {', '.join(preview)}" + (f" (+{len(synced)-10} more)" if len(synced) > 10 else ""))
    if failed:
        lines.append(f"Failed: {', '.join(failed[:5])}")

    # Queue remaining counts
    try:
        for gname in ["LSAM-Queue", "LSAM-Review"]:
            names = get_group_names_sorted(gname)
            lines.append(f"{gname}: {len(names)} remaining")
    except Exception:
        pass

    # Session log path
    if log_dirs:
        lines.append(f"Log: {log_dirs[-1]}/session.log")

    summary = "\n".join(lines)
    # Calendar event notes have a ~4000 char limit
    return summary[:3900]


def get_today_logs_pattern():
    today = datetime.now().strftime("%Y-%m-%d")
    return f"logs/sessions/run_{today}_*"

def count_historical_archived():
    """Counts contacts in logs/archive/applied/run_OLD_DATE_*."""
    archive_root = "logs/archive/applied"
    if not os.path.exists(archive_root): return 0
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    
    # Iterate session folders in archive
    # Structure: logs/archive/applied/run_YYYY-MM-DD_.../ContactName
    for session_name in os.listdir(archive_root):
        session_path = os.path.join(archive_root, session_name)
        if not os.path.isdir(session_path): continue
        
        # Skip if it involves TODAY (covered by live log scanning)
        if f"run_{today_str}" in session_name:
            continue
            
        # Count subdirectories (contacts)
        contacts = [c for c in os.listdir(session_path) if os.path.isdir(os.path.join(session_path, c))]
        count += len(contacts)
        
    return count

def get_group_names_sorted(group_name):
    """Fetches and sorts names from a macOS Contacts group (A-Z)."""
    try:
        # v4.8.3: Robust query to handle "missing value" and UI artifacts
        script = f'''
        use framework "Foundation"
        use framework "Contacts"
        use scripting additions
        
        tell application "Contacts"
            if not (exists group "{group_name}") then return ""
            set rawNames to name of people of group "{group_name}"
            set cleanNames to {{}}
            repeat with n in rawNames
                if n is not missing value and n is not "missing value" and n is not "null" then
                    copy n as text to end of cleanNames
                end if
            end repeat
            return cleanNames
        end tell
        '''
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode != 0: return []
        
        # v4.8.3: Handle empty result or comma-joined output correctly
        raw_output = res.stdout.strip()
        if not raw_output:
            return []
            
        # osascript returns list as "item1, item2, ..."
        names = [n.strip() for n in raw_output.split(',')]
        # Final safety filter
        names = [n for n in names if n and n.lower() not in ["missing value", "null", "none"]]
        names.sort()
        return names
    except Exception as e:
        print(f"⚠️ Error fetching group names: {e}")
        return []

def discover_available_groups():
    """
    v4.9.6: Uses standard AppleScript to list all groups.
    Robustness: Filters out "missing value" and empty strings.
    """
    try:
        script = 'tell application "Contacts" to get name of every group'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode != 0: 
            print(f"⚠️ AppleScript Error in discovery (Code {res.returncode}): {res.stderr}")
            return []
        
        raw_output = res.stdout.strip()
        if not raw_output: return []
        
        groups = [g.strip() for g in raw_output.split(',')]
        # Filter out obvious trash
        groups = [g for g in groups if g and g.lower() not in ["missing value", "null", "none"]]
        return groups
    except Exception as e:
        print(f"⚠️ Error discovering groups: {e}")
        return []

def calculate_smart_offset():
    """
    v1.6.5: Offset calculation moved into Agent (Smart Filtering).
    Supervisor now always starts from index 0, and the Agent skips what is already done.
    """
    return 0
    """
    v1.6.5: Offset calculation moved into Agent (Smart Filtering).
    Supervisor now always starts from index 0, and the Agent skips what is already done.
    """
    return 0

def check_internet_connection(url="http://www.google.com", timeout=5):
    """Checks if internet is available."""
    try:
        requests.get(url, timeout=timeout)
        return True
    except requests.ConnectionError:
        return False
    except Exception:
        return False

def wait_for_network():
    """Blocks execution until network is available."""
    if check_internet_connection():
        return

    print("⚠️  Network Offline. Pausing engine...")
    while not check_internet_connection():
        time.sleep(30)
    print("✅ Network Restored. Resuming...")

def kill_orphans():
    """Aggressive cleanup of lingering Chrome/Python processes."""
    print("🧹 Supervisor: Cleaning up orphan processes...")
    try:
        # Kill Chrome (Headful or Headless types)
        subprocess.run(["pkill", "-9", "Google Chrome"], capture_output=True)
        subprocess.run(["pkill", "-9", "Chrome Helper"], capture_output=True)
        # Kill any OTHER sync_agent instances (but not self)
        subprocess.run(["pkill", "-f", "src/agent/sync_agent.py"], capture_output=True)
    except Exception as e:
        print(f"⚠️ Cleanup warning: {e}")

def ensure_monitor_running():
    """v3.5.9: Ensure the dashboard monitor script is active.
    v4.9.2 FIX (2026-03-15): psutil.process_iter() raises OSError (errno=0, KERN_PROCARGS2)
    for macOS kernel/zombie processes whose cmdline is inaccessible. The inner
    try/except only caught NoSuchProcess+AccessDenied — the OSError propagated up and
    crashed the supervisor. Fix: (1) add OSError to inner except; (2) wrap entire
    scan loop in outer try/except so any remaining iterator-level errors are non-fatal.
    """
    # Check if monitor is already running
    monitor_pids = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                if cmdline and MONITOR_SCRIPT in " ".join(cmdline) and "python" in " ".join(cmdline).lower():
                    monitor_pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
    except (OSError, Exception) as _scan_err:
        # Iterator-level failure (e.g. sysctl KERN_PROCARGS2 on a kernel thread).
        # Non-fatal: proceed with whatever monitor_pids were collected before the error.
        print(f"⚠️ ensure_monitor_running: psutil scan interrupted ({_scan_err}) — proceeding with partial results")

    if not monitor_pids:
        print(f"📡 Supervisor: Starting Dashboard Monitor ({MONITOR_SCRIPT})...")
        try:
            # Use nohup to ensure it survives supervisor restarts
            log_path = "logs/monitor_overnight.log"
            subprocess.Popen(
                f"nohup {sys.executable} {MONITOR_SCRIPT} > {log_path} 2>&1 &",
                shell=True,
                preexec_fn=os.setpgrp
            )
        except Exception as e:
            print(f"⚠️ Failed to start monitor: {e}")
    else:
        if len(monitor_pids) > 1:
            print(f"⚠️ Multiple monitor instances found ({monitor_pids}). Cleaning up...")
            for pid in monitor_pids[1:]:
                try: os.kill(pid, signal.SIGKILL)
                except: pass

def check_monitor_health():
    """v3.5.9: Watchdog rule for SYNC_PROGRESS.md."""
    if not os.path.exists(MONITOR_OUTPUT):
        ensure_monitor_running()
        return

    mtime = os.path.getmtime(MONITOR_OUTPUT)
    idle_time = time.time() - mtime
    
    if idle_time > MONITOR_STALL_TIMEOUT:
        print(f"⚠️ Supervisor: Dashboard STALL detected ({idle_time:.0f}s since last update). Restarting monitor...")
        # Kill all monitor instances
        subprocess.run(["pkill", "-f", MONITOR_SCRIPT], capture_output=True)
        time.sleep(1)
        ensure_monitor_running()
    else:
        # even if not stalled, ensure the process exists
        ensure_monitor_running()

def run_agent(consecutive_crashes, active_agent, target_group, mode="SIMULATION", force=False, limit=None):
    """Launches the agent and waits for it to finish."""
    
    # 1. Smart Resume
    offset = calculate_smart_offset()
    print(f"\n🚀 SUPERVISOR: Launching {active_agent} at offset {offset}")
    if force:
        print("🔥 FORCE MODE ACTIVATED (Bypassing history check)")
    print(f"   (Consecutive Crashes: {consecutive_crashes}/{MaxConsecutiveCrashes})")
    
    cmd = [
        sys.executable, active_agent,
        "--group", target_group,
        "--mode", mode,
        "--offset", str(offset),
        "--limit", "350",
    ]
    if force:
        cmd.append("--force")
    
    # v1.7.8: fast_sync_agent.py needs specific args for single-contact pilot, 
    # but for full batch it uses group-based logic if implemented.
    # For now, we assume both support --group and --mode.

    # Build command
    # v4.8: Pass appropriate offset and limit args
    # Offset is 0 (Agent handles Smart Resume), limit is determined from group state
    # limit is the *batch* size for one run, not a global limit.
    batch_quota = 50 # Default safe batch limit
    if target_group in ["script-LSAM-LinkedIn to Review"]:
        batch_quota = 20 # Review groups are slow
    
    # v5.3 If manually specified group, increase limit to 500 for massive run
    if target_group not in GroupQueue:
        batch_quota = 500
        
    # v5.5 Override with supervisor-level limit if provided
    if limit:
        batch_quota = limit

    cmd = [sys.executable, active_agent, "--group", target_group, "--mode", mode, "--limit", str(batch_quota)]
    if force: cmd.append("--force")
    
    # v1.7.0 Surgical Option (Overnight Reliability)
    # If we crashed multiple times, add surgical flag to lower risks
    if consecutive_crashes > 1:
        cmd.append("--surgical")

    start_time = time.time()
    
    print(f"DEBUG: Executing command: {' '.join(cmd)}")
    try:
        env = os.environ.copy()
        if "PYTHONPATH" not in env:
            env["PYTHONPATH"] = "."
        env["LINKEDIN_DAILY_QUOTA"] = "2000"
        
        # Inject SSL certificates to fix extension download failures on macOS
        try:
            import certifi
            env["SSL_CERT_FILE"] = certifi.where()
            env["REQUESTS_CA_BUNDLE"] = certifi.where()
        except ImportError:
            pass
        
        process = subprocess.Popen(cmd, env=env, start_new_session=True)
        
        # v2.1: Heartbeat Monitor (Stall Detection)
        # v4.9.1 C1: Slow Horse + Gemini Vision needs more time (AUDIT_2026-03-11)
        # BaselineAgent can be sync_agent.py or pro_sync_agent.py (PRO mode) — both are Gemini-heavy
        StallTimeout = 1200 if active_agent == BaselineAgent else 900  # 1200s=Slow Horse, 900s=Fast
        last_activity = time.time()
        
        while process.poll() is None:
            # Check latest log modification
            try:
                # Find newest session folder
                sessions = sorted(glob.glob("logs/sessions/run_*"))
                if sessions:
                    latest_session = sessions[-1]
                    log_path = os.path.join(latest_session, "session.log")
                    if os.path.exists(log_path):
                        mtime = os.path.getmtime(log_path)
                        # Only update if recent (belongs to this process, vaguely)
                        if mtime > last_activity:
                            last_activity = mtime
            except Exception: pass
            
            idle_time = time.time() - last_activity
            if idle_time > StallTimeout:
                print(f"💀 Supervisor: DETECTED STALL (No log activity for {idle_time:.0f}s). KILLING process {process.pid}.")
                process.kill()
                try: process.wait(timeout=5)
                except: subprocess.run(["kill", "-9", str(process.pid)])
                return "CRASH" # Trigger restart logic
            
            # v3.5.9: Check Monitor Watchdog
            check_monitor_health()
            
            time.sleep(5)

        exit_code = process.returncode
    except KeyboardInterrupt:
        print("\n👋 Supervisor: User interrupted.")
        if process: 
            process.terminate()
        return "STOP"

    duration = time.time() - start_time
    
    if exit_code == 0:
        return "SUCCESS"
    elif exit_code == 42:
        # v4.8.3: Batch Recycle — agent processed its batch limit and exited cleanly
        print(f"♻️ Batch recycle signal (exit 42). Agent processed its batch and needs a fresh restart.")
        return "BATCH_COMPLETE"
    elif exit_code == 99:
        # v4.9.2 CAPTCHA-KILL: LinkedIn checkpoint/CAPTCHA detected — do not restart
        print(f"🛑 CAPTCHA-KILL signal (exit 99). LinkedIn security challenge detected. Supervisor stopping.")
        print(f"   Sentinel: logs/CAPTCHA_KILL — remove it and restart when session is safe.")
        return "CAPTCHA"
    else:
        print(f"❌ {active_agent} crashed with Exit Code {exit_code} (Duration: {duration:.1f}s)")
        if duration > CrashResetTime:
            return "CRASH_RESET"
        else:
            return "CRASH"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"current_group": None}

def save_state(group_name):
    with open(STATE_FILE, 'w') as f:
        json.dump({"current_group": group_name}, f)

def update_supervisor_status(group_name, group_idx=-1, total_contacts=0, status="Running"):
    """Writes real-time status to a hidden file for Staged Manager to read."""
    status_file = "logs/.supervisor_status"
    data = {
        "group": group_name,
        "index": group_idx,
        "total": total_contacts,
        "status": status,
        "mode": "Live" if status == "Running" else "Idle",
        "start_time": time.strftime("%H:%M:%S"),
        "timestamp": time.time()
    }
    try:
        with open(status_file, 'w') as f:
            json.dump(data, f)
    except: pass

def clear_supervisor_status():
    status_file = "logs/.supervisor_status"
    if os.path.exists(status_file):
        try: os.remove(status_file)
        except: pass

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LSAMC Supervisor")
    parser.add_argument("--live", action="store_true", help="Run agents in FULL mode instead of SIMULATION")
    parser.add_argument("--group", type=str, help="Target a specific single group and exit")
    parser.add_argument("--limit", type=int, default=100, help="Total work for this run")
    args = parser.parse_args()
    
    mode = "FULL" if args.live else "SIMULATION"
    print(f"🛡️ LSAMC Supervisor v3.5: The Architect (Mode: {mode})")

    # v1.0 CALENDAR-BRIDGE: load calendar_bridge from workspace _skills (graceful degradation)
    _workspace_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(_workspace_root))
    try:
        from _skills.calendar_bridge.scripts.bridge import (
            create_event as _cal_create,
            update_progress as _cal_update,
            complete_event as _cal_complete,
            crash_event as _cal_crash,
        )
        _CALENDAR_ENABLED = True
        print("📅 calendar_bridge loaded — Calendar events active")
    except Exception as _cal_err:
        _CALENDAR_ENABLED = False
        _cal_create = _cal_update = _cal_complete = _cal_crash = None
        print(f"📅 calendar_bridge unavailable — Calendar events disabled ({_cal_err})")
    
    if os.environ.get("LSAMC_IGNORE_LOCK") == "1":
        print("\n" + "!"*60)
        print("⚠️  WARNING: LSAMC_IGNORE_LOCK=1 is DETECTED.")
        print("⚠️  This bypasses safety checks and can cause PROCESS COLLISIONS.")
        print("⚠️  Ensure no other supervisor or agent is running.")
        print("!"*60 + "\n")
    
    available_groups = discover_available_groups()
    print(f"📡 Discovered {len(available_groups)} groups in macOS Contacts.")

    target_group_arg = args.group
    
    if target_group_arg:
        queue = [target_group_arg]
        current_group = target_group_arg
    else:
        state = load_state()
        current_group = state.get("current_group")
        
        # v4.9.5: Intersect Priority Queue with Discovered Groups
        queue = [g for g in GroupQueue if g in available_groups]
        print(f"📋 Priority Queue (Filtered): {len(queue)} groups ready.")
        
        if not current_group and queue:
            current_group = queue[0]
            
    group_idx = 0
    if current_group in queue:
        group_idx = queue.index(current_group)
    else:
        # If saved group is gone, reset to start of queue
        group_idx = 0
        current_group = queue[0] if queue else None
    
    # v3.5.9: Ensure dashboard is live at startup
    ensure_monitor_running()

    # v5.0: Birthday trigger — refresh cache if stale (>7 days), then queue T+2 matches
    try:
        _birthday_cache = os.path.join("data", "birthday_cache.json")
        _cache_stale = True
        if os.path.exists(_birthday_cache):
            _cache_age = time.time() - os.path.getmtime(_birthday_cache)
            _cache_stale = _cache_age > 7 * 86400  # 7 days
        if _cache_stale:
            print("🎂 Birthday cache stale or missing — rebuilding (may take 15-30 min)...")
            _rc = subprocess.run(
                [sys.executable, "scripts/birthday_trigger.py", "--refresh-cache"],
                timeout=3600  # 1 hour max
            ).returncode
            if _rc == 0:
                print("🎂 Birthday cache rebuilt.")
            else:
                print(f"⚠️ Birthday cache rebuild failed (exit {_rc}). Continuing without.")
        else:
            print(f"🎂 Birthday cache fresh ({_cache_age/86400:.1f} days old).")
        # Daily check: find T+2 birthday contacts and add to LSAM-Birthday
        if os.path.exists(_birthday_cache):
            _rc = subprocess.run(
                [sys.executable, "scripts/birthday_trigger.py", "--days", "2"],
                timeout=30
            ).returncode
            if _rc == 0:
                print("🎂 Birthday trigger check complete.")
    except Exception as _bd_err:
        print(f"⚠️ Birthday trigger skipped: {_bd_err}")

    consecutive_crashes = 0
    fast_failures = 0
    active_agent = FastAgent
    stable_batch_count = 0  # v4.9.1 E2: consecutive clean Slow Horse batches (AUDIT_2026-03-11)
    status = None

    # v1.0 CALENDAR-BRIDGE: session-level event (one event per supervisor run)
    _session_start = time.time()
    _current_group = current_group or "?"
    _cal_uid = _cal_create("LSAM", "Sync Session", eta_minutes=None) if _CALENDAR_ENABLED else None
    _session_ended = False  # guards against double-close on exit

    while group_idx < len(queue):
        # v4.9.2 CAPTCHA-KILL: Check for sentinel before each phase
        if os.path.exists("logs/CAPTCHA_KILL"):
            print("🛑 CAPTCHA_KILL sentinel detected at startup. Engine stopped.")
            print("   Remove 'logs/CAPTCHA_KILL' and restart supervisor when LinkedIn session is safe.")
            update_supervisor_status("N/A", status="CAPTCHA_KILL")
            if _CALENDAR_ENABLED and _cal_uid and not _session_ended:
                _cal_crash(_cal_uid, "LSAM", "Sync Session", _current_group, "CAPTCHA_KILL sentinel")
                _session_ended = True
            break

        target_group = queue[group_idx]

        # v3.1.3: Agent Selection (Persistent within Phase)
        # v3.1.3: Agent Selection (Persistent within Phase)
        # We only set the default if we are NOT in the middle of an escalation
        # v3.5.3: Use Name-Based Logic for robustness against Filtered Queue shifts
        if not (status == "SUCCESS" and active_agent == BaselineAgent and group_idx < len(queue) and queue[group_idx] == target_group):
            if target_group_arg:
                 active_agent = BaselineAgent
            elif target_group in ["script-LSAM-Force-Refresh", "script-LSAM-Tier3-NeedAttention", "script-LSAM-LinkedIn to Review"]:
                active_agent = BaselineAgent
            elif fast_failures == 0:
                active_agent = FastAgent
            
        print(f"\n📂 PHASE {group_idx + 1 if not target_group_arg else 'MANUAL'}: Target Group -> {target_group}")
        if not target_group_arg:
            save_state(target_group)

        # v3.5.1: Count contacts for status reporting
        group_names = get_group_names_sorted(target_group)
        total_contacts = len(group_names)
        print(f"📊 {target_group} has {total_contacts} contacts.")
        
        # v4.8.3: Skip empty or non-existent groups to prevent crash loops
        if total_contacts == 0:
            print(f"⏭️ Group '{target_group}' is empty or does not exist. Skipping to next phase.")
            group_idx += 1
            consecutive_crashes = 0
            continue
        
        update_supervisor_status(target_group, group_idx=group_idx, total_contacts=total_contacts)
        _current_group = target_group
        if _CALENDAR_ENABLED and _cal_uid:
            _short = target_group.replace("script-LSAM-", "").replace("script - ", "")
            _cal_update(_cal_uid, "LSAM", "Sync Session", _short, group_idx, len(queue))

        # Pre-Flight Cleanup
        kill_orphans()
        time.sleep(2)
        
        # Network Check (v4.0)
        wait_for_network()

        # Run
        is_phase_5 = (group_idx == 4)
        is_tier3_reprocess = (group_idx == 1)
        is_phase_0 = (group_idx == 0) # Force Refresh Group
        status = run_agent(consecutive_crashes, active_agent, target_group, mode, force=(is_phase_0 or is_phase_5 or is_tier3_reprocess or target_group_arg is not None), limit=args.limit)
        
        # Decision
        if status == "STOP":
            if _CALENDAR_ENABLED and _cal_uid and not _session_ended:
                _cal_crash(_cal_uid, "LSAM", "Sync Session", _current_group, "STOP signal")
                _session_ended = True
            break
        elif status == "CAPTCHA":
            print("🛑 CAPTCHA detected. Supervisor stopping to protect LinkedIn session.")
            update_supervisor_status(target_group, status="CAPTCHA_KILL")
            if _CALENDAR_ENABLED and _cal_uid and not _session_ended:
                _cal_crash(_cal_uid, "LSAM", "Sync Session", _current_group, "CAPTCHA detected by agent")
                _session_ended = True
            break
        elif status == "SUCCESS":
            # v2.2: Mutual Parity / Resync Routing Flow
            # Check if there are .resync flags left that the Fast Agent might have skipped
            resync_flags = glob.glob("logs/sessions/*/backups/*/.resync")
            if resync_flags and active_agent == FastAgent:
                print(f"🔄 Fast Engine finished, but {len(resync_flags)} .resync candidates remain. Switching to Slow Horse for surgical completion...")
                active_agent = BaselineAgent
                consecutive_crashes = 0
                continue

            # v3.0: Group Completion & Escalation
            print(f"✅ Group '{target_group}' complete.")
            
            # Special: Tier 3 Reporting
            if target_group == "script-LSAM-Tier3-NeedAttention":
                print("📝 Generating Tier 3 Comparison Report...")
                subprocess.run([sys.executable, "src/utils/generate_tier3_report.py"])
            
            group_idx += 1
            active_agent = FastAgent # Reset to Fast for next group
            fast_failures = 0
            consecutive_crashes = 0
            stable_batch_count = 0  # v4.9.1 E2: reset on group completion
            continue
            
        elif status in ["CRASH", "CRASH_RESET"]:
            if status == "CRASH_RESET":
                consecutive_crashes = 0
            else:
                consecutive_crashes += 1
            stable_batch_count = 0  # v4.9.1 E2: crash resets stability counter

            # THE DOWNSHIFT LOGIC
            if active_agent == FastAgent:
                fast_failures += 1
                if fast_failures >= MaxFastFailures:
                    print(f"📉 DOWNSHIFT: Fast Engine failed {fast_failures} times. Switching to Baseline (Slow Horse).")
                    active_agent = BaselineAgent
                else:
                    print(f"⚠️ Fast Engine failure {fast_failures}/{MaxFastFailures}. Retrying Fast...")
            
            if consecutive_crashes >= MaxConsecutiveCrashes:
                print(f"🚨 CIRCUIT BREAKER: {consecutive_crashes} total failures. Stopping.")
                if _CALENDAR_ENABLED and _cal_uid and not _session_ended:
                    _cal_crash(_cal_uid, "LSAM", "Sync Session", _current_group, f"Circuit breaker: {consecutive_crashes} crashes")
                    _session_ended = True
                break
            
            print(f"⏳ Restarting in {RestartDelay} seconds...")
            time.sleep(RestartDelay)
        
        elif status == "BATCH_COMPLETE":
            # v4.8.3: Clean batch recycle — restart same group with fresh browser
            consecutive_crashes = 0  # Not a crash, reset counter
            # v4.9.1 E2: Auto-recover Fast mode after 2 stable Slow Horse batches (AUDIT_2026-03-11)
            if active_agent == BaselineAgent:
                stable_batch_count += 1
                if stable_batch_count >= 2:
                    print(f"📈 AUTO-RECOVER: {stable_batch_count} stable Slow Horse batches → restoring Fast Engine.")
                    active_agent = FastAgent
                    fast_failures = 0
                    stable_batch_count = 0
                else:
                    print(f"📊 Slow Horse stable batch {stable_batch_count}/2. One more needed to recover Fast mode.")
            else:
                stable_batch_count = 0  # Already on Fast Engine, no recovery needed
            print(f"♻️ Batch complete. Restarting same group with fresh browser in 10s...")
            time.sleep(10)  # Short delay for Chrome cleanup
            continue

    if group_idx >= len(queue):
        print("\n🏁 ALL GROUPS COMPLETE. SYSTEM STANDBY.")
        if _CALENDAR_ENABLED and _cal_uid and not _session_ended:
            # v5.0 Sprint 6: Collect per-contact outcomes from session logs
            _summary = _collect_session_summary()
            _cal_complete(_cal_uid, "LSAM", "Sync Session",
                          duration_seconds=int(time.time() - _session_start),
                          summary_notes=_summary)
            _session_ended = True
        # v3.6.0: Generate Mandatory Final Report
        try:
            print("📊 Generating Mandatory Final Report...")
            subprocess.run([sys.executable, "scripts/generate_final_report.py"])
        except Exception as e:
            print(f"⚠️ Failed to generate final report: {e}")

        # Cleanup state
        if not target_group_arg and os.path.exists(STATE_FILE): os.remove(STATE_FILE)

    # Safety net: close calendar event if session exited without an explicit close
    if _CALENDAR_ENABLED and _cal_uid and not _session_ended:
        _cal_crash(_cal_uid, "LSAM", "Sync Session", _current_group, "Unexpected exit")

    clear_supervisor_status()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

