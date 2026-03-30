#!/usr/bin/env python3
"""
LSAM Control Center CLI
Version: 1.5.0
Purpose: Central administrative tool for managing LSAM groups and priority.
Bridges to macOS Contacts.app and provides JSON output for GenAI/AppleScript consumption.
v1.1.0 S2-D: demote --all; S2-E: queue command; S2-F: exit code 2 for not-found
v1.2.0 S3-A: list --sort status (agent triage path)
v1.3.0 S4-A: inspect command; S4-B: promote --csv; S4-C: queue --sort oldest
v1.4.0 S5-A: profile command (vault data display for Contact Review UX)
       S5-B: validate command (mark contact reviewed, remove from LinkedIn to Review)
v1.5.0 Sprint 2: preview command (dry-run diff: vault vs current contact state)
       Sprint 2: edit command (field overrides saved to vault master_profile)
"""

import sys
import os
import argparse
import json
import logging
from typing import List, Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

# Group names (v5.0 standardized) - we use current names for now, 
# F5 will handle the migration to finalized names.
GROUPS = {
    "priority": "script-LSAM-Priority",
    "broken": "script-LSAM-Broken Names",
    "damaged": "script-LSAM-DAMAGED",
    "refresh": "script-LSAM-Force-Refresh",
    "attention": "script-LSAM-Tier3-NeedAttention",
    "review": "script-LSAM-LinkedIn to Review"
}

# S3-A: Status classification — mirrors scanAndSortGroup logic in AppleScript (Pattern I)
# Order: [Failed] overrides [Broken] overrides [Damaged] overrides [Ambiguous] overrides [No Block]
_STATUS_ORDER = {"[Failed]": 0, "[Broken]": 1, "[Damaged]": 2, "[Ambiguous]": 3, "[No Block]": 4}

def _classify_note(note: str) -> str:
    """Classify a contact's status tag from its note field."""
    if not note:
        return "[No Block]"
    if "[Failed]" in note:
        return "[Failed]"
    if "BROKEN" in note:
        return "[Broken]"
    if "DAMAGED" in note:
        return "[Damaged]"
    if "LSAM AMBIGUITY" in note:
        return "[Ambiguous]"
    return "[No Block]"


def _not_found_exit(args):
    """S2-F exit convention: code 2 for shell callers (distinguishable not-found signal).
    v1.4.1: In JSON mode (--json), use exit 0 so AppleScript's do shell script doesn't raise —
    the caller parses the JSON payload's 'success: false' instead of catching an OS error.
    """
    sys.exit(0 if getattr(args, 'json', False) else 2)


def setup_logging(debug: bool, json_mode: bool = False):
    """Configure root logger.
    json_mode=True: suppress stderr logging so stdout contains only clean JSON for AppleScript consumers.
    The AppleScript runCLI handler captures stdout; any log line mixed in breaks JSON.parse.
    In debug mode, logging is always active (developer is not using --json for inspection).
    """
    level = logging.DEBUG if debug else logging.INFO
    if json_mode and not debug:
        # JSON output path: route all logging to NullHandler (silent).
        # Errors will still surface via the JSON {"success": false, "error": ...} payload.
        logging.basicConfig(level=level, handlers=[logging.NullHandler()])
    else:
        logging.basicConfig(
            level=level,
            format='%(levelname)s: %(message)s'
        )

def output_result(data: Dict[str, Any], use_json: bool):
    """Outputs data either as pretty text or JSON."""
    if use_json:
        print(json.dumps(data, indent=2))
    else:
        if "message" in data:
            print(data["message"])
        if "contacts" in data:
            print("\nContacts:")
            for c in data["contacts"]:
                comp = f" ({c['company']})" if c.get('company') else ""
                status = f"  {c['status']}" if c.get('status') else ""
                print(f"- {c['name']}{comp}{status} [ID: {c['id']}]")
        if "stats" in data:
            print("\nGroup Statistics:")
            for g, count in data["stats"].items():
                print(f"  {g:30}: {count}")

def cmd_status(bridge: ContactMacOSBridge, args):
    """Reports current group counts and list of groups."""
    stats = {}
    for key, name in GROUPS.items():
        res = bridge.list_group_contacts(name)
        if res["success"]:
            stats[name] = len(res["matches"])
        else:
            stats[name] = "Not Found"
            
    result = {
        "success": True,
        "stats": stats,
        "mode": bridge.mode
    }
    output_result(result, args.json)

def cmd_list(bridge: ContactMacOSBridge, args):
    """Lists contacts in a specific group, optionally sorted by status (S3-A)."""
    group_name = GROUPS.get(args.group, args.group)
    res = bridge.list_group_contacts(group_name)

    if not res["success"]:
        output_result({"success": False, "error": res.get("error", "Unknown error")}, args.json)
        return

    contacts = res["matches"]
    sort_key = getattr(args, "sort", "alpha")

    if sort_key == "status":
        # S3-A: Bulk-fetch notes in one AppleScript call, classify, sort
        notes_res = bridge.batch_get_group_notes(group_name)
        notes_map = notes_res.get("notes", {}) if notes_res.get("success") else {}
        for c in contacts:
            c["status"] = _classify_note(notes_map.get(c["id"], ""))
        contacts = sorted(
            contacts,
            key=lambda c: (_STATUS_ORDER.get(c["status"], 9), c["name"].lower())
        )
    else:
        contacts = sorted(contacts, key=lambda c: c["name"].lower())

    output_result({
        "success": True,
        "group": group_name,
        "sort": sort_key,
        "total": len(contacts),
        "contacts": contacts
    }, args.json)

def cmd_promote(bridge: ContactMacOSBridge, args):
    """Moves a contact (or CSV list) to the Priority group."""
    target_group = GROUPS["priority"]

    contacts_to_promote = []
    if args.selection:
        res = bridge.get_selection()
        if res["success"]:
            contacts_to_promote = res["matches"]
    elif args.name:
        res = bridge.find_contact(args.name)
        if res["success"]:
            if res.get("ambiguous"):
                output_result({"success": False, "message": f"Ambiguous name '{args.name}'. Matches: {res['matches']}"}, args.json)
                return
            contacts_to_promote = [res]
    elif getattr(args, "csv", None):
        # S4-B: bulk promote from CSV file (must have 'full_name' or 'name' column)
        import csv as csv_mod
        try:
            with open(args.csv, newline="", encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                seen: set = set()
                for row in reader:
                    name = (row.get("full_name") or row.get("name") or "").strip()
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    res = bridge.find_contact(name)
                    if res["success"] and not res.get("ambiguous"):
                        contacts_to_promote.append(res)
        except FileNotFoundError:
            output_result({"success": False, "error": f"CSV not found: {args.csv}"}, args.json)
            return

    if not contacts_to_promote:
        output_result({"success": False, "message": "No contacts found to promote."}, args.json)
        _not_found_exit(args)  # S2-F

    results = []
    for c in contacts_to_promote:
        add_res = bridge.add_to_group(c["id"], target_group)
        results.append({
            "name": c["name"],
            "id": c["id"],
            "status": "PROMOTED" if add_res["success"] else f"FAILED: {add_res.get('error')}"
        })
        
    output_result({
        "success": True,
        "message": f"Processed {len(results)} promotions.",
        "results": results,
        "contacts": [{"name": r["name"], "id": r["id"]} for r in results]
    }, args.json)

def cmd_demote(bridge: ContactMacOSBridge, args):
    """Removes a contact (or all contacts) from the Priority group."""
    target_group = GROUPS["priority"]

    contacts_to_demote = []
    if getattr(args, "all", False):
        # S2-D: demote --all — list all Priority contacts and demote every one
        res = bridge.list_group_contacts(target_group)
        if res["success"]:
            contacts_to_demote = res["matches"]
    elif args.selection:
        res = bridge.get_selection()
        if res["success"]:
            contacts_to_demote = res["matches"]
    elif args.name:
        res = bridge.find_contact(args.name)
        if res["success"]:
            if res.get("ambiguous"):
                output_result({"success": False, "message": f"Ambiguous name '{args.name}'. Matches: {res['matches']}"}, args.json)
                return
            contacts_to_demote = [res]

    if not contacts_to_demote:
        output_result({"success": False, "message": "No contacts found to demote."}, args.json)
        _not_found_exit(args)  # S2-F

    results = []
    for c in contacts_to_demote:
        rem_res = bridge.remove_from_group(c["id"], target_group)
        results.append({
            "name": c["name"],
            "id": c["id"],
            "status": "DEMOTED" if rem_res["success"] else f"FAILED: {rem_res.get('error')}"
        })
        
    output_result({
        "success": True,
        "message": f"Processed {len(results)} demotions.",
        "results": results,
        "contacts": [{"name": r["name"], "id": r["id"]} for r in results]
    }, args.json)

def _build_archive_ts_map() -> Dict[str, str]:
    """Walk logs/archive/applied/ and return {contact_id: latest_timestamp}.
    Used by cmd_queue --sort oldest and cmd_inspect. S4-A/S4-C."""
    archive_root = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        "logs", "archive", "applied"
    )
    ts_map: Dict[str, str] = {}
    if not os.path.isdir(archive_root):
        return ts_map
    for run_dir in sorted(os.listdir(archive_root)):
        run_path = os.path.join(archive_root, run_dir)
        if not os.path.isdir(run_path):
            continue
        for contact_dir in os.listdir(run_path):
            profile_path = os.path.join(run_path, contact_dir, "profile.json")
            if not os.path.isfile(profile_path):
                continue
            try:
                profile = json.load(open(profile_path))
                cid = profile.get("_contact_id", "")
                ts = profile.get("timestamp", "")
                if cid and ts and (cid not in ts_map or ts > ts_map[cid]):
                    ts_map[cid] = ts
            except Exception:
                continue
    return ts_map


def cmd_queue(bridge: ContactMacOSBridge, args):
    """Lists contacts in Force-Refresh queue, optionally sorted and truncated."""
    group_name = GROUPS["refresh"]
    res = bridge.list_group_contacts(group_name)
    if not res["success"]:
        output_result({"success": False, "error": res.get("error", "Unknown error")}, args.json)
        _not_found_exit(args)  # S2-F

    contacts = res["matches"]
    sort_key = getattr(args, "sort", "alpha")

    if sort_key == "oldest":
        # S4-C: contacts with no archive entry (never synced) ranked first; then ascending by ts
        ts_map = _build_archive_ts_map()
        contacts = sorted(contacts, key=lambda c: ts_map.get(c["id"], ""))
    else:
        contacts = sorted(contacts, key=lambda c: c["name"].lower())

    # --top N truncation
    top_n = getattr(args, "top", None)
    if top_n and top_n > 0:
        contacts = contacts[:top_n]

    if not contacts:
        output_result({"success": False, "message": "Force-Refresh queue is empty."}, args.json)
        _not_found_exit(args)  # S2-F

    output_result({
        "success": True,
        "group": group_name,
        "total": len(res["matches"]),
        "shown": len(contacts),
        "sort": sort_key,
        "contacts": contacts
    }, args.json)


def cmd_inspect(bridge: ContactMacOSBridge, args):
    """Shows a contact's archive history from logs/archive/applied/. S4-A.
    v1.4.1: In JSON mode (--json), always exit 0 so AppleScript do shell script doesn't raise.
    Non-JSON shell callers still receive exit code 2 for 'not found' (S2-F convention).
    """
    name_query = args.name.lower()
    archive_root = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        "logs", "archive", "applied"
    )
    if not os.path.isdir(archive_root):
        output_result({"success": False, "error": f"Archive not found: {archive_root}"}, args.json)
        return

    sessions = []
    for run_dir in sorted(os.listdir(archive_root)):
        run_path = os.path.join(archive_root, run_dir)
        if not os.path.isdir(run_path):
            continue
        for contact_dir in os.listdir(run_path):
            profile_path = os.path.join(run_path, contact_dir, "profile.json")
            if not os.path.isfile(profile_path):
                continue
            try:
                profile = json.load(open(profile_path))
            except Exception:
                continue
            if name_query in profile.get("full_name", "").lower():
                sessions.append({
                    "session": run_dir,
                    "full_name": profile.get("full_name", ""),
                    "timestamp": profile.get("timestamp", ""),
                    "current_role": profile.get("current_role", ""),
                    "company": profile.get("company", ""),
                    "photo_status": profile.get("_photo_status", ""),
                    "proposed_changes": profile.get("_proposed_changes", {}),
                })

    if not sessions:
        output_result({"success": False, "message": f"No archive entries for '{args.name}'."}, args.json)
        _not_found_exit(args)

    result = {
        "success": True,
        "query": args.name,
        "total_sessions": len(sessions),
        "sessions": sessions
    }
    if args.json:
        output_result(result, True)
    else:
        print(f"\nArchive history for '{args.name}' ({len(sessions)} session(s)):\n")
        for s in sessions:
            print(f"  [{s['session']}]  {s['full_name']}  @ {s['company']}  ({s['photo_status']})")


def cmd_profile(bridge: ContactMacOSBridge, args):
    """Reads vault entry for a contact and returns formatted LinkedIn profile data. S5-A.
    Accepts --contact-id UUID (exact vault dir match) or --name (substring search).
    Returns JSON with display_text (capped ~1000 chars) for use in AppleScript dialogs.
    """
    vault_root = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        "data", "vault"
    )
    if not os.path.isdir(vault_root):
        output_result({"success": False, "error": f"Vault not found: {vault_root}"}, args.json)
        _not_found_exit(args)

    profile = None
    contact_dir = None

    # ── Exact match by contact UUID (preferred — from ASOC scanAndSortGroup) ──
    contact_id_arg = getattr(args, "contact_id", None)
    name_arg = getattr(args, "name", None)

    if contact_id_arg:
        # AppleScript passes plain UUID (pyID strips :ABPerson); vault dirs use UUID:ABPerson.
        # Try both forms so either convention works.
        candidates = [contact_id_arg]
        if not contact_id_arg.endswith(":ABPerson"):
            candidates.append(contact_id_arg + ":ABPerson")
        for candidate in candidates:
            pp = os.path.join(vault_root, candidate, "profile.json")
            if os.path.isfile(pp):
                try:
                    profile = json.load(open(pp))
                    contact_dir = candidate
                except Exception as e:
                    output_result({"success": False, "error": f"Failed to read vault entry: {e}"}, args.json)
                    _not_found_exit(args)
                break
        if not profile:
            output_result({"success": False, "message": f"No vault entry for contact ID '{contact_id_arg}'."}, args.json)
            _not_found_exit(args)

    elif name_arg:
        # ── Name substring search ──────────────────────────────────────────────
        name_query = name_arg.strip().lower()
        matches = []
        for d in sorted(os.listdir(vault_root)):
            pp = os.path.join(vault_root, d, "profile.json")
            if not os.path.isfile(pp):
                continue
            try:
                p = json.load(open(pp))
                if name_query in p.get("full_name", "").lower():
                    matches.append((d, p))
            except Exception:
                continue
        if not matches:
            output_result({"success": False, "message": f"No vault entry found for '{name_arg}'."}, args.json)
            _not_found_exit(args)
        if len(matches) > 1:
            output_result({
                "success": False,
                "message": (f"Ambiguous: {len(matches)} vault matches for '{name_arg}': "
                            f"{[m[1].get('full_name', m[0]) for m in matches[:6]]}")
            }, args.json)
            _not_found_exit(args)
        contact_dir, profile = matches[0]

    else:
        output_result({"success": False, "error": "Specify --contact-id or --name."}, args.json)
        sys.exit(1)

    # ── Build human-readable display text (capped for dialog display) ──────────
    lines = []
    role    = (profile.get("current_role") or "").strip()
    company = (profile.get("company") or "").strip()
    if role or company:
        lines.append("CURRENT: " + role + (" @ " + company if company else ""))

    location = (profile.get("location") or profile.get("city") or "").strip()
    if location and "\n" not in location and len(location) < 80:
        lines.append("LOCATION: " + location)

    experience = profile.get("experience") or []
    education  = profile.get("education")  or []
    skills     = profile.get("skills")     or []

    lines.append("")
    if experience:
        lines.append(f"EXPERIENCE ({len(experience)}):")
        for exp in experience[:4]:
            title = (exp.get("title") or "").strip()
            co    = (exp.get("company") or "").strip()
            sd    = exp.get("start_date") or ""
            ed    = exp.get("end_date") or "now"
            line  = "  • " + title
            if co:    line += " @ " + co
            if sd:    line += "  [" + sd + "–" + ed + "]"
            lines.append(line)
        if len(experience) > 4:
            lines.append(f"  (+ {len(experience) - 4} more)")
    else:
        lines.append("EXPERIENCE: (none in vault)")

    lines.append("")
    if education:
        lines.append(f"EDUCATION ({len(education)}):")
        for edu in education[:3]:
            school = (edu.get("school") or "").strip()
            degree = (edu.get("degree") or edu.get("field_of_study") or "").strip()
            line   = "  • " + school
            if degree: line += " — " + degree
            lines.append(line)
        if len(education) > 3:
            lines.append(f"  (+ {len(education) - 3} more)")
    else:
        lines.append("EDUCATION: (none in vault)")

    if skills:
        lines.append("")
        lines.append("SKILLS: " + ", ".join(skills[:8]) + ("…" if len(skills) > 8 else ""))

    enriched_at = profile.get("_enriched_at", "")
    if enriched_at:
        lines.append("\nVault updated: " + enriched_at[:10])

    display_text = "\n".join(lines)
    if len(display_text) > 1100:
        display_text = display_text[:1097] + "…"

    output_result({
        "success": True,
        "contact_id": contact_dir,
        "full_name": profile.get("full_name", ""),
        "display_text": display_text,
        "exp_count": len(experience),
        "edu_count": len(education),
        "skills_count": len(skills),
        "enriched_at": enriched_at,
    }, args.json)


def cmd_validate(bridge: ContactMacOSBridge, args):
    """Marks a contact as reviewed: removes from 'LinkedIn to Review' group. S5-B.
    Requires --contact-id UUID (from ASOC scan) and --full mode.
    Does NOT modify the contact note — safe, group-only operation.
    """
    contact_id   = args.contact_id
    display_name = (getattr(args, "name", None) or contact_id).strip()
    review_group = GROUPS["review"]   # "script-LSAM-LinkedIn to Review"

    if bridge.mode != "FULL":
        output_result({
            "success": False,
            "message": "validate requires --full mode (group write permission needed)."
        }, args.json)
        sys.exit(1)

    rem_res = bridge.remove_from_group(contact_id, review_group)
    if rem_res.get("success"):
        msg = f"✅ Validated: {display_name} — removed from 'LinkedIn to Review'."
    else:
        err = rem_res.get("error", "")
        # Not being in the group is still a valid outcome (may have been reviewed via engine)
        if any(k in err.lower() for k in ("not in group", "not found", "not a member")):
            msg = f"✅ Validated: {display_name} (was not in review queue — already clean)."
            rem_res["success"] = True
        else:
            msg = f"⚠️ Partial: {display_name} — {err}"

    output_result({
        "success": rem_res.get("success", False),
        "message": msg,
        "contact_id": contact_id,
    }, args.json)


def cmd_focus(bridge: ContactMacOSBridge, args):
    """Selects and focuses a contact in Contacts.app."""
    res = bridge.find_contact(args.name)
    if not res["success"]:
        output_result({"success": False, "message": f"Contact '{args.name}' not found."}, args.json)
        _not_found_exit(args)  # S2-F
        return
        
    if res.get("ambiguous"):
        output_result({"success": False, "message": f"Ambiguous name '{args.name}'. Matches: {res['matches']}"}, args.json)
        return
        
    sel_res = bridge.select_contact(res["id"])
    output_result({
        "success": sel_res["success"],
        "message": f"Focused {res['name']}." if sel_res["success"] else f"Failed to focus: {sel_res.get('error')}"
    }, args.json)

def _resolve_vault_contact(identifier: str) -> dict | None:
    """Find a vault contact by UUID or partial name. Returns {vault_dir, profile, scavenger_meta} or None."""
    vault_root = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), "data", "vault")
    if not os.path.isdir(vault_root):
        return None

    # Direct UUID match
    for suffix in [identifier, f"{identifier}:ABPerson"]:
        candidate = os.path.join(vault_root, suffix)
        if os.path.isdir(candidate):
            mp = os.path.join(candidate, "master_profile.json")
            if os.path.exists(mp):
                with open(mp) as f:
                    profile = json.load(f)
                meta_path = os.path.join(candidate, "scavenger_meta.json")
                meta = {}
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        meta = json.load(f)
                return {"vault_dir": candidate, "profile": profile, "scavenger_meta": meta}

    # Partial name search
    for entry in os.scandir(vault_root):
        if not entry.is_dir():
            continue
        mp = os.path.join(entry.path, "master_profile.json")
        if not os.path.exists(mp):
            continue
        try:
            with open(mp) as f:
                profile = json.load(f)
            if identifier.lower() in profile.get("full_name", "").lower():
                meta_path = os.path.join(entry.path, "scavenger_meta.json")
                meta = {}
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        meta = json.load(f)
                return {"vault_dir": entry.path, "profile": profile, "scavenger_meta": meta}
        except Exception:
            continue
    return None


def cmd_preview(bridge: ContactMacOSBridge, args):
    """v1.5.0 Sprint 2: Preview what would change if vault data were applied to a contact.
    Dry-run diff — read-only, no writes."""
    identifier = args.contact_id or args.name
    if not identifier:
        output_result({"success": False, "error": "Provide --contact-id or --name"}, args.json)
        return

    vault = _resolve_vault_contact(identifier)
    if not vault:
        output_result({"success": False, "error": f"No vault entry for '{identifier}'"}, args.json)
        _not_found_exit(args)
        return

    profile = vault["profile"]
    contact_id = vault["scavenger_meta"].get("contact_id", os.path.basename(vault["vault_dir"]))

    # Fetch current state from macOS Contacts
    current = bridge.get_contact_details(contact_id)
    if not current.get("success"):
        output_result({"success": False, "error": f"Contact {contact_id} not found in Contacts.app"}, args.json)
        return

    # Build diff
    diffs = []
    vault_name = profile.get("full_name", "")
    contact_name = current.get("name", "")

    # Organization
    vault_org = profile.get("company", "") or ""
    current_org = current.get("organization", "") or ""
    if vault_org.lower().strip() != current_org.lower().strip():
        diffs.append({"field": "Organization", "current": current_org, "vault": vault_org, "action": "WOULD UPDATE"})
    else:
        diffs.append({"field": "Organization", "current": current_org, "vault": vault_org, "action": "no change"})

    # Job Title
    vault_title = profile.get("current_role", "") or ""
    current_title = current.get("job_title", "") or ""
    if vault_title[:40].lower().strip() != current_title[:40].lower().strip():
        diffs.append({"field": "Job Title", "current": current_title[:60], "vault": vault_title[:60], "action": "WOULD UPDATE"})
    else:
        diffs.append({"field": "Job Title", "current": current_title[:60], "vault": vault_title[:60], "action": "no change"})

    # Stats
    mutual = profile.get("common_connections_count", 0) or 0
    followers = profile.get("followers_count", 0) or 0
    connections = profile.get("connections_count", 0) or 0

    # Photo
    photo_available = os.path.exists(os.path.join(vault["vault_dir"], "linkedin.heic"))
    diffs.append({"field": "Photo", "current": "present" if current.get("has_image") else "none",
                  "vault": "HI_RES" if photo_available else "none",
                  "action": "WOULD UPDATE" if photo_available else "no change"})

    # Scavenge date
    scavenged_at = vault["scavenger_meta"].get("scavenged_at", "unknown")

    # Vault history (if any)
    try:
        from src.utils.vault_history import load_history, diff as vault_diff, format_diff_human
        history = load_history(vault["vault_dir"])
        history_count = len(history)
        history_diff = None
        if len(history) >= 2:
            history_diff = format_diff_human(vault_diff(history[0], history[1]))
    except Exception:
        history_count = 0
        history_diff = None

    # Build structured display text for AppleScript dialog
    lines = []
    lines.append(f"Vault: {vault_name}  (scavenged {scavenged_at[:10]})")
    lines.append(f"Stats: {mutual} mutual · {followers} followers · {connections} connections")
    lines.append("")
    has_changes = False
    for d in diffs:
        if d["action"] == "no change":
            cur = d["current"] or "(empty)"
            lines.append(f"  {d['field']}: {cur}")
        else:
            has_changes = True
            cur = d["current"] or "(empty)"
            vlt = d["vault"] or "(empty)"
            lines.append(f"→ {d['field']}: {cur}  ⟶  {vlt}")
    if not has_changes:
        lines.append("")
        lines.append("No field changes detected.")
    display_text = "\n".join(lines)

    result = {
        "success": True,
        "contact_name": contact_name or vault_name,
        "contact_id": contact_id,
        "vault_name": vault_name,
        "scavenged_at": scavenged_at,
        "diffs": diffs,
        "display_text": display_text,
        "has_changes": has_changes,
        "stats": {"mutual": mutual, "followers": followers, "connections": connections},
        "history_snapshots": history_count,
    }
    if history_diff:
        result["history_diff"] = history_diff

    if args.json:
        output_result(result, True)
    else:
        print(f"\n=== Preview: {result['contact_name']} ===")
        print(f"    Vault: {vault_name} (scavenged {scavenged_at})")
        print(f"    Stats: {mutual} mutual, {followers} followers, {connections} connections")
        print()
        for d in diffs:
            marker = "  " if d["action"] == "no change" else "→ "
            if d["action"] == "no change":
                print(f"  {d['field']}: {d['current']} (no change)")
            else:
                print(f"  {marker}{d['field']}: {d['current']} → {d['vault']} [{d['action']}]")
        if history_count > 0:
            print(f"\n  Vault history: {history_count} snapshot(s)")
        if history_diff:
            print(f"\n  Last change:\n{history_diff}")


def cmd_edit(bridge: ContactMacOSBridge, args):
    """v1.5.0 Sprint 2: Set field overrides in vault master_profile.json.
    Overrides win over scraped data during sync. Override presence prevents auto-refresh of those fields."""
    identifier = args.contact_id or args.name
    if not identifier:
        output_result({"success": False, "error": "Provide --contact-id or --name"}, args.json)
        return

    vault = _resolve_vault_contact(identifier)
    if not vault:
        output_result({"success": False, "error": f"No vault entry for '{identifier}'"}, args.json)
        _not_found_exit(args)
        return

    profile = vault["profile"]
    mp_path = os.path.join(vault["vault_dir"], "master_profile.json")

    # Parse field=value pairs from args.overrides
    overrides = profile.get("overrides", {})
    changes = []
    for pair in args.overrides:
        if "=" not in pair:
            output_result({"success": False, "error": f"Invalid override format: '{pair}'. Use field=value"}, args.json)
            return
        field, value = pair.split("=", 1)
        field = field.strip()
        value = value.strip()
        overrides[field] = value
        changes.append({"field": field, "value": value})

    if not changes:
        output_result({"success": False, "error": "No overrides provided. Use: edit --name X field1=value1 field2=value2"}, args.json)
        return

    # MORENO_GUARD: backup before modification
    backup_dir = os.path.join(vault["vault_dir"], "history")
    os.makedirs(backup_dir, exist_ok=True)
    from datetime import datetime as _dt
    backup_path = os.path.join(backup_dir, f"pre_edit_{_dt.now().strftime('%Y%m%dT%H%M%S')}.json")
    with open(backup_path, "w") as f:
        json.dump(profile, f, indent=2, default=str)

    # Apply overrides
    profile["overrides"] = overrides
    with open(mp_path, "w") as f:
        json.dump(profile, f, indent=2, default=str)

    # Also update profile.json for backwards compat
    pj_path = os.path.join(vault["vault_dir"], "profile.json")
    if os.path.exists(pj_path):
        with open(pj_path, "w") as f:
            json.dump(profile, f, indent=2, default=str)

    result = {
        "success": True,
        "contact_name": profile.get("full_name", identifier),
        "overrides_applied": changes,
        "backup": backup_path,
        "message": f"Applied {len(changes)} override(s) to {profile.get('full_name', identifier)}. Backup: {backup_path}"
    }
    output_result(result, args.json)


def cmd_log_session(bridge: ContactMacOSBridge, args):
    """v1.5.0: Log a manual sync session to MBP Dev Monitor calendar.
    Called by Control Center AppleScript after manual sync / preview-apply completes."""
    try:
        import sys as _sys
        _workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        _sys.path.insert(0, _workspace_root)
        from _skills.calendar_bridge.scripts.bridge import create_event, complete_event
    except Exception as e:
        output_result({"success": False, "error": f"Calendar bridge not available: {e}"}, args.json)
        return

    names = args.names.split(",") if args.names else []
    count = len(names)
    mode = args.mode or "SIMULATION"

    # Create + immediately complete (manual syncs are already done when this is called)
    uid = create_event("LSAM", "Manual Sync", eta_minutes=1,
                       notes=f"Mode: {mode}\nContacts: {count}")
    if uid:
        summary = f"Contacts: {', '.join(names[:10])}"
        if count > 10:
            summary += f" (+{count - 10} more)"
        from datetime import datetime as _dt
        complete_event(uid, "LSAM", "Manual Sync",
                       duration_seconds=int(args.duration) if args.duration else 60,
                       items_total=count,
                       summary_notes=summary)
        output_result({"success": True, "message": f"Calendar event created for {count} contact(s)"}, args.json)
    else:
        output_result({"success": False, "error": "Failed to create calendar event"}, args.json)


def main():
    # Common arguments for all subparsers
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parent_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parent_parser.add_argument("--full", action="store_true", help="Run in FULL mode (write permission)")

    parser = argparse.ArgumentParser(description="LSAM Control Center CLI", parents=[parent_parser])
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Status
    subparsers.add_parser("status", help="Show group counts and health", parents=[parent_parser])
    
    # List
    list_parser = subparsers.add_parser("list", help="List contacts in a group", parents=[parent_parser])
    list_parser.add_argument("group", choices=list(GROUPS.keys()) + ["all"], help="Standard group key or full name")
    list_parser.add_argument("--sort", choices=["alpha", "status"], default="alpha", help="Sort order: alpha (default) or status (S3-A)")
    
    # Promote
    prom_parser = subparsers.add_parser("promote", help="Add contact to Priority group", parents=[parent_parser])
    prom_group = prom_parser.add_mutually_exclusive_group(required=True)
    prom_group.add_argument("--selection", action="store_true", help="Promote current selection in Contacts.app")
    prom_group.add_argument("--name", help="Name of contact to promote")
    prom_group.add_argument("--csv", metavar="FILE", help="CSV file with full_name column to bulk-promote (S4-B)")
    
    # Demote
    dem_parser = subparsers.add_parser("demote", help="Remove contact from Priority group", parents=[parent_parser])
    dem_group = dem_parser.add_mutually_exclusive_group(required=True)
    dem_group.add_argument("--selection", action="store_true", help="Demote current selection in Contacts.app")
    dem_group.add_argument("--name", help="Name of contact to demote")
    dem_group.add_argument("--all", action="store_true", help="Demote ALL contacts from Priority group (S2-D)")

    # Focus
    foc_parser = subparsers.add_parser("focus", help="Select contact in Contacts.app", parents=[parent_parser])
    foc_parser.add_argument("name", help="Name of contact to focus")

    # Queue (S2-E + S4-C)
    queue_parser = subparsers.add_parser("queue", help="List Force-Refresh queue contacts", parents=[parent_parser])
    queue_parser.add_argument("--sort", choices=["alpha", "oldest"], default="alpha",
                              help="Sort: alpha (default) or oldest (by last archive timestamp, S4-C)")
    queue_parser.add_argument("--top", type=int, help="Show only top N contacts")

    # Inspect (S4-A)
    insp_parser = subparsers.add_parser("inspect", help="Show contact archive history (S4-A)", parents=[parent_parser])
    insp_parser.add_argument("name", help="Contact name to search in archive (partial match)")

    # Profile (S5-A) — reads vault entry, returns formatted data for Control Center dialog
    prof_parser = subparsers.add_parser("profile", help="Show LinkedIn vault profile for a contact (S5-A)", parents=[parent_parser])
    prof_group = prof_parser.add_mutually_exclusive_group(required=True)
    prof_group.add_argument("--contact-id", metavar="UUID", dest="contact_id",
                            help="Contacts.app UUID (exact vault dir match — preferred)")
    prof_group.add_argument("--name", help="Contact name substring search in vault (fallback)")

    # Validate (S5-B) — removes contact from 'LinkedIn to Review' group (requires --full)
    val_parser = subparsers.add_parser("validate", help="Mark contact as reviewed (remove from LinkedIn to Review, S5-B)", parents=[parent_parser])
    val_parser.add_argument("--contact-id", metavar="UUID", dest="contact_id", required=True,
                            help="Contacts.app UUID (from ASOC scanAndSortGroup)")
    val_parser.add_argument("--name", default="", help="Display name for logging (optional)")

    # Preview (Sprint 2) — dry-run diff: vault vs current contact state
    prev_parser = subparsers.add_parser("preview", help="Preview what vault sync would change (read-only, Sprint 2)", parents=[parent_parser])
    prev_id_group = prev_parser.add_mutually_exclusive_group(required=True)
    prev_id_group.add_argument("--contact-id", metavar="UUID", dest="contact_id", help="Contacts.app UUID")
    prev_id_group.add_argument("--name", help="Contact name (partial match against vault)")

    # Edit (Sprint 2) — set field overrides in vault
    edit_parser = subparsers.add_parser("edit", help="Set field overrides in vault profile (Sprint 2)", parents=[parent_parser])
    edit_id_group = edit_parser.add_mutually_exclusive_group(required=True)
    edit_id_group.add_argument("--contact-id", metavar="UUID", dest="contact_id", help="Contacts.app UUID")
    edit_id_group.add_argument("--name", help="Contact name (partial match)")
    edit_parser.add_argument("overrides", nargs="+", metavar="field=value",
                             help="Field overrides (e.g., first_name=Benoit last_name=Deleury)")

    # Log-session — create MBP Dev Monitor calendar event for manual sync
    log_parser = subparsers.add_parser("log-session", help="Log a manual sync to MBP Dev Monitor calendar", parents=[parent_parser])
    log_parser.add_argument("--names", default="", help="Comma-separated contact names")
    log_parser.add_argument("--mode", default="SIMULATION", help="Sync mode (SIMULATION or FULL)")
    log_parser.add_argument("--duration", default="60", help="Duration in seconds")

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    setup_logging(args.debug, json_mode=getattr(args, 'json', False))
    
    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    
    if args.command == "status":
        cmd_status(bridge, args)
    elif args.command == "list":
        cmd_list(bridge, args)
    elif args.command == "promote":
        cmd_promote(bridge, args)
    elif args.command == "demote":
        cmd_demote(bridge, args)
    elif args.command == "focus":
        cmd_focus(bridge, args)
    elif args.command == "queue":
        cmd_queue(bridge, args)
    elif args.command == "inspect":
        cmd_inspect(bridge, args)
    elif args.command == "profile":
        cmd_profile(bridge, args)
    elif args.command == "validate":
        cmd_validate(bridge, args)
    elif args.command == "preview":
        cmd_preview(bridge, args)
    elif args.command == "edit":
        cmd_edit(bridge, args)
    elif args.command == "log-session":
        cmd_log_session(bridge, args)

if __name__ == "__main__":
    main()
