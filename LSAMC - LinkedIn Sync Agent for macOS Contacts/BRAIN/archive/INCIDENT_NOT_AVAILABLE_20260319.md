# INCIDENT — Last Name Poisoning: "NOT AVAILABLE"
**Date**: 2026-03-19
**Resolved**: 2026-03-20 00:10
**Contacts affected**: 52 repaired · 12 already self-corrected · 64 total damaged
**Session backup**: `logs/sessions/fix_2026-03-19_22-10-33/backups/`

---

## Root Cause

LSAM batch runs on **2026-03-08** and **2026-03-13** — before the v5.5 Name Poisoning Guard existed (introduced 2026-03-16) — wrote `"NOT AVAILABLE"` directly into the `last_name` field of macOS Contacts.

The write path in `contact_macos.py` (`else` branch, non-curated contacts) constructed:
```python
ucase_lname = safe_lname.upper()   # "NOT AVAILABLE"
name_script = f'set last name of p to "{ucase_lname}"'
```
No runtime check existed at that point to block placeholder strings at the bridge level.

---

## Investigation

Tool: `scripts/recover_not_available.py`
- Scanned **4 128 VCF backups** across **1 118 unique contact UIDs**
- Matched each damaged UID (`N:NOT AVAILABLE;FirstName`) against earlier session backups where the same contact had a clean name
- **100% recovery rate** — all 64 found in earlier backups, none required LinkedIn lookup

---

## Repair Applied (2026-03-19 22:10)

Tool: `scripts/apply_not_available_fix.py --live`
Method: **surgical** — `tell application "Contacts" / set last name of p to "LastName" / save`
Per-contact pre-fix backup written to `fix_2026-03-19_22-10-33/` before each write.
Result: **52 applied · 0 errors · 12 skipped (already correct)**

### Contacts repaired (sorted by last name)

| First Name | Last Name Restored | Source session |
|---|---|---|
| Lukas | Achermann | run_2026-03-08_06-32-44 |
| Kokou | AGBO-BLOUA | run_2026-03-08_06-05-54 |
| Jean-Luc | ALEXANDRE | run_2026-03-08_05-19-11 |
| Francois | ARLABOSSE | run_2026-03-13_12-18-18 |
| Guillaume | Bodiou | run_2026-01-30_14-54-03 |
| Hélène | BONNET | run_2026-01-17_00-59-55 |
| Jimmy | BRAUN | run_2026-03-08_05-34-28 |
| Gregory | BRENIG | run_2026-03-08_03-41-08 |
| Jean | Brisson | run_2026-01-17_00-59-55 |
| Eric | CHANIOT | run_2026-03-13_12-07-28 |
| Achour Maurad | CHEURF | run_2026-03-08_06-32-44 |
| Jalil | Chikhi | run_2026-03-08_04-51-54 |
| Fabrice | DAGO | run_2026-03-13_12-07-28 |
| Jean-Philippe | Demaël | run_2026-01-17_00-59-55 |
| Gaspard | DEMUR | run_2026-03-07_23-32-58 |
| Guillaume | Deschamps | run_2026-01-17_00-59-55 |
| Didier | Dillard | run_2026-03-07_21-29-37 |
| Denis | DOVGOPOLIY | run_2026-03-13_12-02-07 |
| Jean-Louis | DUPONT | run_2026-03-08_05-05-15 |
| Guy-Laurent | EPSTEIN | run_2026-03-08_03-54-30 |
| Ludovic | Fauvet | run_2026-03-08_06-32-44 |
| Frédéric | FERRER | run_2026-03-07_23-32-58 |
| Christine | Fetro | run_2026-03-07_20-05-08 |
| Jacques | Fouché | run_2026-03-08_04-38-43 |
| Éric | FREYSSINET | run_2026-03-08_03-54-30 |
| Cyprien | GODARD | run_2026-03-13_11-59-33 |
| Christine | Guillen | run_2026-03-07_20-19-40 |
| Chris | HARRISON | run_2026-03-07_21-43-45 |
| Dirk | Hoke | run_2026-03-07_21-29-37 |
| Jérôme | Introvigne | run_2026-01-22_07-57-25 |
| Arnaud | JACOLIN | run_2026-03-13_20-06-15 |
| Alain | JUILLET | run_2026-03-08_06-46-02 |
| Dominique | LACASSAGNE | (self-corrected) |
| Isidro | LASO BALLESTEROS | run_2026-03-08_04-38-43 |
| David | Leborgne | run_2026-01-27_18-01-29 |
| Christophe | LERIBAULT | run_2026-03-07_20-31-20 |
| Luc | MAHOUX-NAKAMURA | (self-corrected) |
| Fabrice | Marsella | run_2026-03-07_22-43-57 |
| Maximilian | MARTIN | run_2026-03-07_22-16-04 |
| Elisabeth | Melin | (self-corrected) |
| Emmanuel | NORMANT | run_2026-03-07_22-30-56 |
| Khalid | Oulahal | run_2026-03-08_06-05-54 |
| Joëlle | Passelègue | (self-corrected) |
| Johannes | Pfister | run_2026-01-24_11-57-40 |
| Alexis | POKROVSKY | run_2026-03-08_07-46-15 |
| Bruno | POMART | (self-corrected) |
| Christophe | Renaud | run_2026-03-07_20-31-20 |
| Gilbert | Reveillon | run_2026-01-24_11-57-40 |
| Jean-Emmanuel | Rodocanachi | run_2026-03-08_05-05-15 |
| Franck | ROGEZ | (self-corrected) |
| Jérémie | ROSSELLI | (self-corrected) |
| Didier | SANZ | run_2026-03-13_12-02-07 |
| Karim | SELOUANE | run_2026-01-22_07-57-25 |
| Gilyoung | Song | run_2026-03-07_23-46-39 |
| Harald | STIEBER | run_2026-03-07_22-16-04 |
| David | SUGDEN | (self-corrected) |
| Frank | SUPPLISSON | (self-corrected) |
| Frédéric | TARDY | (self-corrected) |
| Hubert | Tondeur | run_2026-03-08_04-25-36 |
| Frank | UHLAND | run_2026-01-26_12-14-18 |
| Greg | VANCLIEF | run_2026-03-08_03-41-08 |
| Elena | VASSILIEVA | run_2026-03-07_22-16-04 |
| Fayçal | DOUHANE | (self-corrected) |

---

## Prevention — v5.6 Double Guard

### Layer 1 — `src/models/profile.py` v5.6
Added `model_config = ConfigDict(validate_assignment=True)`.
Without this, post-construction `profile.last_name = "NOT AVAILABLE"` bypassed the `@field_validator` entirely. With `validate_assignment=True`, the field validator fires on every assignment throughout the object's lifetime.

### Layer 2 — `src/bridge/contact_macos.py` v5.6 Bridge Guard
Added explicit `_BRIDGE_BLOCK` check immediately before the AppleScript `set last name of p to` write. Even if both the Pydantic guard and the `validate_assignment` flag are somehow circumvented, the bridge refuses to write any placeholder string. Also blocks writing an empty string (which would silently wipe an existing last name).

```python
_BRIDGE_BLOCK = {
    "NOT AVAILABLE", "INFORMATION NOT AVAILABLE", "NO DATA AVAILABLE", ...
}
if not ucase_lname or ucase_lname in _BRIDGE_BLOCK:
    logger.warning(f"v5.6 Bridge Guard: Blocking '{ucase_lname}' ...")
    # suppresses last name write; first/middle still proceed if valid
```

Defence-in-depth: **Pydantic field validator → validate_assignment → Bridge Guard → AppleScript write**.

---

*Incident closed. See JOURNAL.md for v2.4.9 entry.*
