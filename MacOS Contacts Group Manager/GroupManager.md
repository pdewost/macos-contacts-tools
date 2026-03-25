# Group Manager

**Version:** 0.3.3 (2026-02-15)
**Platform:** macOS 10.11+ (Contacts.app)

## Overview
Group Manager is a robust AppleScript designed to work around the limitations and bugs of the macOS Contacts group management interface. It provides a central "Dashboard" for complex operations and context-aware tools for surgical management of selected contacts.

## Core Features

### 1. Context-Aware Startup
The script automatically adapts based on your current activity:
- **With Selection**: If you have contacts selected in the Contacts app, Group Manager offers immediate surgical actions:
    - **Add/Move to Group**: Precise transfer with automated cleanup from former groups.
    - **Remove from Group**: Surgical extraction from a specific group.
    - **Create Group from Selection**: Instantly turn a selection into a new group.
- **No Selection (Dashboard)**: Presents the main control panel:
    - **Manage Specific Group**: Batch Rename, Delete, Empty, or Backup existing groups.
    - **Smart Filters**: Identify contacts by criteria (Duplicates, LinkedIn, etc.) and sync them to groups.
    - **Inject Contact List**: High-performance matching of names from clipboard/file.

### 2. Advanced Smart Filters & Sync
Found in the Dashboard, these filters use highly optimized **ASOC (AppleScriptObjC)** scanning:
- **Duplicate Fields**: Scans for internal duplicates (multiple identical emails/phones on one card).
- **Duplicate Note Lines**: Finds contacts with redundant lines in their notes.
- **LinkedIn Connections**: Detects 1st and 2nd degree connections.
- **Hygiene**: Finds unmodified contacts (> 2 years) and Deceased (RIP) contacts (marked with `+` or `†`).
- **Sync Workflow**: Results are strictly synced to `script - smart - [Filter]` groups.

### 3. Move & Cleanup Intelligence
When using **Add/Move to Group**, the script:
1. Adds contacts to the target.
2. Identifies all other regular groups those contacts currently belong to.
3. Prompts you to select which former groups to remove them from, ensuring a clean move.

### 4. High-Performance Injection
The **Inject Contact List** feature indices your entire address book in memory to match names against a list (clipboard or file) using 6 strategies:
- Exact, Case-Insensitive, Reversed ("Last First" vs "First Last"), Accent-Folded ("é" vs "e"), and combinations thereof.

### 5. Surgical Name Previews
When fewer than 15 contacts are selected, the surgical context menus ("Add/Move", "Remove", "Create Group") automatically list the specific names of the contacts to be processed, providing an extra layer of verification before action.

## Roadmap (Planned)
- [ ] **v0.3.4 (UX Improvement)**: Alphabetical sorting and single-contact selection focus for migrations.
- [x] **v0.3.6 (Duplicate Field Overhaul)**: ASOC-optimized duplicate detection including Social Profiles, URLs, and label conflict analysis.
- [x] **v0.3.7 (Refined Logic)**: Split duplicate detection into "Phones" (normalized) and "Meta" (Emails/Social/URLs) for better usability.
- [x] **v0.3.8 (Duplicate Resolution)**: Implemented "Auto-Fix" for exact duplicates (Same Value + Label) and conflict logging for label mismatches.
- [x] **v0.3.9 (Safety Patch)**: Added "Staged Cleanup" confirmation dialog and robust file writing to prevent ASOC errors.
- [x] **v0.3.10 (Log Fixes)**: Resolved Finder errors when opening reports and implemented timestamped log filenames to prevent data overwrites.
- [x] **v0.3.11 (Log Visibility)**: Fixed issue where "Skipped Exact Duplicates" were not appearing in the report when "Review Only" was selected.
- [x] **v0.3.12 (Sync & Context)**: Updated Smart Filters to allow syncing even when 0 matches are found (to clear groups) and added a prompt to delete empty groups after sync.
- [x] **v0.3.13 (UX & Crash Fix)**: Resolved Error -1700 (Contact 'note' conflict) in dialogs and implemented a specialized "Empty and Delete Group" path for obsolete smart groups.
- [x] **v0.3.15 (Bug Fix)**: Restored missing batch operation handlers and improved duplicate reporting to include all matches.
- [x] **v0.3.16 (Performance Boost)**: Full ASOC optimization for all Smart Filters (Note Lines, Phones, LinkedIn, Unmodified). Optimized No-Photo detection.
- [x] **v0.3.17 (Reliability Fix)**: Reverted Note-based filters to Scripting Bridge bulk-fetch due to macOS `CNContactStore` note field restrictions. Added context to empty-result dialogs.
- [x] **v0.3.20**: Enhanced surgical removal with contact counts and automated empty group deletion prompts.
- [x] **v0.3.21 (LinkedIn Overhaul)**: Unified LinkedIn degree classification using LSAM note blocks (Rules A-B-C). Replaced individual degree filters with a single tri-state sync.
- [x] **LinkedIn Social Profile Migration**: High-performance detection of LinkedIn handles stored in URL fields, with automated migration to Social Profiles and subsequent URL cleanup.
- [ ] **Cross-Contact Deduplication**: High-performance detection of potential duplicates across different accounts/containers using the "Shared Identifier" engine.
- [ ] **Atomic Fusion & Association**: Safety-first merging (Fusion) and linking (Association) of cross-contact matches with automated VCF and Note backups.

## Usage Patterns
- **Manual Hygiene:** Launch from Dashboard -> Smart Filters -> Duplicate Fields -> Sync.
- **Surgical Move:** Select contacts in Contacts -> Launch Group Manager -> Add/Move to Group.
- **Bulk Import:** Launch from Dashboard -> Inject Contact List -> Paste names.

## Reporting
All major actions conclude with a **Detailed Summary Dialog** listing:
- Total contacts processed.
- Specific names (if < 15 contacts).
- Explicit ✅ Added and ❌ Removed status per group.
