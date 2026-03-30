#!/usr/bin/env python3
"""
LSAM Vault Purge Utility (v0.7.5)
----------------------------------
Scans for "poisoned" identities where the owner's photo (Philippe Dewost) 
was incorrectly captured instead of the target's.
Signature: C4E03AQEvtF7Fr5H4ew
"""

import os
import json
from pathlib import Path

# The signature of the owner's photo found in the vault
BAD_SIGNATURE = "C4E03AQEvtF7Fr5H4ew"

VAULT_ROOT = Path("/Users/pdewost/Documents/Personnel/Developpement/macOS Contacts Management/LSAMC - LinkedIn Sync Agent for macOS Contacts/data/vault")

def purge_folder(folder):
    """Purges poisoned files from a folder and resets profile.json."""
    poisoned = False
    pfile = folder / "profile.json"
    
    if not pfile.exists():
        return False

    try:
        pdata = json.loads(pfile.read_text())
        photo_url = pdata.get("photo_url", "")
        if photo_url and BAD_SIGNATURE in photo_url:
            poisoned = True
    except Exception as e:
        print(f"Error reading {pfile}: {e}")
        return False

    if poisoned:
        print(f"POISONED: {folder.name}")
        
        # 1. Delete all photo candidates
        for ext in ["*.heic", "*.jpg", "*.png", "*-linkedin-raw.jpg", "*-linkedin.heic"]:
            for f in folder.glob(ext):
                print(f"  - Deleting bad photo: {f.name}")
                f.unlink()
        
        # 2. Delete .applied flag (must re-sync)
        applied = folder / ".applied"
        if applied.exists():
            print(f"  - Deleting .applied flag")
            applied.unlink()
            
        # 3. Reset profile.json
        pdata["photo_url"] = None
        # Also clear any photo status markers if they exist
        if "_photo_status" in pdata:
            pdata["_photo_status"] = None
            
        pfile.write_text(json.dumps(pdata, indent=2))
        print(f"  - Reset profile.json")
        return True
    
    return False

def main():
    if not VAULT_ROOT.exists():
        print(f"Vault root not found: {VAULT_ROOT}")
        return

    count = 0
    # 1. Active Vault
    for item in VAULT_ROOT.iterdir():
        if item.is_dir() and item.name != "archived":
            if purge_folder(item):
                count += 1
                
    # 2. Archived Vault
    arch_root = VAULT_ROOT / "archived"
    if arch_root.exists():
        for session in arch_root.iterdir():
            if session.is_dir():
                for item in session.iterdir():
                    if item.is_dir():
                        if purge_folder(item):
                            count += 1

    print(f"\n--- PURGE COMPLETE ---")
    print(f"Poisoned identities reset: {count}")

if __name__ == "__main__":
    main()
