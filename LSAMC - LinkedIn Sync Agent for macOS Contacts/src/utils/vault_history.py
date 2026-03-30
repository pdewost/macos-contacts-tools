"""
vault_history.py — v1.0
Sprint 1 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 1)

Versioned vault snapshot management:
- write_snapshot(): create a timestamped history entry after each acquisition
- prune(): enforce retention_keep_n_sessions (delete oldest beyond N)
- load_history(): retrieve all history snapshots for a contact, newest first
- diff(): structured comparison between two snapshots

Design contract:
  - history/ subfolder inside each vault contact directory
  - Filenames: ISO timestamp with colons replaced by underscores (filesystem-safe)
  - Each snapshot is self-contained JSON (profile + scavenger_meta + engine metadata)
  - master_profile.json remains the canonical current profile (backwards-compat)
  - retention_keep_n_sessions from config/lsam_config.json (default: 3)

Safety:
  - Never deletes master_profile.json or scavenger_meta.json
  - Prune only removes history/ files beyond retention limit
  - All operations are additive; failures logged but never propagated

Author: Claude Opus 4.6 (1M context) | 2026-03-29
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("vault_history")

# Default retention if config is missing or unreadable
DEFAULT_RETENTION = 3

# Fields to track in diff output
DIFF_FIELDS = [
    "current_role", "company", "location", "full_name", "first_name", "last_name",
    "followers_count", "connections_count", "common_connections_count",
    "connection_degree", "photo_url", "photo_blocked", "linkedin_url",
    "summary",
]


def _ts_to_filename(dt: datetime) -> str:
    """Convert datetime to filesystem-safe filename (no colons)."""
    return dt.strftime("%Y-%m-%dT%H_%M_%S") + ".json"


def _filename_to_ts(filename: str) -> Optional[datetime]:
    """Parse a history filename back to datetime. Returns None on parse failure."""
    stem = filename.replace(".json", "")
    try:
        return datetime.strptime(stem, "%Y-%m-%dT%H_%M_%S")
    except ValueError:
        return None


def _load_config_retention(project_root: str) -> int:
    """Read retention_keep_n_sessions from config/lsam_config.json."""
    config_path = os.path.join(project_root, "config", "lsam_config.json")
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        return cfg.get("vault", {}).get("retention_keep_n_sessions", DEFAULT_RETENTION)
    except Exception:
        return DEFAULT_RETENTION


def write_snapshot(
    vault_contact_dir: str,
    profile_dict: Dict[str, Any],
    scavenger_meta: Dict[str, Any],
    engine_version: str = "unknown",
    session_id: str = "",
    source: str = "",
    project_root: str = "",
) -> Optional[str]:
    """
    Write a timestamped history snapshot for a contact.

    Args:
        vault_contact_dir: Path to the contact's vault directory (e.g., data/vault/UUID:ABPerson)
        profile_dict: The LinkedInProfile as a dict (profile.model_dump(mode="json"))
        scavenger_meta: The scavenger_meta dict written alongside the profile
        engine_version: Engine version string (e.g., "v8.7")
        session_id: Session identifier (e.g., "run_2026-03-27_19-07-00")
        source: Acquisition source (e.g., "manual_sync_simulation")
        project_root: Project root for loading config (retention). If empty, uses default retention.

    Returns:
        Path to the written snapshot file, or None on failure.
    """
    history_dir = os.path.join(vault_contact_dir, "history")
    os.makedirs(history_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    filename = _ts_to_filename(now)
    snapshot_path = os.path.join(history_dir, filename)

    snapshot = {
        "profile": profile_dict,
        "scavenger_meta": scavenger_meta,
        "captured_at": now.isoformat(),
        "engine_version": engine_version,
        "session_id": session_id,
        "source": source or scavenger_meta.get("source", "unknown"),
    }

    try:
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)
        logger.info(f"[vault_history] Snapshot written: {snapshot_path}")
    except Exception as e:
        logger.warning(f"[vault_history] Failed to write snapshot: {e}")
        return None

    # Prune after write
    retention = _load_config_retention(project_root) if project_root else DEFAULT_RETENTION
    prune(vault_contact_dir, retention)

    return snapshot_path


def prune(vault_contact_dir: str, keep_n: int = DEFAULT_RETENTION) -> int:
    """
    Enforce retention: keep only the N most recent history snapshots.

    Args:
        vault_contact_dir: Path to the contact's vault directory
        keep_n: Number of snapshots to retain (default from config)

    Returns:
        Number of snapshots deleted.
    """
    history_dir = os.path.join(vault_contact_dir, "history")
    if not os.path.isdir(history_dir):
        return 0

    # List all .json files, sorted newest first
    snapshots = []
    for fname in os.listdir(history_dir):
        if fname.endswith(".json"):
            ts = _filename_to_ts(fname)
            if ts is not None:
                snapshots.append((ts, fname))

    snapshots.sort(key=lambda x: x[0], reverse=True)

    deleted = 0
    for _ts, fname in snapshots[keep_n:]:
        try:
            os.remove(os.path.join(history_dir, fname))
            deleted += 1
            logger.debug(f"[vault_history] Pruned: {fname}")
        except Exception as e:
            logger.warning(f"[vault_history] Failed to prune {fname}: {e}")

    if deleted:
        logger.info(f"[vault_history] Pruned {deleted} snapshot(s) from {vault_contact_dir}")
    return deleted


def load_history(vault_contact_dir: str) -> List[Dict[str, Any]]:
    """
    Load all history snapshots for a contact, newest first.

    Returns:
        List of snapshot dicts, each containing profile, scavenger_meta, captured_at, etc.
        Empty list if no history exists.
    """
    history_dir = os.path.join(vault_contact_dir, "history")
    if not os.path.isdir(history_dir):
        return []

    snapshots = []
    for fname in os.listdir(history_dir):
        if not fname.endswith(".json"):
            continue
        ts = _filename_to_ts(fname)
        if ts is None:
            continue
        try:
            with open(os.path.join(history_dir, fname), "r") as f:
                data = json.load(f)
            data["_filename"] = fname
            data["_parsed_ts"] = ts.isoformat()
            snapshots.append((ts, data))
        except Exception as e:
            logger.warning(f"[vault_history] Failed to read {fname}: {e}")

    snapshots.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in snapshots]


def diff(
    snapshot_new: Dict[str, Any],
    snapshot_old: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute a structured diff between two history snapshots.

    Args:
        snapshot_new: The more recent snapshot dict (from load_history)
        snapshot_old: The older snapshot dict

    Returns:
        Dict with:
          - changed: list of {field, old, new} for fields that changed
          - added: list of {field, value} for fields present in new but not old
          - removed: list of {field, value} for fields present in old but not new
          - experience_changes: dict with added/removed/changed experience entries
          - stats: summary counters
          - captured_at_new / captured_at_old: timestamps of the two snapshots
    """
    profile_new = snapshot_new.get("profile", {})
    profile_old = snapshot_old.get("profile", {})

    changed = []
    added = []
    removed = []

    for field in DIFF_FIELDS:
        val_new = profile_new.get(field)
        val_old = profile_old.get(field)

        if val_new == val_old:
            continue
        if val_old is None and val_new is not None:
            added.append({"field": field, "value": val_new})
        elif val_new is None and val_old is not None:
            removed.append({"field": field, "value": val_old})
        else:
            changed.append({"field": field, "old": val_old, "new": val_new})

    # Experience changes
    exp_new = profile_new.get("experience", []) or []
    exp_old = profile_old.get("experience", []) or []
    exp_changes = _diff_experience(exp_new, exp_old)

    # Education changes
    edu_new = profile_new.get("education", []) or []
    edu_old = profile_old.get("education", []) or []
    edu_changes = _diff_list_by_key(edu_new, edu_old, key_fields=["school", "degree"])

    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "experience_changes": exp_changes,
        "education_changes": edu_changes,
        "stats": {
            "fields_changed": len(changed),
            "fields_added": len(added),
            "fields_removed": len(removed),
            "total_changes": len(changed) + len(added) + len(removed),
        },
        "captured_at_new": snapshot_new.get("captured_at", ""),
        "captured_at_old": snapshot_old.get("captured_at", ""),
    }


def _diff_experience(
    exp_new: List[Dict], exp_old: List[Dict]
) -> Dict[str, Any]:
    """Compare experience lists by company+title as identity key."""
    return _diff_list_by_key(exp_new, exp_old, key_fields=["company", "title"])


def _diff_list_by_key(
    list_new: List[Dict], list_old: List[Dict], key_fields: List[str]
) -> Dict[str, Any]:
    """Generic list diff using composite key from key_fields."""

    def _make_key(entry: Dict) -> str:
        return "|".join(str(entry.get(k, "")).lower().strip() for k in key_fields)

    old_by_key = {_make_key(e): e for e in list_old}
    new_by_key = {_make_key(e): e for e in list_new}

    added = [new_by_key[k] for k in new_by_key if k not in old_by_key]
    removed = [old_by_key[k] for k in old_by_key if k not in new_by_key]

    return {
        "added": added,
        "removed": removed,
        "count_new": len(list_new),
        "count_old": len(list_old),
    }


def format_diff_human(diff_result: Dict[str, Any]) -> str:
    """
    Format a diff result as a human-readable string.

    Used by vault_diff.py CLI and Control Center inspect mode.
    """
    lines = []
    lines.append(f"Comparing: {diff_result['captured_at_new']} vs {diff_result['captured_at_old']}")
    lines.append(f"Changes: {diff_result['stats']['total_changes']} field(s)")
    lines.append("")

    if not diff_result["changed"] and not diff_result["added"] and not diff_result["removed"]:
        lines.append("  No field changes detected.")
    else:
        for c in diff_result["changed"]:
            old_str = str(c["old"])[:60]
            new_str = str(c["new"])[:60]
            lines.append(f"  {c['field']}: {old_str} -> {new_str}")
        for a in diff_result["added"]:
            lines.append(f"  + {a['field']}: {str(a['value'])[:60]}")
        for r in diff_result["removed"]:
            lines.append(f"  - {r['field']}: {str(r['value'])[:60]}")

    exp = diff_result.get("experience_changes", {})
    if exp.get("added") or exp.get("removed"):
        lines.append("")
        lines.append(f"  Experience: {exp['count_old']} -> {exp['count_new']} entries")
        for a in exp.get("added", []):
            lines.append(f"    + {a.get('title', '?')} at {a.get('company', '?')}")
        for r in exp.get("removed", []):
            lines.append(f"    - {r.get('title', '?')} at {r.get('company', '?')}")

    edu = diff_result.get("education_changes", {})
    if edu.get("added") or edu.get("removed"):
        lines.append("")
        lines.append(f"  Education: {edu['count_old']} -> {edu['count_new']} entries")
        for a in edu.get("added", []):
            lines.append(f"    + {a.get('degree', '?')} at {a.get('school', '?')}")
        for r in edu.get("removed", []):
            lines.append(f"    - {r.get('degree', '?')} at {r.get('school', '?')}")

    return "\n".join(lines)
