#!/usr/bin/env python3

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from playwright.async_api import async_playwright

# Add parent directory to path to import shared modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# BigQuery upload helper
try:
    from bq_helper import upload_result, ensure_tables_exist, get_completed_prompts
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False
    print("Warning: bq_helper not available, results will only be saved locally")


class PromptRunner:
    def __init__(
        self,
        prompts_file: str,
        icp_file: str,
        buyer_persona_file: str,
        quantum_sensing_applications_file: str,
        profile_dir: str = "chatgpt_profile",
        headless: bool = False,
    ):
        self.prompts_file = prompts_file
        self.icp_file = Path(icp_file)
        self.buyer_persona_file = Path(buyer_persona_file)
        self.quantum_sensing_applications_file = Path(quantum_sensing_applications_file)
        self.profile_dir = profile_dir
        self.headless = headless

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ---------- Loaders ----------

    def load_prompts(self) -> List[dict]:
        with open(self.prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("prompts", [])

    def _load_text_file(self, path: Path, label: str) -> str:
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def load_icp(self) -> str:
        return self._load_text_file(self.icp_file, "ICP")

    def load_applications(self) -> str:
        return self._load_text_file(
            self.quantum_sensing_applications_file, "Applications"
        )

    def load_buyer_persona(self) -> str:
        return self._load_text_file(self.buyer_persona_file, "Buyer persona")

    def load_companies(self, filepath="companies.txt") -> List[str]:
        path = Path(filepath)
        if not path.exists():
            return []
        return [
            l.strip()
            for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]

    # ---------- Browser Lifecycle ----------

    async def start_browser(self):
        self._playwright = await async_playwright().start()
        profile_path = str(Path(self.profile_dir).resolve())
        self._context = await self._playwright.chromium.launch_persistent_context(
            profile_path,
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def close_browser(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()

    async def _dismiss_modals(self):
        """Dismiss any blocking modals (login prompt, rate-limit, etc.)."""
        dismissed = False

        # Try clicking "Stay logged out" link/button (works for both login and rate-limit modals)
        for selector in [
            'button:has-text("Stay logged out")',
            'a:has-text("Stay logged out")',
            '[data-testid="modal-no-auth-rate-limit"] button:last-child',
            '[data-testid="modal-no-auth-rate-limit"] a',
        ]:
            try:
                el = self._page.locator(selector)
                if await el.count() > 0 and await el.first.is_visible():
                    print(f"Dismissing modal via: {selector}")
                    await el.first.click()
                    await asyncio.sleep(2)
                    dismissed = True
                    break
            except Exception:
                continue

        # Fallback: if a modal overlay is present, try pressing Escape
        if not dismissed:
            for overlay_sel in [
                '[data-testid="modal-no-auth-rate-limit"]',
                '[role="dialog"]',
            ]:
                try:
                    overlay = self._page.locator(overlay_sel)
                    if await overlay.count() > 0 and await overlay.first.is_visible():
                        print(f"Modal overlay detected ({overlay_sel}), pressing Escape...")
                        await self._page.keyboard.press("Escape")
                        await asyncio.sleep(1)
                        dismissed = True
                        break
                except Exception:
                    continue

        return dismissed

    async def ensure_logged_in(self):
        await self._page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        # Dismiss any blocking modals (login, rate-limit, etc.)
        await self._dismiss_modals()

        try:
            await self._page.wait_for_selector("#prompt-textarea", timeout=30000)
            print("ChatGPT session is active.")
        except Exception:
            print("Not logged in. Please log in to ChatGPT in the browser window.")
            print("Waiting for login (up to 120s)...")
            try:
                await self._page.wait_for_selector("#prompt-textarea", timeout=120000)
                print("Login detected. Continuing.")
            except Exception:
                print("Login timeout. Exiting.", file=sys.stderr)
                await self.close_browser()
                sys.exit(1)

    # ---------- Chat Interaction ----------

    async def _start_new_chat(self):
        await self._page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        await self._dismiss_modals()
        await self._page.wait_for_selector("#prompt-textarea", timeout=30000)
        await asyncio.sleep(1)

    async def _submit_prompt_text(self, text: str):
        # Dismiss any modal that may have appeared
        await self._dismiss_modals()

        textarea = self._page.locator("#prompt-textarea")
        await textarea.click()
        await asyncio.sleep(0.3)

        # Use Playwright's fill() which properly triggers React state updates
        await textarea.fill(text)
        await asyncio.sleep(0.5)

        # Try multiple send button selectors (ChatGPT UI changes frequently)
        send_btn = None
        for selector in [
            'button[data-testid="send-button"]',
            'button[aria-label="Send prompt"]',
            'button[aria-label="Send message"]',
            'form button[type="submit"]',
            'button:has(svg[class*="send"])',
            'button:has(path[d*="M15.192"])',  # Send icon path
        ]:
            try:
                btn = self._page.locator(selector)
                if await btn.count() > 0 and await btn.first.is_visible():
                    send_btn = btn.first
                    break
            except Exception:
                continue

        if not send_btn:
            # Fallback: press Enter to submit
            await textarea.press("Enter")
            return

        await send_btn.click()

    async def _wait_for_response_complete(self, timeout_s: int = 180):
        poll_interval = 2
        elapsed = 0
        last_text = ""
        stable_count = 0
        required_stable = 3  # text must be stable for 3 consecutive polls

        while elapsed < timeout_s:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Check if stop button is still visible (response streaming)
            stop_btn = self._page.locator('button[data-testid="stop-button"]')
            stop_visible = await stop_btn.is_visible() if await stop_btn.count() > 0 else False

            # Get current response text
            current_text = await self._get_last_assistant_text()

            if current_text and current_text == last_text:
                stable_count += 1
            else:
                stable_count = 0
            last_text = current_text

            # Done when stop button is gone AND text is stable
            if not stop_visible and stable_count >= required_stable and current_text:
                return

        raise TimeoutError(f"Response did not complete within {timeout_s}s")

    async def _get_last_assistant_text(self) -> str:
        elements = self._page.locator('[data-message-author-role="assistant"] .markdown')
        count = await elements.count()
        if count == 0:
            return ""
        return await elements.nth(count - 1).inner_text()

    async def _extract_response_text(self) -> str:
        return await self._get_last_assistant_text()

    async def _extract_sources(self) -> List[dict]:
        sources = []
        seen_urls = set()

        # Layer 1: Extract <a href> links from the last assistant message
        assistant_msgs = self._page.locator('[data-message-author-role="assistant"] .markdown')
        count = await assistant_msgs.count()
        if count > 0:
            last_msg = assistant_msgs.nth(count - 1)
            links = last_msg.locator("a[href]")
            link_count = await links.count()
            for i in range(link_count):
                link = links.nth(i)
                href = await link.get_attribute("href") or ""
                title = await link.inner_text() or ""
                href = self._clean_url(href)
                if href and href not in seen_urls and href.startswith("http"):
                    seen_urls.add(href)
                    sources.append({
                        "url": href,
                        "title": title.strip(),
                        "publisher": self._extract_domain(href),
                        "snippet": "",
                    })

        # Layer 2: Look for source card elements
        source_selectors = [
            '[class*="source"]',
            '[data-testid*="source"]',
            '[class*="citation"]',
            '[data-testid*="citation"]',
        ]
        for selector in source_selectors:
            try:
                cards = self._page.locator(selector)
                card_count = await cards.count()
                for i in range(card_count):
                    card = cards.nth(i)
                    card_links = card.locator("a[href]")
                    cl_count = await card_links.count()
                    for j in range(cl_count):
                        href = await card_links.nth(j).get_attribute("href") or ""
                        title = await card_links.nth(j).inner_text() or ""
                        href = self._clean_url(href)
                        if href and href not in seen_urls and href.startswith("http"):
                            seen_urls.add(href)
                            sources.append({
                                "url": href,
                                "title": title.strip(),
                                "publisher": self._extract_domain(href),
                                "snippet": "",
                            })
            except Exception:
                continue

        # Layer 3: Fallback regex on answer text for markdown links [title](url)
        if not sources:
            answer_text = await self._extract_response_text()
            md_links = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', answer_text)
            for title, url in md_links:
                url = self._clean_url(url)
                if url not in seen_urls:
                    seen_urls.add(url)
                    sources.append({
                        "url": url,
                        "title": title.strip(),
                        "publisher": self._extract_domain(url),
                        "snippet": "",
                    })

        return sources

    @staticmethod
    def _clean_url(url: str) -> str:
        if not url:
            return url
        parsed = urlparse(url)
        # Strip common tracking params
        if parsed.query:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
            cleaned = {k: v for k, v in qs.items() if k not in tracking_params}
            cleaned_query = urlencode(cleaned, doseq=True)
            url = urlunparse(parsed._replace(query=cleaned_query))
        return url

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            host = urlparse(url).netloc
            # Strip www. prefix
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    # ---------- High-level run_prompt ----------

    async def run_prompt(self, prompt: str) -> dict:
        await self._start_new_chat()
        await self._submit_prompt_text(prompt)
        await self._wait_for_response_complete()

        answer = await self._extract_response_text()
        sources = await self._extract_sources()

        return {
            "answer": answer,
            "sources": sources,
            "response_id": "",
        }


# ====================== MAIN ======================

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile-dir", default="chatgpt_profile", help="Browser profile directory for login persistence")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to wait between prompts")
    parser.add_argument("--test", action="store_true", help="Run only the first prompt (and first company)")
    parser.add_argument("--resume", type=str, help="Resume from existing run folder (e.g., 2026-02-07_16-31-22_chatgpt)")
    args = parser.parse_args()

    runner = PromptRunner(
        prompts_file="prompts/quantum/prompts_company.json",
        icp_file="data/qnami/icp_qnami.txt",
        buyer_persona_file="data/qnami/buyer_persona_qnami.txt",
        quantum_sensing_applications_file="data/quantum-generic/applications_quantum_sensing.txt",
        profile_dir=args.profile_dir,
        headless=args.headless,
    )

    prompts = runner.load_prompts()
    companies = runner.load_companies()

    if args.test:
        prompts = prompts[:1]
        companies = companies[:1]

    CATEGORY = "Quantum Sensing"
    APPLICATIONS = runner.load_applications()
    icp_text = runner.load_icp()
    buyer_persona_text = runner.load_buyer_persona()

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
        run_folder_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_chatgpt"
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
            requires_company = "CompanyName" in p["required_vars"]
            targets = companies if requires_company else [None]

            for company in targets:
                # Skip if already completed (for resume mode)
                name = (company or "category").replace(" ", "_")
                prompt_key = f"{p['id']}_{name}"
                output_path = run_folder / f"{prompt_key}.json"
                if args.resume and (prompt_key in completed_prompts or output_path.exists()):
                    print(f"Skipping (already done): {prompt_key}")
                    continue

                prompt_text = p["template"]

                if "Category" in p["required_vars"]:
                    prompt_text = prompt_text.replace("{{Category}}", CATEGORY)

                if "Applications" in p["required_vars"]:
                    prompt_text = prompt_text.replace("{{Applications}}", APPLICATIONS)

                if company:
                    prompt_text = prompt_text.replace("{{CompanyName}}", company)

                if "CompanyICP" in p["required_vars"]:
                    prompt_text = prompt_text.replace("{{CompanyICP}}", icp_text)

                if "BuyersPersona" in p["required_vars"]:
                    prompt_text = prompt_text.replace(
                        "{{BuyersPersona}}", buyer_persona_text
                    )

                result = {
                    "prompt_id": p["id"],
                    "company": company,
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

                name = (company or "category").replace(" ", "_")
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
                    break  # use break instead of return so finally runs

                await asyncio.sleep(args.delay)

            if args.test:
                break

    finally:
        await runner.close_browser()

if __name__ == "__main__":
    asyncio.run(main())
