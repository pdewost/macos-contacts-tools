
from src.bridge.contact_macos import ContactMacOSBridge
import logging
logging.basicConfig(level=logging.ERROR)
bridge = ContactMacOSBridge()
groups = bridge.list_groups().get("groups", [])
print(f"{'Group Name':<40} | {'Count':<5}")
print("-" * 50)
for g in groups:
    if "LSAM" in g:
        contacts = bridge.list_group_contacts(g).get("matches", [])
        print(f"{g:<40} | {len(contacts):<5}")
