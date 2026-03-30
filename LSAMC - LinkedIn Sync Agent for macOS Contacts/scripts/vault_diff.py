#!/usr/bin/env python3
"""
vault_diff.py — CLI tool for vault snapshot comparison.
Sprint 1 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 1.3)

Usage:
    python3 scripts/vault_diff.py <UUID:ABPerson>          # diff latest vs previous
    python3 scripts/vault_diff.py <UUID:ABPerson> --json    # output as JSON
    python3 scripts/vault_diff.py <UUID:ABPerson> --list    # list all history snapshots
    python3 scripts/vault_diff.py --all                     # summary of all contacts with history

Author: Claude Opus 4.6 (1M context) | 2026-03-29
"""

import argparse
import json
import os
import sys

# Project root resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from src.utils.vault_history import load_history, diff, format_diff_human  # noqa: E402

VAULT_ROOT = os.path.join(PROJECT_ROOT, "data", "vault")


def find_contact_dir(identifier: str) -> str | None:
    """Find vault contact directory by UUID or partial name match."""
    # Direct UUID match
    direct = os.path.join(VAULT_ROOT, identifier)
    if os.path.isdir(direct):
        return direct

    # Try with :ABPerson suffix
    if ":ABPerson" not in identifier:
        with_suffix = os.path.join(VAULT_ROOT, f"{identifier}:ABPerson")
        if os.path.isdir(with_suffix):
            return with_suffix

    # Partial name match via master_profile.json
    for entry in os.scandir(VAULT_ROOT):
        if not entry.is_dir():
            continue
        mp = os.path.join(entry.path, "master_profile.json")
        if os.path.exists(mp):
            try:
                with open(mp, "r") as f:
                    profile = json.load(f)
                full_name = profile.get("full_name", "")
                if identifier.lower() in full_name.lower():
                    return entry.path
            except Exception:
                continue
    return None


def cmd_list(contact_dir: str) -> None:
    """List all history snapshots for a contact."""
    history = load_history(contact_dir)
    if not history:
        print(f"No history snapshots found in {contact_dir}/history/")
        return

    print(f"History for {os.path.basename(contact_dir)}:")
    print(f"  {len(history)} snapshot(s):\n")
    for i, snap in enumerate(history):
        captured = snap.get("captured_at", "?")
        source = snap.get("source", "?")
        version = snap.get("engine_version", "?")
        role = snap.get("profile", {}).get("current_role", "")[:50]
        label = "LATEST" if i == 0 else f"  #{i+1}"
        print(f"  [{label}] {captured}  ({source}, {version})")
        if role:
            print(f"          Role: {role}")


def cmd_diff(contact_dir: str, as_json: bool = False) -> None:
    """Diff latest vs previous snapshot."""
    history = load_history(contact_dir)

    if len(history) < 2:
        # If only 1 snapshot, try to diff against master_profile.json as "old"
        if len(history) == 1:
            mp = os.path.join(contact_dir, "master_profile.json")
            if os.path.exists(mp):
                with open(mp, "r") as f:
                    master = json.load(f)
                # Construct a synthetic "old" snapshot from master
                snap_new = history[0]
                snap_old = {"profile": master, "captured_at": "master_profile.json (no history)"}
                result = diff(snap_new, snap_old)
                if as_json:
                    print(json.dumps(result, indent=2, default=str))
                else:
                    print(format_diff_human(result))
                return
        print("Not enough history snapshots for diff (need at least 2).")
        print("Run a sync to create the first history entry.")
        return

    snap_new = history[0]
    snap_old = history[1]
    result = diff(snap_new, snap_old)

    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        name = snap_new.get("profile", {}).get("full_name", os.path.basename(contact_dir))
        print(f"\n=== Vault Diff: {name} ===\n")
        print(format_diff_human(result))


def cmd_all_summary() -> None:
    """Show summary of all contacts that have history snapshots."""
    print("Scanning vault for contacts with history...\n")
    found = 0
    for entry in sorted(os.scandir(VAULT_ROOT), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        history_dir = os.path.join(entry.path, "history")
        if not os.path.isdir(history_dir):
            continue
        snapshots = [f for f in os.listdir(history_dir) if f.endswith(".json")]
        if not snapshots:
            continue

        # Read name from master_profile
        name = entry.name
        mp = os.path.join(entry.path, "master_profile.json")
        if os.path.exists(mp):
            try:
                with open(mp, "r") as f:
                    profile = json.load(f)
                name = profile.get("full_name", entry.name)
            except Exception:
                pass

        found += 1
        print(f"  {name:<40s} {len(snapshots)} snapshot(s)  [{entry.name}]")

    if found == 0:
        print("  No contacts have history snapshots yet.")
        print("  Run a sync to start building vault history.")
    else:
        print(f"\n  Total: {found} contact(s) with history")


def main():
    parser = argparse.ArgumentParser(
        description="LSAM Vault Diff — compare vault snapshots across sync sessions"
    )
    parser.add_argument(
        "contact", nargs="?", default=None,
        help="Contact UUID (with or without :ABPerson) or partial name"
    )
    parser.add_argument("--json", action="store_true", help="Output diff as JSON")
    parser.add_argument("--list", action="store_true", help="List all history snapshots")
    parser.add_argument("--all", action="store_true", help="Summary of all contacts with history")

    args = parser.parse_args()

    if args.all:
        cmd_all_summary()
        return

    if not args.contact:
        parser.print_help()
        return

    contact_dir = find_contact_dir(args.contact)
    if not contact_dir:
        print(f"Contact not found: {args.contact}")
        print("Provide a UUID, UUID:ABPerson, or partial name.")
        sys.exit(1)

    if args.list:
        cmd_list(contact_dir)
    else:
        cmd_diff(contact_dir, as_json=args.json)


if __name__ == "__main__":
    main()
