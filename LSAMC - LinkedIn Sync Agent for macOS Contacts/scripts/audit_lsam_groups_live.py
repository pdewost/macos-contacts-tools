#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.bridge.contact_macos import ContactMacOSBridge

def main():
    bridge = ContactMacOSBridge(mode="FULL")
    print("--- Current LSAM / script Groups ---")
    
    # We don't have a 'list_all_groups' method exposed directly in the bridge typically,
    # or it might be inefficient. Let's try to find a way to list names.
    # The bridge usually has methods to list contacts IN a group, but maybe not list groups themselves?
    # Let's check the bridge code via grep or view if needed, but for now I'll use AppleScript injection
    # which is reliable for this specific query.
    
    script = '''
    tell application "Contacts"
        set nList to name of every group
        return nList
    end tell
    '''
    
    try:
        res = bridge._run_applescript(script)
        print(f"DEBUG: Raw response type: {type(res)}")
        print(f"DEBUG: Raw response content: {res}")
        
        # Handle if it's a dict containing the output
        if isinstance(res, dict):
             # Bridge sometimes returns {'value': '...'} or {'output': ...}
             val = res.get('value') or res.get('output')
             if val is None and 'data' in res: val = res['data']
        else:
             val = res

        if isinstance(val, list):
            groups = val
        elif isinstance(val, str):
            groups = [g.strip() for g in val.split(',')]
        else:
            groups = []

        count = 0
        for g in groups:
            if isinstance(g, str) and ("LSAM" in g or "script" in g.lower()):
                print(f"- {g}")
                count += 1
        print(f"\nTotal matching groups found: {count}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
