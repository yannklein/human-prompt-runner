#!/usr/bin/env python3

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext


class PromptRunner:

    def __init__(self, prompts_file: str):
        self.prompts_file = prompts_file
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.browser = None
        self.playwright = None

    # ---------- Loaders ----------

    def load_prompts(self):
        with open(self.prompts_file, "r", encoding="utf-8") as f:
            return json.load(f)["prompts"]

    def load_companies(self, filepath="companies.txt"):
        if not Path(filepath).exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    # ---------- Browser (true incognito) ----------

    async def open_browser(self, headless: bool):
        self.playwright = await async_playwright().start()

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir="./chatgpt_profile",
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="UTC",
            args=["--disable-blink-features=AutomationControlled"]
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        await self.page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
        await self.page.wait_for_selector("#prompt-textarea", timeout=60000)

    async def close_browser(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()


    # ---------- Chat ----------

    async def submit_prompt(self, prompt: str):
        textarea = await self.page.wait_for_selector("#prompt-textarea")
        await textarea.fill(prompt)
        await self.page.keyboard.press("Enter")
        return await self.wait_for_response()

    async def wait_for_response(self):
        await self.page.wait_for_selector('[data-message-author-role="assistant"]')
        await asyncio.sleep(12)

        messages = await self.page.query_selector_all('[data-message-author-role="assistant"]')
        message = messages[-1]

        text = await message.inner_text()
        sources = await self.extract_sources(message)

        return text, sources

    # ---------- Source extraction ----------

    async def extract_sources(self, message):
        collected = set()

        for a in await message.query_selector_all('a[href^="http"]'):
            collected.add(await a.get_attribute("href"))

        for btn in await message.query_selector_all('button:has-text("[")'):
            await self.page.evaluate("(btn) => btn.click()", btn)
            await asyncio.sleep(0.4)
            for a in await self.page.query_selector_all('div[role="dialog"] a[href^="http"]'):
                collected.add(await a.get_attribute("href"))
            await self.page.keyboard.press("Escape")

        sources_button = await self.page.query_selector('button:has-text("Sources")')
        if sources_button:
            await self.page.evaluate("(btn) => btn.click()", sources_button)
            await asyncio.sleep(1)
            for a in await self.page.query_selector_all('aside a[href^="http"]'):
                collected.add(await a.get_attribute("href"))
            await self.page.keyboard.press("Escape")

        return list(collected)


# ================== MAIN ==================

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    results_root = Path("results")
    results_root.mkdir(exist_ok=True)

    run_folder = results_root / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    run_folder.mkdir(parents=True, exist_ok=True)

    runner = PromptRunner("prompts.json")
    prompts = runner.load_prompts()
    companies = runner.load_companies()

    for p in prompts:
        requires_company = "CompanyName" in p.get("required_vars", [])
        targets = companies if requires_company else [None]

        for company in targets:
            prompt = p["template"]
            if company:
                prompt = prompt.replace("{{CompanyName}}", company)

            print(f"\nRunning {p['id']}" + (f" — {company}" if company else ""))

            await runner.open_browser(args.headless)

            try:
                text, sources = await runner.submit_prompt(prompt)

                result = {
                    "prompt_id": p["id"],
                    "company": company,
                    "prompt": prompt,
                    "answer": text,
                    "sources": sources,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

                out_file = run_folder / f"{p['id']}.json"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)

            finally:
                await runner.close_browser()

            await asyncio.sleep(4)

    print(f"\nRun complete. Results saved to: {run_folder}")


if __name__ == "__main__":
    asyncio.run(main())
