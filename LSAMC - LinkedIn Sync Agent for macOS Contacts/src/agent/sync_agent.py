import logging
import os
import sys
# v2.5.4: Disable all 3rd party telemetry and convenience extensions for maximum stealth
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["BROWSER_USE_DISABLE_EXTENSIONS"] = "true"

import sys
import asyncio
import argparse
import json

# Add project root to path for imports to work
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
import unicodedata
import re
import glob
import time
import base64
import tempfile
import traceback
import subprocess
from typing import Optional, List, Dict, Any
import random
import inspect
from datetime import datetime
from dotenv import load_dotenv

# Import browser-use and monkeypatch it BEFORE creating any Browser instances
from browser_use import Agent, BrowserSession as Browser, ChatGoogle
from browser_use.browser.profile import BrowserProfile

# LSAMC Fix: browser-use 0.11+ copies profiles to temp dirs by default, 
# which discards LinkedIn login cookies. We monkeypatch it to use the profile in-place.
def _no_copy_profile(self):
    """LSAMC Fix: Do not copy profile to temp directory. Use it in-place for persistence."""
    if self.user_data_dir:
        from pathlib import Path
        import os
        self.user_data_dir = str(Path(self.user_data_dir).expanduser().resolve())
        os.makedirs(self.user_data_dir, exist_ok=True)
        # Ensure a Default folder exists inside it if not present
        os.makedirs(os.path.join(self.user_data_dir, "Default"), exist_ok=True)
    return

BrowserProfile._copy_profile = _no_copy_profile

from src.models.profile import LinkedInProfile, Experience
from src.bridge.image_optim import optimize_image
from src.bridge.contact_macos import ContactMacOSBridge
from src.utils.process_guardian import ProcessGuardian
from src.utils.network_sniffer import NetworkSniffer
from src.utils.stealth_manager import StealthManager
try:
    from src.utils.surgical_overrides import BATCH_9_OVERRIDES
except ImportError:
    BATCH_9_OVERRIDES = {}

from src.utils.local_ocr import AppleVisionOCR
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use.llm.messages import UserMessage
from src.utils.company_knowledge_base import CompanyKnowledgeBase

__version__ = "0.7.1-robust"

# v4.8.3: Batch Recycle — exit cleanly after N successful syncs to prevent Chrome degradation
BATCH_RECYCLE_LIMIT = 12  # v4.9.1 D1: 7→12 (AUDIT_2026-03-11) — fewer restarts; monitor Chrome RAM at contact 12
BATCH_RECYCLE_EXIT_CODE = 42  # Special exit code: "batch complete, restart same group"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# (ProxyLLM removed, unified into ChatGoogle)

class LinkedInSyncAgent:
    """
    Agent that extracts data from LinkedIn and syncs it to macOS Contacts.
    Uses browser-use for navigation and Gemini for visual extraction.
    """
    
    EXCLUSIONS = [
        "Pascal Ancian", "Benny Marom", "Danielle LIGOUT", "M. Jean-Claude MALLET", "Jean-Claude MALLET",
        # v4.8.2: Self-contacts — Philippe DEWOST is the logged-in user, skip all personae
        "Philippe DEWOST", "Philippe Dewost", "Mr Philippe DEWOST", "Mrs Philippe DEWOST",
        "M Philippe DEWOST", "M. Philippe DEWOST",
    ]
    REVIEW_GROUP = "script-LSAM-LinkedIn to Review"
    EXEMPT_GROUP = "script-LSAM-Exempted"
    
    def __init__(self, mode: str = "SIMULATION", api_key: Optional[str] = None, headless: bool = False, vault_only: bool = False, ab_test: bool = False):
        # BROADENED ENV LOADING (v0.2.6): Ensure key is found even in faceless mode
        load_dotenv()
        
        # v1.4.2: Hybrid Extraction Configuration
        self.ab_test_mode = ab_test
        self.comparison_results = []
        self._owner_photo_url = None
        self._owner_photo_signature = "C4E03AQEvtF7Fr5H4ew" # Known fallback
        
        # 0. Session & Audit Setup (v0.2.1) - Move to top for complete logging
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.log_dir = os.path.join(project_root, "logs") 
        self._contacts_since_gc = 0
        self._contacts_since_recycle = 0 # v1.3.3: Browser recycling counter
        self.session_dir = os.path.join(self.log_dir, "sessions", f"run_{self.timestamp}")
        self.backup_dir = os.path.join(self.session_dir, "backups")
        self.vault_root = os.path.join(project_root, "data/vault")
        self.quota_exhausted = False
        
        # Configure logging to file immediately and flush often
        self._init_session_folders()
        self._setup_robust_logging()
        
        # Initialize Safety Guardian
        self.guardian = ProcessGuardian()
        # self.guardian.register(os.getpid()) # DONT REGISTER SELF - will kill agent on cleanup!
        
        self.bridge = ContactMacOSBridge(mode=mode)
        self.mode = mode
        api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        
        # Initialize manual LLM client for robust manual calls
        self.genai_client = None
        if api_key:
            logger.info("Initializing manual LLM client (Gemini Flash Robust)...")
            self.genai_client = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=api_key)
        else:
            logger.warning("❌ GOOGLE_API_KEY not found! LLM features (extraction) will be disabled.")
            
        self.genai_model_name = "gemini-flash-latest"
        # Use Gemini for browser-use internal extraction
        # Setting headless to True for background operation
        self.llm = ChatGoogle(model="gemini-flash-latest", api_key=api_key) if api_key else None
        
        self._lock_file = os.path.join(project_root, "logs/lsamc.lock")
        self._acquire_lock()
        self._last_auth_check = 0
        self._browser_headless = headless
        self.vault_only = vault_only
        self._authenticated = False
        self._browser_started = False
        self.browser = None

        if self.vault_only:
            logger.info("🛠️ VAULT-ONLY MODE: Skipping browser initialization and LinkedIn auth.")
        
        self.group = None # To track active group for 'Move' logic
        
        # v1.3.2: Memory Management
        self._contacts_since_gc = 0  # Counter for garbage collection
        self._contacts_since_context_recycle = 0  # Counter for context refresh
        
        # v3.6.1: Load Exemptions from macOS Group
        try:
            exempt_res = self.bridge.list_group_contacts(self.EXEMPT_GROUP)
            if exempt_res["success"]:
                exempt_names = [c["name"] for c in exempt_res["matches"] if c.get("name")]
                self.EXCLUSIONS.extend(exempt_names)
                logger.info(f"🛡️ Loaded {len(exempt_names)} exempted contacts from {self.EXEMPT_GROUP}.")
        except Exception as e:
             logger.warning(f"Could not load exemptions from {self.EXEMPT_GROUP}: {e}")

        self.session_start_time = datetime.now()
        self._contacts_processed_in_session = 0
        
        # Initialize Stealth Manager (v1.2.0)
        self.stealth = StealthManager(
            log_path=os.path.join(project_root, "data/linkedin_access_log.json"),
            daily_quota=int(os.environ.get("LINKEDIN_DAILY_QUOTA", 2000)),
            cooldown_days=int(os.environ.get("LINKEDIN_COOLDOWN_DAYS", 0))
        )
        
        # v1.5.0: Robustness & Circuit Breaker state
        self.consecutive_failures = 0
        self.failure_threshold = 5
        self.consecutive_extraction_failures = 0
        self.extraction_failure_threshold = 3
        self.health_check_interval = 300 # seconds
        self.last_health_check = 0
        
        # Phase 2: Company Knowledge Base (v5.0.0)
        self.kb = CompanyKnowledgeBase()
        

    async def _cleanup_tabs(self) -> int:
        """Closes ghost background tabs to prevent target storms (v1.5.4)."""
        if self.vault_only or not self.browser: return 0
        try:
            # v1.5.8 FIX: Reliable context access via private attribute
            context = getattr(self.browser, '_browser_context', None)
            if not context:
                # Fallback: try public attribute
                context = getattr(self.browser, 'context', None)
                
            if not context:
                 logger.warning("🧹 Cleanup: Could not access browser context.")
                 return 0
                 
            pages = context.pages
            if len(pages) <= 1: return 0
            
            logger.info(f"🧹 Tab Cleanup: {len(pages)} pages detected. Reducing to 1.")
            
            # Identify current page to keep it
            current_page = await self.browser.get_current_page()
            
            closed_count = 0
            for page in pages:
                # Don't close the active page
                if page == current_page: continue
                
                try:
                    await page.close()
                    closed_count += 1
                except: pass
                
            return closed_count
        except Exception as e:
            logger.error(f"Failed to cleanup tabs: {e}")
            return 0

    async def _check_browser_health(self) -> bool:
        """
        v1.5.4: Performs pre-flight health check of browser session.
        Returns True if healthy, False if restart is needed.
        """
        if self.vault_only or not self.browser: return True
        
        now = time.time()
        # Rate limit health checks
        if now - self.last_health_check < 30: return True
        self.last_health_check = now
        
        try:
            # 1. Check Responsiveness
            page = await self.browser.get_current_page()
            if not page:
                logger.warning("🩺 Health Check: No current page found.")
                return False
                
            try:
                # Simple ping
                await asyncio.wait_for(page.evaluate("() => 1"), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("🩺 Health Check: Browser unresponsive (Timeout).")
                return False
                
            # 2. Check Target Explosion (CDP Storm Protection)
            s_mgr = None
            if hasattr(self.browser, 'session_manager'):
                s_mgr = self.browser.session_manager
                
            if s_mgr and hasattr(s_mgr, '_sessions'):
                target_count = len(s_mgr._sessions)
                if target_count > 200:
                    logger.info(f"🩺 Health Check: Targets high ({target_count}). Triggering tab cleanup...")
                    await self._cleanup_tabs()
                    
                    # Re-check count
                    target_count = len(s_mgr._sessions)
                if target_count > 500:
                    logger.error(f"🩺 Health Check: CRITICAL target count ({target_count}). Forcing restart.")
                    sys.exit(1)
                
                # v1.6.3: Log current count for visibility
                if target_count > 100:
                    logger.info(f"🩺 Health Check: Target count at {target_count}")
        
            return True
        except Exception as e:
            logger.error(f"🩺 Health Check: Exception during check: {e}")
            sys.exit(1)

    def _setup_robust_logging(self):
        """Ensures logs are written and flushed to the session file."""
        log_file = os.path.join(self.session_dir, "session.log")
        handler = logging.FileHandler(log_file, delay=False)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        # Add to root logger or specific logger
        logging.getLogger().addHandler(handler)
        # Ensure we can see logs in real-time
        for h in logging.getLogger().handlers:
            if hasattr(h, 'flush'): h.flush()

    def _get_memory_usage_mb(self) -> float:
        """Returns current Python process memory usage in MB."""
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    
    def _force_gc(self):
        """Aggressively free unused Python objects."""
        import gc
        gc.collect()
        gc.collect()  # Run twice for circular references
        logger.debug(f"🧹 Garbage collection complete. Memory: {self._get_memory_usage_mb():.0f} MB")

    async def _hybrid_extract_fallback(self, contact_name: str, snapshots: Dict[str, str]) -> Optional[LinkedInProfile]:
        """Uses local OCR + thin LLM to extract data from screenshots."""
        if not snapshots: return None
        
        logger.info(f"🧬 [HYBRID] Starting Visual OCR Fallback for {contact_name}...")
        results = {}
        
        # 1. Run local OCR on snapshots
        ocr_texts = []
        for key, path in snapshots.items():
            text = AppleVisionOCR.extract_text_from_image(path)
            if text:
                ocr_texts.append(f"--- {key.upper()} SNIPPET ---\n{text}")
        
        if not ocr_texts: return None
        
        full_ocr_text = "\n\n".join(ocr_texts)
        logger.debug(f"🧬 [HYBRID] OCR Text combined (len {len(full_ocr_text)})")
        
        # 2. Use Gemini for "Thin Extraction" (parsing the OCR text)
        if not self.genai_client: return None
        
        prompt = (
            f"Parse this LinkedIn OCR text into structured JSON.\n"
            f"Fields needed: full_name, current_role, company, location, followers_count, connections_count, phones, emails.\n\n"
            f"OCR TEXT:\n{full_ocr_text}\n\n"
            f"Return ONLY raw JSON matching this schema: {LinkedInProfile.model_json_schema()}"
        )
        
        try:
            start_t = time.time()
            response = await self.genai_client.ainvoke(prompt)
            duration = (time.time() - start_t)
            logger.info(f"🧬 [HYBRID] Thin LLM extraction complete ({duration:.1f}s)")
            
            raw_text = response.content
            # Clean possible markdown wrap
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(raw_text)
            profile = LinkedInProfile(**data)
            return profile
        except Exception as e:
            logger.error(f"🧬 [HYBRID] Fallback failed: {e}")
            return None

    def _record_comparison(self, contact_name: str, branch_a: Optional[LinkedInProfile], branch_b: Optional[LinkedInProfile], metrics: Dict[str, Any]):
        """Records A/B test results to an internal list and periodically to disk."""
        if not self.ab_test_mode: return
        
        comparison = {
            "contact": contact_name,
            "timestamp": datetime.now().isoformat(),
            "branch_a": branch_a.to_dict() if branch_a else None,
            "branch_b": branch_b.to_dict() if branch_b else None,
            "metrics": metrics
        }
        self.comparison_results.append(comparison)
        
        # Save to disk periodically (v1.4.2)
        report_path = os.path.join(self.session_dir, "ab_test_raw_data.json")
        try:
            with open(report_path, "w") as f:
                json.dump(self.comparison_results, f, indent=2)
            logger.info(f"🧪 [AB-TEST] Comparison data updated: {report_path}")
        except Exception as e:
            logger.error(f"Failed to save AB test data: {e}")
            
    async def _capture_element_screenshots(self, contact_name: str) -> Dict[str, str]:
        """Captures atomic screenshots of profile header and contact info modal."""
        results = {}
        safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
        contact_dir = os.path.join(self.backup_dir, safe_name)
        os.makedirs(contact_dir, exist_ok=True)
        
        try:
            page = await self.browser.get_current_page()
            if not page: return {}

            # 1. Header Snapshot
            header_selector = ".pv-text-details__left-panel, .pv-top-card-section__body" # v1.4.2 selectors
            header_path = os.path.join(contact_dir, f"{safe_name}-hybrid-header.png")
            try:
                header_element = await page.wait_for_selector(header_selector, timeout=5000)
                if header_element:
                    await header_element.screenshot(path=header_path)
                    results["header"] = header_path
                    logger.debug(f"📸 Profile header captured: {header_path}")
            except Exception as e:
                logger.debug(f"Failed to capture header snapshot: {e}")

            # 2. Contact Info Box Snapshot
            contact_link_selector = '.pv-top-card--list a[href*="contact-info"]'
            try:
                contact_link = await page.wait_for_selector(contact_link_selector, timeout=3000)
                if contact_link:
                    await contact_link.click()
                    await asyncio.sleep(1) # Grace period for modal animation
                    
                    modal_selector = ".pv-contact-info, .artdeco-modal__content"
                    modal_element = await page.wait_for_selector(modal_selector, timeout=5000)
                    if modal_element:
                        modal_path = os.path.join(contact_dir, f"{safe_name}-hybrid-contact.png")
                        await modal_element.screenshot(path=modal_path)
                        results["contact_box"] = modal_path
                        logger.debug(f"📸 Contact info captured: {modal_path}")
                        
                        # Close modal agentically
                        close_btn = await page.query_selector('button[aria-label="Dismiss"], .artdeco-modal__dismiss')
                        if close_btn: await close_btn.click()
            except Exception as e:
                logger.debug(f"Failed to capture contact info snapshot: {e}")
                
        except Exception as e:
            logger.error(f"Atomic snapshotting error: {e}")
            
        return results
    
    async def _cleanup_page(self, page):
        """Close page and release all associated resources."""
        try:
            if page:
                # v1.4.1: Be very careful closing crashed pages
                try: await page.close()
                except: pass
        except:
            pass

    async def _check_and_fix_crashed_page(self) -> bool:
        """Detects Chrome crash pages (Error Code 5) and attempts recovery."""
        if self.vault_only: return True
        
        try:
            page = await self.browser.get_current_page()
            if not page: return True
            
            # 1. Quick title/content check for internal Chrome error pages
            title = (await page.evaluate("() => document.title")).lower()
            content = (await page.evaluate("() => document.body?.innerText || ''")).lower()
            
            crash_indicators = [
                "aïe aïe aïe", "aw, snap!", "error code: 5", "code d'erreur : 5",
                "out of memory", "incapable d'afficher", "page crashed",
                "error code: 9", "code d'erreur : 9"
            ]
            
            if any(k in title for k in crash_indicators) or any(k in content for k in crash_indicators):
                logger.error("💥 BROWSER CRASH DETECTED (Code 5). Attempting recovery...")
                
                # Attempt 1: Standard reload
                await page.reload()
                await asyncio.sleep(5)
                
                # Verify if still crashed
                title = (await page.evaluate("() => document.title")).lower()
                if any(k in title for k in crash_indicators):
                    logger.warning("♻️ Reload failed to fix crash. Forcing browser recycle.")
                    await self.close()
                    await self._setup_browser(headless=self._browser_headless)
                    return False # Signaled to caller that state changed
                    
                logger.info("✅ Browser recovered via reload.")
                return True
        except Exception as e:
            logger.debug(f"Crash check failed: {e}")
            
        return True
    
    async def _check_memory_and_cleanup(self):
        """Monitor memory and trigger cleanup if needed."""
        mem_mb = self._get_memory_usage_mb()
        
        if mem_mb > 40000:  # 40 GB emergency threshold
            logger.error(f"🚨 EMERGENCY: Memory at {mem_mb:.0f} MB. Forcing aggressive cleanup.")
            self._force_gc()
            # Consider stopping the batch here if needed
            return "EMERGENCY"
        elif mem_mb > 30000:  # 30 GB warning threshold
            logger.warning(f"⚠️ Memory at {mem_mb:.0f} MB. Triggering context recycle.")
            self._force_gc()
            return "WARNING"
        elif mem_mb > 20000:  # 20 GB info threshold
            logger.info(f"ℹ️ Memory at {mem_mb:.0f} MB. Forcing GC.")
            self._force_gc()
            return "INFO"
        
        return "OK"
    
    async def _setup_browser(self, headless: bool = True):
        """v1.6.0: Initializes browser session with active connection verification (browser-use 0.11+)."""
        if self._browser_started and self.browser:
            return
            
        self._browser_headless = headless
        self._browser_started = True
        profile = os.environ.get("LINKEDIN_CHROME_PROFILE", "Default")
        logger.info(f"Setting up browser (headless={headless}, profile={profile})...")
        logger.info("🌐 BROWSER LAUNCH: Chrome window opening...")
        
        self.browser = Browser(
            headless=headless,
            disable_security=True,
            user_data_dir=os.path.join(os.getcwd(), 'data', 'agent_chrome_profile'),
            profile_directory='Default',
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            viewport={'width': 1280, 'height': 800},
            minimum_wait_page_load_time=3.0,
            wait_for_network_idle_page_load_time=3.0,
            enable_default_extensions=False,
            args=[
                "--window-size=1280,800",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-notifications"
            ]
        )
        
        # v1.6.1: Robust CDP Connection Loop
        logger.debug("Establishing browser connection...")
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # v0.11+ requires manual start for Browser instance if not using Agent
                if hasattr(self.browser, 'start'):
                    await self.browser.start()
                
                # v3.1.5: Stabilization delay to ensure CDP client is fully initialized
                await asyncio.sleep(2)
                
                # Verify page access
                page = None
                try:
                    page = await self.browser.get_current_page()
                except Exception as pe:
                    logger.warning(f"Failed to get current page: {pe}. Retrying new page...")
                
                if not page:
                    page = await self.browser.new_page()
                
                await page.evaluate("() => 1")
                logger.info("✅ Browser bridge verified and ready.")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"❌ Browser verification failed after {max_retries} attempts: {e}")
                    raise
                logger.warning(f"⚠️ Connection attempt {attempt+1} failed ({e}). Retrying in 5s...")
                await asyncio.sleep(5)
            # Don't raise, let the first navigation attempt handle it or trigger health check fail

    def _init_session_folders(self):
        """Creates the session and base backup folder."""
        for path in [self.session_dir, self.backup_dir]:
            os.makedirs(path, exist_ok=True)
            
    def _create_backup(self, contact_name: str, content: Any, stage: str, file_type: str = "txt"):
        """
        Saves a contact state to a dedicated subfolder for the contact.
        stage: 'original' or 'linkedin'
        file_type: 'txt', 'vcf', 'heic', etc.
        """
        safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
        contact_folder = os.path.join(self.backup_dir, safe_name)
        os.makedirs(contact_folder, exist_ok=True)
        
        filename = f"{safe_name}-{stage}.{file_type}"
        path = os.path.join(contact_folder, filename)
        
        try:
            # Determine mode based on content type
            is_binary = isinstance(content, bytes)
            mode = "wb" if is_binary else "w"
            encoding = None if is_binary else "utf-8"
            
            with open(path, mode, encoding=encoding) as f:
                f.write(content)
                
            logger.debug(f"Saved {stage} {file_type} backup to {path}")
            return path
        except Exception as e:
            logger.error(f"Failed to save {file_type} backup for {contact_name}: {str(e)}")
            return None

    def _acquire_lock(self):
        """Prevents multiple instances of the script from running."""
        if os.environ.get("LSAMC_IGNORE_LOCK") == "1":
            return
            
        os.makedirs(os.path.dirname(self._lock_file), exist_ok=True)
        try:
            self._lock_fd = os.open(self._lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._lock_fd, f"{os.getpid()}".encode())
        except FileExistsError:
            # Check if process is actually running
            try:
                with open(self._lock_file, "r") as f:
                    content = f.read().strip()
                    if not content: raise ValueError("Empty lock file")
                    pid = int(content)
                os.kill(pid, 0)
                logger.error(f"Another instance of LSAMC is already running (PID: {pid}). Exiting.")
                exit(1)
            except (OSError, ValueError):
                # Process not running or stale lock
                logger.warning("Removing stale lock file.")
                if os.path.exists(self._lock_file):
                    os.remove(self._lock_file)
                self._acquire_lock()

    def _release_lock(self):
        """Releases the process lock."""
        try:
            if hasattr(self, '_lock_fd'):
                os.close(self._lock_fd)
            if os.path.exists(self._lock_file):
                os.remove(self._lock_file)
        except:
            pass

    async def _kill_orphaned_chrome(self):
        """Cleanly terminates any leftover Chrome processes tracked or loosely hanging (v1.5.5)."""
        logger.info("Cleaning up orphaned Chrome processes...")
        try:
            import subprocess
            # Aggressive cleanup for zombie helpers that often leak during target storms
            # Patterns: Chrome Helper, chromium, headless_shell
            patterns = ["Chrome Helper", "Chromium", "headless_shell", "playwright"]
            for pattern in patterns:
                try:
                    # Use pkill -f to match full command lines, but avoid killing this python process
                    subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
                except:
                    pass
            logger.debug("Aggressive process purge complete.")
        except Exception as e:
            logger.warning(f"Process cleanup warning: {e}")
        
        if hasattr(self, 'guardian'):
            self.guardian.cleanup() # Already kills tracked pids

    async def close(self):
        """Cleanly closes the browser and releases lock."""
        try:
            if hasattr(self, 'browser'):
                logger.info("Closing browser session...")
                if hasattr(self.browser, 'kill'):
                    await self.browser.kill()
                elif hasattr(self.browser, 'close'):
                    await self.browser.close()
        except:
            pass
        
        # Guardian handles process cleanup automatically
        if hasattr(self, 'guardian'):
            self.guardian.cleanup()
            
        self._release_lock()

    async def restart_browser(self):
        """Restarts the browser session to keep memory usage low (v0.7.0)."""
        logger.info("♻️ Recycling browser to free up RAM...")
        try:
            if hasattr(self, 'browser'):
                if hasattr(self.browser, 'kill'):
                    await self.browser.kill()
                elif hasattr(self.browser, 'close'):
                    await self.browser.close()
            
            # Brief pause for OS to reclaim resources
            await asyncio.sleep(2)
            self._browser_started = False
            self.browser = None
            await self._setup_browser(headless=self._browser_headless)
            self._authenticated = False
            await self.check_auth()
            logger.info("♻️ Browser recycled successfully.")
        except Exception as e:
            logger.error(f"Failed to recycle browser: {e}")

    async def _show_macos_dialog(self, message: str, title: str = "LSAMC", buttons: list = ["OK"]) -> str:
        """Helper to show a native macOS dialog and get result (async version)."""
        def _run_sync_dialog():
            btn_str = '", "'.join(buttons)
            # Escape quotes for AppleScript
            clean_msg = message.replace('"', '\\"')
            script = f'display dialog "{clean_msg}" with title "{title}" buttons {{"{btn_str}"}} default button "{buttons[-1]}" giving up after 60'
            res = self.bridge._run_applescript(script)
            return res.get("output", "")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_sync_dialog)

    async def _download_photo(self, url: str) -> Optional[str]:
        """Downloads a photo via browser context to avoid 403s."""
        import tempfile
        import base64
        import json
        if os.path.exists(url):
            logger.info(f"Using local historical file: {url}")
            return url

        if url.startswith("data:image/"):
            try:
                header, data = url.split(",", 1)
                ext = header.split(";")[0].split("/")[-1]
                if ext == "jpeg": ext = "jpg"
                tmp = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
                tmp.write(base64.b64decode(data))
                tmp.close()
                logger.info(f"Using direct canvas-captured image ({len(data)} bytes).")
                return tmp.name
            except Exception as e:
                logger.error(f"Failed to decode data URL: {e}")
                return None

        try:
            page = await self.browser.get_current_page()
            if page:
                result_json = await page.evaluate(r"""
                    (baseUrl) => {
                        return (async (url) => {
                            const sizes = ['800_800', '400_400', '200_200'];
                            let res = null;
                            let chosenUrl = url;
                            let attempts = [];
                            
                            if (url.includes('shrink_') || url.includes('scale_')) {
                                for (const size of sizes) {
                                    const testUrl = url.replace(/(shrink|scale)_[0-9x_]+/g, '$1_' + size);
                                    // Try with original signature first
                                    try {
                                        const testRes = await fetch(testUrl, {
                                            headers: {
                                                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                                                'Referer': 'https://www.linkedin.com/',
                                                'Sec-Fetch-Dest': 'image',
                                                'Sec-Fetch-Mode': 'cors',
                                                'Sec-Fetch-Site': 'same-site'
                                            }
                                        });
                                        attempts.push({ url: testUrl, ok: testRes.ok, status: testRes.status });
                                        if (testRes.ok) {
                                            res = testRes;
                                            chosenUrl = testUrl;
                                            break;
                                        }
                                    } catch (e) {
                                        attempts.push({ url: testUrl, error: e.message });
                                    }

                                    // Fallback: Try without signature (sometimes works if the asset is public and signature is just for the specific size)
                                    if (!res || !res.ok) {
                                        const noSigUrl = testUrl.split('&t=')[0];
                                        if (noSigUrl !== testUrl) {
                                            try {
                                                const noSigRes = await fetch(noSigUrl, {
                                                    headers: { 'Referer': 'https://www.linkedin.com/' }
                                                });
                                                attempts.push({ url: noSigUrl, ok: noSigRes.ok, status: noSigRes.status, msg: "no-sig" });
                                                if (noSigRes.ok) {
                                                    res = noSigRes;
                                                    chosenUrl = noSigUrl;
                                                    break;
                                                }
                                            } catch (e) {}
                                        }
                                    }
                                }
                            }
                            
                            if (!res || !res.ok) {
                                try {
                                    res = await fetch(url, {
                                        headers: {
                                            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                                            'Referer': 'https://www.linkedin.com/',
                                            'Sec-Fetch-Dest': 'image',
                                            'Sec-Fetch-Mode': 'cors',
                                            'Sec-Fetch-Site': 'cross-site'
                                        }
                                                                        });
                                    chosenUrl = url;
                                    attempts.push({ url: url, ok: res.ok, status: res.status, msg: "fallback" });
                                } catch (e) {
                                    attempts.push({ url: url, error: e.message, msg: "fallback" });
                                }
                            }
                            
                            if (!res || !res.ok) return JSON.stringify({ error: "Fetch failed", attempts });
                            
                            const blob = await res.blob();
                            const b64 = await new Promise((resolve) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                                reader.readAsDataURL(blob);
                            });
                            
                            return JSON.stringify({
                                data: b64,
                                url: chosenUrl,
                                size: blob.size,
                                is_png: chosenUrl.toLowerCase().includes('.png') || chosenUrl.includes('.png?'),
                                contentType: res.headers.get('content-type'),
                                attempts
                            });
                        })(baseUrl);
                    }
                """, url)
                
                result = json.loads(result_json) if result_json else {}
                if result.get('data'):
                    img_data = base64.b64decode(result['data'])
                    fd, path = tempfile.mkstemp(suffix=".jpg")
                    os.write(fd, img_data)
                    os.close(fd)
                    logger.info(f"Photo downloaded via browser ({len(img_data)} bytes) from: {result['url']}")
                    logger.debug(f"Download attempts: {result.get('attempts')}")
                    return path
                else:
                    logger.warning(f"Browser fetch failed: {result.get('error', 'unknown error')}. Attempts: {result.get('attempts')}")
        except Exception as e:
            logger.debug(f"Browser download attempt failed: {e}")

        # Fallback to requests (only for original url to avoid 403 noise)
        import requests
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                fd, path = tempfile.mkstemp(suffix=".jpg")
                os.write(fd, res.content)
                os.close(fd)
                logger.debug(f"Fallback requests download success: {len(res.content)} bytes")
                return path
        except:
            pass

        return None

    def _find_historical_photo(self, name_or_url: str) -> Optional[str]:
        """Searches all previous sessions for an HQ photo of the contact."""
        # Clean name/handle
        safe_id = "".join([c if c.isalnum() else "_" for c in name_or_url])
        
        sessions_base = "logs/sessions"
        if not os.path.exists(sessions_base):
            return None
            
        sessions = sorted(os.listdir(sessions_base), reverse=True)
        for session in sessions:
            if session == os.path.basename(self.session_dir): continue
            
            # Check backups folder
            backup_path = os.path.join(sessions_base, session, "backups", safe_id)
            if os.path.isdir(backup_path):
                for ext in ["-linkedin-raw.jpg", "-linkedin.heic"]:
                    p = os.path.join(backup_path, f"{safe_id}{ext}")
                    if os.path.exists(p):
                        logger.info(f"Found historical HQ photo for {name_or_url} in session {session}")
                        return p
                
        return None

    async def _stealth_nav(self, page, url: str):
        """
        v5.0 Stealth: Organic Navigation Pattern
        Avoiding direct 'goto' which flags as bot traffic.
        """
        try:
            current_url = await page.get_url()
            if url in current_url: return

            logger.info(f"🎭 Stealth Nav: Spoofing organic flow to {url}")
            
            # 1. Go to Feed (if not already there)
            if "linkedin.com/feed" not in current_url:
                await page.goto("https://www.linkedin.com/feed/")
                # Random feed reading delay (1-3s)
                import random
                await asyncio.sleep(1.0 + random.random() * 2.0)
            
            # 2. "Paste" URL (Simulate user pasting into nav bar)
            # Actually, standard goto from Feed found to be safer than JS redirection 
            # as long as referrer is internal.
            await page.goto(url)
            
        except Exception as e:
            logger.warning(f"Stealth nav failed, falling back to direct: {e}")
            await page.goto(url)

    async def _human_scroll(self, page):
        """
        v5.0 Stealth: Human reading behavior
        Randomized scrolling speed, pauses, and direction changes.
        """
        import random
        try:
            # Initial load pause
            await asyncio.sleep(2.0 + random.random())
            
            # Scroll down in chunks
            for _ in range(random.randint(3, 6)):
                scroll_amount = random.randint(300, 800)
                await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                await asyncio.sleep(0.5 + random.random() * 1.5)
                
                # Occasional small scroll up (reading behavior)
                if random.random() < 0.3:
                     await page.evaluate("window.scrollBy(0, -100)")
                     await asyncio.sleep(0.5)
            
            # Scroll back to top for extraction
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1.0)
        except:
            pass

    async def extract_profile(self, linkedin_url: str, initial_stats: Optional[dict] = None, skip_photo: bool = False) -> Optional[LinkedInProfile]:
        """Extracts structured data from a LinkedIn profile using direct navigation and LLM extraction."""
        logger.info(f"Extracting profile from {linkedin_url}...")
        page = None
        
        # v1.3.2: Wrap entire method in try-finally to ensure page cleanup on any error
        try:
            # v1.4.3: Lazy initialization
            if not self.vault_only:
                await self._setup_browser(headless=self._browser_headless)

            # Browser-use navigation can be flaky, try to get current page or create new
            try:
                page = await self.browser.get_current_page()
                if page:
                    logger.debug(f"Using existing page: {await page.get_url()}")
                else:
                    logger.debug("No current page found, creating new one...")
                    page = await self.browser.new_page(linkedin_url)
            except Exception as be:
                logger.debug(f"Failed to get/create page: {be}. Forcing new page.")
                page = await self.browser.new_page(linkedin_url)
            # Ensure we are on the correct page
            current_url = await page.evaluate("() => window.location.href")
            if linkedin_url not in current_url:
                await self._stealth_nav(page, linkedin_url)
                
            # Wait for actual content (v0.5.7 - JS polling)
            try:
                wait_sel = '.pv-top-card, [class*="pv-top-card"], .pv-text-details__about-this-profile, h1.text-heading-xlarge, .top-card-layout__title, .profile-view-grid'
                found = False
                for _ in range(25):
                    if await page.evaluate(f"() => !!document.querySelector('{wait_sel}')"):
                        found = True
                        break
                    await asyncio.sleep(1)
                
                if not found:
                    # Check for 404 or Page Not Found
                    content_lower = (await page.evaluate("() => document.body?.innerText || ''")).lower()
                    error_keywords = ["page not found", "لم يتم العثور على الصفحة", "n'avons pas pu trouver cette page", "security check", "quick security check", "disappeared", "doesn't exist"]
                    # v5.1: Auth Wall Detection (Emergency Pause)
                    auth_keywords = ["join linkedin", "log in", "s'identifier", "sign in", "professional network"]
                    
                    if any(k in content_lower for k in error_keywords) or "linkedin-error" in current_url:
                        logger.error(f"Target page appears to be an error or search/auth block: {linkedin_url}")
                        return None
                    
                    if any(k in content_lower for k in auth_keywords):
                        logger.critical("🛑 LOGIN WALL DETECTED during extraction! Triggering Emergency Pause...")
                        # This method contains the macOS dialog loop that pauses the engine
                        if await self.check_auth():
                             logger.info("✅ Auth restored by user. Retrying navigation...")
                             await self._stealth_nav(page, linkedin_url)
                             # Recursive call to retry after auth fix
                             return await self.extract_profile(linkedin_url, initial_stats, skip_photo)
                        return None
                        
                    logger.warning("Profile content marker not found via JS discovery. Proceeding anyway...")
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Profile wait polling failed: {e}. Proceeding...")

            # Scroll to trigger lazy loading (v0.3.9) - deeper scroll for activity
            # v5.0: Use Human Scroll
            await self._human_scroll(page)
        except Exception as ne:
            logger.error(f"Navigation/Page setup failed: {ne}")
            return None

        # 1. Aggressive HQ Photo Discovery & Trigger
        photo_url = None
        if not skip_photo:
            try:
                # --- TIER 1: Network Sniffer (Passive) ---
                sniffer = NetworkSniffer()
                # v0.7.5: Emergency Owner Blacklist
                if self._owner_photo_url:
                    sniffer.blacklist_url(self._owner_photo_url)
                if self._owner_photo_signature:
                    sniffer.blacklist_url(self._owner_photo_signature)
                
                # Access underlying Playwright page for CDP events
                pw_page = None
                # Deep discovery for browser-use actor
                sniffer_registered = False
                try:
                    # Path 1: browser_session.session_manager
                    s_mgr = None
                    for attr in ['browser_session', '_browser_session']:
                        if hasattr(page, attr):
                            s = getattr(page, attr)
                            if hasattr(s, 'session_manager'):
                                s_mgr = s.session_manager
                                break
                    
                    if not s_mgr and hasattr(self.browser, 'session_manager'):
                        s_mgr = self.browser.session_manager

                    if s_mgr and hasattr(s_mgr, '_sessions'):
                        for s_id, session in s_mgr._sessions.items():
                            # direct CDP registration (Reliable for browser-use 0.11.x)
                            if hasattr(session, 'cdp_client'):
                                try:
                                    session.cdp_client.register.Network.responseReceived(sniffer.handle_response)
                                    sniffer_registered = True
                                    logger.debug(f"[Sniffer] Registered via CDP for session {s_id[:8]}")
                                except Exception as cdp_err:
                                    logger.debug(f"CDP Registration Error: {cdp_err}")
                            
                            if hasattr(session, 'page'):
                                pw_page = session.page
                            elif hasattr(session, '_page'):
                                pw_page = session._page
                    
                    if not sniffer_registered:
                        # Path 3: context pages (Playwright fallback)
                         if hasattr(self.browser, '_browser_context'):
                             ctx = self.browser._browser_context
                             if ctx and ctx.pages:
                                 pw_page = ctx.pages[0]
                except Exception as e:
                    logger.debug(f"Sniffer Discovery Error: {e}")

                if not sniffer_registered and pw_page and hasattr(pw_page, 'on'):
                    try:
                        pw_page.on("response", sniffer.handle_response)
                        sniffer_registered = True
                        logger.info("Tier 1 SUCCESS: Attached sniffer to Playwright Page.")
                    except:
                        pass
                
                if not sniffer_registered:
                    logger.warning("Tier 1 FAIL: Could not find CDP/Playwright hook for Sniffer.")
                
                logger.debug(f"Tier 1: Sniffer state: {sniffer}")
                logger.info("Tier 1: Listening for passive HQ photo traffic...")
                # Scroll to trigger lazy loads
                await page.evaluate("() => window.scrollTo(0, 500)")
                await asyncio.sleep(1.5)
                await page.evaluate("() => window.scrollTo(0, 0)")
                await asyncio.sleep(1.0)
                
                # Check Sniffer
                best_url = sniffer.get_best_candidate()
                if best_url:
                    logger.info(f"Tier 1 SUCCESS: Passive capture of HQ URL: {best_url[:60]}...")
                    photo_url = best_url
                else:
                    # --- TIER 2: Vision-Based Interaction & Canvas Fallback ---
                    logger.info("Tier 1 yielded nothing. Engaging Tier 2 (Vision + Interactivity)...")
                    
                    # 1. Take Screenshot for Vision
                    screenshot_data = await page.screenshot()
                    # Ensure it's bytes (browser-use might return base64 string)
                    if isinstance(screenshot_data, str):
                        # If it's a data URL or just base64, clean it
                        if ',' in screenshot_data:
                            screenshot_data = screenshot_data.split(',')[1]
                        screenshot_bytes = base64.b64decode(screenshot_data)
                    else:
                        screenshot_bytes = screenshot_data
                    
                    # 2. Coordinate Discovery Strategy
                    click_coords = None
                    
                    # Priority 1: JS Detection (Highest Precision)
                    try:
                        js_coords = await page.evaluate(r"""() => {
                            const img = document.querySelector('.pv-top-card-profile-picture__image') || 
                                        document.querySelector('img.profile-display-photo') ||
                                        document.querySelector('.pv-top-card-profile-picture img');
                            if(img) {
                                const r = img.getBoundingClientRect();
                                if (r.width > 0 && r.height > 0) {
                                    return { x: r.left + r.width/2, y: r.top + r.height/2 };
                                }
                            }
                            return null;
                        }""")
                        if js_coords:
                            click_coords = js_coords
                            logger.info(f"Tier 2: Found coordinates via JS: {click_coords}")
                    except Exception as jse:
                        logger.debug(f"JS Coord Detection Error: {jse}")

                    # Priority 2: Jan 16 Baseline (Fallback for 800x600 or 1280x800)
                    if (False): # v0.7.5: Disabled coordinate guessing (leads to owner photo pollution)
                        # v3.1.6: Dynamic coordinates based on viewport width
                        viewport = await page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
                        if viewport['w'] > 1000:
                            click_coords = {'x': 200, 'y': 220} # 1280x800 guess
                        else:
                            click_coords = {'x': 128, 'y': 175} # Legacy 800x600 guess
                        logger.info(f"Tier 2: Using guessed coordinates for {viewport['w']}x{viewport['h']}: {click_coords}")
                    
                    if click_coords:
                        cx, cy = click_coords['x'], click_coords['y']
                        logger.info(f"Tier 2: Clicking estimated centroid at {cx},{cy}")
                        
                        # Click to open lightbox
                        # We need the underlying mouse if possible, but page.click() usually works
                        try:
                            # Use browser-use wrapper's click if it supports coords
                            # Actually, playwright page mouse is best
                            if hasattr(pw_page, 'mouse'):
                                await pw_page.mouse.click(cx, cy)
                            else:
                                # v4.9.1 B2: DOM walk to find first clickable ancestor (AUDIT_2026-03-11)
                                await page.evaluate(f"""() => {{
                                    let el = document.elementFromPoint({cx}, {cy});
                                    let maxWalk = 6;
                                    while (el && maxWalk-- > 0) {{
                                        if (el.tagName === 'BUTTON' || el.tagName === 'A' ||
                                            el.getAttribute('role') === 'button' || el.onclick) {{
                                            el.click();
                                            break;
                                        }}
                                        el = el.parentElement;
                                    }}
                                }}""")
                        except Exception as ce:
                            logger.warning(f"Click failed: {ce}")
                            
                        await asyncio.sleep(2.5)
                        
                        # Check Sniffer again (Tier 1.5 - Network traffic after click)
                        best_url = sniffer.get_best_candidate()
                        if best_url:
                             logger.info(f"Tier 2 SUCCESS: Network traffic captured after click: {best_url[:60]}...")
                             photo_url = best_url
                        else:
                             # --- TIER 3: Canvas Backup ---
                             logger.info("Tier 2 Network failed. Engaging Tier 3 (Canvas Extraction)...")
                             modal_data = await page.evaluate(r"""
                                 () => {
                                     const img = document.querySelector('.artdeco-modal img[src*="displayphoto"], .artdeco-modal img[src*="shrink_800"], .pv-member-photo-modal__content img');
                                     if(img && img.naturalWidth > 200) {
                                         try {
                                             const c = document.createElement('canvas');
                                             c.width = img.naturalWidth;
                                             c.height = img.naturalHeight;
                                             c.getContext('2d').drawImage(img, 0, 0);
                                             return c.toDataURL('image/jpeg', 0.95);
                                         } catch(e) { return null; }
                                     }
                                     return null;
                                 }
                             """)
                             if modal_data:
                                 logger.info("Tier 3 SUCCESS: Canvas extracted from lightbox.")
                                 photo_url = modal_data
                             else:
                                 logger.warning("All Tiers failed to find high-res photo.")

                        # Close modal
                        await page.evaluate("() => { (document.querySelector('.artdeco-modal__dismiss') || document.querySelector('[aria-label=\"Dismiss\"]') || document.querySelector('.artdeco-close'))?.click(); }")
                    else:
                        logger.warning("Could not identify profile picture location (Blind).")
                
                # Detach sniffer
                if hasattr(pw_page, 'remove_listener'):
                    pw_page.remove_listener("response", sniffer.handle_response)
                
            except Exception as pe:
                 logger.warning(f"Photo pipeline error: {pe}")
                 import traceback
                 logger.debug(traceback.format_exc())
        else:
            logger.info("Skipping high-res photo enrichment (skip_photo=True).")

        # 2. Stats and Identity (v0.3.9 consolidated into Surgical)
        # Use initial_stats if provided to seed the values
        raw_stats = initial_stats.copy() if initial_stats else {}
        
        if photo_url:
            logger.info(f"Final Photo URL candidate: {photo_url[:70]}...")
        else:
            logger.info("No high-res photo captured in current session. Will attempt historical lookup after extraction.")
        
        # Human-like behavior: scroll a bit to trigger lazy loading of other sections
        try:
            await page.evaluate("window.scrollTo(0, 500);")
            await asyncio.sleep(1)
        except:
            pass
        
        # 3. Contact Info Popup Extraction
        contact_info = {}
        try:
            logger.info("Opening Contact Info popup...")
            # Try to trigger the click and wait for the modal
            click_success = False
            for attempt in range(2):
                success_raw = await page.evaluate(r"""
                    () => {
                        const selectors = [
                            '#top-card-text-details-contact-info',
                            'a[href*="contact-info"]',
                            '.pv-top-card--list-bullet a[href*="contact-info"]',
                            '.pv-top-card--list a[href*="contact-info"]',
                            'a[role="button"][href*="contact-info"]',
                            '[aria-label*="Contact info"]',
                            '[aria-label*="Informations de contact"]'
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetParent !== null) {
                                el.scrollIntoView({behavior: 'instant', block: 'center'});
                                el.click();
                                el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                                return JSON.stringify({ success: true, selector: sel });
                            }
                        }
                        return JSON.stringify({ success: false });
                    }
                """)
                
                success = json.loads(success_raw) if isinstance(success_raw, str) else success_raw
                if success and success.get('success'):
                    logger.debug(f"Contact Info click triggered via: {success.get('selector')}")
                    click_success = True
                    break
                else:
                    logger.warning(f"Contact Info trigger attempt {attempt+1} failed to find element.")
                    await asyncio.sleep(2)
            
            if not click_success:
                logger.info("Clicking failed, trying direct navigation to contact-info overlay...")
                # Handle query parameters (v0.3.5 fix)
                if "?" in str(linkedin_url):
                    base, query = str(linkedin_url).split("?", 1)
                    overlay_url = base.rstrip('/') + "/overlay/contact-info/?" + query
                else:
                    overlay_url = str(linkedin_url).rstrip('/') + "/overlay/contact-info/"
                await self.browser.navigate_to(overlay_url)
                await asyncio.sleep(3)
            else:
                await asyncio.sleep(3) 
            
            contact_info_json = await page.evaluate(r"""
                () => {
                    // Search for modal OR the section in the main page if we navigated directly
                    const selectors = [
                        '.artdeco-modal', 
                        '#artdeco-modal-outlet', 
                        '[role="dialog"]', 
                        '.pv-contact-info',
                        'section.pv-contact-info__contact-type',
                        '.pv-profile-section.pv-contact-info'
                    ];
                    let modal = null;
                    for (const sel of selectors) {
                        modal = document.querySelector(sel);
                        if (modal) break;
                    }
                    
                    const data = { websites: [], emails: [], phones: [] };
                    const root = modal || document.body;
                    
                    if (!modal && !window.location.href.includes('contact-info')) {
                         data.error = "Modal not found and not on contact-info page";
                    }
                    
                    // Search for both specific sections and general headers
                    const sections = Array.from(root.querySelectorAll('.pv-contact-info__contact-type, section, .pv-contact-info__header, .pv-contact-info__ci-container, .pv-contact-info__contact-link, a.pv-contact-info__contact-link'));
                    sections.forEach(s => {
                        const fullText = s.innerText || '';
                        const headerEl = s.querySelector('.pv-contact-info__header, h3') || (s.classList.contains('pv-contact-info__header') ? s : null);
                        const header = headerEl?.innerText?.trim()?.toLowerCase() || '';
                        
                        const textLower = fullText.toLowerCase();
                        const isWebsite = header.includes('website') || s.classList.contains('ci-websites') || header.includes('site web');
                        const isEmail = header.includes('email') || s.classList.contains('ci-email') || header.includes('courriel') || (s.querySelector('a[href^="mailto:"]') !== null);
                        const isPhone = header.includes('phone') || s.classList.contains('ci-phone') || header.includes('téléphone') || (s.querySelector('a[href^="tel:"]') !== null);
                        const isConnected = header.includes('connected') || header.includes('relation') || textLower.includes('connected since') || textLower.includes('relation depuis le') || textLower.includes('depuis le');
                        const isBirthday = header.includes('birthday') || header.includes('anniversaire');

                        if (isWebsite) {
                            // v3.1.8 Trace all links in this section or the element itself
                            const sources = s.closest('.pv-contact-info__contact-type') || s;
                            const links = Array.from(sources.querySelectorAll('a'))
                                .concat(sources.tagName === 'A' ? [sources] : [])
                                .map(a => a.href)
                                .filter(h => h && h.startsWith('http') && !h.includes('p-contact-info') && !h.includes('/search/') && !h.includes('/in/')); 
                            if (links.length) data.websites = [...new Set([...data.websites, ...links])];
                        } else if (isEmail) {
                            // v3.1.8 Trace all inner text or links that look like emails
                            const sources = s.closest('.pv-contact-info__contact-type') || s;
                            const emails = Array.from(sources.querySelectorAll('a'))
                                .concat(sources.tagName === 'A' ? [sources] : [])
                                .map(a => a.innerText.trim())
                                .concat(sources.innerText.split(/\s+/))
                                .filter(t => t.includes('@') && !t.includes('linkedin.com'));
                            if (emails.length) data.emails = [...new Set([...data.emails, ...emails])];
                        } else if (isPhone) {
                            const phone = (s.closest('.pv-contact-info__contact-type') || s).querySelector('.pv-contact-info__contact-item, .pv-contact-info__ci-container, a[href^="tel:"]')?.innerText?.trim();
                            if (phone && !data.phones.includes(phone)) data.phones.push(phone);
                        }
                        
                        if (isConnected) {
                            // Connected Date: Ultra-Robust Scan (v0.4.3)
                            const text = root.innerText;
                            const labels = ['Connected since', 'Relation depuis le', 'Relation depuis', 'Relation'];
                            let foundDate = null;
                            for (const label of labels) {
                                if (text.includes(label)) {
                                    const split = text.split(label)[1] || '';
                                    const match = split.match(/([A-Za-z.\u00c0-\u00ff]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z.\u00c0-\u00ff]+\s+\d{4})/i);
                                    if (match) {
                                        foundDate = match[0].trim();
                                        break;
                                    }
                                }
                            }
                            if (foundDate) data.connected_date = foundDate;
                            
                            // Last resort: simple regex match anywhere
                            if (!data.connected_date) {
                                 const m = text.match(/([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})/);
                                 if (m) data.connected_date = m[1];
                            }
                        } else if (isBirthday && !data.birthday) {
                            const b_lines = fullText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                            const bdLine = b_lines.find((l, idx) => idx > 0 && (/[a-zA-Z]/.test(l) && /\d/.test(l)));
                            if (bdLine) data.birthday = bdLine;
                        }
                    });
                    
                    // --- Regex Fallbacks (Very Robust) ---
                    const text = root.innerText;
                    if (data.emails.length === 0) {
                        const emailRegex = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/g;
                        const matches = text.match(emailRegex);
                        if (matches) data.emails = [...new Set(matches)];
                    }
                    
                    // Birthday
                    if (!data.birthday) {
                        const bdRegex = /(?:Birthday|Anniversaire)\s*\n*\s*([A-Z][a-zâäàéèêëîïôöûüùç]+\s+\d{1,2}|\d{1,2}\s+[a-zâäàéèêëîïôöûüùç]+)/i;
                        const match = text.match(bdRegex);
                        if (match && match[1]) data.birthday = match[1].trim();
                    }
                    
                    // Cleanup: Try to close the modal or navigate back if we moved
                    const closeBtn = document.querySelector('.artdeco-modal__dismiss, [aria-label="Dismiss"], .artdeco-modal__close, [aria-label*="Fermer"]');
                    if (closeBtn) closeBtn.click();
                    
                    return JSON.stringify(data);
                }
            """)
            contact_info = json.loads(contact_info_json) if isinstance(contact_info_json, str) else contact_info_json
            if contact_info.get('error'):
                logger.debug(f"Contact Info extraction error: {contact_info['error']}")
            if contact_info.get('connected_date'):
                logger.info(f"LinkedIn Connection Date found: {contact_info['connected_date']}")
        except Exception as ce:
            logger.warning(f"Failed to extract contact info popup: {ce}")

        # --- SURGICAL-FIRST EXTRACTION (v0.3.5) ---
        # User Priority: Prioritize Surgical Local Scrape to save credits and stabilize core data.
        logger.info(f"Final stats before surgical scrape: {raw_stats}")
        logger.info("Attempting primary Surgical Local Scrape...")
        local_p = await self._surgical_local_scrape(page, linkedin_url, photo_url, contact_info, raw_stats)
        if local_p:
            # Fix 'LinkedIn' name glitch if possible (v0.3.9)
            if local_p.full_name == "LinkedIn" and initial_stats.get('job_title'):
                # Try to extract name from job_title which might be "Name \n • 1st..."
                raw_name = initial_stats['job_title'].split('\n')[0].strip()
                if len(raw_name) > 3:
                    logger.info(f"Correcting scrape name 'LinkedIn' back to search-time name: {raw_name}")
                    local_p.full_name = raw_name

            # v0.7.5: Historical Photo Recovery if still missing
            if not local_p.photo_url:
                local_p.photo_url = photo_url or self._find_historical_photo(local_p.full_name) or self._find_historical_photo(linkedin_url.split('/in/')[-1].strip('/'))
            
            if initial_stats and initial_stats.get('is_first'):
                local_p.connection_degree = 1

            # FORCED LOCAL RETURN only if we have professional data (v0.7.7)
            # v1.4.2: UNLESS we are in A/B test mode, in which case we continue to compare
            if (local_p.current_role or local_p.company or local_p.experience) and not self.ab_test_mode:
                logger.info(f"Returning Surgical Local Scrape results for {local_p.full_name} (Surgical Priority Mode).")
                return local_p
            else:
                logger.warning(f"Surgical Scrape for {local_p.full_name} returned empty or A/B Test enabled. Proceeding...")
              
        # v1.4.2: AB TEST Branch B (Hybrid)
        hybrid_p = None
        hybrid_duration = 0
        if self.ab_test_mode:
            logger.info("🧪 [AB-TEST] Branch B: Capturing snapshots for Hybrid OCR...")
            h_start = time.time()
            snapshots = await self._capture_element_screenshots(local_p.full_name if local_p else "Unknown")
            hybrid_p = await self._hybrid_extract_fallback(local_p.full_name if local_p else "Unknown", snapshots)
            hybrid_duration = (time.time() - h_start)

        logger.warning("Surgical Local Scrape completely failed or A/B Test active. Falling back to Gemini as secondary enrichment.")
        try:
             # Instruction for extraction - be concise to save tokens
             instruction = "Extract LinkedIn profile data: Full name, Headline, About/Summary, Experience (list of title+company), Education, Skills."
             profile_data = await page.extract_content(
                 prompt=instruction,
                 structured_output=LinkedInProfile,
                 llm=self.llm
             )
             if profile_data:
                 profile_data.linkedin_url = linkedin_url
                 if photo_url and not profile_data.photo_url:
                     profile_data.photo_url = photo_url
                 
                 # Aggregate stats and popup info
                 profile_data.followers_count = profile_data.followers_count or raw_stats.get('followers')
                 profile_data.connections_count = profile_data.connections_count or raw_stats.get('connections')
                 profile_data.common_connections_count = profile_data.common_connections_count or raw_stats.get('mutual')
                 profile_data.mutual_raw = profile_data.mutual_raw or raw_stats.get('mutual_raw')
                 profile_data.websites = list(set(profile_data.websites + contact_info.get('websites', [])))
                 profile_data.emails = list(set(profile_data.emails + contact_info.get('emails', [])))
                 profile_data.phones = list(set(profile_data.phones + contact_info.get('phones', [])))
                 profile_data.birthday = profile_data.birthday or contact_info.get('birthday')
                 profile_data.connected_date = profile_data.connected_date or contact_info.get('connected_date')
                                  
                 self._sanitize_profile(profile_data)
                 
                 if self.ab_test_mode:
                    a_duration = (time.time() - (h_start if 'h_start' in locals() else time.time()))
                    self._record_comparison(
                        local_p.full_name if local_p else "Unknown",
                        profile_data,
                        hybrid_p if 'hybrid_p' in locals() else None,
                        {"branch_a_duration": a_duration, "branch_b_duration": hybrid_duration if 'hybrid_duration' in locals() else 0}
                    )

                 # v1.3.2: Cleanup page immediately after extraction
                 await self._cleanup_page(page)
                  
                 return profile_data
        except Exception as e:
            if "exhausted" in str(e).lower() or "429" in str(e):
                self.quota_exhausted = True

            logger.warning(f"Built-in extract_content failed: {e}. Falling back to manual.")

            # v0.9.1: Immediate fallback if quota is exhausted
            if self.quota_exhausted:
                logger.warning(f"Quota exhausted. Skipping LLM extraction for {linkedin_url}. Using Surgical Scrape.")
                return await self._surgical_local_scrape(page, linkedin_url, photo_url, contact_info, raw_stats)

            # Use pruned content for LLM to save tokens and avoid noise
            content = await self._get_pruned_content(page)
            snippet = content[:500].replace('\n', ' ')
            logger.debug(f"Pruned content snippet for extraction: {snippet}")
            prompt = f"Extract LinkedIn profile data from this text. Focus on Name, Job Title, Company, Location.\n\nText:\n{content[:15000]}\n\nReturn ONLY raw JSON matching this schema: {LinkedInProfile.model_json_schema()}"
            try:
                if not self.genai_client:
                    raise ValueError("LLM client not initialized")
                    
                response = await self.genai_client.ainvoke(prompt)
                raw_text = response.content
                if isinstance(raw_text, list):
                    raw_text = " ".join([str(item) for item in raw_text])
                logger.debug(f"Raw LLM extraction response: {raw_text}")
                # Clean possible markdown wrap
                json_text = re.sub(r'^```json\s*|\s*```$', '', str(raw_text).strip(), flags=re.MULTILINE)
                json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    # Ensure mandatory fields
                    if not data.get('linkedin_url') or 'http' not in str(data.get('linkedin_url')):
                        data['linkedin_url'] = linkedin_url
                    profile = LinkedInProfile(**data)
                    # FORCE current date to avoid LLM hallucinations (v0.7.8 fix)
                    profile.timestamp = datetime.now().isoformat()[:10]
                    
                    # Identity Guard (v1.5.4): Prevent owner profile sync if page is redirected/missing
                    if profile.full_name and "philippe dewost" in profile.full_name.lower():
                        logger.error(f"🚨 Identity Mismatch: LLM extracted owner profile from {linkedin_url}. Rejecting.")
                        return None
                    
                    if not profile.full_name and local_p: profile.full_name = local_p.full_name
                    if not profile.current_role and local_p: profile.current_role = local_p.current_role
                    if not profile.location and local_p: profile.location = local_p.location
                    if not profile.summary and local_p: profile.summary = local_p.summary

                    # Aggregate base-page stats and popup info if LLM missed them
                    if not profile.photo_url:
                        profile.photo_url = photo_url or self._find_historical_photo(profile.full_name) or self._find_historical_photo(linkedin_url.split('/in/')[-1].strip('/'))
                    
                    profile.connection_degree = 1 if initial_stats and initial_stats.get('is_first') else None
                    
                    profile.followers_count = profile.followers_count or raw_stats.get('followers')
                    profile.connections_count = profile.connections_count or raw_stats.get('connections')
                    profile.common_connections_count = profile.common_connections_count or raw_stats.get('mutual')
                    profile.mutual_raw = profile.mutual_raw or raw_stats.get('mutual_raw')
                    profile.websites = list(set(profile.websites + contact_info.get('websites', [])))
                    profile.emails = list(set(profile.emails + contact_info.get('emails', [])))
                    profile.phones = list(set(profile.phones + contact_info.get('phones', [])))
                    profile.birthday = profile.birthday or contact_info.get('birthday')
                    profile.connected_date = profile.connected_date or contact_info.get('connected_date')
                    
                    self._sanitize_profile(profile)
                    return profile
                else:
                    logger.error(f"No JSON block found in LLM response: {raw_text}")
            except Exception as e:
                logger.warning(f"LLM extraction failed ({str(e)[:100]}).")
                if local_p:
                    logger.info(f"Surgical Local Scrape (cached) recovered profile: {local_p.full_name}")
                    return local_p
                
                # If we didn't even have a cached one, try one last time
                p = await self._surgical_local_scrape(page, linkedin_url, photo_url, contact_info, raw_stats)
                if p:
                    logger.info(f"Final Surgical Local Scrape successfully recovered profile: {p.full_name}")
                    # v0.7.5: Final Photo Recovery Attempt before returning
                    if not p.photo_url:
                        hist_photo = self._find_historical_photo(p.full_name)
                        if hist_photo:
                            p.photo_url = f"file://{os.path.abspath(hist_photo)}"
                    
                    # Ensure degree is populated
                    if initial_stats and initial_stats.get("is_first"):
                        p.connection_degree = 1
                    
                    return p
        except Exception as e:
            logger.warning(f"LLM/Local backfill failed: {e}")
            return None
        
        finally:
            # v1.3.2: GUARANTEE page cleanup on success OR failure
            if page:
                await self._cleanup_page(page)
                logger.debug("✅ Page cleanup guaranteed by finally block")

    async def _surgical_local_scrape(self, page, linkedin_url: str, photo_url: Optional[str] = None, contact_info: dict = {}, raw_stats: dict = {}) -> Optional[LinkedInProfile]:
        """ Professional client-side automation via JS. 0 credits, 100% reliable for core fields. """
        try:
            try:
                # v0.7.3: Wait for body or main content to ensure some rendering
                await page.wait_for_selector('body', timeout=5000)
                # Broader check for profile-like content
                await page.wait_for_selector('main, .scaffold-layout__main, .pv-top-card, h1, h2', timeout=3000)
            except:
                logger.warning(f"[Surgical] Partial timeout waiting for profile elements on {linkedin_url}")
            
            # v0.7.3 settlement wait: Force wait for hydration regardless of selector success
            await asyncio.sleep(3.0)
            
            # Identity - prioritize the H1 or the top card name container
            raw_info = await page.evaluate(r"""
                () => {
                    // v1.5.4: Strictly target the profile area to avoid nav/header noise
                    const profileRoot = document.querySelector('.pv-top-card, [id^="profile-content"], .scaffold-layout__main') || document.querySelector('main');
                    if (!profileRoot) return JSON.stringify({error: "No profile root found"});
                    
                    let h1 = profileRoot.querySelector('h1.text-heading-xlarge') || 
                             profileRoot.querySelector('.pv-text-details__left-panel h1') || 
                             profileRoot.querySelector('h1');
                    
                    let name = h1?.innerText?.trim();
                    // Fallback to title only if the root content looks empty
                    if (!name || name.toLowerCase() === 'linkedin') {
                        name = document.title.split('|')[0].replace(' | LinkedIn', '').trim();
                    }
                    
                    if (name.toLowerCase().includes('search') || name.toLowerCase() === 'linkedin' || 
                        name.toLowerCase().includes('authwall') || name.toLowerCase().includes('philippe dewost')) name = '';
                    
                    const h_el = profileRoot.querySelector('.text-body-medium.break-words') || 
                                   profileRoot.querySelector('h2.top-card-layout__headline') || 
                                   profileRoot.querySelector('.top-card-layout__headline') || 
                                   profileRoot.querySelector('div.text-body-medium') ||
                                   profileRoot.querySelector('.pv-text-details__left-panel div');
                    const headline = h_el?.innerText?.trim() || '';
                                     
                    const summary = document.querySelector('#about + div + div span[aria-hidden="true"], #about ~ .display-flex .inline-show-more-text, section.summary .core-section-container__content, .pv-about-section')
                                     ?.innerText?.trim() || '';
                    
                    const l_el = profileRoot.querySelector('.text-body-small.inline.t-black--light.break-words') || 
                                   profileRoot.querySelector('span.text-body-small.inline.break-words') || 
                                   profileRoot.querySelector('.top-card-layout__first-subline') ||
                                   profileRoot.querySelector('.pv-top-card--list-bullet li:last-child') ||
                                   profileRoot.querySelector('.pv-top-card-section__location') ||
                                   profileRoot.querySelector('.pv-text-details__left-panel + span') ||
                                   Array.from(profileRoot.querySelectorAll('span, div')).find(el => el.innerText?.includes(' France') || el.innerText?.includes(' area'));
                    const location = l_el?.innerText?.trim() || '';

                    // v3.1.4: Tier 4 Photo Fallback (Direct DOM)
                    // If high-res failed, grab the visible image (usually 200x200 or 400x400)
                    const imgEl = profileRoot.querySelector('img.pv-top-card-profile-picture__image') ||
                                  profileRoot.querySelector('img.pv-top-card__photo') ||
                                  profileRoot.querySelector('.pv-top-card__photo img') ||
                                  profileRoot.querySelector('.profile-photo-edit__preview') ||
                                  profileRoot.querySelector('img.update-components-actor__avatar-image') ||
                                  profileRoot.querySelector('img[class*="profile-photo"]') ||
                                  profileRoot.querySelector('img[class*="profile-photo"]') ||
                                  (h1?.innerText?.trim() ? profileRoot.querySelector('img[alt="' + h1.innerText.trim() + '"]') : null); // Alt match heuristic only if name found
                    let photoSrc = imgEl?.src || '';
                    if (photoSrc && (photoSrc.includes('shrink_100') || photoSrc.includes('shrink_200') || photoSrc.includes('shrink_400'))) {
                        photoSrc = photoSrc.replace(/shrink_\d+_\d+/, 'shrink_800_800');
                    }
                    
                    // Restricted Stats Search (within profileRoot only)
                    const statsStore = profileRoot.querySelector('.pv-top-card--list-bullet, .top-card__subline-item, .pv-text-details__separator') || profileRoot;
                    
                    const followersBtn = Array.from(profileRoot.querySelectorAll('span, a, div, li, [class*="follower"]')).find(el => {
                        const t = (el.innerText || '').toLowerCase();
                        // v3.1.6: Strict 'Follower' check. 
                        // Exclude 'Following' (Abonnement), 'Contacts' (Relations), 'Connections'
                        const isFollowing = t.includes('following') || t.includes('abonnement');
                        const isFollowerWord = t.includes('follower') || t.includes('abonné');
                        // v3.2.1: Relax exclusion. If it contains followers, it's a candidate.
                        return isFollowerWord && !isFollowing && /\d/.test(t) && !t.includes('mutual') && !t.includes('commun') && t.length < 150;
                    });
                    const followersTextRaw = followersBtn?.innerText || '';
                    
                    const mutualBtn = Array.from(profileRoot.querySelectorAll('span, a, div, li, button, [class*="mutual"], [class*="highlight"]')).find(el => {
                        const t = (el.innerText || '').toLowerCase().trim();
                        // v3.1.8: Broaden keywords and ensure digits or known name patterns (capitalized twins)
                        const keywords = ['mutual connection', 'relation en commun', 'relations en commun', 'common contact', 'shared connection', 'connexion en commun', 'mutuals', 'en commun'];
                        const hasKeyword = keywords.some(k => t.includes(k));
                        // v3.1.8: Fallback for "A and B" (no digits) - check if text length is reasonable and contains 'and'
                        const isCommonInsight = (t.includes(' and ') || t.includes(' et ')) && !t.includes('follower') && !t.includes('abonné') && !t.includes('following') && !t.includes('abonnement') && t.length < 150;
                        const hasDigits = /\d/.test(t);
                        return (hasKeyword || isCommonInsight) && (hasDigits || isCommonInsight) && t.length < 300;
                    });
                    // v0.7.8 Strategy: If it's a link/button, its text might be 'X mutual connections'. 
                    // If it's the 'insight' line, it's 'A, B and X others'.
                    // We prefer the simpler 'X mutual connections' if available as it's the exact total.
                    const mutualText = mutualBtn?.innerText || '';

                    const connectionBtn = Array.from(profileRoot.querySelectorAll('span, a, div, li, button')).find(el => {
                        const t = (el.innerText || '').toLowerCase();
                        // v0.7.8: Include 'contact' which is the new LinkedIn standard for '500+ contacts'
                        // v0.7.8: Exclude "work here" / "travaillent ici" which is often a false positive button
                        const isWorkHere = t.includes('work here') || t.includes('travaillent ici') || t.includes('travaillé ici') || t.includes('collaborateurs');
                        // v2.1.5: Stronger Degree Badge exclusion for connections (prevents '2nd' being parsed as 2 connections)
                        const isDegree = t.includes('degree') || t.includes('degré') || /^(1st|2nd|3rd|1er|2e|3e)$/.test(t.trim());
                        
                        // v3.2.1: include 'connexion' (FR)
                        const isConnText = t.includes(' connection') || t.includes(' relation') || t.includes(' contact') || t.includes(' connexion');
                        const isFollowerText = t.includes('follower') || t.includes('abonné');
                        
                        return isConnText && /\d/.test(t) && !t.includes('mutual') && !t.includes('commun') && !isWorkHere && !isDegree && t.length < 150;
                    });
                    let connectionText = connectionBtn?.innerText || '';
                    let followersText = followersTextRaw;

                    // v3.2.1: Handle combined subline (X followers • Y connections)
                    if (followersText === connectionText && followersText.includes('•')) {
                        const parts = followersText.split('•');
                        for (let p of parts) {
                            const pt = p.toLowerCase();
                            if (pt.includes('follower') || pt.includes('abonné')) followersText = p.trim();
                            if (pt.includes('connection') || pt.includes('relation') || pt.includes('contact')) connectionText = p.trim();
                        }
                    }

                    // v1.6.0: Extract explicit degree (2nd, 3rd)
                    // Usually in .dist-value or artdeco-badge
                    const degreeBadge = profileRoot.querySelector('.dist-value') || 
                                       Array.from(profileRoot.querySelectorAll('span.artdeco-badge__text, span.tvm-text, span[aria-hidden="true"], span.visually-hidden')).find(el => {
                                           const t = el.innerText.trim();
                                           return t === '1st' || t === '2nd' || t === '3rd' || t === '1er' || t === '2e' || t === '3e';
                                       });
                    const degreeText = degreeBadge ? degreeBadge.innerText.trim() : '';

                    // Simple Experience scraping (Top 3)
                    const expItems = Array.from(document.querySelectorAll('#experience ~ .display-flex .artdeco-list__item, .pv-profile-section.experience-section li.pv-position-entity, section#experience-section li, .experience-item'));
                    const expCount = expItems.length;
                    
                    // Try to get the first company for better matching
                    let firstCompany = document.querySelector('[data-field="experience_company_logo"] img')?.alt || '';
                    if (!firstCompany) {
                        const compEl = document.querySelector('.pv-text-details__right-panel .inline-show-more-text, .top-card-link-container');
                        firstCompany = compEl?.innerText?.split('\n')[0].trim() || '';
                    }
                    if (!firstCompany && expItems.length > 0) {
                        const compEl = expItems[0].querySelector('.t-14.t-normal span[aria-hidden="true"]') || expItems[0].querySelector('.experience-item__title') || expItems[0].querySelector('.pv-entity__secondary-title');
                        firstCompany = compEl?.innerText?.split('·')[0].trim() || '';
                    }

                    const experience = expItems.slice(0, 3).map(item => {
                        const titleEl = item.querySelector('.display-flex.align-items-center.mr1.t-bold span[aria-hidden="true"]') || item.querySelector('.experience-item__title') || item.querySelector('.t-bold span');
                        const companyEl = item.querySelector('.t-14.t-normal span[aria-hidden="true"]') || item.querySelector('.experience-item__subtitle') || item.querySelector('.pv-entity__secondary-title');
                        return { 
                            title: titleEl?.innerText?.trim() || '', 
                            company: companyEl?.innerText?.split('·')[0].trim() || '' 
                        };
                    }).filter(e => e.title);

                    return {
                        full_name: name.split('\n')[0].split('|')[0].trim(),
                        current_role: headline,
                        summary: summary,
                        location: location,
                        experience_raw: experience,
                        exp_count: expCount,
                        first_company: firstCompany,
                        followers_text: followersText,
                        mutual_text: mutualText,
                        connection_text: connectionText,
                        degree_text: degreeText,
                        photo_src: photoSrc,
                        debug_h1: h1?.outerHTML,
                        debug_title: document.title
                    };
                }
            """)
            
            
            result = json.loads(raw_info) if isinstance(raw_info, str) else raw_info
            
            # v1.5.7 SAFEGUARD: Robust Name Check (Prevent Identity Pollution)
            invalid_names = ['linkedin', 'this page doesn’t exist', 'page introuvable', 'philippe dewost']
            raw_name = (result.get('full_name') or '')
            
            # Normalize unicode (handle non-breaking spaces \xa0, etc)
            normalized_name = unicodedata.normalize('NFKC', raw_name).strip().lower()
            
            if not raw_name or any(inv in normalized_name for inv in invalid_names):
                logger.warning(f"🛑 [Surgical] BLOCKED: Invalid or corrupted identity detected: '{raw_name}' (Norm: '{normalized_name}').")
                return None
            
            name = result.get('full_name')
            logger.debug(f"[Surgical] Extracted name: '{name}', Title: '{result.get('debug_title')}', H1: '{result.get('debug_h1')}'")
            
            # Sanitize name
            if name:
                name = re.sub(r'^\(\d+\)\s*', '', name)
                name = re.sub(r'\s*\b(1st|2nd|3rd\+)\b\s*', '', name).strip()
            
            # Map experience
            exp_list = []
            for e in result.get('experience_raw', []):
                # Only add if it's not empty and doesn't look like noise
                if e.get('title') and len(e['title']) > 2:
                    exp_list.append(Experience(title=e['title'], company_name=e.get('company', '')))

            def parse_robust_int(txt):
                if not txt: return 0
                # v0.7.1 Robustness: Normalize input
                txt = txt.replace('\xa0', ' ').replace('\u00a0', ' ').lower().strip()
                
                # If multiple numbers, we want the LAST one for mutuals like "A, B and 224 others" (v0.4.1)
                if " and " in txt or " et " in txt or "other" in txt or "autre" in txt:
                    # v3.1.8 Robust Estimation: Handle both "X others" and "A and B"
                    m_other = re.search(r'([\d,.\s]+)\s+(?:other|autre|others|autres)', txt)
                    base_val = 0
                    if m_other:
                        base_val = int(re.sub(r'[^0-9]', '', m_other.group(1)) or 0)
                    
                    # Estimate name counts from the part before "and" or before "X others"
                    names_part = txt
                    if m_other:
                        names_part = txt[:m_other.start()].strip()
                    
                    # Split by common name separators
                    parts = re.split(r'\s+and\s+|\s+et\s+|,', names_part)
                    # Filter out noise and count meaningful tokens
                    name_count = len([p.strip() for p in parts if len(p.strip()) > 2 and not any(k in p.lower() for k in ['other', 'autre'])])
                    
                    if base_val > 0 or name_count > 0:
                        return base_val + name_count
                
                # Handle "309 mutual connections" or "309 en commun"
                # Look for the largest contiguous number
                nums = re.findall(r'([\d,.\s]+)', txt)
                if not nums:
                    # v3.2.0: If no digits found but it's a mutual/connection insight, 
                    # it's likely a single name like "Philippe Dewost". Return 1.
                    lower_txt = txt.lower()
                    is_insight = any(k in lower_txt for k in ['mutual', 'commun', 'contact', 'relation', 'shared'])
                    if is_insight or (len(txt) > 3 and len(txt) < 60): # Heuristic for single name
                        return 1
                    return 0
                
                best_val = 0
                for n_str in nums:
                    val_str = n_str.strip().replace(' ', '').replace(',', '').replace('.', '')
                    if not val_str: continue
                    try:
                        val = int(val_str)
                        if val > best_val: best_val = val
                    except: pass
                return best_val

            # v2.1.8: TRUTH ON PAGE ONLY. If not found, it's 0. No more stale carry-overs.
            f_count = 0 
            if result.get('followers_text'):
                logger.debug(f"[Surgical] Parsing followers from fresh text: '{result['followers_text']}'")
                f_count = parse_robust_int(result['followers_text'])

            # Parse mutual connections (v0.3.8)
            m_count = 0
            if result.get('mutual_text'):
                logger.debug(f"[Surgical] Parsing mutuals from fresh text: '{result['mutual_text']}'")
                m_count = parse_robust_int(result['mutual_text'])

            p = LinkedInProfile(
                full_name=name,
                current_role=result.get('current_role') or raw_stats.get('job_title'),
                company=result.get('company') or raw_stats.get('company'),
                summary=result.get('summary') or raw_stats.get('summary'),
                location=result.get('location') or raw_stats.get('location'),
                linkedin_url=linkedin_url,
                # v3.1.4/v3.1.8: Tier 4 Photo Fallback + Surgical Preference
                photo_url=photo_url if photo_url and (photo_url.startswith('http') or photo_url.startswith('data:')) else (result.get('photo_src') if result.get('photo_src') and result.get('photo_src').startswith('http') else None),
                followers_count=f_count,
                # v3.1.8: Prioritize SURGICAL ('connection_text') over LLM ('connections_raw')
                connections_count=parse_robust_int(result.get('connection_text')) or raw_stats.get('connections_count') or parse_robust_int(raw_stats.get('connections_raw')),
                connections_raw=result.get('connection_text') or raw_stats.get('connections_raw'),
                common_connections_count=m_count,
                connection_degree=parse_robust_int(result.get('degree_text')) or raw_stats.get('connection_degree'),
                mutual_groups=raw_stats.get('mutual_groups', []),
                # ...
                mutual_raw=result.get('mutual_text') or raw_stats.get('mutual_raw'),
                websites=contact_info.get('websites', []),
                emails=contact_info.get('emails', []),
                phones=contact_info.get('phones', []),
                birthday=contact_info.get('birthday'),
                connected_date=contact_info.get('connected_date'),
                experience=exp_list
            )
            # FORCE current date (v0.7.8 fix)
            p.timestamp = datetime.now().isoformat()[:10]
            self._sanitize_profile(p)

            # Populate Profile fields from surgery (v0.3.7)
            p.full_name = result.get('full_name') or p.full_name
            
            # v0.7.6: Strict Heuristic - take only the first meaningful line for role/company
            def clean_line(txt, name_to_skip=None):
                if not txt: return ""
                lines = [l.strip() for l in txt.split('\n') if l.strip()]
                noise = ["• 1st", "• 2nd", "• 3rd+", "1st", "2nd", "3rd+", "Message", "Following", "Follow"]
                for l in lines:
                    low = l.lower().strip()
                    if any(n.lower() == low for n in noise): continue
                    if name_to_skip and name_to_skip.lower() in low and len(low) < len(name_to_skip) + 5: continue
                    if "mutual connection" in low or "relation en commun" in low: continue
                    if " follower" in low or " abonné" in low: continue
                    
                    # Strip trailing degree badges
                    clean_l = re.sub(r'\s*[•-]?\s*\b(1st|2nd|3rd\+|1er|2e|3e)\b\s*$', '', l, flags=re.IGNORECASE).strip()
                    if clean_l: return clean_l
                return lines[0] if lines else ""

            p.current_role = clean_line(result.get('current_role') or raw_stats.get('job_title'), name_to_skip=p.full_name) or p.current_role
            p.summary = result.get('summary') or p.summary
            p.location = clean_line(result.get('location') or raw_stats.get('location')) or p.location
            p.company = clean_line(result.get('first_company') or raw_stats.get('company')) or p.company
            
            # Map connections from connection_text if any
            if result.get('connection_text') and not p.connections_count:
                # v3.2.1: Ensure connection_text is cleaned of follower counts if it was a combined string
                cleaned_conn_text = result['connection_text']
                if 'follower' in cleaned_conn_text.lower() or 'abonné' in cleaned_conn_text.lower():
                    # Attempt to isolate the connection part if it was combined
                    parts = cleaned_conn_text.split('•')
                    for part in parts:
                        if 'connection' in part.lower() or 'relation' in part.lower() or 'contact' in part.lower():
                            cleaned_conn_text = part.strip()
                            break
                    else: # If no connection part found, default to original but it's likely wrong
                        cleaned_conn_text = result['connection_text']

                p.connections_count = parse_robust_int(cleaned_conn_text)
                p.connections_raw = cleaned_conn_text.strip()

            # v1.6.0: Parse derived degree
            degree_str = str(result.get('degree_text', '')).lower()
            # Strict regex to avoid "1" matching inside "11" or other text
            # Strict regex to avoid "1" matching inside "11" or other text
            # v1.6.1: Improved for French support (2ème, 3ème)
            if re.search(r'\b2(?:nd|e|d|ème|eme)\b', degree_str, re.IGNORECASE): p.connection_degree = 2
            elif re.search(r'\b3(?:rd|e|d|ème|eme)\b', degree_str, re.IGNORECASE): p.connection_degree = 3
            elif re.search(r'\b1(?:st|er|ere|ère)\b', degree_str, re.IGNORECASE): p.connection_degree = 1
            
            # Check for sufficient identity (Name + Role or Name + Company)
            if p.full_name and (p.current_role or p.company):
                logger.info(f"Surgical Local Scrape successful for {p.full_name} (Role='{p.current_role}', Co='{p.company}')")
                return p
            else:
                logger.warning(f"Surgical Local Scrape found incomplete data for {p.full_name or 'Unknown'}: {result}")
                return p
        except Exception as e:
            logger.error(f"Surgical Local Scrape failed: {e}")
            return None

    async def _get_pruned_content(self, page) -> str:
        """Strips non-essential HTML tags to optimize LLM context."""
        try:
            content = await page.evaluate(r"""
                () => {
                    const toRemove = [
                        'script', 'style', 'nav', 'footer', 'header', 'iframe', 
                        'noscript', 'link', 'svg', 'button', 'form', 
                        '.artdeco-modal-overlay', '.global-nav', '.feed-shared-update-v2'
                    ];
                    const body = document.body.cloneNode(true);
                    toRemove.forEach(tag => {
                        Array.from(body.querySelectorAll(tag)).forEach(el => el.remove());
                    });
                    return body.innerText.split('\n')
                               .map(l => l.trim())
                               .filter(l => l.length > 0)
                               .join('\n');
                }
            """)
            return content
        except Exception as e:
            logger.warning(f"DOM Pruning failed: {e}")
            return await page.evaluate("() => document.body?.innerText || ''")


    async def _safe_generate_content(self, prompt: str, retry_count: int = 3) -> Optional[str]:
        """Calls Gemini with exponential backoff on 429 using new SDK."""
        for i in range(retry_count):
            try:
                # synchronous call in threads or just call it since it's fast
                # making it async wrapper for the rest of the code
                loop = asyncio.get_event_loop()
                response = await self.genai_client.ainvoke(prompt)
                content = response.content
                if isinstance(content, list):
                    content = " ".join([str(item) for item in content])
                return str(content)
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "quota" in err_str.lower():
                    # Try to find a suggested retry time in the error message
                    sleep_match = re.search(r'retry in (\d+\.?\d*)s', err_str)
                    wait_time = float(sleep_match.group(1)) if sleep_match else (i + 1) * 20
                    # Cap wait time to avoid hanging too long
                    wait_time = min(wait_time, 60)
                    logger.warning(f"Quota exceeded (429). Waiting {wait_time}s to avoid being stuck... (Attempt {i+1}/{retry_count})")
                    await asyncio.sleep(wait_time + 1)
                else:
                    logger.error(f"LLM Error: {e}")
                    raise e
        self.quota_exhausted = True
        return None

    async def check_auth(self) -> bool:
        """Direct check to ensure user is logged in. Cache result for 5 mins."""
        now = time.time()
        # v1.6.0: Randomized auth check interval for stealth
        import random
        # Base: 5 mins, Jitter: +/- 2 mins -> Range: 3-7 mins
        limit = 300 + random.uniform(-120, 120)
        
        if self._authenticated and (now - self._last_auth_check < limit):
            return True
            
        logger.info("Checking LinkedIn authentication state...")
        self._last_auth_check = now
        
        try:
            # v1.4.3: Lazy initialization
            if not self.vault_only:
                await self._setup_browser(headless=self._browser_headless)
            
            # Ensure browser is started (v0.1x fallback)
            if hasattr(self.browser, 'start'):
                await self.browser.start()
            
            # Standard navigation - ONLY if we are not already on a LinkedIn page (v1.2.4)
            try:
                page = await self.browser.get_current_page()
                cur_url = await page.get_url() if page else ""
                if "linkedin.com" not in cur_url:
                    logger.info("Navigating to LinkedIn home...")
                    await self.browser.navigate_to("https://www.linkedin.com/feed/")
            except:
                pass 
            
            page = await self.browser.get_current_page()
            if not page:
                page = await self.browser.new_page("https://www.linkedin.com/feed/")

            # Give it more time for dynamic content, but check periodically
            # v1.2.5: Reduced polling to avoid fighting user during login
            await asyncio.sleep(2)
            url = await page.get_url()
            title = await page.evaluate("() => document.title")
            logger.debug(f"Auth check current state: {url} - {title}")
            
            content = await page.evaluate("() => document.body?.innerText || ''")
            
            # v1.2.8: Handle Cookie Walls
            if "accepter" in content.lower() or "cookies" in content.lower():
                logger.info("Cookie wall / Splash detected. Attempting auto-accept...")
                await page.evaluate("""() => {
                    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                    const accept = buttons.find(b => b.innerText.match(/accepter/i) || b.innerText.match(/accept/i));
                    if (accept) accept.click();
                }""")
                await asyncio.sleep(2)
                content = await page.evaluate("() => document.body?.innerText || ''")
                title = await page.evaluate("() => document.title")

            logger.info(f"Auth check status: {url} - {title}")
            snippet = content[:200].replace('\n', ' ')
            logger.debug(f"Content snippet: {snippet}")

            logger.info(f"Auth check final: {url} - {title}")
            
            # Text markers for logged-in state (v1.2.3: Added French support)
            markers = [
                "Home", "My Network", "Jobs", "Messaging", "Notifications", "Start a post", "Feed", "Sign Out",
                "Accueil", "Réseau", "Emplois", "Messagerie", "Commencer un post", "Fil d’actualité", "Déconnexion",
                "Search", "Recherche", "Messaging", "Messagerie"
            ]
            
            # v1.2.10: High-fidelity auth check
            is_authed = any(m in title for m in ["Feed", "Messaging", "Notifications", "Fil d’actualité", "Messagerie", "Search", "Recherche"]) or \
                        any(m in content for m in markers) or \
                        ("/in/" in url and "linkedin.com" in url) or \
                        ("/search/" in url and "linkedin.com" in url)
            
            # If we are on any valid LinkedIn page that isn't a login/uas page, we are fine
            if "linkedin.com" in url and "login" not in url.lower() and "checkpoint" not in url.lower() and "uas/" not in url.lower():
                is_authed = True

            if "Security Check" in content or "quick security check" in content.lower() or "solve this puzzle" in content.lower():
                logger.error("🛑 LinkedIn Security Check (CAPTCHA) detected! Please solve it in the opened Chrome window.")
                await self._show_macos_dialog("LinkedIn Security Check detected.\n\nPlease solve the CAPTCHA in the Chrome window and click Resume.", "Security Check", ["Resume"])
                return await self.check_auth() # Recurse once solved

            if is_authed:
                logger.info("LinkedIn auto-authenticated successfully.")
                logger.info("🔐 LINKEDIN LOGIN: Authentication verified.")
                self._authenticated = True
                return True
            
            # v1.2.7: Use a loop instead of recursion to be more stable
            while not is_authed:
                if "login" in url.lower() or "checkpoint" in url.lower() or "uas/login" in url:
                    logger.warning("Redirection to login/checkpoint detected.")
                    logger.info("LinkedIn needs manual authentication.")
                
                await self._show_macos_dialog("LinkedIn needs manual authentication.\n\n1. Sign in in the opened Chrome window.\n2. Verify you are on the Home page.\n3. Click OK HERE ONLY AFTER logging in.", buttons=["OK"])
                await asyncio.sleep(15) # Longer settle
                
                # Refresh state for next loop iteration
                page = await self.browser.get_current_page()
                url = await page.get_url()
                title = await page.evaluate("() => document.title")
                content = await page.evaluate("() => document.body?.innerText || ''")
                is_authed = any(m in title for m in markers) or \
                            any(m in content for m in markers) or \
                            ("linkedin.com" in url and "login" not in url.lower() and "checkpoint" not in url.lower())
            
            # v1.2.9: identify owner photo for blacklisting (Philippe leak prevention)
            if "linkedin.com/feed" in url or "linkedin.com/in/" in url:
                await self._identify_owner_photo(page)
            
            self._authenticated = True
            return True
            
        except Exception as e:
            logger.error(f"Auth check failed: {e}")
            return False

    async def _identify_owner_photo(self, page):
        """Identifies the logged-in user's photo to blacklist it from sniffer."""
        if self._owner_photo_url: return
        
        try:
            # The "Me" icon in top nav usually has the owner's photo
            url = await page.evaluate(r"""() => {
                const img = document.querySelector('img.global-nav__me-photo') || 
                            document.querySelector('.global-nav__me-photo img') ||
                            document.querySelector('img[alt*="Photo de profil"], img[alt*="Profile photo"]');
                return img ? img.src : null;
            }""")
            if url:
                self._owner_photo_url = url
                logger.info(f"✅ Identified Owner Photo URL: {url[:60]}...")
        except Exception as e:
            logger.debug(f"Failed to identify owner photo: {e}")

        # Manual Fallback
        res = self._show_macos_dialog(
            "LSAMC I couldn't confirm you are logged in to LinkedIn.\\n\\nPlease ensure you are logged in in the opened Chrome window.\\n\\nClick 'Resume' when ready.",
            "LinkedIn Authentication",
            ["Cancel", "Resume"]
        )
        if "Cancel" in res:
            raise InterruptedError("User cancelled the sync during auth check.")
        
        self._authenticated = True
        return True

    async def _extract_results_with_context(self, page) -> List[Dict[str, Any]]:
        """Extracts search results with comprehensive metadata (v3.5.0)."""
        raw_results = await page.evaluate(r"""
            () => {
                const items = Array.from(document.querySelectorAll('.reusable-search__result-container, .entity-result, .search-result__info'));
                const list = items.map(el => {
                    const link = el.querySelector('a[href*="/in/"]');
                    const title = el.querySelector('.entity-result__title-text, .name')?.innerText || '';
                    const snippet = el.querySelector('.entity-result__primary-subtitle, .subline-level-1')?.innerText || '';
                    
                    const insight = el.querySelector('.entity-result__simple-insight, .entity-result__insights')?.innerText || '';
                    const badge = el.querySelector('.entity-result__badge')?.innerText || ''; 
                    
                    return {
                        href: link ? link.href.split('?')[0] : null,
                        info: `${title} - ${snippet} - ${badge} - ${insight}`.replace(/\s+/g, ' ').trim(),
                        insight: insight,
                        is_first: badge.includes('1st') || badge.includes('1er')
                    };
                }).filter(r => r.href && r.href.includes('/in/'));
                
                if (list.length === 0) {
                    return Array.from(document.querySelectorAll('a[href*="/in/"]'))
                        .map(a => {
                             const el = a.closest('.entity-result, li, section');
                             const insight = el?.querySelector('.entity-result__simple-insight, .entity-result__insights')?.innerText || '';
                             return { href: a.href.split('?')[0], info: a.innerText.trim(), insight: insight };
                        })
                        .filter(r => r.info.length > 2 && !r.href.includes('/in/ACoA'))
                        .slice(0, 10);
                }
                return list;
            }
        """)
        if isinstance(raw_results, str):
            try: return json.loads(raw_results)
            except: return []
        return raw_results or []

    async def find_linkedin_profile(self, name: str, companies: List[str] = [], role: str = "") -> Any:
        """Searches LinkedIn and picks/clicks the best result."""
        import urllib.parse
        # v1.3.6: Strip title prefixes EXCEPT Dr (Batch 9 feedback) - Remove: M, Me, Mr, Mrs, Mme, Mlle, Herr, M&Me
        search_name = re.sub(r'^\s*(M&Me|Herr|M|Me|Mr|Mrs|Mme|Mlle|M\.|Me\.|Mr\.|Mrs\.|Mme\.|Mlle\.)\s+', '', name, flags=re.IGNORECASE)
        # Fallback if the name is just the prefix (unlikely but safe)
        if not search_name.strip(): search_name = name
        encoded_name = urllib.parse.quote(search_name.strip())
        # Explicitly filter for 1st degree connections (&network=%5B%22F%22%5D)
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_name}&network=%5B%22F%22%5D"
        forced_tier_2 = False
        
        logger.info(f"Navigating to LinkedIn search for: {name}...")
        await asyncio.sleep(2) # Pacing (v0.3.9)
        for attempt in range(3):
            try:
                await self.browser.navigate_to(search_url)
                break
            except Exception as e:
                if attempt == 2:
                    logger.warning(f"Final search navigation attempt failed ({e})")
                else:
                    logger.debug(f"Search navigation timed out ({e}), retrying {attempt+1}/3...")
                    await asyncio.sleep(2)
        
        page = await self.browser.get_current_page()
        if not page:
            logger.error("Could not get browser page after navigation.")
            return None

        # Wait for either results OR security check
        for _ in range(5):
            # v1.4.1: Auto-detection for browser crashes
            await self._check_and_fix_crashed_page()
            
            content = await page.evaluate("() => document.body?.innerText || ''")
            if "Security Check" in content or "quick security check" in content.lower():
                logger.error("🛑 CAPTCHA detected during search navigation.")
                await self.check_auth() # Trigger solve dialog
            
            is_loaded = any(k in content.lower() for k in ["results", "résultats", "people", "items", "personnes", "profils"])
            no_results = any(k in content.lower() for k in ["no results", "aucun résultat", "couldn't find any results", "n'avons trouvé aucun résultat"])
            
            if is_loaded or no_results:
                if no_results and "&network=" in search_url:
                    logger.info(f"No 1st degree results for {name}, trying broad search (2nd/3rd degree)...")
                    search_url = search_url.replace("&network=%5B%22F%22%5D", "")
                    forced_tier_2 = True
                    await self.browser.navigate_to(search_url)
                    # Reset check loop by continuing the outer range(5) - simple but works if we sleep
                    continue
                break
            
            try: await page.evaluate("window.scrollTo(0, 500);")
            except: pass
            logger.debug("Page still loading search results...")

        # v3.5.0: REFINED SEARCH (Dynamic escalation for ambiguous names) - Part 1: Initial Discovery
        results = await self._extract_results_with_context(page)

        if not results:
            logger.warning("No search results found on page.")
            return None

        # --- ZERO-LLM HEURISTIC MATCHING (v0.7.5 Policy) ---
        import unicodedata
        def norm(s):
            return unicodedata.normalize('NFC', s.lower().strip())
            
        # v0.7.6: Strip title prefixes (M., Me, Mr, etc) that might pollute the search/match score
        clean_name = re.sub(r'^\s*(M&Me|Herr|M|Me|Mr|Dr|Mrs|Mme|Mlle|M\.|Me\.|Mr\.|Mrs\.|Mme\.|Mlle\.)\s+', '', name, flags=re.IGNORECASE)
        target_name = norm(clean_name)
        name_parts = [norm(p) for p in re.findall(r'[^\W_]+', clean_name) if len(p) > 2]
        
        def calculate_score(r, is_first, current_results, target_name, companies, role):
            r_info = norm(r.get('info', ''))
            score = 0
            
            # Name match (Primary)
            if target_name in r_info: 
                score += 50
                if target_name == r_info.split('-')[0].strip():
                    score += 20
            
            if name_parts and all(p in r_info for p in name_parts):
                score += 20
                
            # Company match (Strong Signal)
            score_comp = 0
            for comp in companies:
                if comp and norm(comp) in r_info:
                    score_comp = max(score_comp, 45) # Increased from 40
            score += score_comp
            
            # Role match (v3.5.0)
            if role and norm(role) in r_info:
                score += 30
            
            # 2nd Degree connects (Increased from 25)
            if "2nd" in r_info or "2e" in r_info:
                score += 35
                
            # Mutual Connections (Massive Signal - Increased from 45/40)
            if "mutual" in r_info or ("relation" in r_info and "commun" in r_info):
                score += 55
                
            # Mutual Experience / Highlights
            if "both worked" in r_info or "travaillé ensemble" in r_info or "worked at" in r_info.split(' - ')[-1]:
                score += 65
                
            return score

        def evaluate_candidates(results, target_name, companies, role):
            first_degree_results = []
            other_results = []
            
            for r in results:
                r_info = norm(r.get('info', ''))
                is_first = r.get('is_first', False) or "1st" in r_info or "1er" in r_info
                score = calculate_score(r, is_first, results, target_name, companies, role)
                
                logger.debug(f"Candidate: {r['href']} | Score: {score} | Info: {r['info'][:80]}...")
                
                if score >= 50:
                    cand = (score, r['href'], r['info'], r.get('insight', ''))
                    if is_first:
                        first_degree_results.append(cand)
                    else:
                        other_results.append(cand)
            return first_degree_results, other_results

        first_degree_results, other_results = evaluate_candidates(results, target_name, companies, role)

        # v3.5.1: REFINED SEARCH (Part 2: Tie-Breaker escalation)
        if not first_degree_results and len(other_results) > 1 and (role or companies):
            # If we have multiple 2nd/3rd degree matches and they are close in score
            other_results = sorted(other_results, key=lambda x: x[0], reverse=True)
            if other_results[0][0] - other_results[1][0] < 15:
                logger.info(f"Ambiguity Escalation: Found multiple close results. Triggering Refined Search with context...")
                context_query = f"{clean_name} {role or (companies[0] if companies else '')}"
                # Recurse with refined query
                # Actually, don't recurse infinitely, just do ONE more try
                refined_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(context_query)}"
                await self.browser.navigate_to(refined_url)
                await asyncio.sleep(3)
                refined_results = await self._extract_results_with_context(page)
                if refined_results:
                    first_degree_results, other_results = evaluate_candidates(refined_results, target_name, companies, role)
        
        # POLICY ENFORCEMENT (v0.7.5):
        # If any 1st degree matches exist, discard all 2nd/3rd degree matches
        if first_degree_results:
            logger.info(f"Policy: {len(first_degree_results)} 1st-degree matches found. Ignoring {len(other_results)} other leads.")
            best_candidates = sorted(first_degree_results, key=lambda x: x[0], reverse=True)
            
            # DISAMBIGUATION: If multiple 1st degree, use company tie-breaker
            if len(best_candidates) > 1:
                company_leads = [c for c in best_candidates if any(norm(comp) in norm(c[2]) for comp in companies)]
                if len(company_leads) == 1:
                    logger.info(f"Disambiguation: Found unique company match for 1st-degree candidate.")
                    best_candidates = company_leads
                elif len(company_leads) > 1:
                    best_candidates = company_leads # Narrowed but still ambiguous
            
            # v1.3.1: 2nd Degree Tie-Breaker
            # If we still have multiple candidates (regardless of degree), and only one is 2nd degree, boost it.
            if len(best_candidates) > 1:
                second_degree_leads = [c for c in best_candidates if "2nd" in norm(c[2]) or "2e" in norm(c[2])]
                if len(second_degree_leads) == 1:
                    # Give it a virtual 15 point boost to break the gap threshold in next step
                    winner = list(second_degree_leads[0])
                    winner[0] += 15
                    best_candidates[best_candidates.index(second_degree_leads[0])] = tuple(winner)
                    logger.info(f"Disambiguation: Boosting unique 2nd-degree candidate {winner[1]} by +15 pts.")
        else:
            best_candidates = sorted(other_results, key=lambda x: x[0], reverse=True)
            if best_candidates:
                logger.info(f"No 1st-degree matches. Suggesting {len(best_candidates)} lower-degree candidates.")
        
        # If there's a clear winner (>15 point gap) or only one candidate
        if best_candidates:
            winner = best_candidates[0]
            if len(best_candidates) == 1 or (winner[0] >= best_candidates[1][0] + 15):
                score, href, info, insight = winner
                is_first = "1st" in norm(info) or "1er" in norm(info)
                logger.info(f"Local Heuristic Select: '{info}' with score {score}% (Gap: {score - (best_candidates[1][0] if len(best_candidates) > 1 else 0)})")
                
                # Pre-parse mutuals from both info and insight (v0.3.9)
                mutual_count = 0
                search_text = (info + " " + insight).lower().replace('\xa0', ' ').replace('\u00a0', ' ')
                
                def parse_robust_int(txt):
                    if not txt: return 0
                    txt = txt.replace('\xa0', ' ').replace('\u00a0', ' ').lower().strip()
                    # v2.1.2: Support '500+' or '1,234+' formats
                    has_plus = '+' in txt
                    
                    # Focus on the FIRST actual number found, ignoring leading dots/whitespace
                    m = re.search(r'([\d,.\s]*\d)\s*([KkMm])?', txt)
                    if not m: return 500 if has_plus else 0
                    
                    val_str = m.group(1).replace('\xa0', '').replace(' ', '')
                    val_str = re.sub(r'^[^\d]+', '', val_str)
                    unit = m.group(2).lower() if m.group(2) else ""
                    
                    try:
                        if unit == 'k':
                            num = float(val_str.replace(',', '.'))
                            return int(num * 1000)
                        if unit == 'm':
                            num = float(val_str.replace(',', '.'))
                            return int(num * 1000000)
                        
                        # Plain digits
                        clean_num = re.sub(r'[^0-9]', '', val_str)
                        return int(clean_num) if clean_num else (500 if has_plus else 0)
                    except:
                        return 500 if has_plus else 0

                # Mutuals match - scan all lines for engagement (v0.3.9 fix)
                lines = search_text.split('\n')
                engagement_line = ""
                for l in reversed(lines):
                    if "mutual" in l.lower() or "relation" in l.lower() or "commun" in l.lower():
                        engagement_line = l
                        break
                
                if not engagement_line and lines:
                    engagement_line = lines[-1]

                # Fix: Define regex matches before checking them
                # Matches: "John, Jane and 15 other mutual connections"
                m_match = re.search(r'([\w\s,]+)\s+(?:and|et)\s+([\d\s.,Kk]+)\s+(?:other\s+)?(?:mutual|connections|relations|relations en commun)', engagement_line, re.IGNORECASE)
                # Matches: "15 mutual connections"
                m_total = re.search(r'([\d\s.,Kk]+)\s+(?:mutual|connections|relations|relations en commun)', engagement_line, re.IGNORECASE)

                if m_total and not m_match:
                    # Clean total found (e.g. "81 mutual connections")
                    mutual_count = parse_robust_int(m_total.group(1))
                    logger.info(f"Mutual Count (Total Header): {mutual_count} based on '{m_total.group(0)}'")
                elif m_match:
                    names_part = m_match.group(1)
                    others = parse_robust_int(m_match.group(2))
                    
                    if len(names_part) > 2:
                        # v2.1.6: Robust segmenting. Names can be separated by comma, 'and', 'et', '&', or '|'
                        names_clean = names_part.strip().rstrip(',')
                        # Split by any of the common separators
                        segments = [s.strip() for s in re.split(r'[,|&]|\band\b|\bet\b', names_clean, flags=re.IGNORECASE) if len(s.strip()) > 1]
                        name_count = len(segments)
                        logger.info(f"Mutual Count (Split): {others} (others) + {name_count} (names: {segments}) = {others + name_count}")
                    else: 
                        name_count = 0
                        logger.info(f"Mutual Count (Single): {others} (others) + {name_count} (names) = {others + name_count}")
                    mutual_count = others + name_count
                else:
                    m2 = re.search(r'([\d,.\s]+)\s+(?:mutual|relation|commun)', engagement_line)
                    if m2: 
                        mutual_count = parse_robust_int(m2.group(1))
                        logger.info(f"Mutual Count (Fallback): {mutual_count} based on '{m2.group(0)}'")
                
                # Followers match (v0.3.9)
                followers_count = 0
                f_match = re.search(r'([\d,.\s]*[KkMm]?)\s+(?:follower|abonné)', search_text)
                if f_match:
                    followers_count = parse_robust_int(f_match.group(1))
                
                # Connections count (v0.4.0)
                connections_raw = ""
                conn_match = re.search(r'(\d+[+,.\s]*\d*\s*(?:relation|connection|contact|abonn))', search_text)
                if conn_match:
                    connections_raw = conn_match.group(1).strip()
                
                # Mutual Groups (v0.4.0)
                mutual_groups = []
                g_match = re.search(r'(?:mutual group|groupe en commun|groupes en commun):\s*(.*)', search_text)
                if g_match:
                    mutual_groups = [g.strip() for g in g_match.group(1).split(',')]
                elif "mutual group" in search_text or "groupe en commun" in search_text:
                    # Generic flag if count not found
                    mutual_groups = ["Yes (Found in snippet)"]

                # Parse Job/Company from info snippet (v0.3.6)
                # Pattern: "Name - Title at Company" or "Title at Company"
                job_title = ""
                company_name = ""
                
                def clean_title(raw_title, profile_name):
                    # v3.1.5: If title starts with the name, strip it
                    if profile_name and raw_title.lower().startswith(profile_name.lower()):
                        # Look for common separators after the name
                        remainder = raw_title[len(profile_name):].strip()
                        if remainder.startswith('-') or remainder.startswith('|') or remainder.startswith('·'):
                            return remainder[1:].strip()
                    # Also handle case where it's "Name - Title" and we split by " - "
                    if " - " in raw_title:
                        parts = raw_title.split(" - ")
                        if profile_name and parts[0].strip().lower() == profile_name.lower():
                            return " - ".join(parts[1:]).strip()
                    return raw_title.strip()

                if info and " at " in info:
                    parts = info.split(" at ")
                    raw_job = parts[0].strip()
                    job_title = clean_title(raw_job, name)
                    company_name = parts[1].split(" - ")[0].strip()
                elif info and " | " in info:
                    parts = info.split(" | ")
                    raw_job = parts[0].strip()
                    job_title = clean_title(raw_job, name)
                    company_name = parts[1].split(" - ")[0].strip()

                final_url = await self._click_and_verify(page, href)
                return {
                    "url": final_url, 
                    "mutual": mutual_count, 
                    "followers": followers_count,
                    "connections_raw": connections_raw,
                    "mutual_groups": mutual_groups,
                    "insight": insight,
                    "job_title": job_title,
                    "company": company_name,
                    "is_first": is_first and not forced_tier_2
                }
            else:
                # Ambiguity detected
                logger.warning(f"Ambiguity detected for {name}. Flagging for review.")
                relevant = [f"{c[2]}|#|{c[1]}" for c in best_candidates[:3]]
                return f"AMBIGUOUS:{'|OR|'.join(relevant)}"
        
        # Fallback to LLM
        if self.quota_exhausted:
            logger.warning(f"Quota exhausted. Skipping LLM search fallback for {name}.")
            return None

        prompt = f"LinkedIn search results for '{name}'. Pick the most likely profile URL.\n\nResults:\n"
        for r in results[:8]:
            prompt += f"- {r.get('info', 'No Info')}: {r.get('href', 'No URL')}\n"
        prompt += "\nReturn ONLY the chosen URL, or 'NONE' if no match."

        try:
            raw_res = await self._safe_generate_content(prompt)
            if not raw_res: return None
            match = re.search(r'https?://www\.linkedin\.com/in/[a-zA-Z0-9_-]+/?', raw_res)
            if not match:
                return "NOT_FOUND" if "NONE" in raw_res.upper() else None
            
            final_url = await self._click_and_verify(page, match.group(0))
            return {"url": final_url}
        except Exception as e:
            logger.error(f"Error in find_linkedin_profile processing: {e}")
            return "ERROR_TECHNICAL"

    def _extract_companies_from_notes(self, note: str) -> List[str]:
        """
        Heuristic: Extract potential company names from notes.
        v2.0: Advanced Regex to capture 'Time at Company', 'Role at Company', 'Ex-Company', etc.
        """
        if not note: return []
        companies = set()
        
        # 1. Email Domain Extraction (Legacy)
        # Pattern for emails: something@company.domain
        emails = re.findall(r'[\w\.-]+@([\w\.-]+)', note)
        for domain in emails:
            # Strip common suffixes
            parts = domain.lower().split('.')
            base = parts[0]
            if len(parts) > 1 and base not in ["gmail", "outlook", "hotmail", "yahoo", "wanadoo", "orange", "free", "bbox", "me", "icloud", "protonmail"]:
                companies.add(base)
        
        # 2. Text Pattern Extraction (New v4.9.1)
        # Looking for: "at [Company]", "chez [Company]", "Founder of [Company]", "Ex-[Company]"
        # We need to be careful not to capture common words.
        
        # Normalize note for regex
        # Replace non-breaking spaces
        clean_note = note.replace('\xa0', ' ').replace('\u00a0', ' ')
        
        # Regex patterns
        # Captures "Role at Company" or "at Company"
        # We assume Company name is Capitalized or standard
        # Stop at newline, comma, or common delimiters
        patterns = [
            r"\b(?:at|chez|@)\s+([A-Z][\w\s&]+?)(?=\s*(?:\n|,|\.|!|\?|\)|$|—|-))", # "at Company Name"
            r"\b(?:Founder|Co-founder|CEO|CTO|VP|Director|Manager|Head)\s+(?:of|at)\s+([A-Z][\w\s&]+?)(?=\s*(?:\n|,|\.|!|\?|\)|$))", # "CEO of Company"
            r"\b(?:Ex-|Former\s+|Previously\s+at\s+)([A-Z][\w\s&]+?)(?=\s*(?:\n|,|\.|!|\?|\)|$))", # "Ex-Company"
        ]
        
        for p in patterns:
            matches = re.finditer(p, clean_note, re.MULTILINE)
            for m in matches:
                candidate = m.group(1).strip()
                # Validation: Must be > 2 chars, not a common stopword
                if len(candidate) > 2 and candidate.lower() not in ["home", "work", "email", "mobile", "cell", "phone", "contact", "unknown", "none", "n/a"]:
                     # v5.0.0: Check Knowledge Base
                     if self.kb.is_known(candidate):
                         logger.info(f"🏢 KB Match: Found validated company in notes -> {candidate}")
                     companies.add(candidate)

        return list(companies)

    def _normalize_date(self, date_str: Optional[str]) -> Optional[str]:
        """Convert various date formats (Jan 6, 2017 or 6 janv. 2017) to ISO YYYY-MM-DD."""
        if not date_str: return None
        date_str = date_str.strip()
        
        # Already ISO?
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str
            
        try:
            # Try English format
            from dateutil import parser
            dt = parser.parse(date_str)
            return dt.strftime('%Y-%m-%d')
        except:
            # Try manual mapping for common French months if dateutil fails
            months_fr = {
                'janv': 'Jan', 'févr': 'Feb', 'mars': 'Mar', 'avr': 'Apr', 'mai': 'May', 'juin': 'Jun',
                'juil': 'Jul', 'août': 'Aug', 'sept': 'Sep', 'oct': 'Oct', 'nov': 'Nov', 'déc': 'Dec'
            }
            tmp = date_str.lower()
            for fr, en in months_fr.items():
                if fr in tmp:
                    tmp = tmp.replace(fr, en)
                    break
            try:
                from dateutil import parser
                dt = parser.parse(tmp)
                return dt.strftime('%Y-%m-%d')
            except:
                return date_str

    def _sanitize_profile(self, profile: LinkedInProfile):
        """Orchestrates all v0.2.0 sanitization and inference logic."""
        # 1. Name Splitting & Suffixes
        name = profile.full_name
        # Clean degree icons and notification counts
        name = re.sub(r'^\(\d+\)\s*', '', name)
        name = re.sub(r'\s*\b(1st|2nd|3rd\+)\b\s*', '', name).strip()
        
        suffixes = ['PhD', 'MBA', 'M.Sc', 'B.Sc', 'CFA', 'PMP', 'MD', 'Eng', 'JD', 'DDS']
        found_suffixes = []
        for s in suffixes:
            pattern = re.compile(r'\b' + s.replace('.', r'\.') + r'\b', re.IGNORECASE)
            if pattern.search(name):
                found_suffixes.append(s)
                name = pattern.sub('', name).strip()
        
        name = re.sub(r'[,\s]+$', '', name) # trailing comma/space
        name = re.sub(r'\s+', ' ', name).strip()
        
        profile.suffix = ", ".join(found_suffixes) if found_suffixes else None
        parts = name.split()
        if len(parts) >= 2:
            profile.first_name = parts[0]
            profile.last_name = " ".join(parts[1:])
        else:
            profile.first_name = name
            profile.last_name = ""

        # 2. Location Inference
        if profile.location:
            loc_parts = [pt.strip() for pt in profile.location.split(',')]
            if len(loc_parts) >= 2:
                profile.city = loc_parts[0]
                profile.country = loc_parts[-1]

        # 3. Role/Company Fallback (from headline)
        if not profile.current_role or not profile.company:
            # Try to grab headline if available (often stored in current_role initially)
            headline = profile.current_role or ""
            if " at " in headline:
                p = headline.split(" at ")
                profile.current_role = p[0].strip()
                profile.company = p[1].strip()
            elif " @ " in headline:
                p = headline.split(" @ ")
                profile.current_role = p[0].strip()
                profile.company = p[1].strip()

        # 4. Connection Date Parsing (Local Heuristic)
        if profile.connected_date:
            profile.connected_date = self._parse_linkedin_date(profile.connected_date)

        # 5. Email Blocklist (v0.7.8): Prevent leakage of scraper's identity
        email_blocklist = ['p@phileos.eu']
        # Determine if this is the user's own profile based on URL handle
        is_user_profile = False
        if profile.linkedin_url:
            handle = profile.linkedin_url.split('/in/')[-1].strip('/').split('?')[0]
            if handle in ['pdewost', 'philippedewost']:
                is_user_profile = True
                
        if not is_user_profile and profile.emails:
            original_count = len(profile.emails)
            profile.emails = [e for e in profile.emails if e.lower() not in email_blocklist]
            if len(profile.emails) < original_count:
                logger.info(f"Filtered out {original_count - len(profile.emails)} blocked email(s) from {profile.full_name}")

        logger.info(f"Sanitized Profile: {profile.first_name} {profile.last_name} ({profile.suffix or 'No Suffix'})")

    def _check_vault(self, contact_id: str) -> Optional[Dict[str, Any]]:
        """
        Checks the SPOT vault for a contact.
        Returns a dict with 'profile', 'photo_path', 'needs_refresh' if found, else None.
        """
        if not os.path.exists(self.vault_root):
            return None

        # 1. Search for contact_id in scavenger_meta.json across all vault subfolders
        # Efficiency note: In a production system, we'd have an index.json in vault root.
        # For now, we crawl the subdirs.
        target_dir = None
        scavenger_meta = None
        
        for entry in os.scandir(self.vault_root):
            if entry.is_dir():
                meta_path = os.path.join(entry.path, "scavenger_meta.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r') as f:
                            meta = json.load(f)
                            if meta.get('contact_id') == contact_id:
                                target_dir = entry.path
                                scavenger_meta = meta
                                break
                    except: continue
        
        if not target_dir or not scavenger_meta:
            return None

        # 2. Check Data
        profile_path = os.path.join(target_dir, "master_profile.json")
        if not os.path.exists(profile_path):
            return None
            
        try:
            with open(profile_path, 'r') as f:
                profile_data = json.load(f)
                
            # 3. Apply Policy
            # Staleness: 30 days
            from datetime import datetime, timedelta
            scavenged_at = scavenger_meta.get("scavenged_at", "1970-01-01")
            try:
                scavenged_dt = datetime.fromisoformat(scavenged_at)
            except:
                scavenged_dt = datetime(1970, 1, 1)
                
            is_stale = (datetime.now() - scavenged_dt) > timedelta(days=30)
            retry_already_done = scavenger_meta.get("retry_performed", False)
            needs_photo_retry = scavenger_meta.get("needs_hi_res_retry", False) and not retry_already_done
            
            # Check for photo existence
            raw_photo_path = os.path.join(target_dir, "linkedin-raw.jpg")
            heic_photo_path = os.path.join(target_dir, "linkedin.heic")
            
            # Prefer HEIC if available for bridge consumption
            final_photo_path = None
            if os.path.exists(heic_photo_path):
                final_photo_path = heic_photo_path
            elif os.path.exists(raw_photo_path):
                # If only raw exists, we'll need to re-optimize it during audit
                # But for the bridge, optimized is better.
                # Optimization logic is usually in sync_profile.
                final_photo_path = raw_photo_path

            return {
                "profile": LinkedInProfile(**profile_data),
                "photo_path": final_photo_path,
                "raw_photo_path": raw_photo_path if os.path.exists(raw_photo_path) else None,
                "is_stale": is_stale,
                "needs_photo_retry": needs_photo_retry,
                "vault_path": target_dir,
                "photo_res": scavenger_meta.get("photo_res", "UNKNOWN")
            }
            
        except Exception as e:
            logger.warning(f"Error reading vault for {contact_id}: {e}")
            return None

    def _parse_linkedin_date(self, raw_date: str) -> str:
        """Parses En/Fr dates into ISO YYYY-MM-DD based on local regex."""
        if not raw_date: return ""
        
        # Clean common garbage/prefixes
        clean = re.sub(r'^(Connected|since|Relation|depuis|le|on|le)\s*', '', str(raw_date), flags=re.IGNORECASE).strip()
        
        # Comprehensive mapping for EN and FR month signatures
        months_map = {
            'jan': '01', 'janv': '01', 'january': '01', 'janvier': '01',
            'feb': '02', 'fév': '02', 'february': '02', 'février': '02',
            'mar': '03', 'mars': '03', 'march': '03',
            'apr': '04', 'avr': '04', 'april': '04', 'avril': '04',
            'may': '05', 'mai': '05',
            'jun': '06', 'juin': '06', 'june': '06',
            'jul': '07', 'juil': '07', 'july': '07', 'juillet': '07',
            'aug': '08', 'août': '08', 'august': '08', 'août': '08',
            'sep': '09', 'sept': '09', 'september': '09', 'septembre': '09',
            'oct': '10', 'october': '10', 'octobre': '10',
            'nov': '11', 'november': '11', 'novembre': '11',
            'dec': '12', 'déc': '12', 'december': '12', 'décembre': '12'
        }

        # Pattern 1: Day Month Year (12 Jan 2024)
        match1 = re.search(r'(\d{1,2})\s+([a-zA-Záûé]+)\.?\s+(\d{4})', clean)
        # Pattern 2: Month Day, Year (Jan 12, 2024)
        match2 = re.search(r'([a-zA-Záûé]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})', clean)
        # Pattern 3: Month Year (Jan 2024)
        match3 = re.search(r'([a-zA-Záûé]+)\.?\s+(\d{4})', clean)
        
        m = match1 or match2 or match3
        if m:
            if match1:
                day, mon_text, year = m.groups()
            elif match2:
                mon_text, day, year = m.groups()
            else:
                mon_text, year = m.groups()
                day = "01"
            
            mon_key = mon_text.lower().rstrip('.')
            month = months_map.get(mon_key) or months_map.get(mon_key[:3])
            
            if month:
                return f"{year}-{month}-{int(day):02d}"
                
        return raw_date # Preservation is better than total failure
    async def _click_and_verify(self, page, final_url: str) -> Optional[str]:
        """Heuristically clicks or navigates to a profile."""
        logger.info(f"Target URL: {final_url}. Attempting to navigate...")
        slug = final_url.split('/in/')[1].strip('/')
        success = await page.evaluate(rf"""
            (slug) => {{
                const links = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                const target = links.find(a => a.href.includes('/in/' + slug));
                if (target) {{
                    target.scrollIntoView();
                    target.click();
                    return true;
                }}
                return false;
            }}
        """, slug)
        
        if success:
            logger.info("Successfully clicked the result.")
            await asyncio.sleep(4)
            try:
                await page.wait_for_selector('.pv-top-card', timeout=5000)
            except: pass
            return await page.get_url()
        else:
            logger.info("Click failed or link not found in DOM, navigating directly.")
            await self.browser.navigate_to(final_url)
            return final_url

    async def sync_group(self, group_name: str, limit: Optional[int] = None, offset: int = 0, reverse: bool = False, last: Optional[int] = None, force: bool = False):
        """ Processes a specific macOS Contacts group. """
        res = self.bridge.list_group_contacts(group_name)
        if not res["success"]:
            logger.error(f"Failed to list group '{group_name}': {res.get('error')}")
            return
            
        # v1.6.1: Force Alphabetical Sort to ensure stable offsets
        res["matches"].sort(key=lambda x: x.get('name', '').lower())
        
        self.group = group_name
        return await self.sync_batch(res["matches"], f"group '{group_name}'", limit=limit, offset=offset, reverse=reverse, last=last, force=force)

    async def sync_selection(self, limit: Optional[int] = None, offset: int = 0, reverse: bool = False, last: Optional[int] = None):
        """Syncs all contacts currently selected in the macOS Contacts app."""
        logger.info("Starting batch sync for current selection")
        res = self.bridge.get_selection()
        if not res["success"]:
            logger.error(res["error"])
            return
            
        return await self.sync_batch(res["matches"], "current selection", limit=limit, offset=offset, reverse=reverse, last=last)

    async def sync_batch(self, contacts: list, context: str, limit: Optional[int] = None, offset: int = 0, reverse: bool = False, last: Optional[int] = None, force: bool = False):
        """ Core Batch Orchestrator with Smart Resume / History Awareness. """
        if not contacts:
            logger.warning(f"No contacts found in {context}.")
            return

        total_found = len(contacts)
        
        if last:
            contacts = contacts[-last:]
            logger.info(f"Targeting LAST {len(contacts)} contacts (of {total_found})")
        
        if offset:
            contacts = contacts[offset:]
            logger.info(f"Applying offset {offset}: {len(contacts)} contacts remaining")

        if limit and not last: # Don't re-limit if we already took 'last'
            contacts = contacts[:limit]
            logger.info(f"Targeting {len(contacts)} contacts (limited)")

        if reverse:
            contacts.reverse()
            logger.info("Reversing processing order")

        if not last and not offset and not limit and not reverse:
            logger.info(f"Found {len(contacts)} contacts in {context}")
        
        done_names = set()
        resync_pool = set()
        resync_contexts = {}  # v4.7 F2-FIX: Initialize globally to prevent UnboundLocalError
        
        # v2.0.4.10: Aggressive Normalization Helper
        def normalize_name(n):
            import re
            return re.sub(r'[^a-z0-9]', '', n.lower()) if n else ""

        # v1.6.5: SMART FILTERING (Deduplication across history)
        # We only process contacts that don't have a SUCCESS in archive or today's logs.
        if force:
            logger.info("🚀 FORCE MODE: Bypassing Smart Filter history check.")
            # v2.2.1: SESSION RESUME (even in force mode, skip what was done in this phase today)
            today = datetime.now().strftime("%Y-%m-%d")
            today_logs = glob.glob(f"logs/sessions/run_{today}_*/session.log")
            phase_done = set()
            for log_path in today_logs:
                try:
                    with open(log_path, 'r', errors='ignore') as f:
                        content = f.read()
                        if "FORCE MODE" in content:
                            processed = re.findall(r"Sync Results for (.*?):", content)
                            for s in processed: phase_done.add(normalize_name(s.strip()))
                except: pass
            
            original_count = len(contacts)
            contacts = [c for c in contacts if normalize_name(c["name"]) not in phase_done]
            skipped_count = original_count - len(contacts)
            if skipped_count > 0:
                logger.info(f"🔄 Session Resume: Skipped {skipped_count} contacts already processed in this forced phase today.")
        else:
            # v2.0.4.10: Aggressive Normalization Helper (shadowing avoided)

            # 0. BLACKLIST: Check Review groups for manually removed URLs or rejected contacts
            # v3.1.5: Skip this if we are currently syncing one of these groups!
            for b_group in ["script-LSAM-LinkedIn to Review"]:
                if self.group and b_group in self.group:
                    continue
                try:
                    review_group_res = self.bridge.list_group_contacts(b_group)
                    if review_group_res["success"]:
                        for c in review_group_res["matches"]:
                            name = c.get("name", "")
                            if name:
                                done_names.add(normalize_name(name))
                                clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()
                                done_names.add(normalize_name(clean))
                except Exception as e:
                    logger.warning(f"Failed to fetch blacklist from Review group: {e}")

            # 1. Check Archive
            archive_root = "logs/archive/applied"
            if os.path.exists(archive_root):
                for session in os.listdir(archive_root):
                    session_path = os.path.join(archive_root, session)
                    if os.path.isdir(session_path):
                        for c in os.listdir(session_path):
                             if os.path.isdir(os.path.join(session_path, c)):
                                 real_name = c.replace("_", " ")
                                 norm_name = normalize_name(real_name)
                                 done_names.add(norm_name)
                                 # v2.1.3: Also add clean name (without Mr/Mme) to catch salutation variants
                                 clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', real_name, flags=re.IGNORECASE).strip()
                                 done_names.add(normalize_name(clean))
            
            # 2. Check Today's Logs
            today = datetime.now().strftime("%Y-%m-%d")
            today_logs = glob.glob(f"logs/sessions/run_{today}_*/session.log")
            for log_path in today_logs:
                if os.path.exists(log_path):
                    with open(log_path, 'r', errors='ignore') as f:
                        content = f.read()
                        # Find all successfully synced names in this log
                        successes = re.findall(r"Sync Results for (.*?): SUCCESS", content)
                        for s in successes: done_names.add(normalize_name(s.strip()))
                        
                        # v1.6.9: Also skip today's search failures to unblock the queue
                        failures = re.findall(r"Sync Results for (.*?): ERROR_SEARCH_FAILED", content)
                        for f in failures: done_names.add(normalize_name(f.strip()))
                        
                        # v2.0.6: Simulation Loop Fix - skip ambiguous/skipped to prevent blocking the queue
                        skipped = re.findall(r"Sync Results for (.*?): SKIPPED_", content)
                        for s in skipped: done_names.add(normalize_name(s.strip()))
            
            # 3. Check for .resync flags (v1.7.3)
            # If a contact was flagged for resync, we must remove them from done_names
            resync_flags = glob.glob("logs/sessions/*/backups/*/.resync")
            resync_contexts = {}  # v4.7 F2-FIX: Store feedback context per contact
            for flag in resync_flags:
                folder_name = os.path.basename(os.path.dirname(flag))
                guess = folder_name.replace("_", " ")
                resync_pool.add(normalize_name(guess))
                
                # v4.7 F2-FIX: Read .resync file content (JSON context from staged manager)
                try:
                    with open(flag, 'r') as f:
                        content = f.read().strip()
                    if content:
                        import json as _json
                        ctx = _json.loads(content)
                        if ctx.get("feedback_reason"):
                            resync_contexts[normalize_name(guess)] = ctx
                            logger.info(f"📋 Resync context loaded for '{guess}': {ctx.get('feedback_reason')}")
                except (json.JSONDecodeError, IOError):
                    pass  # Legacy empty .resync files — backwards compatible
                
                # v2.0.5: Injection (v4.7 HARDENED: reject ambiguous matches)
                # Check if this name is in current contacts list
                if not any(normalize_name(c['name']) == normalize_name(guess) for c in contacts):
                    logger.info(f"💉 Resync Injection: Fetching '{guess}' (not in target group)...")
                    found = self.bridge.find_contact(guess)
                    if found["success"]:
                         # v4.7 B1-FIX: Only inject if we get a SINGLE exact match.
                         # Ambiguous matches from loose search were injecting 10+ wrong contacts.
                         if found.get("ambiguous"):
                             match_count = len(found.get("matches", []))
                             match_names = [m.get("name", "?") for m in found.get("matches", [])][:5]
                             logger.warning(f"⛔ Resync injection ABORTED for '{guess}': ambiguous match ({match_count} candidates: {match_names}). Skipping to prevent pollution.")
                         elif found.get("id"):
                             inj = {"id": found["id"], "name": found["name"]}
                             if not any(c['id'] == inj['id'] for c in contacts):
                                 logger.info(f"   => Injected {inj['name']} (single exact match)")
                                 contacts.append(inj)
                         else:
                             logger.warning(f"⛔ Resync injection SKIPPED for '{guess}': unexpected response format.")

            original_count = len(contacts)
            # Filter: keep if name or prefix-stripped name is NOT in done_names
            def is_done(name):
                if not name: return False
                # Explicit Resync check
                clean_name = name.strip()
                # Resync pool is now normalized, so check against normalized name
                norm_name = normalize_name(clean_name)
                if norm_name in resync_pool:
                    return False
                
                if norm_name in done_names: return True
                clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', clean_name, flags=re.IGNORECASE).strip()
                if normalize_name(clean) in done_names: return True
                return False
                
            contacts = [c for c in contacts if not is_done(c["name"])]
            skipped_count = original_count - len(contacts)
            
            if skipped_count > 0:
                logger.info(f"🛡️ Smart Filter: Skipped {skipped_count} contacts already synced successfully today or in history.")
        
        # v1.7.5: Fast-Track Resync (Priority Queue)
        # Move any contact in the resync_pool to the top of the list
        if resync_pool:
            resync_items = [c for c in contacts if normalize_name(c["name"]) in resync_pool]
            other_items = [c for c in contacts if normalize_name(c["name"]) not in resync_pool]
            if resync_items:
                logger.info(f"⚡ Fast-Track: Prioritizing {len(resync_items)} contacts flagged for re-sync.")
                contacts = resync_items + other_items

        # LSAMC Monitor Hook:
        logger.info(f"📊 BATCH SIZE: {len(contacts)} candidates selected for processing (of {original_count} total).")

        if not self.vault_only:
            await self.check_auth()
        
        logger.info("✅ SYSTEM STARTUP: Ready to process batch.")
        
        for contact in contacts:
            self._contacts_since_recycle += 1
            contact_name = contact.get("name")
            
            # v4.7 B2-FIX: Defensive guard against None/empty/invalid names
            # Prevents NoneType crashes that were killing entire sessions.
            if not contact_name or contact_name.strip() in ("", "Unknown", "N/A"):
                logger.warning(f"⏭️ Skipping invalid/nameless contact: id={contact.get('id', '?')}, raw_name={contact_name!r}. Moving to Search Failed.")
                cid = contact.get("id")
                if cid:
                    self.bridge.add_to_group(cid, "script-LSAM-Search-Failed")
                    if self.group:
                        self.bridge.remove_from_group(cid, self.group)
                continue
            
            # v3.1: Deceased Protection (skip and move to group)
            suffix = contact.get("suffix", "")
            if re.search(r'[+†]$', contact_name) or re.search(r'[+†]', suffix):
                logger.info(f"⚰️ Deceased contact detected: {contact_name}. Moving to script-deceased group and skipping.")
                self.bridge.add_to_group(contact["id"], "script-deceased")
                continue
            
            # v1.5.0: Pre-flight Health Check
            if not self.vault_only:
                is_healthy = await self._check_browser_health()
                if not is_healthy:
                    logger.warning("🩺 Health Check FAILED. Attempting Surgical Restart...")
                    try:
                        await self.close()
                        # v1.5.9 FIX: Reset state so setup_browser actually re-initializes
                        self._browser_started = False
                        self.browser = None
                        await self._kill_orphaned_chrome()
                        await self._setup_browser(headless=self._browser_headless)
                        self._contacts_since_recycle = 0
                        logger.info("✅ Surgical Restart complete. Resuming...")
                    except Exception as e_restart:
                        logger.error(f"❌ Surgical Restart failed: {e_restart}. Skipping contact.")
                        continue

            # v1.3.4: Browser Watchdog - Detect hangs during extraction
            try:
                # 5 minute timeout per contact to catch renderer crashes/hangs
                contact_start = datetime.now()
                # v4.7 F2-FIX: Pass resync context to sync_profile
                # v4.8: Pass force flag
                ctx = resync_contexts.get(normalize_name(contact_name))
                status = await asyncio.wait_for(
                    self.sync_profile(contact_name=contact_name, contact_id=contact.get("id"), resync_context=ctx, force=force),
                    timeout=300.0 
                )
                duration = (datetime.now() - contact_start).total_seconds()
                self._contacts_processed_in_session += 1
                logger.info(f"Sync Results for {contact_name}: {status}") 
                logger.info(f"Contact {contact_name} sync status: {status} (Duration: {duration:.1f}s)")
                
                # v1.5.0: Circuit Breaker Logic
                # v4.9.0: Expanded Safe Whitelist to prevent False Positives on Ambiguity/NotFound
                SAFE_STATUSES = [
                    "SUCCESS", 
                    "SKIPPED_MANUAL_PURGE", "SKIPPED_MANUAL_IGNORE", "SKIPPED_EXEMPTED",
                    "SKIPPED_NOT_FOUND", "SKIPPED_VAULT_MISS", "SKIPPED_AMBIGUOUS", "SKIPPED_STEALTH_POLICY"
                ]
                
                if status in SAFE_STATUSES:
                    self.consecutive_failures = 0
                    self.consecutive_extraction_failures = 0
                    
                    # v4.8.1: Auto-drain Force Refresh group on SUCCESS
                    if status == "SUCCESS" and self.group == "script-LSAM-Force-Refresh":
                        cid = contact.get("id")
                        if cid:
                            logger.info(f"🧹 Force Refresh: Removing {contact_name} from queue (sync complete).")
                            self.bridge.remove_from_group(cid, "script-LSAM-Force-Refresh")
                    
                    # v4.8.3: Batch Recycle — exit after N processed items (Success OR Resource-Intensive Skips)
                    # We check this for ALL safe statuses to ensure we don't run forever if we hit a streak of ambiguities.
                    if self._contacts_processed_in_session >= BATCH_RECYCLE_LIMIT:
                        logger.info(f"♻️ BATCH RECYCLE: {self._contacts_processed_in_session} contacts processed. Exiting for fresh restart (exit code {BATCH_RECYCLE_EXIT_CODE}).")
                        sys.exit(BATCH_RECYCLE_EXIT_CODE)
                elif status == "ERROR_SEARCH_FAILED":
                    # v1.6.8: Surgical Failure Isolation
                    # Move toxic contacts to a separate group so they don't block the queue
                    cid = contact.get("id")
                    if cid:
                        logger.info(f"📍 Isolation: Moving {contact_name} to 'Search Failed' group to unblock campaign.")
                        self.bridge.add_to_group(cid, "script-LSAM-Search-Failed")
                        if self.group:
                            self.bridge.remove_from_group(cid, self.group)
                    
                    self.consecutive_failures += 1
                elif status == "SKIPPED_SELF_IDENTIFIED":
                    # v1.7.6: Fatal Navigation Error - Immediate Circuit Break
                    # v1.7.7: Quarantine to prevent persistent wrecking
                    logger.critical(f"🛑 FATAL: Self-Identity detected for {contact_name}. Forcing immediate Circuit Breaker.")
                    cid = contact.get("id")
                    if cid:
                        logger.info(f"📍 Quarantine: Moving toxic profile {contact_name} to 'Search Failed' group.")
                        self.bridge.add_to_group(cid, "script-LSAM-Search-Failed")
                        if self.group:
                            self.bridge.remove_from_group(cid, self.group)
                    self.consecutive_failures = self.failure_threshold
                else:
                    self.consecutive_failures += 1
                    if "EXTRACTION" in status:
                        self.consecutive_extraction_failures += 1
                    
                # Circuit Breaker Trip: Consecutive total failures
                if self.consecutive_failures >= self.failure_threshold:
                    logger.critical(f"🚨 [CIRCUIT BREAKER] {self.consecutive_failures} consecutive failures (Last: {status}). Stopping batch to prevent account risk.")
                    # v1.6.8: In isolation mode, we exit so the supervisor can restart us with a fresh queue
                    sys.exit(1)

                    # Circuit Breaker Trip: Consecutive extraction failures (Browser/CDP health)
                    if self.consecutive_extraction_failures >= self.extraction_failure_threshold:
                        logger.warning(f"⚠️ [CIRCUIT BREAKER] {self.consecutive_extraction_failures} consecutive extraction failures. Forcing hard restart...")
                        await self.close()
                        await self._kill_orphaned_chrome()
                        await self._setup_browser(headless=self._browser_headless)
                        self.consecutive_extraction_failures = 0 # Reset after fix
                
            except asyncio.TimeoutError:
                logger.error(f"⏱️ WATCHDOG TIMEOUT for {contact_name}. Renderer probably hung. Forcing recycle.")
                await self.close() # Safe close using existing robust logic
                await self._kill_orphaned_chrome()
                await self._setup_browser(headless=self._browser_headless)
                self._contacts_since_recycle = 0
                logger.info("✅ Browser recycled after timeout. Continuing to next contact.")
                status = "SKIPPED_WATCHDOG_TIMEOUT"
            except Exception as e_fatal:
                logger.error(f"💥 FATAL ERROR during sync of {contact_name}: {e_fatal}")
                # v3.1.6: Isolation on fatal error
                cid = contact.get("id")
                if cid:
                    logger.info(f"📍 Isolation: Moving toxic contact {contact_name} to 'Search Failed' group to unblock campaign.")
                    self.bridge.add_to_group(cid, "script-LSAM-Search-Failed")
                    if self.group:
                        self.bridge.remove_from_group(cid, self.group)
                
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.failure_threshold:
                    logger.critical(f"🚨 [CIRCUIT BREAKER] {self.consecutive_failures} consecutive failures (Last Error: {e_fatal}). Stopping batch.")
                    sys.exit(1)
                continue
            
            # v4.7 B3-FIX: Skip stealth delay for non-network outcomes.
            # Previously, contacts detected as MANUAL_PURGE, MANUAL_IGNORE, EXEMPTED, etc.
            # STILL caused an 80s stealth delay despite no LinkedIn page being loaded.
            # At 50+ such contacts/day × 80s = ~66 min/day wasted.
            INSTANT_SKIP_STATUSES = {"SKIPPED_MANUAL_PURGE", "SKIPPED_MANUAL_IGNORE", "SKIPPED_EXEMPTED", 
                                     "SKIPPED_NOT_FOUND", "ERROR_CONTACT_NOT_FOUND", "SKIPPED_VAULT_MISS", 
                                     "SKIPPED_WATCHDOG_TIMEOUT"}
            if status not in INSTANT_SKIP_STATUSES:
                # v1.3.9: Optimized Target Speed (~25 contacts/hour)
                import random
                wait_time = 70.0 + random.random() * 20.0
                logger.info(f"Stealth delay: {wait_time:.1f}s (Total session time: {(datetime.now() - self.session_start_time).total_seconds()/60:.1f} min)")
                
                # v2.2.2: Incremental Sleep with Heartbeat to satisfy Supervisor
                # v4.7 B4-FIX: Elevated from DEBUG to INFO so supervisor detects liveness
                remaining_wait = wait_time
                while remaining_wait > 0:
                    step = min(remaining_wait, 30.0)
                    await asyncio.sleep(step)
                    remaining_wait -= step
                    if remaining_wait > 0:
                        logger.info(f"⏳ Stealth Heartbeat: {remaining_wait:.1f}s remaining...")
            else:
                logger.info(f"⚡ Fast-skip: No stealth delay for {status} (no LinkedIn network activity).")
            
            # v1.4.0: Random Burst (Rest period every 15 contacts)
            if self._contacts_processed_in_session % 15 == 0:
                burst_rest = 270.0 + random.random() * 60.0
                logger.info(f"💤 Engaging Random Burst Rest: {burst_rest/60:.1f} minutes...")
                await asyncio.sleep(burst_rest)
            
            # v1.3.2: Memory Management
            self._contacts_since_gc += 1
            if self._contacts_since_gc >= 5:
                self._force_gc()
                self._contacts_since_gc = 0
            
            # v1.3.3: Periodic Hard Browser Recycling
            if not self.vault_only:
                mem_status = await self._check_memory_and_cleanup()
                if mem_status == "EMERGENCY":
                    logger.error("🚨 Memory emergency detected. Stopping.")
                    break
                    
                if self._contacts_since_recycle >= 50:
                    logger.info("♻️ Browser recycling triggered (every 50 contacts).")
                    await self.close() # Safe close
                    await self._setup_browser(headless=self._browser_headless)
                    self._contacts_since_recycle = 0
                
        logger.info(f"Batch sync for {context} completed.")
        await self.close()

    async def sync_profile(self, linkedin_url: Optional[str] = None, contact_name: Optional[str] = None, manual_url: Optional[str] = None, contact_id: Optional[str] = None, resync_context: Optional[dict] = None, force: bool = False) -> str:
        """Main sync loop with auditing and simulation features (v0.2.1).
        v4.7 F2-FIX: Accepts optional resync_context dict with user feedback."""
        logger.info(f"Syncing: {contact_name or contact_id or linkedin_url} (LSAMC v{__version__})")
        if resync_context:
            logger.info(f"🔁 RESYNC WITH USER CONTEXT: reason='{resync_context.get('feedback_reason', 'N/A')}' from {resync_context.get('feedback_timestamp', 'unknown')}")
        
        # v0.9.1: Hardcoded skip for deceased/exempted
        if contact_name in self.EXCLUSIONS:
            logger.info(f"⏭️ Skipping exempted contact: {contact_name}")
            return "SKIPPED_EXEMPTED"
        # v4.8.2: Fuzzy self-identity guard — catches emoji suffixes, honorifics, unicode decorations
        name_ascii = unicodedata.normalize('NFKD', contact_name).encode('ascii', 'ignore').decode().lower()
        if "dewost" in name_ascii:
            logger.info(f"⏭️ Skipping self-contact (fuzzy match): {contact_name}")
            return "SKIPPED_EXEMPTED"
            
        # 0. Auth Check
        if not self.vault_only:
            await self.check_auth()
        else:
            logger.debug("Vault-only: skipping check_auth()")

        # 1. macOS Contact Search
        contact_company = None
        if not contact_id and contact_name:
            logger.debug(f"Locating contact in macOS by name: {contact_name}")
            res = self.bridge.find_contact(contact_name)
            if not res["success"]:
                logger.error(res["error"])
                return "ERROR_CONTACT_NOT_FOUND"
            
            if res.get("ambiguous"):
                match = res["matches"][0]
                logger.warning(f"Ambiguous match for {contact_name}. Using the first one: {match['id']}")
                contact_id = match["id"]
                contact_name = match["name"]
                contact_company = match.get("company")
            else:
                contact_id = res["id"]
                contact_name = res["name"]
                contact_company = res.get("company")
        elif contact_id:
            logger.debug(f"Proceeding with provided contact_id: {contact_id}")
            # Still need name and company for later search logic fallback or auditing
            details = self.bridge.get_contact_details(contact_id)
            if details["success"]:
                if not contact_name: contact_name = details["name"]
                contact_company = details.get("company")
            else:
                logger.error(f"Could not retrieve details for ID {contact_id}")
                return "ERROR_CONTACT_NOT_FOUND"

        if not contact_id:
            logger.error(f"Contact ID not found for: {contact_name}")
            return "ERROR_CONTACT_NOT_FOUND"

        # 2. AUDIT: Capture Original State
        vcard_res = {"success": False}
        current = self.bridge.get_contact_details(contact_id)
        if current["success"]:
            # v3.6.0: Manual Purge Detection (Jean-Claude MALLET Pattern)
            note_content = current.get("note", "")
            has_url = bool(current.get("social_profile"))
            has_metadata = "#lsam" in note_content.lower()
            
            # 1. Explicit ignore tags
            if any(tag in note_content.lower() for tag in ["#lsam-ignore", "#lsam-discarded"]):
                logger.info(f"⏭️ Skipping {contact_name}: Explicit ignore tag detected.")
                return "SKIPPED_MANUAL_IGNORE"

            # 2. Check for manual cleanup of previously synced contact
            # v4.8 Manual Purge Override with Force
            # SAFEGUARD: archive_root must be initialized here to prevent UnboundLocalError in Force Mode
            if not has_url and not has_metadata:
                safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
                archive_root = os.path.join(self.log_dir, "archive", "applied")

                if force:
                    logger.info(f"⚠️ FORCE MODE: Bypassing Manual Purge Detection for {contact_name}.")
                    # We still check history just for logging context if needed, but we don't return SKIPPED
                else:
                    # Pattern: logs/archive/applied/*/Contact_Name
                    history_hit = glob.glob(os.path.join(archive_root, "*", safe_name))
                    
                    if history_hit:
                        logger.warning(f"🛑 MANUAL PURGE DETECTED for {contact_name}. Archival record exists but contact is now clean.")
                        logger.info("Respecting user cleanup. Tagging with #lsam-ignore and skipping.")
                        self.bridge.update_contact(contact_id, {"Ignore_Tag": "#lsam-ignore (Detected manual purge)"})
                        return "SKIPPED_MANUAL_PURGE"

            self._create_backup(contact_name, note_content, "original", "txt")
            vcard_res = self.bridge.get_vcard(contact_id)
            if vcard_res["success"]:
                self._create_backup(contact_name, vcard_res["output"], "original", "vcf")
            else:
                logger.error(f"Audit failed to capture vCard for {contact_name}: {vcard_res.get('error')}")
            
            # Audit Original Photo
            safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
            orig_photo_path = os.path.join(self.backup_dir, safe_name, f"{safe_name}-original.jpg")
            photo_res = self.bridge.export_contact_photo(contact_id, orig_photo_path)
            if photo_res["success"] and photo_res["path"]:
                logger.debug(f"Saved original photo backup to {photo_res['path']}")
        else:
            logger.error(f"Audit failed to capture current details for {contact_name}: {current.get('error')}")

        # 2.5 SPOT Vault Check (v1.0.0)
        vault_hit = self._check_vault(contact_id)
        
        # v1.2.2: In vault-only mode, we use the vault hit even if stale or needing photo retry
        should_use_vault = False
        if vault_hit:
            if not vault_hit["is_stale"] and not vault_hit["needs_photo_retry"]:
                should_use_vault = True
            elif self.vault_only:
                reason = "stale" if vault_hit["is_stale"] else "needs photo retry"
                logger.info(f"VAULT: Using record for {contact_name} despite {reason} (vault-only mode)")
                should_use_vault = True

        if should_use_vault:
            logger.info(f"SPOT Vault Hit for {contact_name}! Bypassing LinkedIn. (Quality: {vault_hit['photo_res']})")
            profile = vault_hit["profile"]
            
            # Use a temp copy to avoid deleting the 'Golden' vault source during cleanup
            photo_path = None
            if vault_hit["photo_path"]:
                import tempfile, shutil
                temp_fd, photo_path = tempfile.mkstemp(suffix=os.path.splitext(vault_hit["photo_path"])[1])
                os.close(temp_fd)
                shutil.copy2(vault_hit["photo_path"], photo_path)
                
                # IMPORTANT: Save to session backup folder so 'apply' phase can find it
                with open(photo_path, "rb") as f:
                    self._create_backup(contact_name, f.read(), "linkedin", "heic")
                
                # v1.2.1: Also copy the 'archive' raw photo if available
                if vault_hit.get("raw_photo_path"):
                    with open(vault_hit["raw_photo_path"], "rb") as f:
                        self._create_backup(contact_name, f.read(), "linkedin-raw", "jpg")
                
            return await self._finalize_sync(contact_id, contact_name, profile, photo_path, vcard_res, orig_photo_path, was_retry=True)

        if self.vault_only:
            logger.warning(f"❌ VAULT MISS for {contact_name}. Aborting (Vault-Only mode).")
            return "SKIPPED_VAULT_MISS"

        # 3. LinkedIn Search (if needed)
        search_stats = {}
        
        # v0.7.6 Handle-First Discovery: Check if contact already has a LinkedIn social profile or URL
        existing_url = None
        if current["success"]:
            # Check social profiles (Format: Service|USER:xxx|URL:yyy)
            for s in current.get("social", []):
                if "linkedin" in s.lower():
                    # Try to extract from URL first (most reliable for handle redirected users)
                    if "|URL:" in s:
                        p_url = s.split("|URL:")[-1].strip()
                        if "linkedin.com/in/" in p_url.lower():
                            existing_url = p_url
                            logger.info(f"Found existing LinkedIn URL in social profile: {p_url}")
                            break
                    # Fallback to USER if URL is not a direct LinkedIn profile link
                    if "|USER:" in s:
                        handle = s.split("|USER:")[-1].split("|")[0].strip()
                        if handle and handle != "unknown" and handle != "":
                            existing_url = f"https://www.linkedin.com/in/{handle}/"
                            logger.info(f"Generated LinkedIn URL from handle: {handle}")
                            break
            # Check websites if social profile discovery failed
            if not existing_url:
                for u in current.get("websites", []):
                    if "linkedin.com/in/" in u.lower():
                        existing_url = u
                        logger.info(f"Found existing LinkedIn URL in websites: {u}")
                        break
        
        if manual_url:
            logger.info(f"Surgical override: Using manual URL {manual_url}")
            linkedin_url = manual_url
            search_stats = {"url": manual_url}
        elif BATCH_9_OVERRIDES.get(contact_name):
            url = BATCH_9_OVERRIDES[contact_name]
            logger.info(f"Surgical override (Batch 9): Using manual URL for {contact_name}: {url}")
            linkedin_url = url
            search_stats = {"url": url}
        elif existing_url:
            if ' ' in existing_url:
                logger.warning(f"Ignoring invalid existing URL with spaces: {existing_url}. Will attempt fresh search.")
            else:
                logger.info(f"Proceeding with existing LinkedIn URL: {existing_url}")
                linkedin_url = existing_url
                search_stats = {"url": existing_url}
        elif not linkedin_url:
            note_companies = self._extract_companies_from_notes(current.get("note", ""))
            all_companies = [contact_company] if contact_company else []
            all_companies.extend(note_companies)
            
            find_res = await self.find_linkedin_profile(contact_name, all_companies, role=current.get("job_title", ""))
            if find_res == "NOT_FOUND":
                logger.warning(f"No 1st-degree LinkedIn match found for {contact_name}. Tagging note with Warning.")
                today = datetime.now().strftime("%Y-%m-%d")
                
                # v4.7: Visible Warning in Note (User Request) via manual prepend
                warning_block = (
                    f"⚠️ LinkedIn: No Profile Found (checked on {today})\n"
                    "--------------------------------------------------"
                )
                self.bridge.prepend_to_note(contact_id, warning_block)
                return "SKIPPED_NOT_FOUND"
            elif isinstance(find_res, str) and find_res.startswith("AMBIGUOUS:"):
                logger.warning(f"Handling Ambiguity for {contact_name}...")
                candidates_raw = find_res.replace("AMBIGUOUS:", "").split("|OR|")
                
                # Format candidate list for the note
                candidate_lines = []
                for c in candidates_raw:
                    try:
                        c_info, c_url = c.split("|#|")
                        candidate_lines.append(f"- {c_info} -> {c_url}")
                    except: continue
                
                warning_block = (
                    "⚠️ LSAM AMBIGUITY / 2ND DEGREE\n"
                    "I found multiple potential matches or a 2nd-degree connection.\n"
                    "Please verify which one is correct:\n"
                    + "\n".join(candidate_lines) + "\n\n"
                    "Once verified, paste the correct URL in the 'social profile' field.\n"
                    "#linkedin-ambiguous-profile\n"
                    "--------------------------------------------------"
                )
                
                # 1. Add to Review Group (v1.3.0: Fixed name)
                self.bridge.add_to_group(contact_id, self.REVIEW_GROUP)
                
                # 2. Move out of Source Group (if applicable)
                if hasattr(self, 'group') and self.group and self.group != self.REVIEW_GROUP:
                    logger.info(f"Moving Ambiguous contact from {self.group} to Review group.")
                    self.bridge.remove_from_group(contact_id, self.group)
                
                # 3. Append Warning to Note (v4.7: Prepend for visibility)
                self.bridge.prepend_to_note(contact_id, warning_block)
                
                return "SKIPPED_AMBIGUOUS"
            elif isinstance(find_res, dict):
                linkedin_url = find_res.get("url")
                search_stats = find_res
                
                # CHECK TIER 2 (Broad Search or explicit non-1st)
                # If is_first is False (and not None), it's a 2nd/3rd degree match.
                if find_res.get("is_first") is False:
                     logger.info(f"⚠️ Tier 2 Match (Broad Search) for {contact_name}. Flagging for Review in Slow Horse.")
                     self.bridge.add_to_group(contact_id, "LSAM LinkedIn Review")
            elif not find_res or "ERROR" in str(find_res).upper():
                return "ERROR_SEARCH_FAILED"
            else:
                linkedin_url = find_res

        # v1.7.7: URL Sanitizer (Fix %3F encoding errors)
        if linkedin_url and "%3F" in linkedin_url:
            cleaned = linkedin_url.replace("%3F", "?")
            logger.info(f"🔧 URL Sanitizer: Corrected {linkedin_url} -> {cleaned}")
            linkedin_url = cleaned

        # 4. LinkedIn Extraction with Stealth Manager (v1.2.0)
        stealth_check = self.stealth.is_safe_to_access(contact_id, linkedin_url)
        if not stealth_check["safe"]:
            logger.warning(f"⚠️ STEALTH BLOCK for {contact_name}: {stealth_check['reason']}")
            if vault_hit:
                logger.info(f"Stealth Policy: Falling back to Vault data (Quality: {vault_hit['photo_res']})")
                profile = vault_hit["profile"]
                photo_path = None
                if vault_hit["photo_path"]:
                    import tempfile, shutil
                    temp_fd, photo_path = tempfile.mkstemp(suffix=os.path.splitext(vault_hit["photo_path"])[1])
                    os.close(temp_fd)
                    shutil.copy2(vault_hit["photo_path"], photo_path)
                    with open(photo_path, "rb") as f:
                        self._create_backup(contact_name, f.read(), "linkedin", "heic")
                return await self._finalize_sync(contact_id, contact_name, profile, photo_path, vcard_res, orig_photo_path, was_retry=True)
            else:
                logger.error(f"Stealth Policy: No Vault data available for {contact_name}. Skipping.")
                return "SKIPPED_STEALTH_POLICY"
        
        # v1.5.7 SAFEGUARD: Block Self-Extraction via URL
        # If we somehow navigated to our own profile (e.g. via 'Me' icon or redirect)
        if "linkedin.com/in/" in linkedin_url.lower():
            # Check against known self-handles if configured, or just generic heuristics
            # For now, relying on the name check post-extraction is safer, but we can add a rough check here
            # User is "Philippe DEWOST". Handle might be "pdewost" or "philippe-dewost" etc.
            # Let's add the specific one we saw in backups if known, or rely on Name Check.
            pass

        # Proceed with extraction
        self.stealth.record_access(contact_id, linkedin_url, reason="sync")
        profile = await self.extract_profile(linkedin_url, initial_stats=search_stats)
        if not profile:
            return "ERROR_EXTRACTION_FAILED"

        # v1.6.1 SAFEGUARD: Post-Extraction Identity Check (Me-Blocker)
        # Prevents Gemini/Scraper from accidentally grabbing the logged-in user's name 
        # from the nav bar if the target profile failed to load.
        norm_name = unicodedata.normalize('NFKC', profile.full_name).lower()
        if "philippe dewost" in norm_name and "dewost" in norm_name:
             logger.error(f"🛑 CRITICAL: Self-Identity detected in extraction ({profile.full_name}). Aborting to prevent pollution.")
             return "SKIPPED_SELF_IDENTIFIED"
        
        # Merge local data if LLM missed it (this is now redundant if extract_profile does it, but safer)
        # Note: profile.local_info might be populated by extract_profile
        
        # 5. Photo Handling
        photo_path = None
        if profile.photo_url:
            raw_tmp_path = await self._download_photo(str(profile.photo_url))
            if raw_tmp_path:
                # Save raw HQ if it exists to the backup dir
                safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
                contact_backup_dir = os.path.join(self.backup_dir, safe_name)
                os.makedirs(contact_backup_dir, exist_ok=True)
                
                # Determine extension (crude)
                ext = "jpg"
                if str(profile.photo_url).lower().endswith(".png") or ".png?" in str(profile.photo_url).lower():
                    ext = "png"
                
                raw_dest = os.path.join(contact_backup_dir, f"{safe_name}-linkedin-raw.{ext}")
                import shutil
                shutil.copy2(raw_tmp_path, raw_dest)
                logger.info(f"Saved raw high-res photo to: {raw_dest}")
                
                photo_path = optimize_image(raw_tmp_path, max_dimension=1024)
                if (photo_path and os.path.exists(photo_path)):
                    # Audit LinkedIn Photo (optimized)
                    with open(photo_path, "rb") as f:
                        self._create_backup(contact_name, f.read(), "linkedin", "heic")

        return await self._finalize_sync(contact_id, contact_name, profile, photo_path, vcard_res, orig_photo_path, was_retry=True)

    def _simulate_vcard_changes(self, vcf: str, profile: Any, note: str) -> str:
        """Surgically substitutes fields in a vCard string for audit previews."""
        import re
        lines = vcf.splitlines()
        new_lines = []
        
        # Escape note for vCard format (newlines as literal \n, etc.)
        note = note or ""
        vcf_note = note.replace('\n', '\\n').replace(':', '\\:').replace(';', '\\;')
        
        for line in lines:
            if line.startswith("TITLE:"):
                new_lines.append(f"TITLE:{profile.current_role}")
            elif line.startswith("ORG:"):
                new_lines.append(f"ORG:{profile.company}")
            elif line.startswith("NOTE:"):
                new_lines.append(f"NOTE:{vcf_note}")
            elif line.startswith("PHOTO") or line.startswith(" "):
                continue
            elif line.startswith("REV:"):
                new_lines.append(f"REV:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}")
            elif line.startswith("URL") or line.startswith("item") and "URL" in line:
                # Skip existing URLs
                continue
            else:
                new_lines.append(line)
        
        # Add ORG/TITLE if they were missing
        if not any(l.startswith("ORG:") for l in new_lines) and hasattr(profile, 'company') and profile.company:
            new_lines.insert(-1, f"ORG:{profile.company}")
        if not any(l.startswith("TITLE:") for l in new_lines) and hasattr(profile, 'current_role') and profile.current_role:
            new_lines.insert(-1, f"TITLE:{profile.current_role}")
            
        # Add Websites with proper Attribution Label (v0.7.8 fix)
        if hasattr(profile, 'websites') and profile.websites:
            for i, ws in enumerate(profile.websites):
                idx = i + 10 # start high to avoid collision
                new_lines.insert(-1, f"item{idx}.URL;type=pref:{ws}")
                new_lines.insert(-1, f"item{idx}.X-ABLabel:from LinkedIn")
            
        # Add Photo if available
        photo_path = getattr(profile, '_temp_photo_path', None)
        if photo_path and os.path.exists(photo_path):
            import base64
            with open(photo_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                new_lines.insert(-1, f"PHOTO;ENCODING=b;TYPE=HEIC:{b64}")

        return "\n".join(new_lines)

    def validate_contact(self, session_path: str, contact_name: str, folder_name: Optional[str] = None):
        """Marks a contact in a session as validated."""
        if folder_name:
            target_dir = os.path.join(session_path, "backups", folder_name)
        else:
            safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
            target_dir = os.path.join(session_path, "backups", safe_name)
            
        if not os.path.exists(target_dir):
            logger.error(f"Backup directory not found: {target_dir}")
            return False
        
        lockfile = os.path.join(target_dir, ".validated")
        with open(lockfile, "w") as f:
            f.write(datetime.now().isoformat())
            
        logger.info(f"✅ CONTACT VALIDATED: {contact_name}")
        return True

    async def apply_session(self, session_path: str):
        """Commits all validated contacts in a session to macOS Contacts."""
        if not os.path.exists(backups_dir):
            logger.error(f"Backups directory not found: {backups_dir}")
            return
            
        contacts = [d for d in os.listdir(backups_dir) if os.path.isdir(os.path.join(backups_dir, d))]
        logger.info(f"Scanning {len(contacts)} contacts in session for validated backups...")
        
        applied_count = 0
        for c_dir in contacts:
            path = os.path.join(backups_dir, c_dir)
            if os.path.exists(os.path.join(path, ".validated")) and not os.path.exists(os.path.join(path, ".applied")):
                # Load profile.json
                json_path = os.path.join(path, "profile.json")
                if not os.path.exists(json_path): continue
                
                with open(json_path, "r") as f:
                    data = json.load(f)
                
                profile = LinkedInProfile.model_validate(data)
                contact_id = data.get("_contact_id")
                
                if not contact_id:
                    logger.warning(f"No _contact_id found for {profile.full_name}, skipping.")
                    continue
                
                # Load LinkedIn photo if exists
                photo_path = os.path.join(path, f"{c_dir}-linkedin.heic")
                if not os.path.exists(photo_path):
                    # Try the non-prefixed name if different
                    photo_path = os.path.join(path, "linkedin.heic")
                if not os.path.exists(photo_path):
                    photo_path = None

                # Load original photo for size comparison if exists
                orig_photo_path = os.path.join(path, f"{c_dir}-original.jpg")
                if not os.path.exists(orig_photo_path):
                    orig_photo_path = os.path.join(path, "original.jpg")
                if not os.path.exists(orig_photo_path):
                    orig_photo_path = None
                
                photo_status = data.get("_photo_status")
                
                logger.info(f"Applying validated backup for: {profile.full_name} ({contact_id})")
                res = self.bridge.update_contact(contact_id, profile, photo_path=photo_path, photo_status=photo_status, orig_photo_path=orig_photo_path)
                
                if res.get("success"):
                    applied_count += 1
                    with open(os.path.join(path, ".applied"), "w") as f:
                        f.write(datetime.now().isoformat())
                else:
                    logger.error(f"Failed to apply {profile.full_name}: {res.get('error')}")
        
        logger.info(f"COMMIT COMPLETE: {applied_count} contacts updated in macOS Address Book.")

    async def archive_applied_contacts(self, group_name: str = "script-LSAM-Golden Record"):
        """Removes contacts that were successfully applied today from the specified group."""
        logger.info(f"Archiving contacts applied today from group: {group_name}")
        
        # 1. Find all .applied files from the last 24h
        backups_dir = os.path.join(self.log_dir, "sessions")
        # Use find to get list of applied contacts (folder names)
        cmd = ["find", backups_dir, "-name", ".applied", "-mtime", "-1"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        if res.returncode != 0:
            logger.error("Failed to find applied contacts.")
            return

        applied_paths = res.stdout.splitlines()
        contact_ids = set()
        
        for ap in applied_paths:
            # Load profile.json to get contact_id
            dir_path = os.path.dirname(ap)
            json_path = os.path.join(dir_path, "profile.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r") as f:
                        data = json.load(f)
                        cid = data.get("_contact_id")
                        if cid:
                            contact_ids.add(cid)
                except:
                    continue
        
        if not contact_ids:
            logger.info("No contacts found to archive.")
            return
            
        logger.info(f"Found {len(contact_ids)} unique contacts to archive.")
        
        count = 0
        for cid in contact_ids:
            res = self.bridge.remove_from_group(cid, group_name)
            if res.get("success"):
                if res.get("output") == "REMOVED":
                    count += 1
                    
        logger.info(f"Archival complete. {count} contacts removed from '{group_name}'.")

    def validate_all_in_session(self, session_path: str):
        """Marks all contacts in a session as validated."""
        backups_dir = os.path.join(session_path, "backups")
        if not os.path.exists(backups_dir): return
        
        contacts = [d for d in os.listdir(backups_dir) if os.path.isdir(os.path.join(backups_dir, d))]
        logger.info(f"Validating all {len(contacts)} contacts in session: {session_path}")
        
        for c_dir in contacts:
            path = os.path.join(backups_dir, c_dir)
            json_path = os.path.join(path, "profile.json")
            if not os.path.exists(json_path): continue
            
            with open(json_path, "r") as f:
                data = json.load(f)
            
            contact_name = data.get("full_name", c_dir.replace("_", " "))
            self.validate_contact(session_path, contact_name, folder_name=c_dir)

    async def review_session(self, session_path: str):
        """Interactive CLI and Native GUI for reviewing and validating staged contacts."""
        backups_dir = os.path.join(session_path, "backups")
        if not os.path.exists(backups_dir):
            logger.error("Session not found.")
            return

        contacts = sorted([d for d in os.listdir(backups_dir) if os.path.isdir(os.path.join(backups_dir, d))])
        total = len(contacts)
        print(f"\n--- SESSION REVIEW: {os.path.basename(session_path)} [{total} contacts] ---")
        
        validate_all = False
        
        # MASTER PROMPT (v2 Redesign)
        if total > 0:
            master_msg = f"Reviewing {total} staged contacts.\nHow would you like to proceed?"
            master_res = self.bridge.show_native_dialog(
                master_msg, 
                title=f"LSAMC v{__version__} - Master Review",
                buttons=["Exit", "Apply All", "Review Individually"],
                default_button="Review Individually"
            )
            
            if master_res.get("success"):
                btn = master_res["button"]
                if btn == "Exit":
                    print("   Quitting.")
                    return
                elif btn == "Apply All":
                    print("   Applying ALL changes automatically.")
                    validate_all = True
            elif master_res.get("cancelled"):
                print("   Cancelled.")
                return

    
        for i, c_dir in enumerate(contacts):
            path = os.path.join(backups_dir, c_dir)
            json_path = os.path.join(path, "profile.json")
            if not os.path.exists(json_path): continue
            
            with open(json_path, "r") as f:
                data = json.load(f)
            
            contact_id = data.get("_contact_id")
            contact_name = data.get("full_name")
            
            # v1.2.5: If name looks like a 404 marker, use the folder name (actual contact name)
            error_keywords = ["page doesn’t exist", "page not found", "لم يتم العثور على الصفحة", "n'avons pas pu trouver cette page", "doesn't exist", "doesn t exist"]
            if contact_name and any(k in contact_name.lower() for k in error_keywords):
                contact_name = c_dir.replace("_", " ")
            
            status = "PENDING"
            if os.path.exists(os.path.join(path, ".applied")): status = "APPLIED"
            elif os.path.exists(os.path.join(path, ".validated")): status = "VALIDATED"
            elif os.path.exists(os.path.join(path, ".skipped")): status = "SKIPPED"
            
            print(f"[{i+1}/{len(contacts)}] {contact_name} ({status})")
            
            if status == "PENDING":
                if validate_all:
                    choice = 'y'
                else:
                    # v2.5.2: Re-calculate proposed changes if missing from older session data
                    proposed = data.get("_proposed_changes")
                    if not proposed:
                        logger.debug(f"   (Re-auditing {contact_name} - Proposed changes missing from staged data)")
                        try:
                            # Re-construct profile object
                            profile_obj = LinkedInProfile(**data)
                            # Call bridge in simulation-safe way to get diff
                            # We temporarily set bridge mode to SIMULATION if it's not already
                            orig_mode = self.bridge.mode
                            self.bridge.mode = "SIMULATION"
                            res = self.bridge.update_contact(contact_id, profile_obj)
                            self.bridge.mode = orig_mode
                            
                            proposed = {
                                "added": res.get("added_fields", []),
                                "updated": res.get("updated_fields", []),
                                "note_blob": res.get("proposed_note", ""),
                                "sync_block_changed": res.get("sync_block_changed", False)
                            }
                            data["_proposed_changes"] = proposed
                        except Exception as re_e:
                            logger.error(f"   Error re-auditing {contact_name}: {re_e}")
                            proposed = {}
                    
                    # v4.1: Ensure prev_stats is available for sanity checks (Live Extract)
                    prev_stats = {}
                    try:
                        live_details = self.bridge.get_contact_details(contact_id)
                        if live_details.get("success"):
                            live_note = live_details.get("note", "")
                            # Replicate bridge's stat extraction logic
                            import re
                            match_f = re.search(r"(?:Followers|Contacts or followers):\s*([\d,.\+]+)", live_note, re.IGNORECASE)
                            match_c = re.search(r"Mutual connections:\s*([\d,.\+]+)", live_note, re.IGNORECASE)
                            match_d = re.search(r"<Linkedin-AI-sync\s+(.*?)\s+(?:update|added)>", live_note, re.IGNORECASE)
                            if match_d: prev_stats["date"] = match_d.group(1)
                            if match_f: prev_stats["followers"] = match_f.group(1).strip()
                            if match_c: prev_stats["common"] = match_c.group(1).strip()
                    except Exception as e:
                        logger.debug(f"   (Failed live stats extraction for {contact_name}: {e})")

                    added = proposed.get("added", [])
                    updated = proposed.get("updated", [])
                    blob = proposed.get("note_blob", "")
                    photo_status = data.get("_photo_status")
                    
                    # v4.3: Surgical change detection. 
                    # photo_unavailable is NOT a reason to prompt user if nothing else changed.
                    # blob (note_blob) is no longer a blind trigger as it's the whole note.
                    # We rely on added_fields, updated_fields, photo status, OR material sync block changes.
                    has_changes = bool(added or updated or (photo_status == "photo_downloaded") or proposed.get("sync_block_changed"))
                    
                    if not has_changes:
                        print(f"   (No material changes detected - Skipping)")
                        continue

                    # Visual Selection in macOS Contacts (Only at prompt time to avoid focus-stealing loops)
                    if contact_id:
                        self.bridge.select_contact(contact_id)
                    
                    msg = f"Reviewing: {contact_name}\n"
                    msg += f"Backup: {path}\n\n"
                    
                    # v4: Sanity Checks & Warnings
                    warnings = []
                    
                    # 1. Stat Drastic Change Check (e.g. Roland Grenke cases)
                    f_new = data.get("followers_count")
                    f_old = prev_stats.get("followers")
                    if f_new is not None and f_old is not None:
                        try:
                            f_older = int(str(f_old).replace(",", "").replace(".", "").replace("+", ""))
                            # If jump > 5% OR drop > 2% AND > 10 absolute followers difference, flag it
                            if abs(f_new - f_older) > 10:
                                if f_new > f_older * 1.05:
                                    warnings.append(f"⚠️ DRASTIC FOLLOWERS JUMP: {f_older} -> {f_new}")
                                elif f_new < f_older * 0.98:
                                    warnings.append(f"⚠️ DRASTIC FOLLOWERS DROP: {f_older} -> {f_new}")
                            
                            # High round number check (e.g. exactly 3000)
                            if f_new > 500 and f_new % 100 == 0 and f_older % 10 != 0:
                                warnings.append(f"⚠️ SUSPICIOUS ROUND NUMBER: {f_new} (was {f_older})")
                        except: pass
                    
                    # 1.5 Mutual Connections Drop Check
                    m_new = data.get("common_connections_count")
                    m_old = prev_stats.get("common")
                    if m_new is not None and m_old is not None:
                        try:
                            m_older = int(str(m_old).replace(",", "").replace(".", "").replace("+", ""))
                            if m_new < m_older:
                                warnings.append(f"⚠️ MUTUAL CONNECTIONS DECREASE: {m_older} -> {m_new}")
                            if m_new == 0 and m_older > 0:
                                warnings.append(f"🚩 CRITICAL: MUTUALS DROPPED TO 0 (Extraction Failure?)")
                        except: pass
                    
                    # 2. Extraction Error Flagging
                    role = data.get("current_role")
                    company = data.get("company")
                    if not role or role.lower() in ["linkedin", "none", "unknown"]:
                        warnings.append("⚠️ SUSPICIOUS ROLE (Empty or LinkedIn)")
                    if not company or company.lower() in ["linkedin", "none", "unknown"]:
                        # LinkedIn as company is a common extraction bug
                        warnings.append("⚠️ SUSPICIOUS COMPANY (Empty or LinkedIn)")

                    if warnings:
                        msg += "--- 🛑 WARNINGS ---\n" + "\n".join(warnings) + "\n\n"

                    if added:
                        msg += f"✅ ADDED: {', '.join(added)}\n"
                    if updated:
                        msg += f"🔄 UPDATED: {', '.join(updated)}\n"
                    
                    if blob:
                        # Clean blob: remove potential trailing '...' from manual Note label if any
                        blob = blob.strip()
                        msg += f"\n--- PROPOSED SYNC BLOCK ---\n{blob}\n--------------------------\n"
                    
                    msg += "\nValidate these changes?"
                    
                    title = f"LSAMC v{__version__} [{i+1}/{total}]"
                    
                    # Loop to allow "Show Finder" without closing the review sequence
                    while True:
                        # v2.5: Exit, Skip, Apply (default)
                        # We use a sub-menu for "Apply" to allow "Apply All" (Finish All) without hitting 3-button limit
                        res = self.bridge.show_native_dialog(
                            msg, 
                            title=title, 
                            buttons=["Exit", "Skip", "Apply..."], 
                            default_button="Apply...",
                            cancel_button="Exit"
                        )
                        
                        choice = None
                        if res.get("success"):
                            btn = res["button"]
                            if btn == "Exit":
                                choice = 'q'
                            elif btn == "Skip":
                                choice = 'skip'
                            elif btn == "Apply...":
                                # Sub-menu for Apply options
                                sub_res = self.bridge.show_native_dialog(
                                    f"Apply options for {contact_name}:",
                                    buttons=["Apply This", "Apply All (Auto)", "Back"],
                                    default_button="Apply This",
                                    cancel_button="Back"
                                )
                                if sub_res.get("success"):
                                    sub_btn = sub_res["button"]
                                    if sub_btn == "Apply This":
                                        choice = 'y'
                                    elif sub_btn == "Apply All (Auto)":
                                        choice = 'y'
                                        validate_all = True
                                    else:
                                        continue # Back to main dialog
                                else:
                                    continue # Back to main dialog
                        elif res.get("cancelled"):
                            choice = 'q'
                            break
                        else:
                            # Fallback
                            choice = 'skip'
                            break
                        
                        if choice: break # Exit inner while loop if a decision was made
                
                if choice == 'y':
                    print("   Validated.")
                    self.validate_contact(session_path, contact_name, folder_name=c_dir)
                elif choice == 'skip':
                    print(f"   Skipping {contact_name} (Permanent for this session).")
                    with open(os.path.join(path, ".skipped"), "w") as f:
                        f.write(datetime.now().isoformat())
                elif choice == 'q':
                    print("   Quitting review.")
                    break
            else:
                print(f"   Role: {data.get('current_role')}")
                print(f"   Note: logs/sessions/{os.path.basename(session_path)}/backups/{c_dir}/linkedin.txt")

    async def _finalize_sync(self, contact_id, contact_name, profile, photo_path, vcard_res, orig_photo_path, was_retry: bool = False) -> str:
        """Final steps: Artifact saving, bridge update, and auditing."""
        
        # v1.5.6: Safety check for empty name (Fixes "Sync Results for : SUCCESS")
        if not profile.full_name or profile.full_name.strip() == "":
            logger.warning(f"⚠️ Profile had empty name! Fallback to known contact name: {contact_name}")
            profile.full_name = contact_name

        # 5.5 Handle photo status mapping for bridge (moved from sync_profile during refactor)
        photo_status = None
        if profile.photo_url:
            if str(profile.photo_url).lower().endswith(".png"):
                 photo_status = "photo_error"
            if not photo_path:
                 photo_status = "photo_unavailable"

        # 6. Final Sync & Audit (LinkedIn State)
        res = self.bridge.update_contact(contact_id, profile, photo_path=photo_path, photo_status=photo_status, orig_photo_path=orig_photo_path)
        
        # 7. Save profile as JSON for staging/apply workflow (v1.1.0: include proposed changes)
        safe_name = "".join([c if c.isalnum() else "_" for c in contact_name])
        contact_backup_dir = os.path.join(self.backup_dir, safe_name)
        os.makedirs(contact_backup_dir, exist_ok=True)
        profile_json_path = os.path.join(contact_backup_dir, "profile.json")
        dump = profile.model_dump(mode="json")
        dump["_contact_id"] = contact_id 
        dump["_photo_status"] = photo_status
        if was_retry:
            dump["_hi_res_retry_performed"] = True
            
        # Capture bridge metadata for review
        if res.get("simulated"):
            prop_changes = {
                "added": res.get("added_fields", []),
                "updated": res.get("updated_fields", []),
                "note_blob": res.get("proposed_note", ""),
                "sync_block_changed": res.get("sync_block_changed", False)
            }
            dump["_proposed_changes"] = prop_changes
            
            # v1.5.0: Sync Block History Requirement
            # "Keep a sync block history for each contact that has been staged then updated"
            # We save the PROPOSED sync block to a history file in the staging folder.
            try:
                history_path = os.path.join(contact_backup_dir, "sync_block_history.md")
                timestamp = datetime.now().isoformat()
                
                # Extract just the block for history
                block_content = ""
                import re
                match = re.search(r"(<Linkedin-AI-sync.*?</Linkedin-AI-sync>)", prop_changes["note_blob"], re.DOTALL | re.IGNORECASE)
                if match:
                    block_content = match.group(1)
                else:
                    block_content = "(No Sync Block generated)"
                
                with open(history_path, "a") as hf:
                    hf.write(f"\n\n## Staged: {timestamp}\n")
                    hf.write(f"**Changed**: {prop_changes['sync_block_changed']}\n")
                    hf.write(f"**Added**: {', '.join(prop_changes['added'])}\n")
                    hf.write(f"**Updated**: {', '.join(prop_changes['updated'])}\n")
                    hf.write("```xml\n")
                    hf.write(block_content)
                    hf.write("\n```\n")
            except Exception as e:
                logger.error(f"Failed to save sync block history: {e}")

        with open(profile_json_path, "w") as f:
            json.dump(dump, f, indent=2)
        logger.debug(f"Saved staging profile to: {profile_json_path}")
        
        # Save proposed state
        proposed_note = res.get("proposed_note") or str(profile)
        self._create_backup(contact_name, proposed_note, "linkedin", "txt")
        
        # Simulate LinkedIn vCard for audit
        if vcard_res["success"]:
            orig_vcf = vcard_res["output"]
            if photo_path: profile._temp_photo_path = photo_path
            mod_vcf = self._simulate_vcard_changes(orig_vcf, profile, proposed_note)
            self._create_backup(contact_name, mod_vcf, "linkedin", "vcf")

        if self.mode == "SIMULATION":
            logger.info(f"AUDIT COMPLETE: All artifacts saved to {self.backup_dir}")
        else:
            # Capture real state after update to confirm
            new_state = self.bridge.get_contact_details(contact_id)
            if new_state["success"]:
                new_vcard = self.bridge.get_vcard(contact_id)
                if new_vcard["success"]:
                    self._create_backup(contact_name, new_vcard["output"], "actual_after", "vcf")

        # Cleanup photo
        if photo_path and os.path.exists(photo_path):
            try: os.remove(photo_path)
            except: pass

        if not res["success"]:
            logger.error(f"Update failed: {res.get('error')}")
            return "ERROR_UPDATE_FAILED"
            
        # v1.7.3: Clean up any .resync flags
        try:
            old_resyncs = glob.glob(f"logs/sessions/*/backups/{safe_name}/.resync")
            for old_f in old_resyncs:
                os.remove(old_f)
        except: pass

        # v5.0.0: Update Company Knowledge Base (Feedback Loop)
        if profile and profile.company:
            self.kb.learn(profile.company)

        return "SUCCESS"


async def async_main(args):
    logger.info("🚀 SYSTEM LAUNCH: Tier 3 Agent Starting...")
    agent = LinkedInSyncAgent(mode=args.mode, api_key=args.api_key, headless=args.headless, vault_only=args.vault_only, ab_test=args.ab_test)
    # Ensure a clean slate before starting
    if not args.vault_only:
        await agent._kill_orphaned_chrome()
    try:
        if args.apply:
            if not args.session:
                logger.error("--session required for --apply")
                return
            await agent.apply_session(args.session)
        elif args.apply_all:
            if not args.session:
                logger.error("--session required for --apply-all")
                return
            agent.validate_all_in_session(args.session)
            await agent.apply_session(args.session)
        elif args.review:
            if not args.session:
                logger.error("--session required for --review")
                return
            await agent.review_session(args.session)
        elif args.validate_all:
            if not args.session:
                logger.error("--session required for --validate-all")
                return
            agent.validate_all_in_session(args.session)
        elif args.validate_name:
            if not args.session:
                logger.error("--session required for --validate")
                return
            agent.validate_contact(args.session, args.validate_name)
        elif args.selection:
            await agent.sync_selection(limit=args.limit, offset=args.offset, reverse=args.reverse, last=args.last)
        elif args.archive:
            await agent.archive_applied_contacts(group_name=args.group or "script-LSAM-Golden Record")
        elif args.group:
            await agent.sync_group(args.group, limit=args.limit, offset=args.offset, reverse=args.reverse, last=args.last, force=args.force)
        elif not args.name and not args.url:
            target_group = "no photo LinkedIn 1 line note"
            logger.info(f"No target specified. Defaulting to group: {target_group}")
            await agent.sync_group(target_group, limit=args.limit, offset=args.offset, reverse=args.reverse, last=args.last, force=args.force)
        else:
            if args.name:
                for n in args.name:
                    await agent.sync_profile(args.url, n, force=args.force)
            else:
                await agent.sync_profile(args.url, None, force=args.force)
    except Exception as e:
        print(f"DEBUG: Exception in async_main: {e}")
        traceback.print_exc()
    finally:
        await agent.close()

import traceback

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Sync Agent (LSAMC)")
    parser.add_argument("--url", help="LinkedIn Profile URL")
    parser.add_argument("--name", action="append", help="Name(s) of contacts in macOS Contacts")
    parser.add_argument("--group", help="Name of a macOS Contacts group to sync")
    parser.add_argument("--selection", action="store_true", help="Sync contacts currently selected in macOS Contacts")
    parser.add_argument("--mode", choices=["SIMULATION", "FULL"], default="SIMULATION", help="Run mode")
    parser.add_argument("--api-key", help="Google AI API Key")
    parser.add_argument("--limit", type=int, help="Limit the number of contacts to sync in batch mode")
    parser.add_argument("--offset", type=int, default=0, help="Skip N contacts from the start")
    parser.add_argument("--last", type=int, help="Take only the last N contacts from the list")
    parser.add_argument("--reverse", action="store_true", help="Process contacts in reverse order")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    
    # Staging Workflow
    parser.add_argument("--session", help="Path to a session directory for review/apply")
    parser.add_argument("--validate", dest="validate_name", help="Mark a contact as validated in a session")
    parser.add_argument("--validate-all", action="store_true", help="Mark all contacts in a session as validated")
    parser.add_argument("--apply", action="store_true", help="Apply validated backups from a session to macOS")
    parser.add_argument("--apply-all", action="store_true", help="Validate and Apply all contacts from a session")
    parser.add_argument("--review", action="store_true", help="Interactive session review")
    parser.add_argument("--vault-only", action="store_true", help="Only use local SPOT vault, skip LinkedIn")
    parser.add_argument("--archive", action="store_true", help="Remove applied contacts from the Golden Record group")
    parser.add_argument("--ab-test", action="store_true", help="Enable Hybrid Extraction A/B testing")
    parser.add_argument("--force", action="store_true", help="Force sync even if contact was successfully synced today or in history")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG)
    
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("Sync interrupted by user.")
    except Exception as e:
        print(f"FATAL ERROR in main: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
