
import os
import glob
import re
from datetime import datetime

GroupQueue = [
    "script-LSAM-Force-Refresh", 
    "script-LSAM-Tier3-NeedAttention",
    "script-LSAM-Cleanup-Mutuals", 
    "script-LSAM-Tier2-NoteHasLinkedIn",
    "script-LSAM-LinkedIn to Review",
    "script - no photo and on LinkedIn", 
    "script-LSAM-LinkedIn to Review"
]

def get_todays_sessions():
    today = datetime.now().strftime("%Y-%m-%d")
    return glob.glob(f"logs/sessions/run_{today}_*")

def parse_session_log(log_path):
    stats = {"success": 0, "fail": 0, "skipped": 0}
    with open(log_path, "r", errors="ignore") as f:
        # Replicating parse_session_log logic roughly
        for line in f:
            if " - SUCCESS - " in line: stats["success"] += 1
            elif " - ERROR - " in line: stats["fail"] += 1
            elif " - WARNING - " in line and ("SKIPPED" in line or "Ambiguity" in line): stats["skipped"] += 1
    return stats

def debug_summary(group_idx):
    print(f"🔍 DEBUGGING Group Index {group_idx}")
    group_name = GroupQueue[group_idx]
    
    # Monitor Logic Copy
    is_force_phase = (group_idx == 0 or group_idx == 1) # REMOVED 6
    
    sessions = get_todays_sessions()
    total_processed = 0
    
    for s in sessions:
        log_file = os.path.join(s, "session.log")
        if not os.path.exists(log_file): continue
        
        with open(log_file, "r", errors="ignore") as f:
            content = f.read()
            if group_name not in content: continue
            
            # Ambiguity Logic
            is_ambiguous = GroupQueue.count(group_name) > 1
            if is_ambiguous:
                is_log_force = "FORCE MODE" in content
                if is_force_phase != is_log_force: continue
            
            # If we are here, we count this log
            stats = parse_session_log(log_file)
            p = stats["success"] + stats["fail"] + stats["skipped"]
            print(f"   - {os.path.basename(s)}: +{p}")
            total_processed += p

    print(f"✅ Total Processed: {total_processed}")

if __name__ == "__main__":
    debug_summary(6)
