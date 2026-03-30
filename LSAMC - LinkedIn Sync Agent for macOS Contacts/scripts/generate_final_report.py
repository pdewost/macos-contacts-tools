#!/usr/bin/env python3
"""
LSAM Final Report Generator
Aggregates stats from today's sessions and generates a mandatory summary.
"""

import os
import re
import json
import glob
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

# --- Configuration ---
LOG_DIRS = ["logs/sessions", "logs/fast_sessions"]
ARCHIVE_DIR = "logs/archive/applied"
VAULT_CENSUS = "data/vault_census.json"
REPORT_DIR = "."

# LSAM Groups to check for membership
LSAM_GROUPS = [
    "script-LSAM-Force-Refresh",
    "script-LSAM-Tier3-NeedAttention",
    "script-LSAM-Cleanup-Mutuals",
    "script-LSAM-Tier2-NoteHasLinkedIn",
    "script-LSAM-LinkedIn to Review",
    "script - no photo and on LinkedIn",
    "script-LSAM-Exempted",
    "LSAM LinkedIn Review",
    "script-LSAM-Manual-Fix-Required",
    "script-LSAM-Quarantine",
    "script-LSAM-Search-Failed"
]

def get_group_members(group_name):
    """Fetches members of a macOS Contacts group."""
    try:
        script = f'tell application "Contacts" to get name of people of group "{group_name}"'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode != 0: return []
        raw = res.stdout.strip()
        if not raw: return []
        return [n.strip() for n in raw.split(',')]
    except: return []

def parse_today_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    sessions = []
    for root in LOG_DIRS:
        sessions.extend(glob.glob(os.path.join(root, f"run_{today}_*")))
    
    unique_contacts = set()
    successes = set()
    failures = []
    skips = defaultdict(int)
    total_seconds = 0
    actually_processed = set()
    
    # Skip reasons we care about
    skip_reasons = ["SKIPPED_AMBIGUOUS", "SKIPPED_STEALTH_POLICY", "SKIPPED_EXEMPTED", 
                    "SKIPPED_SELF_IDENTIFIED", "SKIPPED_ALREADY_DONE", "SKIPPED_NO_URL"]

    for s_dir in sorted(sessions):
        log_file = os.path.join(s_dir, "session.log")
        if not os.path.exists(log_file): continue
        
        with open(log_file, "r", errors="ignore") as f:
            lines = f.readlines()
            if not lines: continue
            
            # Duration
            try:
                start_ts = lines[0].split(" - ")[0].split(",")[0]
                end_ts = lines[-1].split(" - ")[0].split(",")[0]
                fmt = "%Y-%m-%d %H:%M:%S"
                d1 = datetime.strptime(start_ts, fmt)
                d2 = datetime.strptime(end_ts, fmt)
                total_seconds += (d2 - d1).total_seconds()
            except: pass
            
            for line in lines:
                # Success
                match_succ = re.search(r"Sync Results for (.*?): SUCCESS", line)
                if match_succ:
                    name = match_succ.group(1).strip()
                    successes.add(name)
                    unique_contacts.add(name)
                    actually_processed.add(name)
                
                # Fails
                match_fail = re.search(r"Sync Results for (.*?): (?:ERROR_|FAILED)(.*)", line)
                if match_fail:
                    name = match_fail.group(1).strip()
                    err = match_fail.group(2).strip()
                    failures.append({"name": name, "reason": err})
                    unique_contacts.add(name)
                    actually_processed.add(name)

                # Skip
                match_skip = re.search(r"Sync Results for (.*?): (SKIPPED_\w+)", line)
                if match_skip:
                    name = match_skip.group(1).strip()
                    reason = match_skip.group(2).strip()
                    skips[reason] += 1
                    unique_contacts.add(name)
                    if reason in ["SKIPPED_AMBIGUOUS", "SKIPPED_SEARCH_FAILED"]:
                        actually_processed.add(name)

    return {
        "unique_contacts": unique_contacts,
        "successes": successes,
        "failures": failures,
        "skips": skips,
        "total_seconds": total_seconds,
        "actually_processed": actually_processed
    }

def get_newbies(successes):
    """Newbies are successes today that were NEVER in archive before today."""
    today = datetime.now().strftime("%Y-%m-%d")
    archived_names = set()
    if os.path.exists(ARCHIVE_DIR):
        for s in os.listdir(ARCHIVE_DIR):
            if today in s: continue
            path = os.path.join(ARCHIVE_DIR, s)
            if os.path.isdir(path):
                archived_names.update([c.replace("_", " ") for c in os.listdir(path) if os.path.isdir(os.path.join(path, c))])
    
    newbies = [n for n in successes if n not in archived_names]
    return newbies

def generate_report():
    stats = parse_today_stats()
    newbies = get_newbies(stats["successes"])
    
    # Vault Total
    vault_total = 0
    if os.path.exists(VAULT_CENSUS):
        with open(VAULT_CENSUS, 'r') as f:
            census = json.load(f)
            vault_total = len(census)
    
    # Duration formatting
    h = int(stats["total_seconds"] // 3600)
    m = int((stats["total_seconds"] % 3600) // 60)
    duration_str = f"{h}h {m}m"
    
    # Avg Speed
    avg_speed = 0
    if stats["total_seconds"] > 0:
        avg_speed = len(stats["unique_contacts"]) / (stats["total_seconds"] / 3600)
    
    # Group membership mapping
    group_map = defaultdict(list)
    relevant_contacts = set(stats["unique_contacts"])
    for gname in LSAM_GROUPS:
        members = get_group_members(gname)
        for m in members:
            # We only list contacts that were part of today's run if possible, 
            # but user said "list of all contacts sorted by the macOS Contact Group" 
            # which might mean the whole group. Let's stick to relevant ones + some sanity.
            group_map[gname].append(m)

    # Filename
    now = datetime.now()
    filename = f"LSAM-Output-Report-{now.strftime('%d%m%y-%H%M')}.md"
    fpath = os.path.join(REPORT_DIR, filename)
    
    with open(fpath, "w") as f:
        f.write(f"# 🏁 LSAM Final Engine Report\n")
        f.write(f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write(f"## 📊 Run Metrics\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"| :--- | :--- |\n")
        f.write(f"| **Duration** | {duration_str} |\n")
        f.write(f"| **Avg Contacts/Hour** | {avg_speed:.1f} |\n")
        f.write(f"| **Contacts Examined (Unique)** | {len(stats['unique_contacts'])} |\n")
        f.write(f"| **Newbies (1st Sync)** | {len(newbies)} |\n")
        f.write(f"| **Actually Processed by LSAM** | {len(stats['actually_processed'])} |\n")
        f.write(f"| **Successes (Ready to Review)** | {len(stats['successes'])} |\n")
        f.write(f"| **Failures** | {len(stats['failures'])} |\n")
        f.write(f"| **Total Vault Size** | {vault_total} |\n\n")
        
        f.write(f"## 🛡️ Skip Analysis\n")
        f.write(f"| Reason | Count |\n")
        f.write(f"| :--- | :--- |\n")
        for reason, count in sorted(stats["skips"].items(), key=lambda x: x[1], reverse=True):
            f.write(f"| {reason} | {count} |\n")
        f.write("\n")
        
        if stats["failures"]:
            f.write(f"## ❌ Failure Details\n")
            f.write(f"| Contact | Error |\n")
            f.write(f"| :--- | :--- |\n")
            for fail in stats["failures"]:
                f.write(f"| **{fail['name']}** | {fail['reason']} |\n")
            f.write("\n")

        f.write(f"## 📂 Contact Placement (by macOS Group)\n")
        for gname in LSAM_GROUPS:
            members = group_map.get(gname, [])
            if members:
                # Only show top 50 if too many? No, user wants the list.
                f.write(f"### `{gname}` ({len(members)} entries)\n")
                # Filter members to those seen today to keep it manageable? 
                # User asked for "all contacts sorted by the macOS Contact Group they have been placed into"
                # This could be messy if a group has 2000 members.
                # I'll list them alphabetically.
                f.write(", ".join(sorted(members)) + "\n\n")

    print(f"✅ Final report generated: {fpath}")
    return fpath

if __name__ == "__main__":
    generate_report()
