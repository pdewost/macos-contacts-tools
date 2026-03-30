from pydantic import BaseModel, Field, HttpUrl, field_validator, ConfigDict
from typing import List, Optional
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

class Experience(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None

class Education(BaseModel):
    school: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class LinkedInProfile(BaseModel):
    # v5.6: validate_assignment=True ensures @field_validator fires on post-construction
    # attribute assignment too (e.g. profile.last_name = "..."), not only at __init__.
    # Without this, direct assignment bypasses the v5.5 placeholder guard entirely.
    model_config = ConfigDict(validate_assignment=True)

    full_name: str
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    suffix: Optional[str] = None
    
    current_role: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    summary: Optional[str] = None
    linkedin_url: str
    _handle_suspect: bool = False  # v4.8: Flag for handles that failed validation
    photo_blocked: bool = False   # v5.4: Flag for blocked identity photos
    force_photo: bool = False     # v2.4.16 Part B: Set by --force-photo CLI flag; bypasses all staleness checks and forces photo update

    # v5.5: Name Poisoning Guards (INCIDENT_POISONING_20260316)
    @field_validator('full_name', 'first_name', 'last_name', mode='before')
    @classmethod
    def block_placeholder_names(cls, v):
        """Block strings like 'Information not available' from entering name fields."""
        if not v or not isinstance(v, str):
            return v
        
        PLACEHOLDERS = {
            "information not available", "not available",
            "available",                              # partial write of "not available"
            "no data available", "data not available", "data unavailable",
            "n/a", "unknown", "page doesn’t exist", "page not found",
            "no information available",
            "the world’s largest professional network",
            "linkedin member", "member",              # partial "linkedin member"
        }

        low_v = v.lower().strip()
        # Also block prefix matches like "no data available in the provided..."
        if low_v in PLACEHOLDERS or any(low_v.startswith(p) for p in PLACEHOLDERS):
            logger.warning(f"v5.5 Guard: Blocking placeholder name value: '{v}'")
            return None
        return v

    # v4.8 B1-FIX: LinkedIn URL Sanitization Validator
    @field_validator('linkedin_url', mode='before')
    @classmethod
    def sanitize_linkedin_url(cls, v):
        """Strip leading //, prefix bare www., and flag space-containing URLs."""
        if not v or not isinstance(v, str):
            return v or ""
        url = v.strip()
        # Strip leading // (e.g. //www.linkedin.com/in/slug)
        if url.startswith('//'):
            url = 'https:' + url
            logger.warning(f"v4.8 B1-FIX: Stripped leading // from linkedin_url: {v} -> {url}")
        # Prefix bare www. (e.g. www.linkedin.com/in/slug)
        elif url.startswith('www.'):
            url = 'https://' + url
            logger.warning(f"v4.8 B1-FIX: Prefixed https:// to linkedin_url: {v} -> {url}")
        return url
    photo_url: Optional[str] = None
    
    # Contact Info
    @field_validator('emails', mode='before')
    @classmethod
    def validate_emails(cls, v):
        """v5.1: Strict email validation - An email cannot contain a space."""
        if not isinstance(v, list): return v
        clean = []
        for email in v:
            if email and isinstance(email, str):
                # Rule: First space terminates the address
                s = email.split()[0]
                if '@' in s: clean.append(s)
        return clean
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    websites: List[str] = Field(default_factory=list)
    birthday: Optional[str] = None
    connected_date: Optional[str] = None
    connection_degree: Optional[int] = None # 1, 2, 3
    
    # Social Stats
    followers_count: Optional[int] = None
    connections_count: Optional[int] = None
    connections_raw: Optional[str] = None # e.g. "500+ connections"
    common_connections_count: Optional[int] = None
    mutual_groups: List[str] = Field(default_factory=list)
    mutual_raw: Optional[str] = None
    
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat()[:10])

    @property
    def is_disappeared(self) -> bool:
        """Returns True if the profile appears to be a 404/Disappeared marker."""
        error_keywords = [
            "page doesn’t exist", "page not found", "لم يتم العثور على الصفحة", 
            "n'avons pas pu trouver cette page", "information not available",
            "profile not available"
        ]
        return any(k in self.full_name.lower() for k in error_keywords) if self.full_name else False

    def to_dict(self) -> dict:
        """Helper for legacy/internal code expecting to_dict()"""
        # pydantic v1/v2 compatibility
        return self.model_dump() if hasattr(self, "model_dump") else self.dict()

    def get_clean_role(self) -> str:
        """
        v5.4: Returns a clean, professional role title — richness-aware.

        Key insight: LinkedIn users pack multi-dimensional branding into their headline
        using '|' separators (e.g. "substans.ai Founder | AI Expert | 25+ Years").
        The FIRST segment is their curated primary role. Comparing the FULL headline
        length against a bare experience title always made the experience win (v5.3 bug).

        Decision logic:
          1. Strip 'at/chez [Company]' redundancy and '| LinkedIn' suffix.
          2. Extract headline_primary = first '|' or '•' segment (or full string if no separator).
          3. If headline_primary is a bare single-word generic title (Founder, CEO, Partner…)
             AND experience[0].title has ≥ 3 words: prefer experience (it's more specific).
          4. If headline_primary itself is > 80 chars AND experience is shorter: prefer experience.
          5. Otherwise: use headline_primary.
             Tie goes to headline_primary — users curate it deliberately as their primary signal.
        """
        # v5.4: Bare single-word generic titles that alone are under-informative as a job title.
        # Two-word combos (e.g. "Senior Partner", "Co-Founder") are considered specific enough.
        _BARE_GENERIC = {
            'founder', 'co-founder', 'ceo', 'cto', 'cfo', 'coo', 'cpo', 'chro', 'cso',
            'partner', 'director', 'vp', 'svp', 'evp', 'md', 'gm',
            'manager', 'consultant', 'advisor', 'associate', 'analyst',
            'engineer', 'developer', 'designer', 'president', 'chairman',
            'head', 'lead', 'principal', 'executive',
        }

        role = (self.current_role or "").strip()
        if not role:
            return role

        # Step 1: Cleanup redundancy (at/chez [Company])
        company_clean = (self.company or "").strip().lower()
        if company_clean:
            patterns = [
                rf"\s+at\s+{re.escape(company_clean)}$",
                rf"\s+chez\s+{re.escape(company_clean)}$",
                rf"\s+@\s+{re.escape(company_clean)}$",
            ]
            for p in patterns:
                role = re.sub(p, "", role, flags=re.IGNORECASE).strip()

        # Step 1b: Suffix pruning (e.g. "... | LinkedIn")
        role = re.sub(r"\s*\|\s*LinkedIn$", "", role, flags=re.IGNORECASE).strip()

        # Step 2: Extract headline_primary — first segment before ' | ' or ' • '
        if " | " in role:
            headline_primary = role.split(" | ")[0].strip()
        elif " • " in role:
            headline_primary = role.split(" • ")[0].strip()
        else:
            headline_primary = role  # No separators — entire string is the primary role

        # Step 3-5: Compare headline_primary against experience[0].title
        exp_role = (self.experience[0].title.strip() if self.experience else "")

        if exp_role:
            hp_words = headline_primary.lower().split()
            is_bare_generic = (len(hp_words) == 1 and hp_words[0] in _BARE_GENERIC)
            # Prefer experience ONLY in two cases:
            prefer_exp = (
                # Case A: headline_primary is a bare single-word generic AND exp has ≥ 3 words
                (is_bare_generic and len(exp_role.split()) >= 3)
                # Case B: headline_primary segment itself is unusually long AND exp is concise
                or (len(headline_primary) > 80 and len(exp_role) < len(headline_primary))
            ) and len(exp_role) < 120  # sanity cap on experience title

            if prefer_exp:
                logger.info(
                    f"v5.4: Preferring experience '{exp_role}' over headline primary '{headline_primary}' "
                    f"(bare_generic={is_bare_generic}, hp_len={len(headline_primary)}, exp_len={len(exp_role)})"
                )
                return exp_role

        # Default: use headline_primary (first segment, or full string if no separators)
        if headline_primary != role:
            logger.info(f"v5.4: Using headline primary '{headline_primary}' (trimmed from full headline).")
        return headline_primary

    def get_handle(self) -> str:
        """v4.8 B1-FIX: Returns handle from linkedin_url, or empty string if malformed."""
        raw = str(self.linkedin_url).split('/in/')[-1].strip('/')
        # v4.8: Reject handles containing spaces (name leakage from scraper)
        if ' ' in raw:
            logger.warning(f"v4.8 B1-FIX: Rejecting handle with space: '{raw}' — likely name leakage")
            return ""
        # v4.8: Reject handles that look like URL-encoded spaces (%20)
        if '%20' in raw:
            logger.warning(f"v4.8 B1-FIX: Rejecting handle with encoded space: '{raw}'")
            return ""
        return raw

    def generate_sync_block(self, added_fields=None, updated_fields=None, prev_stats=None, existing_sync_block_text=None, photo_update_date=None) -> str:
        """
        Generates/Updates the <Linkedin-AI-sync> JSON-like block for the contact's note.
        v5.5: Added photo_update_date support.
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        lines = [f"<Linkedin-AI-sync {date_str}>"]
        
        # v2.7.0: Auto-parse history if not provided
        prev_stats = prev_stats or {}
        if not prev_stats and existing_sync_block_text:
            prev_stats = self.parse_history_from_block(existing_sync_block_text)
        
        # v5.1: Date update only after live sync
        header_date_match = re.search(r"<Linkedin-AI-sync\s+(\d{4}-\d{2}-\d{2})", existing_sync_block_text or "")
        date_str = datetime.now().isoformat()[:10]
        
        # In repair/audit mode (no fresh extraction tags), we MUST preserve the original date
        is_repair = not added_fields and not updated_fields and "Photo" not in (updated_fields or [])
        if is_repair and header_date_match:
            date_str = header_date_match.group(1)

        sync_word = "added" if not existing_sync_block_text else "update"
        lines = [f"<Linkedin-AI-sync {date_str} {sync_word}>"]
        
        # v1.7.4: Toxic Artifact Purge (Clean legacy \"Sync Block (on Date)\" debris)
        def is_toxic(s):
            # v3.2.1: More inclusive blacklist to prune old rejections when new data exists
            return any(k in s for k in ["Rejected", "Low Quality", "Internal Error", "Potential Upgrade", "Accuracy Verified", "Sync Block"])
        
        # 1. Handle Added Fields (Enrichments) with history preservation
        # Format v4: Added (YYYY-MM-DD) : ...
        # Legacy v3: Added: ... (no date)
        historical_adds = {} # date -> set of fields
        legacy_adds = set()
        
        if existing_sync_block_text:
            # v4.4.1: Use non-greedy patterns and explicit delimiters to handle squashed blocks
            # Pattern matches 'Added (date) : fields' until the next tag or end of block
            tags_regex = r"(Added|Updated|Followers|Mutual connections|Connections|LinkedIn_Connection_Since)"
            
            # Parse v4 formats: Added (YYYY-MM-DD) : ...
            v4_adds = re.finditer(r"Added\s*\((.*?)\)\s*:\s*(.*?)(?=" + tags_regex + r"|</Linkedin-AI-sync|$)", existing_sync_block_text, re.DOTALL | re.IGNORECASE)
            for m in v4_adds:
                dt = m.group(1).strip()
                # Split by comma and clean up any trailing garbage from squashing
                raw_flds = m.group(2).strip()
                flds = set([f.strip() for f in re.split(r'[,]', raw_flds) if f.strip() and not is_toxic(f)])
                if dt in historical_adds:
                    historical_adds[dt].update(flds)
                else:
                    historical_adds[dt] = flds
            
            # Parse legacy formats (Added: ...)
            legacy_match = re.search(r"Added\s*:\s*(.*?)(?=" + tags_regex + r"|</Linkedin-AI-sync|$)", existing_sync_block_text, re.DOTALL | re.IGNORECASE)
            if legacy_match:
                raw_flds = legacy_match.group(1).strip()
                flds = set([f.strip() for f in re.split(r'[,]', raw_flds) if f.strip() and not is_toxic(f)])
                # Try to map to existing date
                header_match = re.search(r"<Linkedin-AI-sync\s+(\d{4}-\d{2}-\d{2})", existing_sync_block_text)
                if header_match:
                    dt = header_match.group(1)
                    if dt in historical_adds: historical_adds[dt].update(flds)
                    else: historical_adds[dt] = flds
                else:
                    legacy_adds.update(flds)

        # Add current fields if any
        if added_fields:
            # Global deduplication: don't add if already in history
            existing_global = set()
            for flds in historical_adds.values(): existing_global.update(flds)
            existing_global.update(legacy_adds)
            
            clean_added = set()
            for f in added_fields:
                f_s = f.strip()
                if f_s and f_s not in existing_global and not is_toxic(f_s):
                    clean_added.add(f_s)
            
            if clean_added:
                if date_str in historical_adds: historical_adds[date_str].update(clean_added)
                else: historical_adds[date_str] = clean_added

        # Output Added lines in reverse chronological order
        for dt in sorted(historical_adds.keys(), reverse=True):
            flds = sorted(list(historical_adds[dt]))
            if flds:
                lines.append(f"Added ({dt}) : {', '.join(flds)}")
        
        if legacy_adds:
            lines.append(f"Added: {', '.join(sorted(list(legacy_adds)))}")

        # 2. Handle Updates — dated format v2.4.15, depth-2 sliding window.
        # Format: "Updated (YYYY-MM-DD) : signal1, signal2"
        # Rule: current run's changes → new dated line at top.
        #       Previous most-recent entry carried as second line (last prior state before update).
        #       On no-change runs: both prior lines carry forward unchanged.
        # This gives one clear "what changed today" line + one "what was last changed" reference.
        important_signals = {"Job Title", "Company", "Current Role"}
        current_signals = set()
        for f in updated_fields:
            if f in important_signals or "Photo" in f:
                current_signals.add(f)

        blacklist = {"Sync Block", "Sync Block (Add)", "Sync Block (New)"}

        # Parse previous "Updated (date) :" entries (new format) or legacy "Updated :" (no date).
        prev_update_entries = []  # list of (date_str, set_of_signals), most-recent first
        if existing_sync_block_text:
            for m in re.finditer(
                r"Updated\s*\((\d{4}-\d{2}-\d{2})\)\s*:\s*(.*?)(?=Updated\s*[:(]|" + tags_regex + r"|</Linkedin-AI-sync|$)",
                existing_sync_block_text, re.DOTALL | re.IGNORECASE
            ):
                d = m.group(1)
                flds = {s.strip() for s in re.split(r',', m.group(2))
                        if s.strip() and s.strip() not in blacklist and not is_toxic(s.strip())}
                if flds:
                    prev_update_entries.append((d, flds))
            if not prev_update_entries:
                # Legacy undated "Updated : ..." — absorb as dated entry using block header date
                upd_match = re.search(r"Updated\s*:\s*(.*?)(?=" + tags_regex + r"|</Linkedin-AI-sync|$)", existing_sync_block_text, re.DOTALL | re.IGNORECASE)
                if upd_match:
                    flds = {s.strip() for s in re.split(r',', upd_match.group(1))
                            if s.strip() and s.strip() not in blacklist and not is_toxic(s.strip())}
                    if flds:
                        hm = re.search(r"<Linkedin-AI-sync\s+(\d{4}-\d{2}-\d{2})", existing_sync_block_text)
                        d = hm.group(1) if hm else "unknown"
                        prev_update_entries.append((d, flds))
            # Sort descending (most recent first)
            prev_update_entries.sort(key=lambda x: x[0], reverse=True)

        def _prune(sigs):
            has_success = any("High-Res" in s or "Quality Upgrade" in s or "Potential Upgrade" in s or s == "Photo" for s in sigs)
            if has_success:
                sigs = {s for s in sigs if not any(k in s for k in ["Rejected", "Low Quality", "Internal Error"])}
            return sigs

        if current_signals:
            current_signals = _prune(current_signals)
            lines.append(f"Updated ({date_str}) : {', '.join(sorted(current_signals))}")
            # Carry the single most-recent prior entry as "last prior state before this update"
            if prev_update_entries:
                pd, pf = prev_update_entries[0]
                lines.append(f"Updated ({pd}) : {', '.join(sorted(pf))}")
        elif prev_update_entries:
            # No new signals this run — carry forward up to 2 prior entries unchanged
            for pd, pf in prev_update_entries[:2]:
                lines.append(f"Updated ({pd}) : {', '.join(sorted(pf))}")

        # 3. Stats with history (immediate prior state preservation)
        f_curr = self.followers_count
        f_prev = prev_stats.get("followers")
        
        # v3.1.8 Defensive Type Casting (Ensure comparison doesn't crash if prev is string)
        try:
            if isinstance(f_prev, str): f_prev = int(re.sub(r'[^0-9]', '', f_prev) or 0)
        except:
            f_prev = 0
            
        # v3.1.7: Followers preservation
        if f_curr is not None and f_curr > 0:
            lines.append(f"Followers: {f_curr}")
        elif f_prev is not None:
            # v3.2.1: Preserve zero followers if it was explicitly there
            lines.append(f"Followers: {f_prev}")

        # v5.1: Metric Parity & Connection Logic
        c_text = None
        if self.connections_raw:
            clean_raw = self.connections_raw.lower()
            if "mutual" in clean_raw or "commun" in clean_raw: c_text = None
            else:
                for k in ['connections', 'relations', 'contacts', 'connection', 'relation', 'contact', 'connexion', 'connexions', '1st', 'degree', 'network', 'member']:
                    clean_raw = clean_raw.replace(k, "")
                match = re.search(r'(\d[\d,.]*\+?)', clean_raw)
                if match: c_text = match.group(1)
        
        if not c_text and self.connections_count is not None:
            c_text = "500+" if self.connections_count >= 500 else str(self.connections_count)

        # Sanity: Connections must not mirror followers if followers is exactly the same number
        try:
            c_int = int(re.sub(r'[^0-9]', '', c_text or "0"))
            if c_int == self.followers_count and c_int > 500: c_text = "500+" # Force capped
        except: pass

        c_prev = prev_stats.get("total")
        if not c_text and c_prev and str(c_prev) not in ["0", ""]: c_text = str(c_prev)

        # Mutual connections & Degrees
        m_curr = self.common_connections_count
        m_prev = prev_stats.get("common")
        
        # Metric Parity Guard: Total >= Mutual
        try:
            c_val = int(re.sub(r'[^0-9]', '', str(c_text or "0")))
            m_val = m_curr or m_prev or 0
            if m_val > c_val and c_val > 0:
                # Label swap detected: fix logically
                c_text = str(m_val) + ("+" if c_val >= 500 else "")
                m_curr = c_val
        except: pass
        degree_label = ""
        if self.connection_degree and self.connection_degree >= 1:
            suffix = "st" if self.connection_degree == 1 else ("nd" if self.connection_degree == 2 else ("rd" if self.connection_degree == 3 else "th"))
            degree_label = f" ({self.connection_degree}{suffix} degree)"

        # v5.3: Visibility Rule - Only show Connections if explicitly found in CURRENT extraction
        is_connections_explicit = bool(self.connections_count or self.connections_raw)
        if c_text and is_connections_explicit and str(c_text).strip() != str(m_curr).strip():
            lines.append(f"Connections : {c_text}")

        if m_curr is not None and m_curr > 0:
            hist = f" (was {m_prev})" if m_prev and m_curr != m_prev else ""
            lines.append(f"Mutual connections{degree_label} : {m_curr}{hist}")
        elif m_prev:
            lines.append(f"Mutual connections{degree_label} : {m_prev}")

        if self.mutual_groups:
            # v5.2: Ensure Mutual Groups are prominent
            group_list = ", ".join(self.mutual_groups)
            lines.append(f"Mutual Groups: {group_list}")

        # v5.1: Degree formatting rules
        if self.connection_degree and self.connection_degree >= 1:
            if not m_curr: # Only output degree if not already in Mutual line
                suffix = "st" if self.connection_degree == 1 else ("nd" if self.connection_degree == 2 else ("rd" if self.connection_degree == 3 else "th"))
                msg = "No direct connection" if self.connection_degree >= 3 else "LinkedIn connection"
                if not c_text: msg = "No direct connection"
                lines.append(f"{msg} ({self.connection_degree}{suffix} degree)")
        # v5.5: Photo Date Preservation
        # v2.4.15: Only emit Photo Date when it differs from the current sync date.
        # If the photo was updated today, the header date already conveys this (redundant).
        # Carry it forward only when it's from a PREVIOUS sync (useful cross-reference).
        photo_date = photo_update_date or prev_stats.get("photo_date")
        if photo_date and photo_date != date_str:
            lines.append(f"Photo Date: {photo_date}")

        lines.append("</Linkedin-AI-sync>")
        return "\n".join(lines)

    def parse_history_from_block(self, block_text: str) -> dict:
        """v2.7.0/v3.1.7: Parses historical metrics and the last sync date from an existing block."""
        # v3.2.1: Use None as default to distinguish from explicit zero
        # v5.5: Added photo_date
        stats = {"followers": None, "total": None, "common": None, "date": "last update", "photo_date": None}
        
        if not block_text:
            return stats
            
        # 1. Date
        d_match = re.search(r"<Linkedin-AI-sync\s+(\d{4}-\d{2}-\d{2})", block_text)
        if d_match: stats["date"] = d_match.group(1)
        
        # 2. Metrics (v3.2.1: Robust numeric matching for history preservation)
        f_match = re.search(r"Followers\s*:\s*([\d,.]+)", block_text, re.IGNORECASE)
        if f_match: stats["followers"] = int(re.sub(r'[^0-9]', '', f_match.group(1)) or 0)

        c_match = re.search(r"Connections\s*:\s*([\d,.\+]+)", block_text, re.IGNORECASE)
        if c_match: stats["total"] = c_match.group(1).strip()
        
        m_match = re.search(r"Mutual connections\s*:\s*([^\n]+)", block_text, re.IGNORECASE)
        if m_match: 
            line_content = m_match.group(1)
            val = int(re.sub(r'[^0-9]', '', line_content.split('(')[0]) or 0)
            stats["common"] = val
            # v2.9.4: Deep History Extraction (Check 'was' if current is 0)
            # FIX v3.3: Search for 'was' ONLY within the captured line to avoid matching Followers history
            if val == 0:
                was_match = re.search(r"\(was\s+([\d,.]+)\s+on\s+(.*?)\)", line_content, re.IGNORECASE)
                if was_match:
                    stats["common"] = int(re.sub(r'[^0-9]', '', was_match.group(1)) or 0)
                    stats["date"] = was_match.group(2)
        
        # 3. Photo Date (v5.5)
        p_match = re.search(r"Photo Date\s*:\s*(\d{4}-\d{2}-\d{2})", block_text, re.IGNORECASE)
        if p_match: stats["photo_date"] = p_match.group(1).strip()
        
        return stats