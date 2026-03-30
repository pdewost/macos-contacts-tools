import json
import os
import logging
from typing import Set, List

logger = logging.getLogger(__name__)

class CompanyKnowledgeBase:
    """
    🏢 LSAM Company Knowledge Base
    =============================
    Provides a persistent registry of known/validated company names.
    Used to:
    1. Filter out false positives from regex note extraction (e.g., "at home").
    2. Provide a signal for disambiguation during profile search.
    3. Learn new companies from successful syncs (feedback loop).
    """

    def __init__(self, data_path: str = "data/known_companies.json"):
        self.data_path = data_path
        self.known_companies: Set[str] = set()
        self._ensure_data_dir()
        self.load()
        if not self.known_companies:
            self.seed()

    def _ensure_data_dir(self):
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)

    def load(self):
        """Loads known companies from the JSON file."""
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.known_companies = set(data.get("companies", []))
                logger.info(f"🏢 KB: Loaded {len(self.known_companies)} known companies.")
            except Exception as e:
                logger.error(f"🏢 KB: Failed to load data from {self.data_path}: {e}")

    def save(self):
        """Saves known companies to the JSON file."""
        try:
            data = {"companies": sorted(list(self.known_companies))}
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"🏢 KB: Failed to save data to {self.data_path}: {e}")

    def is_known(self, candidate: str) -> bool:
        """Returns True if the normalized candidate name is in the KB."""
        if not candidate: return False
        norm = candidate.strip().lower()
        return norm in self.known_companies

    def learn(self, company: str):
        """Adds a new company to the knowledge base if not already present."""
        if not company or len(company) < 2: return
        
        norm = company.strip().lower()
        if norm not in self.known_companies:
            logger.info(f"🏢 KB: Learning new company -> {company}")
            self.known_companies.add(norm)
            self.save()

    def seed(self):
        """Initial seeds with common prominent companies to bootstrap the system."""
        initial_seeds = [
            "google", "apple", "microsoft", "amazon", "meta", "nvidia", "tesla", 
            "netflix", "intel", "ibm", "oracle", "sap", "salesforce", "adobe",
            "uber", "airbnb", "spacex", "openai", "stripe", "zoom", "slack",
            "vinci", "l'oreal", "lvmh", "hermes", "airbus", "totalenergies",
            "axa", "bnp paribas", "societe generale", "orange", "renault",
            "carrefour", "michelin", "danone", "sanofi", "pernod ricard",
            "capgemini", "atos", "thales", "safran", "veolia", "engie",
            "deloitte", "accenture", "pwc", "kpmg", "mckinsey", "boston consulting group",
            "goldman sachs", "jp morgan", "morgan stanley", "hsbc", "barclays",
            "linkedin", "facebook", "instagram", "twitter", "tiktok", "youtube"
        ]
        for s in initial_seeds:
            self.known_companies.add(s)
        logger.info(f"🏢 KB: Seeded with {len(initial_seeds)} bootstrap companies.")
        self.save()

    def filter_candidates(self, candidates: List[str]) -> List[str]:
        """Filters a list of candidates, returning only those known to the KB."""
        return [c for c in candidates if self.is_known(c)]
