#!/usr/bin/env python3
"""
Step 2 Result Application
Version: 1.0.0
Purpose: Promotes verified 1st degrees (Surgical Reset) and quarantines non-1st degrees.
"""

import sys
import os
import re

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bridge.contact_macos import ContactMacOSBridge

# BATCH 1, 2, 3, 4 RESULTS + AD-HOC FIXES
PROMOTED = [
    "Nicolas Lopez", "Joëlle Passelègue", "Arnaud JACOLIN", "Patrick BUREL",
    "Vesna Cosich", "Irina S. Zimakova", "David Leborgne", "Jean-Louis WARGNIER",
    "David Feige-Muller", "Karim SELOUANE", "CLARA SORIN", "Voisin-Ratelle Joel",
    "CDC infrastructure", "Johannes Pfister", "M Frank Supplisson", 
    "Jean-Philippe Demaël", "Yves Leon", "M Christophe Tallec", "Deborah Widener",
    "Jérôme Introvigne", "M Maxime PICAT", "Mr Jesus Viceira", "Waleed Kacimi",
    "Hélène CARRIERE - BONNET", "Gilbert Reveillon", "Christophe Grünthaler",
    "Michael Flowers", "Jean Dominique Brisson",
    "Jacques Fouché", "Olivier Midière", "Me Barbara Leibig van Huffel",
    "Mrs Catherine (Evans Winchester) Heald", "Sonesh Balchandani", "Dirk Hoke",
    "Khalid Oulahal", "M Jean-Baptiste GERARD", "Francoise Devaux", "Chris Huls",
    "Jean-Pascal Aubert", "Anne-Juliette Hermant", "Pierre BIVAS", "Marc Drillech",
    "Nicolas Cantu", "Pascal Portelli", "Albane d'Hauteville", "Cécile LAUER",
    "Ludovic Fauvet", "Valérie Balavoine", "Sandrine Murcia", "Pierre Hénon",
    "Philippe HUMEAU", "Nathalie Lhayani", "Guillaume Deschamps", "Christian Liebler",
    "Pierre Guéhenneux", "Dominique Cardon", "Christophe Renaud", "Bernadette Malgorn"
]

QUARANTINE = [
    "Richard Grogan-Crane", "Yongki Min", "Damien GIOLITO", "ALAIN BENESTEAU",
    "Josephine Ceccaldi", "David Wu", "Anil C Kokaram", "Mehdi AMOUR", "Koumar Vijaya",
    "M Claude Sassoulas", "Me Florence Etheimer", "M Olivier FAUQUEUX", 
    "Herr Michael Clever", "M Louis-Gabriel de Causans",
    "M Benjamin Teszner", "M Frederic Vasnier", "François Lagunas", 
    "Mlle Bernadette Cromwell", "Giacomo Bersano", "M Michel GUILLEMET",
    "Me Charlotte Feraille", "Jean-Michel Piquemal", "M Benoit Deleury", "M jean-claude Mallet",
    "Jean-Pierre CASARA", "Giorgi Gurgenidze", "Gregory Yeakle", "Kimmo Myllymaki",
    "Anne Lhotellier", "Jean-Pierre BOKOBZA", "Alexandre Megret", "Ralph Eric Kunz", "Bruno CREMEL"
]

def wash_note(note: str) -> str:
    """Removes the legacy sync block from a note."""
    if not note: return ""
    clean = re.sub(r'<Linkedin-AI-sync.*?</Linkedin-AI-sync>', '', note, flags=re.DOTALL).strip()
    clean = clean.replace("#lsam-force-resync", "").strip()
    return clean

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    
    mode = "FULL" if args.full else "SIMULATION"
    bridge = ContactMacOSBridge(mode=mode)
    
    print(f"--- Applying Step 2 Batch 1 Results (Mode: {mode}) ---")
    
    # 1. Promotions (Surgical Reset)
    for name in PROMOTED:
        print(f"Promoting: {name}")
        res = bridge.find_contact(name)
        if not res["success"]:
            print(f"  ❌ Not found: {name}")
            continue
        
        cid = res["matches"][0]["id"] if "matches" in res else res["id"]
        details = bridge.get_contact_details(cid)
        if details["success"]:
            new_note = wash_note(details["note"])
            print(f"  ✅ Washing note for {name}...")
            bridge.update_note(cid, new_note)
            
    # 2. Quarantines (Move to LinkedIn to Review)
    # Note: We need a 'move_contact' method or use Control Center logic
    for name in QUARANTINE:
        print(f"Quarantining: {name}")
        # For now, we'll just log it. We should move them to 'LinkedIn to Review' group.
        # res = bridge.move_to_group(name, "LinkedIn to Review") # Not yet in bridge
        print(f"  ⚠️ Action Required: Move {name} to 'LinkedIn to Review'")

if __name__ == "__main__":
    main()
