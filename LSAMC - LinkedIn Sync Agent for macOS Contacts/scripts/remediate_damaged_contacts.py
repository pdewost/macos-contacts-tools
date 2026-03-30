#!/usr/bin/env python3
"""
Remediate Damaged Contacts (v4.8.1)
- Deletes invalid LinkedIn social profiles (handles with spaces) for 22 contacts.
- Explicit string conversion and type guards for AppleScript.
"""
import sys, os, argparse, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bridge.contact_macos import ContactMacOSBridge

parser = argparse.ArgumentParser()
parser.add_argument("--execute", action="store_true", help="Actually apply changes (default: dry-run)")
args = parser.parse_args()

mode = "FULL" if args.execute else "SIMULATION"
bridge = ContactMacOSBridge(mode=mode)

ALREADY_FIXED = {
    "BEF01E37-8B36-4574-9D43-DB321BCEDCE1:ABPerson",
    "D00752DC-739F-4E60-83F9-561AC3E201BF:ABPerson",
    "0C1556EC-0EBE-41DC-8CED-120E2CE8BC9F:ABPerson",
}

DAMAGED_IDS = {
    "A9A1D25D-46B6-4CD7-8C34-9842A6DF1E5A:ABPerson": "Me Charlotte HUET HERFRAY",
    "5AAD8225-41F7-49E2-9161-98F65DF6A9E5:ABPerson": "Jean-Pierre Bokobza",
    "B4388B04-5D21-40B3-AF87-C6BAC5D1150B:ABPerson": "Philippe Chuzel",
    "24193DB7-CB16-4E77-9947-33DB9B6506A7:ABPerson": "M Bertrand DIARD",
    "EC7A9EB5-1344-43AA-9F8E-16FA01B10125:ABPerson": "Me Anita Iriart-Sorhondo",
    "6DF4B96D-BEB4-486C-95BE-C46EF1990C22:ABPerson": "Me Meryem TOM",
    "1853E3DA-70C7-461E-8180-2B4580E56792:ABPerson": "Fiona Darmon",
    "E5AB4372-305A-4CE8-9C83-1B2F2485900A:ABPerson": "Andre Loechel",
    "9C205BE5-4C4D-4045-A701-94B8EA263AA4:ABPerson": "Me Nada VILLERMAIN-LECOLIER",
    "CEF0942D-47C5-4A5F-81CB-AC6593016801:ABPerson": "M Maxime PICAT",
    "D47804D8-41E8-4CD9-8B0D-02EC18DC22D0:ABPerson": "Lionel Baraban",
    "CE3690C7-E840-4923-9D36-C04387E35FA0:ABPerson": "M Bernard MALACHANE",
    "4159BA80-D68F-4AC7-9EF6-835581539B1C:ABPerson": "David Ring",
    "E8EDE0A9-17BB-404F-9983-DEAE5D7C4416:ABPerson": "Nicolas MOYNIER",
    "0C55B364-452D-4365-9D57-2C02E24FEC3D:ABPerson": "M Alexandre DELIVET",
    "0C4222EF-4987-4EB5-957E-34249F41C645:ABPerson": "Marc Knoll",
    "A22794DB-C0B6-46DD-9FD1-03354D0EBB4D:ABPerson": "M Pierre SAUREL",
    "E6223A47-E3A5-477E-8ED6-FEAEA90EDE7E:ABPerson": "M Philippe HUMEAU",
    "18797603-3FB6-4EA5-ABAC-20A8890B1739:ABPerson": "M Pierre AUBOUIN",
    "E2E1442D-CEA2-4520-A644-D0F5EDBB53E3:ABPerson": "Esteban Bayro-Kaiser",
    "7EB3A09A-6207-4271-A6EB-7C7D482F58AC:ABPerson": "Me Charlotte HUET HERFRAY (2nd)",
}

targets = {cid: name for cid, name in DAMAGED_IDS.items() if cid not in ALREADY_FIXED}

print(f"{'🔧 EXECUTE MODE' if args.execute else '👁 DRY-RUN MODE'}")
print(f"Targets: {len(targets)} contacts (skipping {len(ALREADY_FIXED)} already fixed)\n")

for cid, name in targets.items():
    print(f"--- {name} ({cid}) ---")
    
    if not args.execute:
        print(f"  [DRY-RUN] Would delete all LinkedIn social profiles with spaces")
        print(f"  [DRY-RUN] Would add to 'script-LSAM-Force-Refresh' group")
        continue
    
    # Step 1: Delete all LinkedIn social profiles that have spaces in the user name
    delete_script = f'''
    tell application "Contacts"
        set p to person id "{cid}"
        set socs to every social profile of p
        set deleted to 0
        repeat with i from (count of socs) to 1 by -1
            set s to item i of socs
            try
                set sn to service name of s
                set un to user name of s
                if (sn is not missing value) and (un is not missing value) then
                    set snS to sn as string
                    set unS to un as string
                    if (snS contains "LinkedIn") and (unS contains " ") then
                        delete s
                        set deleted to deleted + 1
                    end if
                end if
            on error
                -- Skip on error
            end try
        end repeat
        save
        return deleted as string
    end tell
    '''
    res = bridge._run_applescript(delete_script)
    if res.get("success"):
        count = res.get("output", "0")
        print(f"  ✅ Deleted {count} malformed LinkedIn social profile(s)")
    else:
        print(f"  ❌ Delete failed: {res.get('error')}")
    
    # Step 2: Add to group
    res2 = bridge.add_to_group(cid, "script-LSAM-Force-Refresh")
    if res2.get("success"):
        print(f"  ✅ Added to 'script-LSAM-Force-Refresh' group")
    else:
        print(f"  ❌ Group add failed: {res2.get('error')}")

print(f"\n{'🔧 EXECUTION COMPLETE' if args.execute else '👁 DRY-RUN COMPLETE — run with --execute to apply'}")
