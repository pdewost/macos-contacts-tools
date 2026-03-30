#!/usr/bin/env python3
import sys
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.bridge.contact_macos import ContactMacOSBridge

# Configuration
MIGRATION_MAP = {
    # Source Group -> Destination Group
    "script-LSAM-Tier2-NoteHasLinkedIn": "script-LSAM-Tier3-NeedAttention",
    "script-LSAM-Cleanup-Mutuals": "script-LSAM-Tier3-NeedAttention",
    "script-LSAM-Force-Refresh": "script-LSAM-Tier3-NeedAttention"
}

def main():
    bridge = ContactMacOSBridge(mode="FULL")
    
    # 1. Ensure Destination Group Exists
    dest_group = "script-LSAM-Tier3-NeedAttention"
    # We assume it exists or the bridge will create it/handle it, but good to check.
    # The bridge methods usually handle existence or we can just add to it.

    for source_grp, target_grp in MIGRATION_MAP.items():
        logger.info(f"--- Processing Group: {source_grp} ---")
        
        # A. List Contacts in Source
        res = bridge.list_group_contacts(source_grp)
        if not res.get("success"):
            logger.warning(f"Could not list group {source_grp}: {res.get('error')}")
            # If group doesn't exist, we might get an error, which is fine, we just skip
            continue
            
        contacts = res.get("matches", [])
        count = len(contacts)
        logger.info(f"Found {count} contacts in '{source_grp}'.")
        
        if count > 0:
            # B. Add to Target
            logger.info(f"Migrating {count} contacts to '{target_grp}'...")
            
            # We can use add_contacts_to_group. It takes a list of identifiers (names or IDs).
            # The bridge's add_contact_to_group (singular) might be slower for batch.
            # Let's see if there is a batch method or we iterate.
            # Looking at previous usage, we often iterate or use a helper. 
            # The bridge has `add_to_group(group_name, contact_id)`.
            
            # ContactMacOSBridge usually returns objects with 'id'.
            success_count = 0
            for c in contacts:
                c_id = c.get("id")
                if not c_id:
                    logger.warning(f"Skipping contact without ID: {c.get('name')}")
                    continue
                
                # Add to target
                # FIX: add_to_group takes (contact_id, group_name)
                add_res = bridge.add_to_group(c_id, target_grp)
                if add_res.get("success"):
                    success_count += 1
                else:
                    logger.error(f"Failed to move {c.get('name')} to {target_grp}: {add_res.get('error')}")
            
            logger.info(f"Successfully added {success_count}/{count} contacts to '{target_grp}'.")

        # C. Delete Source Group
        logger.info(f"Deleting group '{source_grp}'...")
        del_res = delete_group(bridge, source_grp)
        if del_res.get("success"):
            logger.info(f"Changes applied: Deleted '{source_grp}'.")
        else:
            logger.error(f"Failed to delete '{source_grp}': {del_res.get('error')}")

    print("\nCleanup Complete.")

def delete_group(bridge, group_name):
    """Deletes a group via AppleScript."""
    script = f'''
    tell application "Contacts"
        if exists group "{group_name}" then
            delete group "{group_name}"
            save
            return "DELETED"
        else
            return "NOT_FOUND"
        end if
    end tell
    '''
    res = bridge._run_applescript(script)
    if res.get("success") and res.get("output") == "DELETED":
         return {"success": True}
    elif res.get("success") and res.get("output") == "NOT_FOUND":
         return {"success": False, "error": "Group not found"}
    return res

if __name__ == "__main__":
    main()
