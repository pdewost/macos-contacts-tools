import logging
import re
from src.bridge.contact_macos import ContactMacOSBridge

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

REPORT_OUTPUT = "logs/repeated_names_report.md"

def find_repeated_names():
    bridge = ContactMacOSBridge(mode="SIMULATION")
    
    logger.info("PHASE 1: Fetching ALL contact IDs from vault...")
    script_ids = 'tell application "Contacts" to return id of every person'
    res_ids = bridge._run_applescript(script_ids)
    if not res_ids["success"]:
        logger.error(f"Failed to fetch all IDs: {res_ids.get('error')}")
        return
        
    all_ids = [id.strip() for id in res_ids.get("output", "").split(", ") if id.strip()]
    num_contacts = len(all_ids)
    logger.info(f"Retrieved {num_contacts} total contacts. Scannings for repeated names...")

    suspicious_contacts = []
    
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
                    
                    set fn to first name of p
                    if fn is missing value then set fn to ""
                    set ln to last name of p
                    if ln is missing value then set ln to ""
                    set nm to name of p
                    if nm is missing value then set nm to ""
                    
                    set end of results to tid & "|#|" & fn & "|#|" & ln & "|#|" & nm
                on error
                    # skip silently
                end try
            end repeat
            
            set AppleScript's text item delimiters to "||||"
            set resStr to results as string
            set AppleScript's text item delimiters to ""
            return resStr
        end tell
        '''
        
        res_batch = bridge._run_applescript(script_batch)
        if not res_batch["success"]:
            logger.warning(f"Batch failed (maybe timeout): {res_batch.get('error')}")
            continue
            
        raw_outputs = res_batch.get("output", "").split("||||")
        for raw in raw_outputs:
            if not raw or "|#|" not in raw: continue
            parts = raw.split("|#|")
            if len(parts) < 4: continue
            
            cid, fn, ln, nm = parts[0], parts[1], parts[2], parts[3]
            fn_clean = fn.strip()
            ln_clean = ln.strip()
            nm_clean = nm.strip()
            
            reasons = []
            
            # Rule 1: First name appears twice in the full name string (case-insensitive check)
            if fn_clean and len(fn_clean) > 3:
                occurrences_fn = nm_clean.lower().count(fn_clean.lower())
                if occurrences_fn > 1:
                    reasons.append(f"First Name '{fn_clean}' is repeated")
                    
            # Rule 2: Last name appears twice in the full name string
            if ln_clean and len(ln_clean) > 3:
                occurrences_ln = nm_clean.lower().count(ln_clean.lower())
                if occurrences_ln > 1:
                    reasons.append(f"Last Name '{ln_clean}' is repeated")
                    
            # Rule 3: concatenated strings without spaces but with dots/camelcase matching name
            # Like Jean-Claude.Bourbon -> Check if fn_clean + "." + ln_clean is in nm_clean
            if fn_clean and ln_clean:
                dot_concat = f"{fn_clean}.{ln_clean}".lower()
                dash_concat = f"{fn_clean}-{ln_clean}".lower()
                nospace_concat = f"{fn_clean}{ln_clean}".lower()
                
                nm_lower = nm_clean.lower()
                if dot_concat in nm_lower or dash_concat in nm_lower or nospace_concat in nm_lower:
                     # But only flag if it's truly weird, e.g., the name is JUST the concatenated string
                     # Or if it's "Jean-Claude Jean-Claude.Bourbon"
                     if not " " in nm_clean and "." in nm_clean: # It's a single token with a dot
                          reasons.append(f"Name concatenated with dot: '{nm_clean}'")
                          
            # Deduplicate reasons
            reasons = list(set(reasons))
            
            if reasons:
                suspicious_contacts.append({
                    "id": cid,
                    "first": fn_clean,
                    "last": ln_clean,
                    "full": nm_clean,
                    "reasons": reasons
                })

    if suspicious_contacts:
        logger.info(f"Found {len(suspicious_contacts)} contacts with suspicious repeated names.")
        with open(REPORT_OUTPUT, "w") as f:
            f.write("# 📝 Suspicious Repeated Names Report\n\n")
            f.write(f"**Contacts scanned:** {num_contacts}\n")
            f.write(f"**Flagged contacts:** {len(suspicious_contacts)}\n\n")
            
            f.write("| First Name | Last Name | Full Name | ID | Flag Reason |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
            for c in suspicious_contacts:
                f.write(f"| {c['first']} | {c['last']} | {c['full']} | `{c['id']}` | {', '.join(c['reasons'])} |\n")
    else:
        logger.info("No suspicious repeated names found.")

if __name__ == "__main__":
    find_repeated_names()
