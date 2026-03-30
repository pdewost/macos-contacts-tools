import sys
import os
import logging
from src.agent.sync_agent import main

if __name__ == "__main__":
    # Ensure correct working directory/pythonpath if needed
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    main()
