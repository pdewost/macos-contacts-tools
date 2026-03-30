# macOS Contacts Management

A collection of AppleScript + ASOC utilities for managing, enriching, and automating macOS Contacts.

---

## Background

macOS Contacts has not had a significant feature update since 2012, when Apple renamed Address Book to Contacts in OS X Mountain Lion. Since then:

- **Group management on macOS is still primitive.** No bulk operations, no move-between-groups workflow, no batch add/remove — everything is drag-and-drop, one contact at a time. iOS 26 actually outpaces macOS here: it renamed Groups to "Lists" and added proper management from iPhone.
- **Contact photos behave differently** across macOS, iOS, and iCloud — silent resizing, sync failures, and inconsistent display between platforms are a recurring issue.
- **Mail.app has no contextual intelligence** about contacts — no "last contacted" surfacing, no note-based suggestions, no deduplication assistance.

The scripts in this collection fill specific gaps that Apple has left unaddressed for over a decade.

---

## Scripts

### [Email Contact Importer](Email%20Contact%20Importer/)
**v1.1.2** — Match a list of email addresses from a mail client or Calendar invite against macOS Contacts. Prepend timestamped notes, add new email addresses to existing contacts found by name, create missing contacts, and stage everyone in a named group for further processing.

→ [README](Email%20Contact%20Importer/README.md)

---

### [MacOS Contacts Group Manager](MacOS%20Contacts%20Group%20Manager/)
Surgical and batch management of Contacts groups — cleaning, filtering, smart injection, and sync workflows.

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

Copyright © Philippe Dewost 2026. Licensed under the [Apache License 2.0](LICENSE).
