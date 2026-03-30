-- LSAM Control Center (GUI)
-- Version: 3.0.0
-- Purpose: Native macOS GUI for the LSAM project.
-- Bridges to scripts/lsam_control_center.py (v1.5.0)
-- v3.0.0 (2026-03-29): UX Redesign — PLAN_2026-03-29_LSAM_V5_REDESIGN.md Part 6
--   Menu simplified: 10 items → 7 items. Focused on daily use cases.
--   New menu: Preview Selected | Sync Selected | Review Queue | Review Last Session | More... | Start/Stop | Exit
--   Removed: Triage DAMAGED (audit shows 733/847 have no vault), separate Promote/Demote/Status/Refresh.
--   New handlers: resolveSlugForContact (deduplicated slug resolution, was in 3 places),
--     launchSyncAgent (shared sync launch), handlePreviewSelected (dry-run diff per contact,
--     selects contact in Contacts.app then shows field-by-field diff dialog with Apply/Edit/Skip/Back),
--     handleEditOverride (field=value overrides saved to vault), lsamGetGroupCount (new name + legacy fallback).
--   Groups: LSAM-* prefix (LSAM-Queue, LSAM-Review, LSAM-Golden) with fallback to legacy script-LSAM-*.
--   Preview flow: non-destructive + idempotent. Contact selected in Contacts.app → structured diff dialog →
--     user chooses Apply (vault-only FULL sync) / Edit (field overrides) / Skip / Back.
--   MBP Dev Monitor: paia_control_center.py updated to launch CC via osascript (was dead localhost:5010).
-- v2.4.14 S14: handleSelectionContext sync: track launchedIDs/Names/Slugs so
--               "Review Last Sync" (0b) shows correct count after selection sync.
-- v2.4.13 S13: processProfileReview: add 🔄 Fresh Sync action (full SIMULATION,
--               no --vault-only; bootstraps empty vault after crash). Returns BACK.
--               handleSelectionContext: 🔄 Sync now runs direct SIMULATION on known
--               selection (skips mode picker, passes contacts directly).
-- v2.4.12: processProfileReview: replace open location with plain activate.
--               open location "addressbook://UUID:ABPerson" opens a mini popup card
--               (not the Contacts editor). Contact already selected by caller.
-- v2.4.11: Fix "INCONNU" ghost contact in Contacts.app. Root cause: stripping
--               ":ABPerson" from abID before building addressbook:// URL maps to a
--               stale ghost slot. Fix: use abID as-is ("UUID:ABPerson") in both
--               processTriageAction and processProfileReview open location calls.
-- v2.4.10 S10-B: Selection-aware launch dialog (N=15). When contacts are
--               pre-selected in Contacts.app at launch, mainDashboard() intercepts
--               before the main menu and calls handleSelectionContext(selContacts):
--               lists up to 15 names, offers Sync / Review / Promote / Demote /
--               Full Menu / Cancel. Review delegates to handleSelectionReview()
--               which mirrors handleManualSync slug-resolution + processProfileReview
--               per contact. Full Menu / post-action falls through to mainDashboard.
-- v2.4.10 S10-A: processProfileReview: add "📸 Apply Photo" action. Vault-first
--               (data/vault/<UUID>:ABPerson/linkedin.heic), falls back to most
--               recent session backup heic matched by last-name fragment. Applies
--               via `set image of p to (read (POSIX file path) as data)` + save.
-- v2.4.9 S9-B: [Python engine] Fix _stealth_nav v5.2: page.get_url() returns CDP
--               frame URL (base profile URL without overlay path) — v5.1 early-return
--               still fired even when page was on overlay because _nu() comparison saw
--               two identical base URLs. Fix: use page.evaluate("window.location.href")
--               (JavaScript-visible URL, includes /overlay/contact-info/ suffix) to match
--               the same value used by the v6.2 guard.
--               v6.3 guard: replace asyncio.sleep(3) with wait_for_selector() on
--               h1.text-heading-xlarge / .pv-top-card (profile-specific elements).
--               Absent on /feed/ where h1 is "visually-hidden feed updates" — confirms
--               the profile DOM is ready before surgical scrape runs. Falls back to 4s.
--               v1.5.8 Surgical identity block: add "feed updates" / "feed | linkedin" /
--               "feed post" to invalid_names; also block via document.title check
--               (debug_title contains "feed | linkedin") so feed-page scrapes are
--               hard-rejected regardless of element extraction results.
-- v2.4.9 S9-A: Triage sort — scanAndSortGroup(groupName, sortByStatus).
--               DAMAGED (sortByStatus=false): contacts sorted alpha by family name
--               using NSSortDescriptors (localizedCaseInsensitiveCompare:).
--               Review (sortByStatus=true): status-bucketed ([Ambiguous] first,
--               then [No Block], then other), alpha by family name within each bucket.
-- v2.4.8 S8-I: Fix _stealth_nav early-return: same substring bug as v6.1 guard.
--               `if url in current_url: return` (Python) let overlay URL pass the
--               early-return → _stealth_nav returned immediately without navigating
--               → scrape still ran on overlay/feed page despite v6.2 guard firing.
--               v5.1: changed to normalized exact path comparison (_nu helper).
--               Fix double-prefix regression: stored social profile URLs of the form
--               "http://www.linkedin.com/in/linkedin.com/in/slug" (from an old buggy
--               write) caused lsamNormalizeLinkedInURL to extract "linkedin.com/in/slug"
--               (still has domain). Agent received that as --url, prepended full URL →
--               triple-prefixed URL in Chrome. Two-layer fix: (1) lsamNormalizeLinkedInURL
--               now loops until no more "linkedin.com/in/" prefix remains; (2) Python
--               agent re.split on any number of nested prefixes, keeps last segment.
--               Fix Contacts.app `select` -1708: `select {person id abID}` not understood.
--               Contacts.app AppleScript uses `show person id abID`, not `select`.
--               Applied at processProfileReview and processTriageAction.
-- v2.4.7 S8-H: Fix v6.1 navigation guard false-negative: overlay URL contains profile
--               URL as substring → guard never fired → scrape ran on overlay/contact-info
--               page (h1="feed updates", role="Feed post number 1"). v6.2 uses exact
--               normalized path comparison (strip trailing slash + query/fragment).
--               Fix FULL mode vault bypass: vault hit unconditionally bypassed LinkedIn
--               even without --vault-only, so a failed simulation's incomplete vault
--               (empty role/experience) was applied in FULL mode. Now vault is only used
--               when --vault-only is explicitly set. FULL/SIMULATION always scrape fresh.
--               Fix Sync Now "no slug resolved": processProfileReview now accepts slugHint
--               from handleManualSync (stored in _pLastSyncedSlugs). Avoids re-lookup
--               against Contacts.app which fails silently on zombie/url-only profiles.
--               Fix LECOUFFE-class skip: social profile matching now also checks url field
--               and matches by url containing "linkedin" (not just service name). Logs
--               warning when both user name and url are empty so cause is traceable.
--               handlePostSyncReview now takes slugList (3rd param); all callers updated.
-- v2.4.6 S8-G: Fix shutil UnboundLocalError crashing Sync Now vault-hit path
--               (import shutil was only inside non-vault block ~line 3928; vault hit
--               path at line 3734 executed before it). Added local import at vault hit.
--               Fix surgical scrape selectors (v7.0): experience uses pvs-list DOM
--               traversal from #experience anchor (replaces stale CSS sibling selector);
--               headline walks h1 siblings before class fallbacks; location now
--               validated to reject mutual/connection blobs.
--               Fix processProfileReview dialog title: now shows "LSAM v<ver>".
-- v2.4.5 S8-F: handleManualSync now passes --surgical: DOM-based extraction instead of
--               Gemini Flash page.extract_content(). Fixes role/company not being ingested:
--               the contact-info popup navigates away from the profile URL, leaving
--               extract_content on a JSON/overlay page with no name or role.
--               pro_sync_agent: v6.1 re-navigation guard after contact info popup.
--               profile.py: v5.5 Guard extended — also blocks "No data available",
--               "data not available" and prefix variants.
-- v2.4.4 S8-E: handleManualSync now sets LSAMC_IGNORE_HOURS=1 — bypasses stealth
--               time gate (08:00-20:00) for manual sync. Manual sync is user-initiated
--               on a handful of contacts; daily quota and cooldown still apply.
-- v2.4.3 S8-D: Fixed vault-never-populated root cause: pro_sync_agent._finalize_sync()
--               now writes data/vault/<id>/{profile,master_profile,scavenger_meta}.json
--               + photo after every successful SIMULATION run. cmd_profile() now tries
--               both plain UUID and UUID:ABPerson directory forms (AppleScript passes
--               plain UUID; vault dirs use UUID:ABPerson suffix).
-- v2.4.2 S8-C: Fixed UnboundLocalError in contact_macos.py:792 — stale v5.5 block
--               referenced updated_fields/added_fields before initialization, crashing
--               all sync writes (vault never written → Sync Now always VAULT MISS).
--               Fixed select person id -1708: use select {person id abID} list form
--               in both processProfileReview and processTriageAction.
-- v1.1.0 S1: Dynamic root (Pattern A), venv detection (Pattern B),
--            with timeout + try/on error on all shell calls (fixes F1-F4)
-- v1.2.0 S2-B0: ASOC framework (Patterns H+I) — CNContactStore read path
--               initContactsFramework, lsamGetMemberCountForGroup, scanAndSortGroup
--               Fix: |name|(), |note|(), |error|:(reference) for reserved-word escaping
-- v1.5.0 S2-A/B/C: choose from list main loop (Pattern E, fixes F6),
--                  getBackendPID + handleBackendStop (Patterns C+D),
--                  live ASOC counts in menu, runCLI + jsonGet helpers (S2-C)
-- v2.0.0 S3-B/C: handleTriageDamaged (Pattern I + E inner loop) + processTriageAction,
-- v2.2.0 S5-*:  handleBackendStart — Live/Dry-Run dialog, LSAMC_ENGINE fix
--                handleManualSync — LSAMC_ENGINE fix
-- v2.1.0 S4-D: handleManualSync (pro_sync_agent.py, 3-step dialog, mode picker),
--              Advanced sub-menu wired (Manual Sync + Inspect Contact Archive)
-- v2.4.1 S8-B: processProfileReview: Sync Now now passes --vault-only (uses simulation vault
--               data; no Chrome re-scrape). Contact selection moved to action dispatch so
--               Contacts.app is front when the action executes (not buried by dialog).
--               Error logging added to select person id (was silently swallowed).
--               handlePostSyncReview: mutable remainIDs/Names; processed contacts removed
--               after each non-Skip non-Back action; auto-exit when list empties.
--               processProfileReview returns "SKIP" for Skip (keep in list) vs "" (processed).
-- v2.4.0 S8: processProfileReview overhauled — choose from list action menu (Validate /
--              Sync Now / Promote / Skip / Back), profile summary in prompt.
--              handleManualSync: collects launched IDs, stores in _pLastSyncedIDs/Names,
--              offers post-sync review (poll + handlePostSyncReview loop).
--              Bug fix: select person id now uses UUID:ABPerson format (CNContact
--              identifier lacks suffix → silent failure in Contacts.app).
-- v2.3.5 S7-C: lsamExtractLinkedInSlug — AppleScript passes bare slug to --url, agent owns
--               URL construction. Strips query strings, fragments, trailing slashes.
-- v2.3.4 S7-B: lsamNormalizeLinkedInURL helper — deduplicates linkedin.com/in/ double-prefix.
--               Applied at user name read AND URL prompt dialog.
-- v2.3.3 S7: handleManualSync: fixed -1728 crash on zombie social profiles.
--              Reads user name (handle) instead of value — consistent with bridge.
--              Added try/on error guard; URL constructed from handle.
-- v2.3.2 S6-B: Restored premium emojis, ASOC NSPredicate group counting optimisation,
--              robust interactive logging.
-- v2.3.1 S6: Manual Sync promoted to main menu (Selection-based).
--              handleManualSync overhauled: now works on selected contacts,
--              prompts for missing URLs, logs to Script Editor.
-- v2.3.0 S5-A/B: processProfileReview + handleProfileReview (LinkedIn vault data dialog,
--                validate action); "Triage Review" wired; Advanced → Profile Review added

use framework "Foundation"
use framework "Contacts"
use scripting additions

-- ── Properties (lazy-cached; reset on next launch) ──────────────────────────
property _pAgentRoot : missing value
property _pythonPath : missing value
property _contactStore : missing value
property _pLastSyncedIDs : {} -- AppleScript person id format (UUID:ABPerson) — post-sync review
property _pLastSyncedNames : {} -- contact names parallel to _pLastSyncedIDs
property _pLastSyncedSlugs : {} -- LinkedIn slugs parallel to _pLastSyncedIDs — for Sync Now without re-lookup
property _pVersion : "3.0.0" -- single source of truth for window title

-- ── Handler: dynamic project root (fixes F1 — no hardcoded path) ────────────
on getAgentRoot()
	if _pAgentRoot is missing value then
		try
			with timeout of 10 seconds
				set _pAgentRoot to do shell script "dirname " & quoted form of (POSIX path of (path to me))
			end timeout
		on error errMsg
			display alert "LSAM: Could not resolve project root." message errMsg
			set _pAgentRoot to "."
		end try
	end if
	return _pAgentRoot
end getAgentRoot

-- ── Handler: venv-aware Python interpreter (fixes F4) ────────────────────────
on getVenvPython()
	if _pythonPath is missing value then
		set root to my getAgentRoot()
		if (exists POSIX file (root & "/venv/bin/python3")) then
			set _pythonPath to root & "/venv/bin/python3"
		else
			set _pythonPath to "python3"
		end if
	end if
	return _pythonPath
end getVenvPython

-- ── Handler: Script Editor log (mirrors CCC cmLogInfo pattern) ───────────────
-- Outputs to Script Editor Log pane (View > Log History). No Terminal, no dialogs.
-- Levels: OK / INFO / WARN / ERROR
on lsamLog(level, msg)
	set ts to time string of (current date)
	if level is "OK" then
		log "✅ [" & ts & "] " & msg
	else if level is "WARN" then
		log "⚠️  [" & ts & "] " & msg
	else if level is "ERROR" then
		log "❌ [" & ts & "] " & msg
	else
		log "ℹ️  [" & ts & "] " & msg
	end if
end lsamLog

-- ── Handler: ASOC CNContactStore init (Pattern H) ───────────────────────────
on initContactsFramework()
	if _contactStore is missing value then
		set _contactStore to current application's CNContactStore's alloc()'s init()
	end if
	return _contactStore
end initContactsFramework

-- ── Handler: fast group member count via CNContactStore (Pattern H) ──────────
-- ~200ms for any group size; no Python startup overhead
-- Key: |name|() and |error|:(reference) — name/error are reserved AS keywords
on lsamGetMemberCountForGroup(groupName)
	set cs to my initContactsFramework()
	set {allGroups, gErr} to cs's groupsMatchingPredicate:(missing value) |error|:(reference)
	repeat with grp in allGroups
		if (grp's |name|() as text) is groupName then
			set gID to grp's identifier()
			set pred to (current application's CNContact's predicateForContactsInGroupWithIdentifier:gID)
			set emptyKeys to current application's NSArray's array()
			set {hits, fetchErr} to (cs's unifiedContactsMatchingPredicate:pred keysToFetch:emptyKeys |error|:(reference))
			if hits is missing value then return "0"
			return (count of hits) as text
		end if
	end repeat
	return "0"
end lsamGetMemberCountForGroup

-- ── Handler: ASOC triage scan — generalized from scanAndSortReviewGroup (Pattern I) ──
-- Returns {menuList, idList} parallel arrays for choose from list + getIDForSelection
-- Single CNContactStore round-trip: ~200ms for 1094 contacts
-- v2.4.9: sortByStatus — when true (Triage Review): contacts are bucketed
--   [Ambiguous] first (most urgent), then [No Block], then other statuses,
--   alphabetical by family name within each bucket.
--   When false (Triage DAMAGED): simple alpha by family name.
--   NSSortDescriptors (familyName asc → givenName asc) applied before bucketing.
on scanAndSortGroup(groupName, sortByStatus)
	set cs to my initContactsFramework()
	set {allGroups, gErr} to cs's groupsMatchingPredicate:(missing value) |error|:(reference)
	set targetID to missing value
	repeat with grp in allGroups
		if (grp's |name|() as text) is groupName then
			set targetID to grp's identifier()
			exit repeat
		end if
	end repeat
	if targetID is missing value then return {{}, {}}
	set keys to current application's NSArray's arrayWithArray:{current application's CNContactGivenNameKey, current application's CNContactFamilyNameKey, current application's CNContactNoteKey, current application's CNContactIdentifierKey}
	set pred to current application's CNContact's predicateForContactsInGroupWithIdentifier:targetID
	set {contacts, fetchErr} to cs's unifiedContactsMatchingPredicate:pred keysToFetch:keys |error|:(reference)
	if contacts is missing value then return {{}, {}}
	-- Sort by family name then given name (NSSortDescriptor — locale-aware, case-insensitive)
	set sortDescFam to current application's NSSortDescriptor's sortDescriptorWithKey:"familyName" ascending:true selector:"localizedCaseInsensitiveCompare:"
	set sortDescGiven to current application's NSSortDescriptor's sortDescriptorWithKey:"givenName" ascending:true selector:"localizedCaseInsensitiveCompare:"
	set sortedContacts to contacts's sortedArrayUsingDescriptors:{sortDescFam, sortDescGiven}
	if sortByStatus then
		-- Status-bucketed: [Ambiguous] → [No Block] → others, alpha within each
		set menuAmb to {}
		set idAmb to {}
		set menuNob to {}
		set idNob to {}
		set menuOth to {}
		set idOth to {}
		repeat with c in sortedContacts
			set cNote to (c's |note|() as text)
			set statusTag to "[No Block]"
			if cNote contains "LSAM AMBIGUITY" then set statusTag to "[Ambiguous]"
			if cNote contains "DAMAGED" then set statusTag to "[Damaged]"
			if cNote contains "BROKEN" then set statusTag to "[Broken]"
			if cNote contains "[Failed]" then set statusTag to "[Failed]"
			set dName to (c's givenName() as text) & " " & (c's familyName() as text) & "  " & statusTag
			set cID to (c's identifier() as text)
			if statusTag is "[Ambiguous]" then
				set end of menuAmb to dName
				set end of idAmb to cID
			else if statusTag is "[No Block]" then
				set end of menuNob to dName
				set end of idNob to cID
			else
				set end of menuOth to dName
				set end of idOth to cID
			end if
		end repeat
		set menuList to menuAmb & menuNob & menuOth
		set idList to idAmb & idNob & idOth
	else
		-- Alpha by family name only
		set menuList to {}
		set idList to {}
		repeat with c in sortedContacts
			set cNote to (c's |note|() as text)
			set statusTag to "[No Block]"
			if cNote contains "LSAM AMBIGUITY" then set statusTag to "[Ambiguous]"
			if cNote contains "DAMAGED" then set statusTag to "[Damaged]"
			if cNote contains "BROKEN" then set statusTag to "[Broken]"
			if cNote contains "[Failed]" then set statusTag to "[Failed]"
			set dName to (c's givenName() as text) & " " & (c's familyName() as text) & "  " & statusTag
			set end of menuList to dName
			set end of idList to (c's identifier() as text)
		end repeat
	end if
	return {menuList, idList}
end scanAndSortGroup

-- ── Handler: get supervisor PID (Pattern C) ──────────────────────────────────
on getBackendPID()
	try
		with timeout of 10 seconds
			set pid to do shell script "pgrep -f 'supervisor.py' || echo 0"
		end timeout
		if (count of paragraphs of pid) > 1 then set pid to item 1 of paragraphs of pid
		return pid
	on error
		return "0"
	end try
end getBackendPID

-- ── Handler: stop supervisor via SIGTERM (Pattern D) ────────────────────────
on handleBackendStop(pid)
	if pid is "0" then
		display notification "Supervisor is not running." with title "LSAM"
		return
	end if
	try
		with timeout of 10 seconds
			do shell script "kill " & pid
		end timeout
		display notification "Sent SIGTERM to Supervisor (PID " & pid & ")" with title "LSAM"
	on error errMsg
		display alert "Could not stop process " & pid message errMsg
	end try
end handleBackendStop

-- ── Handler: start supervisor — mode dialog (v2.2.0) ──────────────────────────
-- Uses LSAMC_ENGINE=PRO (fixed: was LSAM_ENGINE). Prompts Live vs Dry-Run.
on handleBackendStart()
	set root to my getAgentRoot()
	set python to my getVenvPython()
	-- Count Priority contacts for dialog context
	set priorityCount to "?"
	try
		set cScript to "tell application \"Contacts\" to count every person in group \"script-LSAM-Priority\""
		set priorityCount to do shell script "osascript -e " & quoted form of cScript
	end try
	-- Mode confirmation dialog
	set dlgMsg to "Launch LSAMC Supervisor (PRO engine)." & return & return & ¬
		"Priority queue: " & priorityCount & " contacts." & return & return & ¬
		"▶ Live — writes to macOS Contacts. Check: logs/sessions/" & return & ¬
		"🧪 Dry-Run — simulation only, no contact is modified."
	set modeChoice to button returned of (display dialog dlgMsg buttons {"Cancel", "🧪 Dry-Run", "▶ Live"} default button "🧪 Dry-Run" with title "LSAM Control Center v" & _pVersion)
	if modeChoice is "Cancel" then return
	set liveFlag to ""
	if modeChoice is "▶ Live" then set liveFlag to " --live"
	-- Launch headless, output to log file
	set logFile to root & "/logs/supervisor_launch.log"
	set cmd to "cd " & quoted form of root
	set cmd to cmd & " && LSAMC_ENGINE=PRO " & quoted form of python & " supervisor.py" & liveFlag
	set cmd to cmd & " >> " & quoted form of logFile & " 2>&1 &"
	if liveFlag is " --live" then
		my lsamLog("OK", "Launching supervisor LIVE (PRO) — will WRITE to Contacts")
	else
		my lsamLog("INFO", "Launching supervisor DRY-RUN (PRO) — simulation only")
	end if
	my lsamLog("INFO", "Log: " & logFile)
	try
		with timeout of 10 seconds
			do shell script cmd
		end timeout
		my lsamLog("OK", "Supervisor launched — PID tracking via getBackendPID()")
		if liveFlag is " --live" then
			display notification "Supervisor started LIVE — writing to Contacts." with title "LSAM"
		else
			display notification "Supervisor started in Dry-Run mode." with title "LSAM"
		end if
	on error errMsg
		my lsamLog("ERROR", "Supervisor launch failed: " & errMsg)
		display alert "Could not start Supervisor." message errMsg
	end try
end handleBackendStart

-- ── Handler: run Python CLI and return raw output ────────────────────────────
on runCLI(command, extraArgs)
	set python to my getVenvPython()
	set cliPath to my getAgentRoot() & "/scripts/lsam_control_center.py"
	set argStr to ""
	repeat with a in extraArgs
		set argStr to argStr & " " & a
	end repeat
	set cmd to quoted form of python & " " & quoted form of cliPath & " " & command & argStr
	try
		with timeout of 30 seconds
			return do shell script cmd
		end timeout
	on error errMsg
		return "{\"success\": false, \"error\": \"" & errMsg & "\"}"
	end try
end runCLI

-- ── Handler: extract a single field from a JSON string via python3 ───────────
on jsonGet(jsonStr, field)
	set cmd to "python3 -c \"import json,sys; d=json.loads(sys.stdin.read()); print(d.get('" & field & "',''))\" <<< " & quoted form of jsonStr
	try
		with timeout of 10 seconds
			return do shell script cmd
		end timeout
	on error
		return ""
	end try
end jsonGet

-- ── Handler: get contact ID from parallel-array selection (Pattern F) ────────
on getIDForSelection(selText, mList, iList)
	repeat with i from 1 to count of mList
		if item i of mList is selText then return item i of iList
	end repeat
	return missing value
end getIDForSelection

-- ── Handler: normalise any LinkedIn URL/handle variant to canonical form ─────
-- v2.3.4: Deduplicates linkedin.com/in/ double-prefix (zombie user name field
--         stores "linkedin.com/in/slug" without protocol → old code prepended
--         "https://www.linkedin.com/in/" again → broken URL).
-- Accepted inputs (all → https://www.linkedin.com/in/<slug>):
--   "federico-trucco-44246911"                       plain slug
--   "linkedin.com/in/federico-trucco-44246911"       no-protocol URL (the glitch)
--   "www.linkedin.com/in/federico-trucco-44246911"   www no-protocol
--   "https://www.linkedin.com/in/federico-trucco-44246911"   full URL
--   "https://www.linkedin.com/in/federico-trucco-44246911/"  trailing slash
on lsamNormalizeLinkedInURL(raw)
	if raw is "" or raw is "missing value" then return ""
	-- v2.4.8: Strip linkedin.com/in/ prefix iteratively to handle double-prefix bug
	-- (old syncs stored "http://www.linkedin.com/in/linkedin.com/in/slug" in the social
	-- profile url field; extracting after the first "linkedin.com/in/" yields "linkedin.com/in/slug"
	-- which when prepended again creates a triple-prefix, etc. Loop until clean.)
	if raw contains "linkedin.com/in/" then
		set work to raw
		repeat 5 times
			if work contains "linkedin.com/in/" then
				set slugStart to (offset of "linkedin.com/in/" in work) + 16
				set work to text slugStart thru -1 of work
				if work ends with "/" then set work to text 1 thru -2 of work
			else
				exit repeat
			end if
		end repeat
		-- Strip query string (? and everything after)
		if work contains "?" then set work to text 1 thru ((offset of "?" in work) - 1) of work
		-- Strip fragment (# and everything after)
		if work contains "#" then set work to text 1 thru ((offset of "#" in work) - 1) of work
		return "https://www.linkedin.com/in/" & work
	else if raw starts with "http" then
		-- Full URL to a non-standard path — use as-is (strip trailing slash)
		if raw ends with "/" then return text 1 thru -2 of raw
		return raw
	else
		-- Plain slug / handle
		return "https://www.linkedin.com/in/" & raw
	end if
end lsamNormalizeLinkedInURL

-- ── Handler: extract bare LinkedIn slug from any URL/handle variant (v2.3.5) ─
-- Returns the raw slug only (e.g. "federico-trucco-44246911"), NOT a full URL.
-- Strips domain prefix, query strings (?overlay=true&foo=bar), fragments (#), slashes.
-- pro_sync_agent.py owns URL construction — AppleScript passes slug as --url arg.
-- This eliminates any double-prefix possibility at source.
on lsamExtractLinkedInSlug(raw)
	-- First normalise to canonical https://www.linkedin.com/in/<slug>
	set canonical to my lsamNormalizeLinkedInURL(raw)
	if canonical is "" then return ""
	-- Extract slug: text after "linkedin.com/in/"
	set slugStart to (offset of "linkedin.com/in/" in canonical) + 16
	set slug to text slugStart thru -1 of canonical
	-- Strip trailing slash
	if slug ends with "/" then set slug to text 1 thru -2 of slug
	-- Strip query string (? and everything after)
	if slug contains "?" then
		set slug to text 1 thru ((offset of "?" in slug) - 1) of slug
	end if
	-- Strip fragment (# and everything after)
	if slug contains "#" then
		set slug to text 1 thru ((offset of "#" in slug) - 1) of slug
	end if
	return slug
end lsamExtractLinkedInSlug

-- ── Handler: action sub-menu for a single triage contact (S3-B) ──────────────
-- First selects contact in Contacts.app (UTILITY PATH — direct AS, no Python round-trip)
-- Write actions delegate to Python CLI (WRITE PATH)
on processTriageAction(contactID, theName)
	-- v2.4.0 fix: CNContact identifier() returns plain UUID; select person id needs UUID:ABPerson
	set abID to contactID
	if abID does not contain ":ABPerson" then set abID to abID & ":ABPerson"
	try
		-- v2.4.11: addressbook:// URL scheme resolves correctly when the FULL
		-- "UUID:ABPerson" string is used. Stripping ":ABPerson" maps to a ghost/stale
		-- slot → "INCONNU". Use abID as-is (already has :ABPerson suffix).
		open location "addressbook://" & abID
		tell application "Contacts" to activate
	end try
	set actionItems to {"🚀 Promote → Priority", "↩️  Keep in DAMAGED", "🚪 Cancel / Back"}
	set actionPick to choose from list actionItems with title "LSAM — " & theName with prompt "Choose action:" default items {item 1 of actionItems}
	if actionPick is false then return
	set action to item 1 of actionPick
	if action contains "🚀" then
		set cmdResult to my runCLI("--full promote", {"--selection"})
	else if action contains "Keep" then
		my lsamLog("INFO", "Kept in DAMAGED.")
	end if
end processTriageAction

-- ── Handler: manual single-contact sync via pro_sync_agent.py (S4-D / v2.3.3) ──
-- Works on selected contacts in Contacts.app. Launches pro_sync_agent.py in background.
-- v2.3.3: Fixed -1728 crash on zombie social profiles — reads user name (not value).
--         LSAM bridge stores handle in user name field; value/url can be null → -1728.
on handleManualSync()
	set sel_contacts to {}
	try
		tell application "Contacts"
			set sel_contacts to its selection
		end tell
	on error
		display alert "Contacts.app error."
		return
	end try
	if (count of sel_contacts) is 0 then
		display alert "Select contacts in Contacts.app first."
		return
	end if
	set modePick to choose from list {"SIMULATION (verification)", "FULL (edit)"} with title "Manual Sync"
	if modePick is false then
		my lsamLog("INFO", "Manual sync cancelled by user.")
		return
	end if
	set syncMode to "SIMULATION"
	if (item 1 of modePick) contains "FULL" then set syncMode to "FULL"
	set totalCount to count of sel_contacts
	my lsamLog("INFO", "─── Manual Sync START — mode: " & syncMode & " — " & totalCount & " contact(s) selected ───")
	set launchedCount to 0
	set skippedCount to 0
	set errorCount to 0
	set contactIndex to 0
	set launchedIDs to {}
	set launchedNames to {}
	set launchedSlugs to {}
	repeat with c in sel_contacts
		set contactIndex to contactIndex + 1
		set cName to ""
		set cID to ""
		set cURL to ""
		set urlSource to ""
		tell application "Contacts"
			set cName to name of c
			set cID to id of c -- AppleScript person id: UUID:ABPerson format
			set sps to social profiles of c
			repeat with sp in sps
				-- v2.4.7: match by service name OR by url field containing "linkedin"
				-- (some contacts store URL only in url field; user name may be blank/zombie)
				set spSvc to ""
				set spUrl to ""
				try
					set spSvc to service name of sp as string
				end try
				try
					set spUrl to url of sp as string
				end try
				if (spSvc contains "linkedin") or (spUrl contains "linkedin") then
					-- v2.3.4: read user name (handle) — avoids -1728 on zombie profiles.
					-- v2.4.7: fall back to url field when user name is empty/missing value.
					set rawHandle to ""
					try
						set rawHandle to user name of sp as string
						if rawHandle is "missing value" then set rawHandle to ""
					on error
						set rawHandle to ""
					end try
					if rawHandle is "" then
						-- Fall back to url field (some contacts only have url, no user name)
						if spUrl is not "" and spUrl is not "missing value" then set rawHandle to spUrl
					end if
					if rawHandle is not "" then
						set cURL to my lsamExtractLinkedInSlug(rawHandle)
						if cURL is not "" then set urlSource to "social profile"
					else
						my lsamLog("WARN", "[" & contactIndex & "/" & totalCount & "] " & cName & " — LinkedIn social profile has no user name or url, falling through to URL prompt")
					end if
					exit repeat
				end if
			end repeat
		end tell
		-- URL prompt fallback when social profile is absent or zombie
		if cURL is "" or (cURL as text) is "missing value" then
			try
				set urlRes to (display dialog ("LinkedIn URL for " & cName & ":") default answer "https://www.linkedin.com/in/" buttons {"Skip", "Sync"} default button "Sync" with title "LSAM — Manual Sync [" & contactIndex & "/" & totalCount & "]")
				if (button returned of urlRes is "Sync") then
					-- v2.3.5: extract bare slug from whatever the user typed
					set cURL to my lsamExtractLinkedInSlug(text returned of urlRes)
					if cURL is not "" then set urlSource to "manual prompt"
				end if
			on error
				set cURL to ""
			end try
		end if
		-- Launch or skip (cURL is now a bare slug — empty string = no URL found)
		if cURL is "" then
			set skippedCount to skippedCount + 1
			my lsamLog("WARN", "[" & contactIndex & "/" & totalCount & "] SKIP — " & cName & " (no URL provided)")
		else
			set root to my getAgentRoot()
			set py to my getVenvPython()
			-- LSAMC_IGNORE_HOURS=1: bypass stealth time gate (08:00-20:00) for manual sync.
			-- Manual Sync is a deliberate, user-initiated action on a handful of contacts;
			-- the daily quota and per-contact cooldown limits still apply.
			-- --surgical: use direct DOM selectors for name/role/company extraction instead of
			-- Gemini Flash page.extract_content(). More reliable when the contact-info popup
			-- causes a URL navigation that leaves the page in a non-profile state.
			set msCmd to "cd " & (quoted form of root) & " && LSAMC_ENGINE=PRO LSAMC_IGNORE_HOURS=1 " & (quoted form of py) & " src/agent/pro_sync_agent.py --url " & (quoted form of cURL) & " --name " & (quoted form of cName) & " --mode " & syncMode & " --surgical >> logs/manual_sync.log 2>&1 &"
			my lsamLog("INFO", "[" & contactIndex & "/" & totalCount & "] " & cName & " — mode: " & syncMode & " — url src: " & urlSource & " — " & cURL)
			try
				do shell script msCmd
				set launchedCount to launchedCount + 1
				set end of launchedIDs to cID
				set end of launchedNames to cName
				set end of launchedSlugs to cURL
				my lsamLog("OK", "[" & contactIndex & "/" & totalCount & "] Launched ✓ — " & cName)
			on error errMsg
				set errorCount to errorCount + 1
				my lsamLog("ERROR", "[" & contactIndex & "/" & totalCount & "] Launch FAILED — " & cName & ": " & errMsg)
			end try
		end if
	end repeat
	-- Store for dashboard "Review Last Sync" access
	set _pLastSyncedIDs to launchedIDs
	set _pLastSyncedNames to launchedNames
	set _pLastSyncedSlugs to launchedSlugs
	my lsamLog("INFO", "─── Manual Sync END — launched: " & launchedCount & "  skipped: " & skippedCount & "  errors: " & errorCount & " ───")
	my lsamLog("OK", "Tail logs: tail -f logs/manual_sync.log")
	display notification "✓ " & launchedCount & " launched  ·  " & skippedCount & " skipped  ·  " & errorCount & " errors" with title "LSAM Manual Sync (" & syncMode & ")"
	-- v3.0: Log manual sync session to MBP Dev Monitor calendar
	if launchedCount > 0 then
		set nameCSV to ""
		repeat with i from 1 to (count of launchedNames)
			if i > 1 then set nameCSV to nameCSV & ","
			set nameCSV to nameCSV & (item i of launchedNames)
		end repeat
		try
			my runCLI("log-session", {"--names", nameCSV, "--mode", syncMode})
		on error
			my lsamLog("WARN", "Calendar logging failed (non-critical)")
		end try
	end if
	-- Offer post-sync review if anything was launched
	if launchedCount > 0 then
		set reviewOffer to choose from list {"🔍 Review now (waits for completion)", "📋 Review from dashboard later", "🚪 Done"} with title "LSAM — Sync launched" with prompt "Launched " & launchedCount & " sync(s) in " & syncMode & " mode." & return & "Review simulation/sync results?" default items {"📋 Review from dashboard later"}
		if reviewOffer is not false then
			set reviewChoice to item 1 of reviewOffer
			if reviewChoice starts with "🔍" then
				-- Poll for all pro_sync_agent processes to finish
				display notification "⏳ Waiting for " & launchedCount & " sync(s) to complete…" with title "LSAM"
				set waitSecs to 0
				repeat
					delay 5
					set waitSecs to waitSecs + 5
					set runningProcs to (do shell script "pgrep -f 'pro_sync_agent.py' | wc -l | tr -d ' '") as integer
					if runningProcs is 0 then exit repeat
					if waitSecs ≥ 300 then
						display notification "⚠️ Timeout (5 min). Check logs/manual_sync.log" with title "LSAM"
						exit repeat
					end if
					display notification "⏳ " & runningProcs & " sync(s) still running… (" & waitSecs & "s)" with title "LSAM"
				end repeat
				my lsamLog("OK", "All sync processes done after " & waitSecs & "s — opening review")
				my handlePostSyncReview(launchedIDs, launchedNames, launchedSlugs)
			end if
		end if
	end if
end handleManualSync

-- ── Handler: show LinkedIn vault profile + action menu for one contact (v2.4.1) ─
-- READ PATH: calls `profile --contact-id UUID --json` via Python CLI.
-- WRITE PATH: Validate / Sync Now (vault-only, no re-scrape) / Promote dispatched.
-- Contact selection happens AFTER dialog so Contacts.app is front when action runs.
-- Returns: "BACK" → caller exits loop; "SKIP" → caller keeps contact in list; "" → processed.
-- slugHint: pre-resolved slug from handleManualSync (avoids re-lookup when Contacts.app is slow or contact
--           has a zombie/url-only social profile). Pass "" to fall back to live lookup.
on processProfileReview(contactID, displayName, slugHint)
	-- Step 0: Normalise ID formats
	-- AppleScript select person id needs UUID:ABPerson; Python CLI needs plain UUID.
	-- CNContact identifier() returns plain UUID; AppleScript id of c returns UUID:ABPerson.
	set abID to contactID
	if abID does not contain ":ABPerson" then set abID to abID & ":ABPerson"
	set pyID to contactID
	if pyID contains ":" then set pyID to text 1 thru ((offset of ":" in pyID) - 1) of pyID
	
	-- Step 1: Resolve LinkedIn slug for "Sync Now" action.
	-- v2.4.7: Use slugHint from handleManualSync first (avoids re-lookup failure on zombie profiles).
	-- Fall back to live social profile lookup if hint is absent.
	set cSlug to slugHint
	if cSlug is "" then
		try
			tell application "Contacts"
				set sps to social profiles of person id abID
				repeat with sp in sps
					set spSvc to ""
					set spUrl to ""
					try
						set spSvc to service name of sp as string
					end try
					try
						set spUrl to url of sp as string
					end try
					if (spSvc contains "linkedin") or (spUrl contains "linkedin") then
						set rawHandle to ""
						try
							set rawHandle to user name of sp as string
							if rawHandle is "missing value" then set rawHandle to ""
						on error
							set rawHandle to ""
						end try
						if rawHandle is "" and spUrl is not "" and spUrl is not "missing value" then
							set rawHandle to spUrl
						end if
						if rawHandle is not "" then
							set cSlug to my lsamExtractLinkedInSlug(rawHandle)
						end if
						exit repeat
					end if
				end repeat
			end tell
		on error errMsg
			my lsamLog("WARN", "processProfileReview: slug lookup failed for " & displayName & ": " & errMsg)
		end try
	end if
	
	-- Step 2: Fetch vault profile from Python CLI (READ PATH — 30s timeout in runCLI)
	set profileResult to my runCLI("profile", {"--contact-id", quoted form of pyID, "--json"})
	set displayText to my jsonGet(profileResult, "display_text")
	set successVal to my jsonGet(profileResult, "success")
	if displayText is "" or successVal is "False" then
		set errMsg to my jsonGet(profileResult, "message")
		if errMsg is "" then set errMsg to "(vault lookup failed)"
		set displayText to "(No LinkedIn vault data available.)" & return & errMsg & return & "Contact ID: " & pyID
	end if
	
	-- Step 3: Build prompt — vault summary (capped at 500 chars) + separator
	set summaryText to displayText
	if (length of summaryText) > 500 then set summaryText to text 1 thru 500 of summaryText & "…"
	set reviewPrompt to displayName & return & "──────────────────────" & return & summaryText & return & return & "Pick action (⌘⇥ to see contact in Contacts.app):"
	
	-- Step 4: Action menu via choose from list (no button limit, self-documenting)
	set actionItems to {¬
		"✅ Validate — data correct; remove from 'LinkedIn to Review' queue", ¬
		"🔁 Sync Now — apply vault data to Contacts (no re-scrape; uses simulation result)", ¬
		"🔄 Fresh Sync — re-scrape from LinkedIn (opens Chrome; bootstraps empty vault)", ¬
		"🚀 Promote → Priority — add to scheduler queue; synced automatically", ¬
		"📸 Apply Photo — apply most recent backed-up LinkedIn photo to contact", ¬
		"⏭ Skip — keep in list; review later this session", ¬
		"🚪 Back — stop reviewing, return to caller"}
	set actionPick to choose from list actionItems with title "LSAM v" & _pVersion & " — Profile Review: " & displayName with prompt reviewPrompt default items {item 4 of actionItems}
	if actionPick is false then return "BACK"
	set action to item 1 of actionPick
	
	-- Step 5: Bring Contacts.app to front so user sees the contact card.
	-- v2.4.11: Removed open location — it opens a mini popup card, not the editor.
	-- Contact is already visible/selected since processProfileReview is called from
	-- either handleSelectionReview (user pre-selected it) or handleProfileReview
	-- (triage loop, contact was just shown via processTriageAction). Just activate.
	tell application "Contacts" to activate
	my lsamLog("INFO", "Contacts.app activated for: " & displayName & " (" & abID & ")")
	
	-- Step 6: Dispatch
	if action starts with "✅" then
		-- WRITE PATH: remove from 'LinkedIn to Review' group
		set validateResult to my runCLI("--full validate", {"--contact-id", quoted form of pyID, "--name", quoted form of displayName})
		set valMsg to my jsonGet(validateResult, "message")
		if valMsg is "" then set valMsg to validateResult
		display notification valMsg with title "LSAM — Validated"
		my lsamLog("OK", "Validated: " & displayName & " — " & valMsg)
		return ""
		
	else if action starts with "🔁" then
		-- Sync Now: uses --vault-only so the agent applies simulation vault data to
		-- Contacts WITHOUT re-opening Chrome or re-scraping LinkedIn.
		-- The simulation run already stored the profile; --vault-only enforces that.
		if cSlug is "" then
			try
				set urlRes to (display dialog ("LinkedIn URL/slug for " & displayName & ":") default answer "https://www.linkedin.com/in/" buttons {"Cancel", "Sync"} default button "Sync" with title "LSAM — Sync Now")
				if button returned of urlRes is "Sync" then
					set cSlug to my lsamExtractLinkedInSlug(text returned of urlRes)
				end if
			end try
		end if
		if cSlug is not "" then
			set root to my getAgentRoot()
			set py to my getVenvPython()
			-- --vault-only: agent finds vault entry by contact_id resolved from --name,
			-- applies it to Contacts in FULL mode — no browser, no LinkedIn navigation.
			set syncCmd to "cd " & (quoted form of root) & " && LSAMC_ENGINE=PRO " & (quoted form of py) & " src/agent/pro_sync_agent.py --url " & (quoted form of cSlug) & " --name " & (quoted form of displayName) & " --mode FULL --vault-only >> logs/manual_sync.log 2>&1 &"
			try
				do shell script syncCmd
				display notification "Applying vault data to Contacts for " & displayName with title "LSAM — Sync Now"
				my lsamLog("OK", "Sync Now (vault-only) launched — " & displayName & " slug: " & cSlug)
			on error errMsg
				my lsamLog("ERROR", "Sync Now failed — " & displayName & ": " & errMsg)
				display notification "Launch failed: " & errMsg with title "LSAM — Error"
			end try
		else
			my lsamLog("WARN", "Sync Now skipped — no slug resolved for " & displayName)
		end if
		return ""

	else if action starts with "🔄" then
		-- Fresh Sync: full SIMULATION with browser (no --vault-only).
		-- Use this to bootstrap an empty vault or refresh stale data.
		-- Returns BACK so the caller exits review (data will be stale until sync finishes).
		if cSlug is "" then
			try
				set urlRes to (display dialog ("LinkedIn URL/slug for " & displayName & ":") default answer "https://www.linkedin.com/in/" buttons {"Cancel", "Sync"} default button "Sync" with title "LSAM — Fresh Sync")
				if button returned of urlRes is "Sync" then
					set cSlug to my lsamExtractLinkedInSlug(text returned of urlRes)
				end if
			on error
			end try
		end if
		if cSlug is not "" then
			set root to my getAgentRoot()
			set py to my getVenvPython()
			-- SIMULATION mode, surgical DOM extraction, bypass stealth time gate.
			-- Does NOT pass --vault-only so a fresh browser scrape always runs.
			set freshCmd to "cd " & (quoted form of root) & " && LSAMC_ENGINE=PRO LSAMC_IGNORE_HOURS=1 " & (quoted form of py) & " src/agent/pro_sync_agent.py --url " & (quoted form of cSlug) & " --name " & (quoted form of displayName) & " --mode SIMULATION --surgical >> logs/manual_sync.log 2>&1 &"
			try
				do shell script freshCmd
				display notification "Re-scraping LinkedIn for " & displayName & "… Check Review when done." with title "LSAM — Fresh Sync ▶"
				my lsamLog("OK", "Fresh Sync launched — " & displayName & " slug: " & cSlug)
			on error errMsg
				my lsamLog("ERROR", "Fresh Sync failed — " & displayName & ": " & errMsg)
				display notification "Launch failed: " & errMsg with title "LSAM — Error"
			end try
		else
			my lsamLog("WARN", "Fresh Sync skipped — no slug for " & displayName)
		end if
		return "BACK" -- exit review; vault data will be stale until sync finishes

	else if action starts with "🚀" then
		set promoteResult to my runCLI("--full promote", {"--selection"})
		set promoteMsg to my jsonGet(promoteResult, "message")
		if promoteMsg is "" then set promoteMsg to promoteResult
		display notification promoteMsg with title "LSAM — Promoted"
		my lsamLog("OK", "Promoted: " & displayName & " — " & promoteMsg)
		return ""
		
	else if action starts with "📸" then
		-- Apply Photo: vault-first (data/vault/<UUID>:ABPerson/linkedin.heic),
		-- fall back to most recent session backup by last-name match.
		set agentRoot to my getAgentRoot()
		set vaultPhotoPath to agentRoot & "/data/vault/" & abID & "/linkedin.heic"
		set photoPath to ""
		-- Primary: vault photo (written by every successful SIMULATION run)
		try
			set photoExists to do shell script "test -f " & (quoted form of vaultPhotoPath) & " && echo YES || echo NO"
			if photoExists is "YES" then set photoPath to vaultPhotoPath
		on error
		end try
		-- Fallback: most recent session backup heic, matched by last word of displayName
		if photoPath is "" then
			set lastName to last word of displayName
			set sessionsDir to agentRoot & "/logs/sessions"
			try
				set photoPath to do shell script "find " & (quoted form of sessionsDir) & " -name '*-linkedin.heic' -path '*" & lastName & "*' 2>/dev/null | sort -r | head -1"
			on error
				set photoPath to ""
			end try
		end if
		if photoPath is "" or photoPath is missing value then
			display notification "No backed-up photo found for " & displayName with title "LSAM — Apply Photo"
			my lsamLog("WARN", "Apply Photo: no heic found for " & displayName)
		else
			try
				tell application "Contacts"
					set p to person id abID
					set image of p to (read (POSIX file photoPath) as data)
					save
				end tell
				-- Derive a short label from the path (last path component)
				set photoLabel to do shell script "basename " & (quoted form of photoPath)
				display notification "Photo applied: " & photoLabel with title "LSAM — Photo Applied ✓"
				my lsamLog("OK", "Photo applied for " & displayName & " from: " & photoPath)
			on error imgErr number imgErrNum
				my lsamLog("ERROR", "Photo apply failed for " & displayName & " (" & imgErrNum & "): " & imgErr)
				display notification "Failed: " & imgErr with title "LSAM — Photo Error"
			end try
		end if
		return ""

	else if action starts with "⏭" then
		my lsamLog("INFO", "Skip: " & displayName & " — kept in list")
		return "SKIP"

	else if action starts with "🚪" then
		my lsamLog("INFO", "Back: exiting review at " & displayName)
		return "BACK"
	end if
	return ""
end processProfileReview

-- ── Handler: LinkedIn to Review triage loop (S5-B) ───────────────────────────
-- Implements "Triage Review" (menu item 2). ASOC group scan → choose from list →
-- processProfileReview dispatch. Pattern matches handleTriageDamaged.
on handleProfileReview()
	set groupName to "script-LSAM-LinkedIn to Review"
	repeat
		-- READ PATH: single CNContactStore round-trip via Pattern I
		-- v2.4.9: sortByStatus=true → [Ambiguous] first, then [No Block], alpha within each
		set scanResult to my scanAndSortGroup(groupName, true)
		set menuList to item 1 of scanResult
		set idList to item 2 of scanResult
		set reviewCount to count of menuList
		if reviewCount is 0 then
			display notification "LinkedIn to Review queue is empty." with title "LSAM"
			return
		end if
		set contactHeader to "LinkedIn to Review: " & reviewCount & " contacts" & return & "Select a contact to review its LinkedIn vault profile:"
		set pick to choose from list menuList with title "LSAM — Profile Review" with prompt contactHeader default items {item 1 of menuList} with empty selection allowed
		if pick is false then return
		set selName to item 1 of pick
		set selID to my getIDForSelection(selName, menuList, idList)
		if selID is missing value then
			display notification "Could not resolve contact ID. Rescanning." with title "LSAM"
		else
			set reviewResult to my processProfileReview(selID, selName, "")
			if reviewResult is "BACK" then return
		end if
	end repeat
end handleProfileReview

-- ── Handler: post-manual-sync review loop (v2.4.1) ──────────────────────────
-- Same UX as handleProfileReview but uses caller-supplied ID/name lists instead
-- of an ASOC group scan. Called after handleManualSync or from dashboard "Review Last Sync".
-- Mutable remainIDs/Names: processed contacts (result "") are removed each iteration.
-- Auto-exits when list is empty (last contact processed → no loop back to empty list).
-- Skip (result "SKIP") keeps contact in list. Back (result "BACK") exits immediately.
-- v2.4.7: slugList added — parallel to idList/nameList, carries pre-resolved LinkedIn slugs
-- from handleManualSync so Sync Now doesn't need to re-lookup social profiles (avoids
-- zombie/url-only profile failures that left cSlug empty and triggered slug prompt).
on handlePostSyncReview(idList, nameList, slugList)
	if (count of idList) is 0 then
		display notification "No contacts to review." with title "LSAM"
		return
	end if
	-- Work with mutable copies so processed contacts are removed
	set remainIDs to {}
	set remainNames to {}
	set remainSlugs to {}
	repeat with i from 1 to count of idList
		set end of remainIDs to item i of idList
		set end of remainNames to item i of nameList
		if (count of slugList) ≥ i then
			set end of remainSlugs to item i of slugList
		else
			set end of remainSlugs to ""
		end if
	end repeat
	repeat
		set remainCount to count of remainIDs
		if remainCount is 0 then
			display notification "All contacts reviewed." with title "LSAM — Post-Sync Review"
			my lsamLog("OK", "Post-sync review complete — all contacts processed")
			return
		end if
		set contactHeader to "Post-Sync Review — " & remainCount & " contact(s) remaining" & return & "Select a contact to review its sync result:"
		set pick to choose from list remainNames with title "LSAM — Post-Sync Review" with prompt contactHeader default items {item 1 of remainNames} with empty selection allowed
		if pick is false then return
		set selName to item 1 of pick
		-- Find index of selected name in remainNames
		set selIndex to 0
		repeat with i from 1 to remainCount
			if item i of remainNames is selName then
				set selIndex to i
				exit repeat
			end if
		end repeat
		if selIndex is 0 then
			display notification "Could not resolve contact." with title "LSAM"
		else
			set selID to item selIndex of remainIDs
			set selSlug to item selIndex of remainSlugs
			set reviewResult to my processProfileReview(selID, selName, selSlug)
			if reviewResult is "BACK" then return
			-- "" = processed (Validate / Sync Now / Promote) → remove from list
			-- "SKIP" = keep in list for this session
			if reviewResult is "" then
				set newIDs to {}
				set newNames to {}
				set newSlugs to {}
				repeat with i from 1 to remainCount
					if i is not selIndex then
						set end of newIDs to item i of remainIDs
						set end of newNames to item i of remainNames
						set end of newSlugs to item i of remainSlugs
					end if
				end repeat
				set remainIDs to newIDs
				set remainNames to newNames
				set remainSlugs to newSlugs
			end if
		end if
	end repeat
end handlePostSyncReview

-- ── Handler: triage DAMAGED queue (S3-B, Pattern I + Pattern E) ──────────────
-- ASOC scan (~200ms for full group), then choose from list inner loop
on handleTriageDamaged()
	set groupName to "script-LSAM-DAMAGED"
	repeat
		-- v2.4.9: sortByStatus=false → alpha by family name only
		-- READ PATH: single CNContactStore round-trip via Pattern I
		set scanResult to my scanAndSortGroup(groupName, false)
		set menuList to item 1 of scanResult
		set idList to item 2 of scanResult
		set dmgCount to count of menuList
		if dmgCount is 0 then
			display notification "DAMAGED queue is empty." with title "LSAM"
			return
		end if
		set contactHeader to "DAMAGED queue: " & dmgCount & " contacts" & return & "Select a contact to triage:"
		set pick to choose from list menuList with title "LSAM — Triage DAMAGED" with prompt contactHeader default items {item 1 of menuList} with empty selection allowed
		if pick is false then return
		set selName to item 1 of pick
		set selID to my getIDForSelection(selName, menuList, idList)
		if selID is missing value then
			display notification "Could not resolve contact ID. Rescanning." with title "LSAM"
		else
			my processTriageAction(selID, selName)
		end if
	end repeat
end handleTriageDamaged

-- ── Selection-context review loop ─────────────────────────────────────────────
-- Called from handleSelectionContext when user picks Review.
-- Iterates each selected contact through processProfileReview (same slug-resolution
-- pattern as handleManualSync). BACK exits loop; other actions continue to next.
on handleSelectionReview(selContacts)
	set totalCount to count of selContacts
	set idx to 0
	repeat with c in selContacts
		set idx to idx + 1
		set cName to ""
		set cID to ""
		set cSlug to ""
		tell application "Contacts"
			set cName to name of c
			set cID to id of c
			set sps to social profiles of c
			repeat with sp in sps
				set spSvc to ""
				set spUrl to ""
				try
					set spSvc to service name of sp as string
				end try
				try
					set spUrl to url of sp as string
				end try
				if (spSvc contains "linkedin") or (spUrl contains "linkedin") then
					set rawHandle to ""
					try
						set rawHandle to user name of sp as string
						if rawHandle is "missing value" then set rawHandle to ""
					on error
						set rawHandle to ""
					end try
					if rawHandle is "" and spUrl is not "" and spUrl is not "missing value" then
						set rawHandle to spUrl
					end if
					if rawHandle is not "" then
						set cSlug to my lsamExtractLinkedInSlug(rawHandle)
					end if
					exit repeat
				end if
			end repeat
		end tell
		my lsamLog("INFO", "Selection Review [" & idx & "/" & totalCount & "] " & cName & " slug: " & cSlug)
		set reviewResult to my processProfileReview(cID, cName, cSlug)
		if reviewResult is "BACK" then exit repeat
	end repeat
end handleSelectionReview

-- ── Selection-context dialog (shown at launch when contacts are pre-selected) ──
-- selContacts: list of contact objects from `tell application "Contacts" to its selection`.
-- Returns true  → caller should proceed to mainDashboard (Full Menu or post-action).
-- Returns false → user cancelled; caller should exit.
on handleSelectionContext(selContacts)
	set selCount to count of selContacts
	set _N to 15 -- list names individually below this threshold
	-- Build dialog prompt: "X contact(s) selected: •Name •Name …"
	set selHeader to "" & selCount & " contact"
	if selCount > 1 then set selHeader to selHeader & "s"
	set selHeader to selHeader & " selected in Contacts.app"
	if selCount <= _N then
		set selHeader to selHeader & ":" & return
		tell application "Contacts"
			repeat with c in selContacts
				set selHeader to selHeader & "  • " & (name of c) & return
			end repeat
		end tell
	end if
	set selHeader to selHeader & return & "Choose action:"
	set selActions to {¬
		"🔄 Sync — scrape from LinkedIn + write vault (SIMULATION)", ¬
		"🔍 Review — browse vault & apply data for each", ¬
		"🚀 Promote → Priority queue", ¬
		"🛑 Demote ← Priority queue", ¬
		"📋 Full Menu — open main dashboard", ¬
		"🚪 Cancel"}
	set selPick to choose from list selActions with title "LSAM v" & _pVersion & " — Selection" with prompt selHeader default items {item 1 of selActions}
	if selPick is false then return false
	set selAction to item 1 of selPick
	if selAction starts with "🔄" then
		-- Direct SIMULATION sync — no mode picker, uses already-known selection.
		-- Reads LinkedIn slug from social profile or prompts per contact.
		set root to my getAgentRoot()
		set py to my getVenvPython()
		set launchedCount to 0
		set idx to 0
		set totalSel to count of selContacts
		set launchedIDs to {}
		set launchedNames to {}
		set launchedSlugs to {}
		tell application "Contacts"
			repeat with c in selContacts
				set idx to idx + 1
				set cName to name of c
				set cID to id of c
				set cSlug to ""
				set sps to social profiles of c
				repeat with sp in sps
					set spSvc to ""
					set spUrl to ""
					try
						set spSvc to service name of sp as string
					end try
					try
						set spUrl to url of sp as string
					end try
					if (spSvc contains "linkedin") or (spUrl contains "linkedin") then
						set rawH to ""
						try
							set rawH to user name of sp as string
							if rawH is "missing value" then set rawH to ""
						on error
							set rawH to ""
						end try
						if rawH is "" and spUrl is not "" and spUrl is not "missing value" then set rawH to spUrl
						if rawH is not "" then set cSlug to my lsamExtractLinkedInSlug(rawH)
						exit repeat
					end if
				end repeat
				if cSlug is "" then
					try
						set urlDlg to (display dialog ("LinkedIn URL for " & cName & ":") default answer "https://www.linkedin.com/in/" buttons {"Skip", "Sync"} default button "Sync" with title "LSAM — Sync [" & idx & "/" & totalSel & "]")
						if button returned of urlDlg is "Sync" then set cSlug to my lsamExtractLinkedInSlug(text returned of urlDlg)
					on error
					end try
				end if
				if cSlug is not "" then
					set syncCmd to "cd " & (quoted form of root) & " && LSAMC_ENGINE=PRO LSAMC_IGNORE_HOURS=1 " & (quoted form of py) & " src/agent/pro_sync_agent.py --url " & (quoted form of cSlug) & " --name " & (quoted form of cName) & " --mode SIMULATION --surgical >> logs/manual_sync.log 2>&1 &"
					try
						do shell script syncCmd
						set launchedCount to launchedCount + 1
						set end of launchedIDs to cID
						set end of launchedNames to cName
						set end of launchedSlugs to cSlug
						my lsamLog("OK", "Selection Sync launched: " & cName & " — " & cSlug)
					on error errMsg
						my lsamLog("ERROR", "Selection Sync failed: " & cName & " — " & errMsg)
					end try
				else
					my lsamLog("WARN", "Selection Sync skipped (no URL): " & cName)
				end if
			end repeat
		end tell
		-- Store for "Review Last Sync" (menu item 0b)
		set _pLastSyncedIDs to launchedIDs
		set _pLastSyncedNames to launchedNames
		set _pLastSyncedSlugs to launchedSlugs
		display notification "▶ " & launchedCount & " of " & totalSel & " sync(s) launched. Review when done." with title "LSAM — Selection Sync"
		return true
	else if selAction starts with "🔍" then
		my handleSelectionReview(selContacts)
		return true
	else if selAction starts with "🚀" then
		set promResult to my runCLI("--full promote", {"--selection"})
		set promMsg to my jsonGet(promResult, "message")
		if promMsg is "" then set promMsg to promResult
		display notification promMsg with title "LSAM — Promoted"
		my lsamLog("OK", "Selection promoted: " & promMsg)
		return true
	else if selAction starts with "🛑" then
		set demResult to my runCLI("--full demote", {"--selection"})
		set demMsg to my jsonGet(demResult, "message")
		if demMsg is "" then set demMsg to demResult
		display notification demMsg with title "LSAM — Demoted"
		my lsamLog("OK", "Selection demoted: " & demMsg)
		return true
	else if selAction starts with "📋" then
		return true
	else
		-- Cancel
		return false
	end if
end handleSelectionContext

-- ══════════════════════════════════════════════════════════════════════════════
-- v3.0 NEW HANDLERS: Preview, Edit Override, shared helpers
-- Sprint 7 of LSAM v5.0 Redesign (PLAN_2026-03-29_LSAM_V5_REDESIGN.md)
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Shared helper: resolve LinkedIn slug for a contact (deduplicated) ────────
-- Tries: social profile URL → vault lookup → user prompt. Returns slug or "".
on resolveSlugForContact(contactID, contactName)
	set cURL to ""
	-- 1. Try social profile in Contacts.app
	tell application "Contacts"
		try
			set p to person id contactID
			set sps to social profiles of p
			repeat with sp in sps
				set spSvc to ""
				set spUrl to ""
				try
					set spSvc to service name of sp as string
				end try
				try
					set spUrl to url of sp as string
				end try
				if (spSvc contains "linkedin") or (spUrl contains "linkedin") then
					set rawHandle to ""
					try
						set rawHandle to user name of sp as string
						if rawHandle is "missing value" then set rawHandle to ""
					on error
						set rawHandle to ""
					end try
					if rawHandle is "" then
						if spUrl is not "" and spUrl is not "missing value" then set rawHandle to spUrl
					end if
					if rawHandle is not "" then
						set cURL to my lsamExtractLinkedInSlug(rawHandle)
					end if
					exit repeat
				end if
			end repeat
		end try
	end tell
	-- 2. Try vault profile via CLI
	if cURL is "" then
		try
			set profileResult to my runCLI("profile", {"--contact-id", contactID, "--json"})
			set vaultURL to my jsonGet(profileResult, "linkedin_url")
			if vaultURL is not "" and vaultURL is not "None" then
				set cURL to my lsamExtractLinkedInSlug(vaultURL)
			end if
		end try
	end if
	-- 3. Prompt user as last resort
	if cURL is "" then
		try
			set urlRes to (display dialog ("LinkedIn URL for " & contactName & ":") default answer "https://www.linkedin.com/in/" buttons {"Skip", "Use"} default button "Use" with title "LSAM — Slug Resolution")
			if (button returned of urlRes is "Use") then
				set cURL to my lsamExtractLinkedInSlug(text returned of urlRes)
			end if
		on error
			set cURL to ""
		end try
	end if
	return cURL
end resolveSlugForContact

-- ── Shared helper: launch sync agent for one contact ────────────────────────
-- Returns true on launch success, false on failure.
on launchSyncAgent(contactName, slug, syncMode, vaultOnly)
	set root to my getAgentRoot()
	set py to my getVenvPython()
	set vaultFlag to ""
	if vaultOnly then set vaultFlag to " --vault-only"
	set msCmd to "cd " & (quoted form of root) & " && LSAMC_ENGINE=PRO LSAMC_IGNORE_HOURS=1 " & (quoted form of py) & " src/agent/pro_sync_agent.py --url " & (quoted form of slug) & " --name " & (quoted form of contactName) & " --mode " & syncMode & " --surgical" & vaultFlag & " >> logs/manual_sync.log 2>&1 &"
	try
		do shell script msCmd
		return true
	on error errMsg
		my lsamLog("ERROR", "Launch FAILED — " & contactName & ": " & errMsg)
		return false
	end try
end launchSyncAgent

-- ── v3.0 handler: Preview selected contacts (non-destructive diff review) ──
-- For each contact:
--   1. Select it in Contacts.app (user sees the contact card)
--   2. Fetch vault diff via Python CLI (preview --contact-id UUID --json)
--   3. Display structured dialog: each proposed change with → arrows
--   4. User chooses: Apply (sync now) / Edit (field overrides) / Skip / Back
-- Non-destructive: no writes until user explicitly clicks Apply.
-- Idempotent: running preview multiple times produces the same diff.
on handlePreviewSelected(selContacts)
	set totalCount to count of selContacts
	if totalCount is 0 then
		display notification "No contacts selected." with title "LSAM"
		return
	end if
	my lsamLog("INFO", "Preview: " & totalCount & " contact(s)")
	set previewedIDs to {}
	set previewedNames to {}
	set previewedSlugs to {}
	repeat with i from 1 to totalCount
		set c to item i of selContacts
		set cName to ""
		set cID to ""
		tell application "Contacts"
			set cName to name of c
			set cID to id of c
		end tell

		-- Step 1: Select the contact in Contacts.app so user sees the card
		tell application "Contacts"
			activate
			try
				set selection to {person id cID}
			on error
				-- Fallback: just activate Contacts.app
			end try
		end tell
		delay 0.3 -- brief pause for Contacts.app to render

		-- Step 2: Fetch preview diff from Python CLI
		set previewResult to my runCLI("preview", {"--contact-id", cID, "--json"})
		set prevSuccess to my jsonGet(previewResult, "success")

		if prevSuccess is "True" then
			-- Step 3: Extract structured display text from CLI output
			set displayText to my jsonGet(previewResult, "display_text")
			set hasChanges to my jsonGet(previewResult, "has_changes")

			-- Fallback if display_text extraction failed
			if displayText is "" then
				set vaultName to my jsonGet(previewResult, "vault_name")
				set displayText to "Vault: " & vaultName & return & "(diff detail unavailable — raw output below)" & return & return
				if (length of previewResult) > 400 then
					set displayText to displayText & (text 1 thru 400 of previewResult) & "…"
				else
					set displayText to displayText & previewResult
				end if
			end if

			-- Step 4: Action dialog — user sees contact card + diff side by side
			if hasChanges is "True" then
				set actionItems to {"✅ Apply (Sync Now)", "✏️ Edit Override", "⏭ Skip", "🚪 Back"}
			else
				-- No changes: Apply is less relevant, Skip is default
				set actionItems to {"⏭ Skip (no changes)", "✅ Force Apply", "✏️ Edit Override", "🚪 Back"}
			end if

			set actionPick to choose from list actionItems with title "LSAM Preview [" & i & "/" & totalCount & "] — " & cName with prompt displayText default items {item 1 of actionItems}

			if actionPick is false then exit repeat
			set actionChoice to item 1 of actionPick

			if actionChoice starts with "✅" then
				-- Apply: run Sync Now (vault-only, FULL mode) — the only write path
				set slug to my resolveSlugForContact(cID, cName)
				if slug is not "" then
					my launchSyncAgent(cName, slug, "FULL", true)
					set end of previewedIDs to cID
					set end of previewedNames to cName
					set end of previewedSlugs to slug
					my lsamLog("OK", "Preview → Apply: " & cName)
					display notification "✓ Applied: " & cName with title "LSAM Preview"
				else
					my lsamLog("WARN", "Preview → Apply: no slug resolved for " & cName)
					display notification "⚠️ No LinkedIn slug for " & cName with title "LSAM Preview"
				end if
			else if actionChoice starts with "✏️" then
				-- Edit: prompt for field overrides
				my handleEditOverride(cID, cName)
				set end of previewedIDs to cID
				set end of previewedNames to cName
				set end of previewedSlugs to ""
			else if actionChoice starts with "🚪" then
				my lsamLog("INFO", "Preview: user chose Back at contact " & i & "/" & totalCount)
				exit repeat
			end if
			-- Skip (⏭): just continue to next contact
		else
			-- No vault entry for this contact
			set errMsg to my jsonGet(previewResult, "error")
			if errMsg is "" then set errMsg to "No vault data available for this contact."
			set noVaultPick to choose from list {"🔄 Fresh Sync (SIMULATION)", "⏭ Skip", "🚪 Back"} with title "LSAM Preview [" & i & "/" & totalCount & "]" with prompt cName & return & return & errMsg default items {"⏭ Skip"}
			if noVaultPick is not false then
				set nvChoice to item 1 of noVaultPick
				if nvChoice starts with "🔄" then
					-- Launch fresh simulation sync to populate vault
					set slug to my resolveSlugForContact(cID, cName)
					if slug is not "" then
						my launchSyncAgent(cName, slug, "SIMULATION", false)
						set end of previewedIDs to cID
						set end of previewedNames to cName
						set end of previewedSlugs to slug
						my lsamLog("OK", "Preview → Fresh Sync: " & cName)
					end if
				else if nvChoice starts with "🚪" then
					exit repeat
				end if
			else
				exit repeat
			end if
		end if
	end repeat
	-- Store for "Review Last Session"
	if (count of previewedIDs) > 0 then
		set _pLastSyncedIDs to previewedIDs
		set _pLastSyncedNames to previewedNames
		set _pLastSyncedSlugs to previewedSlugs
	end if
	-- v3.0: Log preview/apply session to MBP Dev Monitor calendar
	if (count of previewedNames) > 0 then
		set nameCSV to ""
		repeat with i from 1 to (count of previewedNames)
			if i > 1 then set nameCSV to nameCSV & ","
			set nameCSV to nameCSV & (item i of previewedNames)
		end repeat
		try
			my runCLI("log-session", {"--names", nameCSV, "--mode", "PREVIEW"})
		on error
			my lsamLog("WARN", "Calendar logging failed (non-critical)")
		end try
	end if
	display notification "Preview complete: " & (count of previewedIDs) & " processed." with title "LSAM"
end handlePreviewSelected

-- ── v3.0 handler: Edit field overrides in vault ─────────────────────────────
on handleEditOverride(contactID, contactName)
	try
		set overrideInput to text returned of (display dialog "Enter field=value overrides for " & contactName & ":" & return & "(e.g., first_name=Benoit last_name=Deleury)" default answer "" with title "LSAM — Edit Override" buttons {"Cancel", "Apply"} default button "Apply")
		if overrideInput is "" then return
		-- Split by spaces and pass as separate args
		set editResult to my runCLI("edit", {"--contact-id", contactID, overrideInput})
		my lsamLog("OK", "Edit override applied for " & contactName & ": " & editResult)
		display notification "Override applied for " & contactName with title "LSAM"
	on error
		-- User cancelled
	end try
end handleEditOverride

-- ── Shared helper: get group count with fallback to legacy name ─────────────
on lsamGetGroupCount(newName, legacyName)
	set cnt to my lsamGetMemberCountForGroup(newName)
	if cnt is 0 then
		set cnt to my lsamGetMemberCountForGroup(legacyName)
	end if
	return cnt
end lsamGetGroupCount

-- ── Main dashboard loop (Pattern E, fixes F6) ────────────────────────────────
on mainDashboard()
	-- v2.4.10: Check for pre-selected contacts in Contacts.app.
	-- If found, show focused selection-context dialog before the main menu.
	set _startupSel to {}
	try
		tell application "Contacts"
			set _startupSel to its selection
		end tell
	on error
	end try
	if (count of _startupSel) > 0 then
		my lsamLog("INFO", "Startup: " & (count of _startupSel) & " contact(s) pre-selected — showing selection context")
		set _goMain to my handleSelectionContext(_startupSel)
		if not _goMain then
			my lsamLog("INFO", "Selection context: user cancelled — exiting")
			return
		end if
	end if
	repeat
		-- UTILITY PATH: PID check
		set pid to my getBackendPID()
		if pid is "0" then
			set backendLabel to "[Off]"
		else
			set backendLabel to "[On] PID:" & pid
		end if
		
		-- READ PATH: live ASOC counts (~200ms each, no Python startup)
		-- v3.0: Use new LSAM-* group names with fallback to legacy script-LSAM-*
		set queueCount to my lsamGetGroupCount("LSAM-Queue", "script-LSAM-Priority")
		set revCount to my lsamGetGroupCount("LSAM-Review", "script-LSAM-LinkedIn to Review")
		set goldenCount to my lsamGetGroupCount("LSAM-Golden", "script-LSAM-Golden Record")

		set promptMsg to "Backend: " & backendLabel & return & return & "Queue: " & queueCount & "  |  Review: " & revCount & "  |  Golden: " & goldenCount

		set lastSyncCount to count of _pLastSyncedNames
		-- Contextual Start/Stop
		if pid is "0" then
			set supervisorItem to "▶️  6. Start Supervisor"
		else
			set supervisorItem to "⏹  6. Stop Supervisor"
		end if
		set menuItems to {"📋 1. Preview Selected", "🔄 2. Sync Selected", "📝 3. Review Queue (" & revCount & ")", "🔍 4. Review Last Session (" & lastSyncCount & ")", "⚙️  5. More...", supervisorItem, "🚪 7. Exit"}

		set response to choose from list menuItems with title "LSAM Control Center v" & _pVersion with prompt promptMsg default items {item 1 of menuItems}
		
		if response is false then exit repeat
		set choice to item 1 of response
		
		-- v3.0 dispatch table
		if choice starts with "📋 1." then
			-- Preview Selected: dry-run diff for contacts selected in Contacts.app
			set selContacts to {}
			try
				tell application "Contacts" to set selContacts to its selection
			end try
			if (count of selContacts) is 0 then
				display notification "Select contact(s) in Contacts.app first." with title "LSAM"
			else
				my handlePreviewSelected(selContacts)
			end if

		else if choice starts with "🔄 2." then
			-- Sync Selected: existing Manual Sync flow
			my handleManualSync()

		else if choice starts with "📝 3." then
			-- Review Queue: browse LSAM-Review group (Profile Review)
			my handleProfileReview()

		else if choice starts with "🔍 4." then
			-- Review Last Session: post-sync/preview review
			if (count of _pLastSyncedNames) is 0 then
				display notification "No last session data. Run Preview or Sync first." with title "LSAM"
			else
				my handlePostSyncReview(_pLastSyncedIDs, _pLastSyncedNames, _pLastSyncedSlugs)
			end if

		else if choice starts with "⚙️" then
			-- More... sub-menu (v3.0: consolidated infrequent actions)
			set moreItems to {"🚀 Promote Selection → Queue", "🛑 Demote Selection ← Queue", "✏️ Edit Override (by name)", "🔍 Inspect Contact Archive", "🧬 Profile Review (by name)", "🎂 Refresh Birthday Cache", "📊 Status", "🚪 Back"}
			set morePick to choose from list moreItems with title "LSAM — More" with prompt "Additional operations:" default items {item 1 of moreItems}
			if morePick is not false then
				set moreChoice to item 1 of morePick
				if moreChoice starts with "🚀" then
					set cmdResult to my runCLI("--full promote", {"--selection"})
					display dialog cmdResult with title "Promotion Result" buttons {"OK"} default button "OK"
				else if moreChoice starts with "🛑" then
					set cmdResult to my runCLI("--full demote", {"--selection"})
					display dialog cmdResult with title "Demotion Result" buttons {"OK"} default button "OK"
				else if moreChoice starts with "✏️" then
					try
						set editName to text returned of (display dialog "Contact name for edit override:" default answer "" with title "LSAM — Edit" buttons {"Cancel", "Edit"} default button "Edit")
						if editName is not "" then
							-- Resolve contact ID from vault
							set profileResult to my runCLI("profile", {"--name", quoted form of editName, "--json"})
							set lookupSuccess to my jsonGet(profileResult, "success")
							if lookupSuccess is "True" then
								set foundID to my jsonGet(profileResult, "contact_id")
								set foundName to my jsonGet(profileResult, "full_name")
								my handleEditOverride(foundID, foundName)
							else
								display notification "Contact not found in vault." with title "LSAM"
							end if
						end if
					end try
				else if moreChoice starts with "🔍" then
					try
						set inspName to text returned of (display dialog "Contact name to inspect:" default answer "" with title "LSAM — Inspect" buttons {"Cancel", "Inspect"} default button "Inspect")
						set inspResult to my runCLI("inspect", {quoted form of inspName})
						display dialog inspResult with title "Archive History: " & inspName buttons {"OK"} default button "OK"
					end try
				else if moreChoice starts with "🧬" then
					try
						set reviewName to text returned of (display dialog "Contact name for LinkedIn vault review:" default answer "" with title "LSAM — Profile Review" buttons {"Cancel", "Review"} default button "Review")
						if reviewName is not "" then
							set profileResult to my runCLI("profile", {"--name", quoted form of reviewName, "--json"})
							set lookupSuccess to my jsonGet(profileResult, "success")
							if lookupSuccess is "True" then
								set foundID to my jsonGet(profileResult, "contact_id")
								set foundName to my jsonGet(profileResult, "full_name")
								if foundName is "" then set foundName to reviewName
								my processProfileReview(foundID, foundName, "")
							else
								set errMsg to my jsonGet(profileResult, "message")
								if errMsg is "" then set errMsg to profileResult
								display notification errMsg with title "LSAM — Profile Not Found"
							end if
						end if
					end try
				else if moreChoice starts with "🎂" then
					-- Rebuild birthday cache from Contacts.app (15-30 min)
					display notification "Rebuilding birthday cache… this may take 15-30 minutes." with title "LSAM"
					set root to my getAgentRoot()
					set py to my getVenvPython()
					try
						do shell script "cd " & (quoted form of root) & " && " & (quoted form of py) & " scripts/birthday_trigger.py --refresh-cache >> logs/manual_sync.log 2>&1 &"
						display notification "Birthday cache rebuild started in background." with title "LSAM"
					on error errMsg
						display notification "Failed: " & errMsg with title "LSAM"
					end try
				else if moreChoice starts with "📊" then
					set cmdResult to my runCLI("status", {})
					display dialog cmdResult with title "LSAM Project Status" buttons {"OK"} default button "OK"
				end if
			end if

		else if choice starts with "▶️" then
			my handleBackendStart()

		else if choice starts with "⏹" then
			my lsamLog("WARN", "Stopping supervisor (PID " & pid & ")...")
			my handleBackendStop(pid)

		else if choice starts with "🚪 7." then
			exit repeat
		end if
	end repeat
end mainDashboard

-- ── Entry point ───────────────────────────────────────────────────────────────
my lsamLog("INFO", "LSAM Control Center v" & _pVersion & " — starting")
my mainDashboard()
