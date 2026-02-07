#!/bin/bash
# Scheduled runner wrapper script
# This script is called by launchd to run all prompt runners
#
# NOTE: Runs in non-headless mode because ChatGPT/Gemini/Perplexity
# require logged-in sessions that don't persist in headless mode.
# Your computer needs to be unlocked for this to work.

# Change to script directory
cd "$(dirname "$0")"

# Use the pyenv human_prompt Python directly
PYTHON="/Users/cedricdeschaut/.pyenv/versions/human_prompt/bin/python3"

# Ensure logs directory exists
mkdir -p logs

# Log start
echo "$(date): Starting scheduled run" >> logs/cron.log
echo "Python: $PYTHON" >> logs/cron.log
$PYTHON --version >> logs/cron.log

# Run the scheduler (non-headless mode, delay between scripts)
# Browsers will open visibly - computer must be unlocked
$PYTHON run_all_scheduled.py --delay 120 2>&1 | tee -a logs/cron.log

# Log completion
echo "$(date): Completed scheduled run" >> logs/cron.log
