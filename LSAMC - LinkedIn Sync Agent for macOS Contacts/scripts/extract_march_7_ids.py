#!/usr/bin/env python3
import os
import glob
import re

LOG_DIR = "logs/sessions/run_2026-03-07_*"

def extract_pairs():
    pairs = set()
    for log_file in glob.glob(os.path.join(LOG_DIR, "session.log")):
        with open(log_file, 'r', errors='ignore') as f:
            content = f.read()
            
            # Find all successes
            successes = re.findall(r"Sync Results for (.*?): SUCCESS", content)
            
            for name in successes:
                name_esc = re.escape(name)
                # Find all occurrences of name and ID in logs
                # Format 1: Proceeding with provided contact_id: <ID>
                # Format 2: Existing name '<Name>' is curated. Skipping name overwrite for <ID>.
                # Format 3: set p to person id "<ID>"
                
                # We'll split the file by "Syncing: " to isolate each contact session in the log
                sessions = content.split("Syncing: ")
                for session in sessions:
                    if re.match(fr"^{name_esc} \(LSAMC", session):
                        # This is our session! Look for ID in it.
                        id_match = re.search(r"contact_id: (.*?)(?:\s|\n|$)", session)
                        if not id_match:
                            id_match = re.search(r"overwrite for (.*?)\.", session)
                        if not id_match:
                            id_match = re.search(r'set p to person id "(.*?)"', session)
                        
                        if id_match:
                            cid = id_match.group(1).strip()
                            # Clean up if needed
                            if cid.endswith('.'): cid = cid[:-1]
                            pairs.add((name, cid))
                            break

    with open("/tmp/march_7_ids.txt", "w") as f:
        for name, cid in sorted(pairs):
            f.write(f"{name}|{cid}\n")
    print(f"Extracted {len(pairs)} Name/ID pairs.")

if __name__ == "__main__":
    extract_pairs()
