# LSAM Project Handbook (v2.0)
## Tier 0 Continuity: Rules of Engagement & Operations
*Last rebased: 2026-03-30*

> [!NOTE]
> Tactical daily operations and "brain" logs are hosted in the [BRAIN/](BRAIN/) directory.
> Detailed Handover instructions: [Handover Guide](archive/v4_legacy/HANDOVER_GUIDE.md).
> v5.0 design: [PLAN_2026-03-29_LSAM_V5_REDESIGN.md](PLAN_2026-03-29_LSAM_V5_REDESIGN.md) *(all sprints complete)*.


### ⚖️ Core Guardrails (The Moreno Rules)
1.  **DELETION IS FORBIDDEN**: Never call `delete person`. If a contact is wrong, move it to `LSAM-Damaged` or `LSAM-Review`.
2.  **BACKUP IS MANDATORY**: Every write operation must save a pre-write JSON to the session log (MORENO_GUARD v4.9.2).
3.  **SURGICAL EDITS**: Only update fields that have changed. Never overwrite a curated `FirstName` or `LastName` unless it is a placeholder.
4.  **CCC ARTICULATION**: LSAM writes first, CCC cleans second. LSAM inserts `<!--LSAM:pre_mod:-->` stamp before note writes. CCC preserves `<Linkedin-AI-sync>` and `<Linkedin-Career>` blocks verbatim.

### 🕹️ Operations Guide
- **Daily automated sync**: `com.lsam.daily-sync` LaunchAgent at 07:30, runs `start_lsam.sh --pro`.
- **Starting a manual run**: `./start_lsam.sh --pro` (auto-fixes venv/deps, uses `LSAMC_ENGINE=PRO`).
- **Managing Selection** (Control Center v3.0):
    1. Select contact(s) in macOS Contacts.app.
    2. Run `LSAM Control Center.scpt` (or `osascript "LSAM Control Center UTF8.applescript"`).
    3. Choose:
       - **📋 Preview Selected**: Dry-run diff (vault vs current contact state).
       - **🔄 Sync Selected**: Simulation sync (default) — writes only with `--live`.
       - **📝 Review Queue**: Browse `LSAM-Review`, triage one-by-one.
       - **⚙️ More...**: Promote, Demote, Edit Override, Inspect, Status.
- **CLI**: `python3 scripts/lsam_control_center.py <command>` — preview, edit, inspect, promote, demote, queue, list, log-session.

### 📁 Supervised Queues (v5.0 Group Taxonomy)
- **LSAM-Queue**: Pending automated processing (birthday, bounced, promoted, unprocessed). Drained by supervisor.
- **LSAM-Review**: Needs manual triage/disambiguation. Skipped in auto mode; surface in Control Center Review Queue.
- **LSAM-Golden**: Successfully synced, vault current, no issues. Reference pool.
- **LSAM-Damaged**: Confirmed data corruption, parked until manual fix.
- **LSAM-Exempted**: User explicitly excluded from all LSAM processing.
- **LSAM-Birthday**: Contacts queued by birthday trigger (auto-populated, auto-drained).
- *(Legacy `script-LSAM-*` groups still exist as safety net — pending cleanup.)*

### 🔍 Matching Policy (High-Level)
- **1st/2nd Degree**: Automatic sync if unambiguous.
- **Ambiguity**: Prepend `Ambiguity_Warning` to note. Do NOT update fields.
- **3rd Degree**: Prepend `Warning: ⚠️ LSAM CANDIDATE`. NEVER update social profiles automatically.

### 🆘 Troubleshooting
- **403 Forbidden**: Photo extraction failed due to LinkedIn signature. System downshifts to Tier 4 (thumbnail).
- **Stall kill**: If process ends at 1200s, check if Gemini Vision is hitting a Captcha.
- **CAPTCHA kill**: Remove `logs/CAPTCHA_KILL` sentinel before restarting after a CAPTCHA event.

### 🧠 AppleScript Gotchas (distilled from MORENO post-mortem)
1. **Birthday field**: use `birth date of p` ✅ — `birthday of p` raises `-1700` type error.
2. **AEHandler `-10000`**: social profile deletion can fail silently; use `bridge._run_applescript()`, never retry in a loop.
3. **Photo iCloud lag**: verify with `image of p is not missing value` — bridge `.photo` bytes return `None` during iCloud sync delay even after a successful injection.
4. **VCF `x-user`**: macOS Contacts does NOT reliably parse LinkedIn `user name` from VCF import. Always follow up with an AppleScript field patch.
5. **VCF → group loss**: contacts re-created via VCF import lose all group memberships — re-add manually.
6. **ASOC + iCloud writes**: `CNSaveRequest` `addMember:toGroup:` fails with CoreData 134092 on iCloud-backed contacts. Use hybrid ASOC-read + AppleScript-write with batch save.

> Full incident detail: [INCIDENT_MORENO_20260309.md](archive/v4_legacy/INCIDENT_MORENO_20260309.md)
> Project Timeline: [BRAIN/JOURNAL.md](BRAIN/JOURNAL.md)

