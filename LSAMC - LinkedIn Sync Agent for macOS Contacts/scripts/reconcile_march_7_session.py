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
ID_FILE = "/tmp/march_7_ids.txt"

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
    pairs = get_pairs(ID_FILE)
    if not pairs:
        logger.error(f"No pairs found in {ID_FILE}.")
        return

    bridge = ContactMacOSBridge(mode="FULL")
    
    logger.info(f"Adding {len(pairs)} contacts to group '{TARGET_GROUP}'")
    
    success_count = 0
    fail_count = 0
    
    for name, contact_id in pairs:
        logger.info(f"Processing: {name} (ID: {contact_id})...")
        
        # We have the ID! Directly add it to the group.
        res = bridge.add_to_group(contact_id, TARGET_GROUP)
        if res.get("success"):
            logger.info(f"  ✅ Added to '{TARGET_GROUP}'")
            success_count += 1
        else:
            logger.warning(f"  ❌ Failed to add to group: {res.get('error')}")
            fail_count += 1

    logger.info(f"Reconciliation Complete. Total successes: {success_count}/{len(pairs)}")
    print("\n--- Summary of Modified Contacts ---")
    for name, cid in pairs:
        print(f"- {name}")

if __name__ == "__main__":
    main()
