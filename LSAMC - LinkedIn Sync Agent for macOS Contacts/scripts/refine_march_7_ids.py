import os
import glob
import re

def refine_ids():
    sessions_root = "logs/sessions/run_2026-03-07_*"
    pairs = set()
    
    # Only process logs that were initialized in FULL mode
    for log_file in sorted(glob.glob(os.path.join(sessions_root, "session.log"))):
        with open(log_file, 'r', errors='ignore') as f:
            content = f.read()
            if "ContactMacOSBridge initialized in FULL mode" not in content:
                print(f"Skipping Simulation session: {os.path.basename(os.path.dirname(log_file))}")
                continue
            
            print(f"Processing LIVE session: {os.path.basename(os.path.dirname(log_file))}")
            
            sessions = content.split("Syncing: ")
            for session in sessions[1:]:
                # Extract contact name
                name_match = re.match(r"(.*?) \(LSAMC", session)
                if not name_match: continue
                name = name_match.group(1).split("\n")[0].strip()
                
                # Check for Sync Result SUCCESS
                if f"Sync Results for {name}: SUCCESS" in session:
                    # Look for ID in this specific session block
                    id_match = re.search(r"contact_id: (.*?)(?:\s|\n|$)", session)
                    if not id_match:
                        id_match = re.search(r"overwrite for (.*?)\.", session)
                    if not id_match:
                        id_match = re.search(r'set p to person id "(.*?)"', session)
                    
                    if id_match:
                        cid = id_match.group(1).strip()
                        if cid.endswith('.'): cid = cid[:-1]
                        pairs.add((name, cid))

    with open("/tmp/march_7_ids_fixed.txt", "w") as f:
        for name, cid in sorted(pairs):
            f.write(f"{name}|{cid}\n")
    
    print(f"Extracted {len(pairs)} Name/ID pairs from LIVE sessions.")

if __name__ == "__main__":
    refine_ids()
