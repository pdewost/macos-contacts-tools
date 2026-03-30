-- ==============================================
-- FORTRESS HEADER
-- ==============================================
-- SCRIPT: Login to Batch Profile
-- VERSION: 1.0.1
-- PURPOSE: Opens Chrome on the 'batch' profile (non-headless) for manual LinkedIn authentication.
-- ARCHITECTURE: 
--   - Proxies through the Python LinkedInSyncAgent to ensure profile path consistency.
--   - Uses dynamic path resolution to project root.
-- NEXT STEPS:
--   - [ ] Integrate into Control Center 'Setup' menu.
-- ==============================================

property pVersion : "1.0.1"

-- Dynamic Path Resolution
set myPath to (path to me as string)
tell application "System Events" to set projectRoot to POSIX path of container of file myPath

-- Open Chrome non-headless on the batch profile
set cmd to "cd " & quoted form of projectRoot & " && export PYTHONPATH=$PYTHONPATH:. && python3 -c \"from src.agent.sync_agent import LinkedInSyncAgent; import asyncio; agent=LinkedInSyncAgent(); agent.group='batch'; asyncio.run(agent._setup_browser(headless=False)); input('Log in to LinkedIn then press Enter here to close...')\""

do shell script cmd

display notification "Batch Login session closed." with title "LSAM (" & pVersion & ")"
