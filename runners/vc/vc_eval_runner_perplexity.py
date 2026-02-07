#!/usr/bin/env python3
"""
VC Evaluation Runner — Perplexity

Runs VC evaluation prompts (VP1-VP20) against Perplexity using the
existing Perplexity PromptRunner for browser automation.

Usage:
    python vc_eval_runner_perplexity.py
    python vc_eval_runner_perplexity.py --test
    python vc_eval_runner_perplexity.py --headless --delay 10
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
    from bq_helper import upload_result, ensure_tables_exist, get_completed_prompts
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False
    print("Warning: bq_helper not available, results will only be saved locally")


def _load_vcs(filepath="vcs.txt"):
    path = Path(filepath)
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


async def main():
    parser = argparse.ArgumentParser(description="Run VC evaluation prompts on Perplexity")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile-dir", default="perplexity_profile", help="Browser profile directory")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to wait between prompts")
    parser.add_argument("--test", action="store_true", help="Run only the first prompt (and first VC)")
    args = parser.parse_args()

    runner = PromptRunner(
        prompts_file="prompts/quantum/prompts_vc_evaluation.json",
        icp_file="data/qnami/icp_qnami.txt",
        buyer_persona_file="data/qnami/buyer_persona_qnami.txt",
        quantum_sensing_applications_file="data/quantum-generic/applications_quantum_sensing.txt",
        profile_dir=args.profile_dir,
        headless=args.headless,
    )

    prompts = runner.load_prompts()
    vcs = _load_vcs()

    if not vcs:
        print("No VCs found in vcs.txt. Add VC names (one per line) and retry.", file=sys.stderr)
        return

    if args.test:
        prompts = prompts[:1]
        vcs = vcs[:1]

    CATEGORY = "Quantum Sensing"

    results_root = Path("results")
    results_root.mkdir(exist_ok=True)
    run_folder_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_perplexity_vc"
    run_folder = results_root / run_folder_name
    run_folder.mkdir(parents=True, exist_ok=True)

    # Ensure BigQuery tables exist
    if BQ_AVAILABLE:
        try:
            ensure_tables_exist()
            print("BigQuery tables verified")
        except Exception as e:
            print(f"Warning: Could not verify BigQuery tables: {e}")

    await runner.start_browser()
    try:
        await runner.ensure_logged_in()

        for p in prompts:
            requires_vc = "VCName" in p["required_vars"]
            targets = vcs if requires_vc else [None]

            for vc_name in targets:
                prompt_text = p["template"]

                if "Category" in p["required_vars"]:
                    prompt_text = prompt_text.replace("{{Category}}", CATEGORY)

                if vc_name:
                    prompt_text = prompt_text.replace("{{VCName}}", vc_name)

                result = {
                    "prompt_id": p["id"],
                    "vc": vc_name,
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

                name = (vc_name or "category").replace(" ", "_")
                output_path = run_folder / f"{p['id']}_{name}.json"

                # Upload to BigQuery (save locally only if upload fails)
                if BQ_AVAILABLE:
                    if upload_result(result, run_folder_name):
                        print(f"Uploaded to BigQuery: {p['id']}_{name}")
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

            if args.test:
                break

    finally:
        await runner.close_browser()


if __name__ == "__main__":
    asyncio.run(main())
