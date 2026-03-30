# LSAM Project Status (v2.0)
## Tier 2 Continuity: Architecture & Operational Readiness
*Last rebased: 2026-03-30*

> [!NOTE]
> Tactical daily operations and "brain" logs are hosted in the [BRAIN/](BRAIN/) directory.
> Deep dive into data structures: [Data Structure Spec](archive/v4_legacy/LSAMC%20-%20LinkedIn%20Data%20Structure.md).
> macOS Automation logic: [Automation Spec](MACOS_AUTOMATION_SPEC.md) *(redirect → workspace master)*.


### 🏗️ Current Architecture
- **Engine**: `src/agent/pro_sync_agent.py` v2.5.4 (Active when `LSAMC_ENGINE=PRO`). Surgical scrape v8.7 (nameEl anchor, pre/post-scroll split, exp noise filters).
- **Orchestrator**: `supervisor.py` v5.0 — handles batching, stealth delays, crash recovery, GroupQueue (new LSAM-* groups), birthday trigger at startup, enriched calendar events.
- **Bridges**:
    - `src/bridge/contact_macos.py` v5.0: Surgical AppleScript interface to macOS Contacts. MORENO_GUARD v4.9.2, semantic dedup v4.9.3, `last_mod_before` stamp, `pre_mod` for CCC articulation.
    - `src/bridge/image_optim.py`: HEIC/PIL photo optimization (1024px target).
- **Control Center**: AppleScript v3.0.0 (`LSAM Control Center UTF8.applescript`) — simplified 7-item menu, Preview/Edit flow, LSAM-* group counts.
- **Control Center CLI**: `scripts/lsam_control_center.py` v1.5.0 — preview, edit, log-session, inspect, profile, promote, demote, queue, list.
- **Profile Model**: `src/models/profile.py` v5.6 — `LinkedInProfile` (Pydantic), `get_clean_role()` richness-aware, name poisoning guards, `force_photo` field.
- **Vault History**: `src/utils/vault_history.py` v1.0 — versioned snapshots, retention prune, structured diff.
- **Identity Integrity**:
    - [IDENTITY_FRAGILITY.md](BRAIN/IDENTITY_FRAGILITY.md): Clinical diagnosis of sync integrity.
    - [RESCUE_TASK.md](BRAIN/RESCUE_TASK.md): Verification checklist (94/255 complete — stalled, lower priority since v5.0).
- **History & Plans**:
    - [PLAN_2026-03-29_LSAM_V5_REDESIGN.md](PLAN_2026-03-29_LSAM_V5_REDESIGN.md): v5.0 design — all 6 sprints COMPLETE.
    - [JOURNAL.md](BRAIN/JOURNAL.md): Chronological incident and milestone log.
    - [WALKTHROUGH.md](BRAIN/WALKTHROUGH.md): Proof of work for identity restoration.

- **Data**: `data/vault/` stores canonical profile JSONs, images, and `history/` versioned snapshots (v5.0).
- **Logging**: `logs/sessions/run_YYYY-MM-DD_HH-MM-SS/session.log`.
- **LaunchAgent**: `com.lsam.daily-sync` — every day 07:30, birthday trigger + LSAM-Queue drain via `start_lsam.sh --pro`.
- **MBP Dev Monitor**: `paia_control_center.py` v3.0 — osascript CC launch, detects `pro_sync_agent`, uses `start_lsam.sh`.

### 🚦 Operational Health
- **Sync Status**: ⏸️ Idle (v5.0 sprints complete, daily LaunchAgent active at 07:30).
- **Performance**: 2.7 - 5.0 contacts/hr (Slow Horse mode / Stealth enforced).
- **Groups (v5.0 taxonomy — 6 groups)**:
    - **LSAM-Queue**: Pending automated processing (birthday, bounced, promoted, unprocessed).
    - **LSAM-Review**: Needs manual triage/disambiguation before sync.
    - **LSAM-Golden**: Successfully synced, vault current, no issues.
    - **LSAM-Damaged**: Confirmed data corruption, parked until manual fix.
    - **LSAM-Exempted**: User explicitly excluded from all LSAM processing.
    - **LSAM-Birthday**: Contacts queued by birthday trigger (auto-populated, auto-drained).
    - *(Legacy `script-LSAM-*` groups kept as safety net — pending cleanup after 1-2 weeks validation.)*

### 🛡️ Guards & Constants (lsam_config.json)
- `MaxFastFailures`: 3 (allows 2 transient hits).
- `StallTimeout`: 1200s (Slow Horse safe).
- `BATCH_RECYCLE_LIMIT`: 12 (Chrome stability).
- `MorenoGuard`: ACTIVE (blocks `delete person`).
- `vault.retention_keep_n_sessions`: 3 (history snapshots).
