# Project Management: LSAMC-Fast Engine

## 🎯 Primary Objective
Deliver a secondary synchronization engine that maximizes throughput for 1st-degree connections and trusted URLs, reducing total campaign duration from weeks to days.

## 🛠️ Implementation Requirements

### R1: Separate Execution Path
- **Binary**: `src/agent/fast_sync_agent.py`
- **Log Root**: `logs/fast_sessions/`
- **Configuration**: Independent `--fast-threshold` and `--delay-profile` arguments.

### R2: Heuristic Scraper Upgrade
- Enhance the `SurgicalScraper` (JS) to return a confidence boolean.
- Implement strictly deterministic field anchors for:
  - `mutual_count` (Regex for digits only)
  - `follower_count` (Handle 'k' and 'm' multipliers)
  - `high_fidelity_name` (Exact match against Target Name)

### R3: Vault Integration
- Implement `VaultConnector` to query `photo_meta.json` before initiating capture sequences.

## 📅 Development Roadmap

### Phase 1: The "Smart Sorter" (Analysis Only)
- [ ] Create `fast_sync_agent.py` skeleton.
- [ ] Implement `check_confidence()` logic on top of existing scraper.
- [ ] Implement `Vault` freshness check.

### Phase 2: Dynamic Throttle
- [ ] Implement the context-aware delay timer logic.
- [ ] Implement the "Cool Down" burst protection.

### Phase 3: Validation (Dry Run)
- [ ] Run a 10-contact batch in simulation mode.
- [ ] Compare "Fast" vs "Baseline" data quality for the same 10 people.

---

## 🛡️ Risk Assessment
| Risk | Mitigation |
| :--- | :--- |
| **Detection of high-speed browsing** | Strict "Burst Protection" and randomized context-aware delays (DDT). |
| **Data Quality degradation** | Force LLM fallback if any core field fails the JS-regex sanity check. |
| **Account Warming** | Recommended for use only after the account has been "warmed up" by the baseline agent. |
