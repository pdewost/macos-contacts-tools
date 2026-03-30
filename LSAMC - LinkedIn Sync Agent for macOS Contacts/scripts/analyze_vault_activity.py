
import os
import json
import time
import glob
import re
from datetime import datetime, timedelta

VAULT_ROOT = "data/vault"
LOG_ROOT = "logs/sessions"
AnalysisDays = 5
Now = time.time()
TimeLimit = Now - (AnalysisDays * 86400)

print(f"🔍 Analyzing Vault & Logs (Last {AnalysisDays} days)...")

# 1. Map Vault Data
vault_map = {} # ID -> {name, mtime, ctime}
for root, dirs, files in os.walk(VAULT_ROOT):
    for file in files:
        if file == "profile.json":
            path = os.path.join(root, file)
            stats = os.stat(path)
            mtime = getattr(stats, 'st_mtime', 0)
            ctime = getattr(stats, 'st_birthtime', stats.st_ctime)
            
            if mtime > TimeLimit:
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    cid = os.path.basename(root).split(":")[0]
                    vault_map[cid] = {
                        "name": data.get("full_name", "Unknown"),
                        "mtime": mtime,
                        "ctime": ctime,
                        "details": bool(data.get("experience") or data.get("skills")),
                        "url": data.get("linkedin_url"),
                        "is_new": ctime > TimeLimit
                    }
                except: pass

# 2. Parse Logs for Events
events = {
    "disambiguated": set(),
    "reprocessed": set(), # Based on "Updating" or "Enriching" logs
    "failed": set()
}

# Scan logs
log_pattern = os.path.join(LOG_ROOT, "run_2026-*")
for session_dir in glob.glob(log_pattern):
    # Filter by date in filename (run_YYYY-MM-DD...)
    try:
        date_str = session_dir.split("_")[1]
        sess_date = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
        if sess_date < TimeLimit: continue
    except: continue
    
    log_file = os.path.join(session_dir, "session.log")
    if os.path.exists(log_file):
        with open(log_file, 'r', errors='ignore') as f:
            content = f.read()
            
            # Find Disambiguations
            # Heuristic: "Ambiguity resolved" or "Manual override" or "Pre-filled from Review"
            # Actually, the user does manual review. The Agent just syncs.
            # But if a contact was in "Review" group and is now "Success", that's a disambiguation success.
            # We can look for "Starting batch sync for group: script-LSAM-LinkedIn to Review"
            if "script-LSAM-LinkedIn to Review" in content:
                # All successes in this session are likely disambiguations
                successes = re.findall(r"Sync Results for (.*?): SUCCESS", content)
                for name in successes:
                    events["disambiguated"].add(name.strip().lower())

            # Find Reprocessed
            # Look for "Merging with existing vault data" or similar
            # Or if "Force Mode" was used on existing contacts
            if "FORCE MODE" in content:
                 successes = re.findall(r"Sync Results for (.*?): SUCCESS", content)
                 for name in successes:
                     events["reprocessed"].add(name.strip().lower())
                     
            # Find Failures
            fails = re.findall(r"Sync Results for (.*?): (?:ERROR|FAILED)", content)
            for name in fails:
                events["failed"].add(name.strip().lower())

# 3. Correlate
results = {
    "1st_time": [],
    "reprocessed_improved": [],
    "disambiguated": [],
    "success": [],
    "failure": list(events["failed"])
}

for cid, data in vault_map.items():
    name = data["name"]
    name_lower = name.lower()
    mtime_str = datetime.fromtimestamp(data["mtime"]).strftime('%Y-%m-%d %H:%M')
    
    entry = f"{name} ({mtime_str})"
    
    # Categorize
    if name_lower in events["disambiguated"]:
        results["disambiguated"].append(entry)
    elif name_lower in events["reprocessed"]:
         results["reprocessed_improved"].append(entry)
    elif data["is_new"]:
        results["1st_time"].append(entry)
    else:
        # Modified but not in special events -> Reprocessed implicitly? 
        # Or standard update
        results["reprocessed_improved"].append(entry) # Fallback for updated old files

    # All in vault are successes
    results["success"].append(entry)

# 4. Output
print(f"\n📊 Vault Analysis (Last {AnalysisDays} Days)")
print("=========================================")

print(f"\n🆕 1st Time Processing ({len(results['1st_time'])}):")
for i in results['1st_time'][:15]: print(f" - {i}")

print(f"\n✨ Successfully Disambiguated ({len(results['disambiguated'])}):")
for i in results['disambiguated'][:15]: print(f" - {i}")

print(f"\n🔄 Reprocessed / Improved ({len(results['reprocessed_improved'])}):")
for i in results['reprocessed_improved'][:15]: print(f" - {i}")

print(f"\n❌ Failures (In Logs): {len(results['failure'])}")
for i in results['failure'][:5]: print(f" - {i}")

print(f"\n✅ Total Vault Successes (Touched): {len(results['success'])}")

