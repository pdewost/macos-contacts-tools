# LSAM Project Compass (v2.0)
## Tier 3 Continuity: Strategic Map & Roadmap
*Last rebased: 2026-03-30*

> [!NOTE]
> Legacy backlog and brief: [Original Project Brief](archive/v4_legacy/PROJECT_BRIEF.md) and [Legacy TODO](archive/v4_legacy/TODO.md).

### 🗺️ The Vision
A zero-friction LinkedIn-to-macOS sync engine that enhances professional relationships without risk of data loss.

### 📍 Current Phase: Phase 5 (Control & Liquidation) — MOSTLY COMPLETE

1. [x] **Priority Pulse**: `LSAM-Queue` group (migrated from `script-LSAM-Priority`).
2. [x] **Control Center**: **COMPLETE — v3.0.0**. AppleScript GUI + CLI v1.5.0 (preview, edit, log-session).
3. [x] **Backlog Ventilation**: Complete. 1,444 contacts analyzed → 1,116 records moved.
4. [x] **System Rebase (LSAMC)**: COMPLETE (2026-03-16). venv repaired, Chrome locks cleared.
5. [x] **v5.0 Sprint 1 — Vault Rebase**: Versioned snapshots (`vault_history.py`), retention prune, structured diff.
6. [x] **v5.0 Sprint 2 — Manual Processing**: Preview + edit subcommands in CLI v1.5.0.
7. [x] **v5.0 Sprint 3 — Group Simplification**: 12 old groups → 6 new `LSAM-*` groups. 2,279 contacts migrated.
8. [x] **v5.0 Sprint 4 — Automated Triggers**: Birthday (T-2 hybrid cache), onboard_unprocessed (6-tier priority), bounce_handler (manual).
9. [x] **v5.0 Sprint 5 — CCC Articulation**: `<!--LSAM:pre_mod:-->` stamp, CCC tag-awareness for `<Linkedin-AI-sync>`.
10. [x] **v5.0 Sprint 6 — Calendar + UX**: Per-contact outcomes in calendar events, manual sync logging.
11. [x] **Daily LaunchAgent**: `com.lsam.daily-sync` at 07:30, birthday trigger wired into supervisor startup.
12. [ ] **Identity Restoration**: Stalled at 94/255 (37%). Lower priority since v5.0. Tracked in [RESCUE_TASK.md](BRAIN/RESCUE_TASK.md).
13. [ ] **Vault Trimmer**: Automating cleanup of legacy profile artifacts.
14. [ ] **Legacy group cleanup**: Old `script-LSAM-*` groups kept as safety net — empty + delete after validation.
15. [ ] **Control Center v3.0 live test**: .scpt compiled, needs user testing (Preview Selected, Review Queue, Start/Stop).

### 🔜 Future roadmap
- **Phase 6: Multi-Engine Diversification**
    - Alternative scrapers (Voyager vs Desktop).
    - Automated handle discovery from resume PDFs.
- **Phase 7: Mobile Bridging**
    - Dashboard accessibility via iOS Shortcuts.

### 🗑️ The "Fog" Target
- Clean up 135+ archived entries with no matching macOS contact.
- Purge 90+ legacy markdown files into `archive/v4_legacy/` after v5.0 stabilization.
- Remove stale `SYNC_PROGRESS.md` dashboard (references old group names, stuck at Phase 1).
