import sys
import os
import logging
import asyncio
import argparse
import traceback

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from src.agent.pro_sync_agent import async_main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LSAMC Pro Wrapper")
    parser.add_argument("--url", help="LinkedIn Profile URL")
    parser.add_argument("--name", action="append", help="Name(s) of contacts in macOS Contacts")
    parser.add_argument("--group", help="Name of a macOS Contacts group to sync")
    parser.add_argument("--selection", action="store_true", help="Sync contacts currently selected in macOS Contacts")
    parser.add_argument("--mode", choices=["SIMULATION", "FULL"], default="SIMULATION", help="Run mode")
    parser.add_argument("--api-key", help="Google AI API Key")
    parser.add_argument("--limit", type=int, help="Limit the number of contacts to sync in batch mode")
    parser.add_argument("--offset", type=int, default=0, help="Skip N contacts from the start")
    parser.add_argument("--last", type=int, help="Take only the last N contacts from the list")
    parser.add_argument("--reverse", action="store_true", help="Process contacts in reverse order")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    
    parser.add_argument("--session", help="Path to a session directory for review/apply")
    parser.add_argument("--validate", dest="validate_name", help="Mark a contact as validated in a session")
    parser.add_argument("--validate-all", action="store_true", help="Mark all contacts in a session as validated")
    parser.add_argument("--apply", action="store_true", help="Apply validated changes from a session to macOS Contacts")
    parser.add_argument("--apply-all", action="store_true", help="Review AND Apply all contacts (Skip human review)")
    parser.add_argument("--review", action="store_true", help="Review staged changes in a session")
    
    parser.add_argument("--vault-only", action="store_true", help="Only check the SPOT vault, no LinkedIn scrape")
    parser.add_argument("--archive", action="store_true", help="Archive successfully applied contacts")
    parser.add_argument("--ab-test", dest="ab_test", action="store_true", help="Run in A/B test mode (Hybrid vs Pro)")
    parser.add_argument("--force", action="store_true", help="Force sync even if handled today")
    parser.add_argument("--surgical", action="store_true", help="Force surgical local scrape instead of LLM")
    
    args = parser.parse_args()
    
    try:
        asyncio.run(async_main(args))
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"Runner Exception: {e}")
        traceback.print_exc()
