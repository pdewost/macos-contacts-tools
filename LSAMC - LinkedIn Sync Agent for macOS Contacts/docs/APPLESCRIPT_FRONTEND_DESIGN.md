# Logiciel de Contrôle LSAM (AppleScript Front-End) - Design Specification

## 1. Overview & Strategy
The **LSAM Control Center** is a native macOS application (AppleScript) designed to provide a high-performance dashboard and control interface for the LinkedIn Sync Agent.

### Core Philosophy: "State vs. Evidence"
To ensure speed and accuracy, we separate the source of truth into two layers:
1.  **State (macOS Contacts)**: The "Live Dashboard" queries the Address Book directly via **AppleScriptObjC (ASOC)**. If a contact has a sync note, it is counted. This reflects the *user's reality*.
2.  **Evidence (Vault)**: When deep investigation is needed (e.g., "Why did this fail?"), the front-end calls a **Python Bridge** to read the complex JSON logs in the `data/vault/` folder.

## 2. Architecture

```mermaid
graph TD
    A[LSAM Control Center.app] -->|ASOC Query| B(macOS Contacts DB)
    A -->|Shell Command| C{Supervisor Process}
    A -->|Python Bridge| D[lsam_status_helper.py]
    D -->|Read| E[Vault (JSON)]
    C -->|Write| B
    C -->|Write| E
```

### Components
1.  **AppleScript App (`LSAM_Control_Center.applescript`)**:
    *   **Dashboard**: Displays real-time counts of Active, Review, and Exempt queues.
    *   **Monitor**: Checks if `supervisor.py` is running (PID check).
    *   **Triage`: Lists specific failure reasons (AMBIGUOUS, EXTRACT_FAIL) by parsing contact Notes.
2.  **Python Bridge (`scripts/lsam_status_helper.py`)** *(Planned v0.6)*:
    *   Accepts commands like `inspect <uuid>` or `exempt <uuid>`.
    *   Reads `data/vault/<uuid>/profile.json`.
    *   Returns formatted text or opens the Vault folder.

## 3. Data Dictionary (State Indicators)

How the AppleScript determines the status of a contact:

| Category | Indicator (Note Field) | Corresponding Group | Action |
| :--- | :--- | :--- | :--- |
| **🟢 Validated** | Starts with `✓ Synced` | *None* | Archived. |
| **🟡 Staged** | Starts with `⏳ Staged` | `script-LSAM-Tier3...` | Validation needed. |
| **🔴 Review** | `⚠ Error` or `? Ambiguous` | `script-LSAM-LinkedIn to Review` | User intervention. |
| **⚪ Exempt** | Any | `script-LSAM-Exempted` | Ignored by backend. |

## 4. Implementation Plan

### v0.5: The "Mission Control" (Implemented Feb 09, 2026)
*   [x] **ASOC Integration**: High-speed fetching of group counts.
*   [x] **Backend Monitor**: Visual PID check (🟢/🔴).
*   [x] **Smart Triage List**: Displays failure tags (`[AMBIGUOUS]`) in the UI.
*   [x] **Supervisor Control**: Start/Stop buttons.

### v0.6: The "Deep Dive" (Values & Vault)
*   [ ] **Python Bridge**: Implement `lsam_status_helper.py`.
*   [ ] **Action: Inspect**: Open the JSON profile for a specific failure.
*   [ ] **Action: Exempt**: Move a contact effectively to the Exempt group and update the Vault.
*   [ ] **Action: Retry**: Clear the error flag and move back to Tier 3.

## 5. Technical Notes
*   **Performance**: ASOC fetching of 5,000+ contacts takes ~1-2 seconds.
*   **Concurrency**: The Dashboard is read-only for the database; it does not block the Python backend writer.
*   **Security**: The app runs locally with user permissions.
