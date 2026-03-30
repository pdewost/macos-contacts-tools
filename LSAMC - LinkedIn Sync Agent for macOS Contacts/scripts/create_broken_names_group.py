#!/usr/bin/env python3
"""
Create 'script-LSAM-Broken Names' group and add the 23 repeated-name contacts.
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

bridge = ContactMacOSBridge(mode="FULL")
GROUP_NAME = "script-LSAM-Broken Names"
REPORT = os.path.join(os.path.dirname(__file__), "..", "logs", "repeated_names_report.md")

# Parse IDs from the report
contact_ids = []
with open(REPORT) as f:
    for line in f:
        m = re.search(r'`([A-F0-9\-]+:ABPerson)`', line)
        if m:
            contact_ids.append(m.group(1))

print(f"Found {len(contact_ids)} contact IDs from report.")

# Create group if it doesn't exist
groups_res = bridge.list_groups()
if groups_res["success"] and GROUP_NAME not in groups_res.get("groups", []):
    print(f"Creating group: {GROUP_NAME}")
    bridge._run_applescript(f'tell application "Contacts" to make new group with properties {{name:"{GROUP_NAME}"}}')
    bridge._run_applescript('tell application "Contacts" to save')

# Batch add
id_list_str = '{"' + '", "'.join(contact_ids) + '"}'
script = f'''
set targetIds to {id_list_str}
tell application "Contacts"
    set g to group "{GROUP_NAME}"
    repeat with tid in targetIds
        try
            set p to person id tid
            add p to g
        on error errMsg
        end try
    end repeat
    save
end tell
'''
res = bridge._run_applescript(script)
if res.get("success"):
    print(f"✅ Added {len(contact_ids)} contacts to '{GROUP_NAME}'")
else:
    print(f"❌ Failed: {res.get('error')}")
