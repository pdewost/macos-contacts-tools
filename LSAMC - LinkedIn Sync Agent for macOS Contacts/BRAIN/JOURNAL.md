# LSAM Project Journal (v1.1)
## Tier 1 Continuity: Audit Trail & Institutional Memory

> [!NOTE]
> For context on project origins (Phases 1-4), see [Project History](archive/v4_legacy/LSAMC%20-%20LinkedIn%20Sync%20Agent%20MacOS%20Contacts%20-%20Project%20History.md) and [Master Plan](archive/v4_legacy/LSAMC%20-%20LinkedIn%20Sync%20Agent%20MacOS%20Contacts%20-%20Master%20Plan.md).

> [!IMPORTANT]
> This is a living document. Every significant engineering decision, incident, or milestone must be recorded here chronologically.

---
### 2026-03-30 | Strategic Rebase — Post-v5.0 Documentation Alignment

#### Context
All 6 v5.0 sprints completed on 2026-03-29. Core reference documents (STATUS.md, COMPASS.md, HANDBOOK.md) had significant drift from reality — still referenced old group names (`script-LSAM-*`), old Control Center version (v2.2.0/v2.3.2), old architecture descriptions.

#### Actions
1. **STATUS.md** v1.1 → v2.0: Updated architecture section with current engine versions (pro_sync_agent v2.5.4, surgical v8.7, bridge v5.0, profile v5.6, CC v3.0.0, CLI v1.5.0), new group taxonomy, vault history, LaunchAgent, MBP Dev Monitor.
2. **COMPASS.md** v1.1 → v2.0: Added all v5.0 sprint completions (items 5-11), updated CC version, added remaining pending items (CC live test, legacy group cleanup, identity restoration stall).
3. **HANDBOOK.md** v1.1 → v2.0: Updated group names to `LSAM-*` taxonomy, rewrote operations guide for CC v3.0 (preview/edit/review flow), added CCC articulation guardrail, added ASOC+iCloud gotcha.
4. **ANTIGRAVITY_REBASE_2026-03-30.md**: New cold-start context document capturing v5.0 completion state, pending tasks, known issues, reading list.

#### Staleness fixed
- `PROJECT_BRIEF.md`: v4.9.2 → v5.0.
- `PLAN_2026-03-29_LSAM_V5_REDESIGN.md`: "DESIGN PHASE" → "COMPLETE" (retained as design record).
- `BRAIN/task.md`: Rewrote — removed stale v2.3.x CC tasks, added post-v5.0 active/backlog items.

#### Archived (25 files → `archive/v5_rebase_2026-03-30/`)
Root directory: 29 markdown + 7 JSON → 11 markdown + 0 JSON. Moved: closed rebases, historical audits (4×), superseded CC docs (3×), identity/rescue plans, stale dashboards (SYNC_PROGRESS.md), one-off reports + JSON reports (7×).

---
### 2026-03-30 | CC v3.1.x — Birthday Group rewrite (in progress, interrupted)

#### Context
LSAM-Birthday group populated with only 4/10 expected contacts for tomorrow.
Root cause: `handleBirthdayGroup()` v3.1.0 used CNContactStore scan which misses contacts
from non-primary linked accounts, Exchange/CardDAV birthdays in the Dates field,
and any contact where the birthday isn't on the "winning" linked account's CNContactBirthdayKey.

Calendar "Birthdays" (= "Anniversaires" in fr-FR) is the OS-level ground truth — same data
as macOS birthday notifications. Events carry `addressbook://UUID` URL → zero-ambiguity
contact lookup, no name matching required.

#### Work done this session
1. **CC v3.1.0** (compiled, .scpt produced): first Birthday handler using CNContactStore scan.
   Shipped but functionally incomplete (~40% miss rate). File: `LSAM Control Center UTF8.applescript`.
2. **CC v3.1.1** (in progress, NOT compiled): rewrote `handleBirthdayGroup()` to use
   Calendar "Birthdays" as scan source. Version bumped throughout file (`_pVersion`, header, changelog).
   New Phase 10: improperly-filled birthday report (contact in Calendar but no `birth date` in Contacts.app).

#### Current blocker — AppleScript parser contamination
File fails `osacompile` with: `line 1559: Expected class name but found identifier. (-2741)`
Line 1559 = `set evtDate to item i of rawEvtDates` (date filter loop after Calendar tell block).

Bisection findings:
- Simple stub (just date arithmetic + filter loop): compiles ✓
- Phases 1–4 (Calendar tell + event fetch + URL parsing): compiles ✓
- Full handler (Phases 1–10): fails at filter loop ✗
- Trigger is somewhere in Phases 5–10 — bisection was in progress at interruption.
- Known AppleScript keyword conflicts resolved:
  - `start date of evt` → `tell evt; start date; end tell` (multi-dict Calendar+Contacts ambiguity)
  - `events of bdCal from X to Y` — invalid syntax; use `every event of bdCal` + client-side filter
  - `fetch events from X to Y` — command does not exist in Calendar AS dictionary

#### State of file at interruption
`LSAM Control Center UTF8.applescript` — v3.1.1, does NOT compile.
`LSAM Control Center.scpt` — last compiled binary is v3.1.0 (CNContactStore-based).
The `.applescript` source has all v3.1.1 changes but is blocked by the parse error above.

#### Next steps (post-rebase)
1. Continue bisect — add Phases 5-10 one by one to find exact trigger in handleBirthdayGroup().
2. Fix trigger (likely another Calendar/Contacts multi-dict keyword conflict in Phases 5–10).
3. `osacompile` clean → produce .scpt → run dry-run → document.
4. Update task.md + JOURNAL when complete.

#### Key AppleScript lesson for this file
When `tell application "Calendar"` and `tell application "Contacts"` BOTH appear in the same
handler, the parser loads both dictionaries simultaneously. Two-word properties from either
dictionary can conflict. Workaround: use `tell evt ... end tell` nested form to force unambiguous
resolution. Same may be needed for any Calendar property that clashes with a Contacts property.

---
### 2026-03-29 | Manual sync → full component activation (calendar + menu app)

#### Problem
Manual syncs (from Control Center "Sync Selected" or "Preview → Apply") bypassed the supervisor entirely — called `pro_sync_agent.py` directly. Consequences: no MBP Dev Monitor calendar event, menu app didn't detect the running sync, no birthday trigger.

#### Fix
1. **`log-session` CLI command** added to `lsam_control_center.py` v1.5.0 — creates + immediately completes a calendar event via `_skills/calendar_bridge`. Called by AppleScript after both `handleManualSync` and `handlePreviewSelected`.
2. **Menu app process detection** — `_lsam_process_alive()` now checks for both `supervisor.py` AND `pro_sync_agent.py` processes. Manual syncs show as "running" in the menubar.
3. **Menu app start** — `_toggle_lsam()` now uses `start_lsam.sh --pro` (handles venv, deps, PRO mode) instead of calling `supervisor.py` directly. Consistent with LaunchAgent.
4. **Menu app stop** — kills both supervisor and agent processes.
5. **Birthday trigger wired into supervisor** — at startup: checks cache age (>7 days → rebuild), then runs daily T+2 check. `LSAM-Birthday` is first in GroupQueue.
6. **Daily LaunchAgent** — `com.lsam.daily-sync` triggers `start_lsam.sh --pro` every day at 07:30 including weekends.

---
### 2026-03-29 | Group migration executed — hybrid ASOC/AppleScript approach

#### Problem
Pure ASOC `CNSaveRequest` `addMember:toGroup:` fails with CoreData error 134092 on iCloud-backed contacts (container mismatch between CNContactStore and Contacts.app scripting layer). Pure AppleScript `add p to g; save` per contact takes ~5-10s each (3+ hours for 2000 contacts).

#### Solution: Hybrid approach (`migrate_groups_hybrid.applescript`)
- **ASOC for reads**: `CNContactStore` `predicateForContactsInGroupWithIdentifier:` fetches all contact IDs from a group in ~200ms (batch)
- **AppleScript for writes**: `tell application "Contacts"` loops `add p to g` for all contacts, then **one `save`** at the end (not save-per-contact)
- Result: **2,279 contact-group additions in 18 minutes** (vs 3+ hours estimated with old approach, 4-6 hours with pure AppleScript save-per-contact)

#### Also attempted (failed)
- Pure ASOC migration (`migrate_groups_asoc.applescript`): CoreData 134092 on every `executeSaveRequest`. Created 12 duplicate empty groups (cleaned up). Root cause: iCloud container mismatch — groups created by Contacts.app scripting layer are invisible to CNContactStore for writes.

#### Migration results
| Source → Target | Contacts |
|----------------|----------|
| script-LSAM-Priority → LSAM-Queue | 302/302 |
| script-LSAM-Force-Refresh → LSAM-Queue | 249/249 |
| script-LSAM-Golden Record → LSAM-Golden | 221/221 |
| script-LSAM-Tier3 → LSAM-Review | 140/141 |
| script-LSAM-LinkedIn to Review → LSAM-Review | 138/138 |
| script-LSAM-Search-Failed → LSAM-Review | 5/5 |
| script-LSAM-Broken Names → LSAM-Review | 1/1 |
| script-LSAM-Exempted → LSAM-Exempted | 4/5 |
| script-LSAM-DAMAGED → LSAM-Damaged | 847/847 |
| script-LSAM-7mars (3 groups) → LSAM-Golden | 372/372 |

Old `script-LSAM-*` groups kept as safety net (contacts still in both old and new groups).

#### Lesson learned
ASOC `CNContactStore` on macOS with iCloud Contacts: **reads are fast and reliable, writes fail on iCloud-synced groups**. The hybrid ASOC-read + AppleScript-write pattern with batch save is the optimal approach for this environment.

---
### 2026-03-29 | Fix: connection_degree missing from sync block

#### Problem
Eva Casado Poupard's sync block didn't show "2nd degree" despite being a 2nd-degree connection. Investigation showed `connection_degree` was `None` in the vault for most contacts.

#### Root cause
The JavaScript degree badge selector (v1.6.0, line 2062) looked for `.dist-value`, `span.artdeco-badge__text`, `span.tvm-text` — **stale CSS classes from pre-2024 LinkedIn**. In the 2024+ React UI, the degree indicator (`· 2nd`) renders as plain text inside `nameEl.parentElement` (the name+degree container div), not in a dedicated badge element. The badge-based selector returned empty for virtually all contacts.

#### Fix (v5.0)
Added Strategy 1 to degree extraction: parse `nameEl.parentElement.innerText` with regex `/\b(1st|2nd|3rd|1er|2e|3e|2ème|3ème)\b/i`. Falls back to the old badge selector for legacy layouts.

```javascript
// Strategy 1: nameEl parent container text (LinkedIn 2024+ React UI)
if (nameEl && nameEl.parentElement) {
    const parentText = (nameEl.parentElement.innerText || '');
    const degreeMatch = parentText.match(/\b(1st|2nd|3rd|...)\b/i);
    if (degreeMatch) degreeText = degreeMatch[1];
}
```

The `generate_sync_block()` in `profile.py` already had correct degree formatting (lines 436-463) — it just never received the data.

#### Also fixed
- `<!--LSAM:last_mod_before:-->` stamp now saves the contact's **actual modification date** from Contacts.app (not wall-clock time) before any LSAM note write. Previous `<!--LSAM:pre_mod:-->` only saved the current timestamp.

---
### 2026-03-29 (late) | LSAM Control Center v3.0 — AppleScript UX Redesign

#### Changes
- **Menu simplified**: 10 items → 7 items. Removed: Triage DAMAGED (useless), separate Promote/Demote/Status/Refresh. Added: Preview Selected, Edit Override (in More...).
- **New handlers**: `resolveSlugForContact()` (shared, deduplicated from 3 places), `launchSyncAgent()` (shared), `handlePreviewSelected()` (dry-run diff per contact), `handleEditOverride()` (field=value prompts), `lsamGetGroupCount()` (new name + legacy fallback).
- **Group names**: Header now shows LSAM-Queue/Review/Golden counts with fallback to legacy `script-LSAM-*` names.
- **MBP Dev Monitor fix**: `paia_control_center.py` `open_lsam_dashboard()` changed from dead `localhost:5010` to `osascript LSAM Control Center UTF8.applescript`.
- **Version**: 2.4.14 → 3.0.0

#### v3.0 Menu Structure
```
📋 1. Preview Selected       → new (calls preview CLI)
🔄 2. Sync Selected          → existing handleManualSync
📝 3. Review Queue (N)       → existing handleProfileReview (LSAM-Review)
🔍 4. Review Last Session    → existing handlePostSyncReview
⚙️  5. More...                → Promote, Demote, Edit Override, Inspect, Profile Review, Status
▶️/⏹ 6. Start/Stop           → unchanged contextual
🚪 7. Exit
```

---
### 2026-03-29 (evening) | LSAM v5.0 Sprints 1-6 Executed — All 6 sprints complete

#### Sprint 1: Vault Rebase ✅
- Created `src/utils/vault_history.py` (write_snapshot, prune, load_history, diff, format_diff_human)
- Created `scripts/vault_diff.py` (CLI: `--list`, `--all`, `--json`, partial name match)
- Wired into `pro_sync_agent.py` vault write path (SIMULATION mode)
- Retention prune tested: 3-snapshot limit enforced correctly
- Test: Gilbert Menduni snapshot → diff detected role/follower changes

#### Sprint 3: Group Simplification ✅
- Created `scripts/migrate_groups.py` (audit + migrate + verify modes)
- DAMAGED audit (847 contacts): **733 no_vault, 113 broken_vault, 1 valid**
- Most DAMAGED contacts were genuinely never vaulted → stay in LSAM-Damaged
- Updated `supervisor.py` GroupQueue: new `LSAM-` groups + legacy fallbacks
- Migration script ready; execution requires `--migrate` with user confirmation

#### Sprint 2: Manual Processing ✅
- Added `preview` command to `lsam_control_center.py` v1.5.0
  - Dry-run diff: vault vs current macOS Contacts state
  - Shows field-by-field comparison with WOULD UPDATE / no change labels
  - Integrates vault_history diff when snapshots available
- Added `edit` command with field overrides
  - `lsam_control_center.py edit --name X field=value` writes overrides to master_profile.json
  - MORENO_GUARD: pre-edit backup to history/ folder
  - Tested: "No data found" contact overridden with first_name=Benoit last_name=Deleury

#### Sprint 4: Automated Triggers ✅
- Created `scripts/birthday_trigger.py`
  - Hybrid cache: `data/birthday_cache.json` (from Contacts.app AppleScript scan)
  - T-2 detection with Feb 29 edge case
  - Vault freshness check (7-day threshold)
  - `--refresh-cache` / `--dry-run` modes
- Created `scripts/onboard_unprocessed.py`
  - 6-tier priority scoring (LinkedIn URL > company email > phone > birthday > recent mod > alpha)
  - Chunked AppleScript scan (200/chunk) for 14k contacts
  - Filters personal email domains (gmail, yahoo, etc.)
- Created `scripts/bounce_handler.py`
  - Manual mode: `--selection`, `--name`, `--email` → adds to LSAM-Queue

#### Sprint 5: CCC Articulation ✅
- Added `<!--LSAM:pre_mod:TIMESTAMP-->` stamp to `contact_macos.py` `update_note()`
- Modified CCC `processNoteContentV3()` in `contact-operations.applescript`:
  - Extracts `<Linkedin-AI-sync>` and `<Linkedin-Career>` blocks before cleaning
  - Replaces with placeholders, runs cleaning pipeline, re-inserts verbatim
  - Preserves `<!--LSAM:pre_mod:-->` stamps
  - Compiles cleanly (osacompile verified)

#### Sprint 6: Calendar + UX ✅
- Added `_collect_session_summary()` to `supervisor.py`
  - Parses today's session logs for `update_contact SUCCESS` / `VAULT WRITTEN` / `FAILED`
  - Collects per-contact outcomes: synced names, failed names, queue remaining
  - Passes as `summary_notes` to `_cal_complete()` → enriched MBP Dev Monitor events
- Summary limited to 3900 chars (Calendar.app limit)

#### Files created
| File | Purpose |
|------|---------|
| `src/utils/vault_history.py` | Versioned vault snapshot management (v1.0) |
| `scripts/vault_diff.py` | CLI vault comparison tool |
| `scripts/migrate_groups.py` | Group migration + DAMAGED audit |
| `scripts/birthday_trigger.py` | Birthday T-2 trigger with hybrid cache |
| `scripts/onboard_unprocessed.py` | Unprocessed contacts priority queue |
| `scripts/bounce_handler.py` | Manual bounce/delivery-error trigger |
| `data/reexamine_queue_20260327.json` | 8 quarantined contacts from 2026-03-27 |

#### Files modified
| File | Change |
|------|--------|
| `src/agent/pro_sync_agent.py` | Vault write path calls `write_snapshot()` |
| `src/bridge/contact_macos.py` | `update_note()` adds `<!--LSAM:pre_mod:-->` stamp |
| `scripts/lsam_control_center.py` | v1.5.0: `preview` + `edit` commands |
| `supervisor.py` | New GroupQueue + `_collect_session_summary()` for calendar |
| CCC `contact-operations.applescript` | `processNoteContentV3()` tag-awareness |

#### Pending user actions
- Run `scripts/migrate_groups.py --migrate` when ready to execute group migration
- Run `scripts/birthday_trigger.py --refresh-cache` to build full birthday cache (in progress, ~14k contacts)
- Review 8 quarantined contacts via `lsam_control_center.py preview`

---
### 2026-03-29 | LSAM v5.0 Redesign Plan — Vault Rebase & Process Flow

#### Context
Post-mortem of the 2026-03-27 Tier3-NeedAttention session (30 contacts, crashed at circuit breaker: 20 crashes). Analysis of vault data revealed the system cannot compare sessions (single snapshot, no history), has timestamp corruption (future dates), name parsing failures, and 12 overlapping LSAM groups.

#### Findings from 2026-03-27 session
- 30 vault contacts processed (22 rich, 7 minimal/blocked, 1 failed acquisition)
- 8 contacts flagged for re-examination (name corruption, future timestamps, ghost profiles)
- `master_profile.json` = `profile.json` byte-identical for all contacts — no cross-session diff possible
- Crash cause: Eva CASADO had 2 LinkedIn URLs, one invalid (redirected to user's own profile)
- Group state: 12 LSAM groups with 847 in DAMAGED, 302 in Priority — entropy

#### Design — 6-part plan (`PLAN_2026-03-29_LSAM_V5_REDESIGN.md`)
1. **Vault Rebase**: Versioned history/ snapshots, retention enforcement, diff capability, timestamp sanitization
2. **Manual Processing**: Preview mode (dry-run diff) + full edit mode with field overrides
3. **Automated Triggers**: Birthday T-2 (hybrid cache), unprocessed contacts priority queue, bounce handler
4. **CCC Articulation**: Processing order protocol, pre-mod stamps, CCC tag-awareness for LSAM blocks
5. **Group Simplification**: 12 → 6 groups. `LSAM-` prefix. Aggressive DAMAGED audit (847 contacts classified)
6. **Calendar Logging**: Enrich existing MBP Dev Monitor bridge with per-contact detail in session events

#### Sprint plan (6 sprints)
S1 (Vault) → S3 (Groups) → S2 (Manual) → S4 (Triggers) → S5 (CCC) → S6 (Calendar+UX)

#### Decision
Plan approved for sprint planning. No implementation without per-sprint user confirmation. MORENO_GUARD applies to all contact writes. SIMULATION default preserved.

---
### 2026-03-26 | ⚠️ Warning Contacts Audit — 144 contacts across 6 categories

#### Context
Full audit of all macOS Contacts containing ⚠️ in their note field. AppleScript scan across 14,007 contacts, followed by automated categorization and disambiguation analysis.

#### Findings

| Category | Count | Action Required |
|---|---|---|
| AMBIGUITY | 106 | Dedup notes (47 have 2-4 duplicate blocks), auto-resolve ~20-25, manual review ~65 |
| LOW_MUTUAL | 30 | Informational; add verification sweep for wrong-profile detection |
| PROFILE_GONE | 3 | Already handled by `mark_as_disappeared` |
| NO_PROFILE_FOUND | 3 | Already handled by v4.7 warning |
| MANUAL_REJECTION | 3 | Already handled |
| FOLLOWER_DROP | 3 | Informational, within sync block |

16 ambiguity contacts already have a social profile URL set (user-resolved) but ambiguity block was never cleaned.

#### Root Cause: Ambiguity Note Bloat
`prepend_to_note` in `contact_macos.py:1410` checks `currentNote does not start with "{text}"` — but between runs, mutual connection counts change, `Ambiguity_Warning:` prefix may be added/removed, so the `starts with` check fails and a new full block gets prepended. Worst case: Virginie HAAS has 4 duplicate blocks at 4,152 chars.

#### Solution Design (3 layers)

**Layer A — Cleanup script**: Parse notes, dedup ambiguity blocks, reduce to compact format (name + URL only, strip boilerplate). Target: all 106 contacts.

**Layer B — Auto-disambiguator** (`src/tools/disambiguate_ambiguity.py`): Score candidates by name similarity (SequenceMatcher ≥ 0.85 OR URL slug contains last name) + degree + mutual count. Auto-resolve when exactly 1 candidate passes all criteria. Estimated ~20-25 safe auto-resolves out of 106.

**Layer C — Prevention fix**: Change `prepend_to_note` dedup check from `starts with` to `contains "LSAM AMBIGUITY"` to prevent accumulation on re-runs.

#### Decision
All 3 layers approved for implementation. Layer A (cleanup) first, Layer C (prevention) second, Layer B (auto-disambiguator) third. Layer B requires `--live` flag per LSAMC safety rules.

---
### 2026-03-26 (evening) | Layers A + C + B executed — ambiguity cleanup + prevention + disambiguation

#### Layer A — LIVE run (`src/tools/cleanup_ambiguity.py --live --resolved`)

| Metric | Value |
|--------|-------|
| Contacts processed | 74 (Review group subset of 106 total) |
| Written successfully | 74/74 |
| Errors | 0 |
| Bytes saved | 107,170 |
| Duplicate blocks removed | 77 |
| Resolved contacts stripped | 19 (had social profile URL set, ambiguity block removed entirely) |
| `#lsam-force-resync` tags stripped | 12 |

Backups (MORENO_GUARD): `logs/sessions/2026-03-26_17-34-55/ambiguity_cleanup/` — 74 JSON files, one per contact.

**Note**: 74 contacts in Review group vs 106 in full audit — 32 ambiguity contacts are NOT in `script-LSAM-LinkedIn to Review` (likely removed manually or never added).

#### Layer C — Prevention fix (`contact_macos.py` v4.9.3)

Changed `prepend_to_note` dedup logic from fragile `starts with` to semantic `contains` check:
- `"LSAM AMBIGUITY"` in text → checks `currentNote does not contain "LSAM AMBIGUITY"`
- `"No Profile Found"` in text → checks `currentNote does not contain "No Profile Found"`
- `"Profile disappeared"` in text → checks `currentNote does not contain "Profile disappeared"`

This prevents future duplicate block accumulation regardless of changing mutual counts or prefix variations.

#### Layer B — Disambiguation LIVE run (`src/tools/disambiguate.py --live`)

Scoring model: `0.30×name_similarity + 0.15×slug_match + 0.15×degree + 0.15×mutual + 0.25×company_match + connection_bonus`

| Classification | Count | Threshold |
|---------------|-------|-----------|
| AUTO_RESOLVE | 1 | name_sim ≥ 0.85, composite ≥ 0.75, gap ≥ 0.15 |
| SUGGEST | 27 | name_sim ≥ 0.85, composite ≥ 0.60, gap ≥ 0.15 |
| MANUAL_ONLY | 27 | everything else |

**AUTO_RESOLVE applied**:
- **James INGHAM** → James Ingham (name=1.00, comp=0.92) — social profile URL set, note updated with resolved marker

Backups (MORENO_GUARD): `logs/sessions/2026-03-26_17-56-32/disambiguation/`

**Why only 1 auto-resolve**: The strict thresholds (composite ≥ 0.75 with ≥ 0.15 gap to 2nd candidate) are intentionally conservative. Many SUGGEST contacts have strong slug matches but low composite scores because they lack company signals or have only 2nd/3rd degree connections. The 27 SUGGEST contacts are candidates for manual batch review via the Control Center.

---
### 2026-03-25 (evening) | v8.7 + v4.9.2 — Verification sweep: 4 pending tests, 3 fixes, 1 deferred

#### Context
Full autonomous verification run covering 4 pending items from the STATUS.md queue. Each item was tested in sequence with live log confirmation.

---

#### Test 1 — `--force-photo` flag (v2.4.16 Part B) ✅ PASS

Run: `python3 src/agent/pro_sync_agent.py --url /in/g-belin --name "Guillaume BELIN" --mode SIMULATION --surgical --force-photo`

Log confirmed (run_2026-03-25_15-33-20):
- `v2.4.16 Part B: --force-photo applied for Guillaume BELIN — bridge will treat photo as stale.`
- `v2.4.16 Part B: force_photo flag set for Guillaume BELIN — treating photo as stale (user override).`
- No `Photo update skipped … same resolution` message — photo was applied (force override worked). ✅
- `update_contact SUCCESS` ✅

---

#### Test 2 — Experience noise in v8.6 text parser → fixed as v8.7 ✅

**Issue discovered**: After v8.5/v8.6 fixes, BELIN vault had noisy exp[1] (description paragraph) and exp[2] (LinkedIn skills summary). The `entries.length >= 3` cap was filling up with non-role blocks.

**First pass v8.7** added two guards (`titleLine.length > 90`, `> 3 commas without pipe`). This removed the description paragraph but a new entry slipped through: `"Entrepreneuriat, Intelligence artificielle (IA) and +15 skills"` — LinkedIn's compact skills display format. Only 1 comma and 62 chars, so neither filter caught it. However, this revealed a previously-hidden real entry: `Membre du comité stratégique`.

**Second pass v8.7** added a third guard: `/\+\d+\s*skills?/i` — the `+N skills` pattern is unique to LinkedIn's skills display and cannot appear in any real job title. After this fix, vault contains 3 clean real entries:
- exp[0]: Founder & CEO / substans.ai ✅
- exp[1]: Membre du comité stratégique ✅
- exp[2]: Noèse ✅

Fix location: `pro_sync_agent.py`, JS post-scroll evaluate, after `hasMidDot` check (lines 2294–2297).

---

#### Test 3 — MORENO_GUARD Rule 3: pre-write backup missing on vault-only runs → fixed as v4.9.2 ✅

**Issue**: `update_contact` at the main `_finalize_sync` call site was invoked without `session_backup_dir`. This triggered a WARNING on every sync (full and vault-only). `self.backup_dir` is always created by `_init_session_folders()` in `__init__`, even in vault-only mode, so the directory always exists.

**Fix (v4.9.2)**: Added `session_backup_dir=self.backup_dir` to the `update_contact()` call at `pro_sync_agent.py` line ~4891. Added inline comment explaining the guarantee.

Log confirmed (run_2026-03-25_15-47-08):
- No MORENO_GUARD WARNING ✅
- `Pre-write backup saved: .../logs/sessions/run_2026-03-25_15-47-08/backups/BD98EAA4-3F06-4C20-A9FE-4D6D07477CE1_ABPerson-before.json` ✅

**Note**: The second `update_contact` call at line ~4534 (apply-validated-backup path, used by the staging workflow) still has no `session_backup_dir`. That path is for offline batch apply from the archive and is out of scope for this fix.

---

#### Test 4 — Part A modification-date staleness (v2.4.16 Part A) ⚪ DEFERRED — no eligible candidate

**Goal**: Find a contact with (a) no `Photo Date:` in sync block, and (b) Contacts.app modification_date year ≤ 2023. Run sync and confirm log shows `v2.4.16 Part A: No Photo Date … ≥3 years`.

**Scan result**: Checked 100 oldest vault entries + all LSAM group contacts:
- All vault contacts: mod_year = 2026 (March supervisor batch updated every contact)
- All LSAM groups (DAMAGED, LinkedIn-to-Review, Force-Refresh, Search-Failed): 0 members post-batch
- No eligible candidate exists in the current database

**Conclusion**: Part A is correct by code inspection (threshold: `current_year - mod_year >= 3`, i.e. year ≤ 2023; fallback only when `photo_date_str` is absent). Will self-exercise in production the next time a contact is added to LSAM that hasn't been touched in Contacts.app since 2023 or earlier. No action needed.

---

### 2026-03-25 (afternoon) | v8.4/v8.5/v8.6 — LinkedIn 2024+ DOM root cause + surgical scrape complete fix

#### Root cause: LinkedIn 2024+ React hydration removes h1 from final DOM

**Symptom**: `current_role`, `location`, `experience` all empty in vault despite BELIN profile being fully public and visible. v8.3 JS selectors, v6.5 re-nav guard, and v8.2 scroll all deployed but scrape still returning nothing.

**Diagnosis (v8.4 pre-scroll DOM snapshot)**:
- `h1_count: 0` — no `<h1>` in the hydrated DOM at all
- `scaffold_main: false` — no `.scaffold-layout__main` element
- `body_text_start` DOES contain "Guillaume BELIN" and full headline text

**Root cause confirmed**: LinkedIn uses React SSR (server-side rendering). During the initial page load, a server-rendered `<h1>` briefly exists in the DOM — this is what `_wait_for_dom_selector("h1", timeout=8s)` detects and why it returned True. Then React hydration fires, replaces the entire server-rendered HTML with a `<div id="root">` structure, hashed CSS class names, and no `<h1>`. All v8.3 selectors (`h1`, `[class*="text-heading-xlarge"]`, `.scaffold-layout__main`) target artifacts of the server-rendered pass that no longer exist post-hydration.

---

#### Fix 1 — v8.4: DOM diagnostic instrumentation (`_surgical_local_scrape`)

Added pre-scroll and post-scroll DOM snapshots at DEBUG level, plus an INFO-level diagnostic log when role or location is empty after the main evaluate. Snapshot fields: `h1_count`, `xlarge_text`, `scaffold_main`, `url`. This was the tool that confirmed the root cause above.

---

#### Fix 2 — v8.5: Pre/post-scroll evaluate split + nameEl anchor approach

**Core insight**: The profile top card (name, headline, location) is in the pre-scroll DOM. Scrolling may unmount it. Experience requires scroll to lazy-load. These two captures must be separate.

**Pre-scroll evaluate** (main evaluate, runs before any scrolling):
1. Extract profile name from `document.title` — "Guillaume BELIN | LinkedIn" → "Guillaume BELIN". This is the most stable signal across all LinkedIn layout versions.
2. Find `nameEl`: first leaf/near-leaf `div/span/h1/h2/h3` whose `innerText.trim() === name` and `children.length ≤ 1`.
3. Walk to `nameEl.parentElement.parentElement` (grandparent panel). LinkedIn 2024+ panel children:
   - `[0]` name + degree container (contains nameEl)
   - `[1]` headline string
   - `[2]` company/edu line
   - `[3]` location string
4. Walk panel children, skipping the nameEl container. First `isHeadlineCandidate` match → headline. First comma-containing, pipe-free, dot-free string → location.

**Location pipe-filter**: Headline "substans.ai Founder | AI | Best of Consulting, Power of AI | 25+ Years" contains commas and passes `isValidLocation()` — but it contains `|`. Genuine locations never have `|`. Added `!t.includes('|')` to the location filter.

**Post-scroll evaluate** (runs after `scrollTo(0.4h)` + `scrollTo(100%)`, no scroll-back-to-top):
- Experience-only. Scroll-back-to-top was removed — returning to top triggers React to unmount/remount components and can destroy the lazy-loaded experience section.

**Result**: `current_role = 'substans.ai Founder | Digital Transformation & AI | Best of Consulting, Power of AI | 25+ Years Leadership | Sciences Po'` ✅, `location = 'Meudon, Île-de-France, France'` ✅

---

#### Fix 3 — v8.6: Text-based experience extraction (post-scroll evaluate)

**Motivation**: All DOM-selector-based experience strategies (pvs-list, experience anchor, h2 sibling) returned 0 entries. User suggestion: "Did you try alternate approach based on scrolling and viewing and capturing text?" — prompted a fundamentally different approach.

**Approach**: Instead of CSS selectors for specific list items, find the experience section by its header text and parse the entire section's `innerText` as a text document.

**Algorithm**:
1. Find any `h2/h3/div` whose `innerText.trim().toLowerCase()` equals `"experience"` / `"expérience"` / `"expériences"` and has no children (leaf node = section header, not a container).
2. Walk up to `closest('section')` or `parentElement.parentElement`.
3. Split `section.innerText` by `\n{2,}` (double-newline = LinkedIn's block separator).
4. Skip first block (section header). For each subsequent block:
   - Split into lines; filter out date lines and noise lines.
   - If `lines[0]` has a middle dot (·) → skip (this is a detail line like "substans.ai · Paris, Île-de-France"). Only role titles appear as the first line of a block.
   - Parse title from `lines[0]` (before `|` if present). Parse company from `lines[1]` if not a dot-line or date.
5. Cap at 3 entries.

**Result**: `exp[0] = {title: 'Founder & CEO', company: 'substans.ai'}` ✅. exp[1] and exp[2] are description/skills noise (long paragraph, skill keywords) — acceptable since `get_clean_role` and sync block only use `exp[0]`.

---

#### Fix 4 — Experience ValidationError (pydantic field name bug)

The `Experience(...)` constructor call used `company_name=e.get('company', '')`. The pydantic model field is `company`, not `company_name`. This caused a silent `ValidationError` that was swallowed, leaving `exp_list = []` even after v8.6 successfully returned 3 entries. Fixed to `Experience(title=e['title'], company=e.get('company', ''))`.

This bug was latent since v8.3 — experience_raw was always empty before, so the constructor never ran.

---

#### Fix 5 — JS regex SyntaxError in `_scroll_snap` diagnostic

Python non-raw `"""..."""` strings: `'\n'` is an actual newline. JavaScript regex `/\n/g` embedded in these strings became an un-terminated regex at parse time → `SyntaxError: Invalid regular expression: missing /`. Fixed to `.split('\n').join('|')` → then to `.replace(/\\n/g, '|')` (double backslash in Python non-raw string delivers `\n` to JS as the regex wants).

---

#### Fix 6 — SVGAnimatedString crash in nameEl className check

`document.querySelectorAll('div, span, h1, h2, h3')` can match SVG elements embedded in the page. SVG element `.className` returns an `SVGAnimatedString` object, not a plain string. Calling `.substring()` on it raises `TypeError: nameEl.className.substring is not a function`. Fixed to `typeof el.className === 'string' ? el.className : String(el.className.baseVal || '')`.

---

#### Vault state after v8.5/v8.6 (2026-03-25 run, PID 91179)

```
current_role:  'substans.ai Founder | Digital Transformation & AI | Best of Consulting, Power of AI | 25+ Years Leadership | Sciences Po'
location:      'Meudon, Île-de-France, France'
experience[0]: title='Founder & CEO', co='substans.ai'
followers:     2515
connections:   500
mutual:        128
```

`get_clean_role()` → `'substans.ai Founder'` (v5.4: headline_primary wins over single-word generic exp[0].title).

Final log confirmation:
```
Surgical Local Scrape successful for Guillaume BELIN (Role='substans.ai Founder | ...', Co='substans.ai')
```

---

### 2026-03-25 | v2.4.16 — Photo staleness A+B, inspect crash, photo download SyntaxError, v5.4 role heuristic

#### 1. Photo staleness — `--force-photo` flag (Part B) + modification-date fallback (Part A)

**Problem**: `is_stale_photo = False` for any contact with no `Photo Date:` in their sync block. The 3-year freshness rule never fired for first-time syncs or contacts with cleared notes.

**Part B — `--force-photo` CLI flag** (`pro_sync_agent.py`, `profile.py`, `contact_macos.py`):
- New `force_photo: bool = False` field on `LinkedInProfile`.
- New `--force-photo` argument in `pro_sync_agent.py` arg parser.
- In `sync_profile`, just before `update_contact`, sets `profile.force_photo = True` when flag is present.
- In `contact_macos.py`, after existing photo-date staleness logic: if `profile.force_photo` → set `is_stale_photo = True` (photo_age_years sentinel = 99.0, logged as "user override").
- Precedence: force_photo check fires FIRST, before Part A.

**Part A — macOS modification date fallback** (`contact_macos.py`):
- When `photo_date_str` is absent (no Photo Date in sync block) AND `force_photo` is not set:
- Reads `current.get("modification_date")` — the contact's macOS last-modified timestamp. This is fetched BEFORE any write, so it reflects the pre-update state (correct reference point per INCIDENT_MORENO rule).
- Extracts the 4-digit year from the locale-specific date string (AppleScript `as string` is locale-dependent; year regex `\b(20\d{2})\b` is locale-safe).
- If `current_year - mod_year ≥ 3`: sets `is_stale_photo = True`, `photo_age_years = float(mod_year_delta)`.
- Logged as "v2.4.16 Part A".

**Decision precedence** (highest to lowest):
1. `profile.force_photo` → always stale
2. `Photo Date:` in sync block → exact date-based staleness
3. `modification_date` from macOS → year-level proxy staleness
4. No data → `is_stale_photo = False` (safe default, no change)

---

#### 2. `lsam_control_center.py inspect` crash — JSON mode exit + logging isolation

**Root cause** (fully diagnosed):
The `runCLI` handler in AppleScript runs `do shell script cmd`. Python's `logging.basicConfig` writes INFO to stderr. When the Python command exits with code 2 (S2-F convention for "not found"), `do shell script` raises AppleScript error — `errMsg` = the stderr content = `"INFO: ContactMacOSBridge initialized in SIMULATION mode"`. The `on error` handler in `runCLI` wraps this as `{"success": false, "error": "INFO: ContactMacOSBridge initialized in SIMULATION mode"}`.

**Fix — two-layer** (`scripts/lsam_control_center.py`):

**Layer 1 — JSON mode logging isolation**: New `setup_logging(debug, json_mode=False)`. When `json_mode=True` and not debug: installs `NullHandler` on root logger. Stdout stays clean for JSON; no log lines can contaminate the payload. Verified: `NullHandler` confirmed by smoke test.

**Layer 2 — JSON mode exit code**: New `_not_found_exit(args)` helper: `sys.exit(0 if args.json else 2)`. Replaces ALL 10 `sys.exit(2)` calls in `cmd_*` functions. In JSON mode, exit 0 → `do shell script` succeeds and returns the clean JSON. In non-JSON shell mode, exit 2 (S2-F convention preserved).

**Verified end-to-end**:
```
$ python3 scripts/lsam_control_center.py inspect "Guillaume BELIN" --json
{"success": false, "message": "No archive entries for 'Guillaume BELIN'."}
EXIT CODE: 0
```
Clean JSON, exit 0 → `runCLI` returns the JSON string → AppleScript parses it normally.

---

#### 3. Photo download JS `SyntaxError: Unexpected token 'if'` (`pro_sync_agent.py` `_download_photo`)

**Root cause**: In the `for (const size of sizes)` loop, `const noSigUrl = testUrl.split('?')[0]` was declared with `const` INSIDE the `if (!res || !res.ok)` block (block-scoped), then referenced OUTSIDE that block in a subsequent `if (noSigUrl !== testUrl)` check. V8 raises `SyntaxError: Unexpected token 'if'` when parsing the function string because the hoisting rules for `const` are violated at parse time.

**Fix**: Hoisted `const noSigUrl = testUrl.split('?')[0]` to the top of the `for` loop body (before both `if` blocks that need it). Also added `(!res || !res.ok)` guard to the second fetch attempt (Strategy 2b) — no point retrying if Strategy 2a already succeeded. Comment updated to explain both strategies.

**Impact**: Photo browser-fetch path will now work correctly. The `requests` fallback remains for robustness.

---
### 2026-03-24 | v2.4.15 — Sync block, photo quality, re-nav guard, scroll sequence

#### Context
Session focused on BELIN (Guillaume) as test contact. Multiple prior sessions had failed to populate the vault because of a `re.error` crash in `profile.py:438` (fixed in previous session). Once that was fixed, new issues surfaced.

---

#### 1. `_run_applescript` error logging restored (`contact_macos.py:125`)
**Problem**: `logger.error(...)` on non-zero osascript exit was commented out — all AppleScript failures were completely silent. Root cause of "sync block not updated" being undiagnosable for weeks.
**Fix**: Un-commented the logger.error line.
**Impact**: Any future AppleScript failure now surfaces in session.log immediately.

---

#### 2. `update_contact` return value logged at all call sites (`pro_sync_agent.py`)
**Problem**: The three call sites of `self.bridge.update_contact(...)` did not log the result. A successful osascript return meant "SUCCESS" appeared nowhere in the log; a failure was also silent (see #1).
**Fix**: Added `logger.info("update_contact SUCCESS …")` and `logger.error("update_contact FAILED … : …")` after the main FULL-mode call (line ~4595). Added a FAILED-only log for the triage SIMULATION path (line ~4398). The apply-backup path (line ~4248) already had failure logging.
**Result**: Confirmed BELIN's Sync Now DID succeed — `update_contact SUCCESS` visible in manual_sync.log.

---

#### 3. "Updated :" line — replace-not-accumulate (`profile.py` `generate_sync_block`)
**Problem**: Every sync run merged new `updated_fields` with ALL previous "Updated :" signals from the existing sync block. Result: `Updated : Photo (Upgrade: 400x400 vs 100x100), Photo (Upgrade: 800x800 vs 200x200), Photo (Quality Refresh: 27730b vs 483382b)` — a growing list across sessions.
**Fix (v2.4.15)**: Changed to replace-not-accumulate: if the current run has new `updated_fields`, replace the "Updated :" line with ONLY those. If the current run has no new signals, carry forward the LAST "Updated :" line unchanged (preserving the most recent state). The merge-all-history behaviour is removed.

---

#### 4. Photo quality — byte-size comparison removed (`contact_macos.py`)
**Problem**: The "Quality Refresh" path fired when new_res >= old_res AND file size differed >15%. This produced "Photo (Quality Refresh: 27730b vs 483382b)". The comparison was wrong: the vault stores a HEIC-converted copy of the LinkedIn JPEG; HEIC is always significantly smaller than JPEG at equal perceptual quality. Cross-format byte comparison is not a reliable quality signal.
**Fix (v2.4.15)**: Removed the `elif is_size_change: … "Quality Refresh"` branch entirely. For same-resolution, non-stale photos: `should_update_photo = False` — skip the update. Only two conditions now trigger a photo update when `new_res >= old_res`: (a) `is_res_change` = True → "Photo (Upgrade: WxH vs WxH)", (b) `is_stale_photo` = True → "Photo (Refresh: N years old)". Resolution (pixel count) is the only format-agnostic quality metric.
**Note**: The `elif new_res == old_res and img_size > orig_size * 1.5` path at line ~1006 (quality upgrade for same-res but much larger) was intentionally left — this fires for same-format (JPEG vs JPEG) comparisons only, when the contact has no original backup path.

---

#### 5. Photo Date — suppress when same as sync date (`profile.py`)
**Problem**: `Photo Date: 2026-03-24` appeared in the sync block even though the header `<Linkedin-AI-sync 2026-03-24 update>` already conveys the same date.
**Fix (v2.4.15)**: `if photo_date and photo_date != date_str` — Photo Date is now only emitted when the photo was last updated on a DIFFERENT day than the current sync (carry-forward case from a previous session). When the photo is applied today, the header date is sufficient.

---

#### 6. v6.5 re-nav guard — pre-sleep + retry (`pro_sync_agent.py`)
**Root cause diagnosed from timing**: Line 53 (Stealth Nav) at 15:26:36,180; line 54 ("not confirmed") at 15:26:37,338 — only 1.158 seconds elapsed. With timeout=8000ms, a genuine timeout would have put line 54 at ~15:26:44. The ~1s gap is a Playwright `ExecutionContextDestroyed` / `FrameNavigated` exception thrown immediately because `page.goto()` returns on `load` but the SPA continues mounting React components after load. The `except Exception:` swallowed this as if it were a timeout and fell through to `sleep(4)`.

**Fix (v6.5)**:
1. `await asyncio.sleep(2.0)` BEFORE `wait_for_selector` — lets SPA hydration begin
2. Primary `wait_for_selector` with expanded selectors incl. bare `h1` and `article` within `.scaffold-layout__main` (timeout 8s)
3. On ANY exception: sleep 5s (was 4s), retry `wait_for_selector` with even broader selectors + bare `body *` (timeout 12s)
4. On retry failure: log exception type (surfaced for future diagnosis) and proceed — surgical scrape has its own h1 wait (v8.2)

**Log signals to watch for**: `v6.5: Profile DOM confirmed ... (primary pass)` or `(retry pass)` = fix working. Still seeing "still not confirmed" = further investigation needed.

---

#### 7. v8.2 scroll sequence — wait for h1 before scrolling (`pro_sync_agent.py` `_surgical_local_scrape`)
**Root cause**: v8.1 scroll ran immediately after a generic `asyncio.sleep(3.0)`, regardless of whether the profile React components had mounted. When called after v6.4's sleep(4), the page was still rendering. Scroll on an unmounted profile = no-op for lazy-load purposes.

**Fix (v8.2)**:
1. Added `await page.wait_for_selector('h1', timeout=10000)` BEFORE the scroll. h1 presence = profile top card mounted = scroll will trigger real lazy-loading.
2. If h1 still absent after 10s: log warning with exception type, proceed anyway (graceful).
3. Reduced post-h1 settlement sleep from 3.0s to 2.0s (h1 wait already consumed time).
4. Extended scroll pauses: 40% position: 1.2s (was 0.8), 100% position: 2.0s (was 1.2), back to top: 0.8s (was 0.5).

**Expected new log signals**: `[Surgical] v8.2: h1 detected — profile top card mounted` then `[Surgical] v8.2: Scroll-to-load complete.` before the JS evaluation.

---

#### 8. v8.3 JS selector fixes — headline parent-walk, experience `ul li`, location `·` exclusion (`pro_sync_agent.py`)
**Root causes** (diagnosed from BELIN screenshot showing fully-public profile with visible headline/experience/location yet all three returning empty):

1. **Headline**: `h1.nextElementSibling` walk is at the wrong DOM level. LinkedIn 2024+ wraps `h1` in a container `div`; the headline `div` is a sibling of that container, not of `h1` itself.
   - **Fix**: Added Level 1 walk (`h1.parentElement.nextElementSibling`) and Level 2 walk (`h1.parentElement.parentElement.nextElementSibling`). Extracted to helper `isHeadlineCandidate()` to deduplicate the rejection logic across all three walk levels.

2. **Experience**: `.pvs-list > li` (direct-child combinator) missed items nested one level deeper. `document.getElementById('experience')` still works but may fall through Strategy 1 if the list is nested. Strategies 2 and 3 had the same issue.
   - **Fix**: After each `.pvs-list > li` query returns 0 items, fall back to `sib.querySelectorAll('ul li')` (any-descendant) in all three strategies. Also upgraded Strategy 1 anchor detection to `getElementById('experience') || querySelector('[id*="experience"]')` for robustness.

3. **Location**: Geographic keyword heuristic matched `"substans.ai · Paris, Île-de-France, France"` — an experience subline containing both company name and location joined by middle dot `·`. `isValidLocation()` passed it (no digits, not too long). The `·` character is LinkedIn's separator in experience sublines.
   - **Fix (two layers)**: (a) New h1-relative top-card span walk (IIFE in `l_candidates`): scans `h1.parentElement.parentElement` spans for comma-containing, `·`-free strings ≤ 80 chars — the genuine location span is always here in 2024+ layout. (b) Geographic keyword heuristic now excludes strings containing U+00B7 (middle dot) or U+2022 (bullet).

---

#### 9. v5.4 `get_clean_role` — richness-aware headline vs. experience selection (`profile.py`)

**v5.3 bug**: `has_headline_separators` fired for any headline with `|` (virtually all LinkedIn headlines). Then `len(exp_role) < len(role)` was trivially true (7-char "Founder" < 100-char headline) — the bare experience title **always** won. BELIN's job title would be written as "Founder" instead of "substans.ai Founder".

**Root cause**: v5.3 compared the FULL headline length against experience, not the first segment. LinkedIn headlines are multi-segment personal branding statements; only the first segment (before `|`) is the curated primary role.

**v5.4 fix** (`get_clean_role`, `profile.py`):
1. Extract `headline_primary` = first `|` (or `•`) segment.
2. Define `_BARE_GENERIC`: single-word titles that alone are under-informative (Founder, CEO, Partner, Director…).
3. Prefer `experience[0].title` ONLY in two concrete cases:
   - **Case A**: `headline_primary` is a bare single-word generic AND `experience[0].title` has ≥ 3 words.
   - **Case B**: `headline_primary` itself exceeds 80 chars AND experience is shorter.
4. Otherwise: use `headline_primary`. Tie goes to `headline_primary` (user-curated signal).

**Test matrix** (all 8 cases verified by automated unit test, syntax + import checks passed):

| Headline | Exp[0] | v5.3 → v5.4 |
|----------|--------|-------------|
| `substans.ai Founder \| AI \| 25+ Years…` | Founder | Founder ❌ → **substans.ai Founder** ✅ |
| `Executive \| Leader \| Visionary` | Group Chief Digital Officer EMEA | Executive ❌ → **Group Chief Digital Officer EMEA** ✅ |
| `Senior Partner \| McKinsey \| Digital` | Partner | Partner ❌ → **Senior Partner** ✅ |
| `CEO` (single word) | Chief Executive Officer Global | CEO → **Chief Executive Officer Global** ✅ |

---

#### 10. Vault status for BELIN (2026-03-24 session)
- **SIMULATION run 15:26**: vault written at `data/vault/BD98EAA4-3F06-4C20-A9FE-4D6D07477CE1:ABPerson/`
- **Data quality**: `current_role: ""`, `experience: []`, `location: null` — scrape still empty (v6.4 failure, v8.1 scroll on unconfirmed page)
- **Sync Now (vault-only FULL)**: confirmed successful — `Executing update_contact script (len 1795)` + `update_contact SUCCESS` in manual_sync.log
- **Sync block**: written with followers/connections/mutual data, but no role/location/experience (empty vault)
- **Photo**: NOT re-applied by Sync Now (no photo path in vault-only run — expected). Existing contact photo preserved.
- **Next sync**: will benefit from v6.5 + v8.2 fixes — expect `current_role` and `experience` to populate

---

### 2026-03-19 | Skill registry divergence — documented (S4-2)

**Decision**: LSAMC intentionally does NOT import from `_skills/applescript_bridge/` or `_skills/identity_resolution/`. This is a known, deliberate architectural choice, not an oversight.

**Rationale**: LSAMC predates the `_skills/` registry by several versions. Its AppleScript execution and identity resolution are deeply integrated with LSAMC-specific error handling, CAPTCHA detection, retry logic, and session state. Retrofitting skill imports carries risk with zero benefit — the existing code is production-tested across 800+ contacts.

**Implication**: LSAMC does not count toward the "freeze lift" condition in `SKILL_LAYER_DEPLOYMENT_LOG.md`. PAIA remains the only qualifying project for `identity_resolution`. The freeze on Candidates 6 & 7 stands.


---
### 2026-03-19 | v2.4.9 — Triage sort + 52-contact last-name recovery

**Triage sort fix**: `scanAndSortGroup` now takes `sortByStatus` (bool). NSSortDescriptors (`localizedCaseInsensitiveCompare:` familyName → givenName) applied before bucketing. `handleTriageDamaged` (false): alpha by family name only. `handleProfileReview` (true): [Ambiguous] first → [No Block] → others, alpha within each bucket.

**52-contact last-name damage (NOT AVAILABLE)**: Batch runs wrote "NOT AVAILABLE" into `last_name` directly — v5.5 guard only blocked `full_name`. 4128 VCFs scanned across 1118 UIDs; 64 damaged found; all 64 recoverable from earlier session backups via UID matching; 12/64 already self-corrected; 52 remain. Recovery tools: `scripts/recover_not_available.py` (scan + output JSON) + `scripts/apply_not_available_fix.py` (dry-run + `--live` with per-contact backup per Moreno Rule 3). **Applied 2026-03-20**: 52 written · 0 errors · 12 skipped. Backups at `logs/sessions/fix_2026-03-19_22-10-33/`. Archive: `BRAIN/archive/INCIDENT_NOT_AVAILABLE_20260319.md`.

**Prevention — v5.6 Double Guard**: (1) `profile.py`: `model_config = ConfigDict(validate_assignment=True)` — Pydantic field validator now fires on post-construction attribute assignment (previously bypassed). (2) `contact_macos.py` `else` branch: `_BRIDGE_BLOCK` set checked immediately before `set last name of p to` AppleScript write — blocks all placeholder strings and empty string; logs `v5.6 Bridge Guard` on trigger. Defence chain: **Pydantic validator → validate_assignment → Bridge Guard → AppleScript write**.

---
### 2026-03-20 | v2.4.9 S9-B — `_stealth_nav` v5.2 + v6.3 guard + v1.5.8 scrape identity

**Trigger**: manual sync BELIN — no photo applied, nothing in vault. Log: guard fired at 20:37:30, scrape started at 20:37:33 (exactly 3s, meaning `_stealth_nav` completed in ~0ms = early return).

**Root cause (v5.1 did not fix it)**: `_stealth_nav` used `page.get_url()` (CDP frame URL) → returns base profile URL even when overlay is open. v6.2 guard used `page.evaluate("window.location.href")` (JS-visible URL with `/overlay/contact-info/`). `_nu()` comparison saw two identical base URLs → early return → no navigation.
**Fix v5.2**: `_stealth_nav` now uses `page.evaluate("() => window.location.href")`.

**v6.3 guard**: `asyncio.sleep(3)` → `wait_for_selector("h1.text-heading-xlarge, .pv-top-card", timeout=8000)`. Profile-specific; absent on feed. Falls back to `asyncio.sleep(4)`.

**v1.5.8 identity block**: `invalid_names` += `"feed updates"`, `"feed | linkedin"`, `"feed post"`. Also blocks via `debug_title` (document.title). Prevents ghost profile name="feed updates" from reaching `update_contact`.

**Files**: `src/agent/pro_sync_agent.py`, `LSAM Control Center UTF8.applescript` + compiled (v2.4.9 S9-B).

---
### 2026-03-23 | v2.4.10 S10 — Apply Photo action + surgical scrape v8.0 selector hardening

**Apply Photo action (`processProfileReview`)**:
New "📸 Apply Photo" action added to the `processProfileReview` action menu (between Promote and Skip). Logic:
1. Vault-first: checks `data/vault/<UUID>:ABPerson/linkedin.heic` (written by every successful SIMULATION run).
2. Fallback: `find logs/sessions -name '*-linkedin.heic' -path '*<last-word-of-displayName>*' | sort -r | head -1` (most recent session backup by last-name fragment).
3. Applies via `set image of p to (read (POSIX file path) as data)` + `save`. Shows notification with filename on success.
**Files**: `LSAM Control Center.applescript` (UTF-16) + `LSAM Control Center UTF8.applescript` + compiled `.scpt`. Version bumped to **v2.4.10**.

**Surgical scrape v8.0 — selector hardening (`_surgical_local_scrape`)**:
Root cause of `H1: None` / all-empty scrape: `profileRoot` detection relied on `.pv-top-card` (2022-era) and `[id^="profile-content"]` (2023-era) — both obsolete.

| Change | Old | New (v8.0) |
|--------|-----|------------|
| profileRoot | `.pv-top-card` first | `.scaffold-layout__main` first, `body` as last resort |
| h1 detection | `h1.text-heading-xlarge` only | + `h1[class*="t-24"]`, `h1[class*="inline"]`, document-level fallbacks |
| headline fallback | exact `.text-body-medium.break-words` | + `[class*="text-body-medium"][class*="break-words"]`, `[data-generated-suggestion-target]`, `[class*="headline"]` |
| location | exact 4-class `.text-body-small.inline.t-black--light.break-words` | + `[class*="t-black--light"][class*="break-words"]`, `[class*="location"]`, geographic keyword heuristic |
| experience strategy-3 | absent | section heading text match (`"experience"`, `"expérience"`) |
| experience items | `pvs-list > li` only | + `[data-view-name="profile-component-entity"]` |
| getItemTitle | 3 selectors | + `[data-field="experience_title"] span[aria-hidden="true"]` |

**Files**: `src/agent/pro_sync_agent.py` (Syntax OK confirmed).

---
### 2026-03-20 | CLOSED — 8 contacts fixed manually by user

All 8 "NOT AVAILABLE" contacts confirmed repaired (`osascript` query returns 0 exact matches). The `INCOMPLETE` entry below is superseded.

---
### 2026-03-20 | INCOMPLETE — 8 contacts still damaged (next session entry point)

**Status**: Soft rebase pending. Resume here next session before any other work.

**Root cause of scanner miss**: `recover_not_available.py` indexes backups by `UID:` (iCloud UUID). These 8 contacts have backup VCFs where `UID:` is absent or written only post-damage, so they never appeared in the `by_uid` index as "damaged". Fix: add second pass keyed by `X-ABUID:` (always present in Contacts-generated VCF).

**8 remaining damaged contacts** (live `last name = "NOT AVAILABLE"`):

| First name | AB UUID (without :ABPerson suffix)       |
|------------|------------------------------------------|
| Alain      | D418B231-FD72-46E6-8DEC-D98E29B122DB    |
| Guillaume  | BD98EAA4-3F06-4C20-A9FE-4D6D07477CE1    |
| Didier     | 89141D35-5861-4BE1-AC23-DFF0BD8282EC    |
| Alain      | 80A37380-75C8-40C1-9283-B58626FC8413    |
| Alain      | 9FDAFA52-663F-4DE6-89D7-962154DDE171    |
| Alain      | DB95112C-A9A7-4B6B-9F31-AE34E3B56789    |
| Jean-Louis | 6B2C94E9-642C-499A-A679-27C8DF6ED017    |
| Emmanuel   | 82464FA5-AC1F-4AA0-A23F-75DF7AC96DD9    |

**Fix strategy (next session)**:
1. Extend `recover_not_available.py` with second pass keyed by `X-ABUID:` field — catches contacts whose iCloud `UID:` was absent or rotated.
2. For contacts with no clean backup at all: extract last name from LinkedIn slug in the VCF `X-SOCIALPROFILE` field.
3. Apply via `apply_not_available_fix.py --live` (surgical `set last name` only, no vCard replacement).
4. Make `X-ABUID:` secondary index permanent in the scanner.

**What was fixed this session**:
- 52 contacts: `last name = "NOT AVAILABLE"` (exact) via UID-keyed backup scan
- 1 contact: Frédéric CARON — `last name = "AVAILABLE"` (partial write) — fixed after broadening damaged-name set to 14 variants
- 5 contacts: `first name = "Information"/"Profile"` — osascript surgical fix (Humm→Philipp, Tchernonog→Alain, Deleury→Benoît, Clever→Michael, HEME→Éric)
- Guard hardened in `profile.py`, `contact_macos.py`, `recover_not_available.py`, `apply_not_available_fix.py` — now blocks `AVAILABLE`, `MEMBER`, `THE WORLD'S LARGEST PROFESSIONAL NETWORK` and 11 other variants

---
### 2026-03-19 | v2.4.8 — Three bugs from 11:06 session logs

**Bug 1 — `_stealth_nav` substring early-return (critical — same root as v6.1 guard)**
v6.2 guard correctly detected overlay drift and called `_stealth_nav(page, linkedin_url)`, but `_stealth_nav` had `if url in current_url: return` — the same substring bug. Overlay URL contains profile URL as prefix → early-return fired → no navigation → scrape still ran on overlay/feed → "feed updates" with role = "Feed post number 1".
Fix (v5.1): normalized exact path comparison using `_nu()` helper (strip trailing slash + query/fragment).

**Bug 2 — Double-prefix URL regression (LECOUFFE and TRUCCO)**
LECOUFFE's social profile URL stored as `http://www.linkedin.com/in/linkedin.com/in/slug` (written by an old buggy sync). `lsamNormalizeLinkedInURL` extracted `linkedin.com/in/slug` (still has domain). `lsamExtractLinkedInSlug` returned `linkedin.com/in/slug` as the "slug". Agent received it, doesn't start with `http` → prepended full URL → `https://www.linkedin.com/in/linkedin.com/in/slug` in Chrome.
Fix (two layers): (1) `lsamNormalizeLinkedInURL` loops up to 5× until no `linkedin.com/in/` prefix remains. (2) Python agent uses `re.split` on all nested `linkedin.com/in/` markers and keeps only the last segment.

**Bug 3 — Contacts.app contact not displayed before review dialog**
`select {person id abID}` (v2.4.2) failed -1708. `show person id abID` conflicted with AppleScript's own `show` keyword (Finder windows). Fix: `open location "addressbook://UUID"` — Contacts.app URL scheme navigates directly to the contact card. `tell application "Contacts" to activate` follows. Applied at `processProfileReview` and `processTriageAction`.

**Vault empty (consequence)**: all scrapes ran on overlay/feed since v6.1 was introduced → identity check blocked → `_finalize_sync` never reached → no vault write. Bugs 1+2 fix the navigation chain; first successful scrape will populate vault.

**Files**: `src/agent/pro_sync_agent.py` (v5.1 `_stealth_nav`, v2.4.8 URL normalization), `LSAM Control Center UTF8.applescript` + `.applescript` + `.scpt` (v2.4.8).

---
### 2026-03-19 | v2.4.7 — Four bugs diagnosed from 10:33 session logs

**Symptoms observed**: LECOUFFE skipped ("no URL provided") despite having a LinkedIn slug; TRUCCO role = "Feed post number 1" and company = None; CONSOGNI applied empty role/experience from vault despite being a FULL sync; Sync Now asked for CONSOGNI slug again.

**Bug A — v6.1 navigation guard false-negative (critical)**
Substring check `linkedin_url not in current_url` was WRONG: `"https://www.linkedin.com/in/slug/"` IS a substring of `"https://www.linkedin.com/in/slug/overlay/contact-info/"` → guard never fired → surgical scrape executed on the overlay page → h1 was "feed updates" → role = "Feed post number 1", experience = [].
Fix (v6.2): normalized path comparison — strip trailing slash, query string, fragment; compare exact paths. Overlay URL `/in/slug/overlay/contact-info` ≠ profile path `/in/slug` → re-navigation now fires. Sleep extended from 2s to 3s post-navigation for SPA hydration.

**Bug B — Vault hit bypassing FULL mode (critical)**
`sync_profile()` used vault data whenever `vault_hit["is_stale"] == False` AND `vault_hit["needs_photo_retry"] == False`, regardless of `vault_only` flag. CONSOGNI's simulation had written a vault entry with empty role/company/experience (because the surgical scrape had bug A at that time). FULL sync hit that vault, declared it "fresh", bypassed LinkedIn, and applied the broken data.
Fix (v1.2.3): vault shortcut now ONLY applies when `self.vault_only` is True (explicit `--vault-only` flag = Sync Now action). All other modes (FULL, SIMULATION) always scrape LinkedIn fresh.

**Bug C — Sync Now "no slug resolved" for CONSOGNI**
`processProfileReview` re-looked up the LinkedIn slug from `social profiles of person id abID` inside a silent try/on error block. When this lookup failed, the failure was swallowed and `cSlug` stayed empty → URL prompt shown.
Fix: `processProfileReview(contactID, displayName, slugHint)` — new 3rd parameter. `handleManualSync` stores slugs in `_pLastSyncedSlugs` (parallel to IDs/Names); `handlePostSyncReview(idList, nameList, slugList)` passes them through. Slug hint used directly; live lookup only as fallback.

**Bug D — LECOUFFE URL not found**
Social profile loop read `user name of sp` exclusively. Some contacts store LinkedIn URL only in the `url` field. Loop also only matched `service name contains "linkedin"`, missing contacts where url field contains "linkedin.com" but service name is unusual.
Fix: match by `(spSvc contains "linkedin") or (spUrl contains "linkedin")`. Fall back to `url of sp` when user name is empty. Log warning when both are empty.

**Files**: `src/agent/pro_sync_agent.py` (v6.2 guard + v1.2.3 vault-only), `LSAM Control Center UTF8.applescript` + `.applescript` + `.scpt` (v2.4.7), `_pLastSyncedSlugs` property added.

---
### 2026-03-19 | v2.4.6 — shutil Crash, Surgical Scrape Selectors, Dialog Version Title

**Bugs fixed (three independent issues)**:

**1. `UnboundLocalError: shutil` — Sync Now vault-hit path completely broken**
Root cause: `import shutil` only existed inside the non-vault photo block (~line 3928 in `sync_profile()`). The vault-hit branch at line 3734 called `shutil.copy2()` before Python ever reached that import, crashing every Sync Now run where a vault entry was found.
Fix: added `import shutil` as a local import at the top of the `if vault_hit["photo_path"]:` block (same pattern used in `_finalize_sync` with `import shutil as _shutil`).

**2. Surgical scrape — role/company/experience not extracted from current LinkedIn HTML**
Root cause: CSS selectors written for LinkedIn HTML circa 2023 fail silently on current (2025) structure.
- Experience: `#experience ~ .display-flex .artdeco-list__item` — LinkedIn now uses `div#experience` as an anchor node; actual list is in a `pvs-list` in a sibling section. Items never found → `experience_raw: []`, `current_role: ""`.
- Headline: `.text-body-medium.break-words` was correct but fragile; sometimes found wrong element. Replaced with h1-sibling DOM walk as primary path.
- Location: `l_el` selector fell back to an element containing the mutual connections blob (e.g., "Office manager chez E-Lab Bouygues" was captured as location). No validation existed.

Fix (v7.0 surgical JS):
- Experience: replaced with `getExpItems()` — walks from `document.getElementById('experience')` parent, scans forward siblings for `.pvs-list > li`; falls back to section scan, then legacy selector.
- Title/company within item: uses `span.mr1 > span[aria-hidden="true"]` (most stable LinkedIn text carrier) and ordered span scan instead of stale class names.
- Headline: h1 next-sibling walk first; class selectors as fallback. First non-empty, non-numeric, non-connection line wins.
- Location: `isValidLocation()` guard — rejects strings >120 chars, rejects anything with digits AND connection/relation/mutual keywords, rejects multi-line strings. Candidate list scanned; first valid hit wins.

**3. processProfileReview dialog title missing version**
Root cause: `with title "LSAM — Profile Review: " & displayName` — `_pVersion` not included.
Fix: changed to `"LSAM v" & _pVersion & " — Profile Review: " & displayName`.

**Files**: `src/agent/pro_sync_agent.py` (shutil fix + v7.0 surgical JS), `LSAM Control Center UTF8.applescript` + `.applescript` + `.scpt` (v2.4.6, version title fix).

---
### 2026-03-19 | v2.4.4 — Manual Sync Bypasses Stealth Time Gate

**Bug**: Manual Sync (SIMULATION and FULL modes) was blocked by `StealthManager` outside 08:00–20:00 — same policy as the automated scheduler. This made the feature unusable at night.

**Root cause**: `handleManualSync` launched `pro_sync_agent.py` without `LSAMC_IGNORE_HOURS=1`. The env var bypass already existed in `StealthManager` but was never set.

**Fix**: `handleManualSync` now prepends `LSAMC_IGNORE_HOURS=1` to the shell command. Daily quota and per-contact cooldown limits still apply — only the time gate is skipped.

**Also diagnosed (no new code needed)**: All FULL/SIMULATION runs from 16:56–17:17 today crashed with `UnboundLocalError: updated_fields` in `contact_macos.py:792` — the bug fixed earlier this session. No run has reached `update_contact` since that fix; all post-20:00 attempts were stealth-blocked. First successful end-to-end write will confirm the fix.

**Files**: `LSAM Control Center UTF8.applescript` + `.applescript` (v2.4.4), `src/utils/stealth_manager.py` (comment update), `.scpt` recompiled clean.

---
### 2026-03-18 | v2.4.3 — Vault Write Fix (Root Cause: Simulation Never Populated Vault)

**Bug**: After simulation, the dialog showed "No LinkedIn vault data available. (vault lookup failed)" and Sync Now reported VAULT MISS for every contact.

**Root cause (architectural gap)**: `_finalize_sync()` saved all artifacts to `logs/sessions/run_*/backups/<name>/` only. Neither `cmd_profile` (which serves the AppleScript vault display) nor `_check_vault()` (which gates Sync Now --vault-only) ever looked there. Both look in `data/vault/`. `scavenger_meta.json` — required by `_check_vault()` — was only ever read, never written by `pro_sync_agent.py`. The 240 existing entries were from a separate (legacy) scavenger tool.

**Secondary issue**: AppleScript passes plain UUID (`pyID`, `:ABPerson` stripped) to `cmd_profile --contact-id`. Vault dirs use `UUID:ABPerson` format. The exact-path lookup in `cmd_profile` always missed.

**Fix 1 — `pro_sync_agent._finalize_sync()`** (v6.0 block, SIMULATION branch):
After `AUDIT COMPLETE`, writes `data/vault/<contact_id>/`:
- `profile.json` → consumed by `cmd_profile`
- `master_profile.json` → consumed by `_check_vault()`
- photo copy (before temp cleanup) → consumed by both
- `scavenger_meta.json` with `contact_id`, `scavenged_at`, `source: "manual_sync_simulation"` → `_check_vault()` locator

**Fix 2 — `lsam_control_center.cmd_profile()`**:
Now tries `data/vault/<uuid>/profile.json` first, then `data/vault/<uuid>:ABPerson/profile.json`. Backwards-compatible with all existing enricher vault entries.

**Files**: `src/agent/pro_sync_agent.py`, `scripts/lsam_control_center.py`, both `.applescript` sources (v2.4.3), `LSAM Control Center.scpt` recompiled clean.

**Remaining open**: Federico TRUCCO's simulation fails with `Gemini ValidationError: full_name = None` — Gemini cannot extract name from his LinkedIn page. Vault write only triggers after a successful `_finalize_sync` call, so TRUCCO vault stays empty until Gemini succeeds on a retry.

---
### 2026-03-18 | Control Center v2.4.2 — Two Crash Fixes

**Fix 1 — `contact_macos.py` `UnboundLocalError`**:
Stale v5.5 block at lines 790-793 referenced `updated_fields`/`added_fields` 4 lines before their initialization → `UnboundLocalError` crashed every sync write. Vault was never written. Deleted the 4 lines; real `photo_update_date` logic at line 1041 (using `should_update_photo`) was untouched and correct.

**Fix 2 — `select person id` → `-1708`**:
AppleScript parsed `select person id abID` as sending `select` to the person object, not as an application command. Fixed to `select {person id abID}` (list form) in both `processProfileReview` (Step 5) and `processTriageAction`.

**Files**: `src/bridge/contact_macos.py`, both `.applescript` sources (v2.4.2), `LSAM Control Center.scpt` recompiled clean.

---
### 2026-03-18 | Control Center v2.4.0 — Review UX Overhaul + Post-Sync Review

**Three issues addressed:**

**Bug: `select person id` silent failure (Triage Review never selected contact)**
- Root cause: `CNContact.identifier()` (ASOC) returns a plain UUID. AppleScript `select person id` requires `UUID:ABPerson` format. The `try/end try` swallowed the error silently.
- Fix: Added `if abID does not contain ":ABPerson" then set abID to abID & ":ABPerson"` in both `processTriageAction` and `processProfileReview`. Python CLI still receives plain UUID (`:ABPerson` stripped via `offset of ":" in pyID`).

**Feature: `processProfileReview` extended action menu**
- Replaced 2-button `display dialog` with 5-item `choose from list` (no button limit).
- Actions: ✅ Validate / 🔁 Sync Now / 🚀 Promote → Priority / ⏭ Skip / 🚪 Back.
- Each action is self-documenting (consequence baked into the list item text).
- "Sync Now" pre-fetches slug from social profile; falls back to URL prompt if absent.
- "Promote" re-selects contact before CLI call to ensure Contacts.app selection is current.
- Handler returns `"BACK"` string — callers check and exit their review loops.
- Profile vault summary (capped at 500 chars) embedded in the `choose from list` prompt — single-dialog UX.

**Feature: Post-Manual-Sync Review (Option A+C)**
- `handleManualSync` now collects `launchedIDs` / `launchedNames` (parallel arrays, `UUID:ABPerson` format via `id of c`).
- At end of sync loop: stores them in `property _pLastSyncedIDs` / `_pLastSyncedNames` (Option C — persistent across dashboard navigation).
- Post-launch offer: `choose from list {"Review now", "Review from dashboard later", "Done"}`.
- "Review now" (Option A): polls `pgrep -f 'pro_sync_agent.py' | wc -l` in 5s intervals with notification updates; times out at 300s; then calls `handlePostSyncReview`.
- New `handlePostSyncReview(idList, nameList)`: same loop structure as `handleProfileReview` but uses caller-supplied lists — no ASOC group scan needed.
- Dashboard: `"📋 0b. Review Last Sync (N)"` menu item dynamically shows count; calls `handlePostSyncReview` with stored lists.

**Files:** `LSAM Control Center UTF8.applescript` + `LSAM Control Center.applescript` (v2.4.0), `LSAM Control Center.scpt` recompiled clean.

---
### 2026-03-18 | pro_sync_agent.py — Double-Prefix Bug Root-Cause Fix (v2.3.4)
- **Symptom**: AppleScript log showed correct URL `https://www.linkedin.com/in/federico-trucco-44246911`, but Chrome navigated to `https://www.linkedin.com/in/linkedin.com/in/federico-trucco-44246911/`. The fix in the AppleScript was masking without curing.
- **Root cause 1** (`|USER:` handler, line ~3757): `existing_url` built as `f"https://www.linkedin.com/in/{handle}/"` without checking if `handle` already contained `linkedin.com/in/`. LSAM bridge historically stored full URL paths in `user name`, so handle was `"linkedin.com/in/slug"` → double prefix on construction.
- **Fix 1**: Added slug normalization before constructing `existing_url` — split on `linkedin.com/in/` and take the tail if present.
- **Root cause 2** (CLI invocation, line ~4546): `args.url` was passed as first positional param (`linkedin_url`), not `manual_url`. Since `manual_url=None`, the `elif existing_url:` branch silently **overwrote** the correctly-passed `--url` CLI arg with the bad `existing_url`.
- **Fix 2**: Changed CLI invocation to `sync_profile(None, n, manual_url=args.url, ...)` so `--url` is always a surgical override immune to contact-record discovery.
- **Files**: `src/agent/pro_sync_agent.py` (2 hunks).

---
### 2026-03-18 | Control Center v2.4.1 — Three Review Loop Fixes

**Fix 1 — Sync Now re-opened Chrome** (`processProfileReview`):
- Root cause: `--mode FULL` in `pro_sync_agent.py` only affects audit logging (line 4469). The gate for Chrome/scraping is `--vault-only` (line 979: `if not self.vault_only: setup_browser()`).
- Fix: "Sync Now" now passes `--vault-only` — agent reads simulation vault entry and applies it to Contacts without re-opening Chrome.

**Fix 2 — Contact selection invisible** (`processProfileReview`):
- Root cause: `activate`+`select` happened BEFORE the dialog, which then grabbed focus, burying the contact. Error was silently swallowed by bare `try/end try`.
- Fix: contact selection moved to after the dialog (Step 5, before action execution). `on error` now logs with error number. Dialog prompt updated with ⌘⇥ hint.

**Fix 3 — Last contact looped back to review list** (`handlePostSyncReview`):
- Root cause: loop rebuilt `menuList` from original unchanged `nameList` every iteration.
- Fix: mutable `remainIDs`/`remainNames`; processed contacts removed after non-Skip/non-Back. Auto-exits when empty. `processProfileReview` returns `"SKIP"` vs `""` vs `"BACK"`.

---
### 2026-03-18 | Control Center v2.3.3 — Zombie Social Profile Fix
- **Bug fixed**: `handleManualSync` was reading `value of sp` (AppleScript dictionary alias for URL) without try/on error. On any contact with a zombie social profile (service name set, URL null → ABPerson `-1728`), this crashed the entire `tell application "Contacts"` block.
- **Root cause**: Federico TRUCCO's contact has a shell LinkedIn social profile created by LSAM bridge with `{service name:"LinkedIn", user name:"handle"}`. The `value` field (URL) was never set at the ABPerson level → `error -1728` on read.
- **Fix**: Read `user name of sp` (handle) with a try/on error guard. If handle starts with "http", use as-is; otherwise construct `https://www.linkedin.com/in/<handle>`. On error (-1728 or other), cURL stays "" and falls to the existing URL prompt dialog.
- **Source damage repaired**: `LSAM Control Center UTF8.applescript` had lost the `on handleManualSync()` declaration (Antigravity/Gemini corruption). Full function restored.
- **Files**: Both `.applescript` sources unified at v2.3.3 (UTF-8). Compiled to `LSAM Control Center.scpt`. `osacompile` clean.

---
### 2026-03-17: Control Center v2.3.2 & Engine Resilience v5.5.1
- **Control Center Fixes**: Restored premium emojis (`↑`, `↓`, `🔁`), optimized group counting with ASOC `NSPredicate` (near-instant menu refresh), and added robust interactive logging.
- **Engine Resilience**: Implemented regex-based JSON repair in `extract_profile` to handle malformed LLM responses.
- **Tiered Discovery**: Added "Compound Surname" splitting in `find_linkedin_profile` (e.g., retrying search for halves of a hyphenated last name if initial 1st-degree search fails).
- **Compilation**: Successfully compiled `LSAM Control Center.scpt`.

---
### 2026-03-17 | Photo Logic Refinement (v5.5) & Control Center v2.3.1
- **Milestone**: **Photo Logic Refinement (v5.5)** complete.
  - Feature: **Resolution Upgrade**: Targeted 2000px resolution in both Sniffer and Surgical extraction logic.
  - Feature: **Age-Based Refresh**: Propose photo updates if the current photo is > 3 years old (threshold: 1095 days).
  - Persistence: `Photo Date` is now extracted from and stored in the `<Linkedin-AI-sync>` block.
  - Logic: Refresh triggered even if resolution is same/slightly lower (min 400x400) to account for photo aging.
  - UI: Enhanced Review Mode dialog with clear "Refresh" vs "Upgrade" signals and age data.
- **Milestone**: **Control Center Surgical Patch (v2.3.1)** complete.
  - Fix: Restored robust **ASOC (AppleScript Objective-C)** infrastructure for fast group scanning.
  - Fix: Resolved `class az17` dereferencing error when accessing contact properties.
  - Feature: **Manual Sync** promoted to index 0 of the main menu.
  - Feature: Selection-based manual sync with batch processing capabilities.
  - Feature: Synchronous/Asynchronous CLI invocation with logging redirected to `logs/manual_sync.log`.
  - Feature: Integrated missing-URL prompting directly in the GUI flow.
- **System**: Verified UTF-8 source compatibility and successful `osacompile` to binary `.scpt`.

---

### 2026-03-16 | Project Rebase, System Hardening & Manual Sync Fix
- **Milestone**: Full Project Rebase to `LSAMC` directory complete.
  - Fix: Rebuilt `venv` in-place to repair broken absolute paths (shebangs) in `pip` and `playwright`.
  - Fix: Implemented aggressive Chrome lock purging (`SingletonLock`, `SingletonSocket`) in `pro_sync_agent.py` to prevent 30s startup hangs.
- **Milestone**: Manual Sync Resilience (v1.6.5/v0.7.1-robust).
  - Feature: Automatic URL decoding to handle double-encoded links from AppleScript/Clipboard.
  - Verified: Successful manual sync of "Célia Amarante" (detected `#lsam-ignore` tag).
- **Design Experience v5**: Photo Logic Refined.
  - Logic: Quality-based upgrades (>20% resolution jump) and age-based refreshes (3-year threshold).
  - Guard: "NOT AVAILABLE" and "LinkedIn Member" name poisoning blocked at Validator and Bridge layers.
- **Deliverables**: Hardened `pro_sync_agent.py` and universal argument parsing in `lsam_control_center.py`.

---


### 2026-03-13 (Session 2) | T3 Fix, Contact Routing, Design Findings

- **Milestone**: T3 photo extraction root cause confirmed and fixed.
  - `re.search(r'\{.*\}')` without `re.DOTALL` failed on multi-line Gemini JSON → `coord_match = None` → silent photo failure.
  - Fix applied (`pro_sync_agent.py ~line 1212`): `re.DOTALL` + markdown fence stripping + `JSONDecodeError` guard. 4/4 tests pass. SYNTAX OK.
  - Monitoring: T3:0 still at session end (Phase 4 active) — next recycle will confirm.

- **Milestone**: Promoted contacts routing corrected.
  - 57/58 PROMOTED → `script-LSAM-Priority` (300 total). 33/33 QUARANTINE → `script-LSAM-LinkedIn to Review`.
  - 1 not found: Christophe Grünthaler — Contact stored as "Christophe NOT AVAILABLE"; manual fix required.
  - Root cause: `apply_step2_results.py` had group-add logic commented out and defaulted to SIMULATION.

- **Engine Progress**: Phase 3 (DAMAGED) complete. Phase 4 (Force-Refresh, 265 contacts) active at ~19:00. 275 successes today.

- **Design Issue F6 — Field Destruction Policy**:
  - Engine currently overwrites existing Contact fields (name, company, job) with LinkedIn null/garbage.
  - Decision: Name should NEVER be overwritten. Company/job: null guard minimum; source (headline vs EXPERIENCE block) TBD.
  - v4.8 B2-FIX curated name guard protects names partially but has gaps (doesn't cover company/job; "NOT AVAILABLE" treated as curated).

- **Control Center** (`LSAM Control Center.applescript` **v2.2.0** ✅ COMPLETE):
    - GUI: `LSAM Control Center.applescript` v2.2.0.
    - Python CLI: `scripts/lsam_control_center.py` v1.4.0 (Universal Flags) ✅.
- **System Environment**: `LSAMC` (Rebased) ✅.
- **Design Issue F7 — Control Center Blocking UX**:
  - Control Center AppleScript blocks macOS Contacts environment while engine runs — no escape dialog.
  - Use case: editing "NOT AVAILABLE" contacts + moving to Priority group requires both steps while engine is NOT blocking.
  - Fix options: background process launch (Option A), separate launcher/status scripts (Option B), pause signal file (Option C).

- **Antigravity Context**:
  - Antigravity reached context limit (drowning). Rebase doc created: `ANTIGRAVITY_REBASE_2026-03-13.md`.
  - Pending Antigravity tasks: (H1) malformed sync block detector + repair, (H2) backup dive for Mutual Connections degree qualifier.

- **Deliverables**: `AUDIT_2026-03-13.md` (v1.2), `PLAN_2026-03-13_ENGINE_RELAUNCH.md` (v1.1, with Next Round Backlog), `ANTIGRAVITY_REBASE_2026-03-13.md`.

---

### 2026-03-13 | Documentation Consolidation & Rescue Audit Launch
- **Incident**: **The "Extra C" Engine Typo**. 
    - **Issue**: Supervisor was manually restarted with `LSAM_ENGINE=PRO` instead of `LSAMC_ENGINE=PRO`.
    - **Consequence**: Environment mismatch caused the supervisor to fall back to `fast_sync_agent.py` for Phase 0. Since `fast_sync_agent.py` incorrectly rejects the `--force` flag (required for Phase 0), the supervisor entered a crash loop.
    - **Fix**: Standardized environment to `LSAMC_ENGINE=PRO`. Verified `pro_sync_agent.py` correctly handles the `--force` flag.
- **Milestone**: Tactical "brain" artifacts migrated to project root for visibility.
- **Milestone**: Identity Rescue Audit reached **94-contact milestone** (37% progress).
- **Deliverables**: 
    - [RESCUE_TASK.md](RESCUE_TASK.md) (Checklist - 94/255)
    - [IDENTITY_FRAGILITY.md](IDENTITY_FRAGILITY.md) (Clinical Report - 100% Symmetry)
    - [RESCUE_PLAN.md](RESCUE_PLAN.md) (Technical Strategy)
- **Status**: 61 promoters reset; 33 contacts moved to `LinkedIn to Review`.

### 2026-03-12 | Phase 5: Backlog Liquidation & Identity Audit
- **Milestone**: "Institutional Fog" cleared (1,113 contacts moved).
- **Incident**: "Chong Tae Kim" Wrong Horse identified (Legacy Sync Block v0.7.1 mismatch).
- **Control Center Status**: [x] Project Bridge COMPLETE (GUI v2.1.0 / CLI v1.3.0).
- **Identity Integrity Launch**: [IDENTITY_FRAGILITY.md](IDENTITY_FRAGILITY.md) + [RESCUE_TASK.md](RESCUE_TASK.md).

---

### 2026-03-11 | The "Slow Horse" Diagnosis
- **Context**: Throughput dropped to 2.7/hr.
- **Decision**: Audited project risk (R1-R4). Raising `MaxFastFailures` to 3 and `StallTimeout` to 1200s for Slow Horse agent.
- **Evidence**: 90% LQ rate detected in photo extraction. LinkedIn DOM drift confirmed.

---

### 2026-03-09 | Incident: MORENO_GUARD
- **Incident**: Accidental deletion of Elisabeth MORENO record during manual script execution.
- **Detailed Report**: See [Incident Report](archive/v4_legacy/INCIDENT_MORENO_20260309.md).
- **Mitigation**: Established v4.9.1 Moreno Rules. Rule 1: `delete person` is forbidden. Rule 3: Backup before write.
- **Code Fix**: Implemented `_assert_safe_script()` in `contact_macos.py`.

---

### Project Genesis (Legacy archive summary)
- **Phase 1-2**: Foundation. AppleScript bridges and basic LinkedIn scraping.
- **Phase 3**: Scaling. Introduction of `supervisor.py` and stealth policies.
- **Phase 4**: Hardening. HEIC optimization and "Slow Horse" recovery.

