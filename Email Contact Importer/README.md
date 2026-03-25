# Email Contact Importer

Standalone macOS AppleScript + ASOC utility that matches a list of email addresses — pasted from a mail client or Calendar invite — against the macOS Contacts database. For each address it can prepend a timestamped note, add a new email address to an existing contact found by name, create missing contacts, and stage everyone in a named group for downstream LinkedIn enrichment ([LSAMC](../LSAMC%20-%20LinkedIn%20Sync%20Agent%20for%20macOS%20Contacts/)).

No Python. No shell wrapper. No external dependencies.

---

## Requirements

| Requirement | Detail |
|---|---|
| macOS | 12 Monterey or later |
| Contacts.app | Populated address book |
| Accessibility | Script Editor / Script Runner needs Accessibility permission (for GUI-scripted sidebar selection in Contacts.app) |

---

## Installation

Copy `Email Contact Importer.scpt` anywhere convenient — e.g. `~/Library/Scripts/` — then open with Script Editor and click **Run**, or launch directly from the Finder.

To recompile from source:
```bash
osacompile -o "Email Contact Importer.scpt" "Email Contact Importer.applescript"
```

---

## Usage

### Dialog 1 — Email list

Paste your list. The clipboard is pre-loaded. All of the following formats are supported:

| Format | Example |
|---|---|
| Bare address | `alice@example.com` |
| RFC 2822 | `Alice Martin <alice@example.com>` |
| Calendar invite | `Martin Alice: Alice.Martin@example.com` |
| Semicolon-separated | `a@x.com;b@y.com` |
| Comma-separated | `a@x.com, b@y.com` |
| Newline-separated | one address per line |

### Dialog 2 — One-liner note (optional)

Enter a short note to prepend to all contacts (e.g. `UEFA meeting NYON 19 march 2026`).
Leave blank for **match-only mode** — contacts are looked up but no contact notes are modified.

### Dialog 2b — Group staging (optional)

Choose whether to stage all contacts in a named group for LSAMC enrichment.
The name is auto-derived from your note and is fully editable. Click **Skip Group** to skip.

Group naming algorithm:
first 4 non-stopword tokens from the note → Title-Cased → hyphen-joined → prefixed with `script-`

```
"UEFA meeting NYON 19 march 2026"     →  script-UEFA-Meeting-NYON-19
"Attended Steering Committee Q1 2026" →  script-Attended-Steering-Committee-Q1
(no note)                             →  script-email-import
```

### Dialog 3 — Summary & confirm

Review the classification before anything is written:

| Label | Meaning | Action on Apply |
|---|---|---|
| ✅ FOUND | Matched by email address | Prepend note · add to group |
| 🔎 MATCHED BY NAME | Email not stored but contact found by inferred name | Prepend note · add new email · add to group |
| ⚠️ NOT FOUND | No match by email or name | Create new contact · add to group |
| ⚠️ AMBIGUOUS | Multiple contacts share this email | Skipped — manual review needed |

Click **🔍 Dry Run** (default) to preview all changes without writing anything, or **✅ Apply** to proceed.

---

## Name inference

When a bare email address is provided with no display name, the local part is analysed:

| Pattern | Example | Result | Tag |
|---|---|---|---|
| `first.last` | `alice.martin@x.com` | Alice / Martin | *verify name order* |
| `Flast` (≤ 9 chars) | `amartin@x.com` | A. / Martin | *verify first name* |
| `firstL` | `aliceM@x.com` | Alice / M. | *verify last name* |
| other / too long | `info@x.com`, `philippeboue@x.com` | *(no name — email only)* | |

When a name can be inferred (full first + last, no initials), the script attempts a **name-based fallback lookup** using a compound `AND` search in AddressBook.framework. If exactly one contact matches, it is classified as MATCHED BY NAME and the new email address is added to their existing card. Both `First Last` and `Last First` orderings are tried automatically.

---

## Performance

All lookups use `AddressBook.framework` (ASOC) indexed search — no AppleScript `whose` loops. Sub-second over 14,000+ contacts.

---

## Safety

| Guard | Detail |
|---|---|
| Anti-duplication (note) | `prependToNote` checks that the note doesn't already start with the prefix before writing |
| Anti-duplication (email) | `addEmailToContact` checks existing email values before adding |
| Dry Run default | The default confirm button is always Dry Run, never Apply |
| No deletions | All writes are additive — note prepend, email add, group membership |
| Idempotent group | `ensureGroupExists` uses `if not (exists group …)` guard; re-runs are safe |
| Re-run safe | Running twice with the same note on the same contacts is a no-op |

---

## Changelog

| Version | Date | Change |
|---|---|---|
| **1.1.2** | 2026-03-24 | Group creation made optional via Dialog 2b (editable name, Skip button) |
| 1.1.1 | 2026-03-24 | Fix `Last First: email` parsing; reversed name-search fallback for Last-First display names |
| 1.1.0 | 2026-03-24 | Name-based fallback lookup; `addEmailToContact` adds new address to existing contact |
| 1.0.3 | 2026-03-19 | `logMsg` logging system; `focusGroupInContacts`; final summary dialog |
| 1.0.2 | 2026-03-19 | All contacts added to staging group; Flast inference capped at 9 chars |
| 1.0.1 | 2026-03-18 | Semicolon separator support |
| 1.0.0 | 2026-03-18 | Initial release |

---

## Architecture

```
Email Contact Importer.applescript
├── Section 1 — ASOC (AddressBook.framework)
│   ├── initAB()                Lazy ABAddressBook singleton
│   ├── findByEmail(email)      Indexed email search  →  [{uid, contactName}]
│   └── findByName(gn, fn)      Compound AND name search  →  [{uid, contactName}]
├── Section 2 — Logging         logMsg(level, msg)  →  Script Editor Log pane
├── Section 3 — String utils    trimStr / toUpperFirst / toTitleCase / toLower / sanitizeToken
├── Section 4 — Parsing         parseEmailLine / inferNameFromEmail
├── Section 5 — Helpers         deriveGroupName / getToday
├── Section 6 — Contacts writes
│   ├── ensureGroupExists       Idempotent group creation
│   ├── prependToNote           Anti-dup note prepend (UID lookup + email fallback)
│   ├── createContact           New contact with email + note
│   ├── addEmailToContact       Add address to existing contact (anti-dup)
│   ├── focusGroupInContacts    GUI-scripted Contacts.app sidebar selection
│   └── addToGroup              Add contact (by id) to named group
└── Section 7 — run             Main UX flow (5 dialogs)
```

---

## License

Copyright © Philippe Dewost 2026. All rights reserved.
