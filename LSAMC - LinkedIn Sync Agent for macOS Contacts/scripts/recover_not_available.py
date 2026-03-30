#!/usr/bin/env python3
"""
recover_not_available.py — LSAM Recovery Tool
Find contacts whose last name was wiped to "NOT AVAILABLE" and locate their
correct last name from:
  1. Earlier session backups (matched by UID)
  2. LinkedIn slug heuristic (first-last-numbers pattern)
Outputs a JSON recovery plan + a human-readable report.
"""
import os
import re
import json
import sys
from pathlib import Path
from collections import defaultdict
from urllib.parse import unquote

ROOT = Path(__file__).parent.parent
SESSIONS = ROOT / "logs" / "sessions"
VAULT    = ROOT / "data" / "vault"
REPORT   = ROOT / "logs" / "recovery_not_available.json"
TEXT_RPT = ROOT / "logs" / "recovery_not_available.txt"


# ── VCF parsing helpers ────────────────────────────────────────────────────────

def parse_vcf(path: Path) -> dict:
    """Return a dict of key fields from a VCF 3.0 file."""
    data = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return data
    for line in text.splitlines():
        if line.startswith("N:"):
            # N:LASTNAME;FIRSTNAME;ADDITIONAL;PREFIX;SUFFIX
            parts = line[2:].split(";")
            data["last_name"]  = parts[0].strip() if len(parts) > 0 else ""
            data["first_name"] = parts[1].strip() if len(parts) > 1 else ""
        elif line.startswith("FN:"):
            data["full_name"] = line[3:].strip()
        elif line.startswith("UID:"):
            data["uid"] = line[4:].strip()
        elif line.startswith("X-ABUID:"):
            data["abuid"] = line[8:].strip()
        elif "X-SOCIALPROFILE" in line and "linkedin" in line.lower():
            url = line.split(":", 1)[-1].strip()
            data["linkedin_url"] = url
        elif line.startswith("ORG:"):
            data["org"] = line[4:].split(";")[0].strip()
        elif line.startswith("TITLE:"):
            data["title"] = line[6:].strip()
        elif line.startswith("EMAIL"):
            if "email" not in data:
                data["email"] = line.split(":")[-1].strip()
    return data


def slug_to_last_name(url: str) -> str | None:
    """
    Try to extract last name from a LinkedIn slug.
    Pattern A: "firstname-lastname-123456" → last name = middle parts
    Pattern B: "firstnamelastname" (no hyphens) → give up
    """
    slug = unquote(url)
    # Strip URL, keep only the slug
    m = re.search(r"linkedin\.com/in/([^/?#]+)", slug, re.IGNORECASE)
    if not m:
        return None
    slug = m.group(1).rstrip("/")
    parts = slug.split("-")
    if len(parts) < 2:
        return None
    # Drop trailing pure-digit segment (LinkedIn numeric ID)
    while parts and parts[-1].isdigit():
        parts = parts[:-1]
    if len(parts) < 2:
        return None
    # First part = first name (possibly multi-word with prefix like "jean-philippe")
    # Last part(s) = last name — heuristic: capitalise each part and join
    # We skip the first element which is the first name (it may span 1-2 parts)
    # Strategy: first name from VCF known, find where slug first name ends
    last_parts = parts[1:]  # everything after first token = candidate last name
    return " ".join(p.capitalize() for p in last_parts)


# ── Main scan ─────────────────────────────────────────────────────────────────

# All last-name values that indicate poisoned/damaged data.
# Checked case-insensitively. Prefix matches also caught (e.g. "not available in...").
DAMAGED_LAST_NAMES: set[str] = {
    "not available",
    "available",                                    # partial write of "NOT AVAILABLE"
    "not available on 404 page",
    "not available in the provided webpage content",
    "information not available",
    "information not available on 404 page",
    "the world's largest professional network",     # LinkedIn fallback text leaked
    "linkedin member",
    "member",                                       # partial "LinkedIn Member"
    "n/a",
    "unknown",
    "no data available",
    "data not available",
    "data unavailable",
    "page not found",
    "page doesn't exist",
}

def is_damaged_last_name(ln: str) -> bool:
    low = ln.lower().strip()
    if low in DAMAGED_LAST_NAMES:
        return True
    for pattern in DAMAGED_LAST_NAMES:
        if low.startswith(pattern):
            return True
    return False


def main():
    print("Scanning session backups…")

    # Step 1: collect ALL original VCFs, keyed by UID
    # uid → list of (session_date, path, parsed_data)
    by_uid: dict[str, list] = defaultdict(list)
    vcf_count = 0

    for session_dir in sorted(SESSIONS.iterdir()):
        if not session_dir.is_dir():
            continue
        backups_dir = session_dir / "backups"
        if not backups_dir.exists():
            continue
        session_name = session_dir.name  # run_YYYY-MM-DD_HH-MM-SS
        for contact_dir in backups_dir.iterdir():
            if not contact_dir.is_dir():
                continue
            vcf_files = list(contact_dir.glob("*-original.vcf"))
            for vcf in vcf_files:
                parsed = parse_vcf(vcf)
                uid = parsed.get("uid")
                if uid:
                    by_uid[uid].append((session_name, vcf, parsed))
                    vcf_count += 1

    print(f"  Indexed {vcf_count} VCFs across {len(by_uid)} unique contact UIDs.")

    # Step 2: find damaged contacts (any placeholder last name variant)
    damaged: dict[str, dict] = {}  # uid → most-recent damaged entry
    for uid, entries in by_uid.items():
        for session, vcf, parsed in sorted(entries, reverse=True):
            ln = parsed.get("last_name", "")
            if ln and is_damaged_last_name(ln):
                damaged[uid] = {"session": session, "vcf": str(vcf), "parsed": parsed}
                break

    print(f"  Found {len(damaged)} damaged UIDs (last name = NOT AVAILABLE).")

    # Step 3: for each damaged contact, find recovery source
    recovery_plan = []
    unresolved = []

    for uid, dmg in damaged.items():
        parsed = dmg["parsed"]
        first_name = parsed.get("first_name", "?")
        abuid = parsed.get("abuid", "")
        org = parsed.get("org", "")
        title = parsed.get("title", "")
        email = parsed.get("email", "")
        linkedin_url = parsed.get("linkedin_url", "")

        # Method A: earlier backup with correct name (same UID, older session)
        correct_last_name = None
        source = None
        source_session = None

        all_entries = sorted(by_uid[uid])  # chronological
        for session, vcf, p in all_entries:
            ln = p.get("last_name", "")
            if ln and ln.upper() != "NOT AVAILABLE" and ln != "":
                correct_last_name = ln
                source = "backup"
                source_session = session
                break  # earliest correct backup

        # Method B: LinkedIn slug heuristic
        if not correct_last_name and linkedin_url:
            slug_name = slug_to_last_name(linkedin_url)
            if slug_name:
                correct_last_name = slug_name
                source = "linkedin_slug"
                source_session = None

        # Method C: vault profile.json
        if not correct_last_name and abuid:
            plain_uid = abuid.split(":")[0]
            for vault_key in [abuid, plain_uid]:
                vault_profile = VAULT / vault_key / "profile.json"
                if vault_profile.exists():
                    try:
                        prof = json.loads(vault_profile.read_text())
                        vln = prof.get("last_name") or prof.get("family_name") or ""
                        if vln and vln.upper() not in ("NOT AVAILABLE", ""):
                            correct_last_name = vln
                            source = "vault"
                            source_session = str(vault_profile)
                    except Exception:
                        pass
                    break

        entry = {
            "uid": uid,
            "abuid": abuid,
            "first_name": first_name,
            "recovered_last_name": correct_last_name,
            "source": source,
            "source_session": source_session,
            "linkedin_url": linkedin_url,
            "org": org,
            "title": title,
            "email": email,
            "damaged_session": dmg["session"],
            "damaged_vcf": dmg["vcf"],
        }

        if correct_last_name:
            recovery_plan.append(entry)
        else:
            unresolved.append(entry)

    # Step 4: output
    all_entries_out = {"recovered": recovery_plan, "unresolved": unresolved}
    REPORT.write_text(json.dumps(all_entries_out, indent=2, ensure_ascii=False))

    # Human-readable report
    lines = []
    lines.append("=" * 72)
    lines.append("LSAM — NOT AVAILABLE Last Name Recovery Report")
    lines.append(f"Total damaged UIDs: {len(damaged)}")
    lines.append(f"Recoverable:        {len(recovery_plan)}")
    lines.append(f"Unresolved:         {len(unresolved)}")
    lines.append("=" * 72)
    lines.append("")

    lines.append("── RECOVERABLE ─────────────────────────────────────────────────")
    for e in sorted(recovery_plan, key=lambda x: x["recovered_last_name"].upper()):
        fn = e["first_name"]
        ln = e["recovered_last_name"]
        src = e["source"]
        sess = e.get("source_session") or ""
        li = e.get("linkedin_url", "")
        lines.append(f"  {fn:30s} → {ln:30s} [{src}]")
        if sess:
            lines.append(f"    from: {sess}")
        if li:
            lines.append(f"    linkedin: {li}")

    lines.append("")
    lines.append("── UNRESOLVED (manual lookup needed) ───────────────────────────")
    for e in sorted(unresolved, key=lambda x: x["first_name"].upper()):
        fn = e["first_name"]
        li = e.get("linkedin_url", "")
        org = e.get("org", "")
        lines.append(f"  {fn:30s}  org: {org}")
        if li:
            lines.append(f"    linkedin: {li}")

    report_text = "\n".join(lines)
    TEXT_RPT.write_text(report_text, encoding="utf-8")
    print("\n" + report_text)
    print(f"\nFull JSON: {REPORT}")
    print(f"Text report: {TEXT_RPT}")


if __name__ == "__main__":
    main()
