#!/usr/bin/env python3
"""
LSAM Identity Integrity Audit v2
Version: 2.0.0
Purpose: Performs a rigorous symmetry check between macOS contact names 
and LinkedIn handles to find 'Quiet' identity mismatches.
"""

import sys
import os
import re
import unicodedata
from typing import List, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

TARGET_GROUP = "script-LSAM-Force-Refresh"
PRIORITY_GROUP = "script-LSAM-Priority"

def normalize_text(text: str) -> str:
    """Normalizes text for fuzzy matching (lowercase, no accents, alphanumeric)."""
    if not text: return ""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[^a-z0-9]', '', text.lower())

def has_name_symmetry(name: str, handle: str) -> bool:
    """
    Checks if the LinkedIn handle shares at least 3 characters with 
    the contact's first or last name.
    """
    if not name or not handle or handle == "None":
        return False
        
    norm_handle = normalize_text(handle)
    
    # Split name into parts (First, Last, etc.)
    name_parts = name.split()
    norm_parts = [normalize_text(p) for p in name_parts if len(p) >= 3]
    
    # Check for substring match (e.g., 'pdewost' contains 'dewost')
    for p in norm_parts:
        if p in norm_handle or norm_handle in p:
            return True
            
    # Check for initials + last name pattern (e.g., 'p-dewost')
    if len(name_parts) >= 2:
        initial = normalize_text(name_parts[0][0])
        last = normalize_text(name_parts[-1])
        if initial and last and (initial + last in norm_handle or last + initial in norm_handle):
            return True

    return False

def parse_sync_block(note: str) -> Dict[str, Any]:
    """Extracts metadata from the LSAM sync block."""
    res = {
        "version": "0.0.0",
        "degree": "Unknown",
        "connections": 0,
        "mutual": 0,
        "handle": "None",
        "date": "Unknown",
        "raw": note
    }
    if not note: return res
    
    # Version
    v_match = re.search(r"LSAMC v([\d\.]+)", note)
    if v_match: res["version"] = v_match.group(1)
    
    # Date
    d_match = re.search(r"<Linkedin-AI-sync ([\d-]+) (update|added)>", note)
    if d_match: res["date"] = d_match.group(1)
    
    # Degree
    deg_match = re.search(r"Connections : [\d,]+ \(([^)]+)\)", note)
    if deg_match: res["degree"] = deg_match.group(1)
    
    # Handle from note
    h_match = re.search(r"linkedin\.com/in/([^/\s\?\">]+)", note)
    if h_match: res["handle"] = h_match.group(1)
    
    # Connections (Numeric)
    c_match = re.search(r"Connections : ([\d+,]+)", note)
    if c_match:
        try:
            res["connections"] = int(c_match.group(1).replace(",", "").replace("+", ""))
        except: pass
        
    # Mutual (Numeric)
    m_match = re.search(r"Mutual connections : (\d+)", note)
    if m_match:
        try:
            res["mutual"] = int(m_match.group(1))
        except: pass
        
    return res

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LSAM Identity Audit v2")
    parser.add_argument("--limit", type=int, default=1000, help="Limit number of contacts")
    args = parser.parse_args()

    bridge = ContactMacOSBridge(mode="SIMULATION")
    
    print(f"--- Starting Identity Audit v2 (Symmetry Check) on '{TARGET_GROUP}' ---")
    
    # 1. Get contact names and IDs
    list_res = bridge.list_group_contacts(TARGET_GROUP)
    if not list_res["success"]:
        print(f"Error listing contacts: {list_res.get('error')}")
        return
    
    # 2. Get notes and social profiles in bulk
    notes_res = bridge.batch_get_group_notes(TARGET_GROUP)
    social_res = bridge.batch_get_group_social(TARGET_GROUP)
    
    if not notes_res["success"] or not social_res["success"]:
        print("Error fetching batch data.")
        return
    
    notes_data = notes_res["notes"]
    social_map = social_res["social_map"]
    contacts = list_res["matches"][:args.limit]
    
    print(f"Auditing {len(contacts)} contacts for Symmetry and Degree...")
    
    findings = []
    
    # Known 195k "Mega-Horse" threshold
    MEGA_HORSE_SIG = 195000

    for c in contacts:
        contact_id = c["id"]
        name = c["name"]
        note = notes_data.get(contact_id, "")
        
        if "<Linkedin-AI-sync" not in note:
            continue
            
        meta = parse_sync_block(note)
        
        # Determine handle from Social Profile preferably
        urls = social_map.get(contact_id, [])
        found_handle = "None"
        for url in urls:
            if "linkedin.com/in/" in url.lower():
                found_handle = url.split("linkedin.com/in/")[-1].strip("/")
                break
        
        if found_handle == "None":
            found_handle = meta["handle"]

        # 1. Symmetry Verification
        is_symmetric = has_name_symmetry(name, found_handle)
        
        # 2. High-Reach Artifacts (Mega-Horse)
        is_mega_horse = meta["connections"] >= MEGA_HORSE_SIG
        
        # 3. Low-Connection Colleague check
        is_stranger = (meta["connections"] > 1000 and "Mutual connections" in note and meta["mutual"] <= 1)
        
        # 4. Degree Check (3rd degree is suspicious for long-term contacts)
        is_3rd_degree = meta["degree"] in ["3rd", "None", "Unknown"]

        reasons = []
        if not is_symmetric and found_handle != "None":
            reasons.append("Asymmetric Handle")
        if is_mega_horse:
            reasons.append(f"Mega-Horse Stats ({meta['connections']})")
        if is_stranger:
            reasons.append(f"Stranger Signal (Mutuals: {meta['mutual']})")
        if is_3rd_degree:
            reasons.append(f"Suspicious Degree ({meta['degree']})")

        if reasons:
            # Categorization logic
            category = "B (Wrong Stats)" if (is_symmetric and (is_mega_horse or is_stranger)) else "A (Mismatch)"
            if not is_symmetric: category = "A (Mismatch)"
            
            findings.append({
                "name": name,
                "handle": found_handle,
                "date": meta["date"],
                "category": category,
                "reason": "; ".join(reasons),
                "connections": meta["connections"],
                "mutuals": meta["mutual"],
                "degree": meta["degree"]
            })

    print(f"\nAudit complete. Found {len(findings)} flagged contacts.")
    
    # Group findings for reporting
    cat_a = [f for f in findings if f["category"] == "A (Mismatch)"]
    cat_b = [f for f in findings if f["category"] == "B (Wrong Stats)"]
    
    print(f"Category A (Mismatch): {len(cat_a)}")
    print(f"Category B (Wrong Stats): {len(cat_b)}")
    
    # In a real environment, we'd write to MD here, but the agent will do that.
    for f in findings:
        print(f"[{f['category']}] {f['name']} | Handle: {f['handle']} | Reason: {f['reason']}")

if __name__ == "__main__":
    main()
