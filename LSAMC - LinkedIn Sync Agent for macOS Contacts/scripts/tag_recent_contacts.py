#!/usr/bin/env python3
"""
Find contacts modified or created in the last 10 days that have a LinkedIn handle,
and add them to the 'script-LSAM-Force-Refresh' group for priority processing.
"""
import sys, os, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

bridge = ContactMacOSBridge(mode="FULL")

# Target date: 10 days ago
three_weeks_ago_dt = datetime.now() - timedelta(days=10)

script = '''
with timeout of 600 seconds
    tell application "Contacts"
        set target_date to (current date) - (10 * days)
        
        -- Filter contacts modified recently
        set recent_contacts to every person whose modification date > target_date or creation date > target_date
        
        set tagged_count to 0
        set total_examined to count of recent_contacts
        
        -- Ensure group exists
        if not (exists group "script-LSAM-Force-Refresh") then
            make new group with properties {name:"script-LSAM-Force-Refresh"}
        end if
        
        repeat with p in recent_contacts
            try
                set has_linkedin to false
                set socs to social profiles of p
                repeat with s in socs
                    set sn to service name of s
                    if sn is not missing value and sn contains "LinkedIn" then
                        set has_linkedin to true
                        exit repeat
                    end if
                end repeat
                
                if has_linkedin then
                    add p to group "script-LSAM-Force-Refresh"
                    set tagged_count to tagged_count + 1
                end if
            on error
                -- Skip on error
            end try
        end repeat
        save
        return "EXAMINED:" & total_examined & "|ADDED:" & tagged_count
    end tell
end timeout
'''

print(f"Scanning for contacts modified/created since {three_weeks_ago_dt.strftime('%Y-%m-%d')} with a LinkedIn handle...")
res = bridge._run_applescript(script)

if res.get("success"):
    output = res.get("output", "")
    examined = output.split("EXAMINED:")[1].split("|")[0] if "EXAMINED:" in output else "0"
    tagged = output.split("ADDED:")[1] if "ADDED:" in output else "0"
    print(f"✅ Scanning complete.")
    print(f"   Examined {examined} recent contacts.")
    print(f"   Added {tagged} contacts to 'script-LSAM-Force-Refresh'")
else:
    print(f"❌ Failed: {res.get('error')}")
