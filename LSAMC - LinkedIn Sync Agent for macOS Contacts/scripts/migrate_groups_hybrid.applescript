-- migrate_groups_hybrid.applescript — Hybrid ASOC/AppleScript Group Migration
-- Version: 1.0.0
-- Purpose: Fast group migration using ASOC for reads + AppleScript for writes.
--          CNContactStore reads are ~200ms (batch). AppleScript writes use
--          batch add (all contacts added then one save) instead of save-per-contact.
-- Safety: Additive only. Never deletes groups or contacts (MORENO_GUARD).
-- Why hybrid: CNSaveRequest addMember:toGroup: fails with CoreData 134092 on
--             iCloud-backed contacts (container mismatch between CNContactStore
--             and Contacts.app scripting layer). Plain AppleScript writes are
--             the only reliable path for iCloud groups.
--
-- Performance: ~5-15s per group (vs ~30-90 min with save-per-contact)
--
-- Author: Claude Opus 4.6 (1M context) | 2026-03-29

use framework "Foundation"
use framework "Contacts"
use scripting additions

-- ── ASOC: Fast batch read of contact IDs from a group ────────────────────────
on getContactIDsFromGroup(groupName)
	set cs to current application's CNContactStore's alloc()'s init()
	set {allGroups, gErr} to cs's groupsMatchingPredicate:(missing value) |error|:(reference)
	if allGroups is missing value then return {}

	set targetID to missing value
	repeat with grp in allGroups
		if (grp's |name|() as text) is groupName then
			set targetID to grp's identifier()
			exit repeat
		end if
	end repeat
	if targetID is missing value then return {}

	set keys to current application's NSArray's arrayWithArray:{current application's CNContactIdentifierKey}
	set pred to (current application's CNContact's predicateForContactsInGroupWithIdentifier:targetID)
	set {contacts, fetchErr} to (cs's unifiedContactsMatchingPredicate:pred keysToFetch:keys |error|:(reference))
	if contacts is missing value then return {}

	set idList to {}
	repeat with c in contacts
		set end of idList to (c's identifier() as text)
	end repeat
	return idList
end getContactIDsFromGroup

-- ── AppleScript: Batch add contacts to a group (one save at the end) ─────────
on batchAddToGroup(contactIDs, targetGroupName)
	set total to count of contactIDs
	if total is 0 then return 0

	tell application "Contacts"
		-- Ensure target group exists
		try
			set tg to group targetGroupName
		on error
			make new group with properties {name:targetGroupName}
			save
			set tg to group targetGroupName
		end try

		-- Batch add (no save between adds)
		set added to 0
		repeat with cid in contactIDs
			try
				set p to person id (cid as text)
				add p to tg
				set added to added + 1
			on error
				-- Contact not found or already in group — skip silently
			end try
		end repeat

		-- Single save for entire batch
		if added > 0 then save
	end tell
	return added
end batchAddToGroup

-- ── Migration handler ────────────────────────────────────────────────────────
on migrateGroup(sourceGroupName, targetGroupName)
	log "── " & sourceGroupName & " → " & targetGroupName
	set contactIDs to my getContactIDsFromGroup(sourceGroupName)
	set total to count of contactIDs
	log "  Source: " & total & " contacts"
	if total is 0 then
		log "  (empty or not found — skipping)"
		return 0
	end if
	set added to my batchAddToGroup(contactIDs, targetGroupName)
	log "  ✅ Added " & added & "/" & total
	return added
end migrateGroup

-- ── Main ─────────────────────────────────────────────────────────────────────
on run
	log "═══ LSAM Group Migration (Hybrid ASOC/AppleScript) ═══"
	log "Started: " & (current date) as text

	set totalMigrated to 0

	-- Direct-mapped migrations
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Priority", "LSAM-Queue"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Force-Refresh", "LSAM-Queue"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Golden Record", "LSAM-Golden"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Tier3-NeedAttention", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-LinkedIn to Review", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Search-Failed", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Broken Names", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-Exempted", "LSAM-Exempted"))

	-- DAMAGED → LSAM-Damaged (entire group — vault audit already done in Python)
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-DAMAGED", "LSAM-Damaged"))

	-- 7mars archive groups → LSAM-Golden (they were one-off session artifacts)
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-7 mars session", "LSAM-Golden"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-7mars-formatOK", "LSAM-Golden"))
	set totalMigrated to totalMigrated + (my migrateGroup("script-LSAM-7mars-orphans", "LSAM-Golden"))

	-- Verification
	log ""
	log "── Verification ──"
	set newGroups to {"LSAM-Queue", "LSAM-Review", "LSAM-Golden", "LSAM-Damaged", "LSAM-Exempted", "LSAM-Birthday"}
	repeat with gName in newGroups
		set ids to my getContactIDsFromGroup(gName)
		log "  " & gName & ": " & (count of ids) & " contacts"
	end repeat

	log ""
	log "═══ Migration Complete ═══"
	log "Total contact-group additions: " & totalMigrated
	log "Finished: " & (current date) as text

	return "Migration complete. " & totalMigrated & " additions."
end run
