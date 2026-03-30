import subprocess
import json
import os
import logging
import re
from typing import Dict, Any, Optional
from datetime import datetime
import urllib.parse
import tempfile

logger = logging.getLogger(__name__)

# ============================================================
# v4.9.1 MORENO_GUARD — see INCIDENT_MORENO_20260309.md
# Rule 1: 'delete person' is PERMANENTLY FORBIDDEN.
# Any AppleScript containing these patterns raises PermissionError
# before reaching osascript. Covers all callers, present and future.
# ============================================================
_FORBIDDEN_APPLESCRIPT_PATTERNS = [
    "delete person",
    "delete contact",
    "delete every person",
    "delete every contact",
]

def _assert_safe_script(script: str, context: str = "") -> None:
    """
    Raises PermissionError if the AppleScript contains any forbidden destructive pattern.
    Called automatically inside _run_applescript() — no per-call-site setup needed.
    v4.9.1 MORENO_GUARD — see INCIDENT_MORENO_20260309.md §Rule 1
    """
    lower = script.lower()
    for pattern in _FORBIDDEN_APPLESCRIPT_PATTERNS:
        if pattern in lower:
            raise PermissionError(
                f"MORENO_GUARD: AppleScript pattern '{pattern}' is PERMANENTLY FORBIDDEN. "
                f"Context: '{context}'. Contact deletion destroys UUIDs and iCloud metadata "
                f"irreversibly. See INCIDENT_MORENO_20260309.md §Rule 1."
            )


# ============================================================
# Force-Refresh LIFO Queue — v4.9.2
# Snapshots macOS contact modification date at add-to-group time
# so that LIFO ordering is stable even after the engine writes.
# ============================================================
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FORCE_REFRESH_QUEUE_PATH = os.path.join(_PROJECT_ROOT, "data", "force_refresh_queue.json")


def load_force_refresh_queue() -> list:
    """Returns the current LIFO queue entries, or [] if the file is missing/corrupt."""
    if not os.path.exists(_FORCE_REFRESH_QUEUE_PATH):
        return []
    try:
        with open(_FORCE_REFRESH_QUEUE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _save_force_refresh_queue(entries: list) -> None:
    os.makedirs(os.path.dirname(_FORCE_REFRESH_QUEUE_PATH), exist_ok=True)
    with open(_FORCE_REFRESH_QUEUE_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)


def add_to_force_refresh_queue(contact_id: str, contact_name: str, user_modified_at: str) -> None:
    """Upserts a contact into the LIFO queue, snapshotting user_modified_at."""
    entries = load_force_refresh_queue()
    entries = [e for e in entries if e.get("contact_id") != contact_id]
    entries.append({
        "contact_id": contact_id,
        "name": contact_name,
        "user_modified_at": user_modified_at,
    })
    _save_force_refresh_queue(entries)
    logger.info(f"📋 LIFO Queue: Snapshotted '{contact_name}' mod={user_modified_at}")


def remove_from_force_refresh_queue(contact_id: str) -> None:
    """Removes a contact from the LIFO queue after successful Force-Refresh sync."""
    entries = load_force_refresh_queue()
    pruned = [e for e in entries if e.get("contact_id") != contact_id]
    if len(pruned) < len(entries):
        _save_force_refresh_queue(pruned)


class ContactMacOSBridge:
    """
    Bridge to macOS Contacts.app via AppleScript.
    Supports SIMULATION (read-only) and FULL (write) modes.
    """
    
    def __init__(self, mode: str = "SIMULATION"):
        self.mode = mode.upper()
        if self.mode not in ["SIMULATION", "FULL"]:
            raise ValueError("Mode must be either SIMULATION or FULL")
        logger.info(f"ContactMacOSBridge initialized in {self.mode} mode")

    def _run_applescript(self, script_content: str) -> Dict[str, Any]:
        """Executes AppleScript with robust binary capture and unique temp files."""
        # v4.9.1 MORENO_GUARD: block forbidden destructive patterns before any execution
        _assert_safe_script(script_content, context=f"ContactMacOSBridge._run_applescript")
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.applescript', delete=False, encoding='utf-8')
        tmp_path = tf.name
        try:
            wrapped_script = f"with timeout of 300 seconds\n{script_content}\nend timeout"
            tf.write(wrapped_script)
            tf.close()
            
            # Ensure UTF-8 env for subprocess
            env = os.environ.copy()
            env["LANG"] = "en_US.UTF-8"
            
            command = ["/usr/bin/osascript", tmp_path]
            # logger.debug(f"Running AppleScript: {command}")
            
            # Using Popen for more control over pipes
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                err_text = stderr.decode('utf-8', errors='replace')
                logger.error(f"AppleScript failed with code {process.returncode}: {err_text}")
                return {"success": False, "error": err_text}
            
            return {"success": True, "output": stdout.decode('utf-8', errors='replace').strip()}
        except Exception as e:
            logger.exception(f"Error executing AppleScript: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except: pass

    def find_contact(self, name: str) -> Dict[str, Any]:
        """Finds contacts by name. Returns basic info and ID."""
        # v0.7.3 Robustness: Split by both spaces and hyphens to find all parts
        parts = [p for p in re.split(r'[ -]', name) if p]
        
        # Build filter expression: match contacts that contain all parts
        # This handles 'Pierre-Jean' vs 'Pierre Jean' vs 'Pierre-Jean Benghozi'
        filter_parts = [f'name contains "{p}"' for p in parts]
        filter_expr = " and ".join(filter_parts)

        script = f'''
        tell application "Contacts"
            set thePeople to every person whose {filter_expr}
            set results to {{}}
            repeat with aPerson in thePeople
                set theSuffix to suffix of aPerson
                if theSuffix is missing value then set theSuffix to ""
                set end of results to id of aPerson & "|#|" & name of aPerson & "|#|" & theSuffix
            end repeat
            return results
        end tell
        '''
        res = self._run_applescript(script)
        if not res["success"] or not res["output"]:
            # v0.7.6: Loose fallback (v4.7 HARDENED: min 4-char guard on search terms)
            # If searching for 'Pierre-Etienne Bost' fails, try 'Pierre' and 'Bost'
            # GUARD: Skip if any search term is <4 chars to prevent wild substring matches
            #        (e.g. "pic" would match Picard, Picat, Pican, Spicher, etc.)
            if len(parts) >= 2 and len(parts[0]) >= 4 and len(parts[-1]) >= 4:
                logger.info(f"Retrying loose search for: {name} (parts: {parts})...")
                loose_filter = f'name contains "{parts[0]}" and name contains "{parts[-1]}"'
                script_loose = f'''
                tell application "Contacts"
                    set thePeople to every person whose {loose_filter}
                    set results to {{}}
                    repeat with aPerson in thePeople
                        set theSuffix to suffix of aPerson
                        if theSuffix is missing value then set theSuffix to ""
                        set end of results to id of aPerson & "|#|" & name of aPerson & "|#|" & theSuffix
                    end repeat
                    return results
                end tell
                '''
                res = self._run_applescript(script_loose)
            elif len(parts) >= 2:
                logger.warning(f"⛔ Loose search SKIPPED for: {name} — name parts too short ({parts}). Returning not found.")
            
            if not res["success"] or not res["output"]:
                return {"success": False, "error": f"No contact found for '{name}' (parts: {parts})"}
        
        output = res["output"]
        matches = []
        for raw_match in output.split(", "):
            try:
                parts = raw_match.split("|#|")
                cid = parts[0]
                cname = parts[1]
                csuffix = parts[2] if len(parts) > 2 else ""
                matches.append({"id": cid, "name": cname, "suffix": csuffix})
            except: continue

        if len(matches) > 1:
            return {"success": True, "ambiguous": True, "matches": matches}
        elif len(matches) == 1:
            return {"success": True, "ambiguous": False, **matches[0]}
        else:
            return {"success": False, "error": "No contact found"}

    def get_vcard(self, contact_id: str) -> Dict[str, Any]:
        """Returns the raw vCard text for a contact."""
        script = f'''
        tell application "Contacts"
            set p to person id "{contact_id}"
            return vcard of p as text
        end tell
        '''
        return self._run_applescript(script)

    def export_contact_photo(self, contact_id: str, target_path: str) -> Dict[str, Any]:
        """Exports the contact's photo to the specified path using AppleScript."""
        # Ensure path is absolute
        abs_path = os.path.abspath(target_path)
        
        script = f'''
        try
            set targetFile to (POSIX file "{abs_path}")
            tell application "Contacts"
                set p to person id "{contact_id}"
                if exists image of p then
                    set imgData to image of p
                    set f to open for access targetFile with write permission
                    set eof f to 0
                    write imgData to f
                    close access f
                    return "SUCCESS"
                else
                    return "NO_IMAGE"
                end if
            end tell
        on error errMsg
            try
                close access targetFile
            end try
            return "ERROR:" & errMsg
        end try
        '''
        res = self._run_applescript(script)
        if not res["success"]: return res
        
        output = res["output"]
        if output == "SUCCESS":
            return {"success": True, "path": abs_path}
        elif output == "NO_IMAGE":
            return {"success": True, "path": None}
        else:
            return {"success": False, "error": output.replace("ERROR:", "")}

    def get_contact_details(self, contact_id: str) -> Dict[str, Any]:
        """Fetches full details for a specific contact ID for diffing."""

        script = f'''
        try
            set oldDelims to AppleScript's text item delimiters
            set AppleScript's text item delimiters to "|#|"
            tell application "Contacts"
                set p to person id "{contact_id}"
                
                set em to {{}}
                repeat with e in emails of p
                    set end of em to value of e
                end repeat
                set AppleScript's text item delimiters to "|#|"
                set emStr to em as string
                
                set ph to {{}}
                repeat with t in phones of p
                    set end of ph to value of t
                end repeat
                set AppleScript's text item delimiters to "|#|"
                set phStr to ph as string

                set soc to {{}}
                repeat with s in social profiles of p
                    try
                        set sn to ""
                        try
                            set sn to service name of s as string
                        end try
                        set un to ""
                        try
                            set un to user name of s as string
                        end try
                        set surl to ""
                        try
                            set surl to url string of s as string
                        on error
                            try
                                set surl to url of s as string
                            end try
                        end try
                        if sn is "missing value" then set sn to ""
                        if un is "missing value" then set un to ""
                        if surl is "missing value" then set surl to ""
                        set end of soc to sn & "|USER:" & un & "|URL:" & surl
                    on error
                        set end of soc to "unknown:unknown:unknown"
                    end try
                end repeat
                set AppleScript's text item delimiters to "|#|"
                set socStr to soc as string

                set bd to ""
                try
                    set bd_raw to birthday of p
                    if bd_raw is not missing value then set bd to bd_raw as string
                on error
                    -- v1.5.0 Fallback to vCard if direct property access fails (common with dates)
                    try
                         set bd to "VCARD_FALLBACK:" & (vcard of p as string)
                    on error
                         set bd to ""
                    end try
                end try
                
                set ur to {{}}
                repeat with u in urls of p
                    set end of ur to value of u
                end repeat
                set AppleScript's text item delimiters to "|#|"
                set urStr to ur as string
                
                set noteText to note of p
                if noteText is missing value then set noteText to ""
                
                set nameText to name of p
                if nameText is missing value then set nameText to ""
                
                set fname to first name of p
                if fname is missing value then set fname to ""
                
                set mname to middle name of p
                if mname is missing value then set mname to ""
                
                set lname to last name of p
                if lname is missing value then set lname to ""
                
                set jobText to job title of p
                if jobText is missing value then set jobText to ""
                
                set orgText to organization of p
                if orgText is missing value then set orgText to ""

                set hasImg to "NO"
                if exists image of p then set hasImg to "YES"

                set modDate to ""
            try
                set modDate to modification date of p as string
            on error
                set modDate to ""
            end try
            
            set AppleScript's text item delimiters to oldDelims
            return "NAME:" & nameText & "|#|FNAME:" & fname & "|#|MNAME:" & mname & "|#|LNAME:" & lname & "|#|JOB:" & jobText & "|#|ORG:" & orgText & "|#|NOTE:" & noteText & "|#|BD:" & bd & "|#|EMAILS:" & emStr & "|#|PHONES:" & phStr & "|#|SOCIAL:" & socStr & "|#|URLS:" & urStr & "|#|HAS_IMAGE:" & hasImg & "|#|MOD_DATE:" & modDate
            end tell
        on error errMsg
            return "ERROR:" & errMsg
        end try
        '''
        res = self._run_applescript(script)
        if not res["success"]: return res
        
        raw = res["output"]
        if raw.startswith("ERROR:"):
            return {"success": False, "error": raw.replace("ERROR:", "")}
            
        # v2.9.1: Robust Regex Parsing to handle delimiters inside content
        def get_val(tag):
            try:
                # 1. Define the marker for this tag
                # NAME is special (start of string), others have |#| prefix
                prefix = "" if tag == "NAME" else r"\|\#\|"
                pattern = rf"{prefix}{tag}:(.*?)(?=\|\#\|[A-Z_]+:|\|\#\|MOD_DATE:|$)"
                
                # 2. Search for the content
                # DOTALL is crucial so . matches newlines in notes
                match = re.search(pattern, raw, re.DOTALL)
                
                if match:
                    val = match.group(1).strip()
                    if val == "missing value": return ""
                    return val
                return ""
            except Exception as e:
                logger.error(f"Error parsing tag {tag}: {e}")
                return ""


        bd_val = get_val("BD")
        # Handle vCard fallback parsing
        if bd_val.startswith("VCARD_FALLBACK:"):
            vcard_text = bd_val.replace("VCARD_FALLBACK:", "")
            match = re.search(r"BDAY(?:;[^:]*)?:(\d{4}-\d{2}-\d{2})", vcard_text)
            if match:
                 bd_val = match.group(1) # e.g. 1604-06-20
            else:
                 bd_val = ""

        return {
            "success": True,
            "name": get_val("NAME"),
            "first_name": get_val("FNAME"),
            "middle_name": get_val("MNAME"),
            "last_name": get_val("LNAME"),
            "job_title": get_val("JOB"),
            "company": get_val("ORG"),
            "note": get_val("NOTE"),
            "birthday": bd_val,
            "has_image": get_val("HAS_IMAGE") == "YES",
            "emails": [e.strip() for e in get_val("EMAILS").split("|#|") if e.strip()],
            "phones": [p.strip() for p in get_val("PHONES").split("|#|") if p.strip()],
            "social": [s.strip() for s in get_val("SOCIAL").split("|#|") if s.strip()],
            "websites": [u.strip() for u in get_val("URLS").split("|#|") if u.strip()],
            "modification_date": get_val("MOD_DATE")
        }

    def list_groups(self) -> Dict[str, Any]:
        """Returns a list of all group names in Contacts."""
        script = 'tell application "Contacts" to return name of every group'
        res = self._run_applescript(script)
        if not res["success"]: return res
        
        groups = [g.strip() for g in res["output"].split(", ") if g.strip()]
        return {"success": True, "groups": groups}

    def get_selection(self) -> Dict[str, Any]:
        """Returns the list of contacts currently selected in the Contacts app."""
        script = '''
        tell application "Contacts"
            set theSelection to selection
            set results to {}
            repeat with aPerson in theSelection
                set comp to company of aPerson
                if comp is missing value then set comp to ""
                set theSuffix to suffix of aPerson
                if theSuffix is missing value then set theSuffix to ""
                set end of results to "CONTACT_ID:" & id of aPerson & "||NAME:" & name of aPerson & "||COMP:" & comp & "||SUFFIX:" & theSuffix
            end repeat
            set oldDelims to AppleScript's text item delimiters
            set AppleScript's text item delimiters to "@@@"
            set out to results as string
            set AppleScript's text item delimiters to oldDelims
            return out
        end tell
        '''
        res = self._run_applescript(script)
        if not res["success"]: return res
        return self._parse_contact_list(res["output"])

    def list_group_contacts(self, group_name: str) -> Dict[str, Any]:
        """Returns all contacts in the specified group."""
        script = f'''
        tell application "Contacts"
            if not (exists group "{group_name}") then return "GROUP_NOT_FOUND"
            set thePeople to people of group "{group_name}"
            set results to {{}}
            repeat with aPerson in thePeople
                try
                    set theID to id of aPerson
                    set theName to name of aPerson
                    set theComp to company of aPerson
                    set theSuffix to suffix of aPerson
                    if theComp is missing value then set theComp to ""
                    if theName is missing value then set theName to "Unknown"
                    if theSuffix is missing value then set theSuffix to ""
                    set end of results to "CONTACT_ID:" & theID & "||NAME:" & theName & "||COMP:" & theComp & "||SUFFIX:" & theSuffix
                on error
                    -- skip
                end try
            end repeat
            set oldDelims to AppleScript's text item delimiters
            set AppleScript's text item delimiters to "@@@"
            set out to results as string
            set AppleScript's text item delimiters to oldDelims
            return out
        end tell
        '''
        res = self._run_applescript(script)
        if not res["success"]: 
            logger.error(f"AppleScript failed in list_group_contacts: {res.get('error')}")
            return res
        if not res["output"]:
            logger.warning("AppleScript returned empty output in list_group_contacts")
        if res["output"] == "GROUP_NOT_FOUND":
            return {"success": False, "error": f"Group '{group_name}' not found"}
        return self._parse_contact_list(res["output"])

    def batch_get_group_notes(self, group_name: str) -> Dict[str, Any]:
        """Bulk fetches IDs, Names, and Notes for a group in ONE AppleScript call. 
        Critical for Phase 5 ventilation speed."""
        script = f'''
        tell application "Contacts"
            if not (exists group "{group_name}") then return "GROUP_NOT_FOUND"
            set thePeople to people of group "{group_name}"
            set results to {{}}
            repeat with p in thePeople
                try
                    set theID to id of p
                    set theNote to note of p
                    if theNote is missing value then set theNote to ""
                    set end of results to theID & "|||LSAM_SEP|||" & theNote
                on error
                    -- skip corrupt contacts
                end try
            end repeat
            
            set oldDelims to AppleScript's text item delimiters
            set AppleScript's text item delimiters to "@@@LSAM_REC@@@"
            set out to results as string
            set AppleScript's text item delimiters to oldDelims
            return out
        end tell
        '''
        res = self._run_applescript(script)
        if not res["success"]: return res
        if res["output"] == "GROUP_NOT_FOUND": return {"success": False, "error": "Group not found"}
        
        # Parse into {id: note}
        data = {}
        chunks = res["output"].split("@@@LSAM_REC@@@")
        for chunk in chunks:
            if "|||LSAM_SEP|||" in chunk:
                parts = chunk.split("|||LSAM_SEP|||", 1)
                data[parts[0]] = parts[1]
        
        return {"success": True, "notes": data}

    def batch_get_group_social(self, group_name: str) -> Dict[str, Any]:
        """Bulk fetches IDs and Social Profile URLs for a group in ONE AppleScript call.
        Critical for Phase 5 'rescue' audits of false positives."""
        script = f'''
        tell application "Contacts"
            if not (exists group "{group_name}") then return "GROUP_NOT_FOUND"
            set thePeople to people of group "{group_name}"
            set results to {{}}
            repeat with p in thePeople
                try
                    set theID to id of p
                    set socUrls to {{}}
                    repeat with s in social profiles of p
                        try
                            set surl to ""
                            try
                                set surl to url string of s as string
                            on error
                                try
                                    set surl to url of s as string
                                end try
                            end try
                            if surl is not "missing value" and surl is not "" then
                                set end of socUrls to surl
                            end if
                        end try
                    end repeat
                    
                    set oldDelims to AppleScript's text item delimiters
                    set AppleScript's text item delimiters to "@@@LSAM_SOC@@@"
                    set socStr to socUrls as string
                    set AppleScript's text item delimiters to oldDelims
                    
                    set end of results to theID & "|||LSAM_SEP|||" & socStr
                on error
                    -- skip corrupt contacts
                end try
            end repeat
            
            set oldDelims to AppleScript's text item delimiters
            set AppleScript's text item delimiters to "@@@LSAM_REC@@@"
            set out to results as string
            set AppleScript's text item delimiters to oldDelims
            return out
        end tell
        '''
        res = self._run_applescript(script)
        if not res["success"]: return res
        if res["output"] == "GROUP_NOT_FOUND": return {"success": False, "error": "Group not found"}
        
        # Parse into {id: [urls]}
        data = {}
        chunks = res["output"].split("@@@LSAM_REC@@@")
        for chunk in chunks:
            if "|||LSAM_SEP|||" in chunk:
                parts = chunk.split("|||LSAM_SEP|||", 1)
                cid = parts[0]
                soc_str = parts[1]
                urls = [u.strip() for u in soc_str.split("@@@LSAM_SOC@@@") if u.strip()]
                data[cid] = urls
        
        return {"success": True, "social_map": data}

    def _parse_contact_list(self, output: str) -> Dict[str, Any]:
        """Helper to parse the custom @@@ delimited contact list."""
        if not output or output.strip() == "":
            return {"success": True, "matches": []}
            
        matches = []
        items = output.split("@@@")
        for item in items:
            if not item.strip(): continue
            try:
                # Format: CONTACT_ID:xxx||NAME:yyy||COMP:zzz||SUFFIX:sss
                cid = item.split("CONTACT_ID:")[1].split("||NAME:")[0]
                name = item.split("||NAME:")[1].split("||COMP:")[0]
                
                # Suffix and Comp can be missing if using older scripts but we now standardize
                comp = ""
                if "||COMP:" in item:
                    comp = item.split("||COMP:")[1].split("||SUFFIX:")[0]
                
                suffix = ""
                if "||SUFFIX:" in item:
                    suffix = item.split("||SUFFIX:")[1].strip()
                
                # v4.7 B5-FIX: Strip trailing name duplication.
                # macOS sometimes returns `name of aPerson` with the suffix appended,
                # resulting in "Anne Lhotellier Lhotellier" if suffix = "Lhotellier".
                if suffix and name.endswith(f" {suffix}"):
                    # Check if removing suffix leaves a valid name (not just first name)
                    stripped = name[: -(len(suffix) + 1)].strip()
                    if stripped and " " in stripped:  # Must still have first + last
                        name = stripped
                
                matches.append({"id": cid, "name": name, "company": comp, "suffix": suffix})
            except Exception as e:
                logger.debug(f"Skipping malformed contact item: {e}")
                continue
        return {"success": True, "matches": matches}

    def update_note(self, contact_id: str, note: str, backup: bool = False) -> Dict[str, Any]:
        """Surgically updates ONLY the note of a contact. No other enrichment.
        v5.0: Injects <!--LSAM:pre_mod:TIMESTAMP--> preamble for CCC articulation."""
        if self.mode == "SIMULATION":
            logger.info(f"🛠️ SIMULATION: Would update note for {contact_id}")
            return {"success": True}

        if backup:
            # We already have backup logic in bridge.get_contact_details used by script
            pass

        # v5.0: Save contact's actual modification date before we touch it.
        # This preserves the last-modified-by-user timestamp in the note,
        # so CCC and future LSAM runs know when the contact was last touched
        # by a human (vs by automation).
        if "<!--LSAM:last_mod_before:" not in note:
            try:
                mod_date_result = self._run_applescript(f'''
                tell application "Contacts"
                    set p to person id "{contact_id}"
                    set modDate to modification date of p as string
                    return modDate
                end tell
                ''')
                if mod_date_result.get("success"):
                    actual_mod_date = mod_date_result.get("output", "").strip()
                    if actual_mod_date:
                        note = f"<!--LSAM:last_mod_before:{actual_mod_date}-->\n" + note
            except Exception:
                pass  # Non-critical; proceed without stamp

        safe_note = note.replace('"', '\\"')
        script = f'''
        tell application "Contacts"
            try
                set p to person id "{contact_id}"
                set note of p to "{safe_note}"
                save
                return "SUCCESS"
            on error err
                return err
            end try
        end tell
        '''
        res = self._run_applescript(script)
        if res["success"] and res["output"] == "SUCCESS":
            return {"success": True}
        return {"success": False, "error": res.get("output", "AppleScript error")}

    def update_emails(self, contact_id: str, emails: list) -> Dict[str, Any]:
        """Surgically updates ONLY the emails of a contact."""
        if self.mode == "SIMULATION":
            logger.info(f"🛠️ SIMULATION: Would update emails for {contact_id}: {emails}")
            return {"success": True}
            
        email_lines = []
        for e in emails:
            email_lines.append(f'make new email at end of emails of p with properties {{label:"work", value:"{e}"}}')
            
        script = f'''
        tell application "Contacts"
            try
                set p to person id "{contact_id}"
                delete every email of p
                {chr(10).join(email_lines)}
                save
                return "SUCCESS"
            on error err
                return err
            end try
        end tell
        '''
        res = self._run_applescript(script)
        if res["success"] and res["output"] == "SUCCESS":
            return {"success": True}
        return {"success": False, "error": res.get("output", "AppleScript error")}

    def clean_note_ccc(self, note: str) -> str:
        """
        Applies canonical CCC (Contact Cleaning & Consolidation) rules.
        Handles Deduplication, Label Stripping, and Blank Line Normalization.
        """
        if not note: return ""
        
        # Split into lines
        lines = note.split('\n')
        clean_lines = []
        
        for line in lines:
            l = line.strip()
            if not l:
                clean_lines.append("")
                continue
                
            # 1. Label Stripping (LinkedIn-Specific)
            prefixes = ["Location ", "Degree Name ", "Field Of Study ", "Dates Employed ", 
                        "Employment Duration ", "Total Duration "]
            for p in prefixes:
                if l.startswith(p):
                    l = l[len(p):].strip()
            
            # 2. Artifact & Noise removal
            if "Show all " in l and " experience" in l: continue
            if l.endswith(" logo"): continue
            if "degree connection" in l.lower(): continue
            
            # 3. Keyword duplication (ExperienceExperience -> Experience)
            keywords = ["Experience", "Education", "Skills", "About me", "Work", "Contact", "Summary", "Position", "Project", "Company", "Title", "Job", "Profile", "Details"]
            for k in keywords:
                # Rule 1 (No spaces) & Rule 2 (With spaces)
                if l == k + k or l == k + " " + k:
                    l = k
            
            # 4. Halved Line Deduplication (LondonLondon -> London)
            if len(l) > 1 and len(l) % 2 == 0:
                mid = len(l) // 2
                if l[:mid] == l[mid:]:
                    l = l[:mid]
            
            # 5. Consecutive Line Deduplication
            if clean_lines and l == clean_lines[-1] and l != "":
                continue
            
            # 6. Header Formatting
            if l in ["Contact Info", "Experience", "Education"]:
                l = f"==== {l}"
            
            clean_lines.append(l)
            
        # 7. Blank Line Normalization (Max 2 consecutive)
        text = '\n'.join(clean_lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 8. Strip LSAM specifics that might be outside blocks
        text = re.sub(r"(?m)^#(linkedin-sync|handle|stats|linked-since|lsam-force-resync).*$", "", text)
        
        return text.strip()

    def update_contact(self, contact_id: str, profile: Any, photo_path: Optional[str] = None, photo_status: Optional[str] = None, orig_photo_path: Optional[str] = None, session_backup_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Updates a contact surgically. Returns info for auditing/execution.
        session_backup_dir: v4.9.1 MORENO_GUARD Rule 3 — pass logs/sessions/<timestamp>/ to enable
            pre/post JSON backup. If None, a WARNING is logged (callers should always pass this).
            See INCIDENT_MORENO_20260309.md §Rule 3.
        """
        # v4.9.1 B3: Moreno Rule 3 — warn if no backup dir provided (AUDIT_2026-03-11)
        if session_backup_dir is None:
            logger.warning(
                "MORENO_GUARD (Rule 3): update_contact called without session_backup_dir. "
                "Pass logs/sessions/<timestamp>/ to enable pre/post backups. "
                "See INCIDENT_MORENO_20260309.md §Rule 3."
            )

        # 1. Fetch current data for diffing
        current = self.get_contact_details(contact_id)
        if not current["success"]: return current

        # v4.9.1 B3: Save pre-write backup if backup dir is provided
        if session_backup_dir:
            try:
                import json as _json
                os.makedirs(session_backup_dir, exist_ok=True)
                safe_id = contact_id.replace(":", "_").replace("/", "_")
                backup_path = os.path.join(session_backup_dir, f"{safe_id}-before.json")
                with open(backup_path, "w", encoding="utf-8") as _bf:
                    _json.dump(current, _bf, indent=2, default=str)
                logger.info(f"Pre-write backup saved: {backup_path}")
            except Exception as _be:
                logger.warning(f"Pre-write backup failed (non-fatal): {_be}")
        
        # v2.5.0 Safety Guard: Enforce Pydantic Model usage
        if isinstance(profile, dict):
            # This triggers an early error to prevent the 'dict-dump' corruption bug.
            # The StagedManager must instantiate a LinkedInProfile before calling this.
            return {"success": False, "error": "ContactMacOSBridge.update_contact expected a LinkedInProfile object, got dict. Use src.models.profile.LinkedInProfile.parse_obj() before calling update."}

        added_fields = []
        updated_fields = []
        
        # 2. Compare Role/Org/Location (v0.4.0)
        prev_role_line = ""
        if profile.current_role and profile.current_role != current["job_title"]:
            updated_fields.append("Job Title")
            if current["job_title"]:
                prev_role_line = f"previously {current['job_title']} at {current['company']}"
        
        if profile.company and profile.company != current["company"]:
            if "Job Title" not in updated_fields: updated_fields.append("Organization")
            if not prev_role_line and current['company']:
                prev_role_line = f"previously {current['job_title']} at {current['company']}"

        if profile.location and current.get('location') and profile.location != current['location']:
            updated_fields.append("Location")
            logger.info(f"Location change detected: {current['location']} -> {profile.location}")

        # v1.8.0 SAFEGUARD: Validate emails before writing to macOS Contacts.
        # Any non-email string (post text, phone numbers, URLs) is dropped here,
        # regardless of how it entered profile.emails. This is the last line of defence.
        _EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
        valid_emails = []
        for _e in profile.emails:
            if _e and _EMAIL_REGEX.match(_e.strip()):
                valid_emails.append(_e.strip())
            else:
                logger.warning(f"🚫 Email write-gate: Rejected invalid email string for {contact_id}: '{str(_e)[:80]}'")
        
        # v5.4: Legacy URL Cleanup (Before any additions)
        url_cleanup_script = ""
        poisons = ["tardis-contact", "profile/view?id="]
        for p_str in poisons:
            url_cleanup_script += f'''
            repeat with ur_obj in urls of p
                try
                    if value of ur_obj contains "{p_str}" then delete ur_obj
                end try
            end repeat
            '''

        # 3. Handle Email/Phone Merging (v2.3 Labeling Force)
        email_script = ""
        for e in valid_emails:
            if e.lower() not in [ce.lower() for ce in current["emails"]]:
                email_script += f'make new email at end of emails of p with properties {{label:"from LinkedIn", value:"{e}"}}\n'
                added_fields.append("Email")
            else:
                # Ensure label is set ONLY if it's currently generic/empty (don't overwrite 'home', 'work', 'deprecated')
                # We check this in AppleScript to be safe
                email_script += f'''
                repeat with em_obj in emails of p
                    if value of em_obj is "{e}" then
                        if label of em_obj is missing value or label of em_obj is "_$!<Other>!$_" or label of em_obj is "" then
                            set label of em_obj to "from LinkedIn"
                        end if
                    end if
                end repeat
                '''

        phone_script = ""
        for ph in profile.phones:
            norm_ph = re.sub(r'[^0-9]', '', ph)
            if not any(norm_ph in re.sub(r'[^0-9]', '', cp) for cp in current["phones"]):
                phone_script += f'make new phone at end of phones of p with properties {{label:"from LinkedIn", value:"{ph}"}}\n'
                added_fields.append("Phone")
            else:
                # Ensure label is set even if value exists (using partial numeric match for safety)
                phone_script += f'repeat with ph_obj in phones of p\n if value of ph_obj contains "{norm_ph}" then set label of ph_obj to "from LinkedIn"\n end repeat\n'

        # 3.5 Website Merging
        website_script = ""
        for ws in profile.websites:
            # Simple check, ignoring protocol differences if minimal
            clean_ws = ws.replace("http://", "").replace("https://", "").strip("/")
            if not any(clean_ws in cw.replace("http://", "").replace("https://", "").strip("/") for cw in current["websites"]):
                website_script += f'make new url at end of urls of p with properties {{label:"from LinkedIn", value:"{ws}"}}\n'
                added_fields.append("Website")
            else:
                website_script += f'repeat with ur_obj in urls of p\n if value of ur_obj contains "{clean_ws}" then set label of ur_obj to "from LinkedIn"\n end repeat\n'

        # 4. Social Profile (LinkedIn Handle)
        handle = profile.get_handle()
        social_script = ""
        # v4.8 B1-FIX: Skip social profile injection if handle is malformed (empty after sanitization)
        if not handle:
            logger.warning(f"v4.8 B1-FIX: Skipping social profile injection for {contact_id} — handle is empty/malformed.")
        else:
            # v0.7.6 Improved Duplicate Detection:
            # current["social"] items are in "Service|USER:xxx|URL:yyy" format
            is_already_there = False
            for s in current["social"]:
                s_low = s.lower()
                s_unquoted = urllib.parse.unquote(s_low)
                # Check if handle or URL matches
                # v0.7.7 robust check: match handle as whole word or URL (decoded or encoded)
                if handle.lower() in s_low or handle.lower() in s_unquoted:
                    is_already_there = True
                    break
                # Also check if it's a LinkedIn profile even if handle is different (e.g. view?id=)
                if "linkedin.com" in s_unquoted and profile.linkedin_url:
                     h_from_url = profile.linkedin_url.split('/in/')[-1].strip('/')
                     if h_from_url.lower() in s_unquoted or urllib.parse.quote(h_from_url.lower()) in s_low:
                         is_already_there = True
                         break
            
            if not is_already_there:
                # Use locale-safe approach: only service name and user name
                social_script = f'make new social profile at end of social profiles of p with properties {{service name:"LinkedIn", user name:"{handle}"}}'
                added_fields.append("Social Profile")

        # 4.5 Birthday Mapping (v2.8 Robust Precision)
        bd_script = ""
        if profile.birthday:
            staged_d, staged_m = self._parse_bd(profile.birthday)
            native_d, native_m = self._parse_bd(current.get("BD"))
            
            # v2.8 Robust Check: Suppress if native field matches
            has_it = (staged_d and staged_m and staged_d == native_d and staged_m == native_m)
            
            if not has_it:
                # v1.5.0: "Note-Aware Silence" - Check if we already bragged about adding this in the Note
                already_in_note = False
                note_text = current.get("note", "")
                if "Added: Birthday" in note_text or ("Added (2" in note_text and "Birthday" in note_text):
                     if re.search(r"Added(?:\s*\(.*?\))?\s*:\s*.*?Birthday", note_text):
                         already_in_note = True
                
                # v4.9.1 C4 MORENO NOTE: Use 'birth date of p' to SET (NOT 'birthday' → -1700 error)
                # Reading uses 'birthday of p' (get_contact_details ~line 232) — that is correct for GET.
                bd_script = f'''
                set target_date to (current date)
                set day of target_date to {staged_d or 1}
                set month of target_date to {staged_m or 1}
                set year of target_date to 1604
                set birth date of p to target_date
                '''
                
                if already_in_note:
                    logger.info(f"Birthday missing from native field but present in Note history for {profile.full_name}. Silently fixing.")
                else:
                    added_fields.append("Birthday")
            else:
                logger.debug(f"Birthday already set for {profile.full_name}, skipping 'Added' tag.")

        # 4.6 Photo logic (v3.0.1 Resolution-First Architecture)
        # v5.5: Added Age-Based Photo Refresh Logic
        should_update_photo = False
        is_stale_photo = False
        photo_age_years = 0
        
        # v3.1.8 & v5.5: Parse block early to get photo_date
        old_note = current["note"]
        existing_sync_block = None
        block_match = re.search(r"(<Linkedin-AI-sync.*?</Linkedin-AI-sync>)", old_note, re.DOTALL | re.IGNORECASE)
        if block_match:
            existing_sync_block = block_match.group(1).strip()
            
        prev_stats = {}
        if existing_sync_block:
            prev_stats = profile.parse_history_from_block(existing_sync_block)
            
        photo_date_str = prev_stats.get("photo_date")
        if photo_date_str:
            try:
                p_date = datetime.strptime(photo_date_str, "%Y-%m-%d")
                photo_age_years = (datetime.now() - p_date).days / 365.25
                if photo_age_years > 3.0: # v5.5: Stale threshold = 3 years
                    is_stale_photo = True
            except:
                pass

        # v2.4.16 Part B: --force-photo override — user explicitly requested a photo refresh.
        # Set is_stale_photo=True unconditionally so the photo update path fires regardless of
        # resolution or age. Takes priority over all other staleness logic.
        if getattr(profile, 'force_photo', False):
            is_stale_photo = True
            photo_age_years = 99.0  # Sentinel value — forced, not age-based
            logger.info(f"v2.4.16 Part B: force_photo flag set for {profile.full_name} — treating photo as stale (user override).")

        # v2.4.16 Part A: No Photo Date in sync block and no force flag — fall back to the
        # contact's macOS modification date as a staleness proxy. If the contact hasn't been
        # touched in ≥3 years, the photo is likely stale too.
        # IMPORTANT: `current` is fetched BEFORE any write in this method — modification_date
        # reflects the pre-update state, which is the correct reference for staleness.
        elif not photo_date_str and not is_stale_photo:
            mod_date_raw = (current.get("modification_date") or "").strip()
            if mod_date_raw:
                # AppleScript returns locale-specific date strings (e.g., "Monday, March 24, 2026 at 10:45:00 AM").
                # We extract the 4-digit year using regex as the least locale-sensitive approach.
                import re as _re_mod
                year_match = _re_mod.search(r'\b(20\d{2})\b', mod_date_raw)
                if year_match:
                    mod_year = int(year_match.group(1))
                    age_from_mod = datetime.now().year - mod_year
                    if age_from_mod >= 3:
                        is_stale_photo = True
                        photo_age_years = float(age_from_mod)
                        logger.info(
                            f"v2.4.16 Part A: No Photo Date in sync block for {profile.full_name}. "
                            f"Contact modification year {mod_year} is ≥3 years ago — treating photo as stale."
                        )

        if photo_path and os.path.exists(photo_path):
            img_size = os.path.getsize(photo_path)
            
            # v2.4.2: Placeholder guard remains strict
            if img_size < 2048: # 2KB (HEIC can be very small but high res)
                logger.warning(f"Rejecting photo for {profile.full_name}: suspiciously small ({img_size}b) - likely placeholder.")
                updated_fields.append("Photo (Rejected: Placeholder)")
                photo_status = "photo_unavailable"
            else:
                # v3.0.1: For all non-placeholders, we prioritize resolution over file size
                from src.bridge.image_optim import get_image_resolution
                new_w, new_h = (0, 0)
                try:
                    new_w, new_h = get_image_resolution(photo_path)
                except Exception as e_res:
                    logger.warning(f"Failed to get resolution for new photo: {e_res}")
                
                new_res = new_w * new_h
                
                if current.get("has_image") and orig_photo_path and os.path.exists(orig_photo_path):
                    old_w, old_h = (0, 0)
                    try:
                        old_w, old_h = get_image_resolution(orig_photo_path)
                    except: pass
                    old_res = old_w * old_h
                    
                    if new_res >= old_res:
                        should_update_photo = True
                        is_res_change = new_res > old_res
                        is_size_change = abs(img_size - os.path.getsize(orig_photo_path)) > (os.path.getsize(orig_photo_path) * 0.15)
                        
                        if is_res_change:
                            updated_fields.append(f"Photo (Upgrade: {new_w}x{new_h} vs {old_w}x{old_h})")
                        elif is_stale_photo:
                            updated_fields.append(f"Photo (Refresh: {photo_age_years:.1f} years old)")
                        else:
                            # Same resolution, not stale — skip update.
                            # v2.4.15: Byte-size comparison removed entirely. The vault stores
                            # a HEIC-compressed copy of the LinkedIn JPEG; HEIC is always
                            # significantly smaller than JPEG at equal perceptual quality, so
                            # comparing bytes across formats is not a reliable quality signal.
                            # Resolution (pixel count) is the only format-agnostic metric.
                            # Same resolution + not stale = no meaningful improvement to apply.
                            should_update_photo = False
                            logger.info(f"Photo update skipped for {profile.full_name}: same resolution ({new_w}x{new_h}), not stale. Keeping existing contact photo.")
                    elif is_stale_photo and new_res >= (400 * 400):
                        # Even if resolution is lower but it's 3 years old, and new is at least decent (400x400)
                        should_update_photo = True
                        updated_fields.append(f"Photo (Refresh: {photo_age_years:.1f} years old, new {new_w}x{new_h})")
                    elif new_res == old_res and img_size > os.path.getsize(orig_photo_path) * 1.5:
                         # Same res but significantly larger file size might imply better quality/less artifacts
                         should_update_photo = True
                         updated_fields.append(f"Photo (Quality Upgrade: {img_size}b vs {os.path.getsize(orig_photo_path)}b)")
                    else:
                        logger.info(f"Skipping photo update for {profile.full_name}: LinkedIn resolution ({new_w}x{new_h}) not superior to macOS ({old_w}x{old_h}) and not stale enough.")
                elif current.get("has_image"):
                    # No original path to compare, but has image. 
                    # If size is > 10KB and res is > 200x200, let's assume it's at least valid for a replacement if we are syncing.
                    if new_res >= (200 * 200) or img_size > 51200:
                         should_update_photo = True
                         if is_stale_photo:
                             updated_fields.append(f"Photo (Refresh: {photo_age_years:.1f} years old)")
                         else:
                             updated_fields.append("Photo (Potential Upgrade)")
                    else:
                        logger.warning(f"Rejecting photo for {profile.full_name}: unknown current photo quality and new is low ({new_w}x{new_h}, {img_size}b).")
                else:
                    # No current image
                    should_update_photo = True
                    added_fields.append("Photo")
        elif photo_status:
            # Map internal codes to friendly labels
            if photo_status == "photo_error": updated_fields.append("Photo (Internal Error)")
            elif photo_status == "photo_unavailable": updated_fields.append("Photo (Not Available)")
            else: updated_fields.append(f"Photo ({photo_status})")

        # 5. Note Update (Sync Block)
        # v5.5: Use already parsed prev_stats and existing_sync_block from line 948
        # v5.5: Track Photo Update Date
        photo_update_date = None
        if should_update_photo:
             photo_update_date = datetime.now().strftime("%Y-%m-%d")

        # v4.2: Pure block comparison for change detection (ignoring date-only transitions)
        def get_content(b):
            if not b: return ""
            # Normalize tags using regex (handles squashed blocks without newlines)
            c = re.sub(r"^<Linkedin-AI-sync.*?>", "", b.strip(), flags=re.IGNORECASE)
            c = re.sub(r"</Linkedin-AI-sync>$", "", c, flags=re.IGNORECASE)
            
            # Normalize "Added (date) : " / "Added : " → ADD_SIGNAL:
            # Normalize "Updated (date) : " / "Updated : " → UPD_SIGNAL:
            # Both patterns handle the new dated format (v2.4.15) and legacy undated format.
            c = re.sub(r"Added(?:\s*\(.*?\))?\s*:\s*", "ADD_SIGNAL:", c)
            c = re.sub(r"Updated(?:\s*\(.*?\))?\s*:\s*", "UPD_SIGNAL:", c)
            # v4.4: Ignore blacklisted meta-signals
            c = re.sub(r",?\s*Sync Block\s*(?:\(\w+\))?", "", c)
            # Remove dates from Was X on Y
            c = re.sub(r"\(was .*? on .*?\)", "", c)
            # v4.4.1: Aggressive whitespace normalization
            c = re.sub(r"\s+", " ", c).strip()
            return c

        # 5. Build Final Proposed Block (Pass History!)
        # v3.1.8 & v5.5: Re-calculate to include ALL fields (preventing erasure of history)
        pure_header = profile.generate_sync_block(
            added_fields=added_fields, 
            updated_fields=updated_fields, 
            prev_stats=prev_stats,
            existing_sync_block_text=existing_sync_block,
            photo_update_date=photo_update_date
        )
        new_header = pure_header # Default for new contacts or material changes
        
        # Determine if the block itself has "material" changes (ignoring the timestamp)
        existing_core = None  # Initialize to prevent UnboundLocalError
        if existing_sync_block:
             existing_core = get_content(existing_sync_block)
        else:
             existing_core = ""
        new_core = get_content(pure_header)
            
        sync_block_changed = False
        if self.mode == 'SIMULATION' or True: # Force logic to run
             # Calculate Noise Thresholds
             try:
                 prev_f = int(prev_stats.get('followers', 0))
                 followers_diff = abs(int(profile.followers_count or 0) - prev_f)
             except:
                 followers_diff = 0
             
             is_follower_noise = followers_diff < 5 
             
             prev_conn = prev_stats.get('total', '0')
             curr_conn = str(profile.connections_count or 0)
             is_conn_noise = (prev_conn == "500+" and int(profile.connections_count or 0) > 500) or (prev_conn == curr_conn)

             # v4.9.2 POISON_GUARD: Block "verified" stamp if extraction returned poison strings.
             # When LinkedIn returns a 404/restricted page, the extractor produces values like
             # "Information not available" or "not available". The name guard in pro_sync_agent.py
             # correctly rejects these for the name field, but the sync block may appear unchanged,
             # causing the engine to stamp the contact as "verified" — a false positive.
             # Detect poison across the profile's scraped text fields before any stamping.
             _POISON_STRINGS = ["not available", "information not available", "page not found"]
             _profile_text = " ".join(filter(None, [
                 str(profile.first_name or ""), str(profile.last_name or ""),
                 str(profile.current_role or ""), str(profile.company or ""),
             ])).lower()
             _is_poisoned = any(p in _profile_text for p in _POISON_STRINGS)

             # v4.5: Fidelity Timestamp Logic
             if existing_core == new_core:
                 if _is_poisoned:
                     # v4.9.2: Extraction failed silently — do NOT stamp as verified
                     new_header = existing_sync_block or ""
                     sync_block_changed = False
                     logger.warning(f"⚠️ POISON_GUARD: Extraction returned restricted/failed profile data. "
                                    f"Skipping VERIFIED stamp for {profile.full_name}.")
                 elif is_follower_noise and is_conn_noise:
                     # It's noise. Stamp as 'verified' if not already done today.
                     date_str = datetime.now().strftime("%Y-%m-%d")
                     verified_header = pure_header.replace(f" {date_str} added", f" {date_str} verified").replace(f" {date_str} update", f" {date_str} verified")

                     if "verified" in verified_header:
                         if f"{date_str} verified" in (existing_sync_block or ""):
                             new_header = existing_sync_block # No-op
                             sync_block_changed = False
                         else:
                             new_header = verified_header
                             sync_block_changed = True
                             logger.info(f"✅ Idempotent: Profile validated as accurate (Stamped as VERIFIED).")
                     else:
                          new_header = existing_sync_block or ""
                          sync_block_changed = False
                 else:
                     new_header = pure_header
                     sync_block_changed = True
             else:
                 new_header = pure_header
                 sync_block_changed = True

        # v1.2.6: Suppress header if the contact already has a manual 'disappeared' cleanup alert
        if "⚠️ LinkedIn: Profile disappeared" in old_note:
            new_header = ""
        
        # 4.7 B10-FIX: Adopt CCC Knowledge. Note is cleaned BEFORE restructuring.
        clean_note = self.clean_note_ccc(old_note)
        
        # 1. Remove new style blocks from the already cleaned note
        clean_note = re.sub(r"(?s)<Linkedin-AI-sync.*?</Linkedin-AI-sync>", "", clean_note)
        # 2. Remove legacy block formats
        clean_note = re.sub(r"(?s)--- LinkedIn Sync.*?---", "", clean_note)
        
        # Extract existing LinkedIn_Connection_Since if present (PRESERVE EXACT FORMAT)
        existing_since_line = None
        exact_since_match = re.search(r"(?m)^(LinkedIn_Connection_Since:\s*.*)$", clean_note)
        if exact_since_match:
            existing_since_line = exact_since_match.group(1).strip()
            # Remove it from clean_note to avoid duplication in the footer
            clean_note = re.sub(r"(?m)^LinkedIn_Connection_Since:.*$", "", clean_note).strip()
        
        # Extract date value for logic
        existing_since_val = None
        if existing_since_line:
            existing_since_val = existing_since_line.split(":", 1)[1].strip()
        
        # 4. Resolve final_since
        final_since_line = None
        if existing_since_line:
            final_since_line = existing_since_line # Default: preserve format
            
        if profile.connected_date:
            def get_tokens(s):
                return sorted([t.lstrip('0') or '0' if t.isdigit() else t for t in re.findall(r'[a-zA-Z0-9]+', s.lower())])
            
            if existing_since_val and get_tokens(profile.connected_date) == get_tokens(existing_since_val):
                # Same date, keep existing line precisely
                pass
            elif existing_since_val:
                logger.info(f"Updating connection date for {profile.full_name}: {existing_since_val} -> {profile.connected_date}")
                updated_fields.append("Connection Date")
                final_since_line = f"LinkedIn_Connection_Since: {profile.connected_date}"
            else:
                logger.info(f"Adding connection date for {profile.full_name}: {profile.connected_date}")
                added_fields.append("Connection Date")
                final_since_line = f"LinkedIn_Connection_Since: {profile.connected_date}"

        # 5. Remove duplicate role line if already present in history
        if prev_role_line:
            # Check if this specific previous role is already mentioned
            clean_role = re.sub(r'[^a-zA-Z0-9]', '', prev_role_line.lower())
            if clean_role in re.sub(r'[^a-zA-Z0-9]', '', clean_note.lower()):
                prev_role_line = "" 
        
        # Final formatting cleanup
        clean_note = re.sub(r'\n{3,}', '\n\n', clean_note).strip()
        
        if prev_role_line:
            clean_note = prev_role_line + "\n" + clean_note
            
        # Structure: [Sync Block] then [User Notes] then [Blank Line] then [Connection Tag]
        final_note = new_header.strip()
        if clean_note:
            final_note += "\n\n" + clean_note.strip()
        
        if final_since_line:
            final_note += "\n\n" + final_since_line
            
        # v1.2.9: Robust escaping for AppleScript strings
        safe_note = final_note.replace('\\', '\\\\').replace('"', '\\"')
        # Replace newlines for AppleScript string constant
        safe_note = safe_note.replace('\n', '\\n')

        # 6. Execute Multi-Update Script
        # v1.2.7: Protect name from 404/Disappeared poisoning
        # v4.8 B2-FIX: Non-Destructive Name Guard
        name_script = ""
        if not profile.is_disappeared:
            safe_fname = (profile.first_name or "").replace('\\', '\\\\').replace('"', '\\"')
            safe_lname = (profile.last_name or "").replace('\\', '\\\\').replace('"', '\\"')
            safe_mname = (profile.middle_name or "").replace('\\', '\\\\').replace('"', '\\"')
            
            # v4.8 B2-FIX: Check if existing contact already has a curated (non-placeholder) name
            existing_name = (current.get("name") or "").strip()
            PLACEHOLDER_NAMES = {
                "", "M", "Mme", "Me", "Mr", "Mrs", "Ms", "Dr",
                "information not available", "not available", "n/a", "unknown", 
                "not available in the provided content"
            }
            has_curated_name = existing_name.lower() not in PLACEHOLDER_NAMES and len(existing_name) > 3
            
            # v4.8 B2-FIX: Detect concatenation bug (first_name inside last_name)
            is_concat_suspect = False
            if safe_fname and safe_lname and len(safe_fname) > 2:
                if safe_fname.lower() in safe_lname.lower():
                    logger.warning(f"v4.8 B2-FIX: Concatenation suspect — first '{safe_fname}' found inside last '{safe_lname}'. Skipping name update for {contact_id}.")
                    is_concat_suspect = True
            
            if is_concat_suspect:
                name_script = ""  # Skip entirely
            elif has_curated_name:
                logger.info(f"v4.8 B2-FIX: Existing name '{existing_name}' is curated. Skipping full name overwrite for {contact_id}.")
                
                curated_parts = []
                # LSAMC: In curated mode, still uppercase the last name field if a last_name is known
                # v5.5 FIX: Only uppercase if it's a case-only match or very close. Do NOT update if safe_lname is a placeholder.
                current_lname = (current.get("last_name") or "").strip()
                if safe_lname and not safe_lname.isupper() and safe_lname.lower() not in PLACEHOLDER_NAMES:
                    if safe_lname.lower() == current_lname.lower():
                        ucase_lname = safe_lname.upper()
                        curated_parts.append(f'set last name of p to "{ucase_lname}"')
                        logger.info(f"LSAMC: Uppercasing last name for {contact_id}: '{safe_lname}' → '{ucase_lname}'")
                    else:
                        logger.warning(f"v5.5 Guard: Last name discrepancy detected ('{current_lname}' vs '{safe_lname}'). Skipping curation for {contact_id} in curated mode.")
                
                # v5.4: Also update middle name if it's currently empty but we found one
                current_mname = current.get("middle_name", "")
                if safe_mname and not current_mname:
                    curated_parts.append(f'set middle name of p to "{safe_mname}"')
                    logger.info(f"LSAMC: Updating empty middle name for {contact_id} -> '{safe_mname}'")
                
                if curated_parts:
                    name_script = "\n            ".join(curated_parts)
                else:
                    name_script = ""  # Preserve user's local name
            else:
                ucase_lname = safe_lname.upper() if safe_lname else ""
                # v5.6 Bridge Guard — last line of defence before AppleScript write.
                # Blocks placeholder strings that may have slipped past the Pydantic
                # v5.5 guard (e.g. via post-construction assignment before validate_assignment
                # was enabled, or from code paths that build safe_lname independently).
                # An empty ucase_lname would wipe the existing last name with ""; also blocked.
                _BRIDGE_BLOCK = {
                    "NOT AVAILABLE", "AVAILABLE",          # "AVAILABLE" = partial "NOT AVAILABLE"
                    "INFORMATION NOT AVAILABLE", "NO DATA AVAILABLE",
                    "DATA NOT AVAILABLE", "DATA UNAVAILABLE", "N/A", "UNKNOWN",
                    "PAGE DOESN'T EXIST", "PAGE NOT FOUND", "NO INFORMATION AVAILABLE",
                    "THE WORLD'S LARGEST PROFESSIONAL NETWORK",
                    "LINKEDIN MEMBER", "MEMBER",           # "MEMBER" = partial "LinkedIn Member"
                }
                if not ucase_lname or ucase_lname in _BRIDGE_BLOCK or any(
                    ucase_lname.startswith(p) for p in _BRIDGE_BLOCK
                ):
                    logger.warning(
                        f"v5.6 Bridge Guard: Blocking empty/placeholder last name "
                        f"'{ucase_lname}' for {contact_id}. Last name write suppressed."
                    )
                    # Still write first/middle if they are valid
                    if safe_fname:
                        name_script = f'''
            set first name of p to "{safe_fname}"
            set middle name of p to "{safe_mname}"
            '''
                    else:
                        name_script = ""
                else:
                    name_script = f'''
            set first name of p to "{safe_fname}"
            set middle name of p to "{safe_mname}"
            set last name of p to "{ucase_lname}"
            '''
        else:
            logger.warning(f"Skipping name update for {contact_id} because profile is disappeared/poisoned.")

        photo_script = ""
        if getattr(profile, 'photo_blocked', False):
            # v5.4: Identity Guard Lockdown - Explicitly remove photo if blocked
            photo_script = 'set image of p to missing value'
            logger.warning(f"Lockdown: Removing photo from contact {contact_id} due to Guard Block.")
        elif should_update_photo and photo_path and os.path.exists(photo_path):
            photo_script = f'set image of p to (read (POSIX file "{photo_path}") as data)'

        script_parts = []
        safe_suffix = (profile.suffix or "").replace('\\', '\\\\').replace('"', '\\"')
        safe_role = (profile.current_role or "").replace('\\', '\\\\').replace('"', '\\"')
        safe_company = (profile.company or "").replace('\\', '\\\\').replace('"', '\\"')
        
        if safe_suffix != "":
            script_parts.append(f'set suffix of p to "{safe_suffix}"')
        if safe_role != "" and safe_role != "None":
            script_parts.append(f'set job title of p to "{safe_role}"')
        if safe_company != "" and safe_company != "None":
            script_parts.append(f'set organization of p to "{safe_company}"')

        joined_parts = "\n            ".join(script_parts)
        script = f'''
        tell application "Contacts"
            set p to person id "{contact_id}"
            
            {url_cleanup_script}
            
            {name_script}
            
            {joined_parts}
            
            set note of p to "{safe_note}"
            
            {email_script}
            {phone_script}
            {website_script}
            {social_script}
            {bd_script}
            {photo_script}
            
            delay 0.2
            save
            return "SUCCESS"
        end tell
        '''
        if self.mode == "SIMULATION":
            return {
                "success": True, 
                "simulated": True, 
                "proposed_note": final_note,
                "added_fields": added_fields,
                "updated_fields": updated_fields,
                "sync_block_changed": sync_block_changed,
                "proposed_fields": {
                    "first_name": profile.first_name,
                    "last_name": profile.last_name,
                    "job_title": profile.current_role,
                    "organization": profile.company
                }
            }

        logger.info(f"Executing update_contact script (len {len(script)}):\n{script}")
        return self._run_applescript(script)

    def prepend_to_note(self, contact_id: str, text: str) -> Dict[str, Any]:
        """Prepends text to a contact's note safely.

        v4.9.3: Semantic dedup — checks 'contains' for AMBIGUITY/No Profile/disappeared
        markers rather than fragile 'starts with' (which failed when mutual counts changed
        between runs, causing 2-4x duplicate blocks). See JOURNAL 2026-03-26.
        """
        # v4.9.3: Determine the semantic marker for dedup
        if "LSAM AMBIGUITY" in text:
            dedup_marker = "LSAM AMBIGUITY"
        elif "No Profile Found" in text:
            dedup_marker = "No Profile Found"
        elif "Profile disappeared" in text:
            dedup_marker = "Profile disappeared"
        else:
            dedup_marker = None

        if dedup_marker:
            check_clause = f'if currentNote does not contain "{dedup_marker}" then'
        else:
            # Fallback to starts-with for unknown text types
            check_clause = f'if currentNote does not start with "{text}" then'

        script = f'''
        tell application "Contacts"
            set p to person id "{contact_id}"
            set currentNote to note of p
            if currentNote is missing value then set currentNote to ""

            -- v4.9.3: Semantic dedup to prevent accumulation on re-runs
            {check_clause}
                set note of p to "{text}" & return & return & currentNote
            end if
            save
        end tell
        '''
        return self._run_applescript(script)

    def mark_as_disappeared(self, name: str) -> Dict[str, Any]:
        """Removes LinkedIn social profiles and adds disappearance note to a contact."""
        res = self.find_contact(name)
        if not res["success"]:
            return res
        
        contact_id = res["id"]
        today = datetime.now().strftime("%Y-%m-%d")
        notice = f"⚠️ LinkedIn: Profile disappeared as of {today}. Manual cleanup performed."
        
        if self.mode == "SIMULATION":
            logger.info(f"SIMULATION: Marking {name} as disappeared.")
            return {"success": True, "simulated": True}
            
        script = f'''
        tell application "Contacts"
            set p to person id "{contact_id}"
            -- Prepend notice to note
            set oldNote to note of p
            if oldNote is missing value then set oldNote to ""
            set newNote to "{notice}" & return & return & oldNote
            set note of p to newNote
            
            -- Safely delete LinkedIn social profiles
            set socs to every social profile of p
            repeat with i from (count of socs) to 1 by -1
                set s to item i of socs
                try
                    if service name of s contains "LinkedIn" or user name of s contains "linkedin.com" then
                        delete s
                    end if
                end try
            end repeat
            save
        end tell
        '''
        return self._run_applescript(script)

    def remove_linkedin_presence(self, contact_id: str, linkedin_url: Optional[str] = None) -> Dict[str, Any]:
        """Surgically removes LinkedIn handles and sync blocks, leaving a warning (v3.0)."""
        today = datetime.now().strftime("%Y-%m-%d")
        url_text = f" ({linkedin_url})" if linkedin_url else ""
        notice = f"⚠️ Checked LinkedIn on {today}: no confirmed profile{url_text}. Manual rejection performed."
        
        if self.mode == "SIMULATION":
            logger.info(f"SIMULATION: Removing LinkedIn presence for {contact_id}")
            return {"success": True, "simulated": True}
            
        script = f'''
        tell application "Contacts"
            set p to person id "{contact_id}"
            set oldNote to note of p
            if oldNote is missing value then set oldNote to ""
            
            set newNote to "{notice}" & return & return & oldNote
            set note of p to newNote
            
            -- Delete LinkedIn social profiles
            set socs to every social profile of p
            repeat with i from (count of socs) to 1 by -1
                set s to item i of socs
                try
                    set sn to service name of s
                    set un to user name of s
                    set su to url of s
                    if sn is missing value then set sn to ""
                    if un is missing value then set un to ""
                    if su is missing value then set su to ""
                    
                    if sn contains "LinkedIn" or un contains "linkedin.com" or su contains "linkedin.com" then
                        delete s
                    end if
                end try
            end repeat
            save
            return "SUCCESS"
        end tell
        '''
        res = self._run_applescript(script)
        
        # v3.0: After AppleScript prepend, let's do a more thorough cleanup of the note via Python
        if res.get("success"):
            details = self.get_contact_details(contact_id)
            if details.get("success"):
                note = details.get("note", "")
                # Aggressive cleanup of ANY sync artifacts
                clean_note = re.sub(r"(?s)<Linkedin-AI-sync.*?</Linkedin-AI-sync>", "", note)
                clean_note = re.sub(r"(?m)^LinkedIn connection\s*:\s*.*$", "", clean_note, flags=re.IGNORECASE)
                clean_note = re.sub(r"(?m)^LinkedIn_Connection_Since:.*$", "", clean_note).strip()
                
                # If we've already prepended the notice, make sure we don't duplicate it if get_contact_details was slow
                if clean_note != note:
                    # Update with cleaned note
                    safe_note = clean_note.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                    update_script = f'tell application "Contacts" to set note of person id "{contact_id}" to "{safe_note}"'
                    self._run_applescript(update_script)
        
        return res

    def add_to_group(self, contact_id: str, group_name: str, contact_name: str = "") -> Dict[str, Any]:
        """Adds a contact to a group. Creates group if missing.
        v4.9.2: When adding to 'script-LSAM-Force-Refresh', snapshots the contact's
        current macOS modification date into data/force_refresh_queue.json for LIFO ordering.
        Pass contact_name so the queue entry is human-readable.
        """
        if self.mode == "SIMULATION":
            logger.info(f"SIMULATION: Adding contact {contact_id} to group '{group_name}'")
            return {"success": True, "simulated": True}

        script = f'''
        tell application "Contacts"
            if not (exists group "{group_name}") then
                make new group with properties {{name:"{group_name}"}}
                save
                delay 0.5
            end if
            set targetGroup to group "{group_name}"
            set p to person id "{contact_id}"
            if not (exists (person id "{contact_id}" of targetGroup)) then
                add p to targetGroup
                save
                return "ADDED"
            else
                return "ALREADY_IN_GROUP"
            end if
        end tell
        '''
        res = self._run_applescript(script)
        if res["success"]:
            logger.info(f"Group update: {res['output']} (Contact: {contact_id}, Group: {group_name})")
            # v4.9.2 LIFO: snapshot modification date so ordering is stable after engine writes
            if group_name == "script-LSAM-Force-Refresh" and res.get("output") == "ADDED":
                mod_date = self.get_modification_date(contact_id) or datetime.utcnow().isoformat()
                add_to_force_refresh_queue(contact_id, contact_name or contact_id, mod_date)
        return res

    def remove_from_group(self, contact_id: str, group_name: str) -> Dict[str, Any]:
        """Removes a contact from a group."""
        if self.mode == "SIMULATION":
            logger.info(f"SIMULATION: Removing contact {contact_id} from group '{group_name}'")
            return {"success": True, "simulated": True}
            
        script = f'''
        tell application "Contacts"
            if not (exists group "{group_name}") then return "GROUP_NOT_FOUND"
            set targetGroup to group "{group_name}"
            set p to person id "{contact_id}"
            if (exists (person id "{contact_id}" of targetGroup)) then
                remove p from targetGroup
                save
                return "REMOVED"
            else
                return "NOT_IN_GROUP"
            end if
        end tell
        '''
        res = self._run_applescript(script)
        if res["success"]:
            logger.info(f"Group update: {res['output']} (Contact: {contact_id}, Group: {group_name})")
        return res

    def get_modification_date(self, contact_id: str) -> Optional[str]:
        """Returns the macOS modification date string for a contact, or None on failure.
        Lightweight alternative to get_contact_details when only the timestamp is needed.
        Used for LIFO queue snapshotting (v4.9.2).
        """
        script = f'''
        tell application "Contacts"
            try
                set p to person id "{contact_id}"
                return modification date of p as string
            on error
                return ""
            end try
        end tell
        '''
        res = self._run_applescript(script)
        if res["success"] and res.get("output", "").strip():
            return res["output"].strip()
        return None

    def select_contact(self, contact_id: str) -> Dict[str, Any]:
        """Brings Contacts.app to the front and selects the specified contact."""
        script = f'''
        tell application "Contacts"
            activate
            if not (exists person id "{contact_id}") then return "NOT_FOUND"
            
            set thePerson to person id "{contact_id}"
            set selection to {{thePerson}}
            delay 0.1
            
            if selection contains thePerson then
                return "SELECTED"
            else
                return "SELECTION_FAILED_VISIBILITY"
            end if
        end tell
        '''
        return self._run_applescript(script)

    def show_native_dialog(self, message: str, title: str = "LSAMC", buttons: list = ["Skip", "Validate"], default_button: Optional[str] = None, cancel_button: Optional[str] = None) -> Dict[str, Any]:
        """Shows a native macOS dialog and returns the button pressed."""
        # Escape quotes for AppleScript
        safe_message = message.replace('"', '\\"').replace('\n', '" & return & "')
        btn_str = '", "'.join(buttons)
        
        # Determine default/cancel button logic
        extra_logic = []
        if default_button and default_button in buttons:
            extra_logic.append(f'default button "{default_button}"')
        elif buttons:
            extra_logic.append(f'default button "{buttons[-1]}"')
            
        if cancel_button and cancel_button in buttons:
            extra_logic.append(f'cancel button "{cancel_button}"')
        
        logic_str = " ".join(extra_logic)
        
        # v1.2.7: Ensure 'System Events' is used for the dialog but 'Contacts' is also activated if needed
        script = f'''
        tell application "System Events"
            activate
            display dialog "{safe_message}" with title "{title}" buttons {{"{btn_str}"}} {logic_str}
            return result
        end tell
        '''
        res = self._run_applescript(script)
        if res["success"]:
            # AppleScript returns something like '{button returned:"Validate"}'
            match = re.search(r'button returned:(.*)', res["output"])
            if match:
                return {"success": True, "button": match.group(1).strip()}
        
        # Handle "User cancelled" (-128)
        if "User cancelled" in res.get("error", "") or "-128" in res.get("error", ""):
            return {"success": False, "cancelled": True, "error": "User cancelled"}
            
        return res

    def show_in_finder(self, path: str) -> Dict[str, Any]:
        """Opens a folder in Finder and brings it to the front."""
        script = f'''
        tell application "Finder"
            activate
            open POSIX file "{path}"
        end tell
        '''
        return self._run_applescript(script)

    def _parse_bd(self, bd_str: Optional[str]) -> (Optional[int], Optional[int]):
        """Robustly parses Day and Month regardless of language/format. v2.9.3: Smart ISO/Verbal."""
        if not bd_str or bd_str == "": return None, None
        low = bd_str.lower()
        
        # 1. Month Mapping
        month_map = {
            1: ["jan", "janv", "janvier"],
            2: ["feb", "févr", "février"],
            3: ["mar", "mars", "march"],
            4: ["apr", "avr", "avril", "april"],
            5: ["may", "mai"],
            6: ["jun", "juin", "june"],
            7: ["jul", "juil", "juillet", "july"],
            8: ["aug", "août", "august"],
            9: ["sep", "sept", "september"],
            10: ["oct", "octobre", "october"],
            11: ["nov", "novembre", "november"],
            12: ["dec", "déc", "décembre", "december"]
        }
        
        month, day = None, None
        
        for m_num, aliases in month_map.items():
            if any(a in low for a in aliases):
                month = m_num
                break

        # 2. Extract all numbers
        nums = [int(n) for n in re.findall(r'\d+', low)]
        
        # 3. Resolve Day/Month
        if month:
            # If we have a month name, the only other number is the day
            for n in nums:
                if 1 <= n <= 31: 
                    day = n
                    break
        else:
            # No month name found, extract 2 numbers (day/month) and ignore year
            candidates = [n for n in nums if n < 100] # Ignore 4-digit years like 1604
            if len(candidates) >= 2:
                # ISO/Apple format is YYYY-MM-DD (1604-05-18)
                month = candidates[0]
                day = candidates[1]
                
                # Sanity swap if month > 12
                if month > 12 and day <= 12:
                    month, day = day, month
                    
        return day, month

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bridge = ContactMacOSBridge(mode="SIMULATION")
    # Example usage:
    # print(bridge.find_contact("Philippe Dewost"))
