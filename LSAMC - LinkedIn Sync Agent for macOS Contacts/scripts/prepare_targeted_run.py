
import subprocess
import re
import sys
import logging
from typing import List, Dict, Optional

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("TargetedRun")

# Target Group to Populate
TARGET_QUEUE_GROUP = "script-LSAM-Force-Refresh"
SOURCE_GROUP = "no photo LinkedIn 1 line note"
# SOURCE_GROUP = "script - no photo and on LinkedIn" # Backup option if first one fails/is empty

def run_applescript(script: str) -> str:
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, check=True
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"AppleScript Error: {e.stderr}")
        return ""

def get_contacts_from_group(group_name: str) -> List[Dict]:
    logger.info(f"Fetching contacts from '{group_name}'...")
    
    # We need ID, Name, Note, Image Status
    # Using AppleScript to get raw data. 
    # Warning: Large groups might timeout.
    
    script = f'''
    tell application "Contacts"
        set g to group "{group_name}"
        set output to ""
        repeat with p in people of g
            set pid to id of p
            set pname to name of p
            set pnote to note of p
            if pnote is missing value then set pnote to ""
            
            set hasImage to false
            if image of p is not missing value then set hasImage to true
            
            set output to output & pid & "|" & pname & "|" & hasImage & "|" & pnote & "\\n"
        end repeat
        return output
    end tell
    '''
    
    raw = run_applescript(script)
    contacts = []
    
    for line in raw.split('\n'):
        if not line.strip(): continue
        parts = line.split('|')
        if len(parts) < 4: continue
        
        # Re-assemble note if it contained pipes (unlikely but possible)
        note = "|".join(parts[3:])
        
        contacts.append({
            "id": parts[0],
            "name": parts[1],
            "has_image": parts[2] == "true",
            "note": note,
            "last_name": parts[1].split()[-1] if parts[1] else "" # Crude last name sort
        })
        
    logger.info(f"Fetched {len(contacts)} contacts.")
    return contacts

def sort_and_filter(contacts: List[Dict]) -> List[Dict]:
    filtered = []
    
    # 1. Filter: Exclude contacts that have a photo
    for c in contacts:
        if c["has_image"]: 
            continue # User said "excluding contacts that have a photo"
        filtered.append(c)
        
    logger.info(f"Filtered down to {len(filtered)} contacts (No Photo).")
    
    # 2. Sort
    # - First: No sync block
    # - Second: Has sync block
    # - Within each: Sorted by Last Name
    
    start_marker = "--- LINKEDIN SYNC AGENT ---"
    
    no_sync = []
    has_sync = []
    
    for c in filtered:
        if start_marker in c["note"]:
            has_sync.append(c)
        else:
            no_sync.append(c)
            
    # Sort by Name (Last Name approximation)
    no_sync.sort(key=lambda x: x["last_name"])
    has_sync.sort(key=lambda x: x["last_name"])
    
    logger.info(f"Sorting Strategy: {len(no_sync)} without sync block, {len(has_sync)} with sync block.")
    
    return no_sync + has_sync

def add_to_queue(contacts: List[Dict]):
    logger.info(f"Adding {len(contacts)} contacts to '{TARGET_QUEUE_GROUP}'...")
    
    # Batch addition failed with type errors.
    # Fallback: Add one by one using a simple loop. 
    # It's 200 items, so it might take 10-20 seconds but it's safe.
    
    success_count = 0
    fail_count = 0
    
    for i, c in enumerate(contacts):
        try:
            # We use a simple script for each one to isolate failures
            script = f'''
            tell application "Contacts"
                add person id "{c['id']}" to group "{TARGET_QUEUE_GROUP}"
                save
            end tell
            '''
            # result is ignored unless it throws
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            success_count += 1
            if i % 10 == 0:
                print(f"Progress: {i}/{len(contacts)}...", end='\r', flush=True)
        except subprocess.CalledProcessError:
            fail_count += 1
            logger.warning(f"Failed to add {c['name']} ({c['id']})")
            
    print(f"Queueing Complete: {success_count} added, {fail_count} failed.")

def main():
    # 1. Fetch
    raw_list = get_contacts_from_group(SOURCE_GROUP)
    
    # 2. Process
    final_list = sort_and_filter(raw_list)
    
    if not final_list:
        logger.warning("No contacts found matching criteria.")
        return

    print(f"Ready to queue {len(final_list)} contacts.")
    print("Top 5 candidates:")
    for c in final_list[:5]:
        print(f"- {c['name']} (Has Sync: {'Yes' if '--- LINKEDIN SYNC AGENT ---' in c['note'] else 'No'})")
        
    confirm = input(f"Proceed adding to {TARGET_QUEUE_GROUP}? [y/N]: ")
    if confirm.lower() == 'y':
        add_to_queue(final_list)
        print("Done. Start the supervisor to process.")
    else:
        print("Aborted.")

if __name__ == "__main__":
    main()
