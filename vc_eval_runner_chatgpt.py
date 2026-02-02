#!/usr/bin/env python3
"""
VC Evaluation Runner — ChatGPT

Runs VC evaluation prompts (VP1-VP20) against ChatGPT using the
existing ChatGPT PromptRunner for browser automation.

Usage:
    python vc_eval_runner_chatgpt.py
    python vc_eval_runner_chatgpt.py --test
    python vc_eval_runner_chatgpt.py --headless --delay 10
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from vc_prompt_runner_chatgpt import PromptRunner


def _load_vcs(filepath="vcs.txt"):
    path = Path(filepath)
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


async def main():
    parser = argparse.ArgumentParser(description="Run VC evaluation prompts on ChatGPT")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile-dir", default="chatgpt_profile", help="Browser profile directory")
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
    run_folder = results_root / (datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_chatgpt_vc")
    run_folder.mkdir(parents=True, exist_ok=True)

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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "chatgpt-web",
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

                name = (vc_name or "category").replace(" ", "_")
                output_path = run_folder / f"{p['id']}_{name}.json"

                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)

                print(f"Saved: {output_path}")

                if args.test:
                    break

                await asyncio.sleep(args.delay)

            if args.test:
                break

    finally:
        await runner.close_browser()

if __name__ == "__main__":
    asyncio.run(main())
