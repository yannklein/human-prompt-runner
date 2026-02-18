#!/bin/bash
# Scheduled runner for quantum_computing_photonics_companies.txt
# Runs twice per day via launchd

cd "$(dirname "$0")"

PYTHON="/Users/cedricdeschaut/.pyenv/versions/human_prompt/bin/python3"
COMPANIES_FILE="quantum_computing_photonics_companies.txt"

mkdir -p logs
echo "$(date): Starting photonics run" >> logs/cron.log

for runner in runners/company/company_runner_chatgpt.py runners/company/company_runner_gemini.py runners/company/company_runner_perplexity.py; do
    if [ -f "$runner" ]; then
        echo "$(date): Running $runner" >> logs/cron.log
        $PYTHON "$runner" --companies-file "$COMPANIES_FILE" 2>&1 | tee -a logs/cron.log
        sleep 120
    fi
done

echo "$(date): Completed photonics run" >> logs/cron.log
