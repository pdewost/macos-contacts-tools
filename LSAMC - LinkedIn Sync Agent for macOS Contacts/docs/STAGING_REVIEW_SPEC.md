# Staging Review Frontend Specification 🖥️

This document outlines the logic and design principles of the **Staged Manager**, the interactive review component of the LinkedIn Sync Agent.

## 1. Interaction Pipeline
The Staged Manager operates on the "Surgical Mode" principle (v2.7+).

### 1.1 Backlog Scanning
*   **Source**: Scans `logs/sessions/*/backups/` for `profile.json` files.
*   **Exclusion**: Skips folders containing `.applied`, `.flagged`, or `.resync`.
*   **Priority**: Groups are matched against the currently active macOS Contacts selection or a specific Campaign Group.

### 1.2 Selection & Refresh (v1.7.2)
To prevent "Ghosting" (where the Contacts.app UI shows the wrong person):
*   **Reset**: The bridge calls `set selection to {}` before selecting the target contact.
*   **Selection**: Explicitly selects the contact by `ID` to force a visual refresh and scroll-to-visible.

---

## 2. Regression & History Awareness (v2.9.4)
The frontend is designed to be **Regression-Aware** to prevent "data loss" through bad syncs.

### 2.1 Deep History Parsing
When comparing proposed data against native data:
1.  **Extract Current Block**: Parses the structured notes from the macOS Contact.
2.  **Peak Restoration**: If the *current* count is 0, the parser looks for historical markers: `(was X on DATE)`.
3.  **Hormesis Comparison**: It restores the peak value (X) as the "Previous" state to compare against the new extraction.
4.  **Regression Warning**: If Today's extraction < Historical Peak, a `⚠️ REGRESSION` flag is shown.

### 2.2 Toxic Artifact Purge (v1.7.4)
*   **Problem**: Legacy sync versions occasionally injected repetitive "Sync Block" text into notes.
*   **Solution**: The display generator automatically filters out any lines containing "sync block" from the historical "Added" or "Updated" lists, presenting a clean, structured view to the user.

---

## 3. User Decision Logic
Users have three primary actions for every contact:

| Action | Logic |
| :--- | :--- |
| **Apply** | Writes the new data to macOS, creates `.applied` flag, and cleans up artifacts. |
| **Skip** | Moves to the next contact without tagging. Will reappear in the next session. |
| **Skip & Re-Sync** | Creates a `.resync` flag. This signals the **Backend Agent** to prioritize this contact for a fresh extraction, bypassing all "Done" filters. |

---

## 4. Manual Edit Detection
*   **Logic**: Compares the `modification_date` from the macOS Contact with the `DATE` recorded in the sync block.
*   **Action**: If the contact was edited *after* the last sync, the manager displays `ℹ️ MANUAL EDIT DETECTED`, cautioning the user before applying an overwrite.
