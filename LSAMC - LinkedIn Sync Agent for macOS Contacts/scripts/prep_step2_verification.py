#!/usr/bin/env python3
"""
LSAM Step 2 Degree Verification
Version: 1.0.0
Purpose: Verifies the connection degree for Category A contacts.
Promotes 1st degree contacts to Category B (Safe Reset).
Quarantines true non-1st degree as "Wrong Horse".
"""

import sys
import os
import re
import json
from typing import List, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

# Path to the Audit v2 results log
AUDIT_LOG_PATH = "logs/identity_audit_v2.log"

def extract_cat_a_contacts(file_path: str) -> List[Dict[str, str]]:
    contacts = []
    try:
        with open(file_path, "r") as f:
            for line in f:
                if "[A (Mismatch)]" in line:
                    # Format: [A (Mismatch)] Name | Handle: handle | Reason: reason
                    try:
                        parts = line.split(" | ")
                        name = parts[0].replace("[A (Mismatch)]", "").strip()
                        handle = parts[1].replace("Handle: ", "").strip()
                        reason = parts[2].replace("Reason: ", "").strip()
                        
                        # Prioritize Asymmetric or Mega-Horse
                        priority = "HIGH" if ("Asymmetric" in reason or "Mega-Horse" in reason) else "NORMAL"
                        
                        if handle != "None":
                            contacts.append({
                                "name": name,
                                "handle": handle,
                                "reason": reason,
                                "priority": priority
                            })
                    except:
                        continue
    except Exception as e:
        print(f"Error parsing log: {e}")
    return contacts

def main():
    print("--- Step 2: Degree Verification Prep ---")
    contacts = extract_cat_a_contacts(AUDIT_LOG_PATH)
    print(f"Loaded {len(contacts)} Category A candidates.")
    
    # Save the checklist for the browser subagent
    checklist_path = "data/step2_verification_checklist.json"
    with open(checklist_path, "w") as f:
        json.dump(contacts, f, indent=2)
    
    print(f"\nCreated verification checklist: {checklist_path}")
    print("Ready to launch browser subagent for degree checks.")

if __name__ == "__main__":
    main()
