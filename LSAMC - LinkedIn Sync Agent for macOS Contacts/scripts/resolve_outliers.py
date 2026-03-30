#!/usr/bin/env python3
"""
LSAM Outlier Resolution & Promotion
Version: 1.0.0
Purpose: Performs a targeted surgical reset for the 8 Cat B outliers 
and manual promotion for confirmed 1st degrees (Gaëlle).
"""

import sys
import os
import re

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

# TARGETS
CAT_B_OUTLIERS = [
    "Didier Benchimol", "Delphine Fauvage de Surville", "Valérie Balavoine",
    "Guillaume de Marcillac", "Loïc Le Moaligou", "Brendan McGarvey",
    "Frédéric Roullier", "Christine Landrevot"
]

CONFIRMED_PROMOTIONS = [
    "Gaëlle PICARD-ABEZIS"
]

def wash_note(note: str) -> str:
    """Removes the legacy sync block from a note."""
    if not note: return ""
    # Remove <Linkedin-AI-sync>...</Linkedin-AI-sync>
    clean = re.sub(r'<Linkedin-AI-sync.*?</Linkedin-AI-sync>', '', note, flags=re.DOTALL).strip()
    # Also remove the force-resync tag if present
    clean = clean.replace("#lsam-force-resync", "").strip()
    return clean

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LSAM Outlier Resolution")
    parser.add_argument("--full", action="store_true", help="Perform actual note update")
    args = parser.parse_args()

    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    all_targets = CAT_B_OUTLIERS + CONFIRMED_PROMOTIONS
    
    print(f"--- Resolving {len(all_targets)} Outliers & Promotions (Mode: {mode}) ---")
    
    for name in all_targets:
        print(f"Processing: {name}")
        # Find person (using loose search in find_contact)
        res = bridge.find_contact(name)
        if not res["success"]:
             print(f"  ❌ Could not find contact: {name}")
             continue
            
        if "matches" in res:
            contact_id = res["matches"][0]["id"]
        else:
            contact_id = res["id"]
        
        # Get current details
        details_res = bridge.get_contact_details(contact_id)
        if not details_res["success"]:
            print(f"  ❌ Error fetching details for {name}")
            continue
            
        current_note = details_res["note"]
        
        if "<Linkedin-AI-sync" not in current_note:
            print(f"  ⚠️ No sync block found for {name}. Already clean?")
            continue
            
        # Wash Note
        new_note = wash_note(current_note)
        
        # Update Note (Washed)
        print(f"  ✅ Washing note for {name}...")
        update_res = bridge.update_note(contact_id, new_note)
        if not update_res["success"]:
            print(f"  ❌ Failed to update note for {name}: {update_res.get('error')}")
        else:
            print(f"  ✨ Success: {name} record cleaned.")

if __name__ == "__main__":
    main()
