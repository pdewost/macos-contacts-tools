
import asyncio
import json
from src.bridge.contact_macos import ContactMacOSBridge

async def get_stats():
    bridge = ContactMacOSBridge(mode="FULL")
    groups = [
        "script-LSAM-Tier3-NeedAttention",
        "script-LSAM-Cleanup-Mutuals",
        "script-LSAM-Tier2-NoteHasLinkedIn",
        "script-LSAM-LinkedIn to Review",
        "script - no photo and on LinkedIn",
        "script-LSAM-Exempted",
        "script-LSAM-Force-Refresh"
    ]
    
    stats = {}
    for g in groups:
        res = bridge.list_group_contacts(g)
        if res["success"]:
            stats[g] = len(res["matches"])
        else:
            stats[g] = f"Error: {res.get('error')}"
            
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    asyncio.run(get_stats())
