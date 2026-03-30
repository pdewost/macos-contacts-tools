import logging
import re
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class NetworkSniffer:
    """
    Passively listens to browser network traffic to identify high-resolution LinkedIn photos.
    This bypasses the need for complex DOM interactions in many cases.
    """
    
    def __init__(self):
        self._candidates: Dict[str, int] = {} # URL -> Content-Length
        self._best_url: Optional[str] = None
        self._max_size = 0
        self._blacklist = set()
        
    def blacklist_url(self, url: str):
        """Adds a URL to the blacklist to ignore it in future captures."""
        if url:
            self._blacklist.add(url)
            logger.info(f"[Sniffer] Blacklisted: {url[:60]}...")
        
    def handle_response(self, event: dict, session_id: Optional[str] = None):
        """CDP Network.responseReceived handler."""
        try:
            # CDP event structure: event['response'] contains URL and headers
            resp = event.get('response', {})
            url = resp.get('url', '')
            
            if "licdn.com" in url:
                # v0.7.5: Blacklist check ( Philippe leak prevention )
                if any(b in url for b in self._blacklist):
                    return
                logger.debug(f"[Sniffer] Seen: {url[:60]}...")

            # Filter for LinkedIn media
            if "media.licdn.com/dms/image" not in url:
                return
                
            # Must be a photo
            if "profile-displayphoto" not in url and "profile-backgroundphoto" not in url:
                return

            headers = resp.get('headers', {})
            # Normalized headers check
            cl_val = headers.get("content-length") or headers.get("Content-Length") or 0
            try:
                cl = int(cl_val)
            except:
                cl = 0
                
            # Basic sanity check: > 5KB is likely a valid photo (even if small)
            if cl > 5000:
                is_better = False
                # Metric: Priority on resolution (shrink_2000 > shrink_1000 > shrink_800 > shrink_400 > shrink_200)
                # If resolution is same or unknown, priority on size
                is_larger = cl > self._max_size
                is_ultra = "shrink_2000" in url
                is_hq = "shrink_1000" in url or "shrink_800" in url
                is_med = "shrink_400" in url or "shrink_500" in url
                
                def get_rank(u):
                    if "shrink_2000" in u: return 4
                    if "shrink_1000" in u or "shrink_800" in u: return 3
                    if "shrink_400" in u or "shrink_500" in u: return 2
                    if "shrink_" in u: return 1
                    return 0

                our_rank = get_rank(url)
                best_rank = get_rank(self._best_url) if self._best_url else -1

                if our_rank > best_rank:
                    is_better = True
                elif our_rank == best_rank and is_larger:
                    is_better = True
                
                if is_better:
                    self._max_size = cl
                    self._best_url = url
                    logger.debug(f"[Sniffer] Captured (CDP): {cl} bytes {'(NEW BEST)' if is_better else ''} - {url[:40]}")

        except Exception as e:
            logger.debug(f"Sniffer CDP error: {e}")
            
    def get_best_candidate(self) -> Optional[str]:
        """Returns the largest image URL observed so far."""
        return self._best_url
        
    async def wait_for_traffic(self, timeout: float = 5.0) -> Optional[str]:
        """Polls for the best candidate for up to timeout seconds."""
        import asyncio
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            best = self.get_best_candidate()
            if best: return best
            await asyncio.sleep(0.5)
        return None
        
    def reset(self):
        """Clear sniffing history for a new profile."""
        self._candidates = {}
        self._best_url = None
        self._max_size = 0
