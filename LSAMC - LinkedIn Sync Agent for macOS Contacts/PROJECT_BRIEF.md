# LSAMC — PROJECT_BRIEF
**LinkedIn Sync Agent for macOS Contacts** | v5.0 | Domain: macOS Contacts Management

## Goal
Automate the synchronization of LinkedIn profile data (role, company, headline, experience, education, photo) into macOS Contacts. Operates in two modes: SIMULATION (safe dry-run, default) and FULL (live writes, requires `--live` flag). Manages 800+ contact vault entries with scraping, extraction via LLM (Gemini), and vCard-safe atomic updates.

## Tech Stack
- Python 3 (src/agent/, src/models/, src/contact/)
- Playwright (browser automation for LinkedIn scraping)
- Google Gemini API (LLM profile extraction via langchain)
- AppleScript (macOS Contacts read/write via osascript)
- Supervisor pattern: `supervisor.py` → `src/agent/pro_sync_agent.py`
- Data stores: `data/vault/` (800 profile JSONs), `logs/sessions/` (run backups)

## Domain
macOS Contacts

## Skills Used
- `applescript_bridge` v1.0 — Python executes AppleScript for Contacts read/write
- `identity_resolution` v1.0 — contact name matching logic (LSAMC has its own runner; skill is reference)

## Safety Constraints
- **NEVER use `delete person` AppleScript** (INCIDENT_MORENO_20260309 — causes irreversible data loss)
- **`--live` flag required for FULL mode.** Default is SIMULATION. Supervisor enforces this.
- **CAPTCHA kill: remove `logs/CAPTCHA_KILL` sentinel** before restarting after a CAPTCHA event.
- **Operational window**: Do NOT initiate large sync batches between 22:30 and 02:40 (LaunchAgent collision risk)

## Verification Protocol
- Check supervisor: `bash scripts/check_supervisor.sh`
- View progress: tail `logs/sessions/run_*/` or check `SYNC_PROGRESS.md`
- Verify contact was updated: open macOS Contacts, inspect note block for `=== LinkedIn ===` footer

## Tier References
- Tier 0: `/Users/pdewost/Documents/Personnel/Developpement/ANTIGRAVITY.md`
- Tier 1: `/Users/pdewost/Documents/Personnel/Developpement/MACOS_AUTOMATION_SPEC.md`
- Domain entry: `/Users/pdewost/Documents/Personnel/Developpement/macOS Contacts Management/CLAUDE.md`
- Tactical intelligence: `BRAIN/` (JOURNAL.md, STATUS.md, WALKTHROUGH.md, TASK.md)
