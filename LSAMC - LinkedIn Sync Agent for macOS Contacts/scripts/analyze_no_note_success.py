import os
import glob
import re

def analyze_sessions():
    sessions_root = "logs/sessions/run_2026-03-07_*"
    for log_file in sorted(glob.glob(os.path.join(sessions_root, "session.log"))):
        with open(log_file, 'r', errors='ignore') as f:
            content = f.read()
            # Split by individual contact sync sessions
            sessions = content.split("Syncing: ")
            for session in sessions[1:]: # Skip the pre-sync part
                # Extract contact name
                name_match = re.match(r"(.*?) \(LSAMC", session)
                if not name_match: continue
                name = name_match.group(1).split("\n")[0].strip()
                
                # Check for Sync Result
                if "Sync Results for " + name + ": SUCCESS" in session:
                    # Check for note update
                    if "set note of p to" not in session:
                        print(f"Name: {name} (SUCCESS, but no note update in {os.path.basename(os.path.dirname(log_file))})")
                elif "Sync Results for " + name + ":" in session:
                    # Not a success
                    pass

if __name__ == "__main__":
    analyze_sessions()
