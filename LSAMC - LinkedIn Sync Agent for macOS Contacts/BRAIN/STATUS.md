# LSAM Status — 2026-03-29

## Current Version
**AppleScript**: v3.0.0 (Control Center UTF8 — simplified 7-item menu, Preview/Edit, LSAM-* groups)
**Engine**: pro_sync_agent.py (v5.0 vault history + degree fix via nameEl parent, v8.7 exp noise filters, v8.5 pre-scroll evaluate + nameEl anchor, --force-photo)
**Bridge**: contact_macos.py (v5.0 last_mod_before stamp + pre-mod for CCC, v4.9.3 semantic dedup, v4.9.2 MORENO_GUARD, v2.4.16 photo staleness)
**Profile model**: profile.py (v5.4 get_clean_role richness-aware, force_photo field, v2.4.15 Updated (date) sliding window)
**Control Center CLI**: lsam_control_center.py v1.5.0 (preview + edit + log-session commands, vault diff integration)
**Vault History**: vault_history.py v1.0 (versioned snapshots, retention prune, structured diff)
**Supervisor**: supervisor.py (v5.0 new GroupQueue, birthday trigger at startup, enriched calendar events)
**MBP Dev Monitor**: paia_control_center.py (v3.0 osascript CC launch, start_lsam.sh, detect pro_sync_agent)
**LaunchAgent**: com.lsam.daily-sync — every day 07:30 (supervisor via start_lsam.sh --pro)
**Migration tools**: migrate_groups_hybrid.applescript (ASOC read + AS batch write, 18 min for 2279 contacts)

---

## Test Contact
**Guillaume BELIN** — `BD98EAA4-3F06-4C20-A9FE-4D6D07477CE1:ABPerson`
LinkedIn: `https://www.linkedin.com/in/g-belin/`

**Vault state** (last written 2026-03-25 by v8.7 SIMULATION run):
- `current_role`: "substans.ai Founder | Digital Transformation & AI | Best of Consulting, Power of AI | 25+ Years Leadership | Sciences Po" ✅
- `experience`: 3 entries — exp[0]: title='Founder & CEO', co='substans.ai' ✅ exp[1]: 'Membre du comité stratégique' ✅ exp[2]: 'Noèse' ✅ (all real entries, noise filtered by v8.7)
- `location`: "Meudon, Île-de-France, France" ✅
- `followers_count`: 2515 ✅
- `connections_count`: 500 ✅
- `common_connections_count`: 128 ✅
- `linkedin_url`: https://www.linkedin.com/in/g-belin/ ✅
- `photo_url`: captured ✅

**Sync block in contact** (written 2026-03-25 by Sync Now / vault-only):
- `Updated (2026-03-25) : Job Title` ✅
- `Updated (2026-03-24) : Photo` carry-forward ✅
- Followers/Connections/Mutual ✅
- Pre-write backup saved to session backups (MORENO_GUARD satisfied) ✅

---

## What's Fixed This Session

| # | Fix | File | Status |
|---|-----|------|--------|
| 1 | `_run_applescript` error logging restored | `contact_macos.py:125` | ✅ Done |
| 2 | `update_contact` result logged at main call site | `pro_sync_agent.py:~4595` | ✅ Done |
| 3 | "Updated:" replace-not-accumulate | `profile.py` `generate_sync_block` | ✅ Done |
| 4 | Photo quality — byte-size comparison removed | `contact_macos.py:~994` | ✅ Done |
| 5 | Photo Date — suppress when same as sync date | `profile.py` `generate_sync_block` | ✅ Done |
| 6 | v6.5 re-nav guard: pre-sleep + retry | `pro_sync_agent.py:~1562` | ✅ Done |
| 7 | v8.2 scroll: wait for h1 before scrolling + longer pauses | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done |
| 8 | **v8.3 headline**: parent + grandparent sibling walk (LinkedIn 2024+ layout) | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done |
| 9 | **v8.3 experience**: `ul li` fallback in all 3 strategies (direct-child combinator too strict) | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done |
| 10 | **v8.3 location**: h1-relative top-card walk + `·` exclusion on keyword heuristic | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done |
| 11 | **v5.4 `get_clean_role`**: first-segment extraction, `_BARE_GENERIC` set, richness-aware preference | `profile.py` `get_clean_role()` | ✅ Done |
| 12 | **v2.4.16 Part B**: `--force-photo` CLI flag, `force_photo` field on profile | `pro_sync_agent.py`, `profile.py`, `contact_macos.py` | ✅ Done |
| 13 | **v2.4.16 Part A**: contact modification-date year fallback for staleness when no Photo Date | `contact_macos.py` | ✅ Done |
| 14 | **inspect crash**: JSON mode exit 0 + NullHandler logging in `lsam_control_center.py` | `scripts/lsam_control_center.py` v1.4.1 | ✅ Done — verified |
| 15 | **photo JS SyntaxError**: hoist `const noSigUrl` outside block scope in `_download_photo` | `pro_sync_agent.py` `_download_photo` | ✅ Done |
| 16 | **v8.4 DOM diagnostics**: pre-scroll snapshot (`h1_count`, `scaffold_main`, `url`), post-scroll snap, inline `_dbg_*` fields, role/loc INFO log when empty | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done |
| 17 | **v8.5 nameEl anchor**: `document.title`-based name extraction; leaf-element DOM walk to find nameEl; grandparent panel children walk for headline + location | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done — confirmed BELIN ✅ |
| 18 | **v8.5 pre/post-scroll split**: main evaluate runs BEFORE scroll (top-card data); separate post-scroll evaluate for experience only; no scroll-back-to-top | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done |
| 19 | **v8.5 location pipe-filter**: added `!t.includes('\|')` guard — headlines use `\|` separators, genuine locations never do | `pro_sync_agent.py` JS in `_surgical_local_scrape` | ✅ Done — confirmed BELIN ✅ |
| 20 | **v8.6 text-based experience**: `h2/div` whose `innerText === "experience"`; parse `section.innerText` blocks; `hasMidDot` filter skips detail/company sub-lines | `pro_sync_agent.py` `_surgical_local_scrape` | ✅ Done — confirmed BELIN exp[0] ✅ |
| 21 | **Experience field name bug**: `company_name=` → `company=` in `Experience(...)` constructor (pydantic field is `company`, not `company_name`) | `pro_sync_agent.py` experience mapper | ✅ Done — was causing silent ValidationError |
| 22 | **JS regex in non-raw string**: `.replace(/\n/g, '\|')` used actual newlines; fixed to `.replace(/\\n/g, '\|')` in `_scroll_snap` helper | `pro_sync_agent.py` | ✅ Done |
| 23 | **SVGAnimatedString crash**: `nameEl.className.substring` TypeError on SVG elements; fixed to `typeof el.className === 'string' ? el.className : String(el.className.baseVal \|\| '')` | `pro_sync_agent.py` JS in `_surgical_local_scrape` | ✅ Done |
| 24 | **v8.7 exp noise filters**: 3 JS guards in v8.6 text parser — `titleLine.length > 90` (description paragraphs), `> 3 commas + no pipe` (keyword lists), `/\+\d+ skills?/i` (LinkedIn compact skills summary) | `pro_sync_agent.py` JS in post-scroll evaluate | ✅ Done — BELIN exp[1]/exp[2] now real roles |
| 25 | **v4.9.2 MORENO_GUARD**: pass `session_backup_dir=self.backup_dir` in main `update_contact` call — pre-write JSON backup now created on every sync (full and vault-only) | `pro_sync_agent.py` `_finalize_sync` | ✅ Done — log confirms `Pre-write backup saved` |

---

## Pending / Needs Test

| Priority | Item | Notes |
|----------|------|-------|
| ✅ DONE | **Layer A: Ambiguity note cleanup** — 74/74 contacts cleaned, 107,170 bytes saved, 77 duplicate blocks removed, 19 resolved stripped. | `src/tools/cleanup_ambiguity.py` — LIVE 2026-03-26. Backups: `logs/sessions/2026-03-26_17-34-55/ambiguity_cleanup/` |
| ✅ DONE | **Layer C: Fix `prepend_to_note` dedup** — v4.9.3 semantic dedup: `contains` check for AMBIGUITY/No Profile/disappeared markers | `contact_macos.py` `prepend_to_note()` |
| ✅ DONE | **Layer B: Auto-disambiguator** — 55 unresolved scored. 1 AUTO_RESOLVE (James INGHAM, comp=0.92), 27 SUGGEST, 27 MANUAL_ONLY. | `src/tools/disambiguate.py` — LIVE 2026-03-26. Backups: `logs/sessions/2026-03-26_17-56-32/disambiguation/` |
| ✅ DONE | **LSAM v5.0 Sprint 1: Vault Rebase** — `vault_history.py` + `vault_diff.py` + engine wired. Retention prune tested. | 2026-03-29 |
| ✅ DONE | **LSAM v5.0 Sprint 3: Group Simplification** — `migrate_groups.py` created. DAMAGED audit: 1 valid, 113 broken, 733 no_vault. Supervisor GroupQueue updated. | 2026-03-29 |
| ✅ DONE | **LSAM v5.0 Sprint 2: Manual Processing** — `preview` + `edit` subcommands in `lsam_control_center.py` v1.5.0. Field overrides with MORENO_GUARD backup. | 2026-03-29 |
| ✅ DONE | **LSAM v5.0 Sprint 4: Automated Triggers** — `birthday_trigger.py` (hybrid cache), `onboard_unprocessed.py` (6-tier priority), `bounce_handler.py` (manual mode) | 2026-03-29 |
| ✅ DONE | **LSAM v5.0 Sprint 5: CCC Articulation** — `<!--LSAM:pre_mod:-->` stamp in `contact_macos.py`. CCC `processNoteContentV3()` tag-awareness for `<Linkedin-AI-sync>` and `<Linkedin-Career>` blocks. | 2026-03-29 |
| ✅ DONE | **LSAM v5.0 Sprint 6: Calendar + UX** — `_collect_session_summary()` in supervisor, enriched `_cal_complete(summary_notes=...)` with per-contact outcomes | 2026-03-29 |
| ✅ DONE | **Control Center v3.0** — 7-item menu, preview flow (contact selected + diff dialog), edit overrides, calendar logging for manual syncs | 2026-03-29 |
| ✅ DONE | **Group migration** — 2,279 contacts migrated via hybrid ASOC/AS. 12 old groups → 6 new LSAM-* groups. Old groups kept as safety net. | 2026-03-29 |
| ✅ DONE | **Connection degree fix** — nameEl parent text extraction for LinkedIn 2024+ React UI. Eva Casado verified: `Mutual connections (2nd degree) : 2` | 2026-03-29 |
| ✅ DONE | **Manual sync → full component activation** — `log-session` CLI, menu app detects agent, start_lsam.sh for menu app launch | 2026-03-29 |
| ✅ DONE | **Daily LaunchAgent** — `com.lsam.daily-sync` at 07:30, birthday trigger wired into supervisor startup | 2026-03-29 |
| ✅ DONE | **MBP Dev Monitor fixes** — osascript CC launch, detect pro_sync_agent, use start_lsam.sh | 2026-03-29 |
| 🟡 MED | **Control Center v3.0 live test** — .scpt compiled, needs user testing (Preview Selected, Review Queue, Start/Stop) | Ready to test |
| 🟡 MED | **Birthday cache** — rebuilding in background (fixed: 250-chunk + 600s timeout + skip-on-fail) | In progress |
| 🟡 MED | **Old `script-LSAM-*` groups cleanup** — kept as safety net; empty + delete after 1-2 weeks of validation | Deferred intentionally |
| 🟢 LOW | **27 SUGGEST disambiguation contacts** — Layer B scored but not auto-resolved (comp < 0.75). Manual review via Review Queue. | LSAM-Review group |
| 🟢 LOW | **v8.4 diag INFO noise** — `[Surgical] v8.4 diag` fires at INFO when role or loc is empty for non-BELIN contacts | Consider lowering to DEBUG |
| ⚪ DEFERRED | **Part A modification-date test** — no eligible candidate | Will self-verify in production |
| ⚪ QUARANTINE | **8 contacts from 2026-03-27 session** — name corruption, future timestamps, ghost profiles | `data/reexamine_queue_20260327.json` |

### Confirmed ✅ (this session, 2026-03-25)
| Item | Signal | Run |
|------|--------|-----|
| Sync Now after good vault | `Updated (2026-03-25) : Job Title` in contact note | log line 3808 |
| inspect from Control Center | Dialog returned clean JSON, no AS error | user-verified |
| `--force-photo` Part B | `v2.4.16 Part B: force_photo flag set — treating photo as stale` | log line 3853 |
| Photo not downgraded | `Photo update skipped … same resolution, not stale` | log line 3906 |
| Photo Date carry-forward | `Updated (2026-03-24) : Photo` preserved in 2026-03-25 sync | log line 3786 |
| Photo JS SyntaxError absent | No `SyntaxError: Unexpected token 'if'` in session log | full log scan |
| Experience noise fixed (v8.7) | BELIN exp[1]='Membre du comité stratégique', exp[2]='Noèse' | vault 2026-03-25 |
| MORENO_GUARD satisfied (v4.9.2) | `Pre-write backup saved: ...BD98EAA4...-before.json` | log line ~3920 |

---

## Known Outstanding Issues

### ~~Surgical scrape still unconfirmed for v6.5 / v8.2~~ — RESOLVED (2026-03-25)
v8.3 selectors were superseded and made irrelevant by the v8.5 root-cause fix. The real issue was that LinkedIn 2024+ React hydration replaces `<h1>` with a `<div id="root">` structure — the h1 briefly appears during SSR load (which is why `_wait_for_dom_selector("h1")` returned True), then disappears after React mounts. v8.5 nameEl anchor + document.title extraction bypasses this entirely.

**Confirmed working** (2026-03-25 run, PID 91179):
```
[Surgical] v8.5: Post-scroll experience: 3 entries.
v5.4: Using headline primary 'substans.ai Founder' (trimmed from full headline).
Surgical Local Scrape successful for Guillaume BELIN (Role='substans.ai Founder | ...', Co='substans.ai')
```

### JS SyntaxError in photo download code — RESOLVED (2026-03-25, fix #15)
`const noSigUrl` was hoisted to the top of the `for` loop body. The SyntaxError path is eliminated.

### ~~Experience entries exp[1] / exp[2] contain description/skills noise~~ — RESOLVED (2026-03-25, fix #24)
v8.7 adds three JS guards in the text-based parser: `titleLine.length > 90` removes description paragraphs, `> 3 commas + no pipe` removes keyword lists, `/\+\d+ skills?/i` removes LinkedIn compact skills summary lines (e.g. "Entrepreneuriat, Intelligence artificielle (IA) and +15 skills"). After two-pass validation, BELIN vault now contains 3 clean real entries: Founder & CEO / substans.ai, Membre du comité stratégique, Noèse.

---

## Architecture Notes

### Photo pipeline
1. LinkedIn serves JPEG at ~400×400 or ~800×800
2. Python downloads raw JPEG → `backups/.../contact-linkedin-raw.jpg`
3. `image_optim` converts to HEIC → `backups/.../contact-linkedin.heic`
4. Vault stores the HEIC → `data/vault/<UUID>:ABPerson/linkedin.heic`
5. `update_contact` writes HEIC to Contacts: `set image of p to (read POSIX file ... as data)`
6. **Photo quality decision is resolution-only** (pixel count). Byte size comparison removed because HEIC is always smaller than JPEG at equal quality — cross-format comparison is meaningless.

### Surgical scrape evaluate split (v8.5)
- **Pre-scroll evaluate**: runs BEFORE any scrolling — captures top-card data (name via document.title + nameEl anchor, headline via panel children walk, location, stats). This is the ONLY place top-card data is reliable; scrolling may unmount the top card in React.
- **Post-scroll evaluate**: runs AFTER `scrollTo(0.4 * height)` + `scrollTo(height)` — captures experience section only. No scroll-back-to-top (returning to top can destroy lazy-loaded sections).
- **LinkedIn 2024+ DOM**: No `<h1>` after React hydration. No `.scaffold-layout__main`. Profile name in a `<div>` (empty class), not `<h1>`. All CSS classes are hashed. Only stable signals: `document.title`, `<div id="root">`, and `innerText` of DOM elements.

### Sync block "Updated :" semantics (v2.4.15)
- REPLACED each sync run with current run's changes only
- If current run has no changes: carry forward the LAST "Updated :" line
- Photo Date line: only shown when photo was updated on a DIFFERENT day than current sync
