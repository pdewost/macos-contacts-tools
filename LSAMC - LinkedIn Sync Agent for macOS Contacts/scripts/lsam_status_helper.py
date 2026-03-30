#!/usr/bin/env python3
"""
LSAM Status Helper (Python Bridge) - v0.6
-----------------------------------------
Bridge between AppleScript Control Center and the JSON Vault.
Project: LinkedIn Sync Agent for macOS Contacts
"""

import sys
import os
import json
import argparse
from datetime import datetime

# CONSTANTS
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_ROOT = os.path.join(PROJECT_ROOT, "data", "vault")

def get_vault_path(uuid):
    """Finds the vault directory for a given UUID, including archived sessions.
    Now scans for _contact_id inside profile.json for accuracy.
    """
    # 1. Search Active Vault
    if os.path.exists(VAULT_ROOT):
        for item in os.listdir(VAULT_ROOT):
            path = os.path.join(VAULT_ROOT, item)
            if os.path.isdir(path):
                # Try exact UUID dir name first
                if item.startswith(uuid): return path
                # Scan profile.json
                pfile = os.path.join(path, "profile.json")
                if os.path.exists(pfile):
                    try:
                        with open(pfile, 'r') as f:
                            data = json.load(f)
                            if data.get("_contact_id") == uuid: return path
                    except: pass

    # 2. Search Archived Vault
    ARCHIVE_ROOT = os.path.join(VAULT_ROOT, "archived")
    if os.path.exists(ARCHIVE_ROOT):
        for session in sorted(os.listdir(ARCHIVE_ROOT), reverse=True):
            session_path = os.path.join(ARCHIVE_ROOT, session)
            if os.path.isdir(session_path):
                for item in os.listdir(session_path):
                    path = os.path.join(session_path, item)
                    if os.path.isdir(path):
                        if item.startswith(uuid): return path
                        pfile = os.path.join(path, "profile.json")
                        if os.path.exists(pfile):
                            try:
                                with open(pfile, 'r') as f:
                                    data = json.load(f)
                                    if data.get("_contact_id") == uuid: return path
                            except: pass
    return None

def load_profile(uuid):
    """Loads the profile.json for a UUID."""
    folder = get_vault_path(uuid)
    if not folder:
        return {"error": "Vault folder not found"}
        
    profile_path = os.path.join(folder, "profile.json")
    if not os.path.exists(profile_path):
        return {"error": "profile.json missing"}
        
    try:
        with open(profile_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"JSON decode error: {e}"}

def cmd_inspect(args):
    """Returns a formatted summary of the contact."""
    data = load_profile(args.uuid)
    if "error" in data:
        print(f"ERROR: {data['error']}")
        return

    # Basic Info
    name = data.get("full_name", "Unknown Name")
    role = data.get("current_role", "No Role")
    company = data.get("company", "No Company")
    loc = data.get("location", "No Location")
    
    # Stats
    f_count = data.get("followers_count", 0)
    c_count = data.get("connections_count", 0)
    
    # URLs
    li_url = data.get("linkedin_url", "N/A")
    
    # History (Simulated for now, usually in 'sync_history' list if implemented)
    history = data.get("sync_history", [])
    last_sync = "Never"
    if hasattr(data, "last_updated"):
        last_sync = data["last_updated"]
    
    print("-" * 40)
    print(f"👤 {name}")
    print(f"💼 {role} at {company}")
    print(f"📍 {loc}")
    print("-" * 40)
    print(f"🔗 LinkedIn: {li_url}")
    print(f"📊 Stats: {f_count} followers, {c_count} connections")
    print("-" * 40)
    if history:
        print("📜 History:")
        for h in history[-3:]: # Last 3 events
            print(f"   - {h.get('date', '?')}: {h.get('action', 'Update')}")
    else:
        print("📜 History: No records found.")
        
    # Validation info
    if data.get("visual_verification_failed"):
        print("\n⚠️ VISUAL MISMATCH DETECTED")

def cmd_path(args):
    """Returns the absolute path to the vault folder."""
    folder = get_vault_path(args.uuid)
    if folder:
        print(folder, end="") # No newline for cleaner AppleScript usage
    else:
        print("MISSING", end="")

def cmd_json(args):
    """Returns raw JSON."""
    data = load_profile(args.uuid)
    print(json.dumps(data, indent=2))

def cmd_url(args):
    """Returns just the LinkedIn URL if found."""
    data = load_profile(args.uuid)
    url = data.get("linkedin_url")
    if url:
        print(url, end="")
    else:
        print("MISSING", end="")

def main():
    parser = argparse.ArgumentParser(description="LSAM Vault Helper")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Inspect
    p_inspect = subparsers.add_parser("inspect", help="Show human-readable profile")
    p_inspect.add_argument("uuid", help="Contact UUID")
    
    # Path
    p_path = subparsers.add_parser("path", help="Get folder path")
    p_path.add_argument("uuid", help="Contact UUID")
    
    # Raw JSON
    p_json = subparsers.add_parser("json", help="Get raw JSON")
    p_json.add_argument("uuid", help="Contact UUID")
    
    # URL only
    p_url = subparsers.add_parser("url", help="Get LinkedIn URL")
    p_url.add_argument("uuid", help="Contact UUID")
    
    args = parser.parse_args()
    
    if args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "path":
        cmd_path(args)
    elif args.command == "json":
        cmd_json(args)
    elif args.command == "url":
        cmd_url(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
