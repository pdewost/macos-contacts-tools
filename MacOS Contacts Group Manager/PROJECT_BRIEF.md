# PROJECT BRIEF: GroupManager (Utility Suite)

## 1. Context & Goals
**GroupManager** is a specialized utility for surgical and batch management of the macOS Contacts database. It provides a central "Dashboard" to overcome native app limitations, focusing on group cleaning, smart filtering, and high-performance contact injection.

## 2. Key Heuristics & Specifics
- **Architecture**: Monolithic AppleScript with extensive ASOC (AppleScriptObjC) optimization for high-performance scanning.
- **Context-Aware Start**: Dynamically switches between Dashboard (no selection) and Surgical Tools (selection detected).
- **Smart Filter Engine**: Uses an internal indexing strategy to find duplicates (fields/note lines), dead contacts (RIP), and LinkedIn artifacts.
- **High-Performance Injection**: Indexes the entire 14k+ contact vault in memory to match name batches with 6 fuzzy strategies.
- **Safety Protocol**: Detailed summary dialogs before/after actions and atomic group membership updates.

## 3. High-Value Handlers (Potential Universal Candidates)
- `handleInjectContacts` (Fuzzy Matching Engine)
- `handleSyncWorkflow` (Smart Group Integrity)
- `findContactsWithDuplicateMeta` (ASOC Multi-Field Scanner)

---
**Tiers & Standards**:
- [Tier 0: Behavioral Guidelines (ANTIGRAVITY.md)](file:///Users/pdewost/Documents/Personnel/Developpement/ANTIGRAVITY.md)
- [Tier 1: Platform Spec (MACOS_AUTOMATION_SPEC.md)](file:///Users/pdewost/Documents/Personnel/Developpement/macOS%20Contacts%20Management/MACOS_AUTOMATION_SPEC.md)
- [Tier 1: Design Spec (DESIGN_UI_SPEC.md)](file:///Users/pdewost/Documents/Personnel/Developpement/02_Design_Web_Ecosystem/DESIGN_UI_SPEC.md)

*Domain: 01_Contact_Management | Tier: 2*
