
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
import shutil

# --- Configuration ---
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
VAULT_DIR = PROJECT_ROOT / "data" / "vault"
ARCHIVE_DIR = VAULT_DIR / "archived"
OUTPUT_FILE = PROJECT_ROOT / "data" / "vault_census.json"
REPORT_FILE = PROJECT_ROOT / "VAULT_CENSUS_REPORT.md"

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("VaultCensus")

def scan_vault():
    """Scans Active Vault and Archived Vault to build a complete history."""
    
    census: Dict[str, Dict] = {} 
    # Structure:
    # {
    #   "contact_id": {
    #       "name": str,
    #       "first_seen": timestamp,
    #       "last_seen": timestamp,
    #       "sync_count": int,
    #       "paths": [list of paths],
    #       "status": "Active" | "Archived"
    #   }
    # }

    # 1. Scan Active Vault
    logger.info("Scanning Active Vault...")
    if VAULT_DIR.exists():
        for item in VAULT_DIR.iterdir():
            if item.is_dir() and (item / "profile.json").exists():
                process_folder(item, census, "Active")

    # 2. Scan Archive
    logger.info("Scanning Archives...")
    if ARCHIVE_DIR.exists():
        # Archive is typically date-based: archived/YYYY-MM-DD/Name_ID
        for date_folder in ARCHIVE_DIR.iterdir():
            if date_folder.is_dir():
                for item in date_folder.iterdir():
                    if item.is_dir() and (item / "profile.json").exists():
                        process_folder(item, census, "Archived")

    return census

def process_folder(folder_path: Path, census: Dict, status: str):
    try:
        with open(folder_path / "profile.json", 'r') as f:
            profile = json.load(f)
            
        cid = profile.get("id") or profile.get("linkedin_id") # Fallback
        name = profile.get("full_name") or folder_path.name
        
        if not cid:
            # Try to extract from folder name if possible (Name_ID)
            parts = folder_path.name.split('_')
            if len(parts) > 1:
                cid = parts[-1]
            else:
                logger.warning(f"Skipping {folder_path.name}: No ID found.")
                return

        # Timestamp Determination
        # Active folders might not have a timestamp in name, use file mtime
        # Archive folders are usually in a date folder
        
        mtime = folder_path.stat().st_mtime
        ts = datetime.fromtimestamp(mtime)
        
        if cid not in census:
            census[cid] = {
                "id": cid,
                "name": name,
                "first_seen": ts.isoformat(),
                "last_seen": ts.isoformat(),
                "sync_count": 0,
                "paths": [],
                "current_status": "Archived" # Will be overwritten if found in Active
            }
        
        # Update Stats
        rec = census[cid]
        rec["sync_count"] += 1
        rec["paths"].append(str(folder_path))
        
        # Update Status (Active overrides Archived)
        if status == "Active":
            rec["current_status"] = "Active"
            
        # Update Dates
        rec_first = datetime.fromisoformat(rec["first_seen"])
        rec_last = datetime.fromisoformat(rec["last_seen"])
        
        if ts < rec_first:
            rec["first_seen"] = ts.isoformat()
        if ts > rec_last:
            rec["last_seen"] = ts.isoformat()
            
    except Exception as e:
        logger.error(f"Error reading {folder_path}: {e}")

def generate_report(census: Dict):
    """Analyzes census and writes a markdown report."""
    logger.info("Generating Report...")
    
    total = len(census)
    active_count = sum(1 for c in census.values() if c["current_status"] == "Active")
    multi_sync_count = sum(1 for c in census.values() if c["sync_count"] > 1)
    
    # Age Distribution
    now = datetime.now()
    age_dist = {
        "< 1 Week": 0,
        "1-2 Weeks": 0,
        "2-4 Weeks": 0,
        "1-3 Months": 0,
        "> 3 Months": 0
    }
    
    oldest_needs_scan = []
    
    for c in census.values():
        last = datetime.fromisoformat(c["last_seen"])
        delta = (now - last).days
        
        if delta < 7: age_dist["< 1 Week"] += 1
        elif delta < 14: age_dist["1-2 Weeks"] += 1
        elif delta < 30: age_dist["2-4 Weeks"] += 1
        elif delta < 90: age_dist["1-3 Months"] += 1
        else: age_dist["> 3 Months"] += 1
        
        # Identify "Revisit Candidates" (Active in Vault but old)
        # OR just generally old?
        # User wants "Revisit process... starting by the oldest"
        # So we sort ALL by last_seen ascending
        
    # Sort by Last Seen (Ascending = Oldest Last Sync first)
    sorted_census = sorted(census.values(), key=lambda x: x["last_seen"])
    
    # Write Report
    with open(REPORT_FILE, 'w') as f:
        f.write(f"# LSAM Vault Census Report\n")
        f.write(f"**Date**: {now.strftime('%Y-%m-%d %H:%M')}\n\n")
        
        f.write(f"## 📊 Population Stats\n")
        f.write(f"- **Total Unique Contacts**: {total}\n")
        f.write(f"- **Currently Active in Vault**: {active_count}\n")
        f.write(f"- **Multi-Sync Contacts**: {multi_sync_count} (Processed >1 time)\n\n")
        
        f.write(f"## 🕒 Staleness Distribution (Last Sync)\n")
        for k, v in age_dist.items():
            f.write(f"- **{k}**: {v}\n")
            
        f.write(f"\n## 👴 Top 20 Oldest Contacts (Revisit Candidates)\n")
        f.write("| Name | Last Sync | Sync Count | Status |\n")
        f.write("|---|---|---|---|\n")
        for c in sorted_census[:20]:
            last_date = c["last_seen"].split("T")[0]
            f.write(f"| {c['name']} | {last_date} | {c['sync_count']} | {c['current_status']} |\n")
            
        f.write(f"\n## 💡 Revisit Strategy Proposal\n")
        f.write(f"Based on the data above, we recommend:\n")
        f.write(f"1. **Priority**: Start with the `> 3 Months` cohort.\n")
        f.write(f"2. **Pace**: Max 5-10 revisits per day mixed with new traffic.\n")
        f.write(f"3. **Refinement**: Cross-reference with macOS Contacts Sync Block.\n")

    # Save raw JSON
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(census, f, indent=2)
        
    logger.info(f"Census saved to {OUTPUT_FILE}")
    logger.info(f"Report saved to {REPORT_FILE}")

if __name__ == "__main__":
    data = scan_vault()
    generate_report(data)
