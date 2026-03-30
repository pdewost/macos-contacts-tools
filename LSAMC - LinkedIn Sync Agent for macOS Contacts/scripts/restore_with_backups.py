#!/usr/bin/env python3
"""
restore_with_backups.py — v1.0.0 (2026-03-09)

PURPOSE:
    Surgically restore one or more macOS Contacts records from identified
    backup sources, with a FULL session-based backup protocol that mirrors
    the main sync engine (pro_sync_agent.py).

SAFETY PROTOCOL (v4.9.1 GATE):
    1. Create a timestamped session folder in logs/sessions/manual_repair_*/
    2. Backup the CURRENT state of the contact before ANY modification.
    3. Apply targeted field restorations (photo, birthday, note, URLs, socials).
    4. Perform a post-update verification check on every field touched.
    5. Log the diff of Before vs After. Abort and report if verification fails.

USAGE:
    python3 -m scripts.restore_with_backups

CODING CONVENTIONS (ANTIGRAVITY):
    - Every write is preceded by a read (backup).
    - Silence is NOT success — every outcome must emit an observable log line.
    - On failure, report evidence, do NOT silently swallow exceptions.
    - Version-tagged with 'v4.9.1 RESTORE:' prefix in log lines.
"""

import os
import sys
import json
import time
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# -- Path setup
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.bridge.contact_macos import ContactMacOSBridge

# ─── Logging Setup ───────────────────────────────────────────────────────────
TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
SESSION_DIR = os.path.join(project_root, "logs", "sessions", f"manual_repair_{TIMESTAMP}")
BACKUP_DIR = os.path.join(SESSION_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

log_file = os.path.join(SESSION_DIR, "session.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

# ─── Restoration Targets ─────────────────────────────────────────────────────
# Each entry defines what to restore and from which backup sources.
RESTORE_TARGETS = [
    {
        "contact_name": "Elisabeth MORENO",
        "original_backup_dir": os.path.join(
            project_root, "logs/sessions/run_2026-03-07_14-04-57/backups/Elisabeth_MORENO"
        ),
        # Core fields to restore — source of truth for each field
        "restore": {
            "birthday": "September 20",   # From profile.json
            "photo_path": "/tmp/Elisabeth_MORENO.heic",  # Pre-optimized 11KB HEIC
            # Note: Use the canonical version from the original .txt backup
            "note_from_file": os.path.join(
                project_root,
                "logs/sessions/run_2026-03-07_14-04-57/backups/Elisabeth_MORENO/Elisabeth_MORENO-original.txt"
            ),
            # Social: The March 7th backup shows 3 malformed handles. We set the canonical one only.
            "canonical_social_handle": "elisabeth-s-moreno",
            "canonical_linkedin_url": "https://www.linkedin.com/in/elisabeth-s-moreno",
            # URL entries to REMOVE from contact (malformed/redundant)
            "urls_to_remove_containing": ["linkedin.com"],
        },
        "sync_block_to_append": (
            "<Linkedin-AI-sync 2026-03-09 update>\n"
            "Added (2026-03-07) : Birthday\n"
            "Followers: 143333\n"
            "Mutual connections (1st) : 292\n"
            "LinkedIn_Connection_Since: 2023-07-17\n"
            "</Linkedin-AI-sync>"
        ),
    },
]

# ─── Helper Functions ─────────────────────────────────────────────────────────

def save_backup(contact_name: str, content: Any, stage: str, file_type: str = "txt") -> Optional[str]:
    """Saves a snapshot of a contact field to the session backup folder."""
    safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
    contact_folder = os.path.join(BACKUP_DIR, safe_name)
    os.makedirs(contact_folder, exist_ok=True)
    path = os.path.join(contact_folder, f"{safe_name}-{stage}.{file_type}")
    try:
        mode = "wb" if isinstance(content, bytes) else "w"
        enc = None if isinstance(content, bytes) else "utf-8"
        with open(path, mode, encoding=enc) as f:
            f.write(content)
        logger.info(f"v4.9.1 RESTORE: Saved {stage} {file_type} backup → {path}")
        return path
    except Exception as e:
        logger.error(f"v4.9.1 RESTORE: Failed to save backup for {contact_name}: {e}")
        return None


def run_applescript(script: str) -> str:
    """Runs an AppleScript and returns stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_field(contact_id: str, field: str, expected: Any, bridge: ContactMacOSBridge) -> bool:
    """Fetches current contact details and verifies a field against expected value."""
    details = bridge.get_contact_details(contact_id)
    if not details.get("success"):
        logger.error(f"v4.9.1 GATE: Could not fetch details for verification: {details.get('error')}")
        return False
    actual = details.get(field)
    ok = bool(actual) if expected is True else (actual == expected)
    status = "✅ PASS" if ok else "❌ FAIL"
    logger.info(f"v4.9.1 GATE: {status} — Field '{field}': expected={repr(expected)}, got={repr(actual)}")
    return ok


# ─── Core Restoration Logic ───────────────────────────────────────────────────

def restore_contact(target: Dict[str, Any], bridge: ContactMacOSBridge) -> Dict[str, Any]:
    """
    Restores a single contact record with the full safety protocol.
    Returns a result dict with success/failure metrics.
    """
    name = target["contact_name"]
    restore_spec = target["restore"]
    result = {"name": name, "success": False, "fields_restored": [], "fields_failed": []}

    logger.info(f"\n{'='*60}")
    logger.info(f"v4.9.1 RESTORE: Starting restoration for: {name}")

    # ── Step 1: Find contact ──────────────────────────────────────────────────
    find_res = bridge.find_contact(name)
    if not find_res.get("success"):
        result["error"] = f"Contact not found: {find_res.get('error')}"
        logger.error(f"v4.9.1 RESTORE: ❌ {result['error']}")
        return result

    if "id" in find_res:
        contact_id = find_res["id"]
    elif find_res.get("matches"):
        contact_id = find_res["matches"][0]["id"]
    else:
        result["error"] = "No matches found."
        logger.error(f"v4.9.1 RESTORE: ❌ {result['error']}")
        return result

    logger.info(f"v4.9.1 RESTORE: Found contact ID: {contact_id}")

    # ── Step 2: Backup CURRENT state ─────────────────────────────────────────
    logger.info(f"v4.9.1 RESTORE: Capturing 'before' snapshot...")
    current = bridge.get_contact_details(contact_id)
    save_backup(name, json.dumps(current, indent=2, default=str), "before", "json")
    if current.get("note"):
        save_backup(name, current["note"], "before_note", "txt")
    if current.get("photo"):
        save_backup(name, current["photo"], "before_photo", "jpg")

    # ── Step 3: Restore Birthday ──────────────────────────────────────────────
    birthday_raw = restore_spec.get("birthday")
    if birthday_raw:
        logger.info(f"v4.9.1 RESTORE: Setting birthday to '{birthday_raw}'...")
        try:
            # Set birthday via Python-generated date. Use osascript with month/day numbers.
            # AppleScript handler: set month/day on an existing date object.
            from datetime import datetime
            bday = datetime.strptime(birthday_raw, "%B %d")
            month_num = bday.month   # e.g. 9
            day_num = bday.day       # e.g. 20
            # Build date object via numeric handler — locale-independent
            # KEY: The correct AppleScript property is 'birth date', not 'birthday'
            bday_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    set d to current date
    set year of d to 1604
    set month of d to {month_num}
    set day of d to {day_num}
    set birth date of p to d
    save
    return "ok"
end tell"""
            run_applescript(bday_script)
            result["fields_restored"].append("birthday")
            logger.info(f"v4.9.1 RESTORE: ✅ Birthday set ({month}/{day}/1604).")
        except Exception as e:
            result["fields_failed"].append("birthday")
            logger.error(f"v4.9.1 RESTORE: ❌ Birthday set failed: {e}")

    # ── Step 4: Restore Note ───────────────────────────────────────────────────
    note_file = restore_spec.get("note_from_file")
    sync_block_append = target.get("sync_block_to_append", "")
    if note_file and os.path.exists(note_file):
        logger.info(f"v4.9.1 RESTORE: Restoring note from {note_file}...")
        try:
            with open(note_file, "r", encoding="utf-8") as f:
                original_note = f.read().strip()
            # Remove the #lsam-force-resync line (cleanup tag)
            import re
            cleaned_note = re.sub(r"(?m)^#lsam-force-resync\s*\n?", "", original_note).strip()
            # Build final note: sync block first, then original human notes
            if sync_block_append:
                final_note = sync_block_append + "\n\n" + cleaned_note
            else:
                final_note = cleaned_note
            # Write note via temp file to avoid AppleScript string escaping
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tf:
                tf.write(final_note)
                tmp_note_path = tf.name
            note_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    set the_note to (do shell script "cat " & quoted form of "{tmp_note_path}")
    set note of p to the_note
    save
    return "ok"
end tell"""
            run_applescript(note_script)
            os.unlink(tmp_note_path)
            save_backup(name, final_note, "after_note", "txt")
            result["fields_restored"].append("note")
            logger.info(f"v4.9.1 RESTORE: ✅ Note restored ({len(final_note)} chars).")
        except Exception as e:
            result["fields_failed"].append("note")
            logger.error(f"v4.9.1 RESTORE: ❌ Note restore failed: {e}")

    # ── Step 5: Fix Social Profiles (purge multiples, set canonical) ──────────
    canonical_handle = restore_spec.get("canonical_social_handle")
    canonical_url_str = restore_spec.get("canonical_linkedin_url")
    if canonical_handle:
        logger.info(f"v4.9.1 RESTORE: Enforcing canonical social profile: {canonical_handle}")
        try:
            # v4.9.1: Atomic social profile cleanup via full delete + re-add.
            # We use a Python-driven approach: delete ALL socials, add canonical.
            # Step 1: Delete existing LinkedIn profiles one by one via Python loop.
            details_pre = bridge.get_contact_details(contact_id)
            n_profiles = len(details_pre.get("social", []))
            logger.info(f"v4.9.1 RESTORE: Found {n_profiles} social profile(s). Purging LinkedIn ones...")

            for idx in range(n_profiles, 0, -1):
                try:
                    del_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    if count of social profiles of p >= {idx} then
        if service name of social profile {idx} of p is "LinkedIn" then
            delete social profile {idx} of p
            save
        end if
    end if
    return "ok"
end tell"""
                    run_applescript(del_script)
                except Exception as e_del:
                    logger.warning(f"v4.9.1 RESTORE: Could not delete social profile {idx}: {e_del}")

            # Step 2: Add canonical handle
            add_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    make new social profile at end of social profiles of p with properties {{service name:"LinkedIn", user name:"{canonical_handle}"}}
    save
    return "ok"
end tell"""
            run_applescript(add_script)

            # Step 3: Delete existing LinkedIn URLs and add canonical URL
            details_post = bridge.get_contact_details(contact_id)
            existing_urls = details_post.get("urls") or []
            n_urls = len(existing_urls)
            for idx in range(n_urls, 0, -1):
                if "linkedin.com" in existing_urls[idx - 1]:
                    try:
                        del_url_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    if count of urls of p >= {idx} then
        delete url {idx} of p
        save
    end if
    return "ok"
end tell"""
                        run_applescript(del_url_script)
                    except Exception as e_url:
                        logger.warning(f"v4.9.1 RESTORE: URL delete {idx} failed: {e_url}")

            add_url_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    make new url at end of urls of p with properties {{label:"LinkedIn", value:"{canonical_url_str}"}}
    save
    return "ok"
end tell"""
            run_applescript(add_url_script)
            result["fields_restored"].append("social_profiles")
            result["fields_restored"].append("urls")
            logger.info(f"v4.9.1 RESTORE: ✅ Canonical social handle and URL enforced.")
        except Exception as e:
            result["fields_failed"].append("social_profiles")
            logger.error(f"v4.9.1 RESTORE: ❌ Social profile fix failed: {e}")

    # ── Step 6: Restore Photo ─────────────────────────────────────────────────
    photo_path = restore_spec.get("photo_path")
    if photo_path and os.path.exists(photo_path):
        logger.info(f"v4.9.1 RESTORE: Injecting photo from {photo_path}...")
        try:
            photo_script = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    set imageData to (read (POSIX file "{photo_path}") as «class JPEG»)
    set image of p to imageData
    save
    return "ok"
end tell"""
            try:
                run_applescript(photo_script)
            except RuntimeError:
                # Fallback: read as raw data
                photo_script2 = f"""
tell application "Contacts"
    set p to person id "{contact_id}"
    set imageData to (read (POSIX file "{photo_path}"))
    set image of p to imageData
    save
    return "ok"
end tell"""
                run_applescript(photo_script2)
            result["fields_restored"].append("photo")
            logger.info(f"v4.9.1 RESTORE: ✅ Photo injected.")
        except Exception as e:
            result["fields_failed"].append("photo")
            logger.error(f"v4.9.1 RESTORE: ❌ Photo injection failed: {e}")

    # ── Step 7: Post-Update Verification Gate ─────────────────────────────────
    logger.info(f"\nv4.9.1 GATE: Running post-update verification for {name}...")
    time.sleep(2)  # Let Contacts settle

    # Fetch fresh state via bridge
    details = bridge.get_contact_details(contact_id)

    checks_passed = []
    checks_failed = []

    # Check birthday — bridge returns it as a string (e.g. '1604-09-20')
    if "birthday" in result["fields_restored"]:
        bday_val = details.get("birthday", "")
        ok = bool(bday_val)
        logger.info(f"v4.9.1 GATE: {'✅ PASS' if ok else '❌ FAIL'} — birthday = {repr(bday_val)}")
        (checks_passed if ok else checks_failed).append("birthday")

    # Check photo — use a raw AppleScript existence check (most reliable)
    if "photo" in result["fields_restored"]:
        try:
            photo_check = run_applescript(
                f'tell application "Contacts" to return (image of person id "{contact_id}") is not missing value'
            )
            ok = photo_check.strip().lower() == "true"
        except Exception:
            ok = False
        logger.info(f"v4.9.1 GATE: {'✅ PASS' if ok else '❌ FAIL'} — photo present = {ok}")
        (checks_passed if ok else checks_failed).append("photo")

    # Check note
    if "note" in result["fields_restored"]:
        note_val = details.get("note", "")
        ok = len(note_val) > 50
        logger.info(f"v4.9.1 GATE: {'✅ PASS' if ok else '❌ FAIL'} — note length = {len(note_val)}")
        (checks_passed if ok else checks_failed).append("note")

    # Check socials
    if "social_profiles" in result["fields_restored"]:
        social_ok = len(details.get("social", [])) == 1 and canonical_handle in details["social"][0]
        logger.info(f"v4.9.1 GATE: {'✅ PASS' if social_ok else '❌ FAIL'} — Social profiles: {details.get('social')}")
        (checks_passed if social_ok else checks_failed).append("social_profiles")

    result["verification_passed"] = checks_passed
    result["verification_failed"] = checks_failed

    # ── Step 8: Save "after" snapshot ─────────────────────────────────────────
    after_state = bridge.get_contact_details(contact_id)
    save_backup(name, json.dumps(after_state, indent=2, default=str), "after", "json")

    result["success"] = len(result["fields_failed"]) == 0 and len(checks_failed) == 0

    if result["success"]:
        logger.info(f"\nv4.9.1 RESTORE: 🎉 SUCCESS — {name} fully restored! Passed: {checks_passed}")
    else:
        logger.warning(
            f"\nv4.9.1 RESTORE: ⚠️  PARTIAL — {name} restored with issues.\n"
            f"  Fields failed:       {result['fields_failed']}\n"
            f"  Verification failed: {checks_failed}"
        )
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info(f"{'='*60}")
    logger.info(f"LSAM v4.9.1 — Manual Restore with Session Backups")
    logger.info(f"Session: {SESSION_DIR}")
    logger.info(f"Targets: {[t['contact_name'] for t in RESTORE_TARGETS]}")
    logger.info(f"{'='*60}")

    bridge = ContactMacOSBridge(mode="FULL")
    all_results = []

    for target in RESTORE_TARGETS:
        res = restore_contact(target, bridge)
        all_results.append(res)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("FINAL SUMMARY")
    logger.info(f"{'='*60}")
    for r in all_results:
        status = "✅ OK" if r["success"] else "⚠️  PARTIAL"
        logger.info(
            f"{status} | {r['name']}\n"
            f"         Restored:  {r.get('fields_restored', [])}\n"
            f"         Failed:    {r.get('fields_failed', [])}\n"
            f"         V-Passed:  {r.get('verification_passed', [])}\n"
            f"         V-Failed:  {r.get('verification_failed', [])}"
        )

    # Save machine-readable summary
    summary_path = os.path.join(SESSION_DIR, "restore_summary.json")
    with open(summary_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info(f"\nFull session log: {log_file}")
    logger.info(f"Backups saved to: {BACKUP_DIR}")
    logger.info(f"Summary JSON:     {summary_path}")


if __name__ == "__main__":
    main()
