import os
import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuthBridge")

def bridge_auth(project_root: str):
    source_profile = Path(project_root) / "data" / "agent_chrome_profile" / "Default"
    target_profile = Path(project_root) / "data" / "fast_agent_chrome_profile" / "Default"

    if not source_profile.exists():
        logger.error(f"Source profile not found at {source_profile}")
        return False

    os.makedirs(target_profile, exist_ok=True)

    # 1. Cookies
    cookie_file = source_profile / "Cookies"
    if cookie_file.exists():
        logger.info(f"💾 Copying Cookies...")
        shutil.copy2(cookie_file, target_profile / "Cookies")
    else:
        logger.warning("No Cookies file found in source profile.")

    # 2. Local Storage
    ls_dir = source_profile / "Local Storage"
    if ls_dir.exists():
        logger.info(f"💾 Copying Local Storage...")
        target_ls = target_profile / "Local Storage"
        if target_ls.exists():
            shutil.rmtree(target_ls)
        shutil.copytree(ls_dir, target_ls)
        
    # 3. Preferences (Optional but helpful for extensions/window state)
    pref_file = source_profile / "Preferences"
    if pref_file.exists():
        logger.info(f"💾 Copying Preferences...")
        shutil.copy2(pref_file, target_profile / "Preferences")

    logger.info("✨ Auth Bridge complete. Fast Engine profile is now primed.")
    return True

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    bridge_auth(project_root)
