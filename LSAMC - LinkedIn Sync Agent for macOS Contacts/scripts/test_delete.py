#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

bridge = ContactMacOSBridge(mode="FULL")
cid = "A9A1D25D-46B6-4CD7-8C34-9842A6DF1E5A:ABPerson"

test_script = f'''
tell application "Contacts"
    set p to person id "{cid}"
    set socs to every social profile of p
    set deleted to 0
    repeat with s in socs
        set sn to (service name of s) as string
        set un to (user name of s) as string
        if sn contains "LinkedIn" and un contains " " then
            delete s
            set deleted to deleted + 1
        end if
    end repeat
    save
    return "DELETED:" & deleted
end tell
'''
print(bridge._run_applescript(test_script))
