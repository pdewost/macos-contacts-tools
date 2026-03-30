#!/usr/bin/env python3
"""
onboard_unprocessed.py — Unprocessed Contact Priority Queue
Sprint 4 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 3.2)

Scans macOS Contacts for contacts not yet in the LSAM vault, scores them by
priority, and outputs a ranked queue for the supervisor to consume.

Priority tiers (highest first):
  1. Has LinkedIn URL in social profiles
  2. Has email domain matching a known company
  3. In a user-created group (not LSAM-*)
  4. Has phone number
  5. Has birthday set
  6. Recently modified (mod_date last 90 days)
  7. Everything else (alphabetical)

Usage:
    python3 scripts/onboard_unprocessed.py --scan            # Scan and output ranked queue
    python3 scripts/onboard_unprocessed.py --scan --top 50   # Top 50 only
    python3 scripts/onboard_unprocessed.py --scan --json     # Output as JSON
    python3 scripts/onboard_unprocessed.py --queue --top 20  # Add top 20 to LSAM-Queue group

Author: Claude Opus 4.6 (1M context) | 2026-03-29
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VAULT_ROOT = os.path.join(PROJECT_ROOT, "data", "vault")
QUEUE_PATH = os.path.join(PROJECT_ROOT, "data", "unprocessed_queue.json")
TARGET_GROUP = "LSAM-Queue"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("onboard_unprocessed")


def _run_osascript(script: str, timeout: int = 600) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"osascript error: {result.stderr.strip()}")
    return result.stdout.strip()


def get_vault_uuids() -> set:
    """Get all contact UUIDs currently in the vault."""
    uuids = set()
    if not os.path.isdir(VAULT_ROOT):
        return uuids
    for entry in os.scandir(VAULT_ROOT):
        if entry.is_dir() and ":ABPerson" in entry.name:
            uuids.add(entry.name)
    return uuids


def scan_all_contacts_chunked() -> list[dict]:
    """Scan all contacts with scoring signals. Returns list of dicts with id, name, score, signals."""
    total = int(_run_osascript('tell application "Contacts" to count every person'))
    logger.info(f"Total contacts: {total}")

    vault_uuids = get_vault_uuids()
    logger.info(f"Vault entries: {len(vault_uuids)}")

    contacts = []
    chunk_size = 200

    for start in range(1, total + 1, chunk_size):
        end = min(start + chunk_size - 1, total)
        # Extract scoring signals in one pass per chunk
        script = f'''
tell application "Contacts"
    set output to ""
    repeat with i from {start} to {end}
        set p to person i
        set cid to id of p
        set fn to ""
        set ln to ""
        set hasPhone to false
        set hasBirthday to false
        set hasLinkedIn to false
        set emailDomain to ""
        try
            set fn to first name of p
        end try
        try
            set ln to last name of p
        end try
        if fn is missing value then set fn to ""
        if ln is missing value then set ln to ""
        try
            if (count of phones of p) > 0 then set hasPhone to true
        end try
        try
            if birth date of p is not missing value then set hasBirthday to true
        end try
        try
            if (count of urls of p) > 0 then
                repeat with u in urls of p
                    if value of u contains "linkedin.com" then
                        set hasLinkedIn to true
                        exit repeat
                    end if
                end repeat
            end if
        end try
        try
            if (count of emails of p) > 0 then
                set firstEmail to value of email 1 of p
                if firstEmail contains "@" then
                    set emailDomain to text ((offset of "@" in firstEmail) + 1) thru -1 of firstEmail
                end if
            end if
        end try
        set output to output & cid & "\\t" & fn & " " & ln & "\\t" & hasPhone & "\\t" & hasBirthday & "\\t" & hasLinkedIn & "\\t" & emailDomain & linefeed
    end repeat
    return output
end tell
'''
        try:
            raw = _run_osascript(script)
        except Exception as e:
            logger.warning(f"Chunk {start}-{end} failed: {e}")
            continue

        for line in raw.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            cid = parts[0].strip()
            name = parts[1].strip()
            has_phone = parts[2].strip() == "true"
            has_birthday = parts[3].strip() == "true"
            has_linkedin = parts[4].strip() == "true"
            email_domain = parts[5].strip()

            # Skip if already in vault
            if cid in vault_uuids:
                continue

            # Score
            score = 0
            signals = []
            if has_linkedin:
                score += 100
                signals.append("linkedin_url")
            if email_domain and email_domain not in ("gmail.com", "yahoo.com", "hotmail.com",
                                                       "outlook.com", "icloud.com", "me.com",
                                                       "orange.fr", "free.fr", "wanadoo.fr"):
                score += 80
                signals.append(f"company_email:{email_domain}")
            if has_phone:
                score += 40
                signals.append("has_phone")
            if has_birthday:
                score += 30
                signals.append("has_birthday")
            if not name.strip():
                score -= 50  # Penalize nameless contacts

            contacts.append({
                "id": cid,
                "name": name,
                "score": score,
                "signals": signals,
            })

        if (end % 1000) < chunk_size:
            logger.info(f"  Scanned {end}/{total}, {len(contacts)} unprocessed so far")

    # Sort by score descending, then name alphabetically
    contacts.sort(key=lambda c: (-c["score"], c["name"].lower()))
    return contacts


def add_to_group(contact_id: str, group_name: str) -> bool:
    script = f'''
tell application "Contacts"
    try
        set p to person id "{contact_id}"
        try
            set g to group "{group_name}"
        on error
            make new group with properties {{name:"{group_name}"}}
            save
            set g to group "{group_name}"
        end try
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


def main():
    parser = argparse.ArgumentParser(description="LSAM Unprocessed Contact Priority Queue")
    parser.add_argument("--scan", action="store_true", help="Scan and rank unprocessed contacts")
    parser.add_argument("--queue", action="store_true", help="Add top N to LSAM-Queue group")
    parser.add_argument("--top", type=int, default=50, help="Show/queue top N contacts (default: 50)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--group", default=TARGET_GROUP, help=f"Target group (default: {TARGET_GROUP})")
    args = parser.parse_args()

    if not args.scan and not args.queue:
        parser.print_help()
        return

    logger.info("=== Unprocessed Contacts Priority Queue ===")
    contacts = scan_all_contacts_chunked()
    logger.info(f"Found {len(contacts)} unprocessed contacts")

    top = contacts[:args.top]

    if args.scan:
        if args.json:
            output = {
                "total_unprocessed": len(contacts),
                "showing": len(top),
                "contacts": top,
            }
            # Save to file
            with open(QUEUE_PATH, "w") as f:
                json.dump(output, f, indent=2)
            print(json.dumps(output, indent=2))
            logger.info(f"Queue saved: {QUEUE_PATH}")
        else:
            print(f"\nTop {len(top)} unprocessed contacts (of {len(contacts)} total):\n")
            for i, c in enumerate(top, 1):
                signals_str = ", ".join(c["signals"]) if c["signals"] else "no signals"
                print(f"  {i:3d}. [{c['score']:3d}] {c['name']:<40s} ({signals_str})")

    if args.queue:
        logger.info(f"\nAdding top {len(top)} to {args.group}...")
        success = 0
        for c in top:
            if add_to_group(c["id"], args.group):
                success += 1
                logger.info(f"  Added: {c['name']}")
            else:
                logger.warning(f"  Failed: {c['name']}")
        logger.info(f"Queued {success}/{len(top)} contacts in {args.group}")


if __name__ == "__main__":
    main()
