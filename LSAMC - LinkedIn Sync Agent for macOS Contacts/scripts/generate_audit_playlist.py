
import os
import json
import logging
import datetime
import glob
from pathlib import Path

# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
VAULT_DIR = DATA_DIR / "vault"
PLAYLIST_FILE = DATA_DIR / "audit_playlist.json"

# Days to look back
LOOKBACK_DAYS = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AuditPlaylistGen")

def load_processed_logs():
    """Scans session logs for activity."""
    activity = {}
    
    # 1. Scan session.log files (Source of Truth for "Disambiguated" and "Failures")
    # Pattern: logs/sessions/run_YYYY-MM-DD_HH-MM-SS/session.log
    session_logs = glob.glob(str(LOG_DIR / "sessions" / "*" / "session.log"))
    # Also fast_sessions if they exist
    session_logs.extend(glob.glob(str(LOG_DIR / "fast_sessions" / "*" / "session.log")))
    
    cutoff = datetime.datetime.now() - datetime.timedelta(days=LOOKBACK_DAYS)
    
    for log_path in session_logs:
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(log_path))
            if mtime < cutoff: continue
            
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Parse Disambiguations
                    if "Successfully disambiguated" in line or "Ambiguity Resolved" in line:
                         # Extract Name/ID if possible, usually logged as "Contact Name (ID)"
                         # Needs robust parsing based on actual log format
                         pass
                    
                    # Parse Failures
                    if "❌" in line or "Error applying" in line:
                        pass
                        
        except Exception as e:
            logger.error(f"Error reading log {log_path}: {e}")
            
    return activity

def scan_vault_recency():
    """Scans the vault for recently modified profiles."""
    candidates = []
    
    cutoff_ts = (datetime.datetime.now() - datetime.timedelta(days=LOOKBACK_DAYS)).timestamp()
    
    # Walk the vault
    # Structure: 
    # 1. data/vault/contact_id/profile.json (Active Vault)
    # 2. data/vault/archived/run_.../Name/profile.json (Session Backups)
    
    # We want to catch EVERYTHING that happened recently.
    # PROPOSAL: Scan both. "Active Vault" tells us the CURRENT truth.
    # "Archived" tells us about the EVENT.
    # For Audit, we want the EVENT.
    
    # Let's verify vault/archived too
    archived_glob = DATA_DIR / "vault" / "archived" / "*" / "*" / "profile.json"
    
    all_files = list(VAULT_DIR.glob("*/profile.json")) + list(glob.glob(str(archived_glob)))
    
    seen_ids = set()
    
    for p_str in all_files:
        path_obj = Path(p_str)
        
        try:
            stat = path_obj.stat()
            if stat.st_mtime < cutoff_ts: continue
            
            # Load profile
            with open(path_obj, 'r') as f:
                profile = json.load(f)
                
            cid = profile.get("_contact_id") or profile.get("id") or profile.get("contact_id")
            
            # If from archive, ID might not be in filename, trust profile 
            if not cid and "archived" in str(path_obj):
                # Try folder name heuristic? 
                pass
            if not cid: continue
            
            # Deduplicate: Only keep the most recent event per ID
            if cid in seen_ids: continue # TODO: Logic to keep BEST (newest)
            seen_ids.add(cid)

            # Determine Category
            category = "Success" # Default
            reason = "Routine Update"
            
            # Heuristics for Category
            # 1. New: ctime close to mtime (approx)
            if abs(stat.st_mtime - stat.st_birthtime) < 3600: 
                category = "New"
                reason = "First Time Processing"
            
            candidates.append({
                "id": cid,
                "name": profile.get("full_name") or profile.get("Name") or "Unknown",
                "path": str(path_obj),
                "timestamp": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "category": category,
                "reason": reason,
                "status": "VAULT_PRESENT"
            })
            
        except Exception as e:
            logger.error(f"Error scanning {path_obj}: {e}")
            
    return candidates

def main():
    logger.info(f"Generating Audit Playlist (Last {LOOKBACK_DAYS} days)...")
    
    # 1. Get Vault Candidates (Successes/New)
    vault_items = scan_vault_recency()
    logger.info(f"Found {len(vault_items)} recent vault updates.")
    
    # 2. Identify Failures & Disambiguations (TODO: parsing logs is tricky, let's start with Vault)
    # v1.0: Focus on Vault Audit first.
    
    # 3. Categorize & Sort
    # Priority: Disambiguated > New > Success
    # Since we only have Vault items now, let's sort by "New" vs "Success"
    
    def sort_key(item):
        order = {"New": 1, "Success": 2} # lower is higher priority
        return (order.get(item["category"], 99), item["timestamp"])
    
    vault_items.sort(key=sort_key)
    
    # 4. Write Playlist
    with open(PLAYLIST_FILE, 'w') as f:
        json.dump(vault_items, f, indent=2)
        
    logger.info(f"Playlist generated: {len(vault_items)} items written to {PLAYLIST_FILE}")
    print(f"Audit Playlist Ready: {len(vault_items)} items.")

if __name__ == "__main__":
    main()
