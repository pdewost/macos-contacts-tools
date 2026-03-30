# Task List — Post-v5.0 Steady State
*Last updated: 2026-03-30 (rebase)*

## Active

- [ ] **CC v3.1.1 — Birthday Group rewrite (BLOCKED: compile error)**
  - `LSAM Control Center UTF8.applescript` at v3.1.1, does NOT compile.
  - Error: `line 1559: Expected class name but found identifier. (-2741)` — date filter loop after Calendar tell block.
  - Bisection incomplete: phases 1–4 compile OK, trigger is in phases 5–10.
  - Strategy: continue bisect → fix keyword conflict → recompile → test dry-run.
  - See JOURNAL.md 2026-03-30 for full diagnosis and AppleScript keyword conflict notes.
  - `.scpt` binary is stuck at v3.1.0 (CNContactStore-based, misses ~40% contacts).

- [ ] **Control Center v3.0/v3.1.0 live test** — test Preview Selected, Review Queue, Start/Stop
- [ ] **Legacy `script-LSAM-*` group cleanup** — empty + delete old groups after 1-2 weeks validation of new LSAM-* taxonomy

## Backlog

- [ ] **27 SUGGEST disambiguation contacts** — Layer B scored (comp < 0.75), manual review via `LSAM-Review` group
- [ ] **8 quarantined contacts** — name corruption, future timestamps, ghost profiles. See `data/reexamine_queue_20260327.json`
- [ ] **Identity Restoration** — stalled at 94/255 (37%). See `BRAIN/RESCUE_TASK.md`
- [ ] **v8.4 diag INFO noise** — consider lowering `[Surgical] v8.4 diag` to DEBUG when role/loc empty
- [ ] **DESIGN_EXPERIENCE_VAULT.md** — Career block feature (Phase P2). Prerequisites: CCC articulation (done), career_normalizer.py (not started)

## Completed (v5.0 — 2026-03-29)

- [x] v5.0 Sprint 1: Vault Rebase (vault_history.py, vault_diff.py)
- [x] v5.0 Sprint 2: Manual Processing (preview, edit CLI)
- [x] v5.0 Sprint 3: Group Simplification (12 → 6 groups, 2,279 migrated)
- [x] v5.0 Sprint 4: Automated Triggers (birthday, onboard, bounce)
- [x] v5.0 Sprint 5: CCC Articulation (pre_mod stamp, tag-awareness)
- [x] v5.0 Sprint 6: Calendar + UX (per-contact outcomes, manual sync logging)
- [x] Control Center v3.0 (AppleScript + CLI v1.5.0)
- [x] Daily LaunchAgent (com.lsam.daily-sync at 07:30)
- [x] Connection degree fix (nameEl parent extraction)
- [x] Ambiguity cleanup Layer A+B+C
