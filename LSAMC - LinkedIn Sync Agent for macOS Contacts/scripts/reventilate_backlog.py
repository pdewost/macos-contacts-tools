#!/usr/bin/env python3
"""
LSAM Sorting Engine (Backlog Ventilation)
Version: 1.1.0
Purpose: Rule-based redistribution of the 1440+ "Force-Refresh" contacts into refined groups.
Prevents " Institutional Fog" by separating broken links from valid periodic refreshes.
"""

import sys
import os
import argparse
import logging
import re
from typing import List, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge
from src.models.profile import LinkedInProfile

# Target Groups for Ventilation
GROUPS = {
    "source": "script-LSAM-Force-Refresh",
    "priority": "script-LSAM-Priority",         # Explicit user repair
    "broken": "script-LSAM-Broken Names",       # Mismatched handles / Disappeared
    "damaged": "script-LSAM-DAMAGED",           # Toxic / Broken sync blocks
    "attention": "script-LSAM-Tier3-NeedAttention", # Tier 3 simulation debris
    "review": "script-LSAM-LinkedIn to Review"  # Ambiguity
}

def setup_logging(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(levelname)s: %(message)s'
    )

def analyze_contact(bridge: ContactMacOSBridge, contact: Dict[str, Any]) -> str:
    """Analyzes a contact's state and returns the recommended target group key."""
    details = bridge.get_contact_details(contact["id"])
    if not details["success"]:
        return "source" # Keep in source if we can't read it
    
    note = details.get("note", "")
    
    # Rule 1: Toxicity Check (Mismatched handle / Photo Reject)
    # Check for keywords that indicate major sync issues
    toxic_markers = ["Rejected: Low Quality", "Photo rejection", "handle mismatch", "Mismatched handle"]
    if any(m in note for m in toxic_markers):
        return "damaged"
        
    # Rule 2: Handle Verification
    # Check sync block in note (This is the source of truth for ventilation)
    sync_match = re.search(r"<Linkedin-AI-sync.*?</Linkedin-AI-sync>", note, re.DOTALL)
    if not sync_match:
        # No sync block and LinkedIn in note? Might be a new discovery candidate
        if "linkedin.com" in note.lower() or "linkedIn" in note:
            return "attention"
        return "damaged" # Refresh requested but no handle/block found
        
    # Rule 3: Disappeared Check
    if "Profile disappeared" in note or "no confirmed profile" in note:
        return "broken"
        
    # Rule 4: Broken Names (Legacy keyword check)
    if "⚠️ LSAM: Name Mismatch" in note:
        return "broken"
        
    # Rule 5: Tier 3 Debris
    if "Engaging Tier 3" in note and "Ready to Review" not in note:
        return "attention"
        
    # Default: Stays in Refresh (Valid bulk refresh)
    return "source"

def main():
    parser = argparse.ArgumentParser(description="LSAM Sorting Engine (Backlog Ventilation)")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without moving contacts")
    parser.add_argument("--full", action="store_true", help="Execute the moves")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--limit", type=int, help="Limit processing to N contacts (for testing)")
    
    args = parser.parse_args()
    setup_logging(args.debug)
    
    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    
    print(f"--- LSAM Ventilation Engine starting in {mode} mode ---")
    
    # 1. Fetch source backlog
    res = bridge.list_group_contacts(GROUPS["source"])
    if not res["success"]:
        print(f"Error: Could not list source group '{GROUPS['source']}': {res.get('error')}")
        return
        
    backlog = res["matches"]
    if args.limit:
        backlog = backlog[:args.limit]
        
    total = len(backlog)
    print(f"Found {total} contacts in {GROUPS['source']}.")
    
    # NEW: Bulk fetch notes to avoid 1444 osascript processes
    print("Bulk-extracting notes (Speed optimization)...")
    note_res = bridge.batch_get_group_notes(GROUPS["source"])
    if not note_res["success"]:
        print(f"Error: Could not bulk fetch notes: {note_res.get('error')}")
        return
    notes_map = note_res["notes"]
    
    distribution = {k: 0 for k in GROUPS.keys()}
    issue_stats = {
        "Ambiguity": 0,
        "Name Mismatch": 0,
        "Candidate (3rd Degree)": 0,
        "Low Mutuals": 0,
        "Photo Rejection": 0,
        "Broken Sync Block": 0,
        "Disappeared": 0
    }
    results = {k: [] for k in GROUPS.keys()}
    
    # 2. Process & Categorize
    for i, contact in enumerate(backlog):
        if i % 100 == 0:
            print(f"  Processed {i}/{total}...")
            
        # Get note from map instead of bridge call
        note = notes_map.get(contact["id"], "")
        
        # Inlined logic for speed
        category = "source"
        
        # Priority 1: Specific ⚠️ Markers
        if "⚠️ LSAM AMBIGUITY" in note:
            category = "review"
            issue_stats["Ambiguity"] += 1
        elif "⚠️ LSAM: Name Mismatch" in note:
            category = "broken"
            issue_stats["Name Mismatch"] += 1
        elif "⚠️ LSAM CANDIDATE" in note:
            category = "attention"
            issue_stats["Candidate (3rd Degree)"] += 1
        elif "0 mutual ⚠️" in note or "low count - verify" in note:
            category = "review"
            issue_stats["Low Mutuals"] += 1
        
        # Priority 2: Toxicity / Damage
        elif any(m in note for m in ["Rejected: Low Quality", "Photo rejection", "handle mismatch", "Mismatched handle"]):
            category = "damaged"
            issue_stats["Photo Rejection"] += 1
        elif "Profile disappeared" in note or "no confirmed profile" in note:
            category = "broken"
            issue_stats["Disappeared"] += 1
        elif not re.search(r"<Linkedin-AI-sync.*?</Linkedin-AI-sync>", note, re.DOTALL):
            if "linkedin.com" in note.lower() or "linkedIn" in note:
                category = "attention"
            else:
                category = "damaged"
                issue_stats["Broken Sync Block"] += 1
        
        distribution[category] += 1
        results[category].append(contact)
        
    # 3. Report
    print("\n--- Final Distribution ---")
    for key, count in distribution.items():
        name = GROUPS[key]
        print(f"  {name:30}: {count}")
        
    print("\n--- Detailed Issue Breakdown (⚠️ and Errors) ---")
    for issue, count in issue_stats.items():
        print(f"  {issue:30}: {count}")
        
    # 4. Execute
    if args.full:
        print("\n--- Executing Moves ---")
        for category, contacts in results.items():
            if category == "source": continue
            
            target_group = GROUPS[category]
            print(f"Moving {len(contacts)} contacts to {target_group}...")
            
            for contact in contacts:
                # Add to new group
                bridge.add_to_group(contact["id"], target_group)
                # Remove from source
                bridge.remove_from_group(contact["id"], GROUPS["source"])
    else:
        print("\nDry run complete. Use --full to execute moves.")

if __name__ == "__main__":
    main()
