# LSAMC — LinkedIn Sync Agent for macOS Contacts

> High-fidelity synchronizer: LinkedIn professional data + Retina-ready photos (1024px HEIC) → macOS Contacts.

## Overview
LSAMC extracts structured professional data from LinkedIn profiles using AI-powered browser automation and writes it into macOS Contacts via AppleScript. It operates unattended for batch processing of 2,000+ contacts with full stealth management.

## Key Capabilities (v4.9.1)
- **4-Tier extraction**: Surgical > Standard > Profile-only > Fallback
- **High-res photos**: Canvas-based capture bypasses 403 errors, outputs 1024px HEIC
- **Smart filtering**: Pre-scans vault + session history, skips already-synced contacts
- **Sync Block notes**: Non-destructive note enrichment with connection stats, mutual groups, history tracking
- **Moreno Guard**: `_assert_safe_script()` blocks all destructive AppleScript at runtime
- **Priority queue**: `script-LSAM-Priority` group drained first every run for urgent fixes
- **Control Center**: `LSAM Control Center.scpt` GUI — promote/demote contacts from Contacts.app selection
- **Session management**: Supervisor auto-restarts on crashes, enforces daily quotas
- **Maintenance daemon**: Weekly automated pruning of vault binaries and empty sessions

## Quick Start (Robust)
```bash
# 1. First-time Setup
# The launcher script will auto-create the venv and install dependencies.
# Just ensure you have your API key set:
export GEMINI_API_KEY=<your-key>

# 2. Launch System (Auto-healing)
./start_lsam.sh

# 3. Monitor Process
tail -f logs/supervisor_stdout.log
```

## Fault Tolerance & Resilience
- **Auto-Healing Startup**: `start_lsam.sh` automatically detects missing environments or dependencies (`python-dotenv`, `pyobjc`, etc.) and fixes them before launch.
- **Network Awareness**: The Supervisor checks for internet connectivity *before* launching the agent. If offline, it pauses and waits for reconnection, preventing wasted retries.
- **Circuit Breaker**: Stops execution after 20 consecutive crashes to prevent API burn.
- **Silent Fail Protection**: `supervisor.py` monitors the agent's heartbeat (log activity). If the agent freezes for >15 minutes, it is killed and restarted.

## Architecture
```
├── main.py                    # Entry point (single-contact / dev)
├── supervisor.py              # Campaign orchestrator (batch)
├── start_lsam.sh              # 🚀 SAFE LAUNCHER (Use this)
├── monitor_overnight.py       # Live progress dashboard
│
├── src/
│   ├── agent/
│   │   ├── sync_agent.py          # Core sync engine
│   │   ├── staged_manager_v2.py   # Review UI (AppleScript)
│   │   └── fast_sync_agent.py     # Lightweight sync variant
│   ├── bridge/
│   │   ├── contact_macos.py       # macOS Contacts bridge (AppleScript)
│   │   └── image_optim.py         # HEIC conversion & optimization
│   ├── models/
│   │   └── profile.py             # Pydantic model + Sync Block generator
│   └── utils/
│       ├── stealth_manager.py     # Anti-detection timing
│       ├── process_guardian.py    # Chrome process lifecycle
│       ├── network_sniffer.py     # Request interception
│       ├── local_ocr.py           # Apple Vision OCR
│       └── surgical_overrides.py  # Manual URL overrides
│
├── LSAM Control Center.applescript  # 🎛 GUI v2.1.0 — Patterns A–I, triage, manual sync (✅ complete)
├── LSAM Control Center.scpt         # Compiled binary of above
│
├── scripts/
│   ├── lsam_control_center.py         # CLI v1.3.0 — status/list/promote/demote/focus/queue/inspect
│   ├── profile_quality_audit.py       # Audit company-field pollution
│   ├── session_maintenance_daemon.py  # Weekly vault/session pruner
│   ├── vault_retention.py             # Retention policy engine
│   ├── lsam_status_helper.py          # AppleScript ↔ JSON bridge
│   └── com.lsam.maintenance.plist     # launchd schedule
│
├── config/                    # Runtime configuration
├── data/                      # Chrome profiles & agent data
├── logs/                      # Session logs & vault backups
└── tests/                     # Unit tests
```

## Manual Triage: Ambiguity Resolution 
When the agent encounters multiple potential matches for a contact (33% of skipped cases), it aborts extraction to avoid data pollution. These contacts are marked `SKIPPED_AMBIGUOUS`.

**Resolution Workflow (macOS Contacts)**:
1.  Open **Contacts.app** and select group **`script-LSAM-LinkedIn to Review`**.
2.  Check the **Note** field for the `⚠️ LSAM AMBIGUITY` block (lists potential URLs).
3.  **Action**: Copy the correct URL into the **Social Profile** > **LinkedIn** field.
4.  Remove the contact from the "Review" group.
*Next run, the agent will see the explicit URL and skip the ambiguous search.*

## Key Documentation

### Active reference set
| Document | Purpose |
|:--|:--|
| [COMPASS.md](./COMPASS.md) | Strategic roadmap & phase tracker |
| [HANDBOOK.md](./HANDBOOK.md) | Rules of engagement, ops guide, AppleScript gotchas |
| [STATUS.md](./STATUS.md) | Current architecture, constants, operational health |
| [JOURNAL.md](./JOURNAL.md) | Living audit trail — key decisions & incidents |
| [MATCHING_POLICY.md](./MATCHING_POLICY.md) | Contact matching & identity resolution (v5.0) |
| [ANTIGRAVITY.md](./ANTIGRAVITY.md) | LLM behavioral rules + continuity protocol |

### Active working documents (P5)
| Document | Purpose |
|:--|:--|
| [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) | Step-by-step task execution guide (P0–P5) |
| [CONTROL_CENTER_SPEC.md](./CONTROL_CENTER_SPEC.md) | Control Center & housekeeping original spec (F1–F6) |
| [CONTROL_CENTER_AUDIT_2026-03-12.md](./CONTROL_CENTER_AUDIT_2026-03-12.md) | Full technical audit: v1.0.0 + v0.7.4 legacy — fragilities, gold patterns |
| [CONTROL_CENTER_PLAN_2026-03-12.md](./CONTROL_CENTER_PLAN_2026-03-12.md) | v2.1.0 sprint plan (S1–S5) — **all sprints complete**, task table fully ✅ |
| [AUDIT_2026-03-11.md](./AUDIT_2026-03-11.md) | Risk audit + task ledger — moves to archive after P5 |

### Historical archive
| Document | Purpose |
|:--|:--|
| [archive/v4_legacy/HANDOVER_GUIDE.md](./archive/v4_legacy/HANDOVER_GUIDE.md) | Environment setup, benchmark suite, legacy context |
| [archive/v4_legacy/INCIDENT_MORENO_20260309.md](./archive/v4_legacy/INCIDENT_MORENO_20260309.md) | Full post-mortem: contact deletion incident |
| [archive/v4_legacy/LSAMC - LinkedIn Data Structure.md](./archive/v4_legacy/LSAMC%20-%20LinkedIn%20Data%20Structure.md) | Data schema & Sync Block format reference |

## Requirements
- **Python 3.12+**
- **macOS** (Sonoma+ recommended) with Contacts.app
- **Google Chrome** (user profile for session cookies)
- **Gemini API key** (`GEMINI_API_KEY`)
- Grant Terminal/IDE **Accessibility** permissions in System Settings

## License
Private project — not for redistribution.
