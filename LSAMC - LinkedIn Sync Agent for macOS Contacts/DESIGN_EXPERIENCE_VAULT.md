# Design Brief: LinkedIn Career & Education Vault Capture
**Version**: 1.0
**Created**: 2026-03-13 by Claude Sonnet 4.6 (Claude Code)
**Status**: Mid-term feature — DESIGN PHASE. No implementation until prerequisites complete.
**Project**: LSAMC v4.9.1 — LinkedIn Sync Agent for macOS Contacts

---

> [!IMPORTANT]
> **For GenAI Agents — This is a design document only.**
> Do NOT implement anything in this file without explicit user authorization.
> Prerequisites must be completed first (see §8).

---

## 1. The Idea (User's Statement)

> "What would be REALLY smart would be to capture the complete first LinkedIn page, isolate the EXPERIENCE and EDUCATION fields, and add them to the vault. Then use the cleaning and formatting logic found in the CCC project 'contact-operations.applescript' to clean this block. Then either add it if it does not exist, or update the existing one."

---

## 2. Why This Is Architecturally Sound

The current LSAMC engine treats LinkedIn as a **form**: extract headline + company → write to Contact fields. This design brief proposes treating LinkedIn as a **structured document**: capture the full career graph from the first page, store it in the vault, and use it as the authoritative source for both Contact fields and the contact note.

### The payoffs are layered:

**Immediate (resolves existing issues):**
- **Resolves F6 / NR-1** (field destruction policy): `experience_entries[0]` — the most recent job in the EXPERIENCE block — is structurally the most reliable source for the Contact's organization and job title. It replaces the LinkedIn headline (marketing text, often stale) without requiring a user policy decision. The "which source?" ambiguity disappears.
- **Null guard automatic**: If EXPERIENCE scraping fails or returns empty, the engine has nothing to write → existing Contact fields are preserved. No explicit null guard needed.

**Short-term (adds value):**
- **Richer contact notes**: Currently synced notes contain: sync block + mutual connections. With this, they'd contain a full professional dossier: career history, education. Useful in Spotlight, readable in Contacts.app, searchable.
- **Education data**: Currently not captured at all. Alumni grouping, cohort analysis, relationship classification become possible.

**Long-term (foundation):**
- **Career evolution tracking**: Vault stores timestamped EXPERIENCE snapshots → can detect job changes across re-syncs.
- **identity_sweep improvements**: sweep can use EXPERIENCE company as a cross-reference for identity verification.
- **Future classification**: Batch contacts by school, company, or career stage using vault data.

---

## 3. The CCC Cleaning Pipeline — What Exists and What It Does

**File**: `macOS Contacts Management/CCC AppleScript Suite for cleaning macOS Contacts (was Contact Management - v6)/contact-operations.applescript`
**Version**: 0.9.14 (2026-03-09)

The CCC project processes raw LinkedIn text that was copy-pasted into contact notes. Its cleaning logic is directly applicable to DOM-scraped EXPERIENCE/EDUCATION text.

### Relevant handlers:

| Handler | Purpose | Reuse value |
|:---|:---|:---|
| `normalizeContactLine()` | Removes LinkedIn junk (logo lines, "Show all X experience", "degree connection"), standardizes section headers ("ExperienceExperience" → "==== Experience"), strips field prefixes ("Degree Name:", "Field Of Study:", "Location:"), deduplicates LinkedIn DOM repeat artifacts | **HIGH — port to Python** |
| `addExperienceSeparators()` | Detects company boundaries within EXPERIENCE section using look-ahead heuristics. Supports multi-role detection (person held multiple roles at same company). Handles French patterns (Stage, Freelance, Apprentis, En poste, Indépendant). Adds blank-line separators between jobs. | **HIGH — port to Python** |
| `normalizeLinkedInTransition()` | Standardizes the "LinkedIn → ==== Experience" structural transition. Adds proper separator rules. | **MEDIUM — port to Python** |
| `deduplicateFlattenedSeeMoreBlocksEnhanced()` | Handles "see more" LinkedIn preview blob deduplication — when LinkedIn DOM emits content twice due to the preview/expand pattern. | **HIGH — needed for DOM scraping** |
| `processNoteContentV3()` | Full multi-pass cleaning pipeline (junk removal → deduplication → structural normalization). Orchestrates all the above. | **Reference — do not port as-is; adapt** |

### Integration approach: Python port (recommended over subprocess call)

The cleaning handlers are deterministic string operations. Porting to Python is ~150 lines, highly testable, and eliminates the fragile AppleScript-subprocess dependency. The CCC project should remain the canonical reference implementation; the Python port should track its logic but is standalone.

**Alternative (not recommended)**: Call `osascript` from Python to invoke CCC handlers directly. Requires CCC script compiled, specific path dependencies, subprocess overhead per line. Too fragile for production use inside the sync engine.

---

## 4. What to Scrape: LinkedIn First Page Structure

The LinkedIn profile first page (desktop, authenticated) contains, in order:
1. **Main profile block** — name, headline, company, location ← *already scraped*
2. **About** — summary text ← *skip for now*
3. **Activity** — recent posts ← *skip*
4. **Experience** — structured job history ← **NEW**
5. **Education** — structured education history ← **NEW**
6. **Skills / Certifications / etc.** ← *skip for now*

EXPERIENCE and EDUCATION are visible on the first page without additional navigation. No new LinkedIn page load is needed — only additional DOM extraction on the already-loaded profile page.

### DOM extraction strategy

The EXPERIENCE and EDUCATION sections are `<section>` elements with `id="experience-section"` and `id="education-section"` (or similar — verify current DOM, subject to drift). Each job/education entry is a `<li>` element.

**Preferred extraction**: Use the existing Chromium DevTools Protocol (CDP) session to evaluate JavaScript on the profile page and extract the text content of the EXPERIENCE/EDUCATION sections. This is consistent with the current T2/T3 architecture.

**Fallback**: Read the full page text (already available from the profile DOM) and use the `==== Experience` / `==== Education` section markers as delimiters after normalization.

---

## 5. Vault Schema Extension

**Current vault location**: `data/vault/{contact_slug}/profile.json`

**New fields to add** (additive, non-breaking):

```json
{
  "experience_entries": [
    {
      "company": "Acme Corp",
      "title": "VP Global Sales",
      "date_range": "Jan 2019 - Present",
      "duration": "5 yrs 2 mos",
      "location": "Paris, France",
      "description": "Led a team of 45 across EMEA..."
    },
    {
      "company": "Previous Corp",
      "title": "Director, Business Development",
      "date_range": "Mar 2015 - Dec 2018",
      "duration": "3 yrs 9 mos",
      "location": "London, UK",
      "description": ""
    }
  ],
  "education_entries": [
    {
      "institution": "HEC Paris",
      "degree": "MBA",
      "field": "Finance",
      "date_range": "2001 - 2003"
    }
  ],
  "career_raw_text": "...",
  "career_captured_at": "2026-03-13T19:00:00+01:00",
  "career_capture_version": "1.0"
}
```

**Notes**:
- `career_raw_text` stores the pre-normalization DOM text for debugging and re-processing without a new LinkedIn visit
- `career_captured_at` enables stale-detection in future versions (re-scrape if career data is >90 days old)
- `description` truncated at 300 chars per entry to avoid vault bloat
- `experience_entries` capped at 10 entries; `education_entries` capped at 5

---

## 6. Contact Note Block Format

Two new blocks added to the contact note, **outside** the `<Linkedin-AI-sync>` block and **below** it:

```
<Linkedin-AI-sync>
... existing sync content ...
</Linkedin-AI-sync>

<Linkedin-Career>
==== Experience

Acme Corp | VP Global Sales
Jan 2019 - Present  ·  5 yrs 2 mos

Previous Corp | Director, Business Development
Mar 2015 - Dec 2018  ·  3 yrs 9 mos

==== Education

HEC Paris | MBA | Finance | 2001-2003
</Linkedin-Career>
```

**Format rationale**:
- Single tag `<Linkedin-Career>` contains both Experience and Education — simpler block management
- `==== Experience` / `==== Education` headers inside the block use the CCC canonical format (compatible with CCC re-cleaning if user runs CCC manually later)
- Company | Title on one line, date range on next line — matches CCC `addExperienceSeparators` output
- Blank line between entries (CCC standard)

**Update logic (on re-sync)**:
1. Detect existing `<Linkedin-Career>` block via regex
2. If exists → replace content with fresh data
3. If not exists → append after `</Linkedin-AI-sync>`
4. If EXPERIENCE scraping failed or returned empty → **leave existing block untouched** (null guard: never destroy career history)

---

## 7. Impact on Field Destruction Fix (NR-1/F6)

Once `experience_entries` is in the vault, the contact field update logic in `contact_macos.py` changes:

```python
# CURRENT (headline is source)
contact.organization = profile.company   # from LinkedIn headline
contact.job_title   = profile.job_title  # from LinkedIn headline

# NEW (EXPERIENCE[0] is source, headline as fallback)
if profile.experience_entries:
    most_recent = profile.experience_entries[0]
    contact.organization = most_recent["company"] or profile.company or ""
    contact.job_title    = most_recent["title"]   or profile.job_title or ""
else:
    # Fallback: headline (preserve null guard)
    contact.organization = profile.company   if profile.company   else existing_organization
    contact.job_title    = profile.job_title if profile.job_title else existing_job_title
```

This makes NR-1 self-resolving: the EXPERIENCE-first approach is both more accurate AND naturally null-safe.

**Implication for NR-1 sequencing**: Implement the simple null guard (NR-1) as a quick fix in the current cycle. When this feature is ready, NR-1 is superseded by the EXPERIENCE-first logic above.

---

## 8. Implementation Phases

> Prerequisites: H1 (malformed sync block repair) must be complete before adding new block types. Otherwise new `<Linkedin-Career>` blocks may be misidentified as malformed sync blocks.

| Phase | Name | Description | Scope | Depends on |
|:--|:---|:---|:---|:---|
| P0 | Quick fix (NR-1) | Null guard for company/job: skip write if LinkedIn returns empty | 1 file, ~5 lines | None — do now |
| P1 | Research | Read CCC `utilities.applescript` to inventory helper functions (trimWhitespace, deduplicateFirstHalfRepeat, etc.) | Read-only | None |
| P2 | Python port | Port `normalizeContactLine` + `addExperienceSeparators` to Python. Write unit tests against CCC test cases. | New file: `src/bridge/career_normalizer.py` | P1 |
| P3 | Scraping | Extend `pro_sync_agent.py`: after main profile extraction, extract EXPERIENCE/EDUCATION DOM text via CDP JS eval. Store raw text in `profile.career_raw_text`. | `pro_sync_agent.py` | P2 |
| P4 | Vault | Run `career_normalizer.py` on raw text → populate `experience_entries` + `education_entries` in `profile.json`. | `pro_sync_agent.py` + vault writer | P3 |
| P5 | Note block | Add `<Linkedin-Career>` block writer to `_finalize_sync`. Add block update/append logic. Write unit tests for block detection + replacement regex. | `pro_sync_agent.py`, `contact_macos.py` | P4, H1 |
| P6 | Field fix integration | Swap `contact_macos.py` company/job source from headline to `experience_entries[0]`. Deprecates P0 null guard (which remains as safety fallback). | `contact_macos.py` | P5 |
| P7 | Vault audit tool | Script to retrospectively populate `experience_entries` from `career_raw_text` for contacts already in vault (no new LinkedIn visit needed if raw text was captured). | `scripts/career_backfill.py` | P6 |

**Total estimated scope**: Medium-large feature. P2–P6 is approximately 3–4 focused coding sessions.

---

## 9. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|:---|:---|:---|
| LinkedIn DOM drift on EXPERIENCE section | Medium | Capture raw page text as fallback; use section markers rather than specific element IDs |
| "see more" expansion not triggered → truncated entries | High | Apply `deduplicateSeeMoreXYXBlobs` logic to detect and flag truncated entries; mark `description` as partial |
| Very long profiles (10+ jobs) bloat vault + note | Medium | Cap at 10 entries; truncate description at 300 chars; `career_raw_text` cap at 5000 chars |
| `<Linkedin-Career>` block confuses malformed-block detection (H1) | Medium | Implement H1 first; H1 detector must understand and preserve Career blocks |
| CCC port diverges from AppleScript original | Low | Write parity tests: run both versions on same input, compare output |
| French LinkedIn variants missed | Low | CCC already handles French patterns; port faithfully |
| Multi-role at same company misidentified as new company | Medium | Port `addExperienceSeparators` including total-duration look-ahead heuristics |

---

## 10. Open Questions (For User Decision)

1. **Description field**: Include job descriptions (truncated)? Or title + date only? Descriptions add value but create note clutter and vault size.
2. **Skills section**: Worth capturing? CCC drops it by default (`Skills:` → return ""). Could be useful for identity sweep.
3. **Career block visibility**: Should `<Linkedin-Career>` be visible in Contacts.app (i.e., part of the note proper) or hidden inside a tag the user doesn't normally see? The current proposal makes it visible — is that the right UX?
4. **CCC coexistence**: When CCC's `processNoteContentV3` runs on a contact that has both a `<Linkedin-AI-sync>` block and a `<Linkedin-Career>` block, what should CCC do? Preserve the blocks as-is? CCC currently doesn't know about LSAMC blocks — this may require a CCC update.
5. **Retrospective capture**: After implementing P3–P5, should re-syncing a contact always refresh the Career block, or only if it's missing? (Recommendation: always refresh — career data can change.)

---

## 11. References

- `src/agent/pro_sync_agent.py` — scraping engine (extend for EXPERIENCE/EDUCATION extraction)
- `src/bridge/contact_macos.py` — Contact writer (add Career block logic)
- `data/vault/` — vault structure (extend `profile.json`)
- CCC `contact-operations.applescript` (v0.9.14) — normalization reference implementation
- CCC `utilities.applescript` — helper functions (trimWhitespace, etc.) to port
- `AUDIT_2026-03-13.md §12 F6` — field destruction policy (this feature supersedes NR-1)
- `PLAN_2026-03-13_ENGINE_RELAUNCH.md §Next Round Backlog` — NR-11 (this feature)
- `ANTIGRAVITY_REBASE_2026-03-13.md §Design Issues` — design context for Antigravity

---

*DESIGN_EXPERIENCE_VAULT.md — End of Document (v1.0)*
*Status: Design brief only. No implementation until H1 complete and user approves phasing.*
*Next action: User confirms open questions (§10), particularly description field inclusion and CCC coexistence strategy.*

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
