#!/usr/bin/env python3
"""One-off runner: Qmill spider-chart prompts (P18-P27) on ChatGPT, Gemini, Perplexity."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
COMPANY = "Qmill"
PROMPTS_FILE = "prompts/quantum/prompts_spider_only.json"
ICP_FILE = "data/qmill/icp_qmill.txt"
BUYER_PERSONA_FILE = "data/qmill/buyer_persona_qmill.txt"
APPLICATIONS_FILE = "data/quantum-generic/applications_quantum_sensing.txt"

PLATFORMS = {
    "chatgpt": {
        "module_path": "runners.company.company_runner_chatgpt",
        "profile_dir": "chatgpt_profile",
        "model_tag": "chatgpt-web",
        "folder_suffix": "chatgpt",
    },
    "gemini": {
        "module_path": "runners.company.company_runner_gemini",
        "profile_dir": "gemini_profile",
        "model_tag": "gemini-web",
        "folder_suffix": "gemini",
    },
    "perplexity": {
        "module_path": "runners.company.company_runner_perplexity",
        "profile_dir": "perplexity_profile",
        "model_tag": "perplexity-web",
        "folder_suffix": "perplexity",
    },
}


def load_prompts():
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("prompts", [])


async def run_platform(platform_key, headless=False, delay=5.0):
    cfg = PLATFORMS[platform_key]

    # Dynamic import of the PromptRunner class
    import importlib
    mod = importlib.import_module(cfg["module_path"])
    PromptRunner = mod.PromptRunner

    runner = PromptRunner(
        prompts_file=PROMPTS_FILE,
        icp_file=ICP_FILE,
        buyer_persona_file=BUYER_PERSONA_FILE,
        quantum_sensing_applications_file=APPLICATIONS_FILE,
        profile_dir=cfg["profile_dir"],
        headless=headless,
    )

    prompts = load_prompts()

    results_root = Path("results")
    results_root.mkdir(exist_ok=True)
    run_folder_name = (
        datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        + f"_{cfg['folder_suffix']}"
    )
    run_folder = results_root / run_folder_name
    run_folder.mkdir(parents=True, exist_ok=True)

    # Optional BigQuery upload
    try:
        from bq_helper import upload_result, ensure_all_tables_exist, upload_sources
        ensure_all_tables_exist()
        bq = True
    except Exception:
        bq = False

    await runner.start_browser()
    try:
        await runner.ensure_logged_in()

        for p in prompts:
            prompt_text = p["template"].replace("{{CompanyName}}", COMPANY)

            result = {
                "prompt_id": p["id"],
                "company": COMPANY,
                "question": prompt_text,
                "answer": "FAILED",
                "sources": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": cfg["model_tag"],
                "test_mode": False,
            }

            max_retries = 2
            for attempt in range(1 + max_retries):
                try:
                    response = await runner.run_prompt(prompt_text)
                    result["answer"] = response["answer"]
                    result["sources"] = response["sources"]
                    result["response_id"] = response.get("response_id", "")
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    is_retryable = any(
                        kw in err_str
                        for kw in ("timeout", "rate", "session", "expired")
                    )
                    if is_retryable and attempt < max_retries:
                        wait = (attempt + 1) * 10
                        print(f"  Retry {attempt+1}/{max_retries}: {e}")
                        await asyncio.sleep(wait)
                        continue
                    result["error"] = str(e)
                    break

            name = COMPANY.replace(" ", "_")
            output_path = run_folder / f"{p['id']}_{name}.json"

            if bq:
                try:
                    if upload_result(result, run_folder_name):
                        print(f"  [{platform_key}] Uploaded {p['id']}_{name}")
                        upload_sources(result, run_folder_name)
                    else:
                        raise Exception("upload returned False")
                except Exception:
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    print(f"  [{platform_key}] Saved locally: {output_path}")
            else:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"  [{platform_key}] Saved locally: {output_path}")

            await asyncio.sleep(delay)

    finally:
        await runner.close_browser()

    print(f"\n[{platform_key}] Done. Results in: {run_folder}\n")


async def main():
    parser = argparse.ArgumentParser(
        description="One-off: run Qmill spider-chart prompts (P18-P27)"
    )
    parser.add_argument(
        "--platforms",
        nargs="+",
        choices=list(PLATFORMS.keys()),
        default=list(PLATFORMS.keys()),
        help="Which platforms to run (default: all three)",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--delay", type=float, default=5.0)
    args = parser.parse_args()

    for platform in args.platforms:
        print(f"\n{'='*50}")
        print(f"  Running {platform} for {COMPANY} (P18-P27)")
        print(f"{'='*50}\n")
        await run_platform(platform, headless=args.headless, delay=args.delay)

    print("All platforms done.")


if __name__ == "__main__":
    asyncio.run(main())
