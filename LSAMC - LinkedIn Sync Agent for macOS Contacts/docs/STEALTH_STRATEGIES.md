# 🥷 Stealth Strategy: Enhancement Plan (v1.0)
**Date**: 2026-02-15
**Trigger**: User received a warning from LinkedIn about automated tools.

## 🛑 Current State Assessment
| Component | Current Implementation | Risk Level |
| :--- | :--- | :--- |
| **Browser Fingerprint** | `browser-use` defaults. Extensions disabled. Telemetry disabled. | 🟠 **Medium** (Standard automation fingerprint) |
| **Navigation Pattern** | Direct URL visits (`page.goto(url)`). | 🔴 **High** (Unnatural. Zero discovery flow) |
| **Timing** | Batch processing (Fast bursts). Basic `time.sleep` delays. | 🔴 **High** (Machine-like cadence) |
| **Mouse/Input** | Programmatic clicks. No random jitter. | 🟠 **Medium** (Detectable by behavioral biometrics) |
| **Daily Volume** | Quota managed by `StealthManager` (default 2000/day). | 🔴 **High** (2000 is too high for a personal account) |

---

## 🛡️ Proposed Enhancements (Prioritized)

### 1. 📉 Reduced Volume & "Human" Hours
**Goal**: Mimic a busy power-user, not a data center.
- [ ] **Drop Daily Quota**: Reduce `LINKEDIN_DAILY_QUOTA` from 2000 to **150-300** pages/day.
- [ ] **Working Hours**: Only run between 08:00 and 20:00 local time.
- [ ] **Random Breaks**: Enforce 5-15 minute "coffee breaks" every hour.

### 2. 🖱️ Behavioral Biometrics (The "Ghost in the Shell")
**Goal**: Defeat client-side cursor tracking scripts.
- [ ] **Bezier Curves**: Replace direct mouse jumps with Bezier curve paths for cursor movement.
- [ ] **Overshoot & Correction**: Intentionally miss the button by a few pixels and correct, like a human.
- [ ] **Scroll Reading**: Fast scroll down, slow scroll up (reading behavior) before extraction.
- [ ] **Random Focus**: Randomly click "white space" or highlight text while "reading".

### 3. 🕸️ "Organic" Navigation Flow
**Goal**: Eliminate "Direct Hit" traffic which screams "Scraper".
- [ ] **Referrer Spoofing**: Never go straight to a profile URL.
    - *Plan*: Go to Google -> Search "Name LinkedIn" -> Click Result.
    - *Plan*: Go to "My Network" -> Search Name -> Click Result.
    - *Plan*: Go to Feed -> Scroll -> Paste URL in bar (mimics user pasting link).

### 4. 🎭 Fingerprint Hardening
**Goal**: Look like a standard macOS Chrome user.
- [ ] **CDP Detachment**: Minimize use of Chrome DevTools Protocol. Use pure JavaScript injection for extraction where possible to avoid `Runtime.enable` flags.
- [ ] **Canvas/WebGL Noise**: Add tiny noise to canvas rendering to defeat strict fingerprinting (Anti-Fingerprinting tech).
- [ ] **Consistent User Data**: We already use a persistent profile, which is good. Ensure cookies/local storage are never wiped mid-session.

### 5. 🤖 Separation of Concerns
**Goal**: Isolate high-risk activity.
- [ ] **Tiered Scraping**: 
    - *Tier 1 (Safe)*: Public search results (Google/Bing) - No Login required.
    - *Tier 2 (Risk)*: Login only for 2nd/3rd degree connections.

## 📋 Recommended Immediate Actions (Configuration)

1.  **Halve the Speed**: Increase `RestartDelay` and cooldowns.
2.  **Cut the Quota**: Set `LINKEDIN_DAILY_QUOTA=300`.
3.  **Stop Background Tabs**: Ensure only ONE tab is ever open (already implemented in `sync_agent.py`, verify for `fast_sync_agent.py`).

> **Note**: Automated tools warning is usually triggered by **Volume** (requests/minute) or **Pattern** (going to 500 URLs in a row without touching the feed). Fixing traffic volume is the Single Point of Failure (SPOF) fix.
