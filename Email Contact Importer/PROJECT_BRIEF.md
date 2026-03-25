# Email Contact Importer — PROJECT_BRIEF (Tier 2)

## Identity

| Field | Value |
|---|---|
| Script | `Email Contact Importer.applescript` / `.scpt` |
| Version | 1.1.2 |
| Location | `macOS Contacts Management/Email Contact Importer/` |
| Tier refs | ANTIGRAVITY.md (Tier 0) · MACOS_AUTOMATION_SPEC.md (Tier 1) |

## Purpose

Match a list of email addresses (pasted from a mail client or Calendar invite) against macOS Contacts. For each address:

| Classification | Condition | Action |
|---|---|---|
| ✅ FOUND | Email matched in Contacts | Prepend note · add to group |
| 🔎 MATCHED BY NAME | Email absent but full name inferred and uniquely matched | Prepend note · add email to contact · add to group |
| ⚠️ NOT FOUND | No match by email or name | Create new contact · add to group |
| ⚠️ AMBIGUOUS | Multiple contacts share the email | Skip — report only |

## Architecture

- **ASOC** (`AddressBook.framework`) for all lookups — indexed, sub-second at 14,000+ contacts
- **Standard AppleScript** `Contacts.app` for all writes
- **No Python dependency** — self-contained

## Key Handlers

| Handler | Section | Role |
|---|---|---|
| `initAB()` | 1 | Lazy `ABAddressBook` singleton |
| `findByEmail(email)` | 1 | Indexed email search via `ABPerson searchElementForProperty:…comparison:kABEqualCaseInsensitive` |
| `findByName(gn, fn)` | 1 | Compound AND name search — see ASOC constants below |
| `logMsg(level, msg)` | 2 | Script Editor Log pane — levels OK/WARN/ERROR/INFO |
| `parseEmailLine(raw)` | 4 | RFC 2822 · `Name: email` · bare address |
| `inferNameFromEmail(local)` | 4 | `first.last` / Flast (≤9) / firstL / fallback |
| `deriveGroupName(note)` | 5 | `script-{4-non-stopword-tokens}` |
| `prependToNote(uid, email, prefix)` | 6 | Anti-dup note prepend — UID lookup + email fallback |
| `addEmailToContact(uid, email)` | 6 | Anti-dup email addition to existing contact |
| `focusGroupInContacts(name)` | 6 | GUI-scripted Contacts sidebar row selection + fallback |
| `addToGroup(id, name)` | 6 | Add contact by Contacts.app id to named group |

## UX Flow

```
Dialog 1   — Email list (clipboard pre-filled; supports RFC2822, Name:email, bare, ;, ,, \n)
Dialog 2   — One-liner note (optional; blank = match-only, no contact notes written)
Dialog 2b  — Group staging opt-in (editable derived name / Skip Group / Cancel)
Dialog 3   — Summary: FOUND / MATCHED BY NAME / NOT FOUND / AMBIGUOUS  +  Dry Run / Apply
End        — Contacts.app focused, group selected (if applyGroup), result dialog
```

## ASOC Constants — integer literals required

`kABAndSearch` and `kABContainsSubStringCaseInsensitive` **must** be passed as integer literals.
ASOC resolves them as Apple Event property descriptors when passed via `current application's`, causing a type-Q coercion error at runtime.

| Constant | Value | Used in |
|---|---|---|
| `kABEqualCaseInsensitive` | `current application's kABEqualCaseInsensitive` | `findByEmail` (works) |
| `kABContainsSubStringCaseInsensitive` | `8` | `findByName` comparison |
| `kABAndSearch` | `0` | `findByName` conjunction |

## Safety Rules

1. **Anti-duplication (note)** — `prependToNote` checks `currentNote starts with notePrefix` before writing
2. **Anti-duplication (email)** — `addEmailToContact` iterates existing email values before adding
3. **Dry Run default** — default confirm button is always Dry Run, never Apply
4. **No deletions** — all writes are additive (note prepend, email add, group membership)
5. **Idempotent group** — `ensureGroupExists` uses `if not (exists group …)` guard
6. **Flast cap** — `inferNameFromEmail` only applies Flast pattern for `localLen ≤ 9` to avoid splitting merged names like `philippeboue`
7. **Initial exclusion** — name-based fallback search is skipped when either inferred token ends with `.` (initial marker) to avoid false positives

## Name-Search Reversal Logic

When `findByEmail` returns 0 hits and a full name is inferred, `findByName(gn, fn)` is called.
If that also returns 0 hits, `findByName(fn, gn)` is tried (reversed). This handles `Last First` display-name ordering, which is common in calendar invites (`Martin Alice: Alice.Martin@domain`).

## Encoding — Known Issue

Script Editor saves `.applescript` files as **UTF-16 LE with BOM** (`FF FE`). Claude's Write tool re-encodes as UTF-16 LE with BOM. After full file rewrites, apply changes via Python3 keeping UTF-16 encoding, then recompile:

```bash
# Patch in-place (UTF-16 safe)
python3 -c "
src = 'Email Contact Importer.applescript'
text = open(src,'rb').read().decode('utf-16')
text = text.replace('OLD', 'NEW')
open(src,'wb').write(b'\xff\xfe' + text.encode('utf-16-le'))
"
osacompile -o "Email Contact Importer.scpt" "Email Contact Importer.applescript"
```

## Session Resumption Checklist

- [ ] Read ANTIGRAVITY.md (Tier 0)
- [ ] Read MACOS_AUTOMATION_SPEC.md (Tier 1)
- [ ] Check `property scriptVersion` in source
- [ ] `osacompile -o /dev/null "Email Contact Importer.applescript"` — must be clean before any edit
- [ ] After edits: recompile; verify `.scpt` > 100K
- [ ] Smoke test: known email → FOUND; `Last First: First.Last@domain` → MATCHED BY NAME

## Files

| File | Purpose |
|---|---|
| `Email Contact Importer.applescript` | Source (UTF-16 LE with BOM) |
| `Email Contact Importer.scpt` | Compiled binary — distribute this |
| `README.md` | User-facing / GitHub documentation |
| `PROJECT_BRIEF.md` | This file — Tier 2 agent/session doc |
