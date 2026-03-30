import logging
import re
import os
from src.bridge.contact_macos import ContactMacOSBridge

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

REPORT_PATH = "logs/inactive_handles_report.md"
OUTPUT_REPORT = "logs/damaged_contacts_fixes.md"
GROUP_NAME = "script-LSAM-DAMAGED"

def isolate_and_fix():
    if not os.path.exists(REPORT_PATH):
        logger.error(f"Cannot find the report at {REPORT_PATH}")
        return

    bridge = ContactMacOSBridge(mode="FULL") # Need FULL to create/add to group
    
    # Verify/Create Group
    groups_res = bridge.list_groups()
    if not groups_res["success"]:
        logger.error("Failed to list groups.")
        return
        
    all_groups = groups_res.get("groups", [])
    if GROUP_NAME not in all_groups:
        logger.info(f"Creating group: {GROUP_NAME}")
        # Assuming ContactMacOSBridge doesn't have an explicit create_group method,
        # we can do it via AppleScript directly here if needed.
        create_script = f'tell application "Contacts" to make new group with properties {{name:"{GROUP_NAME}"}}'
        res = bridge._run_applescript(create_script)
        
        # Save changes
        bridge._run_applescript('tell application "Contacts" to save')
        
    damaged_contacts = []
    
    with open(REPORT_PATH, "r") as f:
        lines = f.readlines()
        
    for line in lines:
        if line.startswith("| ") and not line.startswith("| Name") and not line.startswith("| :---"):
            parts = line.split("|")
            if len(parts) >= 4:
                name = parts[1].strip()
                cid_raw = parts[2].strip().replace("`", "")
                details = parts[3].strip()
                
                # Extract values from details like: "Invalid Username: 'somestring'"
                values = re.findall(r"'([^']*)'", details)
                
                keep = False
                for val in values:
                    # Filter logic:
                    # Discard if starts with www.
                    if val.startswith("www."):
                        continue
                    # Keep if starts with //
                    if val.startswith("//"):
                        keep = True
                        break
                    # Keep if it contains a space
                    if " " in val:
                        keep = True
                        break
                    # Else it's a single string with no spaces, so discard (it works)
                
                if keep:
                    damaged_contacts.append({
                        "name": name,
                        "id": cid_raw,
                        "values": values
                    })

    logger.info(f"Found {len(damaged_contacts)} contacts matching DAMAGED criteria.")
    
    # Batch add to group
    if damaged_contacts:
        logger.info("Batch adding to group...")
        id_list_str = '{"' + '", "'.join([c["id"] for c in damaged_contacts]) + '"}'
        batch_add_script = f'''
        set targetIds to {id_list_str}
        tell application "Contacts"
            set g to group "{GROUP_NAME}"
            repeat with tid in targetIds
                try
                    set p to person id tid
                    add p to g
                on error errMsg
                    # ignore error if already in group
                end try
            end repeat
            save
        end tell
        '''
        bridge._run_applescript(batch_add_script)
    
    with open(OUTPUT_REPORT, "w") as out:
        out.write("# 🛠 Damaged Contacts Suggested Fixes\n\n")
        out.write(f"Total isolated contacts added to `{GROUP_NAME}`: {len(damaged_contacts)}\n\n")
        
        for contact in damaged_contacts:
            cid = contact["id"]
            name = contact["name"]
            values = contact["values"]
            
            # Suggest Fixes
            out.write(f"### Contact: {name}\n")
            out.write(f"- **ID**: `{cid}`\n")
            
            for handle in values:
                if handle.startswith("//"):
                    out.write(f"- **Issue**: Leading slashes in handle -> `{handle}`\n")
                    out.write(f"  - **Suggested Fix**: Remove the leading slashes. Cleaned handle: `{handle.replace('//', '')}`. Update the social profile field to this value.\n")
                elif " " in handle:
                    out.write(f"- **Issue**: Space in handle indicating likely name leakage -> `{handle}`\n")
                    if name in ["N/A", "Unknown", "M"]:
                         out.write(f"  - **Suggested Fix**: This handle looks like a name. The contact name {name} is a placeholder. Suggest migrating `{handle}` into the First Name & Last Name fields, and removing it from the LinkedIn Social Profile.\n")
                    else:
                         out.write(f"  - **Suggested Fix**: A space implies a name or malformed URL. Suggest wiping this invalid LinkedIn social profile entirely, or searching LinkedIn using the contact's name to find the correct `linkedin.com/in/slug`.\n")
            out.write("\n")
            
    # Save the contacts DB
    bridge._run_applescript('tell application "Contacts" to save')
    logger.info(f"Done. Added contacts to '{GROUP_NAME}' and generated '{OUTPUT_REPORT}'.")

if __name__ == "__main__":
    isolate_and_fix()
