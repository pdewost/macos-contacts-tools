# Front End Engine Focus: Staged Manager & Review Center

Since the LinkedIn account is restricted, we are shifting focus to the **Front End Engine**, which includes the tools for manual review and data validation.

## Status of Front End Tools

### 1. Staged Manager (`src/agent/staged_manager_v2.py`)
- **Status**: Operational.
- **Purpose**: Review and apply profiles captured by the backend.
- **Action**: Verify that the 53 successes from today are correctly displayed and ready for review.

### 2. Review Center Launcher (`Launch_Review_Center.applescript`)
- **Status**: Bug suspected.
- **Purpose**: Unified launcher for Audit and Incoming review.
- **Action**: Fix UTF-16 encoding issues and ensure it correctly launches `staged_manager_v2.py`.

### 3. Dashboard (`monitor_overnight.py` / `SYNC_PROGRESS.md`)
- **Status**: HALTED.
- **Purpose**: Monitor engine health.
- **Action**: Maintain the "Halted" state while allowing the user to view historical data.

## Proposed Front-End Work Items

### [ ] Fix Review Center Launcher
- Resolve "missing value" or "choose from list" errors.
- Ensure proper pathing for `python3` and `staged_manager_v2.py`.

### [ ] Enhance Staged Manager UI (CLI)
- Add a "Summary by Day" view to easily see the impact of today's run.
- Improve the "Batch Apply" logic for filtered groups.

### [ ] Document "Front End Engine" Architecture
- Create `docs/FRONT_END_ENGINE.md` to clarify the separation between back-end (sync) and front-end (review).

---
## 🚨 Safety Warning
The front-end tools **must not** attempt to navigate to LinkedIn while the account is restricted. Ensure all "Verify URL" or "Refresh" buttons are disabled or heavily caveated.
