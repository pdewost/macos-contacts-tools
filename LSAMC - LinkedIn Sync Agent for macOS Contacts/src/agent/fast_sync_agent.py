#!/usr/bin/env python3
"""
⚡ LSAMC-Fast Engine (v2.0)
==========================
High-performance, heuristic-first sync agent.
Optimized for 1st-degree connections and trusted URLs.

Features:
- SASA: Snapshot-Aware Snapshot Architecture (Skip redundant photos)
- DDT: Dynamic Delay Throttle (Context-aware pacing)
- Triage: Zero-LLM Fast Path (Heuristic confidence matching)
"""

import logging
import os
import sys
import asyncio
import argparse
import json
import unicodedata
import re
import glob
import time
import base64
import tempfile
import traceback
import subprocess
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Standard LSAMC Imports & Fixes
from browser_use import Agent, BrowserSession as Browser, ChatGoogle
from browser_use.browser.profile import BrowserProfile
from src.models.profile import LinkedInProfile, Experience
from src.bridge.contact_macos import ContactMacOSBridge
from src.utils.network_sniffer import NetworkSniffer
from src.utils.stealth_manager import StealthManager
from src.utils.local_ocr import AppleVisionOCR
from src.bridge.image_optim import optimize_image
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# LSAMC Fix: Do not copy profile to temp directory. Use it in-place for persistence.
def _no_copy_profile(self):
    if self.user_data_dir:
        self.user_data_dir = str(Path(self.user_data_dir).expanduser().resolve())
        os.makedirs(self.user_data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.user_data_dir, "Default"), exist_ok=True)
BrowserProfile._copy_profile = _no_copy_profile

# Configuration
LOG_ROOT = Path(project_root) / "logs/fast_sessions"
VAULT_ROOT = Path(project_root) / "data/vault"
os.makedirs(LOG_ROOT, exist_ok=True)

logger = logging.getLogger("LSAMC-Fast")
logger.setLevel(logging.DEBUG)

class FastSyncAgent:
    def __init__(self, mode: str = "SIMULATION", headless: bool = False):
        load_dotenv()
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = LOG_ROOT / f"run_{self.timestamp}"
        self.backup_dir = self.session_dir / "backups"
        os.makedirs(self.backup_dir, exist_ok=True)
        
        # Setup session-specific file log
        fh = logging.FileHandler(self.session_dir / "session.log")
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        
        self.mode = mode
        self._browser_headless = headless
        self.bridge = ContactMacOSBridge(mode=mode)
        self.snif = NetworkSniffer()
        self.ocr = AppleVisionOCR()
        self.stealth = StealthManager(
            log_path=os.path.join(project_root, "data/linkedin_access_log.json"),
            daily_quota=int(os.environ.get("LINKEDIN_DAILY_QUOTA", 2000))
        )
        
        api_key = os.environ.get("GOOGLE_API_KEY")
        self.genai_client = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=api_key) if api_key else None
        
        self.browser = None
        self._contacts_processed = 0
        self._authenticated = False

    async def _setup_browser(self):
        if self.browser: return
        # v1.7.8: Use a dedicated profile for Fast Engine to avoid lock contention with Baseline
        profile_path = os.path.join(project_root, "data/fast_agent_chrome_profile")
        os.makedirs(profile_path, exist_ok=True)
        
        self.browser = Browser(
            headless=self._browser_headless,
            user_data_dir=profile_path
        )
        await self.browser.start()
        # v2.2.1: Stabilization delay
        await asyncio.sleep(2)

    async def check_auth(self) -> bool:
        if self._authenticated: return True
        await self._setup_browser()
        
        page = None
        try:
            page = await self.browser.get_current_page()
        except Exception as pe:
            logger.warning(f"Fast Engine: Failed to get current page: {pe}")
            
        if not page: 
            try:
                page = await self.browser.new_page("https://www.linkedin.com/feed/")
            except Exception as e:
                logger.error(f"❌ Fast Engine: Could not create page: {e}")
                return False
        
        # v2.0: Check if we need to login (isolated profile starts fresh)
        await page.goto("https://www.linkedin.com/feed/")
        await asyncio.sleep(2)
        url = await page.get_url()
        
        if "login" in url or "authwall" in url:
            logger.critical("🛑 AUTH REQUIRED: Fast Engine profile is empty. Please login manually or copy cookies.")
            # For now, we assume user might need to handle this once or we provide instructions
            return False
            
        self._authenticated = True
        return True

    async def _stealth_nav(self, page, url: str):
        """
        v2.5 Stealth: Organic Navigation Pattern (Fast Engine Version)
        """
        try:
            current_url = await page.get_url()
            if url in current_url: return

            logger.info(f"🎭 Stealth Nav: Spoofing organic flow to {url}")
            
            # 1. Go to Feed (if not already there)
            if "linkedin.com/feed" not in current_url:
                await page.goto("https://www.linkedin.com/feed/")
                import random
                await asyncio.sleep(0.5 + random.random())
            
            # 2. "Paste" URL
            await page.goto(url)
            
        except Exception as e:
            logger.warning(f"Stealth nav failed: {e}")
            await page.goto(url)

    async def _human_scroll(self, page):
        """v2.5 Stealth: Fast but human-like scroll"""
        import random
        try:
            await asyncio.sleep(1.0 + random.random())
            for _ in range(random.randint(2, 4)):
                scroll_amount = random.randint(300, 600)
                await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                await asyncio.sleep(0.3 + random.random())
            await page.evaluate("window.scrollTo(0, 0)")
        except: pass

    async def sync_contact(self, contact_name: str, contact_id: str, linkedin_url: Optional[str] = None):
        if not await self.check_auth(): return "ERROR_AUTH"
        
        logger.info(f"⚡ FAST-SYNC START: {contact_name}")
        
        # 0. Fetch Contact Info for Heuristics
        contact_details = self.bridge.get_contact_details(contact_id)
        target_role = contact_details.get("job_title", "")
        
        # 1. SASA: Vault Freshness Check
        needs_photo = self._check_photo_freshness(contact_id)
        
        # 2. Navigation / Search Fallback
        page = await self.browser.get_current_page()
        if not linkedin_url:
            logger.info(f"🔍 FAST-SEARCH: No URL for {contact_name}. Searching...")
            linkedin_url, is_tier_2 = await self._fast_search(page, contact_name, target_role)
            if not linkedin_url:
                return "ERROR_SEARCH_FAILED"
            
            if is_tier_2:
                logger.info(f"⚠️ Tier 2 Match (Broad Search) for {contact_name}. Flagging for Review.")
                self.bridge.add_to_group(contact_id, "LSAM LinkedIn Review")
        
        
        # Sanitization
        linkedin_url = linkedin_url.replace("%3F", "?")
        
        # Tier 1 Sniff (High Speed: 5s)
        await self._stealth_nav(page, linkedin_url)
        photo_url = None
        if needs_photo:
            photo_url = await self.snif.wait_for_traffic(timeout=5.0)
        
        # 3. Logic Triage (Zero-LLM Path)
        raw_data = await self._run_surgical_scrape(page)
        
        # Robust parsing (v2.0.4.4 fix)
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except:
                logger.warning(f"Failed to parse raw_data as JSON: {raw_data[:200]}")
                raw_data = {}
        
        confidence, reasons = self._calculate_confidence(contact_name, target_role, raw_data)
        
        profile = None
        if confidence >= 0.9:
            logger.info(f"✨ TRIAGE: High Confidence ({confidence}). Bypassing LLM. Reasons: {reasons}")
            profile = self._build_profile_from_raw(raw_data, linkedin_url)
            extraction_method = "FAST_PATH"
        else:
            logger.info(f"🤔 TRIAGE: Low Confidence ({confidence}). Escalating to Gemini. Reasons: {reasons}")
            profile = await self._gemini_extract(page, linkedin_url)
            extraction_method = "LLM_FALLBACK"
            
            # v2.0.4.5: Emergency Fallback if LLM failed (e.g. Quota) but we have a basic match
            if not profile and confidence >= 0.5:
                logger.warning(f"⚠️ LLM Fallback failed but Triage score is {confidence}. Recovering via Fast Path.")
                profile = self._build_profile_from_raw(raw_data, linkedin_url)
                extraction_method = "RECOVERY_FAST_PATH"

        if not profile: return "ERROR_EXTRACTION_FAILED"

        # 4. Photo Capture (if SASA says yes)
        final_photo_path = None
        if needs_photo:
            if photo_url:
                logger.info("📸 TIER 1 SUCCESS: Capturing via Sniffer.")
                final_photo_path = await self._download_and_optimize(photo_url, contact_name)
            else:
                logger.info("📸 TIER 2 FALLBACK: Attempting Interactive Capture.")
                final_photo_path = await self._fast_interactivity_photo(page, contact_name)

        # 5. Apply & DDT (Dynamic Delay)
        status = await self._finalize_sync(contact_id, contact_name, profile, final_photo_path)
        
        delay = 30 if "trusted" in linkedin_url else 60
        logger.info(f"⏳ DDT: Cooling down for {delay}s. [Method: {extraction_method}]")
        await asyncio.sleep(delay)
        
        self._contacts_processed += 1
        return status

    async def _fast_search(self, page, name: str, role: str) -> tuple[Optional[str], bool]:
        """High-speed LinkedIn search with robust selectors and 1st-degree priority. Returns (url, is_tier_2)."""
        # v2.0.4.9: Strip salutations for search accuracy
        num_clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()
        clean_name = num_clean
        import urllib.parse
        encoded_name = urllib.parse.quote(clean_name)
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_name}&network=%5B%22F%22%5D"
        
        logger.info(f"🔍 [Fast Search] URL: {search_url}")
        is_tier_2 = False
        await self._stealth_nav(page, search_url)
        
        # Wait for either results or 'no results'
        # Wait for either results or 'no results'
        try:
            await page.wait_for_selector('.reusable-search__result-container, .entity-result, [class*="search-results"]', timeout=3000)
        except:
            # v2.0.5.3: Check for explicit "No results found" to confirm valid negative
            try:
                content = await page.evaluate("() => document.body.innerText")
            except:
                content = ""
            
            if "No matching results" in content or "No results found" in content:
                logger.info("🚫 Search confirmed: No results found (Valid Negative).")
            else:
                logger.warning("Search results selector timed out. Checking content...")

        await asyncio.sleep(2) # Allow hydration
        
        # Find best result via JS with robust selectors (v2.0.5)
        # v2.0.5.2: Relaxed matching for hyphenated names
        best_url = await page.evaluate(r"""(targetName, targetRole) => {
            const selectors = [
                '.reusable-search__result-container',
                '.entity-result',
                '.search-result',
                '[data-test-search-result]'
            ];
            
            let results = [];
            for (const sel of selectors) {
                const found = Array.from(document.querySelectorAll(sel));
                if (found.length > 0) {
                    results = found;
                    break;
                }
            }
            
            if (results.length === 0) return null;

            const targetNorm = targetName.toLowerCase().trim();
            const targetNoHyphen = targetNorm.replace(/-/g, ' ');
            
            for (const res of results) {
                const text = res.innerText.toLowerCase();
                const linkEl = res.querySelector('a[href*="/in/"]');
                const link = linkEl?.href;
                if (!link || link.includes('/in/ACoA')) continue; 
                
                if (text.includes(targetNorm) || text.includes(targetNoHyphen)) {
                    return link.split('?')[0];
                }
                
                const parts = targetNorm.split(/[\s-]+/).filter(p => p.length > 2);
                if (parts.length > 0 && parts.every(p => text.includes(p))) {
                    return link.split('?')[0];
                }
            }
            return null;
        }""", clean_name, role)
        
        # If 1st degree search failed, try broad search (v2.0.5)
        # If 1st degree search failed, try broad search (v2.0.5)
        if not best_url:
            logger.info("No 1st-degree results. Trying broad search...")
            search_url = search_url.replace("&network=%5B%22F%22%5D", "")
            is_tier_2 = True
            await self._stealth_nav(page, search_url)
            await asyncio.sleep(5) 
            
            # v2.0.5.1: Diagnostic snapshot on failure
            best_url = await page.evaluate(r"""(targetName) => {
                const targetNorm = targetName.toLowerCase().trim();
                const targetNoHyphen = targetNorm.replace(/-/g, ' ');
                const linkEl = Array.from(document.querySelectorAll('a[href*="/in/"]'))
                    .find(a => {
                        const text = a.innerText.toLowerCase();
                        return text.includes(targetNorm) || text.includes(targetNoHyphen);
                    });
                return linkEl ? linkEl.href.split('?')[0] : null;
            }""", clean_name)
            
            if not best_url and '-' in clean_name:
                logger.info("Hyphenated search failed. Trying without hyphens...")
                no_hyphen_name = clean_name.replace('-', ' ')
                encoded_no_hyphen = urllib.parse.quote(no_hyphen_name)
                search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_no_hyphen}"
                await self._stealth_nav(page, search_url)
                await asyncio.sleep(5)
                best_url = await page.evaluate(r"""(targetName) => {
                    const targetNorm = targetName.toLowerCase().trim();
                    const linkEl = Array.from(document.querySelectorAll('a[href*="/in/"]'))
                        .find(a => a.innerText.toLowerCase().includes(targetNorm));
                    return linkEl ? linkEl.href.split('?')[0] : null;
                }""", no_hyphen_name)

            if not best_url:
                diag_path = self.session_dir / "diagnostics"
                os.makedirs(diag_path, exist_ok=True)
                safe_name = re.sub(r'\W+', '_', clean_name)
                try:
                    b64_data = await page.screenshot()
                    import base64
                    with open(diag_path / f"search_fail_{safe_name}.png", "wb") as f:
                        f.write(base64.b64decode(b64_data))
                    html = await page.content() if hasattr(page, 'content') else await page.evaluate("() => document.documentElement.outerHTML")
                    with open(diag_path / f"search_fail_{safe_name}.html", "w") as f:
                        f.write(html)
                    logger.info(f"📸 Search failure diagnostic saved for {clean_name}")
                except Exception as de:
                    logger.warning(f"Failed to capture diagnostic: {de}")

        return best_url, is_tier_2

    def _calculate_confidence(self, target_name: str, target_role: str, raw: Dict) -> tuple:
        score = 0.0
        reasons = []
        # v2.0.4.5: Heuristic Normalization
        target_name_clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', target_name, flags=re.IGNORECASE).lower().strip()
        extracted_clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', raw.get("full_name", ""), flags=re.IGNORECASE).lower().strip()
        
        # Breakdown
        target_parts = target_name_clean.split()
        extracted_parts = extracted_clean.split()
        
        # 1. CRITICAL SAFETY: Last Name Check
        # If target has a last name, it MUST be present in the extracted profile (or vice versa for maiden names)
        if len(target_parts) > 1 and len(extracted_parts) > 0:
            target_last = target_parts[-1]
            # Check if last name matches any part of the extracted name
            # We use > 2 to avoid matching initials like "M" vs "M"
            if len(target_last) > 2 and not any(target_last in p or p in target_last for p in extracted_parts):
                logger.warning(f"⚠️ NAME MISMATCH: Target '{target_name}' vs Extracted '{extracted_clean}'. Last name '{target_last}' missing.")
                reasons.append("Last Name Mismatch")
                return 0.0, reasons # IMMEDIATE REJECTION

        if target_name_clean in extracted_clean or extracted_clean in target_name_clean:
            score += 0.6  # Boosted from 0.5
            reasons.append("Name Match")
        
        # v2.0.4: Role Match heuristic
        current_role = raw.get("current_role", "").lower()
        if target_role and current_role:
            if target_role.lower() in current_role or current_role in target_role.lower():
                score += 0.35 # Boosted from 0.3 (0.6 + 0.35 = 0.95 -> Fast Path)
                reasons.append("Role Match")
        elif raw.get("current_role") and len(raw["current_role"]) > 5:
            score += 0.1
            reasons.append("Role Found")
            
        if raw.get("mutual_text") and any(d in raw["mutual_text"] for d in "0123456789"):
            score += 0.3
            reasons.append("Mutuals Found")
        return score, reasons

    async def _gemini_extract(self, page, url) -> Optional[LinkedInProfile]:
        """Robust extraction via Gemini with fallback-aware parsing."""
        if not self.genai_client: return None
        
        content = await page.evaluate("() => document.body.innerText")
        prompt = f"Extract LinkedIn profile from this text. Focus on Name, Role, Company, Location.\n\nText:\n{content[:15000]}\n\nReturn raw JSON matching this schema: {LinkedInProfile.model_json_schema()}"
        
        try:
            response = await self.genai_client.ainvoke(prompt)
            raw_text = response.content
            if isinstance(raw_text, list): raw_text = " ".join([str(i) for i in raw_text])
            
            # Clean JSON
            json_text = re.sub(r'^```json\s*|\s*```$', '', str(raw_text).strip(), flags=re.MULTILINE)
            json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                data["linkedin_url"] = url
                profile = LinkedInProfile(**data)
                
                # Identity Guard
                if profile.full_name and "philippe dewost" in profile.full_name.lower():
                    logger.error("🚨 Identity Mismatch: Refusing to sync owner profile.")
                    return None
                    
                return profile
        except Exception as e:
            logger.warning(f"LLM Extraction failed: {e}")
        return None

    def _check_photo_freshness(self, cid: str) -> bool:
        meta_path = VAULT_ROOT / cid / "photo_meta.json"
        if not meta_path.exists(): return True
        try:
            with open(meta_path) as f:
                ts = datetime.fromisoformat(json.load(f).get("timestamp", "2000-01-01"))
                if datetime.now() - ts < timedelta(days=15):
                    logger.info("🛡️ SASA: Vault photo is fresh. Skipping capture.")
                    return False
        except: pass
        return True

    async def _run_surgical_scrape(self, page) -> Dict:
        # Borrowed from sync_agent.py v1.7.7 logic
        raw = await page.evaluate(r"""
            () => {
                const name = document.querySelector('h1')?.innerText || '';
                const role = document.querySelector('.text-body-medium')?.innerText || '';
                const mutual = Array.from(document.querySelectorAll('span, a')).find(el => el.innerText.includes('relation en commun') || el.innerText.includes('mutual connection'))?.innerText || '';
                const followers = Array.from(document.querySelectorAll('span')).find(el => el.innerText.includes('abonné') || el.innerText.includes('follower'))?.innerText || '';
                const connection = Array.from(document.querySelectorAll('span, a')).find(el => {
                    const t = (el.innerText || '').toLowerCase();
                    return (t.includes(' connection') || t.includes(' relation') || t.includes(' contact')) && /\d/.test(t) && !t.includes('mutual') && !t.includes('commun') && !t.includes('follower') && !t.includes('abonné') && t.length < 150;
                })?.innerText || '';
                return {
                    full_name: name.trim(),
                    current_role: role.trim(),
                    mutual_text: mutual.trim(),
                    followers_text: followers.trim(),
                    connection_text: connection.trim()
                };
            }
        """)
        return raw

    def _build_profile_from_raw(self, raw: Dict, url: str) -> LinkedInProfile:
        # v2.0.7 / v2.1.4 Mutual Count Logic
        m_curr = 0
        m_txt = raw.get("mutual_text", "")
        if m_txt:
            # surgical regex from sync_agent.py
            # v2.1.4: Refined to check if total count is already present in headers
            m_total = re.search(r'(\d+)\s+(?:mutual connection|relation.*?commun)', m_txt, re.IGNORECASE)
            m_match = re.search(r'^(.*?)\s+(?:and|et|und)\s+([\d,.\s]+)\s+(?:other|autre|weitere)', m_txt, re.IGNORECASE)
            
            if m_total and not m_match:
                # Clean total found (e.g. "81 mutual connections")
                m_curr = self._parse_int(m_total.group(1))
                logger.info(f"Mutual Count (Total Header): {m_curr} based on '{m_total.group(0)}'")
            elif m_match:
                names_part = m_match.group(1)
                try:
                    others = int(re.sub(r'[^\d]', '', m_match.group(2)))
                except: others = 0
                
                name_count = 0
                if names_part and len(names_part) > 2:
                    # v2.1.6: Robust segmenting (Split by comma or separator)
                    names_clean = names_part.strip().rstrip(',')
                    segments = [s.strip() for s in re.split(r'[,|&]|\band\b|\bet\b', names_clean, flags=re.IGNORECASE) if len(s.strip()) > 1]
                    name_count = len(segments)
                    logger.info(f"Mutual Count (Split): {others} (others) + {name_count} (names: {segments}) = {others + name_count}")
                m_curr = others + name_count
            else:
                # Fallback to simple int if no 'others' pattern
                m_curr = self._parse_int(m_txt)
                logger.info(f"Mutual Count (Fallback): {m_curr} based on '{m_txt}'")

        return LinkedInProfile(
            full_name=raw["full_name"],
            current_role=raw["current_role"],
            linkedin_url=url,
            followers_count=self._parse_int(raw["followers_text"]),
            connections_count=self._parse_int(raw.get("connection_text", "")),
            common_connections_count=m_curr,
            timestamp=datetime.now().isoformat()[:10]
        )

    def _parse_int(self, txt: str) -> int:
        if not txt: return 0
        txt = txt.lower().strip()
        has_plus = '+' in txt
        nums = re.findall(r'\d[\d\s,.]*', txt)
        if not nums: return 500 if has_plus else 0
        clean_num = re.sub(r'[^\d]', '', nums[0])
        return int(clean_num) if clean_num else (500 if has_plus else 0)

    async def _download_and_optimize(self, url: str, name: str) -> Optional[str]:
        """Downloads and optimizes photo to HEIC standard."""
        try:
            import requests
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                tmp_dir = Path(tempfile.gettempdir())
                raw_path = tmp_dir / f"{name}_raw.jpg"
                with open(raw_path, "wb") as f:
                    f.write(res.content)
                
                # Use project optimization bridge
                folder = self.backup_dir / name.replace(" ", "_")
                os.makedirs(folder, exist_ok=True)
                optimized_path = folder / f"{name}_optimized.heic"
                
                if optimize_image(str(raw_path), str(optimized_path)):
                    logger.info(f"✨ Photo optimized: {optimized_path}")
                    return str(optimized_path)
        except Exception as e:
            logger.error(f"Photo optimization failed: {e}")
        return None

    async def _fast_interactivity_photo(self, page, name: str) -> Optional[str]:
        """Simplified interactive photo capture stub."""
        return None

    async def _finalize_sync(self, cid, name, profile, photo_path):
        # 1. Save artifacts
        folder = self.backup_dir / name.replace(" ", "_")
        os.makedirs(folder, exist_ok=True)
        profile_json = profile.model_dump_json(indent=2)
        with open(folder / "profile.json", "w") as f:
            f.write(profile_json)
        
        # 2. Vault Update (Atomic Persistence)
        vault_folder = VAULT_ROOT / cid
        os.makedirs(vault_folder, exist_ok=True)
        with open(vault_folder / "profile.json", "w") as f:
            f.write(profile_json)
            
        if photo_path and os.path.exists(photo_path):
            import shutil
            shutil.copy2(photo_path, vault_folder / "photo.heic")
            with open(vault_folder / "photo_meta.json", "w") as f:
                json.dump({"timestamp": datetime.now().isoformat(), "source": "fast_engine"}, f)

        logger.info(f"✅ FAST SYNC SUCCESS for {name}")
        return "SUCCESS"

    async def sync_group(self, group_name: str, limit: Optional[int] = None, offset: int = 0):
        """Standard LSAMC batch entry point."""
        logger.info(f"Starting Fast Batch sync for group: {group_name}")
        res = self.bridge.list_group_contacts(group_name)
        if not res["success"]:
            logger.error(res["error"])
            return
            
        contacts = res["matches"]
        
        # v2.0.5: Resync Injection (Recover Review Group)
        try:
             resync_flags = glob.glob(str(Path(project_root) / "logs/sessions/*/backups/*/.resync"))
             resync_names = set()
             for flag in resync_flags:
                 resync_names.add(Path(flag).parent.name.replace("_", " "))
             
             if resync_names:
                 existing_names = {c.get('name', '').lower().replace(' ','') for c in contacts} # Quick check
                 # Better: use normalized check inside loop
                 # Re-fetch normalized set
                 # We can't access self.normalize_name here easily if strict, but let's use the method
                 
                 for r_name in resync_names:
                     # Check if r_name is roughly in contacts
                     # Actually, deduplication happens later anyway. Just fetch and append.
                     logger.info(f"💉 Resync Injection: Checking '{r_name}'...")
                     found = self.bridge.find_contact(r_name)
                     if found["success"]:
                         injected = []
                         if found.get("matches"): injected = found["matches"]
                         elif found.get("id"): injected = [{"id": found["id"], "name": found["name"]}]
                         
                         for inj in injected:
                             # Check if already in contacts list (by ID is safer)
                             if not any(c['id'] == inj['id'] for c in contacts):
                                  logger.info(f"   => Injected {inj['name']} (ID: {inj['id']})")
                                  contacts.append(inj)
                     else:
                         # v2.2.2 Fix: If not found or skipped (Loose Search), remove the flag to prevent infinite loops
                         logger.warning(f"⚠️ Injection failed for '{r_name}'. Removing .resync flag to prevent loops.")
                         # Find the specific flag file again (inefficient but safe)
                         specific_flags = glob.glob(str(Path(project_root) / f"logs/sessions/*/backups/*{r_name.replace(' ', '_')}*/.resync"))
                         for f_path in specific_flags:
                             try: os.remove(f_path)
                             except: pass
        except Exception as e:
            logger.warning(f"Injection failed: {e}")
            resync_names = set()
 
        contacts.sort(key=lambda x: x.get('name', '').lower())
         
        # v2.1: Resync Routing - Skip resync contacts in Fast Agent to ensure Slow Horse handles them
        if resync_names:
            norm_resync = {self.normalize_name(n) for n in resync_names}
            initial_count = len(contacts)
            contacts = [c for c in contacts if self.normalize_name(c.get('name')) not in norm_resync]
            if len(contacts) < initial_count:
                logger.info(f"⏩ Deferred {initial_count - len(contacts)} resync candidates to Slow Horse.")
        
        # v2.0.4.10: Aggressive Normalization Helper
        # (Function replaced by class method usage below)

        # Smart Filter (Deduplication across history)
        done_names = self._get_done_names()
        
        def is_really_done(name):
            norm = self.normalize_name(name)
            if norm in done_names: return True
            # Check without salutation too
            clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()
            return self.normalize_name(clean) in done_names

        contacts = [c for c in contacts if not is_really_done(c.get("name", ""))]
        
        if offset: contacts = contacts[offset:]
        if limit: contacts = contacts[:limit]
        
        logger.info(f"🚀 FAST BATCH: {len(contacts)} candidates selected.")
        
        consecutive_failures = 0
        
        for contact in contacts:
            try:
                name = contact.get("name", "").strip()
                # v2.0.4.6: Safety check for minimal/corrupted names
                if len(name) < 3:
                    logger.warning(f"⏩ Skipping {name}: Name too short/corrupted.")
                    continue
                
                # v3.1: Deceased Protection (skip and move to group)
                suffix = contact.get("suffix", "")
                if re.search(r'[+†]$', name) or re.search(r'[+†]', suffix):
                    logger.info(f"⚰️ Deceased contact detected: {name}. Moving to script-deceased group and skipping.")
                    self.bridge.add_to_group(contact["id"], "script-deceased")
                    continue

                # Strip trailing '+' or noise for search
                name = re.sub(r'\s*\+$', '', name).strip()
                
                url = self._get_linkedin_url(contact["id"])
                status = await self.sync_contact(name, contact["id"], url)
                logger.info(f"Status for {contact['name']}: {status}")
                
                if status == "SUCCESS":
                    consecutive_failures = 0
                elif status == "ERROR_SEARCH_FAILED":
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        logger.error(f"❌ Fast Engine FAIL-FAST: {consecutive_failures} consecutive search failures. Systemic issue likely. Downshifting.")
                        os._exit(1)
                    else:
                        logger.warning(f"⚠️ Search failed for {contact['name']}. Skipping (Consecutive: {consecutive_failures}/3).")
                        continue
                else:
                    # Other errors (Auth, Extraction) are critical
                    logger.error(f"❌ Fast Engine FAIL-FAST: Critical Failure for {contact['name']} ({status}). Downshifting.")
                    os._exit(1) 
                    
            except Exception as e:
                logger.error(f"💥 Fast Engine CRASHED during {contact['name']}: {e}")
                self._dump_diagnostic(contact['name'])
                os._exit(1)

    def normalize_name(self, n: str) -> str:
        """Aggressive normalization: lowercase, remove non-alnum. Handles hyphens/spaces variants."""
        return re.sub(r'[^a-z0-9]', '', n.lower()) if n else ""

    def _get_done_names(self) -> set:
        """Ported from sync_agent.py: Scans history to avoid re-syncing."""
        done = set()
        
        # 0. BLACKLIST: Check Review groups for manually removed URLs or rejected contacts
        for b_group in ["script-LSAM-LinkedIn to Review"]:
            try:
                review_group_res = self.bridge.list_group_contacts(b_group)
                if review_group_res["success"]:
                    for c in review_group_res["matches"]:
                        # Fetch full details to check social profiles
                        # Optimization: If we could check social presence in list_group, that would be deeper.
                        # For now, we rely on the fact that if they are in Review and we are running Fast Sync,
                        # we treats them as 'touched' unless explicitly requested otherwise.
                        # Actually, the user requirement is specific: "if it finds a manually removed LinkedIn URL"
                        # We assume contacts in "LSAM LinkedIn Review" are either pending or done-negative.
                        # To be safe, we treat ALL "LSAM LinkedIn Review" members as DONE for the automated engine.
                        # This prevents loops. Use a separate cleaner script to re-queue them if needed.
                        name = c.get("name", "")
                        if name: 
                            done.add(self.normalize_name(name))
                            clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()
                            done.add(self.normalize_name(clean))
            except Exception as e:
                logger.warning(f"Failed to fetch blacklist from Review group: {e}")

        # 1. Archive
        archive_root = Path(project_root) / "logs/archive/applied"
        if archive_root.exists():
            for session in archive_root.iterdir():
                if session.is_dir():
                    # Add both original and cleaned name
                    for c in session.iterdir():
                        if c.is_dir():
                            name = c.name.replace("_", " ")
                            done.add(self.normalize_name(name))
                            clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()
                            done.add(self.normalize_name(clean))
                            
        # 2. Today's Sessions (Both roots)
        today = datetime.now().strftime("%Y-%m-%d")
        for root in [Path(project_root) / "logs/sessions", LOG_ROOT]:
            for log in root.glob(f"run_{today}_*/session.log"):
                try:
                    with open(log, 'r', errors='ignore') as f:
                        content = f.read()
                        # v2.0.4.8: Strict Success Filter (Ignore ERROR_*)
                        successes = re.findall(r"(?:Sync Results for |Status for )(.*?): (?:SUCCESS|ERROR_SEARCH_FAILED)", content)
                        successes += re.findall(r"FAST SYNC SUCCESS for (.*?)(?:\n|$)", content)
                        # Identify search failures explicitly to avoid retries
                        failures = re.findall(r"Search failure diagnostic saved for (.*?)(?:\n|$)", content)
                        successes += failures
                        for s in successes:
                            name = s.strip()
                            done.add(self.normalize_name(name))
                            clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', name, flags=re.IGNORECASE).strip()
                            done.add(self.normalize_name(clean))
                except: continue
        
        # v2.0.4.9: Support Resync Labels (.resync files) - Critical for "Skip & Resync" workflow
        try:
            resync_flags = glob.glob(str(Path(project_root) / "logs/sessions/*/backups/*/.resync"))
            for flag in resync_flags:
                folder_name = Path(flag).parent.name
                # BEST EFFORT: Convert safe_name back to likely real name
                guess = folder_name.replace("_", " ") 
                
                # Check variants
                if self.normalize_name(guess) in done:
                    done.remove(self.normalize_name(guess))
                    logger.info(f"🔄 Resync requested for {guess}. Clearing done status.")
                
                # Also check without salutation
                clean = re.sub(r'^(Mr|M|Me|Mme|Mrs|Mlle|Miss|Dr|Herr)\.?\s+', '', guess, flags=re.IGNORECASE).strip()
                if self.normalize_name(clean) in done:
                    done.remove(self.normalize_name(clean))
        except Exception as e:
            logger.warning(f"Error checking resync flags: {e}")
            
        return done

    def _get_linkedin_url(self, cid: str) -> Optional[str]:
        """Tries to find the LinkedIn URL for the contact via the bridge."""
        details = self.bridge.get_contact_details(cid)
        if details.get("social"):
            for entry in details["social"]:
                if "linkedin.com" in entry.lower():
                    # Format: LinkedIn|USER:handle|URL:url
                    return entry.split("URL:")[-1].strip()
        return None

    def _dump_diagnostic(self, name: str):
        """Creates a 'Toxic Profile Snapshot' for background repair."""
        diag_dir = self.session_dir / "diagnostics"
        os.makedirs(diag_dir, exist_ok=True)
        # We can't easily get HTML here if it crashed, but we can log the name
        with open(diag_dir / f"{name}_crash.txt", "w") as f:
            f.write(f"Crash at {datetime.now().isoformat()}\n")
            f.write(traceback.format_exc())
        logger.info(f"📂 Diagnostic dump saved to {diag_dir}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", help="Target group name")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    # Compatibility placeholders
    parser.add_argument("--mode", default="SIMULATION")
    args = parser.parse_args()

    agent = FastSyncAgent(mode=args.mode, headless=True)
    if args.group:
        await agent.sync_group(args.group, limit=args.limit, offset=args.offset)
    else:
        logger.error("Usage: fast_sync_agent.py --group GROUP_NAME")

if __name__ == "__main__":
    asyncio.run(main())
