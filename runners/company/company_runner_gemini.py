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


class PromptRunner:
    def __init__(
        self,
        prompts_file: str,
        icp_file: str,
        buyer_persona_file: str,
        quantum_sensing_applications_file: str,
        profile_dir: str = "gemini_profile",
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
        """Dismiss cookie consent, ToS, or onboarding overlays for Gemini."""
        dismissed = False

        # Try dismissing cookie consent or onboarding dialogs
        for selector in [
            'button:has-text("I agree")',
            'button:has-text("Accept all")',
            'button:has-text("Got it")',
            'button:has-text("Dismiss")',
            'button:has-text("OK")',
            'button:has-text("Continue")',
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
                '[role="dialog"]',
                '[role="alertdialog"]',
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

    async def _find_input_area(self):
        """Locate Gemini's input area (contenteditable div or rich-textarea)."""
        for selector in [
            'div.ql-editor[contenteditable="true"]',
            'rich-textarea .textarea',
            'div[contenteditable="true"]',
        ]:
            try:
                el = self._page.locator(selector)
                if await el.count() > 0 and await el.first.is_visible():
                    return el.first
            except Exception:
                continue
        return None

    async def ensure_logged_in(self):
        await self._page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Dismiss any blocking modals
        await self._dismiss_modals()

        input_area = await self._find_input_area()
        if input_area:
            print("Gemini session is active.")
            return

        print("Not logged in. Please log in to Google in the browser window.")
        print("Waiting for login (up to 120s)...")

        # Wait for input area to appear after login
        elapsed = 0
        while elapsed < 120:
            await asyncio.sleep(3)
            elapsed += 3
            await self._dismiss_modals()
            input_area = await self._find_input_area()
            if input_area:
                print("Login detected. Continuing.")
                return

        print("Login timeout. Exiting.", file=sys.stderr)
        await self.close_browser()
        sys.exit(1)

    # ---------- Chat Interaction ----------

    async def _start_new_chat(self):
        await self._page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        await self._dismiss_modals()

        # Wait for input area
        elapsed = 0
        while elapsed < 30:
            input_area = await self._find_input_area()
            if input_area:
                break
            await asyncio.sleep(1)
            elapsed += 1
        else:
            raise TimeoutError("Input area not found after navigating to Gemini")

        await asyncio.sleep(1)

    async def _submit_prompt_text(self, text: str):
        # Dismiss any modal that may have appeared
        await self._dismiss_modals()

        input_area = await self._find_input_area()
        if not input_area:
            raise RuntimeError("Cannot find Gemini input area")

        await input_area.click()
        await asyncio.sleep(0.3)

        # Use Playwright's fill() for regular inputs, or type for contenteditable
        try:
            # Try fill first (works for textarea/input)
            await input_area.fill(text)
        except Exception:
            # For contenteditable, use type() which simulates keyboard input
            # Clear existing content first
            modifier = "Meta" if sys.platform == "darwin" else "Control"
            await self._page.keyboard.press(f"{modifier}+a")
            await self._page.keyboard.press("Backspace")
            await input_area.type(text, delay=5)  # Small delay between chars for reliability

        await asyncio.sleep(0.5)

        # Click send button with multiple selector fallbacks
        send_btn = None
        for selector in [
            'button.send-button',
            'button[aria-label="Send message"]',
            'button[aria-label="Send"]',
            'button[data-testid="send-button"]',
            'button:has(mat-icon:text("send"))',
            '[aria-label="Send message"] button',
        ]:
            try:
                el = self._page.locator(selector)
                if await el.count() > 0 and await el.first.is_visible():
                    send_btn = el.first
                    break
            except Exception:
                continue

        if not send_btn:
            raise RuntimeError("Cannot find Gemini send button")

        await send_btn.wait_for(state="visible", timeout=10000)
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
            stop_visible = False
            for selector in [
                'button[aria-label="Stop"]',
                'button[aria-label="Stop generating"]',
            ]:
                try:
                    stop_btn = self._page.locator(selector)
                    if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
                        stop_visible = True
                        break
                except Exception:
                    continue

            # Get current response text
            current_text = await self._get_last_response_text()

            if current_text and current_text == last_text:
                stable_count += 1
            else:
                stable_count = 0
            last_text = current_text

            # Done when stop button is gone AND text is stable
            if not stop_visible and stable_count >= required_stable and current_text:
                return

        raise TimeoutError(f"Response did not complete within {timeout_s}s")

    async def _get_last_response_text(self) -> str:
        for selector in [
            '.model-response-text .markdown',
            '.response-container .markdown',
            'message-content .markdown',
            'model-response .markdown',
        ]:
            try:
                elements = self._page.locator(selector)
                count = await elements.count()
                if count > 0:
                    return await elements.nth(count - 1).inner_text()
            except Exception:
                continue
        return ""

    async def _extract_response_text(self) -> str:
        return await self._get_last_response_text()

    async def _extract_sources(self) -> List[dict]:
        sources = []
        seen_urls = set()

        # Layer 1: Extract <a href> links from the last response
        for selector in [
            '.model-response-text .markdown',
            '.response-container .markdown',
            'message-content .markdown',
            'model-response .markdown',
        ]:
            try:
                elements = self._page.locator(selector)
                count = await elements.count()
                if count > 0:
                    last_msg = elements.nth(count - 1)
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
                    if sources:
                        break
            except Exception:
                continue

        # Layer 2: Look for source card elements
        source_selectors = [
            '[class*="source"]',
            '[class*="citation"]',
            '[class*="reference"]',
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
    parser.add_argument("--profile-dir", default="gemini_profile", help="Browser profile directory for login persistence")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to wait between prompts")
    parser.add_argument("--test", action="store_true", help="Run only the first prompt (and first company)")
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
    run_folder_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_gemini"
    run_folder = results_root / run_folder_name
    run_folder.mkdir(parents=True, exist_ok=True)

    # Ensure BigQuery tables exist
    if BQ_AVAILABLE:
        try:
            ensure_all_tables_exist()
            print("BigQuery tables verified (including sources_analysis)")
        except Exception as e:
            print(f"Warning: Could not verify BigQuery tables: {e}")

    await runner.start_browser()
    try:
        await runner.ensure_logged_in()

        for p in prompts:
            requires_company = "CompanyName" in p["required_vars"]
            targets = companies if requires_company else [None]

            for company in targets:
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

                name = (company or "category").replace(" ", "_")
                output_path = run_folder / f"{p['id']}_{name}.json"

                # Upload to BigQuery (save locally only if upload fails)
                if BQ_AVAILABLE:
                    if upload_result(result, run_folder_name):
                        print(f"Uploaded to BigQuery: {p['id']}_{name}")

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
                    break  # use break instead of return so finally runs

                await asyncio.sleep(args.delay)

            if args.test:
                break

    finally:
        await runner.close_browser()

if __name__ == "__main__":
    asyncio.run(main())
