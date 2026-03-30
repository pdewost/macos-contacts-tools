
import os
import glob
import json
import re
from pathlib import Path
import sys

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Avoid importing LinkedInProfile if it causes issues, but we want its parsing logic
# Actually, we can just use the source logic directly to be fast.

def scan_corruption():
    print("🕵️ Starting Vault & Log Sync Block Corruption Scan...")
    
    # Paths to scan
    paths = [
        "data/vault/*/master_profile.json",
        "logs/sessions/*/backups/*/profile.json",
        "logs/fast_sessions/*/backups/*/profile.json"
    ]
    
    files = []
    for p in paths:
        files.extend(glob.glob(p))
    
    print(f"🔍 Found {len(files)} profile files to analyze.")
    
    corrupted = []
    
    for f_path in files:
        try:
            with open(f_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
            
            # 1. Check Connections Raw for garbage
            connections_raw = str(data.get("connections_raw", ""))
            name = data.get("full_name") or data.get("Name") or "Unknown"
            cid = data.get("_contact_id") or data.get("id") or "N/A"
            
            # Pattern: If connections_raw is too long and contains many spaces/letters, it might be a name
            # or a title that leaked.
            is_garbage_conn = False
            if connections_raw and not re.search(r'\d', connections_raw):
                 # No digits at all? Likely garbage if it's not empty
                 if len(connections_raw) > 5:
                     is_garbage_conn = True
            
            # Check for leaked contact names in connections_raw (very common)
            # If connections_raw matches a name pattern or contains common title words without digits
            if any(title in connections_raw for title in ["Managing", "Director", "CEO", "President"]) and not re.search(r'\d', connections_raw):
                is_garbage_conn = True

            # 2. Check History for "Mutual 0 (was X)" drop
            # We look at the 'history' field if it exists
            history = data.get("history", [])
            has_drop = False
            drop_details = ""
            
            if history and len(history) >= 2:
                # Sort history by date? No, assume it's chronological in the list
                # Actually, let's look for any transition from X > 0 to 0.
                prev_mutual = None
                for entry in history:
                    m = entry.get("mutual")
                    if m is not None:
                        try:
                            m_val = int(str(m).replace("+", "").replace(",", "").strip())
                            if prev_mutual is not None and prev_mutual > 10 and m_val == 0:
                                has_drop = True
                                drop_details = f"{prev_mutual} -> 0"
                            prev_mutual = m_val
                        except:
                            pass

            if is_garbage_conn or has_drop:
                corrupted.append({
                    "name": name,
                    "id": cid,
                    "path": f_path,
                    "connections_raw": connections_raw[:50],
                    "drop": drop_details,
                    "type": "Garbage in Conn" if is_garbage_conn else "Mutual Drop"
                })

        except Exception:
            continue

    print(f"\n📊 Scan Result: Found {len(corrupted)} potentially corrupted items.")
    
    # Save results
    with open("vault_corruption_scan.json", "w") as f:
        json.dump(corrupted, f, indent=2)

    # Generate Report
    report = ["# Sync Block Corruption Audit Report", ""]
    report.append(f"Total Profiles Scanned: {len(files)}")
    report.append(f"Suspicious Items Found: {len(corrupted)}")
    report.append("")
    report.append("| Contact Name | ID | Type | Sample / Drop | Path |")
    report.append("| :--- | :--- | :--- | :--- | :--- |")
    
    for item in corrupted[:100]: # Top 100 for readability
        report.append(f"| {item['name']} | `{item['id']}` | {item['type']} | {item['drop'] or item['connections_raw']} | `{item['path']}` |")

    with open("SCAN_CORRUPTION_REPORT.md", "w") as f:
        f.write("\n".join(report))
    
    print("📝 Report generated: SCAN_CORRUPTION_REPORT.md")

if __name__ == "__main__":
    scan_corruption()
