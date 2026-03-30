#!/usr/bin/env python3
"""
Surgical URL Overrides for Batch 9 Search Failures
Manually researched LinkedIn URLs for contacts that failed automated search
"""

# Batch 9 - Manually researched URLs
BATCH_9_OVERRIDES = {
    "Brigitte GOTTI": "https://www.linkedin.com/in/brigitte-gotti",
    "Franck SILVENT": "https://www.linkedin.com/in/franck-silvent-a32a98177",
}

# Contacts to exclude from retry (invalid entries)
BATCH_9_EXCLUSIONS = [
    "List - List - Newton Alumni",  # Group, not a person
    "SFR",  # Company name, not a person
]

# All contacts approved for retry (with title stripping)
BATCH_9_RETRY_LIST = [
    "Herr Frank UHLAND Dipl.-Ing",
    "Herr Roland GRENKE",
    "M Bertrand GENUYT",
    "M Didier Benchimol",
    "M Fred Thuard",
    "M Gérald-Brice VIRET",
    "M Jean-Baptiste LATOUR",
    "M Jean-Sébastien MÉRIEUX",
    "M Marc SCHWARTZ",
    "M Olivier THOMÉ",
    "M Pierre JACOBS",
    "M Richard GOTAINER",
    "M Thibault JOUAN",
    "M William TUNSTALL-PEDOE",
    "M&Me Christian LAROCHE",
    "M&Me Gilles CHEVALLIER",
    "M&Me Jean-Philippe ARTUR",
    "M&Me Renaud DENOIX DE SAINT MARC",
    "Me Anne HAUDRY De SOUCY",
    "Me Cecile Brosset Dubois",
    "Me Pascale MANNONE",
    "Me Severine Chapus",
    "Me Stéphanie BRUSSET LACORRE",
    "Me Valérie COURIOT",
    "Mlle Flore LABBE DE LA MAUVINIERE",
    "Mme Frédérique BAILLY-DÉROT",
    "Mr Hyoung Rae WOO",
    "Mr Jaakko HATTULA",
    "Mr Jean-Louis CARTOLANO",
    "Mr Jim CALVERLEY",
    "Mr Jonathan MOYER",
    "Mr Jong Eun KIM",
    "Mr K.S. LU",
    "Mr Marc ANDREESSEN",
    "Mr Marc OBERLE",
    "Mr Timo IHAMUOTILA",
    "Mrs Amit TARBERG",
    "Mrs Deborah FENWICK",
    "Mrs Giovanna ZAARUOLO",
    "Mrs Wang AIHUA",
    "Rama AYSOLA",
]

if __name__ == "__main__":
    print(f"Batch 9 Surgical Overrides: {len(BATCH_9_OVERRIDES)} URLs")
    print(f"Batch 9 Exclusions: {len(BATCH_9_EXCLUSIONS)} contacts")
    print(f"Batch 9 Retry List: {len(BATCH_9_RETRY_LIST)} contacts")
    print(f"\nTotal to process: {len(BATCH_9_OVERRIDES) + len(BATCH_9_RETRY_LIST)} contacts")
