#!/usr/bin/env python3
"""
LSAM Surgical Repair — v1.1 (2026-03-14)

A strictly local repair script that fixes data-integrity issues in macOS Contacts
using vault/session data only (no LinkedIn API calls).

Profile sources (both scanned, deduplicated by contact_id — newest session wins):
  • data/vault/UUID:ABPerson/profile.json   — UUID-keyed vault (139 entries)
  • logs/sessions/run_*/backups/*/profile.json — session backups from engine runs (~2000+)

Covers all issues documented in SYNC_CORRUPTION_ANALYSIS.md:
  Task A  — Name de-poisoning ("NOT AVAILABLE" / "INFORMATION NOT AVAILABLE")
  Task B  — Sync-block normalization (Russian Doll nesting, missing 1st-degree label,
             malformed/orphaned blocks) → regenerates a clean [RESCUED] block from vault
  Task C  — Job / Company null guard (fill empty fields from vault, never overwrite)

Usage:
  python3 -m src.rescue.surgical_repair --dry-run               # audit all sources
  python3 -m src.rescue.surgical_repair --apply                 # write changes
  python3 -m src.rescue.surgical_repair --dry-run --sessions-only   # session backups only
  python3 -m src.rescue.surgical_repair --dry-run --vault-only      # UUID vault only
  python3 -m src.rescue.surgical_repair --dry-run --since 2026-03-13  # sessions from date
  python3 -m src.rescue.surgical_repair --dry-run --name "Denis Tersen"
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path bootstrap — allow running as `python3 -m src.rescue.surgical_repair`
# from the project root.
# ---------------------------------------------------------------------------
_SCRIPT_DIR  = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.bridge.contact_macos import ContactMacOSBridge  # noqa: E402
from src.models.profile import LinkedInProfile            # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("surgical_repair")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VAULT_DIR    = _PROJECT_ROOT / "data" / "vault"
SESSIONS_DIR = _PROJECT_ROOT / "logs" / "sessions"

# Strings that indicate a failed/restricted LinkedIn extraction
_POISON = [
    "not available",
    "information not available",
    "page not found",
    "page doesn't exist",
]

# Exact values stored in the last_name or first_name field by the poisoning bug
_POISON_NAME_EXACT = {v.upper() for v in _POISON}

# Regex helpers for sync-block manipulation
_RE_BLOCK_FULL   = re.compile(
    r"<Linkedin-AI-sync[^>]*>.*?</Linkedin-AI-sync>", re.IGNORECASE | re.DOTALL
)
_RE_BLOCK_OPEN   = re.compile(r"<Linkedin-AI-sync[^>]*>",  re.IGNORECASE)
_RE_BLOCK_CLOSE  = re.compile(r"</Linkedin-AI-sync>",       re.IGNORECASE)
_RE_STRIP_LEGACY = re.compile(
    r"^LinkedIn connection\s*:\s*.*$|^LinkedIn_Connection_Since:.*$",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_poison(value: Optional[str]) -> bool:
    """Returns True if value contains a known extraction-failure string."""
    if not value:
        return False
    low = value.lower().strip()
    return any(p in low for p in _POISON)


def _is_junk_job_title(value: Optional[str]) -> bool:
    """
    Returns True if a job_title looks like scraped noise rather than a real title.
    Used by Task C to reject bad values before writing to Contacts.app.

    Heuristics (any match → junk):
      • Starts with '|' or '•' (LinkedIn hashtag / pipe-delimited tag list)
      • Contains 3+ pipe characters (e.g. "| Tech | Finance | VC |")
      • Longer than 120 chars (overflow headline, not a job title)
      • Consists only of hashtags (e.g. "#FinTech #AI #Blockchain")
      • Contains no letters at all (pure emoji / symbol noise)
    """
    if not value:
        return False
    v = value.strip()
    if v.startswith("|") or v.startswith("•"):
        return True
    if v.count("|") >= 3:
        return True
    if len(v) > 120:
        return True
    # Only hashtags: every word starts with #
    words = v.split()
    if words and all(w.startswith("#") for w in words):
        return True
    # No letters at all
    if not re.search(r"[a-zA-ZÀ-ÿ]", v):
        return True
    return False


def _is_name_poisoned(value: Optional[str]) -> bool:
    """Returns True if the field exactly matches a known poison placeholder."""
    if not value:
        return False
    return value.upper().strip() in _POISON_NAME_EXACT or _is_poison(value)


def _is_block_malformed(note: str) -> bool:
    """True when the note has nested, duplicated, or orphaned sync tags."""
    opens  = len(_RE_BLOCK_OPEN.findall(note))
    closes = len(_RE_BLOCK_CLOSE.findall(note))
    return opens > 1 or closes > 1 or opens != closes


def _strip_all_sync_artifacts(note: str) -> str:
    """Removes every <Linkedin-AI-sync> variant (full blocks, orphaned tags, legacy)."""
    # Multi-pass: strip full blocks first, then orphaned openers/closers
    prev = None
    cleaned = note
    while prev != cleaned:
        prev = cleaned
        cleaned = _RE_BLOCK_FULL.sub("", cleaned)
    cleaned = _RE_BLOCK_OPEN.sub("", cleaned)
    cleaned = _RE_BLOCK_CLOSE.sub("", cleaned)
    cleaned = _RE_STRIP_LEGACY.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _degree_label(degree: Optional[int]) -> str:
    """Human-readable degree label for any value including 1st.
    Fixes the generate_sync_block bug that skips 1st-degree contacts.
    """
    if degree is None:
        return ""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(degree, "th")
    return f"{degree}{suffix} degree"


def _build_rescued_block(profile: LinkedInProfile, today: str) -> str:
    """
    Builds a clean [RESCUED] sync block directly from vault data.
    Does NOT call profile.generate_sync_block() to avoid re-introducing the
    degree-label bug (which skips 1st-degree contacts).
    """
    lines = [
        f"<Linkedin-AI-sync {today} rescued>",
        "[RESCUED] — Restored from vault snapshot (no live LinkedIn call)",
    ]

    degree    = profile.connection_degree
    deg_label = _degree_label(degree)

    # Company / Job (from vault Experience[0] when available, fallback to fields)
    company   = ""
    job_title = ""
    if profile.experience:
        company   = (profile.experience[0].company or "").strip()
        job_title = (profile.experience[0].title   or "").strip()
    if not company:
        company   = (profile.company      or "").strip()
    if not job_title:
        job_title = (profile.current_role or "").strip()

    if company   and not _is_poison(company):
        lines.append(f"Company: {company}")
    if job_title and not _is_poison(job_title):
        lines.append(f"Job: {job_title}")

    # Followers
    if profile.followers_count:
        lines.append(f"Followers: {profile.followers_count}")

    # Connections
    c_text = None
    if profile.connections_count is not None and profile.connections_count > 0:
        c_text = "500+" if profile.connections_count >= 500 else str(profile.connections_count)
    if c_text:
        lines.append(f"Connections : {c_text}")

    # Mutual connections — always include degree label (including 1st)
    mutual = profile.common_connections_count
    if mutual is not None and mutual > 0:
        deg_suffix = f" ({deg_label})" if deg_label else ""
        lines.append(f"Mutual connections{deg_suffix} : {mutual}")
    elif deg_label:
        # At minimum record the degree even with no mutual count
        lines.append(f"Connection degree: {deg_label}")

    # Mutual groups
    if profile.mutual_groups:
        lines.append(f"Mutual Groups: {', '.join(profile.mutual_groups)}")

    lines.append("</Linkedin-AI-sync>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-contact analysis (read-only)
# ---------------------------------------------------------------------------

def analyse_contact(
    contact_id: str,
    profile: LinkedInProfile,
    bridge: ContactMacOSBridge,
) -> dict:
    """
    Analyses one vault entry against the live macOS Contacts state.
    Returns a dict describing what needs to be repaired — no writes.
    """
    result: dict = {
        "contact_id": contact_id,
        "name":       profile.full_name,
        "task_a":     None,
        "task_b":     None,
        "task_c":     None,
        "error":      None,
    }

    current = bridge.get_contact_details(contact_id)
    if not current.get("success"):
        result["error"] = current.get("error", "get_contact_details failed")
        return result

    today = datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Task A — Name de-poisoning
    # ------------------------------------------------------------------
    live_last  = (current.get("last_name")  or "").strip()
    live_first = (current.get("first_name") or "").strip()
    live_full  = (current.get("name")       or "").strip()

    if _is_name_poisoned(live_last) or _is_name_poisoned(live_first) or _is_poison(live_full):
        vault_full  = (profile.full_name  or "").strip()
        vault_first = (profile.first_name or "").strip()
        vault_last  = (profile.last_name  or "").strip()

        if vault_full and not _is_poison(vault_full):
            # Parse first/last from full_name if individual fields missing
            if not vault_first and not vault_last:
                parts = vault_full.split(" ", 1)
                vault_first = parts[0]
                vault_last  = parts[1] if len(parts) > 1 else ""
            result["task_a"] = {
                "live_name":   live_full,
                "vault_name":  vault_full,
                "vault_first": vault_first,
                "vault_last":  vault_last,
                "action": "restore_from_vault",
            }
        else:
            result["task_a"] = {
                "live_name":  live_full,
                "vault_name": vault_full,
                "action": "vault_also_empty — manual intervention required",
            }

    # ------------------------------------------------------------------
    # Task B — Sync block repair
    # ------------------------------------------------------------------
    note = current.get("note", "") or ""
    block_match    = _RE_BLOCK_FULL.search(note)
    existing_block = block_match.group(0) if block_match else None

    needs_repair  = False
    block_reasons = []

    if _is_block_malformed(note):
        needs_repair = True
        block_reasons.append("malformed_nested_or_orphaned_tags")

    if existing_block and "[RESCUED]" in existing_block:
        # Already rescued — don't re-process
        needs_repair  = False
        block_reasons = ["already_rescued — skipped"]

    if existing_block and not needs_repair:
        # Missing 1st-degree label check
        if (
            profile.connection_degree == 1
            and "1st" not in existing_block
            and "degree" not in existing_block.lower()
        ):
            needs_repair = True
            block_reasons.append("missing_1st_degree_label")

    if needs_repair:
        result["task_b"] = {
            "reasons":        block_reasons,
            "existing_block": existing_block,
            "rescued_block":  _build_rescued_block(profile, today),
        }

    # ------------------------------------------------------------------
    # Task C — Job / Company null guard
    # ------------------------------------------------------------------
    live_job     = (current.get("job_title")    or "").strip()
    live_company = (current.get("organization") or "").strip()

    # Prefer vault Experience[0] as anchor (per SYNC_CORRUPTION_ANALYSIS.md §4)
    vault_job     = ""
    vault_company = ""
    if profile.experience:
        vault_job     = (profile.experience[0].title   or "").strip()
        vault_company = (profile.experience[0].company or "").strip()
    if not vault_job:
        vault_job     = (profile.current_role or "").strip()
    if not vault_company:
        vault_company = (profile.company      or "").strip()

    task_c: dict = {}
    if not live_job and vault_job and not _is_poison(vault_job) and not _is_junk_job_title(vault_job):
        task_c["job_title"] = vault_job
    if not live_company and vault_company and not _is_poison(vault_company):
        task_c["company"] = vault_company
    if task_c:
        result["task_c"] = task_c

    return result


# ---------------------------------------------------------------------------
# Apply repairs
# ---------------------------------------------------------------------------

def apply_repairs(
    analysis: dict,
    bridge: ContactMacOSBridge,
    dry_run: bool,
) -> list:
    """
    Applies the repairs described in an analysis dict.
    Returns a list of human-readable action strings.
    """
    applied = []
    cid  = analysis["contact_id"]
    name = analysis["name"]
    tag  = "DRY" if dry_run else "APPLY"

    # ---- Task A: Name de-poisoning ----
    ta = analysis.get("task_a")
    if ta and ta.get("action") == "restore_from_vault":
        first = ta["vault_first"]
        last  = ta["vault_last"]
        full  = ta["vault_name"]
        logger.info(f"[Task A][{tag}] '{name}': restore name '{ta['live_name']}' → '{full}'")
        if not dry_run:
            safe_first = first.replace('"', '\\"')
            safe_last  = last.replace('"', '\\"')
            script = (
                f'tell application "Contacts"\n'
                f'    set p to person id "{cid}"\n'
                f'    set first name of p to "{safe_first}"\n'
                f'    set last name of p to "{safe_last}"\n'
                f'    save\n'
                f'    return "OK"\n'
                f'end tell'
            )
            res = bridge._run_applescript(script)
            if res.get("success"):
                applied.append(f"Task A: name restored to '{full}'")
            else:
                applied.append(f"Task A: FAILED — {res.get('error')}")
        else:
            applied.append(f"Task A (dry): would restore name to '{full}'")

    elif ta and ta.get("action", "").startswith("vault_also_empty"):
        applied.append(f"Task A: SKIPPED — {ta['action']}")

    # ---- Task B: Sync block normalization ----
    tb = analysis.get("task_b")
    if tb and tb.get("rescued_block"):
        rescued = tb["rescued_block"]
        reasons = tb["reasons"]
        logger.info(f"[Task B][{tag}] '{name}': replace block [{', '.join(reasons)}]")
        if not dry_run:
            # Re-fetch note to avoid stale state after Task A
            current = bridge.get_contact_details(cid)
            if current.get("success"):
                fresh_note   = current.get("note", "") or ""
                stripped     = _strip_all_sync_artifacts(fresh_note)
                new_note     = (rescued + "\n\n" + stripped).strip() if stripped else rescued
            else:
                new_note = rescued

            safe_note = new_note.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            script = (
                f'tell application "Contacts"\n'
                f'    set p to person id "{cid}"\n'
                f'    set note of p to "{safe_note}"\n'
                f'    save\n'
                f'    return "OK"\n'
                f'end tell'
            )
            res = bridge._run_applescript(script)
            if res.get("success"):
                applied.append(f"Task B: sync block replaced [{', '.join(reasons)}]")
            else:
                applied.append(f"Task B: FAILED — {res.get('error')}")
        else:
            applied.append(f"Task B (dry): would replace sync block [{', '.join(reasons)}]")
            preview = "\n".join(f"    {l}" for l in rescued.splitlines())
            applied.append(f"  Preview:\n{preview}")

    # ---- Task C: Job / Company null guard ----
    tc = analysis.get("task_c")
    if tc:
        for field, value in tc.items():
            prop_map = {"job_title": "job title", "company": "organization"}
            prop = prop_map.get(field)
            if not prop:
                continue
            logger.info(f"[Task C][{tag}] '{name}': set {field} = '{value}'")
            if not dry_run:
                safe_val = value.replace('"', '\\"')
                script = (
                    f'tell application "Contacts"\n'
                    f'    set p to person id "{cid}"\n'
                    f'    set {prop} of p to "{safe_val}"\n'
                    f'    save\n'
                    f'    return "OK"\n'
                    f'end tell'
                )
                res = bridge._run_applescript(script)
                if res.get("success"):
                    applied.append(f"Task C: set {field} = '{value}'")
                else:
                    applied.append(f"Task C: FAILED {field} — {res.get('error')}")
            else:
                applied.append(f"Task C (dry): would set {field} = '{value}'")

    return applied


# ---------------------------------------------------------------------------
# Profile collection — both vault and session backups
# ---------------------------------------------------------------------------

def collect_profiles(
    include_vault: bool = True,
    include_sessions: bool = True,
    since_date: Optional[str] = None,
) -> dict:
    """
    Collects the most recent profile for each unique contact_id from:
      1. data/vault/UUID:ABPerson/profile.json  (folder name = contact_id)
      2. logs/sessions/run_*/backups/*/profile.json  (contact_id in _contact_id field)

    Returns: {contact_id: {"profile_data": dict, "source": str, "timestamp": str}}
    Deduplication: session backup wins over vault if for same contact_id;
    among multiple session entries for the same contact_id, the newest run wins.
    """
    profiles: dict = {}  # contact_id → {profile_data, source, timestamp}

    # --- Source 1: UUID-keyed vault ---
    if include_vault and VAULT_DIR.exists():
        for entry in sorted(VAULT_DIR.iterdir()):
            if not entry.is_dir():
                continue
            pf = entry / "profile.json"
            if not pf.exists():
                continue
            contact_id = entry.name
            if not contact_id.endswith(":ABPerson"):
                continue
            try:
                with open(pf, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                profiles[contact_id] = {
                    "profile_data": data,
                    "source":       f"vault:{entry.name}",
                    "timestamp":    data.get("timestamp", ""),
                }
            except Exception:
                pass

    # --- Source 2: Session backups ---
    if include_sessions and SESSIONS_DIR.exists():
        # Collect all run_ dirs, sorted newest-first so last-write wins on conflict
        run_dirs = sorted(
            [d for d in SESSIONS_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
            key=lambda d: d.name,
        )
        for run_dir in run_dirs:
            # Filter by --since date if requested (run_ dirs are named run_YYYY-MM-DD_*)
            if since_date:
                run_date = run_dir.name[4:14]  # "YYYY-MM-DD" from "run_YYYY-MM-DD_HH-MM-SS"
                if run_date < since_date:
                    continue

            backups_dir = run_dir / "backups"
            if not backups_dir.exists():
                continue

            for contact_dir in backups_dir.iterdir():
                if not contact_dir.is_dir():
                    continue
                pf = contact_dir / "profile.json"
                if not pf.exists():
                    continue
                try:
                    with open(pf, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    contact_id = data.get("_contact_id", "")
                    if not contact_id:
                        continue
                    # Newest run wins (we iterate oldest→newest so later runs overwrite)
                    profiles[contact_id] = {
                        "profile_data": data,
                        "source":       f"session:{run_dir.name}/{contact_dir.name}",
                        "timestamp":    run_dir.name[4:14],
                    }
                except Exception:
                    pass

    return profiles


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LSAM Surgical Repair — fix data-integrity issues from vault/sessions (no LinkedIn calls)"
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run", action="store_true",
        help="Audit only — print what would change, write nothing"
    )
    mode_group.add_argument(
        "--apply", action="store_true",
        help="Write changes to macOS Contacts.app"
    )
    parser.add_argument(
        "--name", metavar="NAME",
        help="Restrict to one contact by full_name (case-insensitive)"
    )
    parser.add_argument(
        "--since", metavar="YYYY-MM-DD",
        help="Only scan session runs from this date onwards (e.g. 2026-03-13)"
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--sessions-only", action="store_true",
        help="Only scan logs/sessions/ backups (skip data/vault/)"
    )
    source_group.add_argument(
        "--vault-only", action="store_true",
        help="Only scan data/vault/ UUID entries (skip session backups)"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    dry_run  = args.dry_run
    mode_str = "DRY-RUN" if dry_run else "APPLY"
    logger.info(f"=== LSAM Surgical Repair [{mode_str}] — {datetime.now().isoformat()[:19]} ===")

    include_vault    = not args.sessions_only
    include_sessions = not args.vault_only

    # Collect all profiles (deduplicated, newest session wins)
    all_profiles = collect_profiles(
        include_vault=include_vault,
        include_sessions=include_sessions,
        since_date=args.since,
    )
    total = len(all_profiles)
    logger.info(
        f"Profiles collected: {total} unique contacts "
        f"({'vault+sessions' if include_vault and include_sessions else 'vault only' if include_vault else 'sessions only'})"
        + (f" since {args.since}" if args.since else "")
    )

    # Bridge runs in SIMULATION mode for dry-run (prevents accidental writes)
    bridge = ContactMacOSBridge(mode="SIMULATION" if dry_run else "FULL")

    skipped = needs_repair = repaired = errors = 0
    report_rows = []

    for contact_id, entry in sorted(all_profiles.items(), key=lambda x: x[1].get("timestamp", "")):
        data = entry["profile_data"]
        source = entry["source"]

        # Strip internal engine fields before constructing LinkedInProfile
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

        try:
            profile = LinkedInProfile(**clean_data)
        except Exception as exc:
            logger.warning(f"Cannot parse profile ({source}): {exc}")
            errors += 1
            continue

        if args.name and profile.full_name.lower() != args.name.lower():
            continue

        analysis = analyse_contact(contact_id, profile, bridge)

        if analysis["error"]:
            logger.warning(f"  ⚠ {profile.full_name}: {analysis['error']}")
            errors += 1
            continue

        has_work = any([analysis["task_a"], analysis["task_b"], analysis["task_c"]])
        if not has_work:
            skipped += 1
            if args.verbose:
                logger.debug(f"  ✓ {profile.full_name}: no repairs needed")
            continue

        needs_repair += 1
        applied = apply_repairs(analysis, bridge, dry_run)

        for line in applied:
            logger.info(f"  → {profile.full_name}: {line}")

        if not dry_run and applied:
            repaired += 1

        report_rows.append({
            "name":       profile.full_name,
            "contact_id": contact_id,
            "task_a":     bool(analysis["task_a"]),
            "task_b":     bool(analysis["task_b"]),
            "task_c":     bool(analysis["task_c"]),
            "applied":    applied,
        })

    # Write JSON report
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _PROJECT_ROOT / f"RESCUE_REPORT_{timestamp_str}.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump({
            "mode":           mode_str,
            "timestamp":      datetime.now().isoformat()[:19],
            "profiles_total": total,
            "skipped":        skipped,
            "needs_repair":   needs_repair,
            "repaired":       repaired if not dry_run else "N/A (dry-run)",
            "errors":         errors,
            "contacts":       report_rows,
        }, fh, ensure_ascii=False, indent=2)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Mode          : {mode_str}")
    logger.info(f"Profiles      : {total} unique contacts")
    logger.info(f"Clean (skip)  : {skipped}")
    logger.info(f"Need repair   : {needs_repair}")
    if not dry_run:
        logger.info(f"Repaired      : {repaired}")
    logger.info(f"Errors        : {errors}")
    logger.info(f"Report        : {report_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
