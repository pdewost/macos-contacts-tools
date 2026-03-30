
import logging
import re
import time
from src.bridge.contact_macos import ContactMacOSBridge

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def find_errors():
    bridge = ContactMacOSBridge(mode="SIMULATION")
    
    # PHASE 1: Get only IDs first
    logger.info("PHASE 1: Fetching IDs of LSAM contacts...")
    script_ids = '''
    tell application "Contacts"
        set thePeople to every person whose note contains "<Linkedin-AI-sync"
        return id of thePeople
    end tell
    '''
    
    res = bridge._run_applescript(script_ids)
    if not res["success"]:
        logger.error(f"Failed to fetch IDs: {res.get('error')}")
        return

    all_ids = [id.strip() for id in res.get("output", "").split(", ") if id.strip()]
    num_contacts = len(all_ids)
    logger.info(f"Found {num_contacts} LSAM-linked contacts. Processing in batches...")

    if num_contacts == 0:
        return

    candidates_for_analysis = []

    # PHASE 2: Bulk fetch fields in batches of 100
    batch_size = 100
    for i in range(0, num_contacts, batch_size):
        batch_ids = all_ids[i:i+batch_size]
        logger.info(f"Processing batch {i//batch_size + 1}/{(num_contacts // batch_size) + 1}...")
        
        id_list_str = '{"' + '", "'.join(batch_ids) + '"}'
        script_batch = f'''
        set targetIds to {id_list_str}
        tell application "Contacts"
            set results to {{}}
            repeat with tid in targetIds
                try
                    set p to person id tid
                    set fn to first name of p
                    if fn is missing value then set fn to ""
                    set ln to last name of p
                    if ln is missing value then set ln to ""
                    set nm to name of p
                    if nm is missing value then set nm to ""
                    set jt to job title of p
                    if jt is missing value then set jt to ""
                    
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
                    repeat with u in urls of p
                        set val to value of u
                        if val contains "linkedin.com" then
                             set end of socs to "VAL:" & val
                        end if
                    end repeat
                    end repeat
                    
                    set AppleScript's text item delimiters to "||SOC||"
                    set socStr to socs as string
                    set AppleScript's text item delimiters to ""
                    
                    set end of results to tid & "|#|" & fn & "|#|" & ln & "|#|" & nm & "|#|" & jt & "|#|" & socStr
                on error
                    -- skip
                end try
            end repeat
            return results
        end tell
        '''
        
        res_batch = bridge._run_applescript(script_batch)
        if not res_batch["success"]:
            logger.warning(f"Batch failed: {res_batch.get('error')}")
            continue
            
        raw_outputs = res_batch.get("output", "").split(", ")
        for raw in raw_outputs:
            parts = raw.split("|#|")
            if len(parts) < 6: continue
            
            cid, fn, ln, nm, jt, soc_str = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            
            reasons = []
            
            # Error 1: No first nor last name
            if not fn.strip() and not ln.strip():
                if not nm.strip() or nm.strip() in ["Unknown", "N/A"]:
                    reasons.append("Missing first and last name")
            
            # Error 2: Name in Job Title
            if jt.strip() and not fn.strip() and not ln.strip():
                jt_parts = jt.strip().split(" ")
                if len(jt_parts) >= 2:
                    if jt_parts[0][0].isupper() and jt_parts[-1][0].isupper():
                        reasons.append(f"Name likely in Job Title field: '{jt}'")
            
            # Error 3: Social Profile space/not URL
            if soc_str:
                soc_entries = soc_str.split("||SOC||")
                for entry in soc_entries:
                    if "VAL:" in entry:
                        val = entry.split("VAL:")[1]
                        if " " in val and not val.startswith("http"):
                            reasons.append(f"LinkedIn URL has space and no protocol: '{val}'")
                    elif "USER:" in entry:
                        u_p = entry.split("|URL:")[0].replace("USER:", "")
                        url_p = entry.split("|URL:")[1] if "|URL:" in entry else ""
                        if " " in u_p and not u_p.startswith("http"):
                            reasons.append(f"LinkedIn Username has space: '{u_p}'")
                        if " " in url_p and url_p and not url_p.startswith("http"):
                            reasons.append(f"LinkedIn URL has space: '{url_p}'")

            if reasons:
                candidates_for_analysis.append({
                    "id": cid,
                    "name": nm,
                    "first": fn,
                    "last": ln,
                    "job": jt,
                    "reasons": list(set(reasons))
                })

    if candidates_for_analysis:
        print(f"\n### Found {len(candidates_for_analysis)} contacts with LSAM errors:\n")
        print("| Name | ID | Errors |")
        print("| :--- | :--- | :--- |")
        for c in candidates_for_analysis:
            print(f"| {c['name']} | {c['id']} | {', '.join(c['reasons'])} |")
    else:
        print("\n✅ No contacts matching error criteria found.")

if __name__ == "__main__":
    find_errors()
