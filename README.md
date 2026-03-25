# macOS Contacts Management

A collection of AppleScript + ASOC utilities for managing, enriching, and automating macOS Contacts.

---

## Scripts

### [Email Contact Importer](Email%20Contact%20Importer/)
**v1.1.2** — Match a list of email addresses from a mail client or Calendar invite against macOS Contacts. Prepend timestamped notes, add new email addresses to existing contacts found by name, create missing contacts, and stage everyone in a named group for LinkedIn enrichment.

→ [README](Email%20Contact%20Importer/README.md)

---

### [MacOS Contacts Group Manager](MacOS%20Contacts%20Group%20Manager/)
Surgical and batch management of Contacts groups — cleaning, filtering, smart injection, and sync workflows.

---

### [LSAMC — LinkedIn Sync Agent for macOS Contacts](LSAMC%20-%20LinkedIn%20Sync%20Agent%20for%20macOS%20Contacts/)
Python + AppleScript supervisor that resolves LinkedIn profiles for contacts and writes enriched data back into macOS Contacts. Operates in SIMULATION mode by default; requires `--live` flag for writes.

---

## Requirements

- macOS 12 Monterey or later
- Contacts.app with populated address book
- Accessibility permission for scripts that use GUI scripting

---

## Architecture Principles

All scripts in this collection follow the same engineering standards:

- **Fortress Header** — version, purpose, architecture, changelog in every file
- **ASOC (AddressBook / Contacts framework)** for performance-critical lookups
- **Standard AppleScript Contacts.app** for all writes
- **Rule of Three UX** — maximum three confirmation dialogs per operation
- **Dry Run default** — destructive confirm buttons are never the default

Governed by:
- `ANTIGRAVITY.md` (Tier 0 — behavioral master)
- `MACOS_AUTOMATION_SPEC.md` (Tier 1 — AppleScript/ASOC platform rules)

---

## Safety

- **No `delete person`** — contact deletion is permanently destructive and disabled across all scripts
- **Anti-duplication guards** — re-running scripts on the same data is always safe
- **Additive writes only** — note prepend, email add, group membership

---

## License

Copyright © Philippe Dewost 2026. All rights reserved.
