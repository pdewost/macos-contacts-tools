# LinkedIn Data Extraction Strategy Analysis (Jan 28, 2026)

## 1. Surgical Scrape vs. Gemini API

Based on the latest "Steady Push" run (`run_2026-01-28_09-04-02`), we have a clear efficiency comparison:

| Metric | **Surgical Scrape (Local JS)** | **Gemini API (Visual AI)** |
| :--- | :--- | :--- |
| **Availability** | 100% (Local logic) | Limited (Quota: 20-50 calls/day) |
| **Speed** | Instant | 5-15s per call |
| **Success Rate** | High for social metrics (Followers, Mutuals) | High for rich bio/professional data |
| **Bot Detection** | Low profile | Higher profile (Complex interactions) |

### Analysis
*   **Surgical Scrape** is our "Stealth Dash-Cam". It is extremely effective at capturing identity (Name, Headline) and social proof (Follower counts/Mutuals) without using up academic/limited API credits.
*   **Gemini API** is our "High-Res Scanner". It is required for meaningful professional enrichment where HTML obfuscation is extreme.

---

## 2. Refined Approach: Visual OCR Fallback

### The Proposal
Instead of purely relying on DOM selectors, we can utilize **Visual OCR** as a secondary layer when Surgical Scrape fails or for high-fidelity verification.

### Key Refinements (from User Feedback)
*   **Accuracy**: High-contrast text on LinkedIn is usually consistent in position. Banner background images are unlikely to interfere with text extraction from the profile header.
*   **Latency Testing**: Before full implementation, we must compare the local execution time of OCR vs. Gemini API calls on the user's specific hardware.
*   **Contact Info + OCR**: The "Contact Info" lightbox should be opened agentically, and then a snapshot taken for OCR. This allows capturing private data (Phone/Email) that is not visible on the main page.

#### Decision/Recommendation:
> [!IMPORTANT]
> **Sequence**: Surgical Scrape → **Visual OCR (Fallback)** → Gemini API (Last Resort).
> Opening the "Contact Info" box remains essential for high-confidence syncs (phones/emails).

---

## 3. Experience & Education Extraction (Deferred)

### Discussion
While capturing the full professional history is desirable, the current risk level and the complexity of scrolling logic warrant a deferral.

### Alignment with CCC v6
*   **Phase**: Deep extraction of EXPERIENCE and EDUCATION blocks will be deferred to the **Contact Management v6** (CCC v6) phase.
*   **Manual Trigger**: The vision is a user-initiated update from macOS Contacts (via AppleScript) to refresh specific profiles, rather than an automated batch process.

---

## 4. Proposed "Hybrid A/B" architecture for Testing

1.  **Branch A (Current)**: Surgical Scrape → Gemini Fallback.
2.  **Branch B (Hybrid)**: Surgical Scrape → Visual OCR (Header & Contact Box) → Gemini Fallback.
3.  **Metrics to Track**: Success rate per field, total duration (ms), and API cost/quota impact.

---

## 5. Stability & Stealth Hardening (Jan 31, 2026)

Following 24 hours of intensive testing and recovery, the following mechanisms are now **MANDATORY** and implemented in the Tier 3 architecture:

### 🛡️ 5.1 Self-Monitoring & Autonomous Repair
The system is now designed to survive crashes and stalls without human intervention.
*   **External Supervisor (`supervisor.py`)**: A "Let It Crash" manager that wraps the agent process.
    *   **Watchdog**: Monitors the agent's exit code.
    *   **Auto-Repair**: If the agent crashes (Exit != 0), it triggers a `RestartDelay` and relaunches the process.
    *   **Smart Resume**: Scans today's logs (`logs/sessions/run_TODAY_*`) to calculate exactly how many contacts were synced, then restarts with an `offset` to skip processed items.
    *   **Circuit Breaker**: Stops execution after 5 consecutive crashes to prevent infinite loops on hard errors.

### 👻 5.2 Stealth & Identity Safeguards
To prevent pollution of the macOS Contacts database and avoid detection:
*   **Simulation Mode Default**: All launchers (`launch_tier3.py`, `supervisor.py`) default to `--mode SIMULATION` to ensure no changes are written to the database without explicit override.
*   **Identity Pollution Prevention**:
    *   **"Me" Blocker**: Explicit logic to detect if the agent has navigated to the user's own profile ("Philippe Dewost") or generic `/in/me` URLs, immediately aborting extraction to prevent overwriting the user's own contact card.
    *   **Unicode Normalization**: Uses `unicodedata.normalize('NFKC', ...)` to strip invisible characters (like Non-Breaking Spaces) that previously allowed duplicate entries to bypass equality checks.
*   **Randomized Timings**:
    *   **Auth Check**: The 5-minute safety check (`check_auth`) now uses a randomized cache duration (`300s ± 120s`).
    *   **Interaction**: Fixed sleeps are banned; all delays use `random.uniform()`.

### 📂 5.3 Data Hygiene & Archiving
*   **Sync Dashboard History**: A dedicated `logs/monitor_history.csv` records every session run, tracking speed, success rates, and total volume over time.
*   **Sync Block Archiving**: Every sync operation creates a timestamped backup in `logs/sessions/<run_id>/backups/`, preserving the exact state of the `vCard`, `json`, and `txt` data before and after processing.
*   **Session Sanitization**:
    *   **Orphan cleanup**: The Supervisor aggressively kills lingering `Google Chrome` and `Python` processes (`kill_orphans`) before every run.
    *   **Ghost Handling**: Mechanisms to detect and ignore/remove empty session folders to keep the log directory clean.

### 🖥️ 5.4 Independent Monitoring Dashboard
The Dashboard must not depend on the Agent's health.
*   **`monitor_overnight.py`**: A separate process that parses logs in real-time.
*   **Adaptive Frequency**: Updates frequently (5s) during warmup, then slows down (15m) for overnight "Cruising" to save resources.
