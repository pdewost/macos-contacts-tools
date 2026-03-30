import os
import glob
import json
import logging
import subprocess
import time
import re
import datetime
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# --- Path Initialization ---
# Ensure project root is in sys.path for absolute imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Configure Logging
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "staged_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("StagedManager")

FEEDBACK_LOG = LOG_DIR / "user_feedback.jsonl"
SESSION_ROOT = LOG_DIR / "sessions"

class StagedContactManager:
    VERSION = "v3.5.2"

    def __init__(self):
        # Initialize bridge in FULL mode
        try:
            from src.bridge.contact_macos import ContactMacOSBridge
            from src.models.profile import LinkedInProfile
            from src.bridge.image_optim import get_image_resolution
            self.bridge = ContactMacOSBridge(mode="FULL")
            self.LinkedInProfile = LinkedInProfile
            self.get_image_resolution = get_image_resolution
            logger.info("Bridge and Models initialized.")
        except ImportError as e:
            logger.error(f"Could not import required modules: {e}")
            raise

        self.ready_contacts: List[Dict] = []
        self.review_contacts: List[Dict] = []
        self.tier3_ids: List[str] = []

    def _fetch_ground_truth(self):
        """
        v3.5.3: Fetches IDs from all relevant LSAM groups to avoid archiving active candidates.
        """
        target_groups = [
            "script-LSAM-Force-Refresh",
            "script-LSAM-Tier3-NeedAttention",
            "script-LSAM-Tier2-NoteHasLinkedIn",
            "script-LSAM-LinkedIn to Review",
            "script - no photo and on LinkedIn"
        ]
        self.tier3_ids = []
        for group in target_groups:
            try:
                res = self.bridge.list_group_contacts(group)
                if res.get("success"):
                    group_ids = [m["id"] for m in res.get("matches", [])]
                    self.tier3_ids.extend(group_ids)
                    logger.info(f"Loaded {len(group_ids)} IDs from {group}")
            except Exception as e:
                logger.warning(f"Error fetching group {group}: {e}")
        
        # Deduplicate
        self.tier3_ids = list(set(self.tier3_ids))
        logger.info(f"Total Ground Truth: {len(self.tier3_ids)} active LSAM IDs.")

    def scan_backlog(self):
        """Scans all session backups for pending profiles, applying smart deduplication."""
        logger.info("Scanning backlog with Smart Deduplication...")
        self._fetch_ground_truth()
        
        # 1. Collect all candidates from all engine roots
        candidates_by_id: Dict[str, List[Dict]] = {}
        
        # v1.7.8 (Option B): Multi-Engine Awareness
        # We scan both baseline sessions and fast_sessions
        session_roots = [LOG_DIR / "sessions", LOG_DIR / "fast_sessions"]
        patterns = [str(root / "*" / "backups" / "*" / "profile.json") for root in session_roots]
        
        files = []
        for p in patterns:
            files.extend(glob.glob(p))
        
        for f_path in files:
            try:
                path_obj = Path(f_path)
                folder = path_obj.parent
                
                # Exclude if already applied, flagged, or pending resync
                if (folder / ".applied").exists():
                    continue
                if (folder / ".flagged").exists():
                    continue
                if (folder / ".resync").exists():
                    continue
                
                if not os.path.exists(f_path) or os.path.getsize(f_path) == 0:
                    continue
                    
                with open(f_path, 'r') as f:
                    try:
                        profile = json.load(f)
                    except json.JSONDecodeError as je:
                        logger.error(f"Corruption detected in {f_path}: {je}")
                        continue
                
                # Determine Contact ID - prioritize internal ID over folder name
                cid = profile.get("_contact_id") or profile.get("id") or profile.get("contact_id")
                
                folder_name = folder.name
                if not cid:
                    # Fallback to folder name ID if present
                    cid = folder_name.split("_")[-1] if "_" in folder_name else folder_name
                
                if not cid:
                    logger.debug(f"Skipping {f_path}: No Contact ID found.")
                    continue

                name_display = profile.get("full_name") or profile.get("Name") or folder_name.rsplit("_", 1)[0]
                
                # Check against EXCLUSIONS
                if name_display in ["Pascal Ancian", "Benny Marom", "Danielle LIGOUT", "M. Jean-Claude MALLET", "Jean-Claude MALLET"]:
                    logger.debug(f"Skipping {name_display}: Present in EXCLUSIONS.")
                    continue

                info = {
                    "path": folder,
                    "profile": profile,
                    "id": cid,
                    "name": name_display,
                    "session_path": folder.parent.parent,
                    "timestamp": folder.parent.parent.name
                }
                
                info["score"] = self._calculate_score(info)
                
                if cid not in candidates_by_id:
                    candidates_by_id[cid] = []
                candidates_by_id[cid].append(info)
                    
            except Exception as e:
                logger.error(f"Error scanning {f_path}: {e}")
                continue

        # 2. Select best candidate per ID
        self.ready_contacts = []
        self.review_contacts = []
        
        orphans = []

        for cid, candidates in candidates_by_id.items():
            # Sort by score (desc), then by timestamp (desc)
            candidates.sort(key=lambda x: (x["score"], x["timestamp"]), reverse=True)
            best = candidates[0]
            
            # Ground Truth Check
            is_active = cid in self.tier3_ids
            
            if not is_active:
                orphans.append(best)
                continue

            # v2.6 Surgical Qualification
            status, reason = self._qualify_contact(best["profile"], best["path"])
            best["reason"] = reason
            if status == "READY":
                self.ready_contacts.append(best)
            else:
                self.review_contacts.append(best)

        # 3. Log results
        total_unique = len(candidates_by_id)
        logger.info(f"Deduplication: Reduced {len(files)} entries to {total_unique} unique contacts.")
        logger.info(f"Results: {len(self.ready_contacts)} READY, {len(self.review_contacts)} REVIEW.")
        
        if orphans:
            logger.info(f"Orphans (not in Tier 3): {len(orphans)}. Auto-archiving...")
            self._archive_orphans(orphans)

    def _calculate_score(self, info: Dict) -> int:
        """Calculates a richness score as per Master Design v2.5."""
        score = 0
        profile = info["profile"]
        folder = info["path"]
        
        # 1. Photos (Weight +100)
        # HEIC > JPG > No Image
        if (folder / "linkedin.heic").exists():
            score += 100
        elif (folder / "linkedin-raw.jpg").exists():
            score += 50
        
        # 2. Recency (+10/day)
        try:
            # folder name format: "Mrs_Catherine_Heald" usually, but it's in run_YYYY-MM-DD
            session_date_str = info["timestamp"].split("_")[1] # e.g. 2026-01-30
            session_date = datetime.datetime.strptime(session_date_str, "%Y-%m-%d")
            today = datetime.datetime.now()
            days_diff = (today - session_date).days
            # Newer is better, so newer sessions get higher scores
            score += max(0, (30 - days_diff) * 10) # Base 30 day relevance
        except:
            pass

        # 3. Completeness (+10 per field)
        # Count non-empty fields in profile
        fields = ["birthday", "emails", "phones", "websites", "current_role", "company"]
        for f in fields:
            val = profile.get(f)
            if val and val != [] and val != "":
                score += 10
            
        # 4. Session Health 
        if not self._is_session_healthy(info["session_path"]):
            score -= 200 # Heavy penalty for crashed sessions
            
        return score

    def _is_session_healthy(self, session_path: Path) -> bool:
        """Checks if session ended prematurely."""
        # Check if backups/ folder has more than 1 entry (at least this contact succeeded)
        backups = session_path / "backups"
        if not backups.exists(): return False
        
        # Check log for critical failure
        log_file = session_path / "session.log"
        if log_file.exists():
            try:
                # Only check last 1KB for efficiency
                with open(log_file, 'rb') as f:
                    f.seek(0, 2)
                    size = f.tell()
                    chunk_size = min(size, 2048)
                    f.seek(max(0, size - chunk_size))
                    last_chunk = f.read().decode('utf-8', errors='ignore')
                    if "CIRCUIT BREAKER" in last_chunk or "CRITICAL: BROWSER CRASH" in last_chunk:
                        return False
            except:
                pass
        return True

    def _archive_orphans(self, orphans: List[Dict]):
        """Moves orphan folders to archive to keep backlog clean."""
        archive_root = Path("data/vault/archived")
        archive_root.mkdir(parents=True, exist_ok=True)
        
        successes = 0
        for contact in orphans:
            try:
                # We move the entire backup folder
                target = archive_root / contact["timestamp"] / contact["path"].name
                target.parent.mkdir(parents=True, exist_ok=True)
                
                # Use sub-processing mv to handle potential cross-partition shifts
                subprocess.run(["mv", str(contact["path"]), str(target)], check=True)
                successes += 1
            except Exception as e:
                logger.debug(f"Failed to archive orphan {contact['name']}: {e}")
        
        if successes > 0:
            logger.info(f"Archived {successes} orphan contact sessions.")

    def _qualify_contact(self, profile: Dict, folder: Path) -> (str, str):
        """Decides if a contact is Ready or Needs Review with 'Jacqueline PIC' Value Filter."""
        # 1. Names
        first = profile.get("First Name") or profile.get("first_name")
        last = profile.get("Last Name") or profile.get("last_name")
        full = profile.get("full_name") or profile.get("Name")
        
        has_name = (first and last) or full
        if not has_name:
            return "REVIEW", "Orphaned data (No Name)"
            
        # 2. Professional Info
        title = profile.get("current_role") or profile.get("Occupation") or profile.get("Headline")
        
        # 3. Signals (New: Check for discrepancy flag)
        if profile.get("has_discrepancy"):
            return "REVIEW", "Discrepancy detected"
        if profile.get("is_disappeared"):
            return "REVIEW", "Profile 404/Disappeared"

        # 4. Photo Check
        photo_status = profile.get("photo_extraction_status") or profile.get("Photo Status")
        has_photo_file = (folder / "linkedin.heic").exists() or (folder / "linkedin-raw.jpg").exists()
        
        if photo_status == "FAILED" or photo_status == "REJECTED":
            return "REVIEW", f"Photo {photo_status}"

        # 5. v2.6 Value Filter (The Jacqueline PIC Guard)
        # If no photo AND no title AND no summary, it's a Low-Value update
        if not has_photo_file and (not title or title in ["--", "", "-"]) and not profile.get("summary"):
            return "REVIEW", "Low Value / Zero Delta (No Photo/Title)"

        if not title:
            return "REVIEW", "No Professional Title"

        return "READY", "Good Fidelity"

    def _show_help_dialog(self):
        """Displays the Help / Legend dialog."""
        help_text = (
            "--- FLAG / SIGNAL ---\\n"
            "• Wrong Contact: Search found wrong person.\\n"
            "• Wrong Profile: Severe mismatch (blacklists URL).\\n"
            "• Photo/Data Issues: Bad quality or missing fields.\\n\\n"
            "--- MORE ACTIONS ---\\n"
            "• 📂 Open Vault: View raw files/JSON.\\n"
            "• 🔗 Open LinkedIn: Verify source.\\n"
            "• 🔄 Retry (Tier 3): Skip & force scraper retry.\\n"
            "• 🗑️ Discard: Mark false match & clear URL."
        )
        self._show_dialog("Staged Manager Guide", help_text, ["OK"])

    def _handle_more_actions(self, contact: Dict, context: str) -> str:
        """Handles the More Actions menu flow. Returns 'STOP', 'SKIP', 'CONTINUE'."""
        cid = contact["id"]
        
        options = [
            "📂 Open Vault Folder",
            "🔗 Open LinkedIn Profile",
            "🚫 Skip (Do Nothing)",
            "🔄 Reduce Scope (Edit Profile)", 
            "🗑️ Discard / Purge",
            "🛑 Quit Manager"
        ]
        
        if context == "READY":
             options.insert(0, "✨ Apply Update (Verify)")

        # v3.5.2: Expanded Options
        options.extend([
            "🚩 Flag / Signal Issue...",
            "🔄 Force Full Re-Sync",
            "📸 Force Photo Retry (Tier 2)"
        ])

        selection = self._choose_from_list("More Actions:", options, title="More Actions")
        
        if selection == "CANCEL" or selection == "None":
            return "CONTINUE"
            
        if "Quit" in selection:
            return "STOP"
        elif "Skip" in selection:
             return "SKIP"
        elif "Apply" in selection:
             if self._apply_contact(contact):
                 if context == "READY": self.ready_contacts.remove(contact)
                 elif context == "REVIEW": self.review_contacts.remove(contact)
             return "CONTINUE" # List modified, but we continue loop
        
        elif "Open Vault" in selection:
             subprocess.run(["open", str(contact["path"])])
        
        elif "Open LinkedIn" in selection:
             url = contact["profile"].get("linkedin_url")
             if url: subprocess.run(["open", url])
             else: self._show_dialog("Error", "No LinkedIn URL found.", ["OK"])

        elif "Flag" in selection:
             self._handle_flagging(contact)
             if context == "REVIEW" and contact not in self.review_contacts:
                 # If flagging removed it (e.g. discard), we are done
                 return "CONTINUE"

        elif "Force Full Re-Sync" in selection:
             self._handle_resync(contact)
             # Resync shows its own dialog usually, unless we silence it? 
             # Let's keep the dialog from handle_resync as confirmation
             return "SKIP"

        elif "Photo Retry" in selection:
             self._handle_resync(contact, silent=True)
             self._show_dialog("Photo Retry", "Scheduled for re-sync. The agent will attempt photo extraction again.", ["OK"])
             return "SKIP"
             

             if self._show_dialog("Confirm", "Discard this contact and delete the session?", ["No", "Yes"], default="No") == "Yes":
                 # Archive as orphan/discarded
                 self._archive_orphans([contact])
                 if context == "READY": self.ready_contacts.remove(contact)
                 elif context == "REVIEW": self.review_contacts.remove(contact)
                 return "CONTINUE"
                 
        elif "Reduce Scope" in selection:
             self._show_dialog("Not Implemented", "Profile editing not available in this version. Edit the JSON directly.", ["OK"])
             subprocess.run(["open", "-t", str(contact["path"] / "profile.json")])
             
        return "CONTINUE"

    # --- AppleScript UI Helpers ---

    def _run_script(self, script: str) -> str:
        """Runs an AppleScript and returns stdout (or CANCEL on error)."""
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, check=True
            )
            return res.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"AppleScript Error: {e.stderr}")
            return "CANCEL"

    def _show_dialog(self, title: str, text: str, buttons: List[str], default: str = None) -> str:
        btns_str = "{" + ", ".join([f'"{b}"' for b in buttons]) + "}"
        default_str = f'default button "{default}"' if default else ""
        icon_str = 'with icon note'
        
        # Escape for AppleScript
        safe_text = text.replace('"', '\\"').replace('\n', '\\n')
        # v3.5.2: Inject Version
        full_title = f"{title} ({self.VERSION})"
        safe_title = full_title.replace('"', '\\"')
        
        script = f'''
        tell application "System Events"
            activate
            delay 0.5
            set userChoice to button returned of (display dialog "{safe_text}" with title "{safe_title}" buttons {btns_str} {default_str} {icon_str})
        end tell
        if userChoice is "More Actions..." then return "MORE_ACTIONS"
        return userChoice
        '''
        return self._run_script(script)

    def _choose_from_list(self, prompt: str, items: List[str], title: str = "Select Option") -> str:
        """Helper to show an AppleScript choice dialog."""
        # Escape items
        safe_items = [i.replace('"', '\\"') for i in items]
        items_str = "{" + ", ".join([f'"{i}"' for i in safe_items]) + "}"
        
        # Escape prompt and title
        safe_prompt = prompt.replace('"', '\\"').replace('\n', '\\n')
        # v3.5.2: Inject Version
        full_title = f"{title} ({self.VERSION})"
        safe_title = full_title.replace('"', '\\"')
        
        script = f'''
        tell application "System Events"
            activate
            delay 0.5
            set userSelection to choose from list {items_str} with title "{safe_title}" with prompt "{safe_prompt}"
        end tell
        if userSelection is false then return "CANCEL"
        return item 1 of userSelection
        '''
        return self._run_script(script)

    def _get_backend_status(self) -> str:
        """Parses real-time supervisor status or SYNC_PROGRESS.md for state."""
        try:
            # v3.5.0: Prefer the real-time status file from supervisor
            status_file = PROJECT_ROOT / "logs" / ".supervisor_status"
            if status_file.exists():
                try:
                    with open(status_file, 'r') as f:
                        data = json.load(f)
                    # Check for staleness (e.g. if script crashed and didn't cleanup)
                    if time.time() - data.get("timestamp", 0) < 60:
                        group = data.get("group", "Unknown")
                        start = data.get("start_time", "")
                        return f"🟢 Active: {group} (Started {start})"
                except: pass

            progress_file = PROJECT_ROOT / "SYNC_PROGRESS.md"
            if not progress_file.exists():
                return "Inactive"
            
            with open(progress_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract Status
            import re
            status_match = re.search(r"\*\*Status\*\*: (.*?)(?:\s\||$)", content)
            status = status_match.group(1).strip() if status_match else "Unknown"
            
            # Extract Progress
            # Looking for: `0 / 86` contacts **(0.0%)**
            prog_match = re.search(r"`(\d+)\s+/\s+(\d+)` contacts \*\*(.*?)\*\*", content)
            if prog_match:
                current, total, pct = prog_match.groups()
                progress_str = f"{pct} ({current}/{total})"
            else:
                progress_str = ""

            # Format
            icon = "🔴" if status in ["Stopped", "Inactive"] else "🟢"
            if "Error" in status or "Issue" in status: icon = "⚠️"
            
            return f"{icon} {status} {progress_str}".strip()
        except Exception as e:
            logger.error(f"Error reading backend status: {e}")
            return "Inactive"

    # --- Core Loops ---

    def run_interactive(self):
        """Main Entry Point."""
        self.scan_backlog()
        
        while True:
            r = len(self.ready_contacts)
            n = len(self.review_contacts)
            
            options = [
                f"Process Ready ({r})",
                f"Review Needs Attention ({n})",
                "Scan Again",
                "🚀 Launch Backend...",
                "View Session Logs",
                "Help / Guide",
                "Quit"
            ]
            
            backend_status = self._get_backend_status()
            
            choice = self._choose_from_list(
                f"Backend System: {backend_status}\n\nStaging Area:\n✅ Ready to Sync: {r}\n⚠️ Needs Attention: {n}\n\nSelect an action:",
                options,
                title="Staged Manager v3.5.1"
            )
            

            if choice == "Quit" or choice == "CANCEL":
                break
            elif choice == "Help / Guide":
                self._show_help_dialog()
            elif choice == "View Session Logs":
                subprocess.run(["open", str(LOG_DIR)])
            elif choice == "Scan Again":
                self.scan_backlog()
                r = len(self.ready_contacts)
                n = len(self.review_contacts)
                self._show_dialog("Scan Complete", f"Found {r} Ready items and {n} items needing attention.", ["OK"])
                continue

            elif choice.startswith("Process Ready"):
                if self._process_ready_loop() == "STOP":
                    break
            elif choice == "🚀 Launch Backend...":
                self._handle_backend_launch()
            elif choice.startswith("Review Needs Attention"):
                if self._review_loop() == "STOP":
                    break
                
            # Re-scan after operations to update counts
            self.scan_backlog()

    def _process_ready_loop(self):
        """Batch processing loop for Ready contacts. v2.7: Surgical Mode."""
        idx = 0
        total = len(self.ready_contacts)
        
        while idx < len(self.ready_contacts):
            contact = self.ready_contacts[idx]
            cid = contact["id"]
            
            # v2.7 Restoration: Auto-select and show comparison
            logger.info(f"Processing Ready Item {idx+1}/{total}: {contact['name']} (CID: {cid})")
            try:
                self.bridge.select_contact(cid)
            except Exception as e:
                logger.error(f"Failed to select contact {cid}: {e}")
            
            existing = self.bridge.get_contact_details(cid)
            
            # Construct summary
            profile_dict = contact["profile"]
            folder = contact["path"]
            
            # Generate Blocks for Comparison
            proposed_info = self._generate_surgical_comparison(profile_dict, existing, folder, cid)
            
            if proposed_info.get("is_exemptible"):
                btns = ["More Actions...", "Skip", "Confirm Exemption"]
                default_btn = "Confirm Exemption"
            elif proposed_info["is_regression"]:
                btns = ["More Actions...", "Skip & Re-Sync", "Apply Anyway"]
                default_btn = "Apply Anyway"
            elif "Photo" in proposed_info.get("updated_fields", []):
                btns = ["More Actions...", "Skip", "Update Photo"]
                default_btn = "Update Photo"
            else:
                btns = ["More Actions...", "Skip", "Apply"]
                default_btn = "Apply"


            action = self._show_dialog(
                f"Reviewing READY ({idx+1}/{total})",
                proposed_info["text"],
                btns,
                default=default_btn
            )
            
            if action == "MORE_ACTIONS":
                res = self._handle_more_actions(contact, "READY")
                if res == "STOP": return "STOP"
                elif res == "SKIP": 
                    idx += 1
                    continue
                # If CONTINUE, loop back to show dialog again
                continue

            if action in ["Stop", "CANCEL", "None"]:
                logger.info("User cancelled or stopped.")
                return "STOP"
            elif action == "Skip":
                idx += 1
            elif action == "Skip & Re-Sync":
                self._handle_resync(contact)
                self.ready_contacts.pop(idx)
                total -= 1
            elif action == "Confirm Exemption":
                if self._exempt_contact(contact):
                    self.ready_contacts.pop(idx)
                    total -= 1
                else:
                    self._show_dialog("Error", "Failed to exempt contact.", ["OK"])
                    idx += 1
            elif action.startswith("Apply") or action == "Update Photo":
                if self._apply_contact(contact):
                    self.ready_contacts.pop(idx)
                    total -= 1
                else:
                    self._show_dialog("Error", f"Failed to apply {contact['name']}.", ["OK"])
                    idx += 1

            



    def _review_loop(self):
        """Interactive review for 'Needs Attention' contacts. v2.7: Surgical Mode."""
        if not self.review_contacts:
            self._show_dialog("Info", "No contacts need attention.", ["OK"])
            return

        i = 0
        while i < len(self.review_contacts):
            contact = self.review_contacts[i]
            cid = contact["id"]
            
            self.bridge.select_contact(cid)
            existing = self.bridge.get_contact_details(cid)
            
            profile_dict = contact["profile"]
            folder = contact["path"]
            
            proposed_info = self._generate_surgical_comparison(profile_dict, existing, folder)
            
            # Action Buttons - Max 3
            if proposed_info.get("is_exemptible"):
                btns = ["More Actions...", "Skip", "Confirm Exemption"]
                default_btn = "Confirm Exemption"
            elif proposed_info["is_regression"]:
                btns = ["More Actions...", "Skip & Re-Sync", "Apply Anyway"]
                default_btn = "Apply Anyway"
            elif "Photo" in proposed_info.get("updated_fields", []):
                btns = ["More Actions...", "Skip", "Update Photo"]
                default_btn = "Update Photo"
            else:
                btns = ["More Actions...", "Skip", "Apply"]
                default_btn = "Apply"

            action = self._show_dialog(
                f"Reviewing NEEDS ATTENTION ({i+1}/{len(self.review_contacts)})",
                proposed_info["text"],
                btns,
                default=default_btn
            )
            
            if action == "MORE_ACTIONS":
                res = self._handle_more_actions(contact, "REVIEW")
                if res == "STOP": return "STOP"
                elif res == "SKIP": 
                    i += 1
                    continue
                # If CONTINUE, loop back to show dialog again
                continue
            
            if action in ["Stop", "CANCEL"]:
                return "STOP"
            elif action == "Skip":
                i += 1
            elif action == "Skip & Re-Sync":
                self._handle_resync(contact)
                self.review_contacts.pop(i)
            elif action == "Confirm Exemption":
                if self._exempt_contact(contact):
                    self.review_contacts.pop(i)
                else:
                    self._show_dialog("Error", "Failed to exempt contact.", ["OK"])
                    i += 1
            elif action.startswith("Apply") or action == "Update Photo":
                if self._apply_contact(contact):
                    self.review_contacts.pop(i)
                else:
                    self._show_dialog("Error", "Failed to apply contact. See logs.", ["OK"])
                    i += 1
            elif action == "Flag / Signal":
                self._handle_flagging(contact)
                self.review_contacts.pop(i)

    def _generate_surgical_comparison(self, staged_profile: Dict, existing: Dict, folder: Path, cid: str) -> Dict:
        """v2.8 Calculation: Robustly confronts extraction vs native data with history awareness. v5.5: Photo Logic."""
        try:
            # 1. Rehydrate model
            p = self.LinkedInProfile.model_validate(staged_profile)
            
            # 2. Extract Current Context and History
            old_note = existing.get("note", "")
            old_block = self._extract_sync_block(old_note)
            old_title = existing.get("job_title", "")
            old_bday_native = existing.get("birthday", "")
            
            # v2.9: Duplicate / Ghost Target Detection
            # If the current target has no Job and no Note, but the name is common, 
            # we need to check if there's a BETTER card we are missing.
            warnings = []
            
            # Surface Manual Alarms (v3.1)
            if old_note:
                for line in old_note.split("\n"):
                    line = line.strip()
                    if line.startswith("⚠️") and "Linkedin-AI-sync" not in line:
                         warnings.append(line)

            if not old_title and not old_note:
                # v3.5.2 PERFORMANCE FIX: Disabled "Ghost Target Detection"
                # The 'whose name is' AppleScript is too slow (60s+) on large databases.
                # Re-enable only if we have a faster lookup method (e.g. internal cache).
                pass
                # try:
                #     name_check = p.full_name or ""
                #     # AppleScript to count matches
                #     chk_script = f'tell application "Contacts" to count (people whose name is "{name_check}")'
                #     res = self.bridge._run_applescript(chk_script)
                #     count = int(res.get("output", "0").strip()) if res["success"] else 0
                #     
                #     if count > 1:
                #         warnings.append(f"⚠️ PROBABLE DUPLICATE: found {count} contacts named '{name_check}'.")
                #         warnings.append(f"⚠️ TARGETING WRONG CARD? (Target ID: {staged_profile.get('_contact_id', 'Unknown')}) has NO DATA.")
                # except:
                #     pass

            
            # Use the new model-level parser for historical context
            prev_stats = p.parse_history_from_block(old_block)
            m_prev = prev_stats.get('common') or 0
            
            # 3. Detect Regressions & Conflicts
            is_regression = False
            
            # Regression: Mutual connections drop
            m_curr = p.common_connections_count or 0
            if m_curr < m_prev and m_prev > 0:
                is_regression = True
                warnings.append(f"⚠️ REGRESSION: Mutual Connections dropped {m_prev} -> {m_curr}")
            
            # v5.5: Photo Age and Quality Logic
            is_photo_upgrade = False
            is_photo_old = False
            photo_info = "No LinkedIn Photo"
            
            new_photo_path = folder / "linkedin.heic"
            if not new_photo_path.exists():
                new_photo_path = folder / "linkedin-raw.jpg"
            
            if new_photo_path.exists():
                new_w, new_h = self.get_image_resolution(str(new_photo_path))
                new_res = new_w * new_h
                photo_info = f"LinkedIn: {new_w}x{new_h}"
                
                # Check current photo
                if existing.get("has_image"):
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        tmp_path = tmp.name
                    
                    try:
                        export_res = self.bridge.export_contact_photo(cid, tmp_path)
                        if export_res.get("success") and export_res.get("path"):
                            old_w, old_h = self.get_image_resolution(tmp_path)
                            old_res = old_w * old_h
                            
                            if new_res > old_res * 1.2: # 20% margin for upgrade
                                is_photo_upgrade = True
                                warnings.append(f"📸 PHOTO UPGRADE: {new_w}x{new_h} vs {old_w}x{old_h}")
                            
                            # Age Check
                            photo_date_str = prev_stats.get("photo_date")
                            if not photo_date_str:
                                # Fallback to contact modification date if no photo date in block
                                mod_date = existing.get("modification_date", "")
                                try:
                                    d_match = re.search(r"(\d{1,2})\s+([a-zéû.]*)\s+(\d{4})", mod_date.lower())
                                    if d_match:
                                        mod_year = int(d_match.group(3))
                                        current_year = datetime.datetime.now().year
                                        if current_year - mod_year >= 3:
                                            is_photo_old = True
                                            warnings.append(f"📸 PHOTO OLD: Last modified in {mod_year}")
                                except Exception as e:
                                     logger.debug(f"Mod date parse error: {e}")
                            else:
                                try:
                                    p_date = datetime.datetime.strptime(photo_date_str, "%Y-%m-%d")
                                    if (datetime.datetime.now() - p_date).days > 365 * 3:
                                        is_photo_old = True
                                        warnings.append(f"📸 PHOTO REFRESH: Last synced on {photo_date_str}")
                                except: pass
                        else:
                            pass
                        
                        if os.path.exists(tmp_path): os.remove(tmp_path)
                    except Exception as pe:
                        logger.debug(f"Photo comparison failed: {pe}")
                else:
                    # No current image, anything is an upgrade
                    is_photo_upgrade = True
                    photo_info += " (New Contact Photo)"
            
            # Conflict: Manual edit since last sync
            mod_date_str = existing.get("modification_date", "")
            if mod_date_str and old_block:
                try:
                    if prev_stats["date"] not in mod_date_str:
                        warnings.append(f"ℹ️ MANUAL EDIT DETECTED: Modified on {mod_date_str}")
                except: pass

            # 4. Filter Redundancy (Native Birthday Guard v2.8)
            added = []
            updated = []
            
            # Check Title Enrichment
            new_title = p.current_role or ""
            if new_title and new_title.strip() != old_title.strip():
                updated.append("Job Title")
            
            # Check Photo
            if is_photo_upgrade or is_photo_old:
                updated.append("Photo")
            
            # Robust Birthday Check
            if p.birthday:
                staged_d, staged_m = self._parse_bd(p.birthday)
                native_d, native_m = self._parse_bd(old_bday_native)
                
                if staged_d and staged_m and staged_d == native_d and staged_m == native_m:
                    logger.debug(f"Birthday {p.birthday} matches native {old_bday_native}. Suppressing 'Added' tag.")
                else:
                    added.append("Birthday")
            
            # 5. Build Final Proposed Block (Pass History!)
            photo_up_date = None
            if "Photo" in updated:
                photo_up_date = datetime.datetime.now().strftime("%Y-%m-%d")

            proposed_block = p.generate_sync_block(
                added_fields=added, 
                updated_fields=updated, 
                prev_stats=prev_stats,
                existing_sync_block_text=old_note,
                photo_update_date=photo_up_date
            )
            
            # 6. Delta Summary
            delta_lines = []
            
            # v3.1 MANUAL REJECTION DETECTION
            is_exemptible = False
            if "Manual rejection performed" in old_note:
                is_exemptible = True
                proposed_block = "" # Suppress sync block
                warnings.append("⚠️ MANUAL REJECTION DETECTED (Will Auto-Exempt)")

            if updated: 
 
                if "Job Title" in updated:
                    delta_lines.append(f"• Job: {old_title or '[Empty]'} -> {new_title}")
            
            # Header info
            res_str = photo_info

            status_line = "Good Fidelity" if not warnings else " / ".join(warnings)
            
            info_text = (
                f"NAME: {p.full_name}\n"
                f"STATUS: {status_line}\n"
                f"PHOTO: {res_str}\n\n"
                f"=== 🔴 DELTA SUMMARY ===\n" + "\n".join(delta_lines) + ("\n[No field changes]" if not delta_lines else "") +
                f"\n\n=== 🟢 PROPOSED SYNC BLOCK ===\n{proposed_block}\n\n"
                f"=== ⚪️ CURRENT SYNC BLOCK ===\n{old_block or '[None Found]'}"
            )
            
            return {
                "text": info_text,
                "is_regression": is_regression,
                "is_exemptible": is_exemptible,
                "proposed": proposed_block,
                "updated_fields": updated
            }
        except Exception as e:
            logger.exception(f"Error in surgical comparison: {e}")
            return {"text": f"[Critical Error in Comparison: {e}]", "is_regression": False}

    def _parse_bd(self, bd_str: Optional[str]) -> (Optional[int], Optional[int]):
        """Robustly parses Day and Month regardless of language/format. v2.9.3"""
        if not bd_str or bd_str == "": return None, None
        low = bd_str.lower()
        
        # Robust Month Map
        months = {
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
        
        day = None
        month = None

        # 1. Try name-based months first
        for m_num, aliases in months.items():
            for a in aliases:
                # Use word boundaries for safety
                if re.search(r'\b' + re.escape(a) + r'\b', low):
                    month = m_num
                    break
            if month: break

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

    def _extract_sync_block(self, note: str) -> str:
        """Extracts the existing sync block for comparison."""
        match = re.search(r"(<Linkedin-AI-sync.*?</Linkedin-AI-sync>)", note, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _handle_resync(self, contact: Dict, silent: bool = False):
        """Flags a contact to be re-processed by the background agent.
        v4.7 F2-FIX: Writes latest feedback context as JSON into .resync file."""
        try:
            flag_file = contact["path"] / ".resync"
            
            # v4.7 F2-FIX: Look up most recent feedback for this contact
            # and write it as context for the sync engine to exploit.
            resync_context = {"contact_id": contact.get("id", ""), "contact_name": contact.get("name", "")}
            try:
                if FEEDBACK_LOG.exists():
                    latest_entry = None
                    with open(FEEDBACK_LOG, 'r') as f:
                        for line in f:
                            try:
                                entry = json.loads(line)
                                if entry.get("contact_id") == contact.get("id"):
                                    latest_entry = entry
                            except json.JSONDecodeError:
                                continue
                    if latest_entry:
                        resync_context["feedback_reason"] = latest_entry.get("reason", "")
                        resync_context["feedback_timestamp"] = latest_entry.get("timestamp", "")
                        logger.info(f"Resync context enriched: {latest_entry.get('reason', 'N/A')}")
            except Exception as e:
                logger.debug(f"Failed to read feedback context: {e}")
            
            with open(flag_file, 'w') as f:
                json.dump(resync_context, f, indent=2)
            
            # Crucially: we do NOT touch .applied, so the smart filter 
            # will see it as a candidate for retry in the next session.
            logger.info(f"Flagged {contact['name']} for Re-Sync (with context).")
            
            # v3.5.0: Proactive Backend Launch
            self._restart_backend()
            
            if not silent:
                 self._show_dialog("Re-Sync", f"{contact['name']} will be re-targeted by the background agent.", ["OK"])
        except Exception as e:
            logger.error(f"Failed to flag for resync: {e}")

    def _handle_backend_launch(self):
        """Allows launching the backend on specific groups or selections."""
        source = self._choose_from_list(
            "Launch Backend system on:", 
            ["Current selection in Contacts", "A specific Group...", "CANCEL"], 
            title="Launch Backend"
        )
        
        if source in ["CANCEL", "None"]:
            return

        target_group = ""
        if source == "Current selection in Contacts":
            selection_res = self.bridge.get_selection()
            if not selection_res.get("success") or not selection_res.get("matches"):
                self._show_dialog("No Selection", "Please select one or more contacts in the Contacts app first.", ["OK"])
                return
            
            matches = selection_res["matches"]
            target_group = "script-LSAM-AdHoc-Selection"
            
            # Clear existing ad-hoc group
            logger.info(f"Clearing ad-hoc group '{target_group}'...")
            clear_script = f'tell application "Contacts" to if exists group "{target_group}" then delete group "{target_group}"'
            self.bridge._run_applescript(clear_script)
            
            # Add selected contacts to group
            for m in matches:
                self.bridge.add_to_group(m["id"], target_group)
            
            logger.info(f"Added {len(matches)} contacts to {target_group}.")
            
        elif source == "A specific Group...":
            groups_res = self.bridge.list_groups()
            if not groups_res.get("success"):
                self._show_dialog("Error", "Failed to fetch groups.", ["OK"])
                return
            
            groups = groups_res["groups"]
            target_group = self._choose_from_list("Select group to sync:", groups, title="Select Group")
            if target_group in ["CANCEL", "None"]:
                return

        # Double check supervisor
        check_cmd = ["pgrep", "-f", "python3 supervisor.py"]
        res = subprocess.run(check_cmd, capture_output=True, text=True)
        if res.stdout.strip():
            self._show_dialog("Backend Active", "A supervisor process is already running. Please stop it first.", ["OK"])
            return

        # Launch detached
        logger.info(f"🚀 Launching Backend on group: {target_group}")
        cmd = [sys.executable, "supervisor.py", "--live", "--group", target_group]
        
        try:
            # v3.5.0: Log output to specific files
            stdout_path = PROJECT_ROOT / "logs" / "supervisor_stdout.log"
            stderr_path = PROJECT_ROOT / "logs" / "supervisor_stderr.log"
            
            subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=open(stdout_path, "a"),
                stderr=open(stderr_path, "a"),
                start_new_session=True
            )
            # Give it a second to create the status file
            time.sleep(1.5)
            new_status = self._get_backend_status()
            self._show_dialog("Success", f"Backend launched on '{target_group}'.\nStatus: {new_status}\n\nCheck SYNC_PROGRESS.md for progress.", ["OK"])
        except Exception as e:
            logger.error(f"Failed to launch backend: {e}")
            self._show_dialog("Error", f"Failed to launch backend: {e}", ["OK"])

    def _restart_backend(self):
        """Launches the supervisor if it's currently inactive."""
        try:
            status_line = self._get_backend_status()
            if "Inactive" in status_line or "Stopped" in status_line:
                logger.info("🚀 Backend is inactive. Restarting Supervisor (Slow Horse)...")
                # v3.5.0: Direct launch of supervisor. 
                # We use --live because SIMULATION is for dry runs.
                cmd = [sys.executable, "supervisor.py", "--live"]
                
                # Check for existing supervisor to avoid duplicates
                check_cmd = ["pgrep", "-f", "python3 supervisor.py"]
                res = subprocess.run(check_cmd, capture_output=True, text=True)
                if res.stdout.strip():
                    logger.info("Supervisor already has a process running. Skipping launch.")
                    return

                # Launch detached
                subprocess.Popen(
                    cmd,
                    cwd=PROJECT_ROOT,
                    stdout=open(PROJECT_ROOT / "logs" / "supervisor_stdout.log", "a"),
                    stderr=open(PROJECT_ROOT / "logs" / "supervisor_stderr.log", "a"),
                    start_new_session=True
                )
                logger.info("Supervisor launched successfully.")
            else:
                logger.info(f"Backend status is '{status_line}'. No restart needed.")
        except Exception as e:
            logger.error(f"Failed to restart backend: {e}")

    def _handle_flagging(self, contact: Dict, default_reason: str = None):
        """Presents the issue list and logs the feedback."""
        # v3.6.0: Reporting Type Choice
        if default_reason:
            reason = default_reason
            category = "Review"
        else:
            cat_choice = self._choose_from_list(
                "Select Reporting Type:",
                ["1. Review (General Issue)", "2. Challenge (Check History)", "CANCEL"],
                title="Flagging Category"
            )
            
            if cat_choice == "CANCEL" or cat_choice == "None":
                return
            
            category = "Challenge" if "Challenge" in cat_choice else "Review"

            # If Challenge, look back 3 days
            if category == "Challenge":
                cid = contact["id"]
                history = []
                try:
                    if FEEDBACK_LOG.exists():
                        with open(FEEDBACK_LOG, 'r') as f:
                            for line in f:
                                entry = json.loads(line)
                                if entry.get("contact_id") == cid:
                                    # Parse timestamp
                                    ts = datetime.datetime.fromisoformat(entry["timestamp"])
                                    delta = datetime.datetime.now() - ts
                                    if delta.days <= 3:
                                        history.append(entry)
                except Exception as e:
                    logger.debug(f"History lookup failed: {e}")

                if history:
                    h_text = "Previous Feedback (Last 3 Days):\n"
                    for h in history:
                        h_date = h["timestamp"][:16]
                        h_reason = h["reason"]
                        # v4.7 F1-FIX: Default category for legacy entries without brackets
                        if not h_reason.startswith("["):
                            h_reason = f"[Review] {h_reason}"
                        h_text += f"• {h_date}: {h_reason}\n"
                    
                    self._show_dialog(f"Challenge: {contact['name']}", h_text, ["Proceed with New Flag", "Cancel Challenge"])
                    # If Canceled, we just return
                    # (Simplified: we dont track the button but the flow continues if they dont cancel)
                else:
                    self._show_dialog("Challenge", "No feedback found for this contact in the last 3 days.", ["OK"])

            issues = [
                "Wrong Contact / Search Failure",
                "Wrong/Suspicious LinkedIn Profile",
                "Not a Person / Invalid Entity",
                "Photo Issue / Mismatch",
                "Sync Block: Error in # of mutual connexions",
                "Sync Block: Error in # of followers",
                "Sync Block: Error in # of contacts",
                "Sync Block: No visible change",
                "Sync Block: Information Loss",
                "Sync Block: Redundancy",
                "Data Mismatch / Parsing Error",
                "Duplicate Email Address",
                "Duplicate / Merge Error",
                "Other Logic Error"
            ]
            
            issue_choice = self._choose_from_list("Signal a problem with this contact:", issues, title="Flag Issue")
            if issue_choice == "CANCEL" or issue_choice == "None":
                return
            
            reason = f"[{category}] {issue_choice}"
        
        if reason:
            # v3.5.0: Automatic Resync for Sync Block errors
            if "Sync Block: Error in #" in reason:
                logger.info(f"Corruption flag '{reason}' detected. Triggering auto-resync.")
                self._handle_resync(contact)
            
            # Add text detail (v3.1)
            detail_script = '''
            try
                set res to (display dialog "Add specific details for this issue (optional):" with title "Flag Details" default answer "" buttons {"OK", "Skip"} default button "OK")
                if button returned of res is "Skip" then
                    return ""
                else
                    return text returned of res
                end if
            on error
                return ""
            end try
            '''
            try:
                detail = self._run_script(detail_script).strip()
                if detail:
                    reason = f"{reason} | Detail: {detail}"
            except Exception as e:
                logger.debug(f"Failed to get flag details: {e}")

            if any(k in reason for k in ["Wrong/Suspicious LinkedIn Profile", "False Match / Not the Target"]):
                # v3.0: High-Priority Manual Rejection
                l_url = contact.get("profile", {}).get("linkedin_url")
                cid = contact["id"]
                logger.info(f"Triggering LinkedIn purge for {contact['name']} due to rejection flag.")
                self.bridge.remove_linkedin_presence(cid, l_url)

            self._log_feedback(contact, reason)
            self._show_dialog("Flagged", f"Contact flagged as: {reason}", ["Next"])

    def _log_feedback(self, contact: Dict, reason: str):
        """Writes to feedback log and creates maker file."""
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "contact_id": contact["id"],
            "contact_name": contact["name"],
            "path": str(contact["path"]),
            "reason": reason
        }
        
        # 1. Append to JSONL
        try:
            with open(FEEDBACK_LOG, 'a') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write feedback log: {e}")
            
        # 2. v3.6.0: Log to session log for maintenance exploitation
        try:
            session_log = contact["path"].parent.parent / "session.log"
            if session_log.exists():
                with open(session_log, 'a') as f:
                    f.write(f"\n[USER_FEEDBACK] [{datetime.datetime.now().strftime('%H:%M:%S')}] {contact['name']}: {reason}\n")
        except Exception as e:
            logger.error(f"Failed to write to session log: {e}")

        # 3. Touch .flagged file
        try:
            flag_file = contact["path"] / ".flagged"
            with open(flag_file, 'w') as f:
                f.write(reason)
        except Exception as e:
            logger.error(f"Failed to create .flagged file: {e}")

    def _apply_contact(self, contact: Dict) -> bool:
        """Applies the contact update using the Bridge. (v2.7: Enforced Model)"""
        try:
            cid = contact["id"]
            profile_dict = contact["profile"]
            folder = contact["path"]
            
            # v2.5 Safety: Instantiate Pydantic Model
            profile_obj = self.LinkedInProfile.model_validate(profile_dict)
            
            # Check for best available photo
            photo_path = None
            if (folder / "linkedin.heic").exists():
                photo_path = str(folder / "linkedin.heic")
            elif (folder / "linkedin-raw.jpg").exists():
                photo_path = str(folder / "linkedin-raw.jpg")
            
            # Also provide the original photo for resolution guarding
            orig_photo_path = None
            orig_candidate = folder / f"{contact['path'].name}-original.jpg"
            if not orig_candidate.exists():
                # Try generic name
                orig_candidate = folder.parent.parent / "backups" / folder.name / (folder.name + "-original.jpg")

            if orig_candidate.exists():
                orig_photo_path = str(orig_candidate)
            else:
                # If specific original not found, try any .jpg in folder that isn't raw
                jpgs = list(folder.glob("*-original.jpg"))
                if jpgs: orig_photo_path = str(jpgs[0])
                
            # Call Bridge
            res = self.bridge.update_contact(
                contact_id=cid,
                profile=profile_obj,
                photo_path=photo_path,
                orig_photo_path=orig_photo_path
            )
            
            if res.get("success"):
                logger.info(f"Applied {cid} ({contact['name']})")
                (folder / ".applied").touch()
                
                # Cleanup group (Tier 3) if success
                self.bridge.remove_from_group(cid, "script-LSAM-Tier3-NeedAttention")
                return True
            else:
                logger.error(f"Bridge failed for {cid}: {res}")
                return False
                
        except Exception as e:
            logger.error(f"Exception applying {contact.get('name')}: {e}")
            return False

    
    def _restore_from_backup(self, contact: Dict) -> bool:
        """
        Attempts to restore original contact data from `original.vcf` or `original.txt`.
        Returns True if restoration was attempted (success or partial), False if no backup found.
        """
        cid = contact["id"]
        folder = contact["path"]
        name = contact["name"]
        
        # 1. Locate Backup Files
        # They should be in the session folder (contact["path"])
        # or in the parent `backups` if structure is different
        orig_vcf = folder / "original.vcf"
        orig_txt = folder / "original.txt"
        
        if not orig_vcf.exists() and not orig_txt.exists():
            # Try finding them in sibling folders? (No, backup should be local)
            logger.warning(f"No backup files found for {name} ({cid}). Skipping restoration.")
            return False
            
        logger.info(f"Restoring {name} from backups...")
        
        # 2. Parse Backup
        restore_payload = {}
        
        # VCF Parsing (for Title, Org)
        if orig_vcf.exists():
            try:
                with open(orig_vcf, 'r', encoding='utf-8') as f:
                    vcf_content = f.read()
                
                # Simple regex parsing
                import re
                title_match = re.search(r"^TITLE:(.*)$", vcf_content, re.MULTILINE)
                org_match = re.search(r"^ORG:(.*)$", vcf_content, re.MULTILINE)
                
                if title_match: restore_payload["current_role"] = title_match.group(1).strip()
                if org_match: 
                    # ORG often has semicolons "Company;Department"
                    restore_payload["company"] = org_match.group(1).split(';')[0].strip()
                    
                logger.info(f"Parsed VCF: Title='{restore_payload.get('current_role')}', Org='{restore_payload.get('company')}'")
            except Exception as e:
                logger.error(f"Failed to parse original.vcf: {e}")

        # TXT Parsing (for Note)
        if orig_txt.exists():
            try:
                with open(orig_txt, 'r', encoding='utf-8') as f:
                    original_note = f.read()
                
                # If note exists, we restore it. 
                # But we might need to remove "Manual rejection performed" if it was somehow saved there?
                # Probably not. stored `original.txt` is usually the snapshot BEFORE we touched it.
                restore_payload["note"] = original_note
                logger.info("Loaded original note backup.")
            except Exception as e:
                logger.error(f"Failed to read original.txt: {e}")
                
        if not restore_payload:
            return False
            
        # 3. Apply Restoration via Bridge
        # We misuse `update_contact` but pass the restored fields as if they were the "profile"
        # Since update_contact expects a profile object, we should construct a minimal one.
        
        try:
            # Construct a minimal profile with just the fields to restore
            # We must pass other fields as None/Empty to avoid overwriting with blanks
            
            dummy_data = {
                "full_name": name,
                "linkedin_url": "", # Irrelevant for restoration
                "current_role": restore_payload.get("current_role"),
                "company": restore_payload.get("company"),
                "note": restore_payload.get("note")
            }
            
            # Problem: bridge.update_contact expects a Pydantic model now (v2.5 safety).
            restoration_profile = self.LinkedInProfile.model_validate(dummy_data)
            
            # WORKAROUND: We can use `_run_script` to forcefully set the note if `original_note` is present.
            
            if "note" in restore_payload:
                # Force Note Restore via AppleScript
                safe_note = restore_payload["note"].replace('\\', '\\\\').replace('"', '\\"')
                script = f'''
                tell application "Contacts"
                    set p to person id "{cid}"
                    set note of p to "{safe_note}"
                    save
                end tell
                '''
                self._run_script(script)
                logger.info("Restored Note via direct AppleScript.")
                
                # Remove note from payload so we don't confuse update_contact
                del restore_payload["note"]
            
            if restore_payload.get("current_role") or restore_payload.get("company"):
                # Apply Title/Org restore via Bridge
                # We need to set `current_role` and `company` to the OLD values.
                res = self.bridge.update_contact(
                    contact_id=cid,
                    profile=restoration_profile
                )
                if res.get("success"):
                    logger.info("Restored Title/Company via Bridge.")
                else:
                    logger.error(f"Bridge failed to restore Title/Org: {res}")

            return True

        except Exception as e:
            logger.error(f"Restoration logic failed: {e}")
            return False

    def _cleanup_contact_sessions(self, contact: Dict):
        """
        Enforce Session Cleanup Policy:
        - Keep Oldest (Original)
        - Keep 3 Most Recent
        - Delete Intermediaries
        """
        try:
            cid = contact["id"]
            name = contact["name"]
            
            # 1. Find all session folders for this contact
            # They are scattered in `logs/sessions/run_*/backups/Folder_Name`
            # or `backups/Folder_Name` if flat? No, structure is `run_.../backups/Name`
            
            # Search pattern: logs/sessions/run_*/backups/*{cid}* 
            # or just match by Name if folder name is consistent.
            # Names can change. CID is only inside the JSON.
            # We must scan.
            # Optim: usage `self._fetch_all_for_contact` helper?
            # We can re-use the logic from `scan_backlog` but targeted.
            
            # Simple approach: identifying sessions by folder name match
            # "Mrs_Catherine_Heald" -> find all folders with this name.
            folder_name = contact["path"].name
            
            # find all `run_...` directories
            session_roots = [LOG_DIR / "sessions", LOG_DIR / "fast_sessions"]
            all_instances = []
            
            for root in session_roots:
                # We look for folders ending with the same name
                candidates = list(root.glob(f"*/backups/{folder_name}"))
                all_instances.extend(candidates)
                
            if len(all_instances) <= 4:
                return # Nothing to clean (1 oldest + 3 recent = 4 max to keep)

            # 2. Sort by timestamp (derived from parent `run_YYYY-MM-DD_HH-MM-SS`)
            def get_ts(path_obj):
                try:
                    run_folder = path_obj.parent.parent.name # run_2026-02-11_...
                    ts_str = run_folder.replace("run_", "")
                    return datetime.datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
                except:
                    return datetime.datetime.min
            
            all_instances.sort(key=get_ts)
            
            # 3. Apply Retention Policy
            oldest = all_instances[0]
            recents = all_instances[-3:] # The last 3 (biggest timestamps)
            
            to_keep = {oldest} | set(recents)
            
            # 4. Delete the rest
            deleted_count = 0
            for folder in all_instances:
                if folder not in to_keep:
                    try:
                        import shutil
                        shutil.rmtree(folder)
                        deleted_count += 1
                        logger.info(f"Cleanup: Deleted intermediate session {folder}")
                    except Exception as e:
                        logger.error(f"Failed to delete {folder}: {e}")
                        
            logger.info(f"Session Cleanup for {name}: Kept {len(to_keep)}, Deleted {deleted_count}.")
            
        except Exception as e:
            logger.error(f"Error in session cleanup: {e}")

    def _exempt_contact(self, contact: Dict) -> bool:
        """Moves a contact to Exempted group and marks session as complete."""
        try:
            cid = contact["id"]
            folder = contact["path"]
            
            logger.info(f"Exempting {contact['name']} ({cid})...")
            
            # 0. Restore Data (New v3.2)
            # Only if "Manual rejection" detected? Or always?
            # User requirement: "contacts manually rejected... are not being properly restored"
            # So specifically for rejection cases.
            # How do we know from here? Check existing note?
            # We can check existing note again.
            existing = self.bridge.get_contact_details(cid)
            if "Manual rejection performed" in existing.get("note", ""):
                logger.info("Manual rejection detected during exemption. Attempting restoration...")
                self._restore_from_backup(contact)

            # 1. Add to Exempted
            self.bridge.add_to_group(cid, "script-LSAM-Exempted")
            
            # 2. Cleanup other groups
            self.bridge.remove_from_group(cid, "script-LSAM-Tier3-NeedAttention")
            self.bridge.remove_from_group(cid, "script-LSAM-LinkedIn to Review")
            
            # 3. Mark processed
            (folder / ".applied").touch()
            
            # 4. Session Cleanup (New v3.2)
            self._cleanup_contact_sessions(contact)
            
            logger.info(f"Exempted {contact['name']} successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to exempt {contact['name']}: {e}")
            return False


if __name__ == "__main__":
    import sys
    manager = StagedContactManager()
    manager.run_interactive()
