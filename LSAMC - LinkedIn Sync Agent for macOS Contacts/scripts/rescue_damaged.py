#!/usr/bin/env python3
"""
LSAM Rescue Audit: DAMAGED -> Priority
Version: 1.0.0
Purpose: Scans the 'script-LSAM-DAMAGED' group for contacts who have a LinkedIn URL 
in their Social Profile field but were missed by the note-only ventilation script.
"""

import sys
import os
import logging
from typing import List, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

DAMAGED_GROUP = "script-LSAM-DAMAGED"
PRIORITY_GROUP = "script-LSAM-Priority"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LSAM Rescue Audit")
    parser.add_argument("--full", action="store_true", help="Execute the rescue moves")
    args = parser.parse_args()

    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    
    print(f"--- Starting Rescue Audit on '{DAMAGED_GROUP}' ---")
    
    # 1. Fetch group members
    res = bridge.list_group_contacts(DAMAGED_GROUP)
    if not res["success"]:
        print(f"Error listing group: {res.get('error')}")
        return
    
    contacts = res["matches"]
    print(f"Auditing {len(contacts)} contacts...")
    
    # 2. Batch fetch social profiles
    soc_res = bridge.batch_get_group_social(DAMAGED_GROUP)
    if not soc_res["success"]:
        print(f"Error fetching social profiles: {soc_res.get('error')}")
        return
    
    social_map = soc_res["social_map"]
    candidates = []
    
    # 3. Analyze
    for c in contacts:
        urls = social_map.get(c["id"], [])
        for url in urls:
            if "linkedin.com/in/" in url.lower():
                candidates.append((c, url))
                break
    
    print(f"Found {len(candidates)} false positives (contacts with LinkedIn social profiles).")
    
    if not candidates:
        print("No rescue needed.")
        return
        
    for c, url in candidates:
        print(f"  [RESCUE candidate] {c['name']} -> {url}")
        
    # 4. Execute
    if args.full:
        print(f"\nMoving {len(candidates)} contacts to '{PRIORITY_GROUP}'...")
        for c, url in candidates:
            # Add to priority
            bridge.add_to_group(c["id"], PRIORITY_GROUP)
            # Remove from damaged
            bridge.remove_from_group(c["id"], DAMAGED_GROUP)
            print(f"  Rescued: {c['name']}")
    else:
        print("\nSimulation complete. Use --full to rescue these contacts.")

if __name__ == "__main__":
    main()
