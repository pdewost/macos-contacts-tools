
import os
import json
from glob import glob

vault_dir = "data/vault"

def audit_divergence(sample_size=30):
    profiles = glob(os.path.join(vault_dir, "*:ABPerson", "profile.json"))
    if not profiles:
        print("No profiles found in vault.")
        return

    # Use a stable subset
    sample = profiles[:sample_size]
    
    divergence_count = 0
    total_with_exp = 0
    
    results = []

    for p_path in sample:
        try:
            with open(p_path, 'r') as f:
                data = json.load(f)
            
            headline_company = (data.get("company") or "").strip()
            headline_role = (data.get("current_role") or "").strip()
            exp_list = data.get("experience", [])
            
            if not exp_list:
                continue
            
            total_with_exp += 1
            latest_exp = exp_list[0]
            exp_company = (latest_exp.get("company") or "").strip()
            exp_role = (latest_exp.get("title") or "").strip()
            
            # Simple divergence check: case-insensitive mismatch
            company_match = headline_company.lower() in exp_company.lower() or exp_company.lower() in headline_company.lower()
            # Headline roles are often richer/different, so we check if the exp_role is at least a substring or vice versa
            role_match = exp_role.lower() in headline_role.lower() or headline_role.lower() in exp_role.lower()
            
            diverged = not (company_match and role_match)
            if diverged:
                divergence_count += 1
            
            results.append({
                "name": data.get("full_name") or os.path.basename(os.path.dirname(p_path)),
                "headline": f"{headline_role} at {headline_company}",
                "experience": f"{exp_role} at {exp_company}",
                "diverged": diverged
            })
            
        except Exception as e:
            continue

    print(f"Audit Results (Sample Size: {len(results)} with Experience data):")
    print(f"Divergence detected: {divergence_count} / {len(results)} ({ (divergence_count/len(results)*100) if len(results) > 0 else 0 :.1f}%)")
    print("\nDetailed Divergences:")
    for r in results:
        if r["diverged"]:
            print(f"- {r['name']}:")
            print(f"  H: {r['headline']}")
            print(f"  E: {r['experience']}")

if __name__ == "__main__":
    audit_divergence(30)
