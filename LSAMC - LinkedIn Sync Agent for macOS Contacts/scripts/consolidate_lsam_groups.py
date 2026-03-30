#!/usr/bin/env python3
"""
scripts/consolidate_lsam_groups.py

Consolidates contacts from legacy LSAM review groups into the single active group:
'script-LSAM-LinkedIn to Review'.

Legacy Groups to Migrate & Remove:
- LSAM-LinkedIn To Review
- LSAM LinkedIn Review

Legacy Groups to Remove (if empty):
- script-LSAM-Tier1-Handle
- script-LSAM-Tier2-NoteHasLinkedIn
"""

import sys
import os
import logging

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bridge.contact_macos import ContactMacOSBridge

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GroupConsolidation")

TARGET_GROUP = "script-LSAM-LinkedIn to Review"

LEGACY_MIGRATION_MAP = {
    "LSAM-LinkedIn To Review": TARGET_GROUP,
    "LSAM LinkedIn Review": TARGET_GROUP
}

LEGACY_DELETION_LIST = [
    "script-LSAM-Tier1-Handle",
    "script-LSAM-Tier2-NoteHasLinkedIn"
]

def main():
    bridge = ContactMacOSBridge(mode="FULL")
    print("\n--- Starting LSAM Group Consolidation ---\n")

    # 1. Migration Phase
    for source, target in LEGACY_MIGRATION_MAP.items():
        logger.info(f"Checking legacy group: '{source}'...")
        
        # Check if source exists and has members
        res = bridge.list_group_contacts(source)
        if not res.get("success"):
            logger.info(f"  -> Group '{source}' not found or error accessing. Skipping.")
            continue
            
        members = res.get("matches", [])
        count = len(members)
        
        if count == 0:
            logger.info(f"  -> Group '{source}' is empty. Scheduling for deletion.")
        else:
            logger.info(f"  -> Found {count} contacts in '{source}'. Migrating to '{target}'...")
            
            # Add to target
            for contact in members:
                cid = contact["id"]
                name = contact.get("name", "Unknown")
                logger.debug(f"     Moving {name} ({cid})...")
                
                # Add to Target
                add_res = bridge.add_to_group(cid, target)
                if not add_res:
                    logger.error(f"     FAILED to add {name} to '{target}'. Skipping removal.")
                    continue
                    
                # Remove from Source
                bridge.remove_from_group(cid, source)
                
            logger.info(f"  -> Migration complete for '{source}'.")

        # Delete the group if empty (now or originally)
        # Verify empty before deleting
        check = bridge.list_group_contacts(source)
        if check.get("success") and len(check.get("matches", [])) == 0:
            logger.info(f"  -> Deleting empty group '{source}'...")
            # Note: ContactMacOSBridge doesn't have a direct 'delete_group' method exposed via Python wrapper usually.
            # We will use AppleScript directly via the bridge's internal runner if possible, 
            # or just inform user to delete it if the bridge lacks the method.
            
            # Using _run_applescript for direct Group deletion
            escaped_source = source.replace('"', '\\"')
            script = f'''
            tell application "Contacts"
                try
                    delete group "{escaped_source}"
                    return "DELETED"
                on error
                    return "FAILED"
                end try
            end tell
            '''
            res = bridge._run_applescript(script)
            if "DELETED" in str(res):
                logger.info(f"  -> ✅ Group '{source}' deleted.")
            else:
                logger.warning(f"  -> ⚠️ Could not delete group '{source}'. Please remove manually.")
        else:
             logger.warning(f"  -> Group '{source}' is not empty! Skipping deletion.")

    # 2. Cleanup Phase (Tiers)
    print("\n--- Checking Deprecated Tier Groups ---\n")
    for group in LEGACY_DELETION_LIST:
        logger.info(f"Checking '{group}'...")
        res = bridge.list_group_contacts(group)
        
        # If group doesn't exist, we are good
        if not res.get("success") and "No group found" in str(res.get("error", "")):
             logger.info(f"  -> Group '{group}' does not exist.")
             continue
             
        members = res.get("matches", [])
        if len(members) == 0:
            logger.info(f"  -> '{group}' is empty. Deleting...")
            escaped_group = group.replace('"', '\\"')
            script = f'''
            tell application "Contacts"
                try
                    delete group "{escaped_group}"
                    return "DELETED"
                on error
                    return "FAILED"
                end try
            end tell
            '''
            bridge._run_applescript(script)
            logger.info(f"  -> ✅ Group '{group}' deleted.")
        else:
            logger.warning(f"  -> ⚠️ Group '{group}' has {len(members)} contacts! SKIPPING DELETION. Please review manually.")

    print("\n--- Consolidation Complete ---\n")

if __name__ == "__main__":
    main()
