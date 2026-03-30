# Report: Mutual Connections Degree Qualifier — Backup Dive
**Version**: 1.0 | **Date**: 2026-03-15 | **Author**: Claude Sonnet 4.6 (Claude Code)
**Status**: ✅ Complete — root cause identified and fixed

---

## 1. Task

Determine whether the "Mutual connections" line in synced contact notes includes a degree qualifier
(`(1st degree)`, `(2nd degree)`, etc.) or only the count.
Assess whether this represents a scraping gap, a write gap, or correct behaviour.

---

## 2. Sample Evidence

Sessions examined: `run_2026-03-13_10-12-45`, `run_2026-03-13_19-42-13`,
`run_2026-03-13_15-33-34`, `run_2026-03-13_10-59-32`, `run_2026-03-13_11-54-41`.

| Contact | connection_degree | Mutual in profile.json | Actual note written |
|:---|:---:|:---|:---|
| Albertine MEUNIER | 1 | `mutual_connections: None` | `Mutual connections : 67` ← **no degree** |
| Benoît MARICHEZ | 1 | — | `Mutual connections : 64` ← **no degree** |
| Christine Landrevot | 1 | — | `Mutual connections : 158` ← **no degree** |
| Lionel BARABAN | 2 | `common_connections_count: 162` | `Mutual connections (2nd degree) : 162` ✅ |
| Frédéric FERRER | 2 | — | `Mutual connections (2nd degree) : 128` ✅ |
| M_Benoît ROUSSET | 2 | `common_connections_count: 7` | `Mutual connections (2nd degree) : 7` ✅ |
| M_Chris_WADE | 3 | `mutual_raw: None` | `No direct connection (3rd degree)` ✅ |

---

## 3. Case Determination

**For 2nd and 3rd degree contacts → Case C**: Degree captured AND written correctly.
The scraping populates `connection_degree`, and `generate_sync_block()` correctly emits the label.

**For 1st degree contacts → 1st-degree gap**: `connection_degree=1` IS captured correctly by
the scraper. But `generate_sync_block()` in `src/models/profile.py` had a conditional:

```python
# BEFORE fix (lines 331, 352):
if self.connection_degree and self.connection_degree > 1:   # ← excludes degree=1
```

This meant `degree_label = ""` for all 1st-degree contacts, producing bare
`Mutual connections : N` with no qualifier. The condition `> 1` was the bug.

This is NOT a scraping gap. The degree is scraped correctly. It was silently dropped at
render time.

---

## 4. Root Cause

`generate_sync_block()` in `src/models/profile.py`, two locations:
- Line 331 (degree_label generation)
- Line 352 (standalone degree fallback line)

Both used `connection_degree > 1` instead of `>= 1`.

---

## 5. Fix Applied — 2026-03-15 (H1)

Changed both occurrences to `>= 1` and added `"st"` suffix for `connection_degree == 1`:

```python
# AFTER fix:
degree_label = ""
if self.connection_degree and self.connection_degree >= 1:
    suffix = "st" if self.connection_degree == 1 else (
        "nd" if self.connection_degree == 2 else (
        "rd" if self.connection_degree == 3 else "th"))
    degree_label = f" ({self.connection_degree}{suffix} degree)"
```

**Unit test results (5/5 pass)**:
| Test case | Output |
|:---|:---|
| 1st degree, mutual=67 | `Mutual connections (1st degree) : 67` ✅ |
| 1st degree, no mutual | `LinkedIn connection (1st degree)` ✅ |
| 2nd degree, mutual=162 | `Mutual connections (2nd degree) : 162` ✅ |
| 3rd degree, no mutual | `No direct connection (3rd degree)` ✅ |
| None degree, mutual=5 | `Mutual connections : 5` ✅ |

---

## 6. Historical Backfill

All contacts synced before this fix have `Mutual connections : N` (no 1st-degree label)
in their notes. The surgical repair script (`src/rescue/surgical_repair.py`) Task B
was already applied on 2026-03-14, restoring correct blocks from session backup profiles.
Task B uses `_build_rescued_block()` which always emits the degree label for all degrees
(including 1st) — it was ahead of this fix.

Future syncs from 2026-03-15 onward will produce correct 1st-degree labels natively.

---

## 7. No Further Action Required

- No scraping repair needed (data was always correct)
- No additional surgical repair needed (Task B already patched historical notes)
- Fix is live in `src/models/profile.py` as of 2026-03-15

---

*REPORT_MUTUAL_CONNECTIONS_DEGREE.md — End*
*Companion: ANTIGRAVITY_REBASE_2026-03-13.md §H2*

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
