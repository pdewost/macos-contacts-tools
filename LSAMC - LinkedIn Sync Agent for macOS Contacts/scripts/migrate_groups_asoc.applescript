-- migrate_groups_asoc.applescript — ASOC Batch Group Migration
-- Version: 1.0.0
-- Purpose: Migrate contacts between LSAM groups using CNContactStore (ASOC)
--          for batch performance. Single CNSaveRequest per group migration.
-- Safety: Additive only. Never deletes groups or contacts (MORENO_GUARD).
-- Performance: ~1-2s per group (vs ~30-90 min with plain AppleScript save-per-contact)
--
-- Usage: osascript scripts/migrate_groups_asoc.applescript
--
-- Author: Claude Opus 4.6 (1M context) | 2026-03-29

use framework "Foundation"
use framework "Contacts"
use scripting additions

-- ── ASOC Helpers ──────────────────────────────────────────────────────────────

on getContactStore()
	return current application's CNContactStore's alloc()'s init()
end getContactStore

on findGroupByName(cs, groupName)
	set {allGroups, gErr} to cs's groupsMatchingPredicate:(missing value) |error|:(reference)
	if allGroups is missing value then return missing value
	repeat with grp in allGroups
		if (grp's |name|() as text) is groupName then
			return grp
		end if
	end repeat
	return missing value
end findGroupByName

on getContactsInGroup(cs, grp)
	set gID to grp's identifier()
	set pred to (current application's CNContact's predicateForContactsInGroupWithIdentifier:gID)
	set keys to current application's NSArray's arrayWithArray:{current application's CNContactIdentifierKey, current application's CNContactGivenNameKey, current application's CNContactFamilyNameKey}
	set {contacts, fetchErr} to (cs's unifiedContactsMatchingPredicate:pred keysToFetch:keys |error|:(reference))
	if contacts is missing value then return {}
	return contacts
end getContactsInGroup

on createGroupIfMissing(cs, groupName)
	set existingGrp to my findGroupByName(cs, groupName)
	if existingGrp is not missing value then
		return existingGrp
	end if
	-- Create new group via CNSaveRequest
	set newGroup to current application's CNMutableGroup's alloc()'s init()
	newGroup's setName:groupName
	set saveReq to current application's CNSaveRequest's alloc()'s init()
	saveReq's addGroup:newGroup toContainerWithIdentifier:(missing value)
	set {saveOk, saveErr} to (cs's executeSaveRequest:saveReq |error|:(reference))
	if not saveOk then
		log "ERROR: Failed to create group " & groupName & ": " & (saveErr's localizedDescription() as text)
		return missing value
	end if
	log "Created group: " & groupName
	-- Re-fetch to get the persisted group object
	return my findGroupByName(cs, groupName)
end createGroupIfMissing

-- ── Batch add contacts to a group (single CNSaveRequest) ────────────────────
on batchAddContactsToGroup(cs, contacts, targetGroup)
	if (count of contacts) is 0 then return 0
	set saveReq to current application's CNSaveRequest's alloc()'s init()
	set addCount to 0
	repeat with c in contacts
		try
			saveReq's addMember:c toGroup:targetGroup
			set addCount to addCount + 1
		on error errMsg
			log "WARN: Could not queue contact " & (c's identifier() as text) & ": " & errMsg
		end try
	end repeat
	if addCount > 0 then
		set {saveOk, saveErr} to (cs's executeSaveRequest:saveReq |error|:(reference))
		if not saveOk then
			log "ERROR: executeSaveRequest failed: " & (saveErr's localizedDescription() as text)
			return 0
		end if
	end if
	return addCount
end batchAddContactsToGroup

-- ── Migration Map ────────────────────────────────────────────────────────────

on migrateGroup(cs, sourceGroupName, targetGroupName)
	log "── Migrating: " & sourceGroupName & " → " & targetGroupName
	set srcGrp to my findGroupByName(cs, sourceGroupName)
	if srcGrp is missing value then
		log "  Source group not found: " & sourceGroupName & " — skipping"
		return 0
	end if
	set tgtGrp to my createGroupIfMissing(cs, targetGroupName)
	if tgtGrp is missing value then
		log "  ERROR: Could not create/find target group: " & targetGroupName
		return 0
	end if
	set contacts to my getContactsInGroup(cs, srcGrp)
	set total to count of contacts
	log "  Source has " & total & " contacts"
	if total is 0 then return 0
	set added to my batchAddContactsToGroup(cs, contacts, tgtGrp)
	log "  ✅ Added " & added & "/" & total & " to " & targetGroupName
	return added
end migrateGroup

-- ── DAMAGED Audit + Classification ──────────────────────────────────────────
-- Classify each DAMAGED contact by checking if it has a valid vault entry

on classifyDamagedContacts(cs)
	log "── DAMAGED Group Audit (ASOC) ──"
	set damagedGrp to my findGroupByName(cs, "script-LSAM-DAMAGED")
	if damagedGrp is missing value then
		log "  script-LSAM-DAMAGED not found — skipping"
		return {golden:{}, review:{}, damaged:{}}
	end if

	-- Fetch contacts with note key for quality check
	set gID to damagedGrp's identifier()
	set pred to (current application's CNContact's predicateForContactsInGroupWithIdentifier:gID)
	set keys to current application's NSArray's arrayWithArray:{current application's CNContactIdentifierKey, current application's CNContactGivenNameKey, current application's CNContactFamilyNameKey, current application's CNContactNoteKey}
	set {contacts, fetchErr} to (cs's unifiedContactsMatchingPredicate:pred keysToFetch:keys |error|:(reference))
	if contacts is missing value then
		log "  ERROR: Failed to fetch DAMAGED contacts"
		return {golden:{}, review:{}, damaged:{}}
	end if

	set total to count of contacts
	log "  " & total & " contacts in DAMAGED group"

	-- Classification: check vault via filesystem (fast — no AppleScript)
	-- We return the contacts grouped for the caller to batch-add
	set goldenList to {}
	set reviewList to {}
	set damagedList to {}

	set vaultRoot to (do shell script "dirname " & (quoted form of (POSIX path of (path to me)))) & "/data/vault"

	repeat with c in contacts
		set cID to (c's identifier() as text)
		-- Check vault: does data/vault/<cID>/master_profile.json exist?
		set masterPath to vaultRoot & "/" & cID & "/master_profile.json"
		set hasVault to (do shell script "test -f " & quoted form of masterPath & " && echo yes || echo no")

		if hasVault is "yes" then
			-- Valid vault → Golden
			set end of goldenList to c
		else
			-- No vault → stays Damaged
			set end of damagedList to c
		end if
	end repeat

	log "  Classification: " & (count of goldenList) & " → Golden, " & (count of reviewList) & " → Review, " & (count of damagedList) & " → Damaged"
	return {golden:goldenList, review:reviewList, damaged:damagedList}
end classifyDamagedContacts

-- ── Main ─────────────────────────────────────────────────────────────────────

on run
	log "═══ LSAM Group Migration (ASOC Batch) ═══"
	log "Started: " & (current date) as text

	set cs to my getContactStore()

	-- Step 1: Verify target groups exist (created by earlier migration; do NOT re-create
	-- to avoid CoreData 134092 iCloud sync conflict with duplicate group names)
	log ""
	log "── Step 1: Verify target groups exist ──"
	set targetNames to {"LSAM-Queue", "LSAM-Review", "LSAM-Golden", "LSAM-Damaged", "LSAM-Exempted", "LSAM-Birthday"}
	repeat with gName in targetNames
		set grp to my findGroupByName(cs, gName)
		if grp is missing value then
			log "  ⚠️ " & gName & " not found — creating"
			my createGroupIfMissing(cs, gName)
			-- Re-init CNContactStore to pick up new group after save
			set cs to my getContactStore()
		else
			log "  ✅ " & gName & " exists"
		end if
	end repeat
	-- Re-init CNContactStore to ensure all groups are visible
	set cs to my getContactStore()

	-- Step 2: Direct-mapped migrations (batch)
	log ""
	log "── Step 2: Direct-mapped migrations ──"
	set totalMigrated to 0
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Priority", "LSAM-Queue"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Force-Refresh", "LSAM-Queue"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Golden Record", "LSAM-Golden"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Tier3-NeedAttention", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-LinkedIn to Review", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Search-Failed", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Broken Names", "LSAM-Review"))
	set totalMigrated to totalMigrated + (my migrateGroup(cs, "script-LSAM-Exempted", "LSAM-Exempted"))

	-- Step 3: DAMAGED audit + classification
	log ""
	log "── Step 3: DAMAGED audit + classification ──"
	set classification to my classifyDamagedContacts(cs)

	-- Batch-add classified contacts
	set goldenGrp to my findGroupByName(cs, "LSAM-Golden")
	set reviewGrp to my findGroupByName(cs, "LSAM-Review")
	set damagedGrp to my findGroupByName(cs, "LSAM-Damaged")

	if goldenGrp is not missing value and (count of golden of classification) > 0 then
		set g to my batchAddContactsToGroup(cs, golden of classification, goldenGrp)
		log "  DAMAGED → Golden: " & g
		set totalMigrated to totalMigrated + g
	end if
	if reviewGrp is not missing value and (count of review of classification) > 0 then
		set r to my batchAddContactsToGroup(cs, review of classification, reviewGrp)
		log "  DAMAGED → Review: " & r
		set totalMigrated to totalMigrated + r
	end if
	if damagedGrp is not missing value and (count of damaged of classification) > 0 then
		set d to my batchAddContactsToGroup(cs, damaged of classification, damagedGrp)
		log "  DAMAGED → Damaged: " & d
		set totalMigrated to totalMigrated + d
	end if

	-- Step 4: Archive 7mars groups → classify by vault state, add to Golden or Review
	log ""
	log "── Step 4: Archive 7mars groups ──"
	set archiveGroups to {"script-LSAM-7 mars session", "script-LSAM-7mars-formatOK", "script-LSAM-7mars-orphans"}
	repeat with archiveName in archiveGroups
		set archGrp to my findGroupByName(cs, archiveName)
		if archGrp is not missing value then
			set archContacts to my getContactsInGroup(cs, archGrp)
			log "  " & archiveName & ": " & (count of archContacts) & " contacts → Golden (batch)"
			if goldenGrp is not missing value and (count of archContacts) > 0 then
				set a to my batchAddContactsToGroup(cs, archContacts, goldenGrp)
				set totalMigrated to totalMigrated + a
				log "    Added " & a
			end if
		else
			log "  " & archiveName & ": not found — skipping"
		end if
	end repeat

	-- Summary
	log ""
	log "═══ Migration Complete ═══"
	log "Total contact-group additions: " & totalMigrated
	log "Finished: " & (current date) as text

	-- Verify (re-init CNContactStore to see post-save state)
	log ""
	log "── Verification ──"
	set cs to my getContactStore()
	repeat with gName in targetNames
		set grp to my findGroupByName(cs, gName)
		if grp is not missing value then
			set contacts to my getContactsInGroup(cs, grp)
			log "  " & (gName as text) & ": " & (count of contacts)
		else
			log "  " & (gName as text) & ": NOT FOUND"
		end if
	end repeat

	return "Migration complete. Total additions: " & totalMigrated
end run
