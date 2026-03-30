#!/usr/bin/env python3
"""
LSAM Profile Quality Auditor — v1.0 (2026-03-12)
==================================================
Phase 4 of the Master Plan: scan archived profiles for DOM-polluted fields.

SAFETY: Read-only by default.
        --add-to-group writes to macOS Contacts groups only — no contact data modified.

Pollution patterns detected:
  LOCATION    — field contains LinkedIn UI artifacts (language selectors, auth prompts, etc.)
  COMPANY     — field ends with " logo" (DOM text from company logo element leaked)
  ROLE        — field contains " logo" (same DOM leak in current_role)
  EMPTY_XPFED — both experience and education arrays are empty (possible scrape failure)

Modes:
  (default)           Scan archive, write CSV to logs/, print summary
  --output FILE       Write CSV to FILE
  --add-to-group      Add HIGH severity contacts to 'script-LSAM-Force-Refresh' (requires --confirm)
  --confirm           Required with --add-to-group
  --archive DIR       Override archive directory (default: logs/archive/applied)

Usage:
  python3 scripts/profile_quality_audit.py
  python3 scripts/profile_quality_audit.py --output logs/quality_audit.csv
  python3 scripts/profile_quality_audit.py --add-to-group --confirm

See AUDIT_2026-03-11.md §R4 for context.
"""

import argparse
import csv
import datetime
import json
import logging
import os
import re
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("profile_quality_audit")

# Default paths (relative to project root — run from project root)
ARCHIVE_DIR = "logs/archive/applied"
LOG_DIR = "logs"
FORCE_REFRESH_GROUP = "script-LSAM-Force-Refresh"

# ---------------------------------------------------------------------------
# DOM pollution detection
# ---------------------------------------------------------------------------

# Patterns that should never appear in a real location field (case-insensitive)
_LOCATION_UI_PATTERNS = [
    (r"\[",            "BRACKET_ARTIFACT"),    # "[contains LinkedIn UI...]"
    (r"language",      "LANGUAGE_SELECTOR"),   # LinkedIn language picker bled in
    (r"sign in",       "AUTH_PROMPT"),         # LinkedIn auth UI bled in
    (r"see more",      "EXPAND_BUTTON"),       # Expand button text bled in
    (r"\blinkedin\b",  "BRAND_TEXT"),          # LinkedIn brand text in location field
    (r"connection",    "CONNECTION_COUNT_UI"), # "X connections" UI bled in
    (r"follower",      "FOLLOWER_COUNT_UI"),   # "X followers" UI bled in
    (r"footer",        "FOOTER_TEXT"),         # Page footer bled in
    (r"navigation",    "NAV_TEXT"),            # Navigation element bled in
    (r"cookie",        "COOKIE_BANNER"),       # Cookie consent banner bled in
]

_LOCATION_MAX_CHARS = 200  # Anything longer is almost certainly a DOM text blob


def check_location(location: str | None) -> str | None:
    """Return a pollution label, or None if the location looks clean."""
    if not location:
        return None
    if len(location) > _LOCATION_MAX_CHARS:
        return f"TOO_LONG ({len(location)} chars)"
    lower = location.lower()
    for pat, label in _LOCATION_UI_PATTERNS:
        if re.search(pat, lower):
            return label
    return None


def check_company(company: str | None) -> str | None:
    """Return a pollution label if the company field looks polluted."""
    if not company:
        return None
    # " logo" appended = DOM text from <img alt="Company logo"> bled into text
    if re.search(r"\blogo\b", company, re.IGNORECASE):
        return "COMPANY_LOGO_SUFFIX"
    return None


def check_role(role: str | None) -> str | None:
    """Return a pollution label if the current_role field looks polluted."""
    if not role:
        return None
    if re.search(r"\blogo\b", role, re.IGNORECASE):
        return "ROLE_LOGO_SUFFIX"
    return None


# ---------------------------------------------------------------------------
# Archive scanner
# ---------------------------------------------------------------------------

def scan_archive(archive_dir: str) -> list[dict]:
    """
    Walk archive_dir recursively, load each profile.json, collect pollution records.
    Returns list of dicts sorted by severity (HIGH first) then full_name.
    """
    if not os.path.isdir(archive_dir):
        logger.error(f"Archive directory not found: '{archive_dir}'. Run from project root.")
        sys.exit(1)

    records = []
    scanned = 0

    for session_name in sorted(os.listdir(archive_dir)):
        session_path = os.path.join(archive_dir, session_name)
        if not os.path.isdir(session_path):
            continue

        for contact_dir in sorted(os.listdir(session_path)):
            contact_path = os.path.join(session_path, contact_dir)
            if not os.path.isdir(contact_path):
                continue

            profile_path = os.path.join(contact_path, "profile.json")
            if not os.path.exists(profile_path):
                continue

            scanned += 1
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as exc:
                logger.warning(f"Cannot read {profile_path}: {exc}")
                continue

            full_name  = profile.get("full_name", contact_dir.replace("_", " "))
            contact_id = profile.get("_contact_id", "")
            location   = profile.get("location")
            company    = profile.get("company")
            role       = profile.get("current_role")
            experience = profile.get("experience", [])
            education  = profile.get("education", [])

            flags   = []
            reasons = []

            loc_issue = check_location(location)
            if loc_issue:
                flags.append("LOCATION")
                reasons.append(f"location: {loc_issue}")

            co_issue = check_company(company)
            if co_issue:
                flags.append("COMPANY")
                reasons.append(f"company: {co_issue}")

            role_issue = check_role(role)
            if role_issue:
                flags.append("ROLE")
                reasons.append(f"role: {role_issue}")

            # Both arrays empty may indicate a failed scrape — flag as LOW severity
            if not experience and not education:
                flags.append("EMPTY_XPFED")
                reasons.append("experience=[] AND education=[]")

            if not flags:
                continue  # Clean profile

            # HIGH = definitive UI contamination; LOW = ambiguous empty arrays
            has_definitive = any(f in flags for f in ("LOCATION", "COMPANY", "ROLE"))
            severity = "HIGH" if has_definitive else "LOW"

            records.append({
                "full_name":  full_name,
                "contact_id": contact_id,
                "session":    session_name,
                "severity":   severity,
                "flags":      "|".join(flags),
                "location":   (location or "")[:120],   # truncate for CSV readability
                "company":    (company  or "")[:80],
                "role":       (role     or "")[:80],
                "reasons":    "; ".join(reasons),
            })

    logger.info(f"Scanned {scanned} profiles across {archive_dir}")
    # HIGH first, then alphabetical within severity
    records.sort(key=lambda r: (0 if r["severity"] == "HIGH" else 1, r["full_name"]))
    return records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "full_name", "contact_id", "session", "severity", "flags",
    "location", "company", "role", "reasons",
]


def write_csv(records: list[dict], output_path: str) -> None:
    """Write pollution records to a CSV file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    logger.info(f"CSV written to: {output_path}")


def _separator():
    print("=" * 60)


def print_summary(records: list[dict]) -> None:
    high = [r for r in records if r["severity"] == "HIGH"]
    low  = [r for r in records if r["severity"] == "LOW"]
    _separator()
    print(f"PROFILE QUALITY AUDIT — {len(records)} polluted profiles found")
    _separator()
    print(f"  HIGH severity (definitive DOM pollution): {len(high)}")
    for r in high[:10]:
        print(f"    {r['full_name']:<40} [{r['flags']}] — {r['reasons']}")
    if len(high) > 10:
        print(f"    ... and {len(high) - 10} more (see CSV)")
    print()
    print(f"  LOW  severity (empty experience+education): {len(low)}")
    if not records:
        print("\n✅ Archive is clean. No action needed.")


# ---------------------------------------------------------------------------
# Add to Force Refresh group
# ---------------------------------------------------------------------------

def add_to_force_refresh(records: list[dict]) -> tuple[int, int]:
    """
    Add HIGH severity contacts to FORCE_REFRESH_GROUP via osascript.
    Returns (ok_count, fail_count).
    MORENO_GUARD: No contact data is modified; only group membership is changed.
    """
    high = [r for r in records if r["severity"] == "HIGH"]
    if not high:
        print("No HIGH severity records — nothing to add to Force Refresh group.")
        return 0, 0

    ok = fail = 0
    for r in high:
        name = r["full_name"].replace('"', '\\"')   # escape double-quotes for AppleScript
        script = (
            f'tell application "Contacts"\n'
            f'    try\n'
            f'        set g to group "{FORCE_REFRESH_GROUP}"\n'
            f'        set p to (first person whose name is "{name}")\n'
            f'        add p to g\n'
            f'    on error errMsg\n'
            f'        log errMsg\n'
            f'    end try\n'
            f'end tell\n'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            ok += 1
            logger.info(f"  ✓ Added to '{FORCE_REFRESH_GROUP}': {r['full_name']}")
        else:
            fail += 1
            logger.warning(f"  ✗ Failed for {r['full_name']}: {result.stderr.strip()}")

    return ok, fail


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LSAM Profile Quality Auditor — v1.0 (2026-03-12)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output",
        help="Path for CSV output (default: logs/profile_quality_audit_TIMESTAMP.csv)",
    )
    parser.add_argument(
        "--add-to-group",
        action="store_true",
        help=f"Add HIGH severity contacts to '{FORCE_REFRESH_GROUP}'. Requires --confirm.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required with --add-to-group.",
    )
    parser.add_argument(
        "--archive",
        default=ARCHIVE_DIR,
        help=f"Archive directory to scan (default: {ARCHIVE_DIR})",
    )

    args = parser.parse_args()

    if args.add_to_group and not args.confirm:
        print(
            "ERROR: --add-to-group requires --confirm.\n"
            "Review the CSV output first, then re-run with --confirm."
        )
        sys.exit(1)

    logger.info(f"Scanning '{args.archive}' ...")
    records = scan_archive(args.archive)

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    output_path = args.output or os.path.join(LOG_DIR, f"profile_quality_audit_{ts}.csv")

    if records:
        write_csv(records, output_path)
        print(f"\nCSV: {output_path}")

    print_summary(records)

    if args.add_to_group:
        print(f"\nAdding HIGH severity contacts to '{FORCE_REFRESH_GROUP}'...")
        ok, fail = add_to_force_refresh(records)
        print(f"Done: {ok} added, {fail} failed.")
        print(
            "\nNEXT STEP: Run supervisor.py — the sync agent will re-scrape these\n"
            "contacts and overwrite DOM-polluted fields with fresh LinkedIn data."
        )
    elif records:
        high_count = sum(1 for r in records if r["severity"] == "HIGH")
        if high_count:
            print(
                f"\nTo add {high_count} HIGH severity contacts to '{FORCE_REFRESH_GROUP}':\n"
                f"  python3 scripts/profile_quality_audit.py --add-to-group --confirm"
            )


if __name__ == "__main__":
    main()
