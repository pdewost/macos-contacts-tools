#!/usr/bin/env python3
"""
apply_not_available_fix.py — LSAM Last Name Restoration Tool
Reads recovery_not_available.json and writes the correct last name back
to macOS Contacts for each damaged contact.

Safety:
  - Dry-run by default (pass --live to apply changes)
  - Creates a timestamped session backup dir and backs up each contact
    before writing (Moreno Rule 3)
  - Uses AppleScript person id (abuid from X-ABUID VCF field)
  - Never deletes any contact
  - Skips entries whose abuid is empty or whose current last name is
    already correct (idempotent)
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).parent.parent
REPORT  = ROOT / "logs" / "recovery_not_available.json"
SESSIONS = ROOT / "logs" / "sessions"


def run_osascript(script: str) -> tuple[str, str, int]:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def backup_contact(abuid: str, name_slug: str, session_backup_dir: Path) -> bool:
    """Export VCF + txt before modifying. Returns True on success."""
    contact_dir = session_backup_dir / name_slug
    contact_dir.mkdir(parents=True, exist_ok=True)
    # VCF export
    vcf_script = f'''
tell application "Contacts"
    set p to person id "{abuid}"
    return vCard of p
end tell'''
    vcf_out, _, rc = run_osascript(vcf_script)
    if rc == 0 and vcf_out:
        (contact_dir / f"{name_slug}-pre-fix.vcf").write_text(vcf_out, encoding="utf-8")
    # Text summary
    txt_script = f'''
tell application "Contacts"
    set p to person id "{abuid}"
    set fn to first name of p
    set ln to last name of p
    return "FN:" & fn & return & "LN:" & ln
end tell'''
    txt_out, _, _ = run_osascript(txt_script)
    (contact_dir / f"{name_slug}-pre-fix.txt").write_text(txt_out, encoding="utf-8")
    return True


def current_last_name(abuid: str) -> str | None:
    script = f'''
tell application "Contacts"
    set p to person id "{abuid}"
    return last name of p
end tell'''
    out, err, rc = run_osascript(script)
    if rc != 0:
        return None
    return out.strip()


def set_last_name(abuid: str, last_name: str) -> bool:
    # Escape double quotes in last_name for AppleScript
    safe_ln = last_name.replace('"', '\\"')
    script = f'''
tell application "Contacts"
    set p to person id "{abuid}"
    set last name of p to "{safe_ln}"
    save
end tell'''
    _, err, rc = run_osascript(script)
    if rc != 0:
        print(f"    ✗ AppleScript error: {err}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Restore NOT AVAILABLE last names")
    parser.add_argument("--live", action="store_true",
                        help="Apply changes (default: dry-run, report only)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max contacts to process (0 = all)")
    args = parser.parse_args()

    if not REPORT.exists():
        print(f"ERROR: recovery JSON not found at {REPORT}")
        print("Run: python3 scripts/recover_not_available.py first")
        sys.exit(1)

    data = json.loads(REPORT.read_text(encoding="utf-8"))
    plan = data.get("recovered", [])

    if not plan:
        print("No recoverable contacts in plan.")
        sys.exit(0)

    mode = "LIVE" if args.live else "DRY-RUN"
    print(f"\n{'='*68}")
    print(f"  LSAM — Last Name Restoration  [{mode}]")
    print(f"  Contacts to fix: {len(plan)}")
    if not args.live:
        print("  Pass --live to apply changes.")
    print(f"{'='*68}\n")

    session_ts = datetime.now().strftime("fix_%Y-%m-%d_%H-%M-%S")
    session_backup_dir = SESSIONS / session_ts / "backups"

    ok = skipped = errors = 0
    limit = args.limit if args.limit > 0 else len(plan)

    for i, entry in enumerate(plan[:limit]):
        abuid = entry.get("abuid", "")
        recovered_ln = entry.get("recovered_last_name", "")
        first_name = entry.get("first_name", "?")
        source = entry.get("source", "?")

        if not abuid:
            print(f"  [{i+1:02d}] SKIP {first_name} — no abuid")
            skipped += 1
            continue
        if not recovered_ln:
            print(f"  [{i+1:02d}] SKIP {first_name} — no recovered last name")
            skipped += 1
            continue

        # Verify current state
        cur_ln = current_last_name(abuid)
        if cur_ln is None:
            print(f"  [{i+1:02d}] ERROR {first_name} — contact not found in Contacts.app ({abuid})")
            errors += 1
            continue
        # v2: check all placeholder variants, not just the exact "NOT AVAILABLE" string
        DAMAGED_SET = {
            "NOT AVAILABLE", "AVAILABLE",
            "INFORMATION NOT AVAILABLE", "NO DATA AVAILABLE",
            "DATA NOT AVAILABLE", "DATA UNAVAILABLE",
            "N/A", "UNKNOWN", "PAGE NOT FOUND", "PAGE DOESN'T EXIST",
            "THE WORLD'S LARGEST PROFESSIONAL NETWORK",
            "LINKEDIN MEMBER", "MEMBER",
        }
        cur_ln_up = cur_ln.upper()
        is_damaged = cur_ln_up in DAMAGED_SET or any(
            cur_ln_up.startswith(p) for p in DAMAGED_SET
        )
        if not is_damaged:
            print(f"  [{i+1:02d}] SKIP {first_name} {cur_ln!r} — already correct")
            skipped += 1
            continue

        name_slug = f"{first_name}_{recovered_ln}".replace(" ", "_").replace("/", "_")
        print(f"  [{i+1:02d}] {first_name} NOT AVAILABLE  →  {first_name} {recovered_ln}  [{source}]")

        if not args.live:
            ok += 1
            continue

        # Backup
        backup_contact(abuid, name_slug, session_backup_dir)

        # Write
        if set_last_name(abuid, recovered_ln):
            print(f"       ✓ Written")
            ok += 1
        else:
            errors += 1

    print(f"\n{'='*68}")
    print(f"  {'Applied' if args.live else 'Would apply'}: {ok}  |  Skipped: {skipped}  |  Errors: {errors}")
    if args.live and ok > 0:
        print(f"  Backups: {session_backup_dir}")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    main()
