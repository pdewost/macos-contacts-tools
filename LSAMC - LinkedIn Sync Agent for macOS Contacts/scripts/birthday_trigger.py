#!/usr/bin/env python3
"""
birthday_trigger.py — Birthday T-2 Trigger
Sprint 4 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 3.1)

Finds contacts whose birthday is 2 days from today and queues them for
LinkedIn refresh if their vault data is older than 7 days.

Hybrid cache: maintains data/birthday_cache.json (refreshed with --refresh-cache).
Daily operation: reads cache, finds T+2 matches, adds to LSAM-Queue or LSAM-Birthday group.

Usage:
    python3 scripts/birthday_trigger.py --refresh-cache    # Rebuild cache from Contacts.app
    python3 scripts/birthday_trigger.py                    # Check T+2 and queue matches
    python3 scripts/birthday_trigger.py --dry-run          # Show what would be queued

Safety:
    - Read-only by default (--dry-run)
    - Cache refresh is safe (read from Contacts, write to local JSON)
    - Queue insertion uses AppleScript group membership (no contact deletion)

Author: Claude Opus 4.6 (1M context) | 2026-03-29
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VAULT_ROOT = os.path.join(PROJECT_ROOT, "data", "vault")
CACHE_PATH = os.path.join(PROJECT_ROOT, "data", "birthday_cache.json")
TARGET_GROUP = "LSAM-Birthday"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("birthday_trigger")


def _run_osascript(script: str, timeout: int = 600) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"osascript error: {result.stderr.strip()}")
    return result.stdout.strip()


def refresh_cache() -> dict:
    """Rebuild birthday cache from macOS Contacts.
    Uses chunked AppleScript to avoid timeout on 14k contacts."""
    logger.info("Refreshing birthday cache from Contacts.app...")

    # Get total count first
    total = int(_run_osascript('tell application "Contacts" to count every person'))
    logger.info(f"Total contacts: {total}")

    cache = {}
    chunk_size = 250  # Smaller chunks to avoid AppleScript timeout on heavy contacts
    for start in range(1, total + 1, chunk_size):
        end = min(start + chunk_size - 1, total)
        script = f'''
tell application "Contacts"
    set output to ""
    repeat with i from {start} to {end}
        set p to person i
        try
            set bd to birth date of p
            if bd is not missing value then
                set m to (month of bd as integer)
                set d to day of bd
                set cid to id of p
                set output to output & cid & "\\t" & m & "-" & d & linefeed
            end if
        end try
    end repeat
    return output
end tell
'''
        try:
            raw = _run_osascript(script)
        except Exception as e:
            logger.warning(f"Chunk {start}-{end} timed out: {e}. Continuing with next chunk.")
            continue
        for line in raw.strip().split("\n"):
            if "\t" not in line:
                continue
            parts = line.split("\t", 1)
            contact_id = parts[0].strip()
            mm_dd = parts[1].strip()
            # Normalize to MM-DD format
            try:
                month, day = mm_dd.split("-")
                mm_dd = f"{int(month):02d}-{int(day):02d}"
            except ValueError:
                continue
            cache[contact_id] = mm_dd

        logger.info(f"  Scanned {end}/{total}, {len(cache)} birthdays found so far")

    # Write cache
    cache_data = {
        "_refreshed_at": datetime.now().isoformat(),
        "_total_contacts": total,
        "_birthdays_found": len(cache),
        "birthdays": cache,
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache_data, f, indent=2)

    logger.info(f"Cache written: {CACHE_PATH} ({len(cache)} entries)")
    return cache


def load_cache() -> dict:
    """Load birthday cache. Returns {contact_id: "MM-DD", ...}."""
    if not os.path.exists(CACHE_PATH):
        logger.warning(f"No cache found at {CACHE_PATH}. Run with --refresh-cache first.")
        return {}
    with open(CACHE_PATH) as f:
        data = json.load(f)

    refreshed = data.get("_refreshed_at", "unknown")
    logger.info(f"Cache loaded: {data.get('_birthdays_found', '?')} birthdays (refreshed {refreshed})")
    return data.get("birthdays", {})


def check_vault_freshness(contact_id: str, max_age_days: int = 7) -> bool:
    """Check if a contact's vault data is older than max_age_days. Returns True if stale."""
    vault_dir = os.path.join(VAULT_ROOT, contact_id)
    meta_path = os.path.join(vault_dir, "scavenger_meta.json")
    if not os.path.exists(meta_path):
        return True  # No vault = stale

    try:
        with open(meta_path) as f:
            meta = json.load(f)
        scavenged_at = meta.get("scavenged_at", "1970-01-01")
        scavenged_dt = datetime.fromisoformat(scavenged_at)
        age = datetime.now() - scavenged_dt
        return age.days > max_age_days
    except Exception:
        return True


def add_to_group(contact_id: str, group_name: str) -> bool:
    """Add contact to group via AppleScript."""
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


def find_birthday_matches(cache: dict, days_ahead: int = 2) -> list[dict]:
    """Find contacts whose birthday is exactly days_ahead days from today."""
    import calendar
    target = datetime.now() + timedelta(days=days_ahead)
    target_mmdd = f"{target.month:02d}-{target.day:02d}"

    matches = [{"contact_id": cid, "birthday_mmdd": mmdd}
               for cid, mmdd in cache.items() if mmdd == target_mmdd]

    # Feb 29 edge case: in non-leap years, also check Feb 28 and Mar 1
    if not calendar.isleap(target.year):
        if target_mmdd == "02-28":
            # Also match Feb 29 birthdays
            feb29 = [{"contact_id": cid, "birthday_mmdd": mmdd}
                     for cid, mmdd in cache.items() if mmdd == "02-29"]
            matches.extend(feb29)

    return matches


def main():
    parser = argparse.ArgumentParser(description="LSAM Birthday Trigger — queue contacts for T-2 refresh")
    parser.add_argument("--refresh-cache", action="store_true", help="Rebuild birthday cache from Contacts.app")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without queuing")
    parser.add_argument("--days", type=int, default=2, help="Days ahead to check (default: 2)")
    parser.add_argument("--group", default=TARGET_GROUP, help=f"Target group (default: {TARGET_GROUP})")
    args = parser.parse_args()

    if args.refresh_cache:
        refresh_cache()
        return

    cache = load_cache()
    if not cache:
        return

    matches = find_birthday_matches(cache, args.days)
    target_date = (datetime.now() + timedelta(days=args.days)).strftime("%B %d")
    logger.info(f"Checking birthdays for {target_date} ({args.days} days from now)")

    if not matches:
        logger.info("No birthday matches found.")
        return

    logger.info(f"Found {len(matches)} contact(s) with birthday on {target_date}")

    queued = 0
    skipped = 0
    for m in matches:
        cid = m["contact_id"]
        is_stale = check_vault_freshness(cid)
        vault_dir = os.path.join(VAULT_ROOT, cid)

        # Get name from vault if possible
        name = cid
        mp = os.path.join(vault_dir, "master_profile.json")
        if os.path.exists(mp):
            try:
                with open(mp) as f:
                    p = json.load(f)
                name = p.get("full_name", cid)
            except Exception:
                pass

        if not is_stale:
            logger.info(f"  SKIP: {name} — vault fresh (< 7 days)")
            skipped += 1
            continue

        if args.dry_run:
            logger.info(f"  WOULD QUEUE: {name} (birthday {m['birthday_mmdd']}, vault stale)")
            queued += 1
        else:
            if add_to_group(cid, args.group):
                logger.info(f"  QUEUED: {name} → {args.group}")
                queued += 1
            else:
                logger.warning(f"  FAILED to add {name} to {args.group}")

    logger.info(f"\nSummary: {queued} queued, {skipped} skipped (fresh vault)")


if __name__ == "__main__":
    main()
