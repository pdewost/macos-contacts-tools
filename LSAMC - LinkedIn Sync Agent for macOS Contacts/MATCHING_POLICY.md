# LinkedIn Matching Policy (v5.0) — Phase 5 Hardened

## 1. Core Search & Pre-Qualifying Rule (v5.0)
The agent MUST prioritize safety to avoid "Institutional Fog" and data poisoning.

1.  **Implicit Discovery**: For contacts without a LinkedIn handle, ONLY process if:
    - The word `LinkedIn` is present anywhere in the contact note.
    - **OR** it is an explicit user request (e.g., selection in GUI Control Center).
2.  **Search Query**: Perform a search for `FirstName LastName`.
3.  **Last Name Match**: Automated processing MUST NOT occur if the LinkedIn `LastName` does not match the macOS `LastName`.

## 2. Degree-Based Logic & Note Prepending

### Tier A: 1st Degree Connections (Direct)
- **Case 1 (Single Result)**: Add handle to social profile. Process with LSAM backend.
- **Case 2 (Ambiguous Results)**: 
    - **Action**: Do NOT process. Flag as `SKIPPED_AMBIGUOUS`.
    - **Prepending**: Prepend to top of note:
      `Ambiguity_Warning: ⚠️ LSAM AMBIGUITY (1st degree) - [YYYY-MM-DD]`
    - **Details**: List candidate URLs sorted by decreasing mutual connections (e.g., `mutual: 15`).

### Tier B: 2nd Degree Connections (Mutuals)
- **Case 1 (Single Result)**: Add handle to social profile. Process with LSAM backend.
- **Case 2 (Ambiguous Results)**:
    - **Disambiguation**: Compare LinkedIn Company/Experience names with macOS Company, Email domain, or Note keywords.
    - **Action**: If ambiguity remains, do NOT process.
    - **Prepending**: Prepend to top of note:
      `Ambiguity_Warning: ⚠️ LSAM AMBIGUITY (2nd degree) - [YYYY-MM-DD]`
    - **Details**: List candidate URLs sorted by decreasing mutual connections (e.g., `mutual: 3`).

### Tier C: 3rd Degree Connections (Strangers)
- **Policy**: NEVER process automatically.
- **Action**: ONLY provide awareness.
- **Prepending**: Prepend to top of note:
  `Warning: ⚠️ LSAM CANDIDATE (3d degree) - [YYYY-MM-DD]`
- **Details**: List the LinkedIn URL of the candidate(s).

## 3. Ambiguity Signals & Disambiguation Benchmarks
Before any 1st/2nd degree match is accepted, the agent checks:
1.  **Current Company Match**: Matches macOS `organization` vs LinkedIn Snippet.
2.  **Experience Field Match**: Checks past companies in LinkedIn "Experience" (e.g., "Worked at [Company] together").
3.  **Common Education**: High-weight signal for 1st-degree connections.

## 3. Name Match Sensitivity

*   **Exact Match**: Results where the name matches exactly (case-insensitive) are given a significant scoring boost (+50).
*   **Fuzzy Match**: If "Christian Buchel" matches "Christian Bucheli", it is a fuzzy match. However, if an exact "Christian Buchel" is present in the same list, it MUST be preferred regardless of other signals.
*   **Hyphen Agnosticism**: Matching ignores spaces vs hyphens (e.g., "Pierre Jean" matches "Pierre-Jean").

## 4. Verification Benchmarks

Every contact successfully matched must be audited for:
1.  **Mutual Connections Count**: If 0 mutual connections are found for a supposedly 1st-degree connection, the agent flags it as `⚠️ low count - verify`.
2.  **Connected Date**: The date since the connection was established is used to confirm the relationship's longevity.

## 5. Social Stats & Note Formatting

To ensure clarity in the macOS Contact note, the following formatting rules apply to social stats:

1.  **Terminology**: Use "Connections" for the network size (e.g., "Connections: 500+").
2.  **Display Logic**: Social stats (Connections and Followers) should only appear in the note if they are **non-zero** and **non-empty**, mimicking LinkedIn's own display behavior.
3.  **Zero-Follower Handling**: If a profile has 0 followers, this line MUST NOT be displayed.
4.  **Coexistence**: If both Connections and Followers are non-zero/available, they should both be displayed to provide a complete view.
5.  **Raw Strings**: Always preserve the "500+" or "1K+" raw strings from LinkedIn when available, as they are iconic indicators of reach.

## 6. Photo Retrieval Edge Cases

The agent may fail to retrieve a profile picture in the following specific scenarios:

1.  **Company vs. Person**: If a LinkedIn profile is identified as a **Company/Organization** (e.g. "InProcess Agency"), it uses a completely different HTML structure. Our agent is optimized for **Person** profiles. Company logos might not be captured by the same "Surgical Scrape" selectors used for faces.
2.  **Privacy Settings**: Even for 1st-degree connections, some users may restrict their profile picture visibility to "LinkedIn members" or "My network". If the agent's session has a temporary glitch, the high-res lightbox might not trigger.

### 6.2 1st-Degree Zero-Mutual Exception
While rare, a 1st-degree connection might occasionally show "0 mutual connections" (e.g., very private profiles or new accounts).
- **Policy**: If Degree is **1st**, the match is accepted even with 0 mutuals.
- **Reporting**: This must be explicitly reported in the Contact Note with a `⚠️` suffix to the connections string (e.g., `LinkedIn Connections: 500+ (0 mutual ⚠️)`).

### 6.3 Historical Photo Recovery
Before marking a photo as "None" or using a low-res version, the agent should:
1.  Search all previous session `backups/` directories for that specific contact name.
2.  If an HQ photo (`-linkedin-raw.jpg` or `-linkedin.heic`) was captured in a previous run, use it as a candidate.
3.  This is particularly useful for Company Profiles where the logo extraction might be intermittent. (e.g., InProcess Agency logo found in `logs/sessions/inprocessagency_profile.png`).

3.  **Missing Photo**: Some professional profiles simply do not have a photo uploaded.
4.  **Extraction Failure & Tier 4 Fallback (v3.1.4)**:
    *   **Tiers 1-3 (High-Res)**: The agent attempts to retrieve a high-resolution image (800x800) via Network Sniffing, Lightbox Clicking, or Canvas Capture.
    *   **Tier 4 (Standard Res Fallback)**: If all high-res methods fail, the agent **MUST** capture the standard/thumbnail photo visible in the DOM (`img.pv-top-card-profile-picture__image`).
    *   **Outcome**: The macOS contact photo will only be left unchanged if **NO** photo is visible on the profile at all. A 200px photo is considered strictly better than no photo.

When a photo is missing:
- Verify the LinkedIn URL in the note.
- If the URL points to a company, this is an expected "No Photo" case for the current LSAMC version.
