import re
import subprocess
import json
from pathlib import Path

def run_applescript(script):
    process = subprocess.Popen(['osascript', '-e', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = process.communicate()
    return out.strip(), err.strip()

def extract_names_from_md(file_path):
    content = Path(file_path).read_text()
    # Matches lines like | Name | ... |
    matches = re.findall(r'\|\s*([^|]+?)\s*\|', content)
    # Filter out table headers and separators
    names = [m.strip() for m in matches if m.strip() and not re.match(r'^[\s:-]+$', m) and m.strip() not in ['Contact', 'Previous State', 'New State', 'Reason']]
    return names

def add_contacts_to_group(group_name, names):
    print(f"Adding contacts to group: {group_name}")
    # AppleScript to create group and add contacts
    # We do it in batches to avoid AppleScript hanging on huge commands
    batch_size = 50
    for i in range(0, len(names), batch_size):
        batch = names[i:i+batch_size]
        as_script = f'''
        tell application "Contacts"
            if not (exists group "{group_name}") then
                make new group with properties {{name:"{group_name}"}}
            end if
            set theGroup to group "{group_name}"
            '''
        for name in batch:
            # We use "whose name is" which matches the full name
            as_script += f'''
            try
                set thePersons to every person whose name is "{name}"
                repeat with p in thePersons
                    add p to theGroup
                end repeat
            on error
                -- ignore
            end try
            '''
        as_script += '\nsave\nend tell'
        run_applescript(as_script)
        print(f"  Processed {min(i+batch_size, len(names))}/{len(names)}...")

def main():
    root = Path("/Users/pdewost/Documents/Personnel/Developpement/macOS Contacts Management/LSAMC - LinkedIn Sync Agent for macOS Contacts")
    report_file = root / "logs/mutual_repairs_report.md"
    failures_file = root / "logs/mutual_repairs_failures.md"
    
    ok_names = extract_names_from_md(report_file)
    orphan_names = extract_names_from_md(failures_file)
    
    # Filter out N/A or empty if any
    ok_names = [n for n in ok_names if n and n != "N/A"]
    orphan_names = [n for n in orphan_names if n and n != "N/A"]
    
    print(f"Extracted {len(ok_names)} OK names and {len(orphan_names)} orphan names.")
    
    add_contacts_to_group("script-LSAM-7mars-formatOK", ok_names)
    add_contacts_to_group("script-LSAM-7mars-orphans", orphan_names)
    
    print("Done.")

if __name__ == "__main__":
    main()
