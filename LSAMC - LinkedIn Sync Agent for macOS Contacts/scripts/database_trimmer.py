#!/usr/bin/env python3
"""
LSAM Database Trimmer — v1.0 (2026-03-11)
==========================================
Phase 4 of the Master Plan: audit and trim oversized vault photos.

SAFETY: scan / estimate / dry_run are fully READ-ONLY.
        apply writes vault files only — macOS Contacts are NOT modified.
        To push resized photos back to Contacts, add contacts to
        'script-LSAM-Force-Refresh' and run the sync agent.

Modes:
  --mode scan      Walk data/vault/, measure all HEIC photos. Write CSV. (read-only)
  --mode estimate  Show space savings at different downsampling targets. (read-only)
  --mode dry_run   List which photos would be resized at --target. (read-only)
  --mode apply     Resize vault HEICs to --target. Requires --confirm.

Usage:
  python3 scripts/database_trimmer.py --mode scan
  python3 scripts/database_trimmer.py --mode estimate
  python3 scripts/database_trimmer.py --mode dry_run --target 1024
  python3 scripts/database_trimmer.py --mode apply --target 1024 --confirm

See AUDIT_2026-03-11.md §R4 and INCIDENT_MORENO_20260309.md for safety context.
"""

import argparse
import csv
import datetime
import logging
import os
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("database_trimmer")

# Default paths (relative to project root — run from project root)
VAULT_DIR = "data/vault"
LOG_DIR = "logs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_image_info(heic_path: str) -> dict:
    """Return {width, height, max_dim, size_bytes} for a file. Returns zeros on error."""
    try:
        result = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", heic_path],
            capture_output=True, text=True, timeout=10,
        )
        w, h = 0, 0
        for line in result.stdout.splitlines():
            if "pixelWidth" in line:
                w = int(line.split(":")[-1].strip())
            elif "pixelHeight" in line:
                h = int(line.split(":")[-1].strip())
        size = os.path.getsize(heic_path)
        return {"width": w, "height": h, "max_dim": max(w, h), "size_bytes": size}
    except Exception as exc:
        logger.warning(f"Cannot inspect {heic_path}: {exc}")
        return {"width": 0, "height": 0, "max_dim": 0, "size_bytes": 0}


def walk_vault(vault_dir: str) -> list:
    """Walk vault_dir recursively, collect info for every .heic file. Returns sorted list."""
    if not os.path.isdir(vault_dir):
        logger.error(f"Vault directory not found: '{vault_dir}'. Run from project root.")
        sys.exit(1)

    records = []
    for root, _dirs, files in os.walk(vault_dir):
        for fname in sorted(files):
            if not fname.lower().endswith(".heic"):
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, vault_dir)
            contact_name = os.path.basename(root).replace("_", " ")
            info = get_image_info(full_path)
            records.append({
                "contact": contact_name,
                "path": full_path,
                "rel_path": rel_path,
                "width": info["width"],
                "height": info["height"],
                "max_dim": info["max_dim"],
                "size_bytes": info["size_bytes"],
            })

    return sorted(records, key=lambda r: r["max_dim"], reverse=True)


def _separator():
    print("=" * 60)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def cmd_scan(vault_dir: str):
    """Walk vault and write a full CSV inventory. No writes to photos."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    csv_path = os.path.join(LOG_DIR, f"database_trimmer_scan_{ts}.csv")

    logger.info(f"Scanning '{vault_dir}' ...")
    records = walk_vault(vault_dir)

    os.makedirs(LOG_DIR, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["contact", "rel_path", "width", "height", "max_dim", "size_bytes"],
        )
        writer.writeheader()
        writer.writerows(records)

    _separator()
    print(f"SCAN COMPLETE — {len(records)} HEIC photos found")
    _separator()
    if records:
        sizes = [r["size_bytes"] for r in records]
        dims = [r["max_dim"] for r in records if r["max_dim"] > 0]
        print(f"  Total size:    {sum(sizes) / 1024 / 1024:.1f} MB")
        print(f"  Avg size:      {sum(sizes) / len(sizes) / 1024:.1f} KB")
        if dims:
            print(f"  Avg max_dim:   {sum(dims) / len(dims):.0f} px")
            print(f"  Largest:       {max(dims)} px")
            print(f"  Smallest:      {min(dims)} px")
        over_1024 = sum(1 for d in dims if d > 1024)
        print(f"  > 1024px:      {over_1024} photos")
    print(f"\nCSV written to: {csv_path}")


# ---------------------------------------------------------------------------
# estimate
# ---------------------------------------------------------------------------

def cmd_estimate(vault_dir: str):
    """Show projected savings at various downsampling targets. Read-only."""
    logger.info("Running estimate (read-only) ...")
    records = walk_vault(vault_dir)
    total_bytes = sum(r["size_bytes"] for r in records)

    _separator()
    print(f"ESTIMATE — {len(records)} photos, {total_bytes / 1024 / 1024:.1f} MB total")
    _separator()

    for target in [512, 768, 1024]:
        affected = [r for r in records if r["max_dim"] > target]
        if not affected:
            print(f"  Target {target}px: 0 photos exceed limit — no work needed")
            continue
        # Estimate size reduction: HEIC sizes scale roughly with pixel area
        saved_bytes = sum(
            r["size_bytes"] * (1 - (target / r["max_dim"]) ** 2)
            for r in affected
        )
        pct = saved_bytes / total_bytes * 100 if total_bytes else 0
        print(
            f"  Target {target}px:  {len(affected):>4} photos affected  →  "
            f"~{saved_bytes / 1024:.0f} KB savings  ({pct:.1f}% of vault)"
        )

    print(f"\n  Recommended: --target 1024 (matches spec; minimal impact on quality)")


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

def cmd_dry_run(vault_dir: str, target: int):
    """List photos that would be resized. No writes."""
    logger.info(f"Dry run at target={target}px (read-only) ...")
    records = walk_vault(vault_dir)
    affected = [r for r in records if r["max_dim"] > target]

    _separator()
    print(f"DRY RUN — target {target}px — {len(affected)}/{len(records)} photos would be resized")
    _separator()

    PREVIEW_LIMIT = 50
    for r in affected[:PREVIEW_LIMIT]:
        print(
            f"  {r['contact']:<42} {r['max_dim']:>5}px  {r['size_bytes'] // 1024:>5}KB  "
            f"{r['rel_path']}"
        )
    if len(affected) > PREVIEW_LIMIT:
        print(f"  ... and {len(affected) - PREVIEW_LIMIT} more (see CSV from --mode scan)")

    if affected:
        saved = sum(r["size_bytes"] * (1 - (target / r["max_dim"]) ** 2) for r in affected)
        print(f"\n  Estimated savings: ~{saved / 1024:.0f} KB")

    print(f"\nTo proceed: python3 scripts/database_trimmer.py --mode apply --target {target} --confirm")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def cmd_apply(vault_dir: str, target: int):
    """
    Resize oversized vault HEIC files to --target px. Requires --confirm.

    v4.9.1 MORENO_GUARD compliance:
    - macOS Contacts are NOT touched (Rule 1/3 — no bridge writes)
    - A log is written before any resize (audit trail)
    - Failed resizes are non-fatal and logged
    - To push changes to Contacts: add contacts to 'script-LSAM-Force-Refresh' and re-run sync
    """
    # Import image_optim from project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        from src.bridge.image_optim import optimize_image
    except ImportError as exc:
        logger.error(f"Cannot import image_optim: {exc}. Run from project root.")
        sys.exit(1)

    logger.info(f"APPLY mode: resizing vault photos > {target}px in '{vault_dir}'")
    records = walk_vault(vault_dir)
    affected = [r for r in records if r["max_dim"] > target]

    if not affected:
        print(f"No vault photos exceed {target}px. Nothing to do.")
        return

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    apply_log = os.path.join(LOG_DIR, f"database_trimmer_apply_{ts}.log")
    os.makedirs(LOG_DIR, exist_ok=True)

    _separator()
    print(f"APPLY — resizing {len(affected)} photos to {target}px max dim")
    print(f"Log: {apply_log}")
    _separator()

    ok_count = 0
    fail_count = 0
    total_saved = 0

    with open(apply_log, "w", encoding="utf-8") as log_f:
        log_f.write(f"LSAM Database Trimmer — apply run {ts}\n")
        log_f.write(f"Target: {target}px  Vault: {vault_dir}  Photos: {len(affected)}\n")
        log_f.write(
            "NOTE: vault files only. macOS Contacts NOT modified.\n"
            "Add affected contacts to 'script-LSAM-Force-Refresh' to sync back.\n\n"
        )

        for r in affected:
            orig_path = r["path"]
            orig_size = r["size_bytes"]
            orig_dim = r["max_dim"]

            try:
                # optimize_image creates a sibling <name>_opt.heic
                opt_path = optimize_image(orig_path, max_dimension=target)

                if opt_path == orig_path:
                    # Edge case: optimize_image returned same path (no resize needed)
                    log_f.write(f"SKIP  {r['rel_path']} — already within target\n")
                    continue

                new_size = os.path.getsize(opt_path)
                # Atomically replace original
                os.replace(opt_path, orig_path)
                saving = orig_size - new_size
                total_saved += saving
                ok_count += 1

                line = (
                    f"OK    {r['rel_path']:<55} "
                    f"{orig_dim}px→{target}px  "
                    f"{orig_size // 1024}KB→{new_size // 1024}KB  "
                    f"saved {saving // 1024}KB"
                )
                log_f.write(line + "\n")
                print(f"  ✓ {r['contact']:<42} {orig_dim}→{target}px  saved {saving // 1024}KB")

            except Exception as exc:
                fail_count += 1
                msg = f"FAIL  {r['rel_path']} — {exc}"
                log_f.write(msg + "\n")
                logger.warning(f"  ✗ {r['contact']}: {exc}")

        log_f.write(f"\nSUMMARY: {ok_count} OK, {fail_count} failed, {total_saved // 1024}KB saved\n")
        log_f.write(
            "\nNEXT STEP: To write resized photos back to macOS Contacts:\n"
            "  1. Identify affected contacts from this log\n"
            "  2. Add them to group 'script-LSAM-Force-Refresh' in Contacts.app\n"
            "  3. Run the sync agent (python3 supervisor.py) — it will detect the\n"
            "     higher-quality vault photo and apply it during the next sync pass\n"
        )

    _separator()
    print(f"DONE: {ok_count} resized, {fail_count} failed, {total_saved // 1024}KB saved")
    print(f"Log: {apply_log}")
    print(
        "\nNEXT STEP: Add affected contacts to 'script-LSAM-Force-Refresh'\n"
        "and run supervisor.py to push resized photos to macOS Contacts."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LSAM Database Trimmer — vault photo downsampling tool (v1.0, 2026-03-11)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["scan", "estimate", "dry_run", "apply"],
        required=True,
        help="Operation mode (scan/estimate/dry_run are read-only; apply writes vault files only)",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=1024,
        help="Max dimension in px for dry_run and apply modes (default: 1024)",
    )
    parser.add_argument(
        "--vault",
        default=VAULT_DIR,
        help=f"Path to vault directory (default: {VAULT_DIR})",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required for --mode apply. Confirms you have reviewed --mode dry_run output.",
    )

    args = parser.parse_args()

    if args.mode == "apply" and not args.confirm:
        print(
            "ERROR: --mode apply requires --confirm.\n"
            "Run --mode dry_run first to review what will change, then add --confirm."
        )
        sys.exit(1)

    if args.mode not in ("scan", "estimate") and args.target < 256:
        print(f"ERROR: --target {args.target} is dangerously small. Minimum is 256px.")
        sys.exit(1)

    if args.mode == "scan":
        cmd_scan(args.vault)
    elif args.mode == "estimate":
        cmd_estimate(args.vault)
    elif args.mode == "dry_run":
        cmd_dry_run(args.vault, args.target)
    elif args.mode == "apply":
        cmd_apply(args.vault, args.target)


if __name__ == "__main__":
    main()
