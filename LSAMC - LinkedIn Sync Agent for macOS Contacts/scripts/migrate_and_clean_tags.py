#!/usr/bin/env python3
"""
Optimized Cleanup Script:
1. Gets IDs of all contacts with the tag.
2. Processes them in batches to avoid AppleEvent timeouts.
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

bridge = ContactMacOSBridge(mode="FULL")

def get_tagged_ids():
    script = '''
    tell application "Contacts"
        set tagged_ids to id of every person whose note contains "#lsam-force-resync"
        return tagged_ids
    end tell
    '''
    res = bridge._run_applescript(script)
    if res.get("success"):
        output = res.get("output", "")
        if not output.strip(): return []
        return [i.strip() for i in output.split(", ")]
    return []

def process_batch(ids):
    # Construct AppleScript for this batch
    id_list_str = '", "'.join(ids)
    script = f'''
    tell application "Contacts"
        set target_group to "script-LSAM-Force-Refresh"
        if not (exists group target_group) then
            make new group with properties {{name:target_group}}
        end if
        
        set the_ids to {{"{id_list_str}"}}
        set cleaned to 0
        
        repeat with cid in the_ids
            try
                set p to person id cid
                set n to note of p
                if n is missing value then set n to ""
                
                -- Remove tag
                set new_note to n
                set tag to "#lsam-force-resync"
                if n contains tag then
                    -- Simple replacement
                    set AppleScript's text item delimiters to tag
                    set parts to text items of n
                    set AppleScript's text item delimiters to ""
                    set new_note to parts as string
                    set note of p to new_note
                end if
                
                add p to group target_group
                set cleaned to cleaned + 1
            on error
                -- Skip
            end try
        end repeat
        save
        return cleaned
    end tell
    '''
    res = bridge._run_applescript(script)
    return int(res.get("output", "0")) if res.get("success") else 0

print("🔍 Fetching tagged contact IDs...")
all_ids = get_tagged_ids()
print(f"Found {len(all_ids)} contacts to migrate.")

if all_ids:
    batch_size = 50
    total_cleaned = 0
    for i in range(0, len(all_ids), batch_size):
        batch = all_ids[i:i+batch_size]
        print(f"Processing batch {i//batch_size + 1}/{(len(all_ids)-1)//batch_size + 1} ({len(batch)} contacts)...")
        cleaned = process_batch(batch)
        total_cleaned += cleaned
        print(f"   Done. (Total cleaned: {total_cleaned})")
        time.sleep(1) # Brief pause to let Contacts breathe

    print(f"\n✅ Migration finished. Total cleaned: {total_cleaned}")
else:
    print("No tagged contacts found.")
