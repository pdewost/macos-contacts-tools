# Project History: LSAMC-Fast Engine

## 🕰️ Chronology of Design

### Feb 03, 2026: Design Genesis (v2.0.0-alpha)
- **Initiation**: Following the successful stabilization of the "Slow Horse" baseline (v1.7.7), a need was identified to increase throughput for large batches of trusted 1st-degree connections.
- **Architectural Shift**: Decided to diverge from the "AI-First" approach to a "Heuristic-First" model.
- **Decision Matrix**:
    - **Logic Triage**: Use LLM as an "Exception Handler" rather than a "Primary Scraper."
    - **Photo Throttling**: Recognizing that profile pictures don't change as frequently as career data.
    - **Delay Profiles**: Recognizing that "Search" is more scrutinized than "Direct Link" navigation by LinkedIn.

## 📓 Engineering Notes
- **Reflected on Parallelization**: Consciously rejected parallelization/sibling-instances to avoid the high risk of account association and "device fingerprint" collisions. 
- **Focus on Latency**: Identified that ~60% of current sync time is spent waiting for LLM completion and CDP network stabilization.
- **Proposed "Cool Down"**: Learned from previous bot-detection research that sustained high-speed scraping (even if human-like) often triggers "interstitial" challenges; hence the 20-contact cool down period.
