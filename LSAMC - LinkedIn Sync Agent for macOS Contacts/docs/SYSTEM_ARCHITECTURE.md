# 🏗️ LSAMC System Architecture (v3.0)

## 📡 Core Engines

### 1. Fast Engine (⚡ `fast_sync_agent.py`)
- **Philosophy**: "Trust but Verify".
- **Strategy**: Zero-LLM Fast Path (Triage) for high-confidence matches.
- **Features**:
  - **SASA**: Snapshot-Aware Architecture (Skip redundant syncs).
  - **DDT**: Dynamic Delay Throttle (Context-aware pacing).
  - **Surgical Search**: Specialized LinkedIn selectors prioritizing 1st-degree connections.
- **Downshift**: Crashes or repeated search failures trigger a supervisor-led downshift to the Slow Horse.

### 2. Slow Horse (🐎 `sync_agent.py`)
- **Philosophy**: "Maximum Accuracy".
- **Strategy**: Surgical scraping with interactive fallbacks.
- **Features**:
  - **Multi-Tier Photo Extraction**: (CDP Traffic -> Interactivity -> Canvas Capture).
  - **Local OCR**: Apple Vision API for extracting data from uncopyable elements.
  - **Robust Parsing**: Advanced regex for multi-language mutual connections and connections count.

## 🛡️ Monitoring & Lifecycle (`supervisor.py`)
- **Architect Mode**: Manages sequential group queues (Tiers).
- **Let-It-Crash**: Automated restarts with exponential backoff and circuit breakers.
- **Heartbeat Monitor**: Stall detection via log modification tracking (300s timeout).
- **Engine Selection**: Logic to switch between Fast and Slow engines based on performance/failures.

## 🌉 Bridge Layer (`contact_macos.py`)
- **Unified Interface**: Abstracted macOS Contacts access (Simulation vs. Full mode).
- **Photo Guard**: v3.0 Resolution-First quality protection (Resolves HEIC compression edge cases).
- **Sync Block**: Intelligent note management (Prevents duplication, manages history).

## 🗄️ History & Session Management
- **Logs**: Session-based logging (`logs/sessions`, `logs/fast_sessions`).
- **Archive**: Final applied states stored for smart skipping (`logs/archive/applied`).
- **Value Filter**: Qualification logic to flag low-value updates (missing photo/role/summary).

## 🎯 Accuracy & Performance Metrics (v3.0)
- **Speed**: Fast Engine (~12-15s) vs. Slow Horse (~45-90s).
- **Success Rate**: Target > 90% in Hybrid mode.
- **Stability**: Heartbeat recovery ensures overnight runs complete despite LinkedIn DOM changes or network blips.
