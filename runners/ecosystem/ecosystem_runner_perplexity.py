#!/usr/bin/env python3
"""
Ecosystem Prompt Runner — Perplexity

Runs ecosystem prompts (P1-P9) that don't require company-specific information.

Usage:
    python ecosystem_runner_perplexity.py
    python ecosystem_runner_perplexity.py --test
    python ecosystem_runner_perplexity.py --headless --delay 10
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path to import shared modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runners.company.company_runner_perplexity import PromptRunner

# BigQuery upload helper
try:
    from bq_helper import (
        upload_result,
        ensure_tables_exist,
        ensure_all_tables_exist,
        get_completed_prompts,
        upload_sources,
    )
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False
    print("Warning: bq_helper not available, results will only be saved locally")


async def main():
    parser = argparse.ArgumentParser(description="Run ecosystem prompts on Perplexity")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile-dir", default="perplexity_profile", help="Browser profile directory")
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
        run_folder_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_perplexity_ecosystem"
        run_folder = results_root / run_folder_name
        run_folder.mkdir(parents=True, exist_ok=True)

    # Ensure BigQuery tables exist and get completed prompts for resume
    completed_prompts = set()
    if BQ_AVAILABLE:
        try:
            ensure_all_tables_exist()
            print("BigQuery per-prompt tables verified")
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
                "sources": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "perplexity-web",
                "test_mode": args.test,
            }

            try:
                response = await runner.run_prompt(prompt_text)
                result["answer"] = response["answer"]
                result["sources"] = response["sources"]
            except Exception as e:
                result["error"] = str(e)

            # Upload to BigQuery (save locally only if upload fails)
            if BQ_AVAILABLE:
                if upload_result(result, run_folder_name):
                    print(f"Uploaded to BigQuery: {prompt_key}")

                    # Upload sources
                    if upload_sources(result, run_folder_name):
                        sources_count = len(result.get("sources", []))
                        if sources_count > 0:
                            print(f"  Uploaded {sources_count} sources")
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
