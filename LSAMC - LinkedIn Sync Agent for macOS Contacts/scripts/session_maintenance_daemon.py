#!/usr/bin/env python3
"""
LSAM Session Maintenance Daemon  (v4.7 B6-FIX)
Implements the design from SESSION_MAINTENANCE_DESIGN.md.

Responsibilities:
  1. Binary Asset Pruning — per-contact retention: oldest + 3 most recent (via vault_retention logic)
  2. Empty Session Cleanup — delete session dirs with no backups and tiny session.log
  3. Feedback Archival — rotate user_feedback.jsonl entries older than 90 days
  4. Maintenance Log — writes summary to logs/maintenance.log

Usage:
  python3 scripts/session_maintenance_daemon.py                  # Full run (interactive)
  python3 scripts/session_maintenance_daemon.py --dry-run        # Report only
  python3 scripts/session_maintenance_daemon.py --quiet          # No stdout, log only (for launchd/cron)

Scheduling (launchd):
  See the generated plist at scripts/com.lsam.maintenance.plist
"""

import os
import sys
import json
import shutil
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSIONS_DIR = PROJECT_ROOT / "logs" / "sessions"
FEEDBACK_LOG = PROJECT_ROOT / "logs" / "user_feedback.jsonl"
FEEDBACK_ARCHIVE = PROJECT_ROOT / "logs" / "user_feedback_archive.jsonl"
MAINTENANCE_LOG = PROJECT_ROOT / "logs" / "maintenance.log"

BINARY_EXTENSIONS = {".heic", ".jpg", ".jpeg", ".png", ".vcf"}
FEEDBACK_RETENTION_DAYS = 90

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MAINTENANCE] %(message)s",
    handlers=[
        logging.FileHandler(MAINTENANCE_LOG),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def get_session_date(session_name: str) -> str:
    """Extract date from session directory name like run_2026-01-27_16-22-38."""
    try:
        parts = session_name.split("_")
        if len(parts) >= 2:
            return parts[1]
    except Exception:
        pass
    return "0000-00-00"


# ============================================================
# TASK 1: Binary Asset Pruning (per-contact retention)
# ============================================================
def prune_binary_assets(execute: bool = True) -> dict:
    """Retention policy: oldest + 3 most recent per contact. Delete binaries from the rest."""
    contact_map = defaultdict(list)

    if not SESSIONS_DIR.exists():
        logger.warning(f"Sessions directory not found: {SESSIONS_DIR}")
        return {"files": 0, "bytes": 0, "contacts_pruned": 0}

    for session in sorted(os.listdir(SESSIONS_DIR)):
        session_path = SESSIONS_DIR / session
        if not session_path.is_dir():
            continue
        backups_dir = session_path / "backups"
        if not backups_dir.exists():
            continue

        session_date = get_session_date(session)

        for contact_dir in os.listdir(backups_dir):
            contact_path = backups_dir / contact_dir
            if not contact_path.is_dir():
                continue

            binary_files = []
            for f in os.listdir(contact_path):
                fpath = contact_path / f
                if fpath.is_file():
                    ext = fpath.suffix.lower()
                    if ext in BINARY_EXTENSIONS:
                        binary_files.append((fpath, fpath.stat().st_size))

            contact_map[contact_dir].append({
                "session_date": session_date,
                "binary_files": binary_files,
            })

    total_files = 0
    total_bytes = 0
    contacts_pruned = 0

    for contact_name, entries in sorted(contact_map.items()):
        if len(entries) <= 4:
            continue

        entries.sort(key=lambda e: e["session_date"])
        keep_indices = {0, len(entries) - 1, len(entries) - 2, len(entries) - 3}
        prune_entries = [e for i, e in enumerate(entries) if i not in keep_indices]

        if not prune_entries:
            continue

        contacts_pruned += 1
        for entry in prune_entries:
            for fpath, fsize in entry["binary_files"]:
                total_files += 1
                total_bytes += fsize
                if execute:
                    try:
                        os.remove(fpath)
                    except Exception as e:
                        logger.error(f"  Failed to delete {fpath}: {e}")

    return {"files": total_files, "bytes": total_bytes, "contacts_pruned": contacts_pruned}


# ============================================================
# TASK 2: Empty Session Cleanup
# ============================================================
def cleanup_empty_sessions(execute: bool = True) -> dict:
    """Delete session dirs with no backups and session.log < 500 bytes."""
    removed = 0
    bytes_recovered = 0

    if not SESSIONS_DIR.exists():
        return {"removed": 0, "bytes": 0}

    for session in sorted(os.listdir(SESSIONS_DIR)):
        session_path = SESSIONS_DIR / session
        if not session_path.is_dir():
            continue

        backups_dir = session_path / "backups"
        session_log = session_path / "session.log"

        has_backups = backups_dir.exists() and any(backups_dir.iterdir()) if backups_dir.exists() else False
        log_size = session_log.stat().st_size if session_log.exists() else 0

        # Empty session: no backups AND log < 500 bytes (just startup/shutdown lines)
        if not has_backups and log_size < 500:
            dir_size = sum(f.stat().st_size for f in session_path.rglob("*") if f.is_file())
            if execute:
                try:
                    shutil.rmtree(session_path)
                    removed += 1
                    bytes_recovered += dir_size
                except Exception as e:
                    logger.error(f"  Failed to remove {session_path}: {e}")
            else:
                removed += 1
                bytes_recovered += dir_size

    return {"removed": removed, "bytes": bytes_recovered}


# ============================================================
# TASK 3: Feedback Archival
# ============================================================
def archive_old_feedback(execute: bool = True) -> dict:
    """Move feedback entries older than 90 days to archive file."""
    if not FEEDBACK_LOG.exists():
        return {"archived": 0, "kept": 0}

    cutoff = datetime.now() - timedelta(days=FEEDBACK_RETENTION_DAYS)
    kept_entries = []
    archived_entries = []

    with open(FEEDBACK_LOG, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts < cutoff:
                    archived_entries.append(line)
                else:
                    kept_entries.append(line)
            except (json.JSONDecodeError, KeyError, ValueError):
                kept_entries.append(line)  # Keep unparseable entries

    if execute and archived_entries:
        # Append to archive
        with open(FEEDBACK_ARCHIVE, 'a') as f:
            for line in archived_entries:
                f.write(line + "\n")
        # Rewrite active log
        with open(FEEDBACK_LOG, 'w') as f:
            for line in kept_entries:
                f.write(line + "\n")

    return {"archived": len(archived_entries), "kept": len(kept_entries)}


# ============================================================
# MAIN
# ============================================================
def main():
    dry_run = "--dry-run" in sys.argv
    quiet = "--quiet" in sys.argv

    if quiet:
        # Remove stdout handler, keep file handler only
        for handler in logging.root.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
                logging.root.removeHandler(handler)

    mode = "DRY RUN" if dry_run else "EXECUTE"
    execute = not dry_run

    logger.info("=" * 60)
    logger.info(f"LSAM Session Maintenance Daemon — {mode}")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # Task 1: Binary Asset Pruning
    logger.info("")
    logger.info("--- Task 1: Binary Asset Pruning ---")
    prune_result = prune_binary_assets(execute=execute)
    logger.info(f"  Contacts pruned:  {prune_result['contacts_pruned']}")
    logger.info(f"  Files {'deleted' if execute else 'to delete'}:  {prune_result['files']}")
    logger.info(f"  Space {'recovered' if execute else 'to recover'}:  {prune_result['bytes'] / 1024 / 1024:.1f} MB")

    # Task 2: Empty Session Cleanup
    logger.info("")
    logger.info("--- Task 2: Empty Session Cleanup ---")
    empty_result = cleanup_empty_sessions(execute=execute)
    logger.info(f"  Sessions {'removed' if execute else 'to remove'}:  {empty_result['removed']}")
    logger.info(f"  Space {'recovered' if execute else 'to recover'}:  {empty_result['bytes'] / 1024:.1f} KB")

    # Task 3: Feedback Archival
    logger.info("")
    logger.info("--- Task 3: Feedback Archival ---")
    feedback_result = archive_old_feedback(execute=execute)
    logger.info(f"  Entries {'archived' if execute else 'to archive'}:  {feedback_result['archived']}")
    logger.info(f"  Entries kept:    {feedback_result['kept']}")

    # Summary
    total_bytes = prune_result["bytes"] + empty_result["bytes"]
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total space {'recovered' if execute else 'to recover'}: {total_bytes / 1024 / 1024:.1f} MB")
    logger.info(f"Next run: schedule via launchd (see scripts/com.lsam.maintenance.plist)")
    logger.info("")


if __name__ == "__main__":
    main()
