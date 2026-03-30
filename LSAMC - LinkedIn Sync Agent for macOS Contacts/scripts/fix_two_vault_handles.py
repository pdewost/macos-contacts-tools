#!/usr/bin/env python3
"""
Step 1: Reinstate valid LinkedIn handles for Jean-Claude Bourbon and Bruno Dedieu.
For each contact:
  1. Delete the invalid social profile (the one with spaces)
  2. Add the correct social profile with the valid vault handle
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

bridge = ContactMacOSBridge(mode="FULL")

FIXES = [
    {
        "id": "BEF01E37-8B36-4574-9D43-DB321BCEDCE1:ABPerson",
        "name": "Jean-Claude Bourbon",
        "bad_handle": "Jean-Claude Jean-Claude.Bourbon",
        "good_handle": "jean-claude-jean-claude-bourbon-423b0072",
    },
    {
        "id": "D00752DC-739F-4E60-83F9-561AC3E201BF:ABPerson",
        "name": "BRUNO DEDIEU",
        "bad_handle": "Dedieu Bruno",
        "good_handle": "bruno-dedieu-740460117",
    },
]

for fix in FIXES:
    cid = fix["id"]
    name = fix["name"]
    bad = fix["bad_handle"].replace('"', '\\"')
    good = fix["good_handle"]
    
    print(f"--- Fixing {name} ({cid}) ---")
    
    # 1. Delete ALL LinkedIn social profiles with the bad handle, then add the good one
    script = f'''
    tell application "Contacts"
        set p to person id "{cid}"
        
        -- Delete invalid LinkedIn social profiles
        set socs to every social profile of p
        repeat with i from (count of socs) to 1 by -1
            set s to item i of socs
            try
                set sn to service name of s
                if sn is missing value then set sn to ""
                if sn contains "LinkedIn" then
                    delete s
                end if
            end try
        end repeat
        
        -- Add the correct handle
        make new social profile at end of social profiles of p with properties {{service name:"LinkedIn", user name:"{good}"}}
        
        save
        return "SUCCESS"
    end tell
    '''
    
    res = bridge._run_applescript(script)
    if res.get("success"):
        print(f"  ✅ Replaced bad handle with '{good}'")
    else:
        print(f"  ❌ Failed: {res.get('error')}")

print("\nDone.")
