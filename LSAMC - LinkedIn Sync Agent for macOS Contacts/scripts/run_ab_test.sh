#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.
# Overnight Session: Default to all remaining in group if no limit provided
LIMIT=${1:-500}
GROUP="script-LSAM-Tier3-NeedAttention"

echo "Starting OVERNIGHT A/B test recovery on $GROUP at $(date) (Limit: $LIMIT)" > logs/ab_test_launcher.log

# v1.5.2 Robust Logic: Use --group and let the agent handle internal delays/health checks
python3 src/agent/sync_agent.py \
    --mode SIMULATION \
    --group "$GROUP" \
    --limit "$LIMIT" \
    --ab-test \
    --headless >> logs/ab_test_launcher.log 2>&1

echo "Overnight A/B test finished at $(date)" >> logs/ab_test_launcher.log
