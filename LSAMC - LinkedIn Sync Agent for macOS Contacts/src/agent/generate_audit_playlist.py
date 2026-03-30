import os
import re
import json
import glob
from datetime import datetime
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIRS = [PROJECT_ROOT / "logs/sessions", PROJECT_ROOT / "logs/fast_sessions"]
OUTPUT_FILE = PROJECT_ROOT / "data" / "audit_playlist.json"

def scan_recent_failures(hours=48):
    """Scans session logs for failures in the last N hours."""
    playlist = []
    seen_ids = set()
    
    # Calculate cutoff
    cutoff_ts = datetime.now().timestamp() - (hours * 3600)
    
    for log_dir in LOG_DIRS:
        if not log_dir.exists(): continue
        
        # Sort by time, newest first
        sessions = sorted(log_dir.glob("run_*"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        for session in sessions:
            if session.stat().st_mtime < cutoff_ts:
                break
                
            log_file = session / "session.log"
            if not log_file.exists(): continue
            
            with open(log_file, "r", errors="ignore") as f:
                lines = f.readlines()
                
            for line in lines:
                # Basic parsing
                if "ERROR" in line or "FAILED" in line or "Ambiguous" in line:
                    # Extract Name
                    # Patterns: "Sync Results for Name: ERROR" or "Status for Name: ERROR"
                    match = re.search(r"(?:Sync Results for |Status for |during )(.*?)(?::| crashed| sync status)", line)
                    if match:
                        name = match.group(1).strip()
                        if len(name) < 2 or name in ["Unknown", "setup", "browser"]: continue
                        
                        # We need an ID and Path found in the folder
                        # Search the session folder for this contact
                        contact_dir = None
                        for item in session.iterdir():
                            if item.is_dir() and item.name != "artifacts" and name.lower() in item.name.lower().replace("_"," "):
                                contact_dir = item
                                break
                        
                        if contact_dir:
                            # Try to read profile.json for ID
                            cid = "Unknown"
                            try:
                                with open(contact_dir / "profile.json", "r") as pf:
                                    prof = json.load(pf)
                                    cid = prof.get("id") or prof.get("_contact_id") or contact_dir.name
                            except:
                                cid = contact_dir.name

                            if cid not in seen_ids:
                                playlist.append({
                                    "id": cid,
                                    "name": name,
                                    "path": str(contact_dir),
                                    "reason": line.split("-")[-1].strip(),
                                    "category": "Session Failure"
                                })
                                seen_ids.add(cid)

    return playlist

if __name__ == "__main__":
    print(f"Generating audit playlist from logs (last 48h)...")
    items = scan_recent_failures()
    
    # Ensure data dir exists
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    
    with open(OUTPUT_FILE, "w") as f:
        json.dump(items, f, indent=2)
        
    print(f"Generated {len(items)} items in {OUTPUT_FILE}")
