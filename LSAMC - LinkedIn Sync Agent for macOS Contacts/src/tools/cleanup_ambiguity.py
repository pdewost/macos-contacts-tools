#!/usr/bin/env python3
"""
Layer A: Ambiguity Note Cleanup Tool
=====================================
Scans all macOS Contacts for ⚠️ LSAM AMBIGUITY blocks, deduplicates them,
reduces to compact format, and preserves original note content.

Also strips orphan #lsam-force-resync tags (legacy, no longer consumed by engine).

Usage:
    python3 src/tools/cleanup_ambiguity.py                  # SIMULATION (dry run)
    python3 src/tools/cleanup_ambiguity.py --live            # LIVE (writes to contacts)
    python3 src/tools/cleanup_ambiguity.py --live --resolved # Also strip resolved ambiguity blocks

Safety:
    - MORENO_GUARD: backs up each note to logs/sessions/<ts>/ambiguity_cleanup/ before modification
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
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("cleanup_ambiguity")

# ── AppleScript helpers ─────────────────────────────────────────────────────

def run_applescript(script: str, timeout: int = 30) -> str:
    """Run an AppleScript and return stdout."""
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(f"AppleScript error: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run_applescript_file(script: str, timeout: int = 300) -> str:
    """Write AppleScript to a temp file and execute (avoids shell escaping issues)."""
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


def _get_matching_ids() -> list[str]:
    """Phase 1: Get IDs of contacts with LSAM AMBIGUITY in note.

    Uses the 'script-LSAM-LinkedIn to Review' group (fast path, ~100 contacts).
    The engine moves all ambiguity contacts into this group (pro_sync_agent.py:4310).
    """
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
                        set end of matchIDs to (id of p as text)
                    end if
                end try
            end repeat
        on error errMsg
            error "Review group not found: " & errMsg
        end try
        set AppleScript's text item delimiters to linefeed
        set resultText to matchIDs as text
        set AppleScript's text item delimiters to ""
        return resultText
    end tell
    '''
    raw = run_applescript_file(script, timeout=120)
    return [line.strip() for line in raw.split("\n") if line.strip()]


def _get_contact_detail(contact_id: str) -> dict:
    """Phase 2: Fetch name, social status, and note for a single contact by ID."""
    script = f'''
    tell application "Contacts"
        set p to person id "{contact_id}"
        set pFirst to ""
        set pLast to ""
        try
            set pFirst to first name of p as text
        end try
        try
            set pLast to last name of p as text
        end try
        set hasSocial to "false"
        try
            if (count of social profiles of p) > 0 then set hasSocial to "true"
        end try
        set pNote to ""
        try
            set pNote to note of p as text
        end try
        return pFirst & " " & pLast & "|||" & hasSocial & "|||" & pNote
    end tell
    '''
    raw = run_applescript(script, timeout=10)
    parts = raw.split("|||", 2)
    return {
        "id": contact_id,
        "name": parts[0].strip() if len(parts) > 0 else "",
        "has_social": parts[1].strip() == "true" if len(parts) > 1 else False,
        "note": parts[2] if len(parts) > 2 else "",
    }


def get_ambiguity_contacts() -> list[dict]:
    """Fetch all contacts with LSAM AMBIGUITY. Two-phase: bulk filter then individual fetch."""
    logger.info("Phase 1: Getting matching contact IDs...")
    ids = _get_matching_ids()
    logger.info(f"Phase 1 complete: {len(ids)} contacts match.")

    logger.info("Phase 2: Fetching details for each contact...")
    contacts = []
    for i, cid in enumerate(ids):
        try:
            detail = _get_contact_detail(cid)
            contacts.append(detail)
            if (i + 1) % 20 == 0:
                logger.info(f"  ... {i + 1}/{len(ids)} fetched")
        except Exception as e:
            logger.warning(f"  Failed to fetch {cid}: {e}")
    logger.info(f"Phase 2 complete: {len(contacts)} contacts loaded.")
    return contacts


def write_note(contact_id: str, new_note: str) -> bool:
    """Write a new note to a contact. Returns True on success."""
    # Escape for AppleScript string embedding
    escaped = new_note.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = f'''
    tell application "Contacts"
        set p to person id "{contact_id}"
        set note of p to "{escaped}"
        save
    end tell
    '''
    try:
        run_applescript(script)
        return True
    except RuntimeError as e:
        logger.error(f"Failed to write note for {contact_id}: {e}")
        return False


# ── Note Parser ─────────────────────────────────────────────────────────────

SEPARATOR_RE = re.compile(r"-{20,}")
AMBIGUITY_MARKER = "LSAM AMBIGUITY"
FORCE_RESYNC_RE = re.compile(r"(?m)^#lsam-force-resync\s*$")
AMBIGUITY_WARNING_PREFIX = re.compile(r"^Ambiguity_Warning:\s*")
PIPE_PREFIX_RE = re.compile(r"^\|\|\|\s*")


def parse_candidates_from_block(block: str) -> list[dict]:
    """Parse candidate entries from a single ambiguity block.

    Each candidate has: name, degree, url, headline, location, mutual_count.
    """
    lines = block.split("\n")
    candidates = []
    current = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("- "):
            if current:
                candidates.append(current)

            rest = stripped[2:]
            url = ""
            name = rest
            degree = ""

            # Inline URL: "Name -> URL"
            if "-> https://www.linkedin.com/in/" in rest:
                parts = rest.split(" -> ", 1)
                name = parts[0].strip()
                url = parts[1].strip()

            # Degree on same line: "Name • 2nd"
            deg_m = re.search(r"[•·]\s*(\d+(?:st|nd|rd|th)\+?)", name)
            if deg_m:
                degree = deg_m.group(1)
                name = name[: deg_m.start()].strip()

            current = {
                "name": name,
                "url": url,
                "degree": degree,
                "headline": "",
                "location": "",
                "mutual_count": 0,
            }

        elif current:
            if not stripped:
                continue

            # Degree on separate line
            deg_m = re.match(r"[•·]\s*(\d+(?:st|nd|rd|th)\+?)", stripped)
            if deg_m and not current["degree"]:
                current["degree"] = deg_m.group(1)
                continue

            # URL in "... -> URL" or "... -> URL" pattern
            url_m = re.search(r"->\s*(https://www\.linkedin\.com/in/\S+)", stripped)
            if url_m and not current["url"]:
                current["url"] = url_m.group(1)
                mut_m = re.search(r"(\d[\d,]*)\s+other\s+mutual\s+connection", stripped)
                if mut_m:
                    current["mutual_count"] = int(mut_m.group(1).replace(",", ""))
                elif "is a mutual connection" in stripped:
                    current["mutual_count"] = 1
                continue

            # Skip action buttons
            if stripped in ("Connect", "Follow", "Message", "View my services"):
                continue

            # Skip boilerplate
            if stripped.startswith("Once verified") or stripped.startswith("#linkedin-ambiguous"):
                continue
            if stripped.startswith("I found multiple") or stripped.startswith("Please verify"):
                continue

            # Current/Past company
            if stripped.startswith("Current:") or stripped.startswith("Past:"):
                if not current["headline"]:
                    current["headline"] = stripped
                continue

            # Followers line
            if re.match(r"[\d,]+K?\s+followers", stripped):
                continue

            # Location (has comma + geographic marker)
            geo_markers = [
                "France", "United States", "United Kingdom", "Germany", "Belgium",
                "Netherlands", "Spain", "Italy", "Brazil", "China", "Japan", "Korea",
                "Area", "Region", "Metropolitan", "Canada", "Australia", "India",
                "Ireland", "Switzerland", "Sweden", "Finland", "Denmark", "Norway",
                "Portugal", "Austria", "Luxembourg", "Île-de-France", "Auvergne",
                "Provence", "Occitanie", "Bretagne", "Pays de la Loire",
            ]
            if not current["location"] and "," in stripped and len(stripped) < 80:
                if any(g in stripped for g in geo_markers):
                    current["location"] = stripped
                    continue

            # Headline (first substantial non-matched line)
            if not current["headline"] and len(stripped) > 5:
                current["headline"] = stripped

    if current:
        candidates.append(current)

    return candidates


def build_compact_block(candidates: list[dict]) -> str:
    """Build a compact ambiguity block from parsed candidates."""
    n = len(candidates)
    lines = [f"⚠️ LSAM AMBIGUITY ({n} candidate{'s' if n != 1 else ''})"]

    for c in candidates:
        deg = f" • {c['degree']}" if c["degree"] else ""
        headline = ""
        if c["headline"]:
            h = c["headline"][:60]
            if len(c["headline"]) > 60:
                h += "…"
            headline = f" — {h}"
        loc = ""
        if c["location"]:
            # Shorten: just city
            city = c["location"].split(",")[0].strip()
            loc = f" ({city})"
        mut = ""
        if c["mutual_count"]:
            mut = f" [{c['mutual_count']} mutual]"

        lines.append(f"- {c['name']}{deg}{headline}{loc}{mut}")
        if c["url"]:
            lines.append(f"  {c['url']}")

    lines.append("#linkedin-ambiguous-profile")
    lines.append("-" * 50)
    return "\n".join(lines)


def clean_note(note: str, has_social: bool, strip_resolved: bool = False) -> tuple[str, dict]:
    """Clean an ambiguity note. Returns (cleaned_note, stats).

    Stats: {blocks_removed, candidates_kept, force_resync_stripped, resolved_stripped}
    """
    stats = {
        "blocks_removed": 0,
        "candidates_kept": 0,
        "force_resync_stripped": False,
        "resolved_stripped": False,
        "original_len": len(note),
        "new_len": 0,
    }

    # Strip #lsam-force-resync tags
    if "#lsam-force-resync" in note:
        note = FORCE_RESYNC_RE.sub("", note)
        stats["force_resync_stripped"] = True

    # Split by dashed separator
    sections = SEPARATOR_RE.split(note)

    ambiguity_sections = []
    original_sections = []

    for section in sections:
        cleaned = section.strip()
        # Remove ||| prefix (artifact from multi-block extraction)
        cleaned = PIPE_PREFIX_RE.sub("", cleaned).strip()
        # Remove Ambiguity_Warning: prefix
        cleaned = AMBIGUITY_WARNING_PREFIX.sub("", cleaned).strip()

        if AMBIGUITY_MARKER in cleaned:
            ambiguity_sections.append(cleaned)
        elif cleaned:
            original_sections.append(cleaned)

    stats["blocks_removed"] = max(0, len(ambiguity_sections) - 1)

    # If contact already has social profile set (resolved), optionally strip all ambiguity
    if has_social and strip_resolved:
        stats["resolved_stripped"] = True
        stats["candidates_kept"] = 0
        today = datetime.now().strftime("%Y-%m-%d")
        header = f"✅ LinkedIn resolved (ambiguity cleaned {today})"
        parts = [header]
        if original_sections:
            parts.append("-" * 50)
            parts.extend(original_sections)
        result = "\n".join(parts)
        stats["new_len"] = len(result)
        return result, stats

    # Parse candidates from the FIRST (most recent) ambiguity block
    if ambiguity_sections:
        candidates = parse_candidates_from_block(ambiguity_sections[0])
        # Deduplicate candidates by URL
        seen_urls = set()
        unique_candidates = []
        for c in candidates:
            key = c["url"] or c["name"]
            if key not in seen_urls:
                seen_urls.add(key)
                unique_candidates.append(c)
        candidates = unique_candidates
        stats["candidates_kept"] = len(candidates)

        compact = build_compact_block(candidates)
        parts = [compact]
        if original_sections:
            parts.extend(original_sections)
        result = "\n".join(parts)
    else:
        # No ambiguity block found (shouldn't happen, but safety)
        result = "\n".join(original_sections) if original_sections else ""

    # Normalize blank lines
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    stats["new_len"] = len(result)
    return result, stats


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Layer A: Ambiguity note cleanup")
    parser.add_argument("--live", action="store_true", help="Apply changes (default: SIMULATION)")
    parser.add_argument("--resolved", action="store_true", help="Also strip resolved ambiguity blocks")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N contacts (0=all)")
    args = parser.parse_args()

    mode = "LIVE" if args.live else "SIMULATION"
    logger.info(f"=== Ambiguity Cleanup Tool — {mode} mode ===")

    # Backup directory (MORENO_GUARD)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_dir = Path(f"logs/sessions/{ts}/ambiguity_cleanup")
    if args.live:
        backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Backup dir: {backup_dir}")

    logger.info("Fetching contacts with LSAM AMBIGUITY blocks...")
    contacts = get_ambiguity_contacts()
    logger.info(f"Found {len(contacts)} contacts with ambiguity blocks.")

    if args.limit:
        contacts = contacts[: args.limit]
        logger.info(f"Limited to {args.limit} contacts.")

    total_stats = {
        "processed": 0,
        "blocks_removed": 0,
        "force_resync_stripped": 0,
        "resolved_stripped": 0,
        "bytes_saved": 0,
        "written": 0,
        "errors": 0,
    }

    for contact in contacts:
        cid = contact["id"]
        cname = contact["name"]
        note = contact["note"]
        has_social = contact["has_social"]

        cleaned, stats = clean_note(note, has_social, strip_resolved=args.resolved)

        # Skip if no meaningful change
        if cleaned == note.strip():
            continue

        total_stats["processed"] += 1
        total_stats["blocks_removed"] += stats["blocks_removed"]
        total_stats["bytes_saved"] += stats["original_len"] - stats["new_len"]
        if stats["force_resync_stripped"]:
            total_stats["force_resync_stripped"] += 1
        if stats["resolved_stripped"]:
            total_stats["resolved_stripped"] += 1

        savings_pct = ((stats["original_len"] - stats["new_len"]) / max(stats["original_len"], 1)) * 100

        if mode == "SIMULATION":
            logger.info(
                f"[SIM] {cname:40s} | {stats['original_len']:5d} → {stats['new_len']:5d} chars "
                f"({savings_pct:4.0f}% saved) | {stats['blocks_removed']} dup blocks removed | "
                f"{'RESOLVED' if stats['resolved_stripped'] else str(stats['candidates_kept']) + ' candidates'}"
            )
        else:
            # MORENO_GUARD: backup original note
            safe_name = re.sub(r"[^\w\-]", "_", cname)
            backup_file = backup_dir / f"{safe_name}_{cid[:8]}.json"
            backup_data = {
                "contact_id": cid,
                "contact_name": cname,
                "timestamp": datetime.now().isoformat(),
                "original_note": note,
                "cleaned_note": cleaned,
                "stats": stats,
            }
            backup_file.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2))

            # Write cleaned note
            if write_note(cid, cleaned):
                total_stats["written"] += 1
                logger.info(
                    f"[LIVE] {cname:40s} | {stats['original_len']:5d} → {stats['new_len']:5d} chars "
                    f"({savings_pct:4.0f}% saved) | written ✅"
                )
            else:
                total_stats["errors"] += 1
                logger.error(f"[LIVE] {cname:40s} | WRITE FAILED ❌")

    # Summary
    logger.info("=" * 70)
    logger.info(f"{'SIMULATION' if mode == 'SIMULATION' else 'LIVE'} COMPLETE")
    logger.info(f"  Contacts with changes:  {total_stats['processed']}")
    logger.info(f"  Duplicate blocks removed: {total_stats['blocks_removed']}")
    logger.info(f"  #lsam-force-resync stripped: {total_stats['force_resync_stripped']}")
    logger.info(f"  Resolved blocks stripped: {total_stats['resolved_stripped']}")
    logger.info(f"  Bytes saved:             {total_stats['bytes_saved']:,}")
    if mode != "SIMULATION":
        logger.info(f"  Written:                 {total_stats['written']}")
        logger.info(f"  Errors:                  {total_stats['errors']}")


if __name__ == "__main__":
    main()
