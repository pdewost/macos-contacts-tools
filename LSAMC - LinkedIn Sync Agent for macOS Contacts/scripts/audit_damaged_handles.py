import os
import sys
import logging
import re
import urllib.parse
from typing import List, Dict, Any, Optional
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bridge.contact_macos import ContactMacOSBridge
from src.models.profile import LinkedInProfile

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)-8s [%(name)s] %(message)s')
logger = logging.getLogger("DamagedAudit")

CCC_CLEANING_RULES = """
- Keyword Deduplication
- Halved Line Deduplication
- Consecutive Line Deduplication
- Blank Line Normalization
- LinkedIn-Specific Label stripping
"""

class DamagedHandleAuditor:
    def __init__(self, mode: str = "SIMULATION"):
        self.bridge = ContactMacOSBridge(mode=mode)
        self.mode = mode

    def sanitize_linkedin_handle(self, handle_or_url: str) -> Optional[str]:
        """Extracts the pure vanity handle with high resilience to malformations."""
        if not handle_or_url:
            return None
        
        # 1. Strip whitespace
        s = handle_or_url.strip()
        
        # 2. Iterate to resolve nested URLs (e.g. http://.../https://...)
        # We unquote repeatedly and look for the last /in/ slug
        for _ in range(3):
            s = urllib.parse.unquote(s)
            if "linkedin.com/in/" in s:
                parts = s.split("linkedin.com/in/")
                # Take the last part (the actual handle)
                candidate = parts[-1].split("?")[0].split("/")[0].strip()
                if candidate:
                    s = candidate
                    break
            elif "/in/" in s:
                parts = s.split("/in/")
                candidate = parts[-1].split("?")[0].split("/")[0].strip()
                if candidate:
                    s = candidate
                    break
        
        # 3. Final cleanup: strip any remaining protocol bloat if iteration failed
        s = s.split("?")[0].strip("/")
        if "linkedin.com" in s:
            # If we still have a URL after 3 unquotes, it's really messy
            # Try a direct search for the likely handle pattern
            match = re.search(r'/in/([a-zA-Z0-9\-\_]+)', s)
            if match:
                s = match.group(1)
        
        # 4. Final validation: should look like a handle
        # Handles are typically alphanumeric with hyphens
        if re.match(r'^[a-zA-Z0-9\-\_]+$', s) and len(s) > 2:
            # Basic sanity check: handles aren't usually things like "missing"
            if s.lower() not in ["missing", "unknown", "linkedin"]:
                return s
        return None

    def clean_note_ccc(self, note: str) -> str:
        """Applies canonical CCC cleaning rules."""
        if not note: return ""
        lines = note.split('\n')
        clean_lines = []
        
        for line in lines:
            l = line.strip()
            # 1. Label Stripping
            prefixes = ["Location ", "Degree Name ", "Field Of Study ", "Dates Employed ", 
                        "Employment Duration ", "Total Duration "]
            for p in prefixes:
                if l.startswith(p):
                    l = l[len(p):].strip()
            
            # 2. Artifact removal
            if "Show all " in l and " experience" in l: continue
            if l.endswith(" logo"): continue
            if "degree connection" in l.lower(): continue
            
            # 3. Keyword duplication (ExperienceExperience -> Experience)
            keywords = ["Experience", "Education", "Skills", "About me", "Summary"]
            for k in keywords:
                if l == k + k or l == k + " " + k:
                    l = k
            
            # 4. Halved Line Deduplication
            if len(l) > 0 and len(l) % 2 == 0:
                mid = len(l) // 2
                if l[:mid] == l[mid:]:
                    l = l[:mid]
            
            # 5. Consecutive Line Deduplication
            if clean_lines and l == clean_lines[-1]:
                continue
            
            # 6. Remove #lsam-force-resync
            if l == "#lsam-force-resync": continue
            
            clean_lines.append(l)
            
        # 7. Blank Line Normalization (max 2)
        # 8. Header Formatting
        formatted_lines = []
        for l in clean_lines:
            if l in ["Contact Info", "Experience", "Education"]:
                formatted_lines.append(f"==== {l}")
            else:
                formatted_lines.append(l)
                
        # Join and fix consecutive breaks
        text = '\n'.join(formatted_lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    async def audit_group(self, group_name: str):
        logger.info(f"Starting audit of group: {group_name} ({self.mode} mode)")
        contacts = self.bridge.list_group_contacts(group_name)
        if not contacts["success"]:
            logger.error(f"Failed to list contacts: {contacts.get('error')}")
            return

        matches = contacts.get("matches", [])
        logger.info(f"Found {len(matches)} contacts in group.")

        for contact in matches:
            cid = contact["id"]
            name = contact["name"]
            logger.info(f"--- Auditing: {name} ---")
            
            details = self.bridge.get_contact_details(cid)
            if not details["success"]:
                logger.error(f"Failed to get details for {name}")
                continue

            # Analyze Social Profiles
            socials = details.get("social", [])
            urls = details.get("websites", [])
            
            handles_found = []
            malformed_handles = []
            
            # 1. Harvest handles from social profiles
            for s in socials:
                # Format: Service|USER:xxx|URL:yyy
                parts = s.split("|")
                if len(parts) >= 3:
                    user = parts[1].replace("USER:", "").strip()
                    s_url = parts[2].replace("URL:", "").strip()
                    
                    h = self.sanitize_linkedin_handle(user) or self.sanitize_linkedin_handle(s_url)
                    if h:
                        if h not in handles_found: handles_found.append(h)
                    else:
                        malformed_handles.append(s)

            # 2. Harvest handles from website URLs
            for u in urls:
                if "linkedin.com" in u.lower():
                    h = self.sanitize_linkedin_handle(u)
                    if h and h not in handles_found:
                        handles_found.append(h)

            # 3. Decision Logic
            if not handles_found:
                logger.warning(f"No valid handle found for {name}. Socials: {socials} | URLs: {urls}")
                continue

            # Pick the "True Handle" (first one for now, or the most vanity-looking one)
            # Longest handle is often more canonical if there are sub-parts
            true_handle = sorted(handles_found, key=len, reverse=True)[0]
            canonical_url = f"https://www.linkedin.com/in/{true_handle}"

            logger.info(f"True Handle: {true_handle} | Canonical URL: {canonical_url}")

            # 4. Apply Fix (if in FULL mode)
            if self.mode == "FULL":
                # Create a minimal profile for the update_contact method
                # We just want to fix the handles
                from src.models.profile import LinkedInProfile
                dummy_profile = LinkedInProfile(
                    full_name=name,
                    linkedin_url=canonical_url
                )
                
                # The bridge.update_contact handles deduplication of social profiles
                # but it might ADD the new one. We actually want to PURGE the old ones.
                # So we might need a more specialized bridge method or a direct AppleScript here.
                
                self.repair_handles_applescript(cid, true_handle, canonical_url)

    def repair_handles_applescript(self, cid: str, handle: str, url: str):
        """Surgically cleans all LinkedIn socials/urls and replaces with one clean pair."""
        script = f'''
        tell application "Contacts"
            set p to person id "{cid}"
            
            -- 1. Force purge ALL social profiles
            set sCount to count of social profiles of p
            repeat with i from sCount to 1 by -1
                delete social profile i of p
            end repeat
            
            -- 2. Purge LinkedIn-specific URLs
            set uCount to count of urls of p
            repeat with i from uCount to 1 by -1
                try
                    set u to url i of p
                    set uv to value of u as string
                    set ul to label of u as string
                    if uv contains "linkedin.com" or ul contains "LinkedIn" then
                        delete u
                    end if
                end try
            end repeat
            
            -- 3. Add canonical versions
            make new social profile at end of social profiles of p with properties {{service name:"LinkedIn", user name:"{handle}"}}
            make new url at end of urls of p with properties {{label:"LinkedIn", value:"https://www.linkedin.com/in/{handle}"}}
            
            save
        end tell
        '''
        res = self.bridge._run_applescript(script)
        if res["success"]:
            logger.info(f"Successfully repaired handles for {cid}")
            # Also clean the note as per CCC if we are in FULL mode
            details = self.bridge.get_contact_details(cid)
            original_note = details.get("note", "")
            cleaned_note = self.clean_note_ccc(original_note)
            if cleaned_note != original_note:
                 self.bridge._run_applescript(f'''
                    tell application "Contacts"
                        set p to person id "{cid}"
                        set note of p to "{cleaned_note.replace('"', '\\"')}"
                        save
                    end tell
                 ''')
                 logger.info(f"Cleaned note for {cid} according to CCC spec")
        else:
            logger.error(f"Failed to repair handles for {cid}: {res.get('error')}")

if __name__ == "__main__":
    import asyncio
    mode = "FULL" if "--apply" in sys.argv else "SIMULATION"
    auditor = DamagedHandleAuditor(mode=mode)
    asyncio.run(auditor.audit_group("script-LSAM-DAMAGED"))
