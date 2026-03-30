# 📊 LinkedIn Metrics Logic

This document explains how the agent parses, validates, and displays network metrics in the macOS Contact notes.

## 1. Metrics Definitions

### 👥 Connections (Total)
*   **Source**: The precise number under "500+ connections" or the "Contact Info" popup.
*   **Logic**: 
    *   If extracted as "500+", it is displayed as "500+".
    *   If extracted as a specific number (e.g., 266), it is displayed.
    *   **Suppression Rule (v3.5.2)**: If this number is **identical** to the *Mutual Connections* count and is below 500, it is suppressed. This usually indicates that the scraper accidentally grabbed the mutual string instead of the total network size, or that the profile is so isolated that all their connections are mutual (rare, but effectively redundant).

### 🤝 Mutual Connections
*   **Source**: The "Mutual connections" link or the "A, B, and X others" text on the profile.
*   **Logic**:
    *   This is the most strictly validated metric.
    *   It filters out keywords like "Followers" or "Following" to avoid mixing up social graphs.
    *   **History**: If the count changes, the previous value is preserved: `Mutual connections: 12 (was 8)`.

### 📡 Followers
*   **Source**: The "Followers" count, distinct from connections.
*   **Logic**:
    *   Strictly matched to exclude "Following" (people the target follows).
    *   Used as a secondary engagement metric.

---

## 2. Display Hierarchy

The `Sync Block` writes these metrics in a specific order:

1.  **Followers**: Top-level reach.
2.  **Connections**: Total network size (unless suppressed as redundant).
3.  **Mutual Connections**: The intersection with your network (most relevant for networking).
4.  **Mutual Groups**: List of shared LinkedIn groups.
5.  **Connection Degree**: 
    *   **1st**: Suppressed (Implicit if synced).
    *   **2nd/3rd**: Explicitly stated at the bottom.

## 3. Data Hygiene & History

*   **Preservation**: If a sync fails to extract a metric (e.g., UI layout change), the agent **preserves the previous value** from the last successful sync block to prevent data loss.
*   **Zero Handling**: A subtle distinction is made between `None` (failed to fetch) and `0` (confirmed zero). `0` is preserved; `None` falls back to history.
