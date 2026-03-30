#!/usr/bin/env python3
"""
bounce_handler.py — Mail Delivery Error Trigger (Manual Mode)
Sprint 4 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 3.3)

Phase 1 (Option B): Manual queue-for-refresh.
User selects bounced contacts in Contacts.app, this script adds them to LSAM-Queue.

Usage:
    python3 scripts/bounce_handler.py --selection        # Queue currently selected contacts
    python3 scripts/bounce_handler.py --name "John Doe"  # Queue by name
    python3 scripts/bounce_handler.py --email "x@y.com"  # Find contact by bounced email, queue

Author: Claude Opus 4.6 (1M context) | 2026-03-29
"""

import argparse
import json
import logging
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
TARGET_GROUP = "LSAM-Queue"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("bounce_handler")


def _run_osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"osascript error: {result.stderr.strip()}")
    return result.stdout.strip()


def get_selection() -> list[dict]:
    """Get currently selected contacts in Contacts.app."""
    script = '''
tell application "Contacts"
    set output to ""
    set sel to selection
    repeat with p in sel
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


def find_by_email(email: str) -> list[dict]:
    """Find contacts matching a given email address."""
    script = f'''
tell application "Contacts"
    set output to ""
    set matches to (every person whose value of emails contains "{email}")
    repeat with p in matches
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


def find_by_name(name: str) -> list[dict]:
    """Find contacts matching a name."""
    script = f'''
tell application "Contacts"
    set output to ""
    set matches to (every person whose name contains "{name}")
    repeat with p in matches
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
    parser = argparse.ArgumentParser(description="LSAM Bounce Handler — queue contacts with delivery errors")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--selection", action="store_true", help="Queue currently selected contacts in Contacts.app")
    source.add_argument("--name", help="Queue contact by name")
    source.add_argument("--email", help="Find contact by bounced email address and queue")
    parser.add_argument("--group", default=TARGET_GROUP, help=f"Target group (default: {TARGET_GROUP})")
    args = parser.parse_args()

    if args.selection:
        contacts = get_selection()
        if not contacts:
            logger.info("No contacts selected in Contacts.app")
            return
    elif args.email:
        contacts = find_by_email(args.email)
        if not contacts:
            logger.info(f"No contact found with email: {args.email}")
            return
    elif args.name:
        contacts = find_by_name(args.name)
        if not contacts:
            logger.info(f"No contact found matching: {args.name}")
            return

    logger.info(f"Found {len(contacts)} contact(s) to queue for refresh:")
    success = 0
    for c in contacts:
        if add_to_group(c["id"], args.group):
            logger.info(f"  ✅ {c['name']} → {args.group}")
            success += 1
        else:
            logger.warning(f"  ❌ Failed to add {c['name']}")

    logger.info(f"\nQueued {success}/{len(contacts)} for refresh in {args.group}")


if __name__ == "__main__":
    main()
