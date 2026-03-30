# Operational Safety Guide (LSAMC)

## 🚨 The "Single Supervisor" Rule
The LSAMC system is designed to have **exactly one** supervisor process running at any given time. Running multiple supervisors concurrently leads to:
- **State Jumping**: Multiple processes fight over `logs/.supervisor_state`, causing phases to skip or repeat.
- **Log Corruption**: Concurrent writes to `session.log` make debugging impossible.
- **LinkedIn Rate Limiting**: Multiple agents hitting the same profile session can trigger account flags.

## 🛠 Identifying Process Collision
Symptoms of a collision:
1. `SYNC_PROGRESS.md` shows rapidly flashing values or inconsistent phase titles.
2. `supervisor.log` shows two different phases starting within seconds of each other.
3. AppleScript errors (e.g., "Contacts got an error: Connection is invalid") due to multiple scripts fighting for the UI lock.

## ⚠️ The Risk of `LSAMC_IGNORE_LOCK`
`LSAMC_IGNORE_LOCK=1` is an emergency escape hatch. It bypasses the safety check that prevents the agent from starting if it detects another instance.
- **NEVER** use this in a normal `supervisor.py` run.
- **ONLY** use this for targeted debugging of a single contact while the main sync is paused.

## ☢️ The "Nuclear Option" (Cleanup)
If the system becomes unstable, perform a full reset:
1. Stop all terminal windows running `supervisor.py` or `monitor_overnight.py`.
2. Run the cleanup command:
   ```bash
   pkill -9 -f "[P]ython" ; pkill -9 -f "Google Chrome" ; pkill -9 -f "chromedriver"
   ```
3. Verify `logs/.supervisor_status` is deleted.
4. Restart from a fresh terminal.

## 📉 Known Glitch: The "Double Launch"
If you launch the supervisor while an orphaned `sync_agent.py` is still idling in the background, the supervisor may "adopt" the chaos or launch a second agent atop it. Always run `kill_orphans()` (automatic in supervisor) or the manual nuclear option before a fresh campaign.
