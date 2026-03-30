# Enhanced Staged Manager v3.0 Guide

## Overview
The Enhanced Staged Manager (v3.0) introduces a **Hybrid UI** that combines the speed of AppleScript dialogs with rich, actionable menus. This allows for deep inspection of contacts (Vault, LinkedIn, JSON) without cluttering the main workflow.

## Installation
The v3.0 manager runs side-by-side with the existing v2.7 manager.
*   **Launcher**: `Launch_Staged_Manager_v2.applescript`
*   **Core Script**: `src/agent/staged_manager_v2.py`

## New Features

### 1. The "More Actions" Menu
When reviewing a contact (Ready or Needs Attention), you now see a `[More Actions...]` button. Clicking it reveals:
*   📂 **Open Vault Folder**: Opens the specific contact's folder in Finder.
*   🔗 **Open LinkedIn Profile**: Opens the source profile in your default browser.
*   📝 **View Raw JSON**: Opens the `profile.json` in your default text editor.
*   🚩 **Flag / Report Issue**: Quickly flag a contact as "Wrong Profile", "Not a Person", etc.
*   🗑️ **Discard (False Match)**: Flag as "False Match" and skip.
*   🔄 **Retry / Re-Sync**: Move the contact to Tier 3 for a fresh attempt.
*   🚫 **Stop Session**: Exit safely.



## Usage
1.  Run `Launch_Staged_Manager_v2` from your Script Menu or Editor.
2.  Select "Process Ready" or "Review Needs Attention".
3.  Use `[Apply]` or `[Skip]` for speed.
4.  Use `[More Actions...]` when you need to investigate a discrepancy.
