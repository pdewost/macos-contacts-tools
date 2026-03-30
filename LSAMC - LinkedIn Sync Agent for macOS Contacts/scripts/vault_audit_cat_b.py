#!/usr/bin/env python3
"""
LSAM Vault Audit (Category B) - V2
Version: 2.0.0
Purpose: Verifies 'note.txt' integrity using the archive folders.
"""

import sys
import os
import re
import subprocess

CAT_B_NAMES = [
    "christian icard", "Didier Bench", "Christine SALMON-LEGAGNEUR", "Julie Gauthier",
    "Christophe Bourdeleau", "Mourad Haddad", "Nishant Chhatrola", "Christophe GONTARD",
    "Christophe Van Cauwenberghe", "Martin Varsavsky", "Fabienne MARQUET", "Patrick de Champs",
    "GOUJON Samuel", "Delphine Fauvage de Surville", "Julia Zhu", "Valérie Balavoine",
    "Guillaume de Marcillac", "Assia Touil Spicher", "Khaoula Tlili", "Ludovic Petit",
    "Jean-Marie PILLOT", "Christine Landrevot", "Jean-Michel VENET", "Jean-Eudes Leleu",
    "Frederic Honnorat", "Reginal King", "Gilles Chevallier", "Emmanuelle Hoss",
    "Pierre Le Cacheux", "Loïc Le Moaligou", "Pascal Buffard", "Didier Janci",
    "Olivier Sylvain", "Brendan McGarvey", "Frédéric Roullier", "Vincent Champain"
]

VAULT_ARCHIVE = "data/vault/archived"

def normalize(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())

def find_latest_archive_note(name: str):
    norm_name = normalize(name)
    # Search for *-original.txt in subdirectories
    matches = []
    for root, dirs, files in os.walk(VAULT_ARCHIVE):
        for f in files:
            if f.endswith("-original.txt"):
                if norm_name in normalize(f):
                    matches.append(os.path.join(root, f))
    
    if not matches:
        return None
    
    # Sort by mtime to get the latest
    matches.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return matches[0]

def get_current_note(name: str):
    script = f'tell application "Contacts" to get note of first person whose name contains "{name}"'
    res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if res.returncode == 0:
        return res.stdout.strip()
    return None

def main():
    print(f"--- Starting Refined Vault Audit (36 Contacts) ---")
    results = []
    
    for name in CAT_B_NAMES:
        archive_path = find_latest_archive_note(name)
        current_note = get_current_note(name)
        
        if not archive_path:
            results.append(f"❌ {name:30} | Status: NO_ARCHIVE")
            continue
            
        try:
            with open(archive_path, "r") as f:
                archive_content = f.read()
            
            # Extract non-sync data from archive
            archive_human = re.sub(r'<Linkedin-AI-sync.*?</Linkedin-AI-sync>', '', archive_content, flags=re.DOTALL).strip()
            
            # Check if current_note contains archive_human
            # (Note: current_note might have changed whitespace, so we normalize)
            def clean(t): return re.sub(r'\s+', ' ', t).strip()
            
            if not archive_human:
                results.append(f"✅ {name:30} | Status: OK (No human data to lose)")
            elif clean(archive_human) in clean(current_note or ""):
                results.append(f"✅ {name:30} | Status: OK (Data Preserved)")
            else:
                results.append(f"⚠️ {name:30} | Status: MISMATCH/DATA_LOSS?")
                print(f"    DEBUG {name}: Archive human data: [{archive_human}]")
                print(f"    DEBUG {name}: Current note: [{current_note}]")
        except Exception as e:
            results.append(f"❌ {name:30} | Status: ERROR ({str(e)})")

    print("\n".join(results))
    with open("logs/vault_audit_v2.log", "w") as f:
        f.write("\n".join(results))

if __name__ == "__main__":
    main()
