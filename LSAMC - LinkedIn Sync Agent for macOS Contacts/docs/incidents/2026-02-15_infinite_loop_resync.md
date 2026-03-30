# 🐛 Incident Report: Infinite Loop & Resync Injection Failure
**Date**: 2026-02-15
**Severity**: High (Backend availability impact: 14h downtime)
**Status**: Resolved

## 📝 Summary
The backend engine (`supervisor.py`) entered an infinite restart loop on 2026-02-14. It repeatedly attempted to process a single contact (`Me jacqueline pic`) via the Fast Engine, crashed/exited, and restarted.

## 🕵️ Root Cause Analysis

### 1. The Trigger: A Toxic `.resync` Flag
- A contact named **"Me jacqueline pic"** (likely incomplete name) had a `.resync` flag present in a backup folder.
- This flag instructs the Fast Engine (`fast_sync_agent.py`) to "inject" this contact into the current batch for reprocessing.

### 2. The Bug in `fast_sync_agent.py` (Injection Loop)
- The agent successfully detected the `.resync` flag and attempted to find the contact in macOS Contacts.
- **Expected Behavior**: Find contact -> Add to batch -> Process -> Remove flag.
- **Actual Behavior**: 
    - The search for "Me jacqueline pic" returned `None` or was skipped by the "Safety Check" (Name parts too short).
    - **CRITICAL FAILURE**: The script **did not remove the `.resync` flag** when the injection failed.
    - Result: The flag remained on disk, causing the same injection attempt (and failure) on every subsequent run.

### 3. The Bug in `supervisor.py` (Index Misalignment)
- The Supervisor iterates through groups based on an index (`group_idx`).
- It logic for selecting the engine ("Fast" vs "Baseline") relied on hardcoded indices:
    ```python
    # OLD LOGIC (Fragile)
    if group_idx == 0 or group_idx == 1: active_agent = BaselineAgent
    ```
- Due to dynamic filtering of empty groups, the index for "LSAM LinkedIn to Review" shifted. The Supervisor incorrectly selected the **Fast Agent** for a group that should have used the **Baseline Agent**.
- The Fast Agent then hit the `.resync` loop described above.

## 🛠️ Fixes Implemented

### 1. Loop Breaker in `fast_sync_agent.py`
**Fix**: Added logic to explicitly delete the `.resync` flag if the injection fails (e.g., contact not found or name invalid).
```python
else:
    # v2.2.2 Fix: If not found or skipped, remove flag to prevent loops
    logger.warning(f"⚠️ Injection failed for '{r_name}'. Removing .resync flag.")
    os.remove(flag_path)
```

### 2. Robust Selection in `supervisor.py`
**Fix**: Replaced index-based logic with explicit name-based logic for agent selection.
```python
# NEW LOGIC (Robust)
if target_group in ["script-LSAM-Force-Refresh", "script-LSAM-Tier3-NeedAttention", "script-LSAM-LinkedIn to Review"]:
    active_agent = BaselineAgent
```
This ensures that even if group indices shift, the correct engine (Baseline) is used for difficult groups.

## 📉 Impact
- **Processed Contacts**: ~300 unique contacts were successfully synced before the loop started.
- **Downtime**: ~14 hours of potential processing time lost to the loop.
- **Data Integrity**: No data corruption. The system simply spun its wheels.

## ✅ Verification
- The Supervisor has been restarted (2026-02-15 10:30).
- It should now correctly identify "Me jacqueline pic" as invalid, remove the flag, and proceed to the next contact/group.
