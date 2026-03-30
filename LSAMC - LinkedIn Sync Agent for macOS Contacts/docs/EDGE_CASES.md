# ⚔️ Edge Cases & Resolutions

## 1. 💀 Deceased Contacts
- **Case**: Contacts marked with `+` or `†`.
- **Issue**: Syncing deceased contacts is unnecessary and potential search for "Name +" fails or returns noise.
- **Resolution**: **Deceased Protocol (v3.1)**. Automated detection in name and suffix fields. Automatic move to `script-deceased` group and immediate sync abort.

## 2. 📸 Photo Downgrades
- **Case**: LinkedIn returns highly compressed HEIC or small WebP.
- **Issue**: File size (e.g., 30KB) might be lower than existing High-Res JPEG (e.g., 100KB), but resolution (800x800) might be superior.
- **Resolution**: **Resolution-First Guard (v3.0.1)**. The bridge now compares `pixelWidth * pixelHeight` instead of raw file size for all photos > 5KB.

## 3. 👻 "Ghost Stats" Carry-over
- **Case**: Scraping failures lead to carrying over old stats in the Sync Block.
- **Issue**: Misleading "Was XX on Date" notes.
- **Resolution**: **Strict Scrape Policy**. Any field not explicitly found on the current page is set to 0/None, killing historical "ghost" data.

## 4. 🔄 Resync Deadlock
- **Case**: Contact flagged for resync but Fast Engine skips it as "already done".
- **Issue**: Manual intervention not applied.
- **Resolution**: **Resync Routing**. Supervisor checks for `.resync` flags and forces the Slow Horse to re-process these specific contacts with maximum surgical accuracy.

## 5. 🚫 Wrong Profile Linking
- **Case**: Fast Engine finds a plausible but incorrect profile (e.g., "Jacqueline PIC").
- **Issue**: Persistent incorrect data in macOS Contacts.
- **Resolution**: **Manual Rejection Workflow**. User flags as "Wrong Profile" in UI; bridge surgically purges all LinkedIn identifiers and adds a `[WRONG PROFILE WARNING]` to the note.

## 6. 🐌 Silent Engine Hangs
- **Case**: Browser-use or Playwright enters an infinite loop or wait.
- **Issue**: No progress for hours.
- **Resolution**: **Heartbeat Monitor**. Supervisor monitors the `session.log`. If it remains unchanged for 300s, it kills the engine and restarts from the last valid offset.
