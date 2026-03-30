
import logging
import re
from src.bridge.contact_macos import ContactMacOSBridge

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def find_errors():
    bridge = ContactMacOSBridge(mode="SIMULATION")
    
    # PHASE 1: Fast Bulk Fetch IDs and Notes
    logger.info("PHASE 1: Fast Bulk Fetching IDs and Notes for all 14k contacts...")
    script_bulk = '''
    tell application "Contacts"
        set IDs to id of every person
        set Notes to note of every person
        
        set results to {}
        repeat with i from 1 to count of IDs
            set theNote to item i of Notes
            if theNote is missing value then set theNote to ""
            
            if theNote contains "<Linkedin-AI-sync" then
                set end of results to item i of IDs
            end if
        end repeat
        return results
    end tell
    '''
    # Wait, the repeat loop in AppleScript is still the slow part.
    # Actually, fetching Notes of every person can be slow too if Notes are large.
    
    # Better: Use the groups first, then maybe a slower "whose" only if needed.
    # But the group search ALREADY found 3 errors.
    
    # Let's try this optimized AppleScript:
    script_fast_tag = '''
    tell application "Contacts"
        return id of every person whose note contains "<Linkedin-AI-sync"
    end tell
    '''
    # If this times out, I'll stick to groups.
    
    logger.info("Fetching IDs of LSAM-tagged contacts (global search)...")
    res = bridge._run_applescript(script_fast_tag)
    if not res["success"]:
        logger.error(f"Global sync-tag search failed: {res.get('error')}")
        logger.info("Falling back to scanning LSAM-named groups...")
        # Fallback to the group script logic
        import scripts.find_lsam_errors_groups as groups_script
        groups_script.find_errors()
        return

    lsam_ids = [id.strip() for id in res.get("output", "").split(", ") if id.strip()]
    logger.info(f"Found {len(lsam_ids)} contacts with LSAM tag. Analyzing details...")
    
    error_contacts = []
    batch_size = 100
    for i in range(0, len(lsam_ids), batch_size):
        batch_ids = lsam_ids[i:i+batch_size]
        logger.info(f"Analyzing batch {i//batch_size + 1}/{(len(lsam_ids) // batch_size) + 1}...")
        
        id_list_str = '{"' + '", "'.join(batch_ids) + '"}'
        script_details = f'''
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
                    end repeat
                    repeat with u in urls of p
                        set val to value of u
                        if val contains "linkedin.com" then
                             set end of socs to "VAL:" & val
                        end if
                    end repeat
                    
                    set AppleScript's text item delimiters to "||SOC||"
                    set socStr to socs as string
                    set AppleScript's text item delimiters to ""
                    set end of results to tid & "|#|" & fn & "|#|" & ln & "|#|" & nm & "|#|" & jt & "|#|" & socStr
                on error
                    # skip
                end try
            end repeat
            return results
        end tell
        '''
        res_batch = bridge._run_applescript(script_details)
        if not res_batch["success"]: continue
        
        raw_outputs = res_batch.get("output", "").split(", ")
        for raw in raw_outputs:
            if "|#|" not in raw: continue
            parts = raw.split("|#|")
            if len(parts) < 6: continue
            cid, fn, ln, nm, jt, soc_str = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            
            reasons = []
            if not fn.strip() and not ln.strip():
                if not nm.strip() or nm.strip() in ["Unknown", "N/A", "M"]:
                    reasons.append("Missing first and last name")
            if jt.strip() and not fn.strip() and not ln.strip():
                jt_parts = jt.strip().split(" ")
                if len(jt_parts) >= 2:
                    if jt_parts[0][0].isupper() and jt_parts[-1][0].isupper():
                        reasons.append(f"Name likely in Job Title field: '{jt}'")
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
                             reasons.append(f"LinkedIn Username/URL has space: '{u_p}'")
                        if " " in url_p and url_p and not url_p.startswith("http"):
                             reasons.append(f"LinkedIn URL has space: '{url_p}'")

            if reasons:
                error_contacts.append({
                    "id": cid,
                    "name": nm,
                    "reasons": list(set(reasons))
                })

    if error_contacts:
        print(f"\n### Found {len(error_contacts)} contacts with LSAM errors:\n")
        print("| Name | ID | Errors |")
        print("| :--- | :--- | :--- |")
        for c in error_contacts:
            print(f"| {c['name']} | {c['id']} | {', '.join(c['reasons'])} |")
    else:
        print("\n✅ No contacts matching error criteria found.")

if __name__ == "__main__":
    find_errors()
