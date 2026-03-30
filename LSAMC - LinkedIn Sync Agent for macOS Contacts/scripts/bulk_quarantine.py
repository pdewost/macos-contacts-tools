#!/usr/bin/env python3
"""
Bulk Group Mover
Version: 1.0.0
Purpose: Moves contacts to 'LinkedIn to Review' group.
"""

import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

QUARANTINE = [
    "Richard Grogan-Crane", "Yongki Min", "Damien GIOLITO", "ALAIN BENESTEAU",
    "Josephine Ceccaldi", "David Wu", "Anil C Kokaram", "Mehdi AMOUR", "Koumar Vijaya",
    "M Claude Sassoulas", "Me Florence Etheimer", "M Olivier FAUQUEUX", 
    "Herr Michael Clever", "M Louis-Gabriel de Causans",
    "M Benjamin Teszner", "M Frederic Vasnier", "François Lagunas", 
    "Mlle Bernadette Cromwell", "Giacomo Bersano", "M Michel GUILLEMET",
    "Me Charlotte Feraille", "Jean-Michel Piquemal", "M Benoit Deleury", "M jean-claude Mallet",
    "Jean-Pierre CASARA", "Giorgi Gurgenidze", "Gregory Yeakle", "Kimmo Myllymaki",
    "Anne Lhotellier", "Jean-Pierre BOKOBZA", "Alexandre Megret", "Ralph Eric Kunz", "Bruno CREMEL"
]

def main():
    bridge = ContactMacOSBridge(mode="FULL")
    target_group = "LinkedIn to Review"
    
    print(f"--- Bulk Quarantining {len(QUARANTINE)} contacts to '{target_group}' ---")
    
    for name in QUARANTINE:
        print(f"Moving: {name}")
        # AppleScript to add to group
        script = f'''
        tell application "Contacts"
            if not (exists group "{target_group}") then make new group with properties {{name:"{target_group}"}}
            set theGroup to group "{target_group}"
            set thePeople to people whose name contains "{name}"
            repeat with p in thePeople
                add p to theGroup
            end repeat
            save
            return "SUCCESS"
        end tell
        '''
        res = bridge._run_applescript(script)
        if res["success"] and "SUCCESS" in res["output"]:
            print(f"  ✅ {name} moved.")
        else:
            print(f"  ❌ Error moving {name}: {res.get('error') or res.get('output')}")

if __name__ == "__main__":
    main()
