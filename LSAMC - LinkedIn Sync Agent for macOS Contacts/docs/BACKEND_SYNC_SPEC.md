# Backend Sync Specification 🔄

## 1. Resumption & Crash Recovery Strategy
The system implements a **"Smart Resume"** architecture to handle interruptions (crashes, reboots, or manual stops) without data loss or redundant processing.

### 1.1 Global Offset Calculation
When `supervisor.py` starts heavily, it calculates the **Global Offset** to determine where to resume in the contact list.

**Formula**:
```python
Global_Offset = Count(Archived_Contacts) + Count(Current_Session_Successes)
```

*   **Archived_Contacts**: Contacts processed in *previous* sessions/days that have been successfully committed to macOS and moved to `logs/archive/applied/`.
*   **Current_Session_Successes**: Contacts processed *today* (in the current `logs/sessions/run_TODAY_...`) that are marked `SUCCESS` in the session log but not yet archived.

### 1.2 Skip Logic
*   **Goal**: Ensure we resume exactly where we left off.
*   **Mechanism**: The agent fetches the full target list (e.g., from a Smart Group or Script) and then **skips** the first `N` items, where `N = Global_Offset`.
*   **Result**: The agent seamlessly continues the batch, treating the multi-session run as a single continuous operation.

### 1.3 Data Integrity & Sorting (CRITICAL)
*   **Requirement**: The Contact List provided by the bridge MUST be **Alphabetically Sorted (A-Z)** before the offset is applied.
*   **Why**: The macOS Address Book does not guarantee stable return order (order may shift based on modification time).
*   **Prevention**: The Agent explicitly calls `.sort(key=lambda x: x['name'])` immediately after fetching the list. This ensures that `Skip N` always skips the *same* `N` individuals, preventing "Groundhog Day" duplication loops.

---

## 2. Connection Degree Handling
The system handles 1st, 2nd, and 3rd-degree connections differently based on available data.

### 2.1 "Connected Since" Date
*   **1st Degree**: The "Connected Since" date is extracted from the "Contact Info" modal on LinkedIn.
    *   **Sync Block**: Appended as `LinkedIn_Connection_Since: YYYY-MM-DD` in the footer.
*   **2nd & 3rd Degree**: These contacts do not have a "Connected Since" date (as they are not connected).
    *   **Sync Block**: The field is **omitted**. The sync block generates without this line.
    *   **Handling**: The system does *not* error out or insert placeholders. It simply skips the data point.

### 2.2 Extraction Depth
*   **1st Degree**: Full surgical scrape (Contact Info, Email, Phone if visible).
*   **2nd/3rd Degree**: Restricted scrape. Email/Phone often hidden (Privacy settings). The agent extracts publicly visible info (Job, Company, Location, Mutual Connections).

---

## 4. Resync Orchestration (v1.7.3 - v1.7.5)
The system supports user-initiated re-syncs through a dedicated flagging mechanism.

### 4.1 Flagging Mechanism
When a user clicks "Skip & Re-Sync" in the Staged Manager:
1.  A `.resync` file is created in the contact's backup directory (e.g., `logs/sessions/*/backups/John_Doe/.resync`).
2.  The contact is **not** marked as `.applied`, allowing the backend to see it again.

### 4.2 Priority Processing (Fast-Track)
The Backend Agent scans for `.resync` files at startup:
*   **Smart Filter Override**: Contacts with a `.resync` flag are removed from the "Done Pool", even if they succeeded earlier in the day.
*   **Priority Queue**: These contacts are moved to the **top of the processing list**, ensuring the user gets their requested data immediately.
*   **Finalization**: Upon a successful NEW sync, the agent automatically deletes all `.resync` flags for that contact to exit the priority loop.

---

## 5. Security & Account Safety (v1.7.7)
Advanced protections to prevent account flags and data pollution.

### 5.1 Self-Identity Protection (Fatal)
*   **Detection**: After any navigation, the agent inspects the page for "Philippe DEWOST".
*   **Protocol**: If detected, the agent assumes navigation has failed or redirected to private profile data. 
*   **Action**: Triggers an **Immediate Circuit Breaker** (Fatal Exit). This forces a hard browser recycle via the Supervisor.

### 5.2 Malicious Profile Quarantine
*   **Triggers**: Repeated Search Failures or Self-Identity Detection.
*   **Action**: The agent automatically moves the contact from the main campaign group to `script-LSAM-Search-Failed`.
*   **Purpose**: Silently "ejects" toxic profiles that would otherwise cause infinite crash loops and stop the system.

### 5.3 URL Sanitization
*   **Engine**: Proactively fixes common encoding artifacts in social URLs.
*   **Example**: Corrects `%3F` (encoded `?`) which causes LinkedIn 404s/Redirects back into a valid `?` parameter.
