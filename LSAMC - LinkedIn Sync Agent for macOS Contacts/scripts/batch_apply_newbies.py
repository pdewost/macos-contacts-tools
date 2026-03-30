#!/usr/bin/env python3
"""
LSAM Batch Apply Utility (v0.7.4)
----------------------------------
Automates the application of staged profiles (Photo + Sync Block) for high-confidence Newbies.
Usage: python3 scripts/batch_apply_newbies.py --limit 5
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.bridge.contact_macos import ContactMacOSBridge
from src.models.profile import LinkedInProfile
from src.agent.sync_agent import LinkedInSyncAgent

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BatchApply")

VAULT_ROOT = PROJECT_ROOT / "data" / "vault"
PRIORITY_FILE = PROJECT_ROOT / "data" / "priority_newbies.json"

def get_vault_path(uuid):
    if not VAULT_ROOT.exists(): return None
    
    # 1. Active Vault
    for item in VAULT_ROOT.iterdir():
        if item.is_dir():
            if item.name.startswith(uuid): return item
            pfile = item / "profile.json"
            if pfile.exists():
                try:
                    pdata = json.loads(pfile.read_text())
                    if pdata.get("_contact_id") == uuid: return item
                except: pass
                
    # 2. Archived Vault
    ARCHIVE_ROOT = VAULT_ROOT / "archived"
    if ARCHIVE_ROOT.exists():
        for session in sorted(ARCHIVE_ROOT.iterdir(), reverse=True):
            if session.is_dir():
                for item in session.iterdir():
                    if item.is_dir():
                        if item.name.startswith(uuid): return item
                        pfile = item / "profile.json"
                        if pfile.exists():
                            try:
                                pdata = json.loads(pfile.read_text())
                                if pdata.get("_contact_id") == uuid: return item
                            except: pass
    return None

def main():
    parser = argparse.ArgumentParser(description="Batch Apply Newbies")
    parser.add_argument("--limit", type=int, default=5, help="Max candidates to process")
    args = parser.parse_args()

    if not PRIORITY_FILE.exists():
        logger.error(f"Priority file not found: {PRIORITY_FILE}")
        sys.exit(1)

    try:
        with open(PRIORITY_FILE, "r") as f:
            all_newbies = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON: {e}")
        sys.exit(1)

    if not all_newbies:
        print("RESULT|FINISHED|No newbies to process")
        return

    bridge = ContactMacOSBridge(mode="FULL")
    agent = None
    count = 0
    results = []

    for item in all_newbies:
        if count >= args.limit: break
        
        cid = item.get("uuid")
        name = item.get("name")
        
        logger.info(f"--- Processing {count+1}/{args.limit}: {name} ({cid}) ---")
        
        folder = get_vault_path(cid)
        if not folder:
            logger.warning(f"Vault not found for {name}")
            continue
            
        profile_file = folder / "profile.json"
        if not profile_file.exists():
            logger.warning(f"Profile missing for {name}")
            continue
            
        try:
            profile_dict = json.loads(profile_file.read_text())
            # Ensure pydantic model (v2.5 safety)
            profile_obj = LinkedInProfile.model_validate(profile_dict)
            
            # Photo Resolution (v0.7.5: Robust detection)
            photo_path = None
            # 1. Try HEIC (High Res)
            heics = list(folder.glob("*linkedin.heic"))
            if heics:
                photo_path = str(heics[0])
            else:
            # 2. Try raw JPG
                jpgs = list(folder.glob("*linkedin-raw.jpg"))
                if jpgs:
                    photo_path = str(jpgs[0])
            
            # 3. SCRAPE ON DEMAND (v0.7.5: Replay support)
            if not photo_path:
                logger.info(f"Photo missing for {name}. Triggering Scrape-on-demand...")
                if not agent:
                    logger.info("Initializing Hardened Sync Agent...")
                    agent = LinkedInSyncAgent(mode="FULL", headless=True)
                    # Force check auth to identify owner (Philippe leak prevention)
                    import asyncio
                    asyncio.run(agent.check_auth())
                    
                li_url = profile_dict.get("linkedin_url")
                if li_url:
                    logger.info(f"Targeting: {li_url}")
                    import asyncio
                    # Use extraction logic to get a fresh profile and photos
                    new_profile = asyncio.run(agent.extract_profile(li_url))
                    if new_profile:
                        # Re-check folder for new photos
                        heics = list(folder.glob("*linkedin.heic"))
                        if heics:
                            photo_path = str(heics[0])
                        else:
                            jpgs = list(folder.glob("*linkedin-raw.jpg"))
                            if jpgs:
                                photo_path = str(jpgs[0])
                        
                        # Refresh profile data for bridge
                        profile_obj = new_profile
                        logger.info(f"Scrape-on-demand SUCCESS for {name}")
                    else:
                        logger.warning(f"Scrape-on-demand FAILED for {name}")
                
            # Original Guard
            orig_photo_path = None
            origs = list(folder.glob("*original.jpg"))
            if origs:
                orig_photo_path = str(origs[0])
                
            # UPDATE
            res = bridge.update_contact(
                contact_id=cid,
                profile=profile_obj,
                photo_path=photo_path,
                orig_photo_path=orig_photo_path
            )
            
            if res.get("success"):
                logger.info(f"SUCCESS: Applied {name}")
                # Mark as applied in vault
                (folder / ".applied").touch()
                print(f"RESULT|SUCCESS|{cid}|{name}")
                count += 1
            else:
                logger.error(f"FAIL: {res.get('error')}")
                print(f"RESULT|FAIL|{cid}|{name}|{res.get('error')}")
                
        except Exception as e:
            logger.error(f"EXCEPTION: {e}")
            print(f"RESULT|ERROR|{cid}|{name}|{str(e)}")

    print(f"RESULT|SUMMARY|Processed {count} contacts")

if __name__ == "__main__":
    main()
