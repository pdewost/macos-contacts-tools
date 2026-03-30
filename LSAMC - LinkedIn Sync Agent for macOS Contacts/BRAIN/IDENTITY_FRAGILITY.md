# Identity Fragility Analysis: 'Wrong Horse' Mismatch
**Case Study**: Chong Tae Kim (France Telecom R&D Korea)
**Date of Incident**: 2026-03-12 (Phase 5 Launch)

## 📋 The Incident
During the Phase 5 "Clean Backlog" run, the engine synced **Chong Tae Kim**.
- **Expected human**: A 2005 1st-degree connection from France Telecom R&D Korea.
- **Matched human**: A 195k-follower influencer (often not even a 3rd degree connection).

---

## 🔍 Root Cause Diagnosis
1.  **Legacy Anchor (Jan 22)**: The mismatch was established on **Jan 22, 2026** (Run `2026-01-22_07-57-25`). At that time, the engine (v0.7.1) conducted a "Loose Search" for the name.
2.  **Top-Result Pollution**: The influencer profile, having the same name and high relevance in LinkedIn's search algorithm, was picked as the top result.
3.  **Handle Lock-In**: Once the handle `chong-tae-kim-00b35925b` was written to the macOS Contact note, the system became "anchored". All subsequent syncs (including today's) skip searching and blindly trust the stored handle.
4.  **Verification Failure**: The current sync block (`v1.1.0`) reports "Success" because it technically succeeded in scraping the profile at that handle, even if it's the wrong human.

---

## ☣️ The "Invisible Fog" (How many others?)
This incident reveals that while we cleared the **Institutional Fog** (contacts with no sync blocks), we still have **Identity Fog** (contacts with incorrect legacy sync blocks).

### Risk Profile:
- **Clean Backlog (327)**: **CRITICAL RISK**. The Legacy Sweep identified **41 contacts** (12.5% of the backlog) with "Wrong Horse" signatures.
- **Rescue Backlog (248)**: LOW RISK. These had *no* sync blocks, meaning they were never subjected to the legacy "Loose Search" lottery.

---

## 📊 Sweep Results (2026-03-12)
- **Engine Version**: v1.0.0 (Surgical Heuristics)
- **Scope**: `script-LSAM-Force-Refresh` (327 contacts)
- **Flagged**: **41 contacts**.
- **Common Signature**: `Connections : 195,76x` (Shared by 30+ contacts, indicating a specific scraping artifact or influencer profile collision).
- **Mutuals Signature**: Many flagged records had `Mutual connections : 0` despite being 10-year industry contacts.

---

## 🔬 Beyond the Mega-Horse: Verification v2
The "195k signature" is just the tip of the iceberg—it represents a **Scraping Artifact**. There is a second, quieter risk: **Identity Mismatch** (The "Quiet Wrong Horse").

### Rigorous Identification Rules
To move from "Heuristics" to "Verification", we must cross-reference three signals:
1.  **Handle-Name Symmetry**: Does the LinkedIn handle (e.g., `didierbench`) share at least 3 characters of the macOS `lastName` or `firstName`? If not, it's a High-Risk mismatch.
2.  **Legacy Degree Check**: Any contact created by a legacy engine (< v1.0) that is listed as **3rd Degree** or **None** is a likely mismatch for someone you've known since 2005.
3.  **Company Anchor**: Use the **"previously"** block in the sync note. Does it mention the macOS `organization` (e.g., "Orange")? If there is zero overlap between the LinkedIn history and your original contact record, it's likely a Wrong Horse.

---

## 🛡️ Data Safety & Loss Prevention
**Can we lose data in Category A?**
Risk is **LOW** because of the **B2-FIX (Data Parking)** protocol:
- Whenever LSAM updates a Job Title or Organization, it **archives** the previous value into the `previously [Title] at [Company]` block in the notes.
- **Recovery Method**: If we strip a "Wrong Horse" sync block, we simply delete the fraudulent high-reach data. The original user-entered data remains preserved in the "previously" section and the name remains untouched.

---

## 🛠️ Revised Restoration Plan

### Step 1: Surgical Reset (Category B) ✅ COMPLETE
- **Scope**: 36 contacts with valid identities but corrupted stats (195k Mega-Horse / wrong stats).
- **Action**: Wipe sync block while preserving human data and LinkedIn handle.
- **Outcome**: 36 contacts reset; 28 confirmed (100% data preservation); 8 outliers (Didier Bench, etc.) handled via V2 reset due to name discrepancies.

### Step 2: Verification-First (Category A) 🔄 IN PROGRESS (94/255 — 37%)
**Scope**: 255 contacts flagged by Integrity Audit v2 for "Suspicious Degree (Unknown)" or "Asymmetric Handle". Full list: `data/step2_verification_checklist.json`.

**Verification criteria (per contact):**
1. Visit `linkedin.com/in/{handle}`
2. Confirm Connection Degree == **1st**
3. Confirm Name match (First/Last)

**Outcome routing:**
- ✅ **1st Degree + Name Match** → Promote to Category B (Surgical Reset then to Priority queue)
- ⚠️ **Non-1st Degree / Name Mismatch** → Quarantine: apply `⚠️ Wrong Horse?`, move to `LinkedIn to Review`

**Cumulative Progress:**

| Batch | Verified | Promoted (1st °) | Quarantined | Date |
|:---|---:|---:|---:|:---|
| Batch 1 | 7 | 5 | 2 | 2026-03-12 |
| Batch 2 | 15 | 8 | 7 | 2026-03-12 |
| Batch 3 | 20 | 15 | 5 | 2026-03-12 |
| Batch 4 | 22 | 12 | 10 | 2026-03-12 |
| **Batch 5** | **30** | **21** | **9** | 2026-03-13 ✅ |
| **Total** | **94** | **61** | **33** | |
| **Remaining** | **161** | | | |

> [!NOTE]
> Batch 5 verification proof (Recordings):
> - [Part 1 (Indices 65-79)](file:///Users/pdewost/.gemini/antigravity/brain/9c4fb54a-ee94-4922-8fb1-a86d483087f5/degree_verification_batch_5_part_1_1773385000000_1773390738064.webp)
> - [Part 2 (Indices 80-94)](file:///Users/pdewost/.gemini/antigravity/brain/9c4fb54a-ee94-4922-8fb1-a86d483087f5/degree_verification_batch_5_part_2_1773385000000_1773390931799.webp)

💡 **Example**: Gaëlle PICARD-ABEZIS was flagged for an asymmetric handle but confirmed 1st degree → promoted to Category B.

💡 **Automation path**: The 161 remaining candidates can be batch-verified by running `pro_sync_agent.py --mode SIMULATION` on each stored handle — the engine resolves the degree badge without writing to Contacts.app. `legacy_sweep.py` can then re-classify. Manual review only needed for ambiguous cases.

---

## 📅 Chronology of Findings
- **2026-03-12**: Phase 1 (Surgical Reset) completed for 36 Cat B contacts.
- **2026-03-12**: Step 2 Batch 1 verified 7 contacts (5 Promoted, 2 Quarantined).
- **2026-03-12**: Step 2 Batch 2 verified 15 contacts (8 Promoted, 7 Quarantined).
- **2026-03-12**: Step 2 Batch 3 verified 20 contacts (15 Promoted, 5 Quarantined).
- **2026-03-12**: Bulk move of 14 quarantine candidates to `LinkedIn to Review`.
- **2026-03-12**: Surgical Reset triggered for all 30 Batch 1-3 promoters.
- **2026-03-12**: Step 2 Batch 4 verified 22 contacts (12 Promoted, 10 Quarantined).
- **2026-03-13**: Step 2 Batch 5 (30 contacts) completed (21 Promoted, 9 Quarantined).
- **2026-03-13**: Bulk move and Surgical Reset applied to Batch 5 candidates.
