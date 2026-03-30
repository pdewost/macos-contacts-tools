#!/usr/bin/env python3
"""
LSAM Surgical Reset (Step 1)
Version: 1.0.0
Purpose: Performs a "Note Wash" for Category B contacts (Right Identity, Wrong Stats).
Wipes the sync block but preserves the LinkedIn handle.
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

def normalize_text(text: str) -> str:
    if not text: return ""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[^a-z0-9]', '', text.lower())

def has_name_symmetry(name: str, handle: str) -> bool:
    if not name or not handle or handle == "None":
        return False
    norm_handle = normalize_text(handle)
    name_parts = name.split()
    norm_parts = [normalize_text(p) for p in name_parts if len(p) >= 3]
    for p in norm_parts:
        if p in norm_handle or norm_handle in p:
            return True
    return False

def parse_connections(note: str) -> int:
    match = re.search(r"Connections : ([\d+,]+)", note)
    if match:
        try:
            return int(match.group(1).replace(",", "").replace("+", ""))
        except: return 0
    return 0

def parse_mutuals(note: str) -> int:
    match = re.search(r"Mutual connections : (\d+)", note)
    if match:
        try:
            return int(match.group(1))
        except: return 0
    return 0

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LSAM Surgical Reset (Category B)")
    parser.add_argument("--full", action="store_true", help="Execute the note wash")
    args = parser.parse_args()

    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    
    print(f"--- Starting Surgical Reset on '{TARGET_GROUP}' ---")
    
    # 1. Get contact names and IDs
    list_res = bridge.list_group_contacts(TARGET_GROUP)
    if not list_res["success"]:
        print(f"Error listing contacts: {list_res.get('error')}")
        return
    
    # 2. Get notes and social profiles
    notes_res = bridge.batch_get_group_notes(TARGET_GROUP)
    social_res = bridge.batch_get_group_social(TARGET_GROUP)
    
    if not notes_res["success"] or not social_res["success"]:
        print("Error fetching batch data.")
        return
    
    notes_data = notes_res["notes"]
    social_map = social_res["social_map"]
    contacts = list_res["matches"]
    
    reset_list = []
    
    for c in contacts:
        contact_id = c["id"]
        name = c["name"]
        note = notes_data.get(contact_id, "")
        
        if "<Linkedin-AI-sync" not in note:
            continue
            
        # Extract handle
        urls = social_map.get(contact_id, [])
        handle = "None"
        for url in urls:
            if "linkedin.com/in/" in url.lower():
                handle = url.split("linkedin.com/in/")[-1].strip("/")
                break
        
        # Identity Check
        is_symmetric = has_name_symmetry(name, handle)
        
        # Corruption Check
        connections = parse_connections(note)
        mutuals = parse_mutuals(note)
        is_mega_horse = connections >= 195000
        is_stranger = (connections > 1000 and "Mutual connections" in note and mutuals <= 1)
        
        # Category B: Symmetric Handle + Corrupted Data
        if is_symmetric and (is_mega_horse or is_stranger):
            reset_list.append({
                "id": contact_id,
                "name": name,
                "note": note,
                "reason": "Mega-Horse" if is_mega_horse else "Low Mutuals/High Reach"
            })

    print(f"Found {len(reset_list)} Category B contacts for Surgical Reset.")
    
    for item in reset_list:
        print(f"  [WASH] {item['name']} ({item['reason']})")
        
    if args.full and reset_list:
        print(f"\nExecuting Note Wash for {len(reset_list)} contacts...")
        for item in reset_list:
            # Strip the sync block
            # Regex to find <Linkedin-AI-sync.*?</Linkedin-AI-sync>
            clean_note = re.sub(r'<Linkedin-AI-sync.*?</Linkedin-AI-sync>', '', item['note'], flags=re.DOTALL).strip()
            
            # Update the note via AppleScript (Bridge update_note is efficient)
            res = bridge.update_note(item['id'], clean_note)
            if res["success"]:
                print(f"  ✅ Reset: {item['name']}")
            else:
                print(f"  ❌ Failed: {item['name']} - {res.get('error')}")
    elif not args.full:
        print("\nSimulation complete. Use --full to execute the note wash.")

if __name__ == "__main__":
    main()
