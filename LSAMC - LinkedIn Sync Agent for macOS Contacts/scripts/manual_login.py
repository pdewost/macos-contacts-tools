
import asyncio
import os
import sys
from src.agent.sync_agent import LinkedInSyncAgent

async def manual_login():
    # Force batch mode to use agent_batch_profile
    agent = LinkedInSyncAgent()
    agent.group = 'batch' 
    
    print("🚀 Opening Chrome for manual login...")
    agent._setup_browser(headless=False)
    
    # Actually create a page to force the window to open
    session = await agent.browser.get_session()
    page = await session.get_current_page()
    await page.goto("https://www.linkedin.com/login")
    
    print("\n" + "="*50)
    print("WINDOW OPENED!")
    print("1. Log in to LinkedIn in the browser window.")
    print("2. Once you see your feed, come back here.")
    print("="*50)
    
    input("\nPress Enter HERE once you have successfully logged in...")
    
    await agent.close()
    print("✅ Login session closed. Background task should now be able to proceed.")

if __name__ == "__main__":
    asyncio.run(manual_login())
