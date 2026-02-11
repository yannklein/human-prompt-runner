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
        profile_dir: str = "perplexity_profile",
        headless: bool = False,
    ):
        self.prompts_file = prompts_file
        self.icp_file = Path(icp_file)
        self.buyer_persona_file = Path(buyer_persona_file)
        self.quantum_sensing_applications_file = Path(quantum_sensing_applications_file)
        self.profile_dir = profile_dir
        self.headless = headless

        self._playwright = None
        self._context = None
        self._page = None

    # ---------- Loaders ----------

    def load_prompts(self) -> List[dict]:
        with open(self.prompts_file, "r", encoding="utf-8") as f:
            return json.load(f).get("prompts", [])

    def _load_text_file(self, path: Path, label: str) -> str:
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def load_icp(self) -> str:
        return self._load_text_file(self.icp_file, "ICP")

    def load_applications(self) -> str:
        return self._load_text_file(self.quantum_sensing_applications_file, "Applications")

    def load_buyer_persona(self) -> str:
        return self._load_text_file(self.buyer_persona_file, "Buyer persona")

    def load_companies(self, filepath="companies.txt") -> List[str]:
        path = Path(filepath)
        if not path.exists():
            return []
        return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # ---------- Browser ----------

    async def start_browser(self):
        self._playwright = await async_playwright().start()
        profile_path = str(Path(self.profile_dir).resolve())

        self._context = await self._playwright.chromium.launch_persistent_context(
            profile_path,
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )

        # BLOCK ALL EXTERNAL NAVIGATION (context-level)
        await self._context.route(
            "**/*",
            lambda route, request: (
                route.continue_()
                if not request.is_navigation_request()
                or "perplexity.ai" in request.url
                else route.abort()
            )
        )

        # KILL ALL POPUPS / NEW TABS
        self._context.on("page", lambda page: asyncio.create_task(page.close()))

        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        # Disable window.open defensively
        await self._page.add_init_script("window.open = () => null;")

    async def close_browser(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()

    # ---------- UI helpers ----------

    async def _dismiss_modals(self):
        for selector in [
            'button:has-text("Accept")',
            'button:has-text("Got it")',
            'button:has-text("Dismiss")',
            'button:has-text("Skip")',
            'button[aria-label="Close"]',
        ]:
            try:
                el = self._page.locator(selector)
                if await el.count() > 0 and await el.first.is_visible():
                    await el.first.click()
                    await asyncio.sleep(1)
                    return
            except Exception:
                pass
        try:
            await self._page.keyboard.press("Escape")
        except Exception:
            pass

    async def _expand_and_load_all_sources(self):
        for selector in [
            'button:has-text("Show more")',
            'button:has-text("More")',
            'button[aria-label*="expand"]',
            '[class*="expand"] button',
        ]:
            try:
                buttons = self._page.locator(selector)
                for i in range(await buttons.count()):
                    btn = buttons.nth(i)
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.3)
            except Exception:
                pass

        last = 0
        stable = 0
        while stable < 3:
            count = await self._page.locator('a[href]').count()
            stable = stable + 1 if count == last else 0
            last = count
            await self._page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)

    async def _find_input_area(self):
        for selector in [
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]',
            'textarea',
        ]:
            el = self._page.locator(selector)
            if await el.count() > 0 and await el.first.is_visible():
                return el.first
        return None

    async def ensure_logged_in(self):
        await self._page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await self._dismiss_modals()

        for _ in range(40):
            if await self._find_input_area():
                return
            await asyncio.sleep(2)

        raise RuntimeError("Perplexity input area not found.")

    # ---------- Chat ----------

    async def _start_new_chat(self):
        await self._page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        await self._dismiss_modals()

    async def _submit_prompt_text(self, text: str):
        input_area = await self._find_input_area()
        if not input_area:
            raise RuntimeError("Input area missing")

        await input_area.click()
        mod = "Meta" if sys.platform == "darwin" else "Control"
        await self._page.keyboard.press(f"{mod}+a")
        await self._page.keyboard.press("Backspace")

        # Use Playwright's fill() which properly triggers React state updates
        await input_area.fill(text)
        await asyncio.sleep(0.3)
        await self._page.keyboard.press("Enter")

    async def _get_last_answer_block(self):
        for selector in ['[class*="prose"]', '[class*="markdown"]', '[class*="answer"]']:
            els = self._page.locator(selector)
            if await els.count():
                return els.nth(await els.count() - 1)
        return None

    async def _get_last_response_text(self) -> str:
        block = await self._get_last_answer_block()
        return await block.inner_text() if block else ""

    async def _wait_for_response_complete(self, timeout=180):
        last = 0
        stable = 0
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            txt = await self._get_last_response_text()
            if not txt:
                continue
            l = len(txt)
            stable = stable + 1 if l == last else 0
            last = l
            if stable >= 3:
                return
        raise TimeoutError("Response did not stabilize")

    # ---------- Sources ----------

    async def _harvest_citation_popovers(self, sources):
        triggers = self._page.locator('sup, button[class*="citation"], span[class*="citation"]')
        for i in range(await triggers.count()):
            t = triggers.nth(i)
            if not await t.is_visible():
                continue
            try:
                await t.click()
                await asyncio.sleep(0.3)
                pops = self._page.locator('[role="dialog"], [class*="popover"], [class*="tooltip"]')
                for p in range(await pops.count()):
                    links = pops.nth(p).locator('a[href]')
                    for j in range(await links.count()):
                        href = self._unwrap_perplexity_url(
                            self._clean_url(await links.nth(j).get_attribute("href"))
                        )
                        title = (await links.nth(j).inner_text()).strip()
                        if href and href.startswith("http"):
                            sources.append(self._source_obj(href, title))
                await self._page.keyboard.press("Escape")
            except Exception:
                await self._page.keyboard.press("Escape")

    async def _extract_sources(self) -> List[dict]:
        await self._expand_and_load_all_sources()
        sources = []

        for selector in ['[class*="Source"]', '[class*="Citation"]', '[class*="reference"]']:
            cards = self._page.locator(selector)
            for i in range(await cards.count()):
                links = cards.nth(i).locator('a[href]')
                for j in range(await links.count()):
                    href = self._unwrap_perplexity_url(
                        self._clean_url(await links.nth(j).get_attribute("href"))
                    )
                    title = (await links.nth(j).inner_text()).strip()
                    if href and href.startswith("http"):
                        sources.append(self._source_obj(href, title))

        block = await self._get_last_answer_block()
        if block:
            links = block.locator('a[href]')
            for i in range(await links.count()):
                href = self._unwrap_perplexity_url(
                    self._clean_url(await links.nth(i).get_attribute("href"))
                )
                title = (await links.nth(i).inner_text()).strip()
                if href and href.startswith("http"):
                    sources.append(self._source_obj(href, title))

        await self._harvest_citation_popovers(sources)
        return sources

    @staticmethod
    def _unwrap_perplexity_url(url: str) -> str:
        if not url:
            return ""
        p = urlparse(url)
        if "perplexity.ai" in p.netloc and p.path.startswith("/out"):
            return parse_qs(p.query).get("url", [""])[0]
        return url

    @staticmethod
    def _clean_url(url: str) -> str:
        p = urlparse(url)
        qs = {k: v for k, v in parse_qs(p.query).items() if not k.startswith("utm_")}
        return urlunparse(p._replace(query=urlencode(qs, doseq=True)))

    @staticmethod
    def _source_obj(url, title):
        return {
            "url": url,
            "title": title,
            "publisher": urlparse(url).netloc.replace("www.", ""),
            "snippet": "",
        }

    # ---------- Public ----------

    async def run_prompt(self, prompt: str) -> dict:
        await self._start_new_chat()
        await self._submit_prompt_text(prompt)
        await self._wait_for_response_complete()
        return {
            "answer": await self._get_last_response_text(),
            "sources": await self._extract_sources(),
            "response_id": "",
        }


# ====================== MAIN ======================

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--profile-dir", default="perplexity_profile")
    parser.add_argument("--delay", type=float, default=5.0)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--companies-file", default="quantum_sensing_companies.txt", help="Path to companies list file")
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
    companies = runner.load_companies(args.companies_file)

    if args.test:
        prompts = prompts[:1]
        companies = companies[:1]

    CATEGORY = "Quantum Sensing"
    APPLICATIONS = runner.load_applications()
    icp_text = runner.load_icp()
    buyer_persona_text = runner.load_buyer_persona()

    # ---------- RESULTS FOLDER ----------
    results_root = Path("results")
    results_root.mkdir(exist_ok=True)

    run_folder_name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_perplexity"
    run_folder = results_root / run_folder_name
    run_folder.mkdir(parents=True, exist_ok=True)

    # Ensure BigQuery tables exist
    if BQ_AVAILABLE:
        try:
            ensure_all_tables_exist()
            print("BigQuery per-prompt tables verified")
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
                    prompt_text = prompt_text.replace("{{BuyersPersona}}", buyer_persona_text)

                result = {
                    "prompt_id": p["id"],
                    "company": company,
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
                    break

                await asyncio.sleep(args.delay)

            if args.test:
                break

    finally:
        await runner.close_browser()



if __name__ == "__main__":
    asyncio.run(main())
