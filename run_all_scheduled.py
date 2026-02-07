#!/usr/bin/env python3
"""
Master Scheduler Script

Runs all prompt runners (company, ecosystem, VC) across all AI platforms.
Designed to be called by cron or launchd every 4 days.

Usage:
    python run_all_scheduled.py                    # Run all
    python run_all_scheduled.py --type company     # Run only company/ecosystem
    python run_all_scheduled.py --type vc          # Run only VC evaluation
    python run_all_scheduled.py --platform chatgpt # Run only ChatGPT
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Setup logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

log_file = LOG_DIR / f"scheduler_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Script directory
SCRIPT_DIR = Path(__file__).parent

# Python executable - use pyenv human_prompt environment
PYTHON_EXEC = "/Users/cedricdeschaut/.pyenv/versions/human_prompt/bin/python3"

# Runner configurations
RUNNERS = {
    "company": {
        "chatgpt": "runners/company/company_runner_chatgpt.py",
        "gemini": "runners/company/company_runner_gemini.py",
        "perplexity": "runners/company/company_runner_perplexity.py",
    },
    "ecosystem": {
        "chatgpt": "runners/ecosystem/ecosystem_runner_chatgpt.py",
        "gemini": "runners/ecosystem/ecosystem_runner_gemini.py",
        "perplexity": "runners/ecosystem/ecosystem_runner_perplexity.py",
    },
    "vc": {
        "chatgpt": "runners/vc/vc_eval_runner_chatgpt.py",
        "gemini": "runners/vc/vc_eval_runner_gemini.py",
        "perplexity": "runners/vc/vc_eval_runner_perplexity.py",
    },
}


def run_script(script_name: str, headless: bool = False) -> tuple[bool, str]:
    """Run a single script and return success status and output.

    Note: headless=False by default because ChatGPT/Gemini/Perplexity
    require active login sessions which don't persist well in headless mode.
    """
    script_path = SCRIPT_DIR / script_name

    if not script_path.exists():
        return False, f"Script not found: {script_path}"

    cmd = [PYTHON_EXEC, str(script_path)]
    if headless:
        cmd.append("--headless")

    logger.info(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout per script
        )

        if result.returncode == 0:
            logger.info(f"SUCCESS: {script_name}")
            return True, result.stdout
        else:
            logger.error(f"FAILED: {script_name}\n{result.stderr}")
            return False, result.stderr

    except subprocess.TimeoutExpired:
        logger.error(f"TIMEOUT: {script_name}")
        return False, "Script timed out after 1 hour"
    except Exception as e:
        logger.error(f"ERROR: {script_name}: {e}")
        return False, str(e)


def run_all(
    run_types: list[str] = None,
    platforms: list[str] = None,
    headless: bool = False,
    delay_between: int = 60,
):
    """Run all configured scripts.

    Note: headless=False by default because AI services require logged-in sessions.
    """
    import time

    run_types = run_types or ["company", "ecosystem", "vc"]
    platforms = platforms or ["chatgpt", "gemini", "perplexity"]

    results = {"success": [], "failed": []}

    logger.info("=" * 60)
    logger.info(f"Starting scheduled run at {datetime.now()}")
    logger.info(f"Types: {run_types}")
    logger.info(f"Platforms: {platforms}")
    logger.info(f"Headless: {headless}")
    logger.info("=" * 60)

    for run_type in run_types:
        if run_type not in RUNNERS:
            logger.warning(f"Unknown run type: {run_type}")
            continue

        for platform in platforms:
            if platform not in RUNNERS[run_type]:
                logger.warning(f"Unknown platform for {run_type}: {platform}")
                continue

            script = RUNNERS[run_type][platform]
            success, output = run_script(script, headless=headless)

            if success:
                results["success"].append(f"{run_type}/{platform}")
            else:
                results["failed"].append(f"{run_type}/{platform}")

            # Delay between scripts to avoid rate limiting
            if delay_between > 0:
                logger.info(f"Waiting {delay_between}s before next script...")
                time.sleep(delay_between)

    # Summary
    logger.info("=" * 60)
    logger.info("Run complete!")
    logger.info(f"Success: {len(results['success'])} - {results['success']}")
    logger.info(f"Failed: {len(results['failed'])} - {results['failed']}")
    logger.info("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(description="Run all prompt runners on schedule")
    parser.add_argument(
        "--type",
        choices=["company", "ecosystem", "vc", "all"],
        default="all",
        help="Type of prompts to run",
    )
    parser.add_argument(
        "--platform",
        choices=["chatgpt", "gemini", "perplexity", "all"],
        default="all",
        help="AI platform to use",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browsers in headless mode (requires pre-authenticated sessions)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=60,
        help="Seconds to wait between scripts",
    )

    args = parser.parse_args()

    run_types = ["company", "ecosystem", "vc"] if args.type == "all" else [args.type]
    platforms = ["chatgpt", "gemini", "perplexity"] if args.platform == "all" else [args.platform]

    results = run_all(
        run_types=run_types,
        platforms=platforms,
        headless=args.headless,
        delay_between=args.delay,
    )

    # Exit with error if any failed
    sys.exit(0 if not results["failed"] else 1)


if __name__ == "__main__":
    main()
