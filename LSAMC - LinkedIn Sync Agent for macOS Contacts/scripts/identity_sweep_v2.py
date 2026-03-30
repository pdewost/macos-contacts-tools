#!/usr/bin/env python3
"""
LSAM Identity Sweep v2.0
Version: 2.0.0

Purpose:
    Automated degree + name verification for Category A contacts (Step 2).
    Uses pro_sync_agent.py to extract LinkedIn connection_degree and full_name
    from each profile, then classifies and optionally applies results.

Architecture (three operational modes):
    --prepare  : Read checklist[94:], create sweep group, populate Burst A,
                 write data/sweep_manifest.json (contact_id → checklist entry)
    --report   : Scan session profile.jsons, classify each contact,
                 write data/sweep_results.json + BRAIN/AUDIT_SWEEP_RESULTS.md
    --apply    : Apply results to macOS Contacts (Surgical Reset for PROMOTE,
                 quarantine tag for QUARANTINE; skip AMBIGUOUS / ERROR)

Recommended Workflow:
    Step 1:  python3 scripts/identity_sweep_v2.py --prepare
             → Creates "script-LSAMC-Identity-Sweep" group with Burst A (80 contacts)
             → Writes data/sweep_manifest.json

    Step 2:  LSAMC_ENGINE=PRO python3 supervisor.py --group "script-LSAMC-Identity-Sweep"
             (Dry-Run mode is sufficient — degree extraction does not require FULL writes)

    Step 3:  python3 scripts/identity_sweep_v2.py --report [--session PATH]
             → Parses session profile.jsons via manifest
             → Writes data/sweep_results.json + BRAIN/AUDIT_SWEEP_RESULTS.md

    Step 4:  Human review of BRAIN/AUDIT_SWEEP_RESULTS.md

    Step 5:  python3 scripts/identity_sweep_v2.py --apply [--full] [--yes]
             → PROMOTE   : wash_note() + ensure in script-LSAM-Priority
             → QUARANTINE: tag note + add to script-LSAM-LinkedIn to Review
             → AMBIGUOUS : skip (manual review required)
             → ERROR     : skip (profile unresolved / 404 / private)

Double-Burst Protocol (rate-limit safety):
    Burst A: 80 contacts  →  wait 30 min  →  Burst B: 81 contacts
    Between bursts: stop supervisor, wait for cooling, restart with Burst B group.
    Run --prepare twice (once with default --burst-a 80, once with --burst-b-mode).

Classification Logic:
    PROMOTE    : degree == 1  AND  name MATCH   → Surgical Reset candidate
    QUARANTINE : degree != 1  OR   name MISMATCH → Wrong Horse
    AMBIGUOUS  : degree == 1  AND  name PARTIAL  → Human review
    ERROR      : degree is None                  → Unresolved / private / 404
"""

import sys
import os
import re
import json
import unicodedata
import argparse
import glob as glob_module
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# Add project root to path for bridge import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.bridge.contact_macos import ContactMacOSBridge  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────────

VERSION                 = "2.0.0"
CHECKLIST_PATH          = "data/step2_verification_checklist.json"
FIRST_UNVERIFIED_INDEX  = 94        # Batches 1–5 complete (indices 0–93)
SWEEP_GROUP             = "script-LSAMC-Identity-Sweep"
PROMOTE_GROUP           = "script-LSAM-Priority"
QUARANTINE_GROUP        = "script-LSAM-LinkedIn to Review"
BURST_A_SIZE            = 80
BURST_B_SIZE            = 81
RESULTS_PATH            = "data/sweep_results.json"
MANIFEST_PATH           = "data/sweep_manifest.json"
AUDIT_REPORT_PATH       = "BRAIN/AUDIT_SWEEP_RESULTS.md"

# Name-diff stopwords (FR / EN / DE / NL / ES / IT / AR)
STOPWORDS = {
    "de", "du", "le", "la", "les", "un", "une", "des", "au", "aux",   # FR
    "von", "van", "der", "die", "das", "den",                          # DE / NL
    "di", "da", "del", "della",                                         # IT / ES
    "el", "al", "bin", "binti",                                         # AR / Malay
    "the", "of", "and", "d",                                            # EN / abbrev
    "mr", "mrs", "ms", "dr", "me", "m",                                 # Titles
    "jr", "sr", "ii", "iii",
}


# ── Name Diff Algorithm ────────────────────────────────────────────────────────

def _normalize_tokens(name: str) -> set:
    """
    Normalize a name to a set of lowercase ASCII tokens.
    Strips accents, splits on spaces / hyphens / dots / apostrophes,
    removes stopwords and single-character tokens.
    """
    if not name:
        return set()
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = re.split(r"[\s\-\.\,\']+", name)
    return {t for t in tokens if t and t not in STOPWORDS and len(t) > 1}


def name_diff(linkedin_name: str, macos_name: str) -> str:
    """
    Compare a LinkedIn full_name to a macOS contact name.

    Returns:
        MATCH    — ≥ 2 tokens in common (high confidence same person)
        PARTIAL  — exactly 1 token in common, at least one name has ≥ 2 tokens
        MISMATCH — 0 tokens in common (wrong horse)
    """
    li  = _normalize_tokens(linkedin_name)
    mac = _normalize_tokens(macos_name)
    if not li or not mac:
        return "MISMATCH"
    common = li & mac
    if len(common) >= 2:
        return "MATCH"
    if len(common) == 1 and (len(mac) >= 2 or len(li) >= 2):
        return "PARTIAL"
    return "MISMATCH"


def classify(degree: Optional[int], diff: str) -> str:
    """
    4-tier classification:

        PROMOTE    degree == 1  AND  MATCH     → Surgical Reset candidate
        QUARANTINE degree != 1  OR   MISMATCH  → Wrong Horse
        AMBIGUOUS  degree == 1  AND  PARTIAL   → Human review
        ERROR      degree is None              → Unresolved / 404 / private
    """
    if degree is None:
        return "ERROR"
    if degree == 1 and diff == "MATCH":
        return "PROMOTE"
    if degree != 1 or diff == "MISMATCH":
        return "QUARANTINE"
    return "AMBIGUOUS"  # degree == 1 AND PARTIAL


# ── Note Operations ────────────────────────────────────────────────────────────

def wash_note(note: str) -> str:
    """
    Surgical Reset: strips the <Linkedin-AI-sync> block from a contact note,
    preserving any human-written content.
    """
    if not note:
        return ""
    clean = re.sub(
        r"<Linkedin-AI-sync.*?</Linkedin-AI-sync>", "", note, flags=re.DOTALL
    ).strip()
    clean = clean.replace("#lsam-force-resync", "").strip()
    return clean


# ── Helpers ────────────────────────────────────────────────────────────────────

def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _abs(relative_path: str) -> str:
    return os.path.join(_project_root(), relative_path)


def _load_checklist() -> List[Dict]:
    with open(_abs(CHECKLIST_PATH), "r", encoding="utf-8") as f:
        return json.load(f)


def _load_manifest() -> Dict[str, Dict]:
    """Load sweep_manifest.json → {contact_id: checklist_entry}."""
    path = _abs(MANIFEST_PATH)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(manifest: Dict[str, Dict]) -> None:
    os.makedirs(os.path.dirname(_abs(MANIFEST_PATH)), exist_ok=True)
    with open(_abs(MANIFEST_PATH), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


# ── Mode: --prepare ────────────────────────────────────────────────────────────

def cmd_prepare(args, bridge: ContactMacOSBridge) -> None:
    """
    Read checklist[start_index : start_index + burst_a], add each contact to
    the sweep group in macOS Contacts, and persist a manifest of
    contact_id → checklist entry for use by --report.
    """
    start_idx = args.start_index
    burst_a   = args.burst_a

    print(f"=== Identity Sweep v{VERSION} — PREPARE ===")
    print(f"Checklist : {CHECKLIST_PATH}")
    print(f"Start idx : {start_idx}  |  Burst A : {burst_a}  |  Burst B (next run): {BURST_B_SIZE}")

    checklist = _load_checklist()
    remaining = checklist[start_idx:]
    burst_slice = remaining[:burst_a]

    print(f"\nChecklist total : {len(checklist)}")
    print(f"Remaining       : {len(remaining)}  (indices {start_idx}–{len(checklist)-1})")
    print(f"Burst A slice   : {len(burst_slice)}  (indices {start_idx}–{start_idx + len(burst_slice) - 1})")

    if not burst_slice:
        print("\n✅ Nothing to prepare — checklist exhausted from index", start_idx)
        return

    # Load existing manifest to avoid duplicates
    manifest = _load_manifest()

    found_count = 0
    not_found   = []

    for i, entry in enumerate(burst_slice):
        name   = entry["name"]
        handle = entry.get("handle", "")
        idx    = start_idx + i

        res = bridge.find_contact(name)
        matches = res.get("matches", []) if res.get("success") else []
        if not matches:
            not_found.append({"idx": idx, "name": name, "handle": handle})
            print(f"  ❌ [{idx:3d}] Not found : {name}")
            continue

        # Use first match (same logic as apply_step2_results.py)
        cid = matches[0]["id"]

        add_res = bridge.add_to_group(cid, SWEEP_GROUP)
        if add_res.get("success"):
            found_count += 1
            # Persist in manifest: contact_id → full checklist entry + resolved name
            manifest[cid] = {
                **entry,
                "checklist_idx": idx,
                "resolved_macos_name": matches[0].get("name", name),
            }
            print(f"  ✅ [{idx:3d}] {name} ({handle})  →  {SWEEP_GROUP}")
        else:
            not_found.append({"idx": idx, "name": name, "handle": handle})
            print(f"  ⚠️  [{idx:3d}] {name} — add_to_group failed: {add_res.get('error')}")

    _save_manifest(manifest)

    print(f"\n── Prepare Summary ──────────────────────────")
    print(f"Added to '{SWEEP_GROUP}' : {found_count} / {len(burst_slice)}")
    print(f"Not found               : {len(not_found)}")
    for nf in not_found:
        print(f"  [{nf['idx']:3d}] {nf['name']}  ({nf['handle']})")
    print(f"Manifest written        : {MANIFEST_PATH}")

    print(f"\n── Next Step ────────────────────────────────")
    print(f"Launch the supervisor (Dry-Run is enough for degree extraction):")
    print(f"  LSAMC_ENGINE=PRO python3 supervisor.py --group \"{SWEEP_GROUP}\"")
    print(f"  (add --live for FULL-mode writes — not required for --report)")
    print(f"\nAfter the supervisor finishes, run:")
    print(f"  python3 scripts/identity_sweep_v2.py --report")


# ── Mode: --report ─────────────────────────────────────────────────────────────

def _find_session_dirs(session_arg: Optional[str], max_sessions: int) -> List[str]:
    """Return a list of session directories to scan for profile.jsons."""
    if session_arg:
        return [os.path.abspath(session_arg)]
    sessions_base = _abs(os.path.join("logs", "sessions"))
    dirs = sorted(
        glob_module.glob(os.path.join(sessions_base, "run_*")),
        key=os.path.getmtime,
        reverse=True,
    )
    return dirs[:max_sessions]


def _load_profiles_from_session(session_dir: str) -> List[Dict]:
    """Collect all profile.json files from a session's backups/ sub-directory."""
    backups = os.path.join(session_dir, "backups")
    if not os.path.isdir(backups):
        return []
    profiles = []
    for contact_dir in os.listdir(backups):
        pfile = os.path.join(backups, contact_dir, "profile.json")
        if not os.path.isfile(pfile):
            continue
        try:
            with open(pfile, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_source_session"] = os.path.basename(session_dir)
            data["_source_path"]    = pfile
            profiles.append(data)
        except Exception as e:
            print(f"  ⚠️  Could not load {pfile}: {e}")
    return profiles


def cmd_report(args, bridge: ContactMacOSBridge) -> None:
    """
    Scan session directories for profile.jsons, cross-reference with the
    sweep manifest, classify each contact, and produce:
        data/sweep_results.json
        BRAIN/AUDIT_SWEEP_RESULTS.md
    """
    print(f"=== Identity Sweep v{VERSION} — REPORT ===")

    manifest = _load_manifest()
    if not manifest:
        print(
            f"⚠️  Manifest is empty ({MANIFEST_PATH}).\n"
            f"   Run --prepare first, or use --all-profiles to process all found profiles."
        )
        if not args.all_profiles:
            return

    session_dirs = _find_session_dirs(args.session, args.max_sessions)
    if not session_dirs:
        print("❌ No session directories found.")
        return

    # Collect all profiles
    all_profiles: List[Dict] = []
    for sdir in session_dirs:
        batch = _load_profiles_from_session(sdir)
        if batch:
            print(f"  {os.path.basename(sdir)} : {len(batch)} profiles")
        all_profiles.extend(batch)

    print(f"\nTotal profiles loaded : {len(all_profiles)}")

    if not all_profiles:
        print("❌ No profile.json files found in scanned sessions.")
        print("   Did the supervisor process the sweep group yet?")
        return

    results: List[Dict] = []
    skipped = 0

    for profile in all_profiles:
        contact_id     = profile.get("_contact_id", "")
        linkedin_name  = profile.get("full_name", "")
        degree         = profile.get("connection_degree")

        # --- Resolve checklist entry via manifest (preferred) ---
        checklist_entry = manifest.get(contact_id) if contact_id else None

        # --- Fallback: fuzzy name match against manifest values ---
        if not checklist_entry and manifest:
            li_tokens = _normalize_tokens(linkedin_name)
            for cid, entry in manifest.items():
                if li_tokens & _normalize_tokens(entry["name"]):
                    checklist_entry = entry
                    break

        if not checklist_entry and not args.all_profiles:
            skipped += 1
            continue

        # macOS name for diff: prefer manifest's resolved name, else linkedin_name
        macos_name = (checklist_entry or {}).get("resolved_macos_name", linkedin_name)

        diff           = name_diff(linkedin_name, macos_name)
        classification = classify(degree, diff)

        results.append({
            "checklist_idx"  : (checklist_entry or {}).get("checklist_idx"),
            "checklist_name" : (checklist_entry or {}).get("name", linkedin_name),
            "linkedin_name"  : linkedin_name,
            "macos_name"     : macos_name,
            "handle"         : (checklist_entry or {}).get("handle", ""),
            "contact_id"     : contact_id,
            "degree"         : degree,
            "diff"           : diff,
            "classification" : classification,
            "reason"         : (checklist_entry or {}).get("reason", ""),
            "session"        : profile.get("_source_session", ""),
        })

    if skipped:
        print(
            f"  (Skipped {skipped} profiles not in sweep manifest"
            f" — run with --all-profiles to include them)"
        )

    # Sort: PROMOTE → AMBIGUOUS → QUARANTINE → ERROR, then by name
    _order = {"PROMOTE": 0, "AMBIGUOUS": 1, "QUARANTINE": 2, "ERROR": 3}
    results.sort(key=lambda r: (_order.get(r["classification"], 9), r["checklist_name"] or ""))

    counts = {k: sum(1 for r in results if r["classification"] == k)
              for k in ("PROMOTE", "AMBIGUOUS", "QUARANTINE", "ERROR")}

    # Write JSON results
    os.makedirs(os.path.dirname(_abs(RESULTS_PATH)), exist_ok=True)
    with open(_abs(RESULTS_PATH), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults JSON written : {RESULTS_PATH}  ({len(results)} entries)")

    # Write markdown audit report
    _write_audit_report(results, counts)

    # Print summary
    print(f"\n── Classification Summary ───────────────────")
    print(f"  ✅ PROMOTE    : {counts['PROMOTE']:3d}  (1st-degree + name MATCH → Surgical Reset)")
    print(f"  ⚠️  AMBIGUOUS  : {counts['AMBIGUOUS']:3d}  (1st-degree + partial name → human review)")
    print(f"  ❌ QUARANTINE : {counts['QUARANTINE']:3d}  (wrong degree or name mismatch → LinkedIn to Review)")
    print(f"  🚫 ERROR      : {counts['ERROR']:3d}  (unresolved / 404 / private → skip)")
    print(f"  ─────────────────────────────────────────")
    print(f"     TOTAL      : {len(results):3d}")
    print(f"\nAudit report : {AUDIT_REPORT_PATH}")
    print(f"\nReview the report, then run:")
    print(f"  python3 scripts/identity_sweep_v2.py --apply [--full] [--yes]")


def _write_audit_report(results: List[Dict], counts: Dict[str, int]) -> None:
    """Write the human-readable markdown audit report to BRAIN/."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(results)

    lines = [
        "# Identity Sweep — Audit Report",
        f"**Generated** : {now}  |  **Tool** : `identity_sweep_v2.py` v{VERSION}",
        f"**Scope** : checklist indices {FIRST_UNVERIFIED_INDEX}+ ({total} contacts processed)",
        "",
        "## Summary",
        "",
        "| Classification | Count | Auto-action |",
        "|:---|:---:|:---|",
        f"| ✅ PROMOTE    | {counts['PROMOTE']} | Surgical Reset → add to Priority |",
        f"| ⚠️ AMBIGUOUS  | {counts['AMBIGUOUS']} | **Manual review required** |",
        f"| ❌ QUARANTINE | {counts['QUARANTINE']} | Tag note → move to LinkedIn to Review |",
        f"| 🚫 ERROR      | {counts['ERROR']} | Skip — profile unresolved |",
        f"| **TOTAL**     | **{total}** | |",
        "",
        "---",
        "",
    ]

    def _table_section(title: str, label: str, cols_extra: bool, rows: List[Dict]) -> List[str]:
        if not rows:
            return []
        out = [f"## {title}", ""]
        if cols_extra:
            out += [
                "| # | macOS Name | LinkedIn Name | Handle | °  | Diff | Reason |",
                "|:--|:-----------|:--------------|:-------|:--:|:-----|:-------|",
            ]
            for i, r in enumerate(rows, 1):
                out.append(
                    f"| {i} | {r['macos_name']} | {r['linkedin_name']} "
                    f"| `{r['handle']}` | {r['degree']} | {r['diff']} | {r['reason']} |"
                )
        else:
            out += [
                "| # | macOS Name | LinkedIn Name | Handle | °  | Diff |",
                "|:--|:-----------|:--------------|:-------|:--:|:-----|",
            ]
            for i, r in enumerate(rows, 1):
                out.append(
                    f"| {i} | {r['macos_name']} | {r['linkedin_name']} "
                    f"| `{r['handle']}` | {r['degree']} | {r['diff']} |"
                )
        out.append("")
        return out

    lines += _table_section(
        "✅ PROMOTE — Surgical Reset Candidates", "PROMOTE", False,
        [r for r in results if r["classification"] == "PROMOTE"]
    )
    lines += _table_section(
        "⚠️ AMBIGUOUS — Human Review Required", "AMBIGUOUS", True,
        [r for r in results if r["classification"] == "AMBIGUOUS"]
    )
    lines += _table_section(
        "❌ QUARANTINE — Wrong Horse", "QUARANTINE", True,
        [r for r in results if r["classification"] == "QUARANTINE"]
    )

    errors = [r for r in results if r["classification"] == "ERROR"]
    if errors:
        lines += [
            "## 🚫 ERROR — Unresolved Profiles",
            "",
            "| # | macOS Name | Handle | Reason |",
            "|:--|:-----------|:-------|:-------|",
        ]
        for i, r in enumerate(errors, 1):
            lines.append(f"| {i} | {r['macos_name']} | `{r['handle']}` | {r['reason']} |")
        lines.append("")

    lines += [
        "---",
        "",
        f"*Generated by `identity_sweep_v2.py` v{VERSION} — {now}*",
        f"*Apply with: `python3 scripts/identity_sweep_v2.py --apply [--full]`*",
    ]

    report_abs = _abs(AUDIT_REPORT_PATH)
    os.makedirs(os.path.dirname(report_abs), exist_ok=True)
    with open(report_abs, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Audit MD written     : {AUDIT_REPORT_PATH}")


# ── Mode: --apply ──────────────────────────────────────────────────────────────

def cmd_apply(args, bridge: ContactMacOSBridge) -> None:
    """
    Apply sweep results to macOS Contacts:

        PROMOTE    → wash_note() + ensure in PROMOTE_GROUP
        QUARANTINE → prepend identity tag + add to QUARANTINE_GROUP
        AMBIGUOUS  → skip (manual review)
        ERROR      → skip
    """
    print(f"=== Identity Sweep v{VERSION} — APPLY ===")

    results_abs = _abs(args.results)
    if not os.path.isfile(results_abs):
        print(f"❌ Results file not found: {args.results}")
        print(f"   Run --report first.")
        return

    with open(results_abs, "r", encoding="utf-8") as f:
        results = json.load(f)

    promote    = [r for r in results if r["classification"] == "PROMOTE"]
    quarantine = [r for r in results if r["classification"] == "QUARANTINE"]
    ambiguous  = [r for r in results if r["classification"] == "AMBIGUOUS"]
    errors     = [r for r in results if r["classification"] == "ERROR"]

    mode = "FULL" if args.full else "SIMULATION"
    print(f"\nMode       : {mode}")
    print(f"PROMOTE    : {len(promote)}")
    print(f"QUARANTINE : {len(quarantine)}")
    print(f"AMBIGUOUS  : {len(ambiguous)} — SKIPPED (manual review)")
    print(f"ERROR      : {len(errors)} — SKIPPED")

    if not promote and not quarantine:
        print("\nNothing to apply.")
        return

    # --- Confirmation gate (FULL mode only) ---
    if args.full and not args.yes:
        total_mutations = len(promote) + len(quarantine)
        print(f"\n⚠️  About to modify {total_mutations} contacts in macOS Contacts.")
        print(f"   PROMOTE    ({len(promote)}) : note washed + moved to '{PROMOTE_GROUP}'")
        print(f"   QUARANTINE ({len(quarantine)}) : identity tag prepended + moved to '{QUARANTINE_GROUP}'")
        answer = input("\n   Type APPLY to confirm, anything else to abort: ").strip()
        if answer != "APPLY":
            print("Aborted.")
            return
    elif not args.full:
        print(f"\n[SIMULATION] Dry-run — no contact will be modified.")

    applied_promote    = 0
    applied_quarantine = 0
    failed: List[Dict] = []

    # ── PROMOTE ─────────────────────────────────────────────────────────────

    print(f"\n── PROMOTE ({len(promote)}) {'[SIMULATION]' if not args.full else '[LIVE]'} ──")

    for r in promote:
        name = r["checklist_name"]
        cid  = r.get("contact_id") or ""

        if not cid:
            res = bridge.find_contact(name)
            if not res.get("success") or not res.get("matches"):
                print(f"  ❌ {name} — not found in Contacts")
                failed.append({"name": name, "reason": "not_found", "classification": "PROMOTE"})
                continue
            cid = res["matches"][0]["id"]

        print(f"  [WASH] {name}", end="")

        if args.full:
            # Fetch current note
            det = bridge.get_contact_details(cid)
            if not det.get("success"):
                print(f"\n    ❌ get_contact_details failed: {det.get('error')}")
                failed.append({"name": name, "reason": "get_details_failed", "classification": "PROMOTE"})
                continue

            clean_note  = wash_note(det.get("note", ""))
            update_res  = bridge.update_note(cid, clean_note)
            if not update_res.get("success"):
                print(f"\n    ❌ update_note failed: {update_res.get('error')}")
                failed.append({"name": name, "reason": "update_note_failed", "classification": "PROMOTE"})
                continue

            # Ensure contact is in Priority group
            bridge.add_to_group(cid, PROMOTE_GROUP)
            applied_promote += 1
            print(f"  ✅  note washed + in '{PROMOTE_GROUP}'")
        else:
            applied_promote += 1
            print(f"  [SIM] would wash note + add to '{PROMOTE_GROUP}'")

    # ── QUARANTINE ───────────────────────────────────────────────────────────

    print(f"\n── QUARANTINE ({len(quarantine)}) {'[SIMULATION]' if not args.full else '[LIVE]'} ──")

    for r in quarantine:
        name   = r["checklist_name"]
        cid    = r.get("contact_id") or ""
        degree = r.get("degree")
        diff   = r.get("diff")
        stamp  = datetime.now().strftime("%Y-%m-%d")
        tag    = f"⚠️ Identity Sweep {stamp}: degree={degree}, diff={diff}"

        if not cid:
            res = bridge.find_contact(name)
            if not res.get("success") or not res.get("matches"):
                print(f"  ❌ {name} — not found in Contacts")
                failed.append({"name": name, "reason": "not_found", "classification": "QUARANTINE"})
                continue
            cid = res["matches"][0]["id"]

        print(f"  [TAG] {name}  (degree={degree}, diff={diff})", end="")

        if args.full:
            # Prepend tag via get_details + update_note (defensive: avoids dependency on prepend_to_note)
            det = bridge.get_contact_details(cid)
            if not det.get("success"):
                print(f"\n    ❌ get_contact_details failed: {det.get('error')}")
                failed.append({"name": name, "reason": "get_details_failed", "classification": "QUARANTINE"})
                continue

            existing_note = det.get("note", "")
            new_note      = tag + ("\n" + existing_note if existing_note else "")
            update_res    = bridge.update_note(cid, new_note)
            if not update_res.get("success"):
                print(f"\n    ❌ update_note failed: {update_res.get('error')}")
                failed.append({"name": name, "reason": "update_note_failed", "classification": "QUARANTINE"})
                continue

            bridge.add_to_group(cid, QUARANTINE_GROUP)
            applied_quarantine += 1
            print(f"  ✅  tagged + in '{QUARANTINE_GROUP}'")
        else:
            applied_quarantine += 1
            print(f"  [SIM] would tag '{tag[:60]}…' + add to '{QUARANTINE_GROUP}'")

    # ── Summary ──────────────────────────────────────────────────────────────

    print(f"\n── Apply Summary ────────────────────────────")
    print(f"  PROMOTE applied    : {applied_promote} / {len(promote)}")
    print(f"  QUARANTINE applied : {applied_quarantine} / {len(quarantine)}")
    print(f"  AMBIGUOUS skipped  : {len(ambiguous)}")
    print(f"  ERROR skipped      : {len(errors)}")
    if failed:
        print(f"  FAILED             : {len(failed)}")
        for item in failed:
            print(f"    ❌ {item['name']}  ({item['classification']}) — {item['reason']}")

    if not args.full:
        print(f"\n  ⚠️  Simulation only. Run with --full to write changes.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="identity_sweep_v2.py",
        description=f"LSAM Identity Sweep v{VERSION} — Automated Cat-A degree + name verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/identity_sweep_v2.py --prepare\n"
            "  LSAMC_ENGINE=PRO python3 supervisor.py --group 'script-LSAMC-Identity-Sweep'\n"
            "  python3 scripts/identity_sweep_v2.py --report\n"
            "  python3 scripts/identity_sweep_v2.py --apply --full\n"
        ),
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--prepare", action="store_true",
                            help="Create sweep group, populate Burst A, write manifest")
    mode_group.add_argument("--report",  action="store_true",
                            help="Parse session profiles, classify, write audit report")
    mode_group.add_argument("--apply",   action="store_true",
                            help="Apply sweep results to macOS Contacts")

    # --prepare options
    parser.add_argument("--start-index", type=int, default=FIRST_UNVERIFIED_INDEX,
                        help=f"First checklist index to process (default: {FIRST_UNVERIFIED_INDEX})")
    parser.add_argument("--burst-a",     type=int, default=BURST_A_SIZE,
                        help=f"Burst A contact count (default: {BURST_A_SIZE})")

    # --report options
    parser.add_argument("--session",      type=str, default=None,
                        help="Specific session dir to parse (default: scan recent sessions)")
    parser.add_argument("--max-sessions", type=int, default=10,
                        help="Max recent sessions to scan (default: 10)")
    parser.add_argument("--all-profiles", action="store_true",
                        help="Include profiles not matched in the sweep manifest")

    # --apply options
    parser.add_argument("--results", type=str, default=RESULTS_PATH,
                        help=f"Results JSON to apply (default: {RESULTS_PATH})")
    parser.add_argument("--full",    action="store_true",
                        help="Execute writes; default is simulation")
    parser.add_argument("--yes",     action="store_true",
                        help="Skip confirmation prompt (use with --full)")

    args = parser.parse_args()

    # Bridge mode: FULL only for --apply --full
    bridge_mode = "FULL" if (args.apply and args.full) else "SIMULATION"
    bridge = ContactMacOSBridge(mode=bridge_mode)

    if args.prepare:
        cmd_prepare(args, bridge)
    elif args.report:
        cmd_report(args, bridge)
    elif args.apply:
        cmd_apply(args, bridge)


if __name__ == "__main__":
    main()
