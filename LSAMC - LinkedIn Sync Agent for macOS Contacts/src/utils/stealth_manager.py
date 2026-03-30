import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class StealthManager:
    """
    Manages LinkedIn access logs and enforces safety policies to avoid account flagging.
    """
    def __init__(self, log_path: str = "data/linkedin_access_log.json", 
                 daily_quota: int = 300, 
                 cooldown_days: int = 7):
        self.log_path = log_path
        self.daily_quota = daily_quota
        self.cooldown_days = cooldown_days
        self._ensure_dir()
        self.logs = self._load()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def _load(self) -> List[Dict]:
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load stealth log: {e}")
        return []

    def _save(self):
        try:
            with open(self.log_path, 'w') as f:
                json.dump(self.logs, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stealth log: {e}")

    def record_access(self, target_id: str, url: str, reason: str = "sync"):
        """Records a successful or attempted LinkedIn profile access."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "target_id": target_id,
            "url": url,
            "reason": reason
        }
        self.logs.append(entry)
        # Keep logs manageable? Maybe only keep last 1000 entries
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        self._save()

    def get_last_access(self, target_id: str = None, url: str = None) -> Optional[datetime]:
        """Returns the last timestamp this specific profile was accessed."""
        matches = []
        for entry in reversed(self.logs):
            if (target_id and entry.get("target_id") == target_id) or \
               (url and entry.get("url") == url):
                try:
                    return datetime.fromisoformat(entry["timestamp"])
                except:
                    continue
        return None

    def get_daily_count(self) -> int:
        """Returns the number of LinkedIn accesses in the last 24 hours."""
        now = datetime.now()
        day_ago = now - timedelta(hours=24)
        count = 0
        for entry in self.logs:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts > day_ago:
                    count += 1
            except:
                continue
        return count

    def is_safe_to_access(self, target_id: str, url: str) -> Dict[str, Any]:
        """
        Checks if it's safe to hit LinkedIn for this profile today.
        Returns {'safe': bool, 'reason': str}
        """
        # 0. Working Hours (08:00 - 20:00 Local)
        # v3.5.4: Enforce business hours to mimic human behavior.
        # LSAMC_IGNORE_HOURS=1 bypasses this gate for user-initiated manual sync
        # (set by handleManualSync in LSAM Control Center). Daily quota and per-contact
        # cooldown checks below still apply — only the time gate is skipped.
        now = datetime.now()
        if not (8 <= now.hour < 20):
            if os.environ.get("LSAMC_IGNORE_HOURS") != "1":
                return {
                    "safe": False,
                    "reason": f"Outside working hours (08:00-20:00). Current: {now.strftime('%H:%M')}"
                }

        # 1. Total Daily Quota
        daily_count = self.get_daily_count()
        if daily_count >= self.daily_quota:
            return {
                "safe": False, 
                "reason": f"Daily quota reached ({daily_count}/{self.daily_quota})"
            }

        # 2. Individual Cooldown
        last_ts = self.get_last_access(target_id, url)
        if last_ts:
            cooldown_limit = datetime.now() - timedelta(days=self.cooldown_days)
            if last_ts > cooldown_limit:
                days_since = (datetime.now() - last_ts).days
                return {
                    "safe": False, 
                    "reason": f"Profile accessed {days_since} days ago (Cooldown: {self.cooldown_days} days)"
                }

        return {"safe": True, "count": daily_count}
