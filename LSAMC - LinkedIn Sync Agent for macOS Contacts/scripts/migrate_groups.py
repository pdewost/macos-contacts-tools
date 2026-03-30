#!/usr/bin/env python3
"""
migrate_groups.py — LSAM Group Simplification
Sprint 3 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 5)

Migrates from 12 legacy groups (script-LSAM-*) to 6 new groups (LSAM-*).
Includes DAMAGED audit: classifies 847 contacts by vault state.

Usage:
    python3 scripts/migrate_groups.py --audit          # Dry-run: classify DAMAGED, report only
    python3 scripts/migrate_groups.py --audit --json   # Audit output as JSON
    python3 scripts/migrate_groups.py --migrate        # Execute migration (creates new groups, moves contacts)
    python3 scripts/migrate_groups.py --verify         # Post-migration verification

Safety:
    - NEVER deletes groups or contacts (MORENO_GUARD / INCIDENT_MORENO)
    - Creates new groups first (additive)
    - Adds contacts to new groups, then removes from old groups
    - --audit is always safe (read-only)
    - --migrate requires explicit confirmation

Author: Claude Opus 4.6 (1M context) | 2026-03-29
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VAULT_ROOT = os.path.join(PROJECT_ROOT, "data", "vault")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("migrate_groups")

# === Group mapping ===

OLD_GROUPS = {
    "script-LSAM-Priority": "LSAM-Queue",
    "script-LSAM-Force-Refresh": "LSAM-Queue",
    "script-LSAM-Golden Record": "LSAM-Golden",
    "script-LSAM-Tier3-NeedAttention": "LSAM-Review",
    "script-LSAM-LinkedIn to Review": "LSAM-Review",
    "script-LSAM-Search-Failed": "LSAM-Review",
    "script-LSAM-Broken Names": "LSAM-Review",
    "script-LSAM-Exempted": "LSAM-Exempted",
    # DAMAGED handled separately via audit
    # 7mars groups archived (emptied)
}

ARCHIVE_GROUPS = [
    "script-LSAM-7 mars session",
    "script-LSAM-7mars-formatOK",
    "script-LSAM-7mars-orphans",
]

NEW_GROUPS = ["LSAM-Queue", "LSAM-Review", "LSAM-Golden", "LSAM-Damaged", "LSAM-Exempted", "LSAM-Birthday"]


# === AppleScript helpers ===

def _run_osascript(script: str) -> str:
    """Run AppleScript and return output. Raises on failure."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript error: {result.stderr.strip()}")
    return result.stdout.strip()


def get_group_contacts(group_name: str) -> list[dict]:
    """Get all contacts in a group with their IDs and names."""
    script = f'''
tell application "Contacts"
    try
        set g to group "{group_name}"
        set output to ""
        repeat with p in people of g
            set cid to id of p
            set fn to ""
            set ln to ""
            try
                set fn to first name of p
            end try
            try
                set ln to last name of p
            end try
            if fn is missing value then set fn to ""
            if ln is missing value then set ln to ""
            set output to output & cid & "\\t" & fn & " " & ln & linefeed
        end repeat
        return output
    on error
        return ""
    end try
end tell
'''
    raw = _run_osascript(script)
    contacts = []
    for line in raw.strip().split("\n"):
        if "\t" not in line:
            continue
        parts = line.split("\t", 1)
        contacts.append({"id": parts[0].strip(), "name": parts[1].strip()})
    return contacts


def create_group(group_name: str) -> bool:
    """Create a group in Contacts.app if it doesn't exist."""
    script = f'''
tell application "Contacts"
    try
        set g to group "{group_name}"
        return "exists"
    on error
        make new group with properties {{name:"{group_name}"}}
        save
        return "created"
    end try
end tell
'''
    result = _run_osascript(script)
    logger.info(f"Group '{group_name}': {result}")
    return True


def add_contact_to_group(contact_id: str, group_name: str) -> bool:
    """Add a contact to a group."""
    script = f'''
tell application "Contacts"
    try
        set p to person id "{contact_id}"
        set g to group "{group_name}"
        add p to g
        save
        return "ok"
    on error errMsg
        return "error: " & errMsg
    end try
end tell
'''
    result = _run_osascript(script)
    return result == "ok"


def remove_contact_from_group(contact_id: str, group_name: str) -> bool:
    """Remove a contact from a group (does NOT delete the contact)."""
    script = f'''
tell application "Contacts"
    try
        set p to person id "{contact_id}"
        set g to group "{group_name}"
        remove p from g
        save
        return "ok"
    on error errMsg
        return "error: " & errMsg
    end try
end tell
'''
    result = _run_osascript(script)
    return result == "ok"


# === Vault audit ===

def check_vault_status(contact_id: str) -> dict:
    """Check a contact's vault status for DAMAGED audit classification."""
    vault_dir = os.path.join(VAULT_ROOT, contact_id)
    if not os.path.isdir(vault_dir):
        return {"status": "no_vault", "vault_dir": None}

    mp = os.path.join(vault_dir, "master_profile.json")
    if not os.path.exists(mp):
        return {"status": "broken_vault", "vault_dir": vault_dir}

    try:
        with open(mp, "r") as f:
            profile = json.load(f)
    except Exception:
        return {"status": "corrupt_json", "vault_dir": vault_dir}

    # Check for known data quality issues
    full_name = profile.get("full_name", "")
    issues = []

    if not full_name or full_name.lower() in ("no data found", ""):
        issues.append("empty_or_error_name")
    if "ttt" in full_name.lower() and any(c.isdigit() for c in full_name):
        issues.append("handle_artifact_in_name")

    first_name = profile.get("first_name", "")
    if first_name and first_name[0].islower() and len(first_name) > 1:
        issues.append("lowercase_first_name")

    timestamp = profile.get("timestamp", "")
    if timestamp:
        try:
            ts_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if ts_dt > datetime.now(ts_dt.tzinfo):
                issues.append("future_timestamp")
        except Exception:
            pass

    exp = profile.get("experience", []) or []
    edu = profile.get("education", []) or []
    followers = profile.get("followers_count", 0) or 0
    connections = profile.get("connections_count", 0) or 0

    if len(exp) == 0 and len(edu) == 0 and followers <= 2 and connections <= 1:
        issues.append("ghost_account")

    if issues:
        return {
            "status": "quality_issues",
            "issues": issues,
            "vault_dir": vault_dir,
            "full_name": full_name,
        }

    return {
        "status": "valid",
        "vault_dir": vault_dir,
        "full_name": full_name,
        "experience_count": len(exp),
        "connections": connections,
    }


# === Commands ===

def cmd_audit(as_json: bool = False):
    """Audit DAMAGED group: classify each contact by vault state."""
    logger.info("=== DAMAGED Group Audit ===")
    logger.info("Fetching contacts from script-LSAM-DAMAGED...")

    contacts = get_group_contacts("script-LSAM-DAMAGED")
    logger.info(f"Found {len(contacts)} contacts in DAMAGED group")

    classification = defaultdict(list)
    for i, c in enumerate(contacts):
        status = check_vault_status(c["id"])
        status["contact_id"] = c["id"]
        status["contact_name"] = c["name"]
        classification[status["status"]].append(status)

        if (i + 1) % 100 == 0:
            logger.info(f"  Audited {i+1}/{len(contacts)}...")

    # Map to target groups
    target_mapping = {
        "valid": "LSAM-Golden",
        "quality_issues": "LSAM-Review",
        "no_vault": "LSAM-Damaged",
        "broken_vault": "LSAM-Damaged",
        "corrupt_json": "LSAM-Damaged",
    }

    logger.info("\n=== AUDIT RESULTS ===")
    for status_key, contacts_list in sorted(classification.items()):
        target = target_mapping.get(status_key, "LSAM-Damaged")
        logger.info(f"  {status_key}: {len(contacts_list)} → {target}")

    if as_json:
        report = {
            "audit_date": datetime.now().isoformat(),
            "total": len(contacts),
            "classification": {k: len(v) for k, v in classification.items()},
            "details": {k: v for k, v in classification.items()},
            "target_mapping": target_mapping,
        }
        report_path = os.path.join(PROJECT_ROOT, "logs", f"damaged_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"\nAudit report saved: {report_path}")
    else:
        logger.info("\nRun with --json to save full report.")

    return classification


def cmd_migrate():
    """Execute the full group migration."""
    logger.info("=== LSAM Group Migration ===")
    logger.info(f"New groups to create: {NEW_GROUPS}")

    # Step 1: Create new groups
    logger.info("\n--- Step 1: Creating new groups ---")
    for g in NEW_GROUPS:
        create_group(g)

    # Step 2: Migrate direct-mapped groups
    logger.info("\n--- Step 2: Migrating direct-mapped groups ---")
    for old_group, new_group in OLD_GROUPS.items():
        logger.info(f"  {old_group} → {new_group}")
        contacts = get_group_contacts(old_group)
        logger.info(f"    {len(contacts)} contacts")
        success = 0
        for c in contacts:
            if add_contact_to_group(c["id"], new_group):
                success += 1
        logger.info(f"    Added {success}/{len(contacts)} to {new_group}")

    # Step 3: DAMAGED audit + classification
    logger.info("\n--- Step 3: DAMAGED audit + migration ---")
    classification = cmd_audit(as_json=True)

    target_mapping = {
        "valid": "LSAM-Golden",
        "quality_issues": "LSAM-Review",
        "no_vault": "LSAM-Damaged",
        "broken_vault": "LSAM-Damaged",
        "corrupt_json": "LSAM-Damaged",
    }

    for status_key, contacts_list in classification.items():
        target = target_mapping.get(status_key, "LSAM-Damaged")
        logger.info(f"  Moving {len(contacts_list)} '{status_key}' contacts to {target}")
        success = 0
        for c in contacts_list:
            if add_contact_to_group(c["contact_id"], target):
                success += 1
        logger.info(f"    Added {success}/{len(contacts_list)}")

    # Step 4: Archive 7mars groups (add to Review first)
    logger.info("\n--- Step 4: Archiving 7mars groups ---")
    for archive_group in ARCHIVE_GROUPS:
        contacts = get_group_contacts(archive_group)
        logger.info(f"  {archive_group}: {len(contacts)} contacts → checking vault state")
        for c in contacts:
            status = check_vault_status(c["id"])
            if status["status"] == "valid":
                add_contact_to_group(c["id"], "LSAM-Golden")
            else:
                add_contact_to_group(c["id"], "LSAM-Review")

    logger.info("\n=== Migration PHASE 1 complete (additions) ===")
    logger.info("Run --verify to confirm counts before removing old groups.")


def cmd_verify():
    """Verify migration: compare old vs new group counts."""
    logger.info("=== Post-Migration Verification ===\n")

    old_total = 0
    new_total = 0

    logger.info("Old groups:")
    all_old = list(OLD_GROUPS.keys()) + ["script-LSAM-DAMAGED"] + ARCHIVE_GROUPS
    for g in all_old:
        try:
            contacts = get_group_contacts(g)
            count = len(contacts)
        except Exception:
            count = 0
        old_total += count
        logger.info(f"  {g}: {count}")

    logger.info(f"\nNew groups:")
    for g in NEW_GROUPS:
        try:
            contacts = get_group_contacts(g)
            count = len(contacts)
        except Exception:
            count = 0
        new_total += count
        logger.info(f"  {g}: {count}")

    logger.info(f"\nOld total: {old_total}")
    logger.info(f"New total: {new_total}")

    # Note: contacts may appear in multiple old groups, so new_total may be less
    if new_total > 0:
        logger.info("✅ New groups populated. Review counts above.")
        logger.info("Note: some contacts were in multiple old groups — dedup expected.")
    else:
        logger.info("⚠️ New groups empty. Migration may not have run yet.")


def main():
    parser = argparse.ArgumentParser(description="LSAM Group Migration Tool")
    parser.add_argument("--audit", action="store_true", help="Audit DAMAGED group (read-only)")
    parser.add_argument("--migrate", action="store_true", help="Execute migration")
    parser.add_argument("--verify", action="store_true", help="Verify post-migration state")
    parser.add_argument("--json", action="store_true", help="Output audit as JSON")

    args = parser.parse_args()

    if args.audit:
        cmd_audit(as_json=args.json)
    elif args.migrate:
        print("⚠️  This will create new groups and move contacts.")
        print("    Run --audit first to review classification.")
        confirm = input("    Proceed? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            return
        cmd_migrate()
    elif args.verify:
        cmd_verify()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
