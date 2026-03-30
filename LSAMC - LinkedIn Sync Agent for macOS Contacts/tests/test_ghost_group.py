
import subprocess

def discover_available_groups():
    """
    Copy of logic from supervisor.py
    """
    try:
        script = 'tell application "Contacts" to get name of every group'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if res.returncode != 0: 
            print(f"⚠️ AppleScript Error: {res.stderr}")
            return []
        
        raw_output = res.stdout.strip()
        if not raw_output: return []
        
        groups = [g.strip() for g in raw_output.split(',')]
        groups = [g for g in groups if g and g.lower() not in ["missing value", "null", "none"]]
        return groups
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return []

def test_filtering():
    print("🧪 Testing Ghost Group Logic...")
    
    # 1. Discover Real Groups
    available = discover_available_groups()
    print(f"✅ Discovered {len(available)} groups.")
    
    # 2. Define Queue with a GHOST
    GhostName = "script-LSAM-Ghost-XYZ-123"
    GroupQueue = [
        "script-LSAM-Force-Refresh", 
        GhostName, 
        "script-LSAM-Tier3-NeedAttention"
    ]
    
    # 3. Intersect
    queue = [g for g in GroupQueue if g in available]
    
    print(f"📋 Input Queue: {GroupQueue}")
    print(f"📉 Filtered Queue: {queue}")
    
    if GhostName in queue:
        print("❌ FAIL: Ghost group was NOT filtered out! Logic is broken.")
    else:
        print("✅ PASS: Ghost group was correctly filtered.")

if __name__ == "__main__":
    test_filtering()
