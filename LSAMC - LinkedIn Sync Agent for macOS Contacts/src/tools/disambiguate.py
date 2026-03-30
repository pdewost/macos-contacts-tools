#!/usr/bin/env python3
"""
Layer B: Ambiguity Disambiguation Tool
=======================================
Scores candidates in compact ambiguity blocks using signals from the contact note
(email domains, category tags, LinkedIn_Connection_Since) and name matching.

For high-confidence matches: sets the social profile URL on the contact and strips
the ambiguity block.

Usage:
    python3 src/tools/disambiguate.py                  # SIMULATION (score + report)
    python3 src/tools/disambiguate.py --live            # LIVE (apply AUTO_RESOLVE)

Safety:
    - MORENO_GUARD: backs up each note before modification
    - Never uses `delete person` (Domain Safety Rule #1)
    - Default is SIMULATION; --live required for writes
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("disambiguate")

# ── Constants ───────────────────────────────────────────────────────────────

GENERIC_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.fr", "hotmail.com", "hotmail.fr",
    "outlook.com", "live.fr", "live.com", "wanadoo.fr", "orange.fr",
    "free.fr", "noos.fr", "aol.com", "icloud.com", "laposte.net",
    "numericable.fr", "sfr.fr", "neuf.fr", "club-internet.fr", "voila.fr",
    "msn.com", "me.com", "mac.com",
}

# Category tags that map to company names for cross-referencing
CATEGORY_COMPANY_MAP = {
    "FT": ["france telecom", "france télécom", "orange", "ftgroup", "ft group"],
    "Ukibi": ["ukibi"],
    "Wanadoo": ["wanadoo"],
}

# ── AppleScript helpers ─────────────────────────────────────────────────────

def run_applescript(script: str, timeout: int = 15) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(f"AppleScript error: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run_applescript_file(script: str, timeout: int = 120) -> str:
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".applescript", delete=False) as f:
        f.write(script)
        f.flush()
        try:
            proc = subprocess.run(
                ["osascript", f.name],
                capture_output=True, text=True, timeout=timeout
            )
            if proc.returncode != 0:
                raise RuntimeError(f"AppleScript error: {proc.stderr.strip()}")
            return proc.stdout.strip()
        finally:
            os.unlink(f.name)


# ── Contact fetching (reuses Review group pattern from cleanup) ─────────────

def get_unresolved_ambiguity_contacts() -> list:
    """Get contacts with LSAM AMBIGUITY that DON'T have a social profile set."""
    script = '''
    tell application "Contacts"
        set matchIDs to {}
        try
            set reviewGroup to group "script-LSAM-LinkedIn to Review"
            set groupPeople to people of reviewGroup
            repeat with p in groupPeople
                try
                    set pNote to note of p as text
                    if pNote contains "LSAM AMBIGUITY" then
                        -- Only include if NO social profile set (unresolved)
                        set hasSocial to false
                        try
                            if (count of social profiles of p) > 0 then set hasSocial to true
                        end try
                        if not hasSocial then
                            set end of matchIDs to (id of p as text)
                        end if
                    end if
                end try
            end repeat
        end try
        set AppleScript's text item delimiters to linefeed
        return matchIDs as text
    end tell
    '''
    raw = run_applescript_file(script, timeout=120)
    ids = [line.strip() for line in raw.split("\n") if line.strip()]

    contacts = []
    for cid in ids:
        try:
            detail_script = f'''
            tell application "Contacts"
                set p to person id "{cid}"
                set pFirst to ""
                set pLast to ""
                try
                    set pFirst to first name of p as text
                end try
                try
                    set pLast to last name of p as text
                end try
                set pNote to ""
                try
                    set pNote to note of p as text
                end try
                return pFirst & " " & pLast & "|||" & pNote
            end tell
            '''
            raw = run_applescript(detail_script, timeout=10)
            parts = raw.split("|||", 1)
            contacts.append({
                "id": cid,
                "name": parts[0].strip(),
                "note": parts[1] if len(parts) > 1 else "",
            })
        except Exception as e:
            logger.warning(f"Failed to fetch {cid}: {e}")

    return contacts


# ── Signal extraction ───────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"[\w.+-]+@([\w.-]+\.\w+)")


def extract_company_from_domain(domain: str) -> str | None:
    """Extract meaningful company name from email domain."""
    domain = domain.lower()
    if domain in GENERIC_EMAIL_PROVIDERS:
        return None
    parts = domain.split(".")
    if len(parts) >= 3:
        candidate = parts[-2]
        if len(candidate) <= 2:
            candidate = parts[-3] if len(parts) >= 3 else parts[0]
        return candidate.replace("-", " ")
    return parts[0].replace("-", " ")


def extract_signals(note: str) -> dict:
    """Extract disambiguation signals from the original note (below the --- separator)."""
    # Get content below the first separator
    parts = re.split(r"-{20,}", note)
    original = ""
    for part in parts:
        if "LSAM AMBIGUITY" not in part and part.strip():
            original = part
            break

    signals = {
        "email_companies": [],
        "category_companies": [],
        "connection_since": None,
        "raw_text": original.lower(),
    }

    for match in EMAIL_RE.finditer(original):
        company = extract_company_from_domain(match.group(1))
        if company and len(company) >= 3:
            signals["email_companies"].append(company.lower())

    for line in original.split("\n"):
        line = line.strip()
        if line.startswith("Catégorie:"):
            cat = line.replace("Catégorie:", "").strip()
            for alias in CATEGORY_COMPANY_MAP.get(cat, []):
                signals["category_companies"].append(alias.lower())

    if "LinkedIn_Connection_Since" in original:
        signals["connection_since"] = True

    # Deduplicate
    signals["email_companies"] = list(set(signals["email_companies"]))
    signals["category_companies"] = list(set(signals["category_companies"]))

    return signals


# ── Candidate parsing (from compact format) ─────────────────────────────────

def parse_compact_candidates(note: str) -> list[dict]:
    """Parse candidates from the compact ambiguity block produced by Layer A."""
    candidates = []

    # Find the ambiguity block (before the first --- separator)
    parts = re.split(r"-{20,}", note)
    amb_block = ""
    for part in parts:
        if "LSAM AMBIGUITY" in part:
            amb_block = part
            break

    if not amb_block:
        return []

    lines = amb_block.split("\n")
    for line in lines:
        stripped = line.strip()

        if stripped.startswith("- "):
            # Parse: "- Name • degree — Headline (Location) [N mutual]"
            rest = stripped[2:]

            # Extract mutual count [N mutual]
            mutual = 0
            mut_m = re.search(r"\[(\d+)\s+mutual\]", rest)
            if mut_m:
                mutual = int(mut_m.group(1))
                rest = rest[: mut_m.start()].strip()

            # Extract location (City)
            location = ""
            loc_m = re.search(r"\(([^)]+)\)\s*$", rest)
            if loc_m:
                location = loc_m.group(1)
                rest = rest[: loc_m.start()].strip()

            # Extract headline after " — "
            headline = ""
            if " — " in rest:
                parts2 = rest.split(" — ", 1)
                rest = parts2[0].strip()
                headline = parts2[1].strip()

            # Extract degree after " • "
            degree = ""
            if " • " in rest:
                parts2 = rest.split(" • ", 1)
                rest = parts2[0].strip()
                degree = parts2[1].strip()

            name = rest
            candidates.append({
                "name": name,
                "degree": degree,
                "headline": headline,
                "location": location,
                "mutual": mutual,
                "url": "",
            })

        elif stripped.startswith("https://www.linkedin.com/in/"):
            # URL line belongs to the last candidate
            if candidates:
                candidates[-1]["url"] = stripped

    return candidates


# ── Scoring ─────────────────────────────────────────────────────────────────

def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z\s]", "", s.lower().strip())


def name_similarity(contact_name: str, candidate_name: str) -> float:
    cn = normalize_name(contact_name)
    can = normalize_name(candidate_name)
    if not cn or not can:
        return 0
    if cn == can:
        return 1.0
    cn_words = set(cn.split())
    can_words = set(can.split())
    if cn_words and cn_words.issubset(can_words):
        return 0.95
    if can_words and can_words.issubset(cn_words):
        return 0.9
    return SequenceMatcher(None, cn, can).ratio()


def url_slug_contains_lastname(contact_name: str, url: str) -> bool:
    """Check if the LinkedIn URL slug contains the contact's last name."""
    last_name = contact_name.strip().split()[-1].lower() if contact_name.strip() else ""
    if len(last_name) < 3:
        return False
    slug = url.lower().split("/in/")[-1] if "/in/" in url else ""
    return last_name in slug


def company_match(candidate: dict, signals: dict) -> bool:
    """Check if any company signal matches the candidate's headline."""
    text = (candidate.get("headline", "") + " " + candidate.get("name", "")).lower()
    for co in signals["email_companies"] + signals["category_companies"]:
        if co in text:
            return True
    return False


def score_candidate(contact_name: str, candidate: dict, signals: dict, max_mutual: int) -> dict:
    """Score a candidate. Returns dict with score breakdown."""
    ns = name_similarity(contact_name, candidate["name"])
    slug_match = 1.0 if url_slug_contains_lastname(contact_name, candidate["url"]) else 0.0

    degree = candidate.get("degree", "")
    if "1st" in degree:
        deg_score = 1.0
    elif "2nd" in degree:
        deg_score = 0.5
    else:
        deg_score = 0.1

    mutual_norm = candidate["mutual"] / max(max_mutual, 1)
    co_match = 1.0 if company_match(candidate, signals) else 0.0

    # Connection_since means we know this person was 1st-degree at some point
    # If only one candidate is 1st-degree, boost them
    connection_bonus = 0.0
    if signals["connection_since"] and "1st" in degree:
        connection_bonus = 0.1

    composite = (
        0.30 * ns
        + 0.15 * slug_match
        + 0.15 * deg_score
        + 0.15 * mutual_norm
        + 0.25 * co_match
        + connection_bonus
    )

    return {
        "composite": composite,
        "name_sim": ns,
        "slug_match": slug_match,
        "degree_score": deg_score,
        "mutual_norm": mutual_norm,
        "company_match": co_match,
        "connection_bonus": connection_bonus,
    }


# ── Resolution actions ──────────────────────────────────────────────────────

def set_social_profile(contact_id: str, url: str) -> bool:
    """Set the LinkedIn social profile URL on a contact."""
    script = f'''
    tell application "Contacts"
        set p to person id "{contact_id}"
        make new social profile at end of social profiles of p with properties {{service name:"LinkedIn", url:"{url}"}}
        save
    end tell
    '''
    try:
        run_applescript(script, timeout=10)
        return True
    except RuntimeError as e:
        logger.error(f"Failed to set social profile for {contact_id}: {e}")
        return False


def update_note_resolved(contact_id: str, old_note: str, winner_url: str) -> bool:
    """Replace ambiguity block with resolved marker."""
    today = datetime.now().strftime("%Y-%m-%d")
    # Remove the ambiguity block and replace with resolved marker
    parts = re.split(r"-{20,}", old_note)
    original_sections = []
    for part in parts:
        if "LSAM AMBIGUITY" not in part and part.strip():
            original_sections.append(part.strip())

    new_note = f"✅ LinkedIn auto-resolved ({today})\n"
    new_note += "-" * 50 + "\n"
    if original_sections:
        new_note += "\n".join(original_sections)

    new_note = re.sub(r"\n{3,}", "\n\n", new_note).strip()

    # Escape for AppleScript
    escaped = new_note.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = f'''
    tell application "Contacts"
        set p to person id "{contact_id}"
        set note of p to "{escaped}"
        save
    end tell
    '''
    try:
        run_applescript(script, timeout=10)
        return True
    except RuntimeError as e:
        logger.error(f"Failed to update note for {contact_id}: {e}")
        return False


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Layer B: Ambiguity disambiguation")
    parser.add_argument("--live", action="store_true", help="Apply AUTO_RESOLVE (default: SIMULATION)")
    args = parser.parse_args()

    mode = "LIVE" if args.live else "SIMULATION"
    logger.info(f"=== Disambiguation Tool — {mode} mode ===")

    # Backup directory (MORENO_GUARD)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_dir = Path(f"logs/sessions/{ts}/disambiguation")
    if args.live:
        backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Backup dir: {backup_dir}")

    logger.info("Fetching unresolved ambiguity contacts...")
    contacts = get_unresolved_ambiguity_contacts()
    logger.info(f"Found {len(contacts)} unresolved ambiguity contacts.")

    results = {"AUTO_RESOLVE": [], "SUGGEST": [], "MANUAL_ONLY": []}

    for contact in contacts:
        cid = contact["id"]
        cname = contact["name"]
        note = contact["note"]

        candidates = parse_compact_candidates(note)
        if not candidates:
            logger.warning(f"  {cname}: no candidates parsed from note")
            results["MANUAL_ONLY"].append((cname, "no candidates"))
            continue

        signals = extract_signals(note)
        max_mutual = max(c["mutual"] for c in candidates) if candidates else 1

        scored = []
        for c in candidates:
            s = score_candidate(cname, c, signals, max_mutual)
            scored.append((c, s))

        scored.sort(key=lambda x: -x[1]["composite"])
        best_cand, best_score = scored[0]
        second_score = scored[1][1]["composite"] if len(scored) > 1 else 0

        # Decision
        decision = "MANUAL_ONLY"
        reason = ""

        if (best_score["name_sim"] >= 0.85 and
                best_score["composite"] >= 0.75 and
                best_cand["url"]):
            if len(scored) == 1 or best_score["composite"] - second_score >= 0.15:
                decision = "AUTO_RESOLVE"
                reason = f"name={best_score['name_sim']:.2f} comp={best_score['composite']:.2f}"
            else:
                decision = "SUGGEST"
                reason = f"close: best={best_score['composite']:.2f} 2nd={second_score:.2f}"
        elif (best_score["name_sim"] >= 0.85 and
              best_score["composite"] >= 0.60 and
              best_cand["url"] and
              best_score["composite"] - second_score >= 0.15):
            decision = "SUGGEST"
            reason = f"name={best_score['name_sim']:.2f} comp={best_score['composite']:.2f}"
        else:
            # Check slug match as a strong fallback signal
            if (best_score["slug_match"] > 0 and
                    best_score["name_sim"] >= 0.80 and
                    best_cand["url"]):
                decision = "SUGGEST"
                reason = f"slug+name match comp={best_score['composite']:.2f}"
            else:
                reason = f"best_name={best_score['name_sim']:.2f} comp={best_score['composite']:.2f}"

        results[decision].append((cname, reason))

        # Log
        signals_str = ""
        if signals["email_companies"]:
            signals_str += f" email=[{','.join(signals['email_companies'])}]"
        if signals["category_companies"]:
            signals_str += f" cat=[{','.join(signals['category_companies'])}]"
        if signals["connection_since"]:
            signals_str += " conn_since=yes"

        logger.info(
            f"  [{decision:12s}] {cname:40s} → {best_cand['name'][:30]:30s} "
            f"| {reason}{signals_str}"
        )

        # Apply if LIVE + AUTO_RESOLVE
        if mode == "LIVE" and decision == "AUTO_RESOLVE":
            # MORENO_GUARD: backup
            safe_name = re.sub(r"[^\w\-]", "_", cname)
            backup_file = backup_dir / f"{safe_name}_{cid[:8]}.json"
            backup_data = {
                "contact_id": cid,
                "contact_name": cname,
                "timestamp": datetime.now().isoformat(),
                "original_note": note,
                "winner": {
                    "name": best_cand["name"],
                    "url": best_cand["url"],
                    "score": best_score,
                },
                "all_candidates": [(c["name"], s) for c, s in scored],
            }
            backup_file.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2, default=str))

            # Set social profile
            if set_social_profile(cid, best_cand["url"]):
                # Update note
                if update_note_resolved(cid, note, best_cand["url"]):
                    logger.info(f"    ✅ Social profile set + note updated for {cname}")
                else:
                    logger.error(f"    ❌ Social profile set but note update failed for {cname}")
            else:
                logger.error(f"    ❌ Failed to set social profile for {cname}")

    # Summary
    logger.info("=" * 70)
    logger.info(f"{'SIMULATION' if mode == 'SIMULATION' else 'LIVE'} COMPLETE")
    logger.info(f"  AUTO_RESOLVE:  {len(results['AUTO_RESOLVE'])}")
    logger.info(f"  SUGGEST:       {len(results['SUGGEST'])}")
    logger.info(f"  MANUAL_ONLY:   {len(results['MANUAL_ONLY'])}")

    if results["AUTO_RESOLVE"]:
        logger.info("\nAUTO_RESOLVE contacts:")
        for name, reason in results["AUTO_RESOLVE"]:
            logger.info(f"  ✅ {name}: {reason}")

    if results["SUGGEST"]:
        logger.info("\nSUGGEST contacts (need manual confirmation):")
        for name, reason in results["SUGGEST"]:
            logger.info(f"  🔍 {name}: {reason}")


if __name__ == "__main__":
    main()
