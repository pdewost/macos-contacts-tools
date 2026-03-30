import os
import re
import json
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# --- Settings ---
LOG_MAP_FILE = Path("/tmp/lsam_sync_map.txt")
DRY_RUN = False # LIVE UPDATES
REPORT_DIR = Path("/Users/pdewost/Documents/Personnel/Developpement/macOS Contacts Management/LSAMC - LinkedIn Sync Agent for macOS Contacts/logs")
REPAIR_REPORT = REPORT_DIR / "mutual_repairs_report.md"
FAILURE_REPORT = REPORT_DIR / "mutual_repairs_failures.md"

def parse_robust_int(txt):
    if not txt: return 0
    txt = txt.replace('\xa0', ' ').replace('\u00a0', ' ').lower().strip()
    if " and " in txt or " et " in txt or "other" in txt or "autre" in txt:
        m_other = re.search(r'([\d,.\s]+)\s+(?:other|autre|others|autres)', txt)
        base_val = 0
        if m_other:
            base_val = int(re.sub(r'[^0-9]', '', m_other.group(1)) or 0)
        relevant_line = txt
        for line in txt.split('\n'):
            if any(k in line for k in ['other', 'autre', 'mutual', 'commun']):
                relevant_line = line
                break
        names_part = relevant_line
        if m_other and m_other.start() > 0:
            names_part = relevant_line[:m_other.start()].strip()
        parts = re.split(r'\s+and\s+|\s+et\s+|,', names_part)
        noise_keywords = ['other', 'autre', 'follower', 'abonné', 'partners', 'group', 'company', 'associé', 'founder', 'fondateur']
        name_count = 0
        for p in parts:
            s = p.strip()
            if len(s) > 2 and not any(k in s.lower() for k in noise_keywords):
                if not any(char.isdigit() for char in s):
                    name_count += 1
        if base_val > 0 or name_count > 0:
            return base_val + name_count
    nums = re.findall(r'([\d,.\s]+)', txt)
    if not nums:
        lower_txt = txt.lower()
        if any(k in lower_txt for k in ['mutual', 'commun', 'contact', 'relation', 'shared']): return 1
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

def get_degree(segment, candidate_info=None):
    if "Tier 2 Match" in segment or "Broad Search" in segment: return 2
    if "Tier 3 Match" in segment: return 3
    if candidate_info:
        degree_str = candidate_info.lower()
        if re.search(r'\b2(?:nd|e|d|ème|eme)\b', degree_str): return 2
        if re.search(r'\b3(?:rd|e|d|ème|eme)\b', degree_str): return 3
        if re.search(r'\b1(?:st|er|ere|ère)\b', degree_str): return 1
    return 1

def run_applescript(script):
    process = subprocess.Popen(['osascript', '-e', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = process.communicate()
    return out.strip(), err.strip()

async def main():
    print(f"--- LSAM Global Mutual Connections Repair (Pass 6 - ULTIMATE PRECISION) ---")
    
    # 1. Load Sync Map
    print(f"Loading sync map...")
    name_to_logs = defaultdict(list)
    if LOG_MAP_FILE.exists():
        with open(LOG_MAP_FILE, "r") as f:
            for line in f:
                m = re.match(r"(.*?):.*Syncing:\s+(.*)", line)
                if m:
                    log_path, val = m.groups()
                    clean_val = re.sub(r'\(LSAMC.*?\)', '', val).strip().lower()
                    name_to_logs[clean_val].append(log_path)

    # 2. Discovery
    print("Finding contacts...")
    uids = set()
    # Hybrid Discovery: combine grep, priorities, and broad AppleScript
    cmd = 'grep -r -a -l "Mutual connections" ~/Library/Application\\ Support/AddressBook/Sources/'
    try:
        raw_paths = subprocess.check_output(cmd, shell=True, text=True).strip().split('\n')
        for p in raw_paths:
            if p: uids.add(Path(p).stem)
    except: pass
    
    # Explicit Priorities (IDs from previous investigations)
    uids.add("ACD4389D-3045-4C76-876A-EF3B3AFF0929:ABPerson") # Atha
    uids.add("E858B988-62DC-4A34-B9EC-D2C1B162F00C:ABPerson") # Amiel
    
    as_missed = 'tell application "Contacts" to get id of every person whose note contains "Linkedin-AI-sync"'
    raw_missed, _ = run_applescript(as_missed)
    if raw_missed:
        for mid in raw_missed.split(","):
            uids.add(mid.strip().replace(":ABPerson", ""))

    uids_list = sorted(list(uids))
    print(f"Auditing {len(uids_list)} unique contact IDs...")

    stats = {"processed": 0, "correct": 0, "corrected": 0, "failed_logs": 0}
    corrections_details = []
    failures_details = []

    batch_size = 10 # Safer batching
    for i in range(0, len(uids_list), batch_size):
        batch = uids_list[i:i+batch_size]
        as_inner = ""
        for bid in batch:
            full_id = bid if ":" in bid else f"{bid}:ABPerson"
            as_inner += f'try\nset p to person id "{full_id}"\nset end of r to (id of p & "|#|" & name of p & "|#|" & note of p)\non error\n-- skip\nend try\n'
        as_script = f'tell application "Contacts"\nset r to {{}}\n{as_inner}\nset AppleScript\'s text item delimiters to "||||"\nreturn r as string\nend tell'
        res, _ = run_applescript(as_script)
        if not res: continue
        
        for c_data in res.split("||||"):
            if not c_data: continue
            parts = c_data.split("|#|")
            if len(parts) < 3: continue
            cid, name, note = parts
            stats["processed"] += 1
            
            # Match Line - support space before colon and various line endings
            # Pass 6: Handle degree inside parenthesis before optional space and colon
            m_regex = r'Mutual connections([\s\(\w\)]*)\s?:\s?([\d]+)(?: \(was ([\d]+)\))?'
            m_match = re.search(m_regex, note)
            if not m_match: 
                # Try finding just "Mutual connections" without the rest to be sure
                if "Mutual connections" in note:
                    print(f"DEBUG: Found 'Mutual connections' in {name} but regex failed. Note tail: {note[-50:]}")
                continue
            
            full_match_text = m_match.group(0)
            curr_val = int(m_match.group(2))
            was_val = m_match.group(3)

            raw_text = None
            found_degree = 1
            sn = name.lower().strip()
            sn_clean = re.sub(r'^(mr|mme|m|mrs|ms|dr)\.?\s+', '', sn)
            
            candidate_logs = []
            if sn in name_to_logs: candidate_logs = name_to_logs[sn]
            elif sn_clean in name_to_logs: candidate_logs = name_to_logs[sn_clean]
            else:
                for k in name_to_logs:
                    if sn_clean in k:
                        candidate_logs.extend(name_to_logs[k])
                        break
            
            if candidate_logs:
                for log_path in sorted(list(set(candidate_logs)), reverse=True):
                    try:
                        content = Path(log_path).read_text()
                        idx = content.lower().find(f"syncing: {sn}")
                        if idx == -1: idx = content.lower().find(f"syncing: {sn_clean}")
                        if idx != -1:
                            sync_end = content.find("Sync Results for", idx + 1)
                            if sync_end == -1: sync_end = len(content)
                            segment = content[idx:sync_end]
                            parse_match = re.search(r"\[Surgical\] Parsing mutuals from fresh text: '(.*?)'", segment, re.DOTALL)
                            if parse_match:
                                raw_text = parse_match.group(1)
                                cand_match = re.search(r"search results.*?Info: (.*?)\n", segment, re.IGNORECASE) or re.search(r"Candidate:.*?Info: (.*?)\n", segment, re.IGNORECASE)
                                info_txt = cand_match.group(1) if cand_match else None
                                found_degree = get_degree(segment, info_txt)
                            break
                    except: pass
                    if raw_text: break
            
            if not raw_text:
                stats["failed_logs"] += 1
                failures_details.append(f"| {name} | No log found |")
                # Even if log fails, apply formatting fix if needed
                new_degree = found_degree # Likely defaulted to 1
                degree_label = f" ({new_degree}nd)" if new_degree == 2 else f" ({new_degree}rd)" if new_degree == 3 else ""
                # Mandatory space before colon
                new_line = f"Mutual connections{degree_label} : {curr_val}"
                if was_val: new_line += f" (was {was_val})"
                
                if new_line != full_match_text:
                     print(f"FORMAT {name}: '{full_match_text}' -> '{new_line}'")
                     if not DRY_RUN:
                        new_note = note.replace(full_match_text, new_line)
                        as_update = f'tell application "Contacts" to set note of person id "{cid}" to {json.dumps(new_note)}'
                        run_applescript(as_update + "\n" + "save")
                continue

            # Format: Mutual connections (degree) : count
            new_val = parse_robust_int(raw_text)
            degree_label = ""
            if found_degree > 1:
                deg_s = "nd" if found_degree == 2 else "rd" if found_degree == 3 else "th"
                degree_label = f" ({found_degree}{deg_s})"
            
            new_line = f"Mutual connections{degree_label} : {new_val}"
            if was_val:
                diff = new_val - curr_val
                new_was = int(was_val) + diff
                new_line += f" (was {new_was})"
            
            if new_line == full_match_text:
                stats["correct"] += 1
            else:
                stats["corrected"] += 1
                print(f"UPDATE {name}: '{full_match_text}' -> '{new_line}'")
                corrections_details.append(f"| {name} | {full_match_text} | {new_line} |")
                if not DRY_RUN:
                    new_note = note.replace(full_match_text, new_line)
                    as_update = f'tell application "Contacts" to set note of person id "{cid}" to {json.dumps(new_note)}'
                    # Added explicit SAVE
                    run_applescript(as_update + "\n" + "tell application \"Contacts\" to save")

        print(f"  Processed {min(i+batch_size, len(uids_list))}/{len(uids_list)}...")

    # 5. Reports
    report_header = f"# 🛠️ Mutual Connections Repair Report ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n\n"
    report_header += f"- **Total Audited**: {stats['processed']}\n"
    report_header += f"- **Correct**: {stats['correct']} ({stats['correct']*100/stats['processed']:.1f}%)\n"
    report_header += f"- **Corrected**: {stats['corrected']} ({stats['corrected']*100/stats['processed']:.1f}%)\n"
    report_header += f"- **Failed (Missing Logs)**: {stats['failed_logs']} (Logs missing from agent history but formatting updated if possible)\n\n"
    
    with open(REPAIR_REPORT, "w") as f:
        f.write(report_header + "## 📝 Correction Details\n\n| Contact | Previous State | New State |\n| :--- | :--- | :--- |\n" + "\n".join(corrections_details))
    with open(FAILURE_REPORT, "w") as f:
        f.write(report_header + "## ❌ Failures Details\n\n| Contact | Reason |\n| :--- | :--- |\n" + "\n".join(failures_details))
    print(f"\nFinal report written to: {REPAIR_REPORT}")

if __name__ == "__main__":
    asyncio.run(main())
