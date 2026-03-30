"""
vault_enricher.py — LSAM Vault Enricher (NR-11)
================================================
Version: 1.0.0 (2026-03-15)

PURPOSE
    Promotes EXPERIENCE, EDUCATION, SKILLS, SUMMARY and other rich fields from
    session backup profile.json files into the data/vault/ entries.

    The engine writes rich profile data (experience, education, skills) to
    logs/sessions/run_*/backups/*/profile.json on every sync, but the data/vault/
    entries (used for stealth-mode fallback and surgical repair) only contain
    sparse fields. This script bridges that gap.

TWO VAULT STORES (recap)
    - data/vault/{UUID:ABPerson}/profile.json   — 139 entries, sparse, populated
                                                  by a separate vault population tool
    - logs/sessions/run_*/backups/*/profile.json — ~2,200+ entries, rich, engine-written
                                                   (contact_id stored as _contact_id field)

STRATEGY
    1. Scan all session backups, group by _contact_id, keep newest session per contact
    2. For each contact_id: find or create a vault entry
    3. Merge rich fields into vault entry (additive — never overwrites non-empty vault fields
       unless session data is longer/richer)
    4. Track which fields were promoted

FIELDS PROMOTED
    experience, education, skills, summary
    + followers_count, connections_count, connection_degree (if vault has 0/null)
    + photo_url (if vault has none)
    + linkedin_url (if vault has none but session has one)

USAGE
    python3 scripts/vault_enricher.py --dry-run             # audit only
    python3 scripts/vault_enricher.py --apply               # write vault entries
    python3 scripts/vault_enricher.py --dry-run --name "François Siegel"
    python3 scripts/vault_enricher.py --apply --since 2026-03-14
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR     = _PROJECT_ROOT / "data" / "vault"
SESSIONS_DIR  = _PROJECT_ROOT / "logs" / "sessions"
REPORT_DIR    = _PROJECT_ROOT

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Fields promoted from session → vault ─────────────────────────────────────
RICH_FIELDS    = ["experience", "education", "skills"]           # list fields: promote if session longer
SCALAR_FILL    = ["summary", "photo_url", "linkedin_url",        # scalars: fill if vault is empty
                  "location", "city", "country"]
NUMERIC_FILL   = ["followers_count", "connections_count",        # numerics: fill if vault is 0/None
                  "connection_degree", "common_connections_count"]

# ── Poison / junk guards ──────────────────────────────────────────────────────
_POISON_STRINGS = ["not available", "information not available", "page not found"]
_SHORT_SCALAR_FIELDS = {"city", "country"}    # must be ≤60 chars, no newlines
_MEDIUM_SCALAR_FIELDS = {"location"}          # must be ≤120 chars, no newlines


def _is_poison_name(full_name: str) -> bool:
    """Reject NOT AVAILABLE / scraping-failed contacts."""
    if not full_name:
        return True
    fn_lower = full_name.lower().strip()
    return any(p in fn_lower for p in _POISON_STRINGS)


def _is_junk_scalar(field: str, value: str) -> bool:
    """Reject garbage values in location/city/country (scraping artifacts)."""
    if not isinstance(value, str):
        return False
    if "\n" in value or "\r" in value:
        return True
    if field in _SHORT_SCALAR_FIELDS and len(value) > 60:
        return True
    if field in _MEDIUM_SCALAR_FIELDS and len(value) > 120:
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Collection
# ══════════════════════════════════════════════════════════════════════════════

def _session_timestamp(session_dir: Path) -> str:
    """Extract sortable timestamp from run_YYYY-MM-DD_HH-MM-SS directory name."""
    m = re.search(r"run_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", session_dir.name)
    return m.group(1) if m else "0000-00-00_00-00-00"


def collect_session_profiles(
    since_date: Optional[str] = None,
    name_filter: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Scan session backups, return the NEWEST profile per contact_id.
    Returns: {contact_id: {"profile": dict, "source": path_str, "session_ts": str}}
    """
    since_dt = datetime.strptime(since_date, "%Y-%m-%d") if since_date else None
    by_contact: Dict[str, Tuple[str, Dict[str, Any]]] = {}  # contact_id → (session_ts, profile)

    if not SESSIONS_DIR.exists():
        logger.warning(f"Sessions directory not found: {SESSIONS_DIR}")
        return {}

    session_dirs = sorted(SESSIONS_DIR.iterdir(), key=lambda d: _session_timestamp(d))

    for session_dir in session_dirs:
        if not session_dir.is_dir() or not session_dir.name.startswith("run_"):
            continue

        # Date filter
        if since_dt:
            m = re.search(r"run_(\d{4}-\d{2}-\d{2})", session_dir.name)
            if m:
                sess_date = datetime.strptime(m.group(1), "%Y-%m-%d")
                if sess_date < since_dt:
                    continue

        backups_dir = session_dir / "backups"
        if not backups_dir.exists():
            continue

        session_ts = _session_timestamp(session_dir)

        for contact_dir in backups_dir.iterdir():
            if not contact_dir.is_dir():
                continue

            pfile = contact_dir / "profile.json"
            if not pfile.exists():
                continue

            try:
                with open(pfile, encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception:
                continue

            contact_id = profile.get("_contact_id", "")
            if not contact_id:
                continue

            # Name filter
            if name_filter:
                full_name = profile.get("full_name", "") or ""
                if name_filter.lower() not in full_name.lower():
                    continue

            # Keep newest session for this contact_id
            existing = by_contact.get(contact_id)
            existing_ts = existing[0] if existing else ""
            if session_ts >= existing_ts:
                by_contact[contact_id] = (session_ts, profile, str(pfile))

    return {
        cid: {"profile": data[1], "source": data[2], "session_ts": data[0]}
        for cid, data in by_contact.items()
    }


# ══════════════════════════════════════════════════════════════════════════════
# Vault I/O
# ══════════════════════════════════════════════════════════════════════════════

def _vault_path(contact_id: str) -> Path:
    return VAULT_DIR / contact_id / "profile.json"


def load_vault_entry(contact_id: str) -> Optional[Dict[str, Any]]:
    p = _vault_path(contact_id)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_vault_entry(contact_id: str, entry: Dict[str, Any]) -> None:
    p = _vault_path(contact_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)


def _make_blank_vault_entry(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Create a minimal vault entry skeleton from a session profile."""
    return {
        "full_name":              profile.get("full_name") or "",
        "first_name":             profile.get("first_name"),
        "last_name":              profile.get("last_name"),
        "suffix":                 profile.get("suffix"),
        "current_role":           profile.get("current_role") or "",
        "company":                profile.get("company"),
        "location":               profile.get("location") if not _is_junk_scalar("location", profile.get("location") or "") else None,
        "city":                   profile.get("city")     if not _is_junk_scalar("city",     profile.get("city") or "")     else None,
        "country":                profile.get("country")  if not _is_junk_scalar("country",  profile.get("country") or "")  else None,
        "summary":                profile.get("summary"),
        "linkedin_url":           profile.get("linkedin_url"),
        "photo_url":              profile.get("photo_url"),
        "emails":                 profile.get("emails") or [],
        "phones":                 profile.get("phones") or [],
        "websites":               profile.get("websites") or [],
        "birthday":               profile.get("birthday"),
        "connected_date":         profile.get("connected_date"),
        "connection_degree":      profile.get("connection_degree"),
        "followers_count":        profile.get("followers_count") or 0,
        "connections_count":      profile.get("connections_count") or 0,
        "connections_raw":        profile.get("connections_raw"),
        "common_connections_count": profile.get("common_connections_count") or 0,
        "mutual_groups":          profile.get("mutual_groups") or [],
        "mutual_raw":             profile.get("mutual_raw"),
        "experience":             profile.get("experience") or [],
        "education":              profile.get("education") or [],
        "skills":                 profile.get("skills") or [],
        "timestamp":              profile.get("timestamp") or datetime.now().strftime("%Y-%m-%d"),
        "_enriched_from":         "vault_enricher",
        "_enriched_at":           datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Merge logic
# ══════════════════════════════════════════════════════════════════════════════

def compute_diff(
    vault_entry: Optional[Dict[str, Any]],
    session_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute what would change if we merged session_profile into vault_entry.
    Returns a dict of {field: new_value} for all fields that would be promoted.
    Returns empty dict if vault_entry is None (full create case handled separately).
    """
    if vault_entry is None:
        return {}  # caller handles create case

    changes: Dict[str, Any] = {}

    # List fields: promote if session has more items
    for field in RICH_FIELDS:
        sess_val = session_profile.get(field) or []
        vault_val = vault_entry.get(field) or []
        if isinstance(sess_val, list) and len(sess_val) > len(vault_val):
            changes[field] = sess_val

    # Scalar fields: fill if vault is empty/null (with junk guard)
    for field in SCALAR_FILL:
        sess_val = session_profile.get(field)
        vault_val = vault_entry.get(field)
        if sess_val and not vault_val:
            if isinstance(sess_val, str) and _is_junk_scalar(field, sess_val):
                continue
            changes[field] = sess_val

    # Numeric fields: fill if vault is 0/None
    for field in NUMERIC_FILL:
        sess_val = session_profile.get(field)
        vault_val = vault_entry.get(field)
        if sess_val and (not vault_val or vault_val == 0):
            changes[field] = sess_val

    return changes


# ══════════════════════════════════════════════════════════════════════════════
# Main enrichment loop
# ══════════════════════════════════════════════════════════════════════════════

def run_enricher(
    apply: bool,
    since_date: Optional[str] = None,
    name_filter: Optional[str] = None,
) -> Dict[str, Any]:
    mode_label = "APPLY" if apply else "DRY-RUN"
    logger.info(f"=== LSAM Vault Enricher [{mode_label}] — {datetime.now().isoformat()} ===")

    session_profiles = collect_session_profiles(since_date=since_date, name_filter=name_filter)
    logger.info(f"Session profiles collected: {len(session_profiles)} unique contacts")

    stats = {
        "mode": mode_label,
        "session_profiles": len(session_profiles),
        "vault_created": 0,
        "vault_updated": 0,
        "already_rich": 0,
        "errors": 0,
        "details": [],
    }

    for contact_id, data in sorted(session_profiles.items()):
        profile   = data["profile"]
        source    = data["source"]
        sess_ts   = data["session_ts"]
        full_name = profile.get("full_name") or contact_id

        # Skip poisoned / NOT AVAILABLE contacts
        if _is_poison_name(full_name):
            logger.debug(f"  [POISON-SKIP] {full_name}: name indicates failed extraction")
            continue

        vault_entry = load_vault_entry(contact_id)

        try:
            if vault_entry is None:
                # CREATE: new vault entry from session backup
                new_entry = _make_blank_vault_entry(profile)
                created_fields = [f for f in RICH_FIELDS + SCALAR_FILL if new_entry.get(f)]
                if not created_fields:
                    logger.debug(f"  [SKIP] {full_name}: session profile also sparse, skipping")
                    continue

                record = {
                    "contact_id": contact_id,
                    "name": full_name,
                    "action": "CREATE",
                    "fields": created_fields,
                    "source": source,
                    "session_ts": sess_ts,
                }
                logger.info(f"  [CREATE] {full_name}: {', '.join(created_fields[:5])}"
                            + (f" (+{len(created_fields)-5} more)" if len(created_fields) > 5 else ""))

                if apply:
                    save_vault_entry(contact_id, new_entry)
                    record["applied"] = True

                stats["vault_created"] += 1
                stats["details"].append(record)

            else:
                # UPDATE: merge into existing vault entry
                changes = compute_diff(vault_entry, profile)

                if not changes:
                    stats["already_rich"] += 1
                    continue

                record = {
                    "contact_id": contact_id,
                    "name": full_name,
                    "action": "UPDATE",
                    "fields": list(changes.keys()),
                    "source": source,
                    "session_ts": sess_ts,
                }

                # Detail counts for list fields
                detail_parts = []
                for field, val in changes.items():
                    if isinstance(val, list):
                        old_count = len(vault_entry.get(field) or [])
                        detail_parts.append(f"{field}: {old_count}→{len(val)}")
                    else:
                        snippet = str(val)[:40] + "…" if len(str(val)) > 40 else str(val)
                        detail_parts.append(f"{field}: '{snippet}'")

                logger.info(f"  [UPDATE] {full_name}: {', '.join(detail_parts)}")

                if apply:
                    merged = dict(vault_entry)
                    merged.update(changes)
                    merged["_enriched_from"] = "vault_enricher"
                    merged["_enriched_at"]   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    save_vault_entry(contact_id, merged)
                    record["applied"] = True

                stats["vault_updated"] += 1
                stats["details"].append(record)

        except Exception as e:
            logger.error(f"  [ERROR] {full_name} ({contact_id}): {e}")
            stats["errors"] += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Mode           : {mode_label}")
    logger.info(f"Session profiles: {stats['session_profiles']}")
    logger.info(f"Vault CREATED  : {stats['vault_created']}")
    logger.info(f"Vault UPDATED  : {stats['vault_updated']}")
    logger.info(f"Already rich   : {stats['already_rich']}")
    logger.info(f"Errors         : {stats['errors']}")

    # ── Report ────────────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"VAULT_ENRICH_REPORT_{ts}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    logger.info(f"Report         : {report_path}")
    logger.info("=" * 60)

    return stats


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LSAM Vault Enricher — promote experience/education from session backups to vault"
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--dry-run", action="store_true", help="Audit only, no writes")
    mode_group.add_argument("--apply",   action="store_true", help="Write changes to vault")

    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Only consider session backups from this date onward")
    parser.add_argument("--name",  metavar="NAME",
                        help="Only process contacts whose full_name contains NAME")

    args = parser.parse_args()

    run_enricher(
        apply       = args.apply,
        since_date  = args.since,
        name_filter = args.name,
    )


if __name__ == "__main__":
    main()
