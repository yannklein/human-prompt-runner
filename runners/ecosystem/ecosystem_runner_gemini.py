#!/usr/bin/env python3
"""
Ecosystem Prompt Runner — Gemini

Runs ecosystem prompts (P1-P9) that don't require company-specific information.

Usage:
    python ecosystem_runner_gemini.py
    python ecosystem_runner_gemini.py --test
    python ecosystem_runner_gemini.py --headless --delay 10
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path to import shared modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runners.company.company_runner_gemini import PromptRunner

# BigQuery upload helper
try:
    from bq_helper import upload_result, ensure_tables_exist, get_completed_prompts
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False
    print("Warning: bq_helper not available, results will only be saved locally")


async def main():
    parser = argparse.ArgumentParser(description="Run ecosystem prompts on Gemini")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile-dir", default="gemini_profile", help="Browser profile directory")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to wait between prompts")
    parser.add_argument("--test", action="store_true", help="Run only the first prompt")
    parser.add_argument("--resume", type=str, help="Resume from existing run folder")
    args = parser.parse_args()

    # Use ecosystem prompts file
    runner = PromptRunner(
        prompts_file="prompts/quantum/prompts_ecosystem.json",
        icp_file="data/qnami/icp_qnami.txt",
        buyer_persona_file="data/qnami/buyer_persona_qnami.txt",
        quantum_sensing_applications_file="data/quantum-generic/applications_quantum_sensing.txt",
        profile_dir=args.profile_dir,
        headless=args.headless,
    )

    prompts = runner.load_prompts()

    if args.test:
        prompts = prompts[:1]

    CATEGORY = "Quantum Sensing"
    APPLICATIONS = runner.load_applications()

    results_root = Path("results")
    results_root.mkdir(exist_ok=True)

    if args.resume:
        run_folder_name = args.resume
        run_folder = results_root / run_folder_name
        if not run_folder.exists():
            print(f"Resume folder not found: {run_folder}", file=sys.stderr)
            sys.exit(1)
        print(f"Resuming from: {run_folder_name}")
    else:
        run_folder_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_gemini_ecosystem"
        run_folder = results_root / run_folder_name
        run_folder.mkdir(parents=True, exist_ok=True)

    # Ensure BigQuery tables exist and get completed prompts for resume
    completed_prompts = set()
    if BQ_AVAILABLE:
        try:
            ensure_tables_exist()
            print("BigQuery tables verified")
            if args.resume:
                completed_prompts = get_completed_prompts(run_folder_name)
                print(f"Found {len(completed_prompts)} completed prompts in BigQuery")
        except Exception as e:
            print(f"Warning: Could not verify BigQuery tables: {e}")

    await runner.start_browser()
    try:
        await runner.ensure_logged_in()

        for p in prompts:
            prompt_key = f"{p['id']}_category"
            output_path = run_folder / f"{prompt_key}.json"

            # Skip if already completed (for resume mode)
            if args.resume and (prompt_key in completed_prompts or output_path.exists()):
                print(f"Skipping (already done): {prompt_key}")
                continue

            prompt_text = p["template"]

            if "Category" in p["required_vars"]:
                prompt_text = prompt_text.replace("{{Category}}", CATEGORY)

            if "Applications" in p["required_vars"]:
                prompt_text = prompt_text.replace("{{Applications}}", APPLICATIONS)

            result = {
                "prompt_id": p["id"],
                "company": None,
                "question": prompt_text,
                "answer": "FAILED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "gemini-web",
                "test_mode": args.test,
            }

            max_retries = 2
            for attempt in range(1 + max_retries):
                try:
                    response = await runner.run_prompt(prompt_text)
                    result["answer"] = response["answer"]
                    result["sources"] = response["sources"]
                    result["response_id"] = response["response_id"]
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    is_retryable = (
                        "timeout" in err_str
                        or "rate" in err_str
                        or "session" in err_str
                        or "expired" in err_str
                    )
                    if is_retryable and attempt < max_retries:
                        wait = (attempt + 1) * 10
                        print(f"Retryable error (attempt {attempt + 1}/{max_retries}): {e}")
                        print(f"Waiting {wait}s before retry...")
                        await asyncio.sleep(wait)
                        continue
                    result["error"] = str(e)
                    break

            # Upload to BigQuery (save locally only if upload fails)
            if BQ_AVAILABLE:
                if upload_result(result, run_folder_name):
                    print(f"Uploaded to BigQuery: {prompt_key}")
                else:
                    print(f"BigQuery upload failed, saving locally: {output_path}")
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
            else:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"Saved locally: {output_path}")

            if args.test:
                break

            await asyncio.sleep(args.delay)

    finally:
        await runner.close_browser()


if __name__ == "__main__":
    asyncio.run(main())
