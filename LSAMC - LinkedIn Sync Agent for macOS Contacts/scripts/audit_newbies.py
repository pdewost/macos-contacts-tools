import json
import os
import glob
import argparse
import subprocess
from datetime import datetime

PROJECT_ROOT = "/Users/pdewost/Documents/Personnel/Developpement/macOS Contacts Management/LSAMC - LinkedIn Sync Agent for macOS Contacts"
VAULT_CENSUS = os.path.join(PROJECT_ROOT, "data/vault_census.json")
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data/priority_newbies.json")

def normalize_path(path):
    return path.replace("Janvier 2026 - LinkedIn Sync Agent for macOS Contacts", "macOS Contacts Management/LSAM - LinkedIn Sync Agent for macOS Contacts")

def has_photo_in_vcf(vcf_path):
    if not os.path.exists(vcf_path): return False
    try:
        with open(vcf_path, 'r', errors='ignore') as f:
            content = f.read()
            return "PHOTO" in content
    except:
        return False

def is_already_synced(vcf_path):
    """Checks if the original vCard already contains a sync block."""
    if not os.path.exists(vcf_path): return False
    try:
        with open(vcf_path, 'r', errors='ignore') as f:
            content = f.read()
            # LSAM sync blocks contain the checkmark emoji or the tag
            return "✓ Synced" in content or "<Linkedin-AI-sync" in content
    except:
        return False

def filter_existing_photos(candidates):
    """Filters out candidates who already have an image in macOS Contacts."""
    if not candidates: return []
    
    # Split into chunks of 10 for stability and speed
    chunk_size = 10
    final_list = []
    
    for i in range(0, len(candidates), chunk_size):
        chunk = candidates[i:i + chunk_size]
        # Clean IDs and wrap in quotes for AppleScript list
        id_list = ", ".join([f'"{c["uuid"]}"' for c in chunk])
        
        # Use Foundation for JSON output (100% robust parsing)
        as_cmd = f'''
        use framework "Foundation"
        set cids to {{{id_list}}}
        set hasPhoto to {{}}
        tell application "Contacts"
            repeat with cid in cids
                set cidStr to contents of cid
                try
                   if image of person id cidStr is not missing value then
                       set end of hasPhoto to cidStr
                   end if
                end try
            end repeat
        end tell
        set jsonData to current application's NSJSONSerialization's dataWithJSONObject:hasPhoto options:0 |error|:(missing value)
        return (current application's NSString's alloc()'s initWithData:jsonData encoding:(current application's NSUTF8StringEncoding)) as text
        '''
        
        try:
            res = subprocess.check_output(["/usr/bin/osascript", "-e", as_cmd], timeout=60).decode('utf-8')
            has_photo_ids = json.loads(res)
            
            for c in chunk:
                if c["uuid"] not in has_photo_ids:
                    final_list.append(c)
                else:
                    print(f"Skipping {c['name']} (Already has macOS Photo)")
        except Exception as e:
            print(f"Subprocess error filtering photos: {e}")
            final_list.extend(chunk)
            
    return final_list

def main():
    if not os.path.exists(VAULT_CENSUS):
        print("Census not found.")
        return
        
    with open(VAULT_CENSUS, 'r') as f:
        census = json.load(f)
    
    results = []
    processed_ids = set()
    
    for key, info in census.items():
        if info.get('sync_count') == 1:
            for path in info.get('paths', []):
                norm_path = normalize_path(path)
                if not os.path.isdir(norm_path): continue
                
                # Check for profile.json to get the real UUID
                profile_path = os.path.join(norm_path, "profile.json")
                contact_uuid = None
                full_name = info.get('name') or key
                
                if os.path.exists(profile_path):
                    try:
                        with open(profile_path, 'r') as f:
                            p_data = json.load(f)
                            contact_uuid = p_data.get("_contact_id")
                            if p_data.get("full_name"):
                                full_name = p_data["full_name"]
                    except:
                        pass
                
                if not contact_uuid:
                    contact_uuid = info.get('id')
                
                if contact_uuid in processed_ids: continue

                files = os.listdir(norm_path)
                has_original_img = any("-original." in f or f.startswith("original.") for f in files if f.split('.')[-1].lower() in ['jpg', 'jpeg', 'heic', 'png'])
                has_linkedin_img = any("-linkedin-raw." in f or "-linkedin." in f or f.startswith("linkedin.") for f in files if f.split('.')[-1].lower() in ['jpg', 'jpeg', 'heic', 'png'])
                
                has_original_vcf_photo = False
                is_previously_synced = False
                for f in files:
                    if "original.vcf" in f:
                        vcf_p = os.path.join(norm_path, f)
                        if has_photo_in_vcf(vcf_p):
                            has_original_vcf_photo = True
                        if is_already_synced(vcf_p):
                            is_previously_synced = True
                        if has_original_vcf_photo and is_previously_synced:
                            break
                
                # REFINED CRITERIA (v0.7.5):
                # 1. Must HAVE a LinkedIn photo OR a profile.json (allow re-scrape of purged profiles)
                # 2. Must NOT have an original photo (neither file nor in vCard).
                # 3. Must NOT have been previously synced (no sync block in original vCard).
                if (has_linkedin_img or os.path.exists(profile_path)) and not has_original_img and not has_original_vcf_photo and not is_previously_synced:
                    results.append({
                        "name": full_name,
                        "uuid": contact_uuid,
                        "run": os.path.basename(os.path.dirname(norm_path))
                    })
                    processed_ids.add(contact_uuid)
                    break
    
    # NEW (v0.7.4): Filter against Live Contacts.app for existing photos
    print(f"Performing Live Filter against {len(results)} candidates...")
    results = filter_existing_photos(results)
    
    # Save to JSON for the Control Center
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Audit Complete. Exported {len(results)} high-confidence IDs to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
