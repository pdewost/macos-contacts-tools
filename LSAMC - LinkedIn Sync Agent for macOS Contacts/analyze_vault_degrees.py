
import os
import json
import re
from glob import glob

vault_dir = "data/vault"
backups_base = "logs/sessions"

def analyze_vault():
    results = []
    
    # 1. Scan Vault
    for person_dir in glob(os.path.join(vault_dir, "*:ABPerson")):
        profile_path = os.path.join(person_dir, "profile.json")
        if not os.path.exists(profile_path):
            continue
            
        try:
            with open(profile_path, "r") as f:
                data = json.load(f)
                
            degree = data.get("connection_degree")
            name = data.get("full_name") or os.path.basename(person_dir).split(":")[0]
            url = data.get("linkedin_url", "")
            
            if degree is not None:
                results.append({
                    "name": name,
                    "degree": degree,
                    "url": url,
                    "vault_id": os.path.basename(person_dir),
                    "force_resync": False
                })
        except Exception as e:
            pass # Silent skip for broken JSON

    # 2. Check for #lsam-force-resync in recent session backups
    for item in results:
        # Search for this person in session backups
        safe_name = "".join([c if c.isalnum() else "_" for c in item["name"]])
        # Look in all sessions
        matches = glob(os.path.join(backups_base, "run_*", "backups", safe_name, "*.vcf"))
        for vcf in matches:
            try:
                with open(vcf, "r") as f:
                    content = f.read()
                    if "#lsam-force-resync" in content:
                        item["force_resync"] = True
                        break
            except:
                pass

    # Sort by degree
    results.sort(key=lambda x: (x["degree"] if x["degree"] is not None else 99, x["name"]))
    
    return results

if __name__ == "__main__":
    report = analyze_vault()
    print(json.dumps(report, indent=2))
