# GroupManager - Project History

## Overview
**Date:** January 26, 2026
**Script Name:** `GroupManager.applescript` (v0.2.4)
**Objective:** Enhance AppleScript-based group management for macOS Contacts by adding surgical contact removal.

## Requirements
- Add a new tool: **Remove selected contact(s) from a selected group**.

## Current Feature Set (v0.2.5)
1.  **List Groups:** Displays all groups (Regular and Smart) alphabetically with member counts.
2.  **Smart Group Protection:** Identifies and protects Smart Groups from modification.
3.  **Group Operations:**
    - **Create Group:** specific workflow to create new groups.
    - **Rename Group:** Rename any regular group.
    - **Delete Group(s):** Delete selected groups (contacts remain in All Contacts).
    - **Empty Group(s):** Remove all contacts from selected groups (groups remain).
4.  **Contact Operations:**
    - **Add Selected Contacts:** Add contacts selected in the app to a chosen group in the script.
    - **Remove Selected Contacts:** Remove contacts selected in the app from the specific group selected in the script (v0.2.4).
    - **Move Contacts:** Move all contacts from one group to another (removing from source).
    - **List Contacts:** View a simple text list of members in selected groups.
5.  **Special Processes:**
    - **RIP Process Deceased:** Automatically identifies and groups deceased contacts (marked with `+` or `†`) into `script-deceased`.
- **Contextual visibility:** This option should ONLY appear when exactly one group is selected in the initial list.
- **Workflow:**
    1. User selects a group in the script.
    2. User selects one or more contacts in the macOS Contacts app.
    3. User chooses "Remove Selected Contacts from Group" in the script's action menu.
    4. Script removes those specific contacts from that group (without deleting the contacts themselves).
- **Safety:** Log the operation and provide a notification of success.
- **Version Control:** Increment script version to v0.2.4.

## Technical Log

### 2026-01-26: v0.2.4 - Surgical Contact Removal
- **UI Logic:** Updated `handleActionMenu` to include "Remove Selected Contacts from Group" when `groupCount` is 1.
- **Handler Implementation:** Created `handleRemoveSelectedContacts(targetInfo)`:
    - Fetches current `selection` from Contacts app.
    - Validates selection isn't empty.
    - Uses `remove (person id pID) from targetGroup` for each selected contact.
    - Includes error handling and atomic `save`.
- **User Feedback:** Added specific logging for removed counts and a macOS notification.
- **Verification:** Verified compilation and logic flow.

### 2026-02-10: v0.2.5 - RIP Feature (Deceased Management)
- **Objective:** Automatically identify and group deceased contacts based on naming conventions.
- **UI Logic:** Added `[ ✝ RIP Process Deceased ]` to the main group list.
- **Handler Implementation:** Created `handleRIP()`:
    - **Group Management:** Checks for existence of "script-deceased" group; creates it if missing.
    - **Identification Logic:** Scans all contacts for:
        - Last Name ends with `+` or `†`
        - First Name ends with `+` or `†`
        - Suffix ends with `+` or `†`
    - **Action:** Adds identified contacts to "script-deceased" group if not already present.
    - **Feedback:** Logs count of added contacts to console and displays notification/dialog.
    - **Fix (Post-Release):** Resolved 'add' command error by using explicit `person id` targeting.

## Planned Feature: Inject & Process Contact List
**Status:** Performance Refactor (Feb 2026)

### Objective
Allow users to inject a list of contact names (e.g. from a text file) and perform bulk actions on them, such as selecting them in the Contacts app or adding them to a specific group.

### Proposed Workflow
1.  **Entry Point:** New main menu item `[ 🔍 Find and Select Contacts ]`.
2.  **Input:** User is prompted to choose input method:
    - **Paste Text:** Paste a list of names directly from the clipboard.
    - **Select File:** Choose a plain text file (`.txt`) containing names (one per line).
3.  **Processing (Optimized):** 
    - Use `CNContactStore` (AppleScriptObjC) to fetch **ALL** contacts in one batch.
    - Build an in-memory map of `Name -> ID`.
    - Match input names against this map (O(1) lookup).
4.  **Reporting - Success:** 
    - Display a scrolling list of all **FOUND** contacts using `choose from list` (read-only verification).
    - User clicks **"Proceed"** or **"Cancel"**.
5.  **Action:** User is prompted to choose an action for the *found* contacts:
    - **Select in Contacts**
    - **Add to Group**
6.  **Reporting - Failure:**
    - After action completes, display a list/log of any names that were **NOT FOUND**.

### 2026-02-13: v0.3.0 - Major Release & UX Polish
- **Objective:** Finalize UX and stability for the "Move & Cleanup" features.
- **Top-Level Feature:** Added `[ 📥 Move Selected Contacts ]` to the main menu for a faster workflow.
- **Stability Fixes:** Resolved the `-1728` selection error by using explicit `tell application "Contacts"` blocks.
- **Unified Versioning:** Incremented version to **v0.3.0** across all script titles, headers, dialogs, and console logs.
- **Internal:** Normalized entire script to UTF-8 to ensure structural integrity and prevent compilation regressions.

### 2026-02-13: v0.3.1 - Patch Release (Critical Fixes)
- **Fix (Critical):** Added missing `save` commands to `performMoveAndCleanup`. The "Move" feature was silently failing because changes were not committed.
- **Performance:** Optimized `handleRIP` to use `CNContactStore` (batch fetch), reducing execution time from minutes to seconds.
- **Fix:** Filtered out the mysterious 'card' group from the main list.
### 2026-02-13: v0.3.2 - UX Polish & Crash Fix
- **Crash Fix:** Explicitly ignored the ghost 'card' group during the cleanup audit, preventing script failure.
- **UX Improvement:** "Move" dialogs now display contact names (e.g., "John Doe and 2 others") instead of just counts.
- **UX Improvement:** All dialog windows now display the version number (**v0.3.2**) in the title bar.
- **Versioning:** Incremented to **v0.3.2**.
### 2026-02-15: v0.3.3 - Canonical Consolidation & UX Patch
- **Objective:** Consolidate competing versions into a single performant, context-aware script and refine surgical UX.
- **Merge:** Combined v0.3.1 (UX/Context/Dashboard) and v0.3.2 (ASOC Performance/Session Detection).
- **Core Features:**
    - Context-Aware Startup (detects selected contacts).
    - Advanced Smart Filters (Duplicates, LinkedIn Connections, Hygiene).
    - Sync Workflow for filters (Strict Sync).
    - ASOC-optimized search for RIP and Contact Injection.
- **Iteration 2 UX Enhancement:** Surgical context dialogs ("Add/Move", "Remove", "Create Group") now display the names of selected contacts if the count is less than 15.
- **Bug Fix:** Blocked the internal "card" group (ghost group) from appearing in contextual cleanup and removal dialogs.
- **Refinement:** Unified all dialog reporting with `generateReport`.
- **Archive:** Moved all competing `GroupManager_v*` files and debug scripts to an `archive` folder.
- **Versioning:** Incremented to **v0.3.3**.

### 2026-02-16: v0.3.6 - Duplicate Field Overhaul
- **ASOC Migration**: Ported `findContactsWithDuplicateFields` to AppleScriptObjC for high performance.
- **Coverage Expansion**: Detection now includes **Social Profiles** and **URL addresses**.
- **Normalization**: Implemented case-insensitive email comparison and digit-only phone normalization.
- **Label Handling**: Maintained value-blind checking to identify duplicate data regardless of label (Home vs Work).
- **Versioning**: Incremented to **v0.3.6**.

### 2026-02-16: v0.3.7 - Refined Logic (Split Duplicates)
- **Split Operations**: Separated "Duplicate Fields" into two distinct filters:
    - **Duplicate Meta**: Scans Emails, Social Profiles, and URLs (case-insensitive).
    - **Duplicate Phones**: Scans Phone Numbers (digit-only normalization).
- **Reasoning**: Addresses the complexity difference between simple string matching (URLs/Emails) and complex phone number formatting.
- **Versioning**: Incremented to **v0.3.7** across script and logs.

### 2026-02-16: v0.3.8 - Duplicate Resolution (Auto-Fix & Logging)
- **Auto-Fix (Exact Matches)**:
    - If a contact has multiple entries with **identical Value** AND **identical Label**, script automatically removes the redundant copies.
    - Applies to Emails, Social Profiles, and URLs.
- **Conflict Logging (Label Mismatch)**:
    - If a contact has multiple entries with **identical Value** but **different Labels** (e.g., `bob@test.com` as "Work" and "Home"):
        - Script does NOT modify the contact.
        - Adds it to the "Duplicate Meta" group for review.
        - Logs the conflict details to `~/Library/Logs/GroupManager/duplicates_report.txt` and reveals the report.
- **Versioning**: Incremented to **v0.3.8**.

### 2026-02-16: v0.3.9 - Resolution Safety & Fixes
- **Safety Dialog**: The "Duplicate Meta" filter now **counts** exact duplicates first and displays a dialog:
    - **Staged Cleanup**: If confirmed, the duplicates are removed.
    - **Generate Review only** (Default): If cancelled/defaulted, no changes are made; duplicates are logged to the report.
- **Robustness**: Replaced legacy `open for access` file writing with `NSString writeToFile` to resolve ASOC context errors.
- **Versioning**: Incremented to **v0.3.9**.

### 2026-02-16: v0.3.10 - Log System Fixes
- **Timestamped Logs**: All duplicate reports now include a timestamp in the filename (e.g., `duplicates_report_20260216-143000.txt`) to prevent previous reports from being overwritten.
- **Reliable Opening**: Replaced the error-prone `tell Finder to open` command (Error -1728) with the robust `do shell script "open ..."` standard.
- **Versioning**: Incremented to **v0.3.10**.

### 2026-02-16: v0.3.11 - Log Visibility Fix
- **Skipped Duplicates**: Fixed a bug where exact duplicates skipped during a "Review Only" run were not being appended to the report log.
- **Versioning**: Incremented to **v0.3.11**.

### 2026-02-16: v0.3.12 - Sync & Context Logic
- **Smart Filter Cleanup**: Modified the `handleSyncWorkflow` to allow processing even when **0 matches** are found. This ensures that if you clean up all contacts in a smart group, running the filter again will correctly empty the group.
- **Empty Group Deletion**: After a sync operation, if the target group becomes empty, the script now prompts: *"Group 'X' is now empty. Delete it?"*.
- **Versioning**: Incremented to **v0.3.12**.

### 2026-02-16: v0.3.13 - UX & Crash Fix
- **Fix Error -1700**: Resolved a crash where `with icon note` failed inside the Contacts execution context due to a naming conflict with the contact 'note' property.
- **Refined 0-Match UX**: If a smart filter returns 0 results but the group is not empty, the script now offers a direct **"Empty and Delete Group"** path with a clear explanation of why the group is obsolete.
- **Unified Branding**: Added the script version to the title of ALL user-facing dialogs for better clarity.
- **Versioning**: Incremented to **v0.3.13**.

### 2026-02-16: v0.3.19 - Performance & UX Polish
- **Progress Bar Integration**: Added real-time progress feedback to "Duplicate Lines in Notes", "LinkedIn Degree", and "No Photo" filters. Users now see "Scanning candidate X of Y" during the surgical verification phase instead of a frozen applet.
- **`trimText` Optimization**: Replaced the legacy `text item delimiters` list-creation method with a high-speed character-scan loop. This massively reduces memory garbage collection overhead during large-scale text block analysis.
- **Versioning**: Incremented to **v0.3.19**.

### 2026-02-16: v0.3.18 - Scalability Engine (14k+)
- **Hybrid Candidate Search**: Re-architected all Note-scanning filters (Duplicate Lines, LinkedIn Degree, No Photo) to use a 2-phase approach:
    1. **ASOC Phase**: Fast-scan of memory-safe fields (URLs, Social Profiles, Job Titles) to identify "LinkedIn Candidates".
    2. **Bridge Phase**: Surgical verification of Notes ONLY for identified candidates.
- **Fixed Note Scoping**: Restored "Duplicate Lines in Notes" accuracy based on v0.3.9 specialized script results.
- **Compiler Optimization**: Pruned project changelog literals in the script to resolve `Internal table overflow (-2707)` caused by script complexity.
- **UX**: Harmonized "No matches found" dialog and fixed formatting glitches.
- **Versioning**: Incremented to **v0.3.18**.

### 2026-02-16: v0.3.17 - Reliability Fix & UX
- **ASOC Note Restriction Fix**: Reverted filters that scan the `note` field (Duplicate Note Lines, LinkedIn Degree, No Photo) to use the Contacts scripting bridge. On modern macOS, `CNContactStore` (ASOC) is prohibited from reading notes without a special app entitlement, which caused these filters to find 0 matches.
- **Bulk Scripting Performance**: Maintained performance by using AppleScript's bulk property fetch (`{id, note} of every person`) which is significantly faster than looping.
- **UX Improvement**: Updated the "No matching contacts found" dialog to clearly state which smart filter was run, providing better feedback during activity.
- **Versioning**: Incremented to **v0.3.17**.

### 2026-02-16: v0.3.16 - Performance Overhaul
- **Note Line Optimization**: Rewrote "Duplicate Lines in Notes" using ASOC (`CNContactStore`). Performance improved from taking minutes (one-by-one Contacts app queries) to a few seconds (bulk fetch + in-memory analysis).
- **Phone Normalization**: Moved duplicate phone detection to ASOC and replaced the slow `do shell script` normalization with high-performance in-memory regex.
- **LinkedIn Degree Optimization**: Switched LinkedIn degree filters to ASOC bulk fetching of `note` and `job title` properties.
- **Unmodified Contacts**: Migrated the "Unmodified > 2 Years" filter to ASOC for consistency and stability in large databases.
- **No-Photo Filter**: Optimized the "No Photo + LinkedIn" filter to use `imageDataAvailable` (a lightweight boolean fetch) instead of downloading full images to check for existence.
- **UX Alignment**: Harmonized all group names to match menu items exactly, ensuring that "Empty and Delete" cleanup flow works reliably across all smart filters.
- **Versioning**: Incremented to **v0.3.16**.

### 2026-02-16: v0.3.15 - Bug Fix & Duplicate Logic
- **Restored Missing Handlers**: Fixed a critical crash by restoring batch operation handlers (Delete, Empty, Move, Rename) that were lost in a previous merge.
- **Improved Duplicate Logic**: Updated the "Duplicate Meta" filter to include *all* detected duplicates in the sync group, not just those with label conflicts. This ensures a consistent review process for name-matched individuals.
- **Log Formatting**: Added proper spacing and newlines to the conflict reports for better readability.
- **Versioning**: Incremented to **v0.3.15**.

### 2026-02-16: v0.3.14 - Smart Filter Alignment
- **Name Standardisation**: Aligned all internal `groupName` returns with the actual menu items. Specifically, "Duplicate Meta" now maps to the group *"script - smart - Duplicate Fields (Emails, Social, URLs)"*. This ensures the v0.3.13 cleanup logic can find and manage the existing groups correctly.
- **Improved Logging**: Added specific console logging at the start of any sync workflow to aid in transparency and debugging.
- **Versioning**: Incremented to **v0.3.14**.
