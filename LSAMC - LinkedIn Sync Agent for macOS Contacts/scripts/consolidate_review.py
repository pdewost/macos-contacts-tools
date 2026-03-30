
import os
import shutil
import json
from datetime import datetime

def consolidate_batch_1():
    # Use the same logic as our audit script to find the paths
    sessions_dir = "logs/sessions"
    contact_map = {}
    sessions = sorted([s for s in os.listdir(sessions_dir) if s.startswith("run_2026-01-27") or s.startswith("run_2026-01-28")])
    
    for session_name in sessions:
        session_path = os.path.join(sessions_dir, session_name)
        backups_dir = os.path.join(session_path, "backups")
        if not os.path.exists(backups_dir): continue
        for contact_dir in os.listdir(backups_dir):
            contact_path = os.path.join(backups_dir, contact_dir)
            json_path = os.path.join(contact_path, "profile.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r") as f: data = json.load(f)
                    name = data.get("full_name") or contact_dir.replace("_", " ")
                    if os.path.exists(os.path.join(contact_path, ".applied")): continue
                    if not (data.get("current_role") or data.get("company")): continue
                    
                    score = 10
                    if data.get("photo_url"): score += 5
                    
                    if name not in contact_map or score > contact_map[name]['score']:
                        contact_map[name] = {"path": contact_path, "score": score, "dir": contact_dir}
                except: continue

    # Create meta-session
    meta_name = f"meta_batch_1_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    meta_path = os.path.join(sessions_dir, meta_name)
    meta_backups = os.path.join(meta_path, "backups")
    os.makedirs(meta_backups, exist_ok=True)
    
    # Touch a log file so review works
    with open(os.path.join(meta_path, "session.log"), "w") as f:
        f.write("Batch 1 Consolidation Log\n")
        
    for name, info in contact_map.items():
        dest = os.path.join(meta_backups, info['dir'])
        # Symlink or copy? Let's symlink to save space and keep it live
        try:
            os.symlink(os.path.abspath(info['path']), dest)
        except FileExistsError:
            pass
            
    print(f"Meta-session created: {meta_path}")
    print(f"Contains {len(contact_map)} contacts.")
    return meta_path

if __name__ == "__main__":
    consolidate_batch_1()
