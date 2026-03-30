import os
import sys
import logging
from typing import List, Tuple

# Setup path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.bridge.contact_macos import ContactMacOSBridge

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_GROUP = "script-LSAM-7 mars session"
ID_FILE_FIXED = "/tmp/march_7_ids_fixed.txt"
ID_FILE_ORIGINAL = "/tmp/march_7_ids.txt"

def get_pairs(file_path: str) -> List[Tuple[str, str]]:
    if not os.path.exists(file_path):
        return []
    pairs = []
    with open(file_path, 'r') as f:
        for line in f:
            if "|" in line:
                name, cid = line.strip().split("|", 1)
                pairs.append((name, cid))
    return pairs

def main():
    fixed_pairs = get_pairs(ID_FILE_FIXED)
    original_pairs = get_pairs(ID_FILE_ORIGINAL)
    
    if not fixed_pairs:
        logger.error(f"No fixed pairs found.")
        return

    bridge = ContactMacOSBridge(mode="FULL")
    
    # Identify contacts to remove (those in original but not in fixed)
    fixed_ids = {p[1] for p in fixed_pairs}
    to_remove = [p for p in original_pairs if p[1] not in fixed_ids]
    
    logger.info(f"Cleaning up {len(to_remove)} simulated contacts from group '{TARGET_GROUP}'")
    for name, contact_id in to_remove:
        logger.info(f"Removing: {name} (ID: {contact_id})...")
        res = bridge.remove_from_group(contact_id, TARGET_GROUP)
        if res.get("success"):
            logger.info(f"  ✅ Removed from '{TARGET_GROUP}'")
        else:
            logger.warning(f"  ❌ Failed to remove: {res.get('error')}")

    logger.info(f"Ensuring {len(fixed_pairs)} actually-modified contacts are in group '{TARGET_GROUP}'")
    for name, contact_id in fixed_pairs:
        # Just in case some were missing
        bridge.add_to_group(contact_id, TARGET_GROUP)

    logger.info(f"Reconciliation Cleaned. {len(fixed_pairs)} contacts remain in group.")

if __name__ == "__main__":
    main()
