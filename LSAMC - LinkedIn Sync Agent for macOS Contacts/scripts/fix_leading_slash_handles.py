#!/usr/bin/env python3
"""
Fix the 3 contacts with leading // in their LinkedIn social profile.
Replaces the malformed handle with the correct slug.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

bridge = ContactMacOSBridge(mode="FULL")

FIXES = [
    {
        "id": "DED977C1-104E-482B-8C3E-31FD2067D7B1:ABPerson",
        "name": "Elisabeth MORENO",
        "good_handle": "elisabeth-s-moreno",
    },
    {
        "id": "1B5BA697-EB41-4838-9B13-FBE71707C241:ABPerson",
        "name": "Katia HARDOUIN",
        "good_handle": "katia-hardouin-6a3a3148",
    },
    {
        "id": "24557775-E266-404F-912E-145B42560EA8:ABPerson",
        "name": "Benoît MARICHEZ",
        "good_handle": "benoitmarichez",
    },
]

for fix in FIXES:
    cid = fix["id"]
    name = fix["name"]
    good = fix["good_handle"]
    
    print(f"--- Fixing {name} ({cid}) ---")
    
    script = f'''
    tell application "Contacts"
        set p to person id "{cid}"
        
        -- Delete ALL LinkedIn social profiles (to remove the malformed one)
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
        print(f"  ✅ Fixed with handle '{good}'")
    else:
        print(f"  ❌ Failed: {res.get('error')}")

print("\nDone.")
