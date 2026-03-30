#!/usr/bin/env python3
"""
LSAM Legacy Integrity Sweep
Version: 1.0.0
Purpose: Audits the 'script-LSAM-Force-Refresh' group for 'Wrong Horse' mismatches
caused by legacy engine versions (< 1.0.0).
"""

import sys
import os
import re
from typing import List, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

TARGET_GROUP = "script-LSAM-Force-Refresh"
QUARANTINE_GROUP = "script-LSAM-LinkedIn to Review"

def parse_sync_block(note: str) -> Dict[str, Any]:
    """Extracts metadata from the LSAM sync block."""
    if not note: return {}
    
    res = {
        "version": "0.0.0",
        "degree": "Unknown",
        "connections": 0,
        "mutual": 0,
        "handle": "None",
        "date": "Unknown",
        "raw": note
    }
    
    # Version
    v_match = re.search(r"LSAMC v([\d\.]+)", note)
    if v_match: res["version"] = v_match.group(1)
    
    # Date
    d_match = re.search(r"<Linkedin-AI-sync ([\d-]+) (update|added)>", note)
    if d_match: res["date"] = d_match.group(1)
    
    # Degree
    deg_match = re.search(r"Connections : [\d,]+ \(([^)]+)\)", note)
    if deg_match: res["degree"] = deg_match.group(1)
    
    # Handle (either in note or we can extract from URL if present)
    h_match = re.search(r"linkedin\.com/in/([^/\s\?\">]+)", note)
    if h_match: res["handle"] = h_match.group(1)
    
    # Connections (Numeric)
    c_match = re.search(r"Connections : ([\d,]+)", note)
    if c_match:
        try:
            res["connections"] = int(c_match.group(1).replace(",", ""))
        except: pass
        
    # Mutual (Numeric)
    m_match = re.search(r"Mutual connections : (\d+)", note)
    if m_match:
        try:
            res["mutual"] = int(m_match.group(1))
        except: pass
        
    return res

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LSAM Legacy Sweep")
    parser.add_argument("--full", action="store_true", help="Execute the quarantine moves")
    parser.add_argument("--threshold", type=int, default=5000, help="Connection threshold for suspicion")
    args = parser.parse_args()

    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    
    print(f"--- Starting Legacy Integrity Sweep on '{TARGET_GROUP}' ---")
    
    # 1. Get names and IDs
    list_res = bridge.list_group_contacts(TARGET_GROUP)
    if not list_res["success"]:
        print(f"Error listing contacts: {list_res.get('error')}")
        return
    
    # 2. Get notes in bulk
    notes_res = bridge.batch_get_group_notes(TARGET_GROUP)
    if not notes_res["success"]:
        print(f"Error fetching notes: {notes_res.get('error')}")
        return

    # 3. Get social handles in bulk
    social_res = bridge.batch_get_group_social(TARGET_GROUP)
    social_map = {}
    if social_res["success"]:
        # Map ID to first LinkedIn handle found
        for cid, urls in social_res["social_map"].items():
            for url in urls:
                if "linkedin.com/in/" in url.lower():
                    handle = url.split("linkedin.com/in/")[-1].strip("/")
                    social_map[cid] = handle
                    break
    
    notes_data = notes_res["notes"]
    contacts = list_res["matches"]
    
    print(f"Auditing {len(contacts)} contacts...")
    
    quarantine_list = []
    
    for c in contacts:
        contact_id = c["id"]
        note = notes_data.get(contact_id, "")
        
        if "<Linkedin-AI-sync" not in note:
            continue
            
        meta = parse_sync_block(note)
        # Prioritize handle from social profile field
        effective_handle = social_map.get(contact_id, meta["handle"])
        
        # Determine if it's a legacy version
        try:
            version_parts = [int(p) for p in meta["version"].split(".")]
            is_legacy = version_parts[0] < 1
        except:
            is_legacy = True
        
        is_suspicious = False
        reasons = []
        
        # Rule 1: Legacy + High Connections (> threshold)
        if is_legacy and meta["connections"] >= args.threshold:
            is_suspicious = True
            reasons.append(f"High Connections ({meta['connections']}) in Legacy block")
            
        # Rule 2: Legacy + Low Mutuals (0 or 1)
        if is_legacy and "Mutual connections" in note:
             if meta["connections"] > 1000 and meta["mutual"] <= 1:
                is_suspicious = True
                reasons.append(f"Low Mutuals ({meta['mutual']}) for {meta['connections']} connections")

        if is_suspicious:
            quarantine_list.append({
                "name": c['name'],
                "handle": effective_handle,
                "date": meta["date"],
                "reason": "; ".join(reasons)
            })

    print(f"\nFound {len(quarantine_list)} suspicious legacy contacts.")
    
    for item in quarantine_list:
        print(f"  [QUARANTINE] {item['name']} | Handle: {item['handle']} | Date: {item['date']} | Reason: {item['reason']}")
        
    if args.full and quarantine_list:
        print(f"\nMoving {len(quarantine_list)} contacts to '{QUARANTINE_GROUP}'...")
        for c, reason in quarantine_list:
            bridge.add_to_group(c["id"], QUARANTINE_GROUP)
            bridge.remove_from_group(c["id"], TARGET_GROUP)
            # Tag the note
            new_note = f"⚠️ LSAM QUARANTINE: {reason}\n\n" + c.get("note", "")
            # Note: updating note is missing in simple bridge, but we can use AppleScript if needed
            print(f"  Quarantined: {c['name']}")
    elif not args.full:
        print("\nSimulation complete. Use --full to quarantine these contacts.")

if __name__ == "__main__":
    main()
