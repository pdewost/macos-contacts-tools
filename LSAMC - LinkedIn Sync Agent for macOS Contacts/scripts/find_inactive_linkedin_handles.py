import logging
import re
from src.bridge.contact_macos import ContactMacOSBridge

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def find_inactive_handles():
    bridge = ContactMacOSBridge(mode="SIMULATION")
    
    # PHASE 1: Fast Bulk Fetch IDs
    logger.info("PHASE 1: Fetching ALL contact IDs from vault...")
    script_ids = 'tell application "Contacts" to return id of every person'
    res_ids = bridge._run_applescript(script_ids)
    if not res_ids["success"]:
        logger.error(f"Failed to fetch all IDs: {res_ids.get('error')}")
        return
        
    all_ids = [id.strip() for id in res_ids.get("output", "").split(", ") if id.strip()]
    num_contacts = len(all_ids)
    logger.info(f"Retrieved {num_contacts} total contacts. Processing for inactive LinkedIn handles...")

    error_contacts = []
    
    # PHASE 2: Batch process to avoid timeouts
    batch_size = 300
    for i in range(0, num_contacts, batch_size):
        batch_ids = all_ids[i:i+batch_size]
        logger.info(f"Scanning vault: batch {i//batch_size + 1}/{(num_contacts // batch_size) + 1}...")
        
        id_list_str = '{"' + '", "'.join(batch_ids) + '"}'
        script_batch = f'''
        set targetIds to {id_list_str}
        tell application "Contacts"
            set results to {{}}
            repeat with tid in targetIds
                try
                    set p to person id tid
                    
                    set socs to {{}}
                    repeat with s in social profiles of p
                         set sn to service name of s
                         if sn is "LinkedIn" then
                             set un to user name of s
                             if un is missing value then set un to ""
                             set surl to url of s
                             if surl is missing value then set surl to ""
                             set end of socs to "USER:" & un & "|URL:" & surl
                         end if
                    end repeat
                    
                    if (count of socs) > 0 then
                        set nm to name of p
                        if nm is missing value then set nm to ""
                        
                        set AppleScript's text item delimiters to "||SOC||"
                        set socStr to socs as string
                        set AppleScript's text item delimiters to ""
                        set end of results to tid & "|#|" & nm & "|#|" & socStr
                    end if
                on error
                    # skip silently
                end try
            end repeat
            return results
        end tell
        '''
        
        res_batch = bridge._run_applescript(script_batch)
        if not res_batch["success"]:
            logger.warning(f"Batch failed (maybe timeout): {res_batch.get('error')}")
            continue
            
        raw_outputs = res_batch.get("output", "").split(", ")
        for raw in raw_outputs:
            if not raw or "|#|" not in raw: continue
            parts = raw.split("|#|", 2)
            if len(parts) < 3: continue
            
            cid, nm, soc_str = parts[0], parts[1], parts[2]
            
            reasons = []
            if soc_str:
                soc_entries = soc_str.split("||SOC||")
                for entry in soc_entries:
                    if "USER:" in entry:
                        parts_soc = entry.split("|URL:")
                        u_p = parts_soc[0].replace("USER:", "").strip()
                        url_p = parts_soc[1].strip() if len(parts_soc) > 1 else ""
                        
                        if u_p:
                            if not u_p.startswith("http") or " " in u_p:
                                reasons.append(f"Invalid Username: '{u_p}'")
                        if url_p:
                            if not url_p.startswith("http") or " " in url_p:
                                reasons.append(f"Invalid URL: '{url_p}'")
                        if not u_p and not url_p:
                            reasons.append(f"Empty LinkedIn Profile")

            if reasons:
                error_contacts.append({
                    "id": cid,
                    "name": nm,
                    "reasons": list(set(reasons))
                })

    # Output generation
    if error_contacts:
        print(f"\n# 🚨 Inactive LinkedIn Handles Report\n")
        print(f"**Total contacts scanned:** {num_contacts}")
        print(f"**Contacts with errors:** {len(error_contacts)}\n")
        print("| Name | ID | Malformed Handle Details |")
        print("| :--- | :--- | :--- |")
        for c in error_contacts:
            print(f"| {c['name']} | `{c['id']}` | {', '.join(c['reasons'])} |")
    else:
        print(f"\n# ✅ Inactive LinkedIn Handles Report\n")
        print(f"**Total contacts scanned:** {num_contacts}")
        print("\nNo contacts matching error criteria found in the vault.")

if __name__ == "__main__":
    find_inactive_handles()
