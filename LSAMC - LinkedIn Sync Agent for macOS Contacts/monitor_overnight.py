#!/usr/bin/env python3
"""
Dashboard Monitor (Campaign Edition - v2.1)
=====================================
Monitors the progress of the LinkedIn Sync Agent across multiple auto-restarts.
Aggregates "Global Progress" from Historical Archives + All Today's Sessions.
Includes "Review Bucket" and "Live Heartbeat" sections.
"""

import os
import time
import re
import glob
import json
import unicodedata
from datetime import datetime, timedelta
import subprocess

# CONFIG
LOG_DIRS = ["logs/sessions", "logs/fast_sessions"]
ARCHIVE_DIR = "logs/archive/applied"
OUTPUT_FILE = "SYNC_PROGRESS.md"
JOURNAL_FILE = "JOURNAL.md"
JOURNAL_TRACKER = "logs/.journal_tracker"
REFRESH_INTERVAL = 10  # Seconds

def normalize_name(n):
    return re.sub(r'[^a-z0-9]', '', n.lower()) if n else ""

# Estimated Total for Tier 3 (Hardcoded based on user info)
TOTAL_CAMPAIGN_TARGET = 278 

def count_historical_archived():
    """Counts contacts in logs/archive/applied (excluding today)."""
    if not os.path.exists(ARCHIVE_DIR): return 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for session_name in os.listdir(ARCHIVE_DIR):
        session_path = os.path.join(ARCHIVE_DIR, session_name)
        if not os.path.isdir(session_path): continue
        if f"run_{today_str}" in session_name: continue
        contacts = [c for c in os.listdir(session_path) if os.path.isdir(os.path.join(session_path, c))]
        count += len(contacts)
    return count

def get_todays_sessions():
    """Returns list of session directories from all engine roots for today, sorted by time."""
    today = datetime.now().strftime("%Y-%m-%d")
    all_sessions = []
    for root in LOG_DIRS:
        all_sessions.extend(glob.glob(os.path.join(root, f"run_{today}_*")))
    return sorted(all_sessions, key=lambda x: os.path.basename(x))

def parse_session_log(session_dir):
    """Parses a single session log for stats and events."""
    log_file = os.path.join(session_dir, "session.log")
    stats = {
        "success_count": 0,
        "fail_count": 0,
        "skipped_count": 0,
        "start_time": None,
        "end_time": None,
        "status": "Unknown",
        "events": [],
        "processed_names": set(),
        "is_fast": "fast_sessions" in session_dir
    }
    
    if not os.path.exists(log_file):
        return stats

    try:
        with open(log_file, "r", errors="ignore") as f:
            lines = f.readlines()
    except:
        return stats
        
    if not lines: return stats

    # Time extraction
    try:
        stats["start_time"] = lines[0].split(" - ")[0]
        stats["end_time"] = lines[-1].split(" - ")[0]
    except: pass

    # Status inference
    last_line = lines[-1]
    last_mod = datetime.fromtimestamp(os.path.getmtime(log_file))
    time_since_mod = (datetime.now() - last_mod).total_seconds()

    if "Closing browser session" in last_line or "Job Complete" in last_line:
        stats["status"] = "✅ Done"
    elif "CRITICAL" in last_line or "Traceback" in last_line:
        stats["status"] = "❌ Crashed"
    elif time_since_mod < 300: # Increased window from 180
        stats["status"] = "🏃 Running"
    else:
        stats["status"] = "⚠️ Stalled"

    # Engine specific icons
    engine_icon = "⚡" if stats["is_fast"] else "🐌"

    # Event parsing
    for line in lines:
        try:
            parts = line.split(" - ")
            if len(parts) < 4: continue
            
            ts_raw = parts[0].split(" ")
            ts = ts_raw[1].split(",")[0] if len(ts_raw) > 1 else "?"
            lvl = parts[2].strip()
            msg = parts[3].strip()
            
            event_type = "INFO"
            if "SUCCESS" in msg: 
                event_type = "SUCCESS"
                match = re.search(r"(?:Sync Results for |FAST SYNC SUCCESS for )(.*?)(?::| \()", msg)
                if match: 
                    name = match.group(1).strip()
                    stats["processed_names"].add(name)
                    stats["success_count"] += 1
            elif "FAILED" in msg or "ERROR" in msg:
                event_type = "ERROR"
                stats["fail_count"] += 1
            elif "SKIPPED" in msg or "Ambiguity" in msg:
                event_type = "WARNING"
                stats["skipped_count"] += 1
            elif "delay" in msg.lower() or "cooling down" in msg.lower() or "Resting" in msg:
                event_type = "DELAY"
            elif "SYSTEM STARTUP" in msg or "BROWSER LAUNCH" in msg or "LOGIN" in msg:
                event_type = "SYSTEM"

            # v2.1.2: Refined Heartbeat Filter (Allow Extraction Progress)
            noise_markers = [
                "Saved staging profile", "AUDIT COMPLETE", "[Surgical]", 
                "Final stats before surgical", "Sanitized Profile", 
                "Surgical Local Scrape successful", "Returning Surgical Local Scrape", 
                "Attempting primary Surgical", "Contact Info trigger attempt", 
                "Clicking failed, trying direct navigation", "Stealth Heartbeat",
                "Checking LinkedIn authentication", "Setting up browser", "🌐 BROWSER LAUNCH"
            ]
            if any(m in msg for m in noise_markers):
                continue

            # Clean message icon
            icon = "ℹ️"
            if event_type == "SUCCESS": icon = "✅"
            elif event_type == "ERROR": icon = "❌"
            elif event_type == "WARNING": icon = "⚠️"
            elif event_type == "SYSTEM": 
                if "LOGIN" in msg: icon = "🔐"
                elif "STARTUP" in msg: icon = "🚀"
                else: icon = "⚙️"
            elif event_type == "DELAY": icon = "⏳"

            # Add to stats events
            stats["events"].append({
                "ts": ts,
                "msg": msg,
                "type": event_type,
                "icon": icon,
                "engine": engine_icon
            })
        except:
            continue

    return stats

def get_group_names_sorted(group_name):
    """Fetches full name list from group via AppleScript (Robust version)."""
    try:
        script = f'tell application "Contacts" to get name of people of group "{group_name}"'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode != 0: return []
        raw_output = res.stdout.strip()
        if not raw_output: return []
        names = [n.strip() for n in raw_output.split(',')]
        # Filter "missing value" strings
        return [n for n in names if n and n.lower() not in ["missing value", "null", "none"]]
    except: return []

def discover_available_groups():
    """v3.5.0: Dynamic Discovery to Match Supervisor."""
    try:
        script = 'tell application "Contacts" to get name of every group'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode != 0: return []
        raw_output = res.stdout.strip()
        if not raw_output: return []
        groups = [g.strip() for g in raw_output.split(',')]
        return [g for g in groups if g and g.lower() not in ["missing value", "null", "none"]]
    except: return []

def get_all_time_successes():
    """Builds a set of all names ever successfully synced."""
    success_pool = set()
    # 1. Archive
    if os.path.exists(ARCHIVE_DIR):
        for session in os.listdir(ARCHIVE_DIR):
            path = os.path.join(ARCHIVE_DIR, session)
            if os.path.isdir(path):
                contacts = [c.replace("_", " ") for c in os.listdir(path) if os.path.isdir(os.path.join(path, c))]
                success_pool.update(contacts)
    # 2. All Session Logs (Dual Engine Root)
    for root in LOG_DIRS:
        log_files = glob.glob(os.path.join(root, "run_*/session.log"))
        for log_path in log_files:
            if os.path.exists(log_path):
                with open(log_path, 'r', errors='ignore') as f:
                    content = f.read()
                    matches = re.findall(r"(?:Sync Results for |FAST SYNC SUCCESS for )(.*?)(?::| SUCCESS)", content)
                    success_pool.update([m.strip() for m in matches])
    return success_pool

# v3.0 Architectural Queue
GroupQueue = [
    "script-LSAM-Priority",               # Phase 0: Struggle / Urgent Fixes (F1)
    "script-LSAM-Broken Names",           # Phase 1: High Visibility Bug Fixes
    "script-LSAM-DAMAGED",                # Phase 2: Remediated Social Handles
    "script-LSAM-Force-Refresh",          # Phase 3: Recent (10-Day) & Bulk Tagged
    "script-LSAM-Tier3-NeedAttention",    # Phase 4: Tier 3 Refinement
    "script-LSAM-LinkedIn to Review",     # Phase 5: Ambiguous matches
    "script - no photo and on LinkedIn"   # Extra: legacy smart group
]
STATE_FILE = "logs/.supervisor_state"

def get_supervisor_state():
    """Reads state from STATE_FILE or .supervisor_status for real-time sync."""
    status_file = "logs/.supervisor_status"
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as f:
                data = json.load(f)
                # If status is fresh (< 30 min), trust it for the active group
                if time.time() - data.get("timestamp", 0) < 1800:
                    # v3.5.8: Prefer explicit index from status if available
                    if "index" in data and data["index"] >= 0:
                        return {"current_group_idx": data["index"], "live_status": data}
                    
                    # Fallback to name-based lookup
                    group_name = data.get("group")
                    for i, g in enumerate(GroupQueue):
                        if g == group_name:
                            return {"current_group_idx": i, "live_status": data}
        except: pass

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    
    # v3.1.7: Infer state from logs if supervisor finished or state lost
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = glob.glob(f"logs/sessions/run_{today}_*")
        if not sessions: return {"current_group_idx": 0}
        
        last_s = sorted(sessions)[-1]
        log_file = os.path.join(last_s, "session.log")
        if os.path.exists(log_file):
            with open(log_file, "r", errors="ignore") as f:
                content = f.read()
                # If FORCE MODE was used today, it's likely a forced phase
                if "FORCE MODE" in content:
                    return {"current_group_idx": 0}
                # Fallback: check group names in order
                for i in reversed(range(len(GroupQueue))):
                    if GroupQueue[i] in content:
                        return {"current_group_idx": i}
    except: pass
    
    return {"current_group_idx": 0}

def get_group_summary(group_idx):
    """Aggregates successes/fails/duration for a specific phase index today."""
    if group_idx >= len(GroupQueue): return {"success": 0, "fail": 0, "skipped": 0, "processed": 0, "duration": "0m"}
    group_name = GroupQueue[group_idx]
    
    # v3.5.7: Align with Supervisor.py v4.9.x
    # Index 0 (Broken), Index 1 (Damaged), Index 2 (Refresh) are forced.
    is_force_phase = (group_idx in [0, 1, 2])
    
    sessions = get_todays_sessions()
    total_success = 0
    total_fail = 0
    total_skipped = 0
    total_seconds = 0
    
    for s in sessions:
        log_file = os.path.join(s, "session.log")
        if not os.path.exists(log_file): continue
        try:
            with open(log_file, "r", errors="ignore") as f:
                content = f.read()
                if group_name not in content: continue
                
                # v3.5.3: Only use FORCE MODE disambiguation for shared group names
                is_ambiguous = GroupQueue.count(group_name) > 1
                if is_ambiguous:
                    is_log_force = "FORCE MODE" in content
                    if is_force_phase != is_log_force: continue
                
                stats = parse_session_log(s)
                total_success += stats["success_count"]
                total_fail += stats["fail_count"]
                total_skipped += stats["skipped_count"]
                
                if stats["start_time"] and stats["end_time"]:
                    try:
                        fmt = "%Y-%m-%d %H:%M:%S"
                        # Handle milliseconds and trailing garbage
                        s_ts = stats["start_time"].split(",")[0].strip()
                        e_ts = stats["end_time"].split(",")[0].strip()
                        
                        d1 = datetime.strptime(s_ts, fmt)
                        d2 = datetime.strptime(e_ts, fmt)
                        total_seconds += (d2 - d1).total_seconds()
                    except: pass
        except: pass
                
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    duration_str = f"{h}h {m}m" if h > 0 else f"{m}m"
    return {
        "success": total_success,
        "fail": total_fail,
        "skipped": total_skipped,
        "processed": total_success + total_fail + total_skipped,
        "duration": duration_str
    }

def count_photo_tiers_today() -> dict:
    """
    Scan today's session logs for photo quality and tier attribution.
    v4.9.1 E1 (AUDIT_2026-03-11): DOM drift detection metric.

    Tier attribution via explicit log markers in pro_sync_agent.py:
      Tier 1: "Tier 1 SUCCESS: Passive capture"
      Tier 2: "Tier 2 post-click sniffer captured signed URL"   (v4.9.1 C2)
      Tier 4: "Tier 4 SUCCESS: Canvas extracted"
      Tier 3: inferred — HQ download not attributed to T1/T2/T4
      LQ:     "Photo downloaded via browser" where bytes < LQ_BYTES_THRESHOLD
      Vault:  "SPOT Vault Hit for" (profile served from vault, no live photo needed)
      None:   "All Tiers failed" (all 4 live tiers failed; may still use historical URL)

    Returns dict: tier1, tier2, tier3, tier4, hq, lq, vault, none
    """
    LQ_BYTES_THRESHOLD = 20_000  # <20KB → 200×200 or smaller fallback thumbnail

    today = datetime.now().strftime("%Y-%m-%d")
    sessions = []
    for root in LOG_DIRS:
        sessions.extend(glob.glob(os.path.join(root, f"run_{today}_*")))

    tier1 = tier2 = tier4 = 0
    hq = lq = vault = none_count = 0

    pat_download = re.compile(r"Photo downloaded via browser \((\d+) bytes\)")
    pat_tier1 = re.compile(r"Tier 1 SUCCESS: Passive capture")
    pat_tier2 = re.compile(r"Tier 2 post-click sniffer captured signed URL")
    pat_tier4 = re.compile(r"Tier 4 SUCCESS: Canvas extracted")
    pat_vault  = re.compile(r"SPOT Vault Hit for")
    pat_none   = re.compile(r"All Tiers failed to find high-res photo")

    for s in sessions:
        log_file = os.path.join(s, "session.log")
        if not os.path.exists(log_file):
            continue
        try:
            with open(log_file, "r", errors="ignore") as f:
                content = f.read()
            tier1      += len(pat_tier1.findall(content))
            tier2      += len(pat_tier2.findall(content))
            tier4      += len(pat_tier4.findall(content))
            vault      += len(pat_vault.findall(content))
            none_count += len(pat_none.findall(content))
            for m in pat_download.finditer(content):
                if int(m.group(1)) >= LQ_BYTES_THRESHOLD:
                    hq += 1
                else:
                    lq += 1
        except Exception:
            pass

    # Tier 3 inferred: HQ browser downloads not attributed to T1 or T2
    # (T4 uses canvas extraction — not a browser download)
    tier3 = max(0, hq - tier1 - tier2)

    return {
        "tier1": tier1, "tier2": tier2, "tier3": tier3, "tier4": tier4,
        "hq": hq, "lq": lq, "vault": vault, "none": none_count,
    }


# ---------------------------------------------------------------------------
# v4.9.1 — Journal auto-append (one-liner per completed session)
# ---------------------------------------------------------------------------

def _load_journaled_sessions() -> set:
    """Load the set of session paths already written to JOURNAL.md."""
    if not os.path.exists(JOURNAL_TRACKER):
        return set()
    try:
        with open(JOURNAL_TRACKER, "r") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def _record_journaled_session(session_path: str) -> None:
    """Persist a session path to the tracker file so it is never re-appended."""
    try:
        os.makedirs(os.path.dirname(JOURNAL_TRACKER), exist_ok=True)
        with open(JOURNAL_TRACKER, "a") as f:
            f.write(session_path + "\n")
    except Exception:
        pass


def _append_session_to_journal(session_path: str, stats: dict, group_name: str) -> None:
    """
    Append a one-liner session summary to JOURNAL.md under:

        ## 🤖 Session Log *(auto-appended by monitor_overnight.py)*
        ### YYYY-MM-DD
        - HH:MM ✅ N synced[, F failed][, S skipped] | X/hr | Engine — Group (Xm)

    The section is created at the end of the file if it does not yet exist.
    A new date subsection is created if today's date is not present.
    Existing human-authored journal entries are never modified.
    """
    if not os.path.exists(JOURNAL_FILE):
        return

    today_str = datetime.now().strftime("%Y-%m-%d")

    # --- Build the one-liner ---
    speed = 0.0
    duration_m = 0
    if stats.get("start_time") and stats.get("end_time"):
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            t1 = datetime.strptime(stats["start_time"].split(",")[0].strip(), fmt)
            t2 = datetime.strptime(stats["end_time"].split(",")[0].strip(), fmt)
            elapsed_s = (t2 - t1).total_seconds()
            duration_m = max(0, int(elapsed_s // 60))
            if elapsed_s > 0 and stats["success_count"] > 0:
                speed = stats["success_count"] / (elapsed_s / 3600)
        except Exception:
            pass

    end_hhmm = "??:??"
    if stats.get("end_time"):
        try:
            end_hhmm = stats["end_time"].split(" ")[1].split(",")[0][:5]
        except Exception:
            pass

    status_icon = (
        "✅" if "Done"    in stats["status"] else
        "❌" if "Crashed" in stats["status"] else
        "⚠️"
    )
    engine = "Fast" if stats.get("is_fast") else "Slow Horse"
    counts = [f"{stats['success_count']} synced"]
    if stats["fail_count"]:
        counts.append(f"{stats['fail_count']} failed")
    if stats["skipped_count"]:
        counts.append(f"{stats['skipped_count']} skipped")
    group_short = group_name.replace("script-LSAM-", "").replace("script - ", "")
    speed_str = f"{speed:.1f}/hr" if speed > 0 else "—"
    dur_str = f"{duration_m}m" if duration_m else "?"

    bullet = (
        f"- {end_hhmm} {status_icon} {', '.join(counts)}"
        f" | {speed_str} | {engine} — {group_short} ({dur_str})"
    )

    # --- Splice into JOURNAL.md ---
    SESSION_LOG_HEADER = "## 🤖 Session Log *(auto-appended by monitor_overnight.py)*"
    date_subheader = f"### {today_str}"

    try:
        with open(JOURNAL_FILE, "r") as f:
            content = f.read()

        if SESSION_LOG_HEADER not in content:
            # First-ever entry: create the section at the very end
            content = (
                content.rstrip("\n")
                + f"\n\n---\n\n{SESSION_LOG_HEADER}\n\n{date_subheader}\n{bullet}\n"
            )
        else:
            sec_pos = content.index(SESSION_LOG_HEADER)
            tail = content[sec_pos:]

            if date_subheader in tail:
                # Append bullet right after the existing date line
                dh_abs = sec_pos + tail.index(date_subheader) + len(date_subheader)
                nl = content.find("\n", dh_abs)
                if nl != -1:
                    content = content[:nl + 1] + bullet + "\n" + content[nl + 1:]
                else:
                    content += "\n" + bullet + "\n"
            else:
                # Insert a new date subsection right after the section header line
                header_end = sec_pos + len(SESSION_LOG_HEADER)
                nl = content.find("\n", header_end)
                insert_at = nl + 1 if nl != -1 else len(content)
                content = (
                    content[:insert_at]
                    + f"\n{date_subheader}\n{bullet}\n"
                    + content[insert_at:]
                )

        with open(JOURNAL_FILE, "w") as f:
            f.write(content)

    except Exception as e:
        print(f"⚠️ Journal append error: {e}")


# Module-level set — loaded once at import, kept in sync during the monitor loop
_journaled_sessions: set = _load_journaled_sessions()


def update_dashboard():
    now = datetime.now()
    available_groups = discover_available_groups()
    state = get_supervisor_state()
    current_idx = state.get("current_group_idx", 0)
    live_status = state.get("live_status", {})
    
    # v3.5.0: Dynamic Filtered Queue
    active_queue = [g for g in GroupQueue if g in available_groups]
    
    current_group = GroupQueue[current_idx] if current_idx < len(GroupQueue) else "Unknown"
    
    # Check if we are in a forced-rerun phase (v3.1)
    is_force_rerun_phase = (current_idx in [0, 1, 2])
    
    # --- 1. THE GROUND TRUTH ---
    all_successes = get_all_time_successes()
    
    # v3.1.6: Forced Rerun Logic
    # If the supervisor is in index 4 (Phase 5), we only count progress from FORCE sessions today.
    is_force_rerun_phase = (current_idx == 4)
    force_session_processed = set()
    
    if is_force_rerun_phase:
        sessions = get_todays_sessions()
        for s in sessions:
            log_file = os.path.join(s, "session.log")
            if os.path.exists(log_file):
                with open(log_file, "r", errors="ignore") as f:
                    content = f.read()
                    if "FORCE MODE" in content:
                        # Count SUCCESS, SKIPPED_AMBIGUOUS, and SEARCH_FAILED as "Processed" for progress bar
                        processed = re.findall(r"Sync Results for (.*?): (?:SUCCESS|SKIPPED_|ERROR_SEARCH_FAILED)", content)
                        before_count = len(force_session_processed)
                        for s_name in processed:
                            force_session_processed.add(normalize_name(s_name.strip()))
                        if len(force_session_processed) > before_count:
                            print(f"  [Monitor] Found {len(force_session_processed) - before_count} new results in {os.path.basename(s)}")

    # v2.0.4.10: Aggressive Normalization Helper
        
    def get_clean_name(name):
        return re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()

    def is_done(name):
        norm = normalize_name(name)
        norm_clean = normalize_name(get_clean_name(name))
        
        if is_force_rerun_phase:
            return (norm in force_session_processed) or (norm_clean in force_session_processed)
            
        if norm in all_successes: return True
        if norm_clean in all_successes: return True
        return False

    # Current Group Stats
    group_names = get_group_names_sorted(current_group)
    total_target = live_status.get("total") or len(group_names)
    
    # v3.5.2: Progress Calculation Refinement
    # Instead of counting "Done names STILL in group" (which fails if agent removes them),
    # we use the aggregated session summary for this phase index.
    summary = get_group_summary(current_idx)
    current_progress = summary["processed"] # Includes success, fail, skipped
    
    remaining_count = max(0, total_target - current_progress)
    progress_pct = (current_progress / total_target) * 100 if total_target > 0 else 0
    
    # --- 2. LOG AGGREGATION ---
    sessions = get_todays_sessions()
    session_rows = []
    heartbeat_events = []
    review_bucket = {} # Name -> {ts, reason, icon}
    unique_names_today = set()
    latest_session_status = "Inactive"
    current_engine = "Unknown"
    current_skipped_by_filter = 0

    session_stats_pairs = []
    for session_path in sessions:
        stats = parse_session_log(session_path)
        session_stats_pairs.append((session_path, stats))
        unique_names_today.update(stats["processed_names"])
        
        start_t = stats["start_time"].split(" ")[1].split(",")[0] if stats["start_time"] else "?"
        end_t = stats["end_time"].split(" ")[1].split(",")[0] if stats["end_time"] else "*"
        
        if stats["status"] == "🏃 Running":
            end_t = "*Active*"
            latest_session_status = "🏃 Running"
            current_engine = "⚡ Fast Engine" if stats["is_fast"] else "🐌 Slow Horse"
            
            log_file = os.path.join(session_path, "session.log")
            if os.path.exists(log_file):
                with open(log_file, "r", errors="ignore") as f:
                    log_c = f.read()
                    match = re.search(r"Smart Filter: Skipped (\d+)", log_c)
                    if match: current_skipped_by_filter = int(match.group(1))
        
        heartbeat_events.extend(stats["events"])
        
        for ev in stats["events"]:
            if ev["type"] in ["WARNING", "ERROR"]:
                match = re.search(r"(?:Status for |Sync Results for |during )(.*?)(?::| crashed| sync status)", ev["msg"])
                if match:
                    name = match.group(1).strip()
                    if len(name) < 3 or name.lower() in ["unknown", "linkedin", "browser", "setup"]: continue
                    reason = ev["msg"].split(":")[-1].strip() if ":" in ev["msg"] else ev["msg"]
                    review_bucket[name] = {"ts": ev["ts"], "reason": reason, "icon": ev["icon"]}
            elif ev["type"] == "SUCCESS":
                match = re.search(r"(?:Sync Results for |FAST SYNC SUCCESS for )(.*?)(?::| \()", ev["msg"])
                if match:
                    name = match.group(1).strip()
                    if name in review_bucket: del review_bucket[name]

        engine_icon = "⚡" if stats["is_fast"] else "🐌"
        session_rows.append(f"| {start_t} | {end_t} | {stats['success_count']} | {stats['status']} | {engine_icon} |")

    # --- 2b. JOURNAL: append one-liner for each newly-completed session ---
    global _journaled_sessions
    for sess_path, sess_stats in session_stats_pairs:
        if sess_path in _journaled_sessions:
            continue
        finished = sess_stats["status"] in ("✅ Done", "❌ Crashed", "⚠️ Stalled")
        has_data  = (sess_stats["success_count"] + sess_stats["fail_count"]) > 0
        if finished and has_data:
            _append_session_to_journal(sess_path, sess_stats, current_group)
            _record_journaled_session(sess_path)
            _journaled_sessions.add(sess_path)

    # --- 3. HEARTBEAT & REVIEW ---
    heartbeat_events.sort(key=lambda x: x["ts"], reverse=True)
    heartbeat_visible = heartbeat_events[:20]
    review_visible = sorted(review_bucket.items(), key=lambda x: x[1]["ts"], reverse=True)[:20]

    # --- 4. SPEED & ETA ---
    speed = 0
    if sessions:
        first_s = parse_session_log(sessions[0])
        if first_s["start_time"]:
            try:
                start_dt = datetime.strptime(first_s["start_time"].split(",")[0], "%Y-%m-%d %H:%M:%S")
                elapsed = (now - start_dt).total_seconds() / 3600
                if elapsed > 0: speed = len(unique_names_today) / elapsed
            except: pass

    eta_str = "Unknown"
    if speed > 0 and remaining_count > 0:
        eta_dt = now + timedelta(hours=(remaining_count / speed))
        eta_str = eta_dt.strftime("%H:%M")
    elif remaining_count == 0:
        eta_str = "Done"

    # --- 4.5. PHOTO QUALITY METRIC (v4.9.1 E1) ---
    _ph = count_photo_tiers_today()
    _ph_total = _ph["hq"] + _ph["lq"]
    _drift_warn = (
        " ⚠️ **DOM DRIFT**"
        if _ph["lq"] > _ph_total * 0.6 and _ph_total >= 3
        else ""
    )
    photo_metric_row = (
        f"| Photo HQ | Photo LQ | Vault | No Photo (Live) | Tier Attribution |\n"
        f"| :--- | :--- | :--- | :--- | :--- |\n"
        f"| 📷 `{_ph['hq']}` | 🔻 `{_ph['lq']}` "
        f"| 🗄️ `{_ph['vault']}` | 🚫 `{_ph['none']}` "
        f"| T1:`{_ph['tier1']}` T2:`{_ph['tier2']}` "
        f"T3:`{_ph['tier3']}` T4:`{_ph['tier4']}`{_drift_warn} |"
    )

    # --- 5. PROGRESS BAR ---
    bar_len = 40
    filled = int(progress_pct / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    # --- 6. ROADMAP RENDERING ---
    roadmap_lines = []
    found_current = False
    active_phase_display_index = "?"
    
    for i, g_name in enumerate(active_queue):
        # v3.5.5: Robust absolute indexing
        try:
            mapped_idx = GroupQueue.index(g_name)
        except ValueError:
            mapped_idx = -1

        
        summary = get_group_summary(mapped_idx)
        
        if mapped_idx == current_idx and not found_current:
            found_current = True
            active_phase_display_index = i + 1
            badge = "🏃 **Phase {} (ACTIVE)**".format(i + 1)
            extra = " (🔥 **Forced Rerun**)" if (mapped_idx == 6) else ""
            line = f"- {badge}: `{g_name}`{extra} (Dur: {summary['duration']} | Pro: {summary['processed']} | ✅: {summary['success']})"
        elif not found_current:
            line = f"- ✅ **Phase {i+1}**: `{g_name}` (Dur: {summary['duration']} | Pro: {summary['processed']} | ✅: {summary['success']})"
        else:
            line = f"- 🕒 **Phase {i+1}**: `{g_name}` (Queued)"
        roadmap_lines.append(line)

    # --- 7. RENDER ---
    report = f"""# 📊 LSAM Backend Engine Sync Dashboard
**Last Update**: `{now.strftime("%Y-%m-%d %H:%M:%S")}` | **Status**: {latest_session_status} | **Engine**: {current_engine}

## 🗺️ Execution Roadmap
"""
    report += "\n".join(roadmap_lines) + "\n"

    report += f"""
---

## 📈 Active Phase Progress: Phase {active_phase_display_index}
`{current_progress} / {total_target}` contacts **({progress_pct:.1f}%)**
`{bar}`
**Remaining**: `{remaining_count}` unique contacts | **ETA**: `{eta_str}`

| Success (Today) | Speed (Today) | Filtered (Safe Skip) | Active Sessions |
| :--- | :--- | :--- | :--- |
| ✅ `{len(unique_names_today)}` | 🏎️ `{speed:.1f} /hr` | 🛡️ `{current_skipped_by_filter}` | 🔢 `{len(sessions)}` |

{photo_metric_row}

---

## 🕒 Live Heartbeat (Latest 20)
*Shows current pacing and system vitality.*

"""
    if heartbeat_visible:
        for ev in heartbeat_visible:
            msg = ev["msg"]
            if len(msg) > 100: msg = msg[:97] + "..."
            report += f"- {ev['icon']} `{ev['ts']}` {msg}\n"
    else:
        report += "- *Waiting for events...*\n"

    report += f"""
---

## 🚨 Review Bucket (Action Required - Latest {len(review_visible)})
*Contacts that failed or were flagged as ambiguous and need manual review.*

| Timestamp | Contact Name | Result / Reason |
| :--- | :--- | :--- |
"""
    if review_visible:
        for name, data in review_visible:
            report += f"| `{data['ts']}` | **{name}** | {data['icon']} {data['reason']} |\n"
    else:
        report += "| - | *No items pending review* | - |\n"

    report += f"""
---

## 🧬 Historical Timeline
*Full session history for today.*

| Start | End | Success | Status | Eng |
| :--- | :--- | :--- | :--- | :--- |
"""
    for row in reversed(session_rows):
        report += row + "\n"

    with open(OUTPUT_FILE, "w") as f:
        f.write(report)
    print(f"✅ Dashboard updated: Phase {current_idx+1} ({current_group}) - {current_progress}/{total_target}")

def monitor():
    print("🔭 Campaign Monitor (v2.1) Started...")
    while True:
        try:
            update_dashboard()
        except Exception as e:
            print(f"⚠️ Dashboard error: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    monitor()
