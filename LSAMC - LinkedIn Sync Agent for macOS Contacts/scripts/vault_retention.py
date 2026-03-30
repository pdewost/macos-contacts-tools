#!/usr/bin/env python3
"""
LSAM Session Vault Retention Script
Retention Policy: Per contact, keep oldest + 3 most recent session backups.
For all other session backups: delete binary assets (.heic, .jpg, .vcf), keep metadata (profile.json, .txt, .validated, .applied, .resync, session.log).

Usage:
  python3 scripts/vault_retention.py --dry-run    # Report only
  python3 scripts/vault_retention.py --execute    # Actually delete
"""

import os
import sys
import glob
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(PROJECT_ROOT, "logs", "sessions")
BINARY_EXTENSIONS = {".heic", ".jpg", ".jpeg", ".png", ".vcf"}
METADATA_FILES = {"profile.json", "session.log", ".validated", ".applied", ".resync"}

def get_session_date(session_name):
    """Extract date from session directory name like run_2026-01-27_16-22-38."""
    try:
        parts = session_name.split("_")
        if len(parts) >= 2:
            return parts[1]  # e.g., "2026-01-27"
    except:
        pass
    return "0000-00-00"

def scan_sessions():
    """Build a map: contact_name -> [(session_dir, session_date, backup_path, binary_sizes)]."""
    contact_map = defaultdict(list)
    
    if not os.path.exists(SESSIONS_DIR):
        print(f"ERROR: Sessions directory not found: {SESSIONS_DIR}")
        sys.exit(1)
    
    sessions = sorted(os.listdir(SESSIONS_DIR))
    for session in sessions:
        session_path = os.path.join(SESSIONS_DIR, session)
        if not os.path.isdir(session_path):
            continue
        
        backups_dir = os.path.join(session_path, "backups")
        if not os.path.exists(backups_dir):
            continue
        
        session_date = get_session_date(session)
        
        for contact_dir in os.listdir(backups_dir):
            contact_path = os.path.join(backups_dir, contact_dir)
            if not os.path.isdir(contact_path):
                continue
            
            # Calculate binary file sizes
            binary_size = 0
            binary_files = []
            for f in os.listdir(contact_path):
                fpath = os.path.join(contact_path, f)
                if os.path.isfile(fpath):
                    _, ext = os.path.splitext(f)
                    if ext.lower() in BINARY_EXTENSIONS:
                        fsize = os.path.getsize(fpath)
                        binary_size += fsize
                        binary_files.append((fpath, fsize))
            
            contact_map[contact_dir].append({
                "session": session,
                "session_date": session_date,
                "backup_path": contact_path,
                "binary_size": binary_size,
                "binary_files": binary_files,
            })
    
    return contact_map

def apply_retention(contact_map, execute=False):
    """Apply retention policy: keep oldest + 3 most recent, prune rest."""
    total_files_to_delete = 0
    total_bytes_to_recover = 0
    contacts_pruned = 0
    contacts_skipped = 0
    
    for contact_name, entries in sorted(contact_map.items()):
        if len(entries) <= 4:
            # 4 or fewer entries: nothing to prune (oldest + 3 most recent = all)
            contacts_skipped += 1
            continue
        
        # Sort by session date (ascending)
        entries.sort(key=lambda e: e["session_date"])
        
        # Keep: index 0 (oldest) + last 3 (most recent)
        keep_indices = {0, len(entries) - 1, len(entries) - 2, len(entries) - 3}
        
        prune_entries = [e for i, e in enumerate(entries) if i not in keep_indices]
        
        if not prune_entries:
            contacts_skipped += 1
            continue
        
        contacts_pruned += 1
        contact_bytes = 0
        contact_files = 0
        
        for entry in prune_entries:
            for fpath, fsize in entry["binary_files"]:
                total_files_to_delete += 1
                total_bytes_to_recover += fsize
                contact_bytes += fsize
                contact_files += 1
                
                if execute:
                    try:
                        os.remove(fpath)
                    except Exception as e:
                        print(f"  ERROR deleting {fpath}: {e}")
        
        if contact_files > 0 and not execute:
            # Only log contacts with actual binary files to prune
            if contact_bytes > 100_000:  # Only show >100KB contacts
                print(f"  {contact_name}: {contact_files} files, {contact_bytes / 1024 / 1024:.1f} MB ({len(entries)} sessions -> kept 4)")
    
    return total_files_to_delete, total_bytes_to_recover, contacts_pruned, contacts_skipped

def main():
    mode = "--dry-run"
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    
    execute = (mode == "--execute")
    
    print(f"{'=' * 60}")
    print(f"LSAM Vault Retention Script — {'EXECUTE' if execute else 'DRY RUN'}")
    print(f"{'=' * 60}")
    print(f"Sessions directory: {SESSIONS_DIR}")
    print(f"Retention policy: oldest + 3 most recent per contact")
    print(f"Pruned data: binary files only (.heic, .jpg, .vcf)")
    print(f"Preserved: profile.json, .txt, .validated, .applied, .resync")
    print()
    
    print("Scanning sessions...")
    contact_map = scan_sessions()
    
    total_contacts = len(contact_map)
    total_entries = sum(len(v) for v in contact_map.values())
    print(f"Found {total_contacts} unique contacts across {total_entries} session entries.")
    print()
    
    print("Applying retention policy...")
    files, bytes_recovered, pruned, skipped = apply_retention(contact_map, execute=execute)
    
    print()
    print(f"{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"Contacts analyzed:     {total_contacts}")
    print(f"Contacts pruned:       {pruned}")
    print(f"Contacts skipped:      {skipped} (≤4 sessions, nothing to prune)")
    print(f"Binary files {'deleted' if execute else 'to delete'}:  {files}")
    print(f"Space {'recovered' if execute else 'to recover'}:      {bytes_recovered / 1024 / 1024:.1f} MB ({bytes_recovered / 1024 / 1024 / 1024:.2f} GB)")
    
    if not execute and files > 0:
        print()
        print(f"To execute: python3 scripts/vault_retention.py --execute")

if __name__ == "__main__":
    main()
