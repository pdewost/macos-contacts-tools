#!/usr/bin/env python3
"""
Vault Lookup: Check if any of the 24 space-in-handle contacts have a prior valid LinkedIn URL
stored in the vault (active or archived).
"""
import json
import re
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
VAULT_ROOT = PROJECT_ROOT / "data" / "vault"
DAMAGED_REPORT = PROJECT_ROOT / "logs" / "damaged_contacts_fixes.md"

# Extract the 24 space-in-handle contact IDs from the report
SPACE_CONTACTS = []
with open(DAMAGED_REPORT) as f:
    for line in f:
        if "Space in handle" in line:
            # Extract ID from previous lines context - look for ID pattern
            pass

# Simpler: hardcode from the report (these are the 24 space-in-handle contacts)
SPACE_CONTACT_IDS = [
    "A9A1D25D-46B6-4CD7-8C34-9842A6DF1E5A:ABPerson",  # Me Charlotte HUET HERFRAY
    "BEF01E37-8B36-4574-9D43-DB321BCEDCE1:ABPerson",  # Jean-Claude Bourbon
    "5AAD8225-41F7-49E2-9161-98F65DF6A9E5:ABPerson",  # Jean-Pierre Bokobza
    "B4388B04-5D21-40B3-AF87-C6BAC5D1150B:ABPerson",  # Philippe Chuzel
    "24193DB7-CB16-4E77-9947-33DB9B6506A7:ABPerson",  # M Bertrand DIARD
    "EC7A9EB5-1344-43AA-9F8E-16FA01B10125:ABPerson",  # Me Anita Iriart-Sorhondo
    "6DF4B96D-BEB4-486C-95BE-C46EF1990C22:ABPerson",  # Me Meryem TOM
    "1853E3DA-70C7-461E-8180-2B4580E56792:ABPerson",  # Fiona Darmon
    "E5AB4372-305A-4CE8-9C83-1B2F2485900A:ABPerson",  # Andre Loechel
    "9C205BE5-4C4D-4045-A701-94B8EA263AA4:ABPerson",  # Me Nada VILLERMAIN-LECOLIER
    "CEF0942D-47C5-4A5F-81CB-AC6593016801:ABPerson",  # M Maxime PICAT
    "D47804D8-41E8-4CD9-8B0D-02EC18DC22D0:ABPerson",  # Lionel Baraban
    "CE3690C7-E840-4923-9D36-C04387E35FA0:ABPerson",  # M Bernard MALACHANE
    "4159BA80-D68F-4AC7-9EF6-835581539B1C:ABPerson",  # David Ring
    "D00752DC-739F-4E60-83F9-561AC3E201BF:ABPerson",  # BRUNO DEDIEU
    "E8EDE0A9-17BB-404F-9983-DEAE5D7C4416:ABPerson",  # Nicolas MOYNIER
    "0C55B364-452D-4365-9D57-2C02E24FEC3D:ABPerson",  # M Alexandre DELIVET
    "0C4222EF-4987-4EB5-957E-34249F41C645:ABPerson",  # Marc Knoll
    "A22794DB-C0B6-46DD-9FD1-03354D0EBB4D:ABPerson",  # M Pierre SAUREL
    "0C1556EC-0EBE-41DC-8CED-120E2CE8BC9F:ABPerson",  # M Information not available (Éric HEME)
    "E6223A47-E3A5-477E-8ED6-FEAEA90EDE7E:ABPerson",  # M Philippe HUMEAU
    "18797603-3FB6-4EA5-ABAC-20A8890B1739:ABPerson",  # M Pierre AUBOUIN
    "E2E1442D-CEA2-4520-A644-D0F5EDBB53E3:ABPerson",  # Esteban Bayro-Kaiser
    "7EB3A09A-6207-4271-A6EB-7C7D482F58AC:ABPerson",  # Me Charlotte HUET HERFRAY (2nd)
]

def find_vault_profiles(contact_id):
    """Search active and archived vault for all profile.json files for a given contact ID."""
    results = []
    uuid = contact_id  # Full ID including :ABPerson
    
    # 1. Active vault
    active_path = VAULT_ROOT / uuid
    if active_path.exists():
        pfile = active_path / "profile.json"
        if pfile.exists():
            try:
                data = json.loads(pfile.read_text())
                results.append(("active", data))
            except: pass
    
    # Also check by _contact_id match in active vault
    for item in VAULT_ROOT.iterdir():
        if item.is_dir() and item.name != "archived":
            pfile = item / "profile.json"
            if pfile.exists():
                try:
                    data = json.loads(pfile.read_text())
                    if data.get("_contact_id") == uuid:
                        results.append(("active", data))
                except: pass
                
    # 2. Archived vault
    archive_root = VAULT_ROOT / "archived"
    if archive_root.exists():
        for session in sorted(archive_root.iterdir(), reverse=True):
            if session.is_dir():
                # Check direct match
                archived_path = session / uuid
                if archived_path.exists():
                    pfile = archived_path / "profile.json"
                    if pfile.exists():
                        try:
                            data = json.loads(pfile.read_text())
                            results.append((f"archived/{session.name}", data))
                        except: pass
                
                # Check by _contact_id
                for item in session.iterdir():
                    if item.is_dir():
                        pfile = item / "profile.json"
                        if pfile.exists():
                            try:
                                data = json.loads(pfile.read_text())
                                if data.get("_contact_id") == uuid:
                                    results.append((f"archived/{session.name}", data))
                            except: pass
    return results

def is_valid_handle(url):
    """Check if the linkedin_url is a valid handle (no spaces, starts with http)."""
    if not url: return False
    url = str(url).strip()
    if " " in url: return False
    if url.startswith("//"): return False
    if not url.startswith("http"): return False
    handle = url.split("/in/")[-1].strip("/")
    if " " in handle: return False
    if not handle: return False
    return True

print("# 🔍 Vault Lookup: Prior Valid LinkedIn Handles for 24 Space-in-Handle Contacts\n")
print(f"Vault root: {VAULT_ROOT}")
print(f"Archived sessions exist: {(VAULT_ROOT / 'archived').exists()}\n")

found_count = 0
not_found_count = 0

for cid in SPACE_CONTACT_IDS:
    profiles = find_vault_profiles(cid)
    
    valid_urls = []
    all_urls = []
    for source, data in profiles:
        url = data.get("linkedin_url", "")
        name = data.get("full_name", "?")
        all_urls.append((source, url, name))
        if is_valid_handle(url):
            valid_urls.append((source, url, name))
    
    if valid_urls:
        found_count += 1
        print(f"✅ {cid}")
        for src, url, name in valid_urls:
            handle = url.split("/in/")[-1].strip("/")
            print(f"   [{src}] {name} -> handle: {handle}")
            print(f"   Full URL: {url}")
    elif all_urls:
        not_found_count += 1
        print(f"❌ {cid} — vault found but NO valid handle")
        for src, url, name in all_urls:
            print(f"   [{src}] {name} -> {url}")
    else:
        not_found_count += 1
        print(f"⬜ {cid} — NOT in vault at all")

print(f"\n---\nSUMMARY: {found_count} contacts HAVE a valid prior handle. {not_found_count} do NOT.")
