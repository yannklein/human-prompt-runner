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
        self.playwright = None

    def load_prompts(self):
        with open(self.prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("prompts", [])

    def load_companies(self, filepath="companies.txt"):
        if not Path(filepath).exists(): return []
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    async def kill_blockers(self):
        """Standard JS method to remove interference elements."""
        await self.page.evaluate('''() => {
            const selectors = [
                'div[role="dialog"]',
                '.fixed.inset-0',
                '.absolute.right-4.top-4',
                'div[id^="radix-"]',
                'div#sodal-no-auth-rate-limit'
            ];
            selectors.forEach(s => {
                try {
                    document.querySelectorAll(s).forEach(el => el.remove());
                } catch (e) {}
            });

            // Find and remove by text (Login/Stay logged out/Restore)
            const elements = document.querySelectorAll('button, div, span, a');
            elements.forEach(el => {
                const txt = el.innerText || "";
                if (txt.includes("Stay logged out") || txt.includes("Restore pages") || txt.includes("Log in or sign up")) {
                    el.remove();
                }
            });

            document.body.style.pointerEvents = 'auto';
            document.body.style.overflow = 'auto';
            document.documentElement.style.pointerEvents = 'auto';
        }''')

    async def open_browser(self, headless: bool):
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir="./chatgpt_profile",
            headless=headless,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-session-crashed-bubble",
            ]
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => false})")

        print("Navigating to ChatGPT...")
        await self.page.goto("https://chatgpt.com/")
        await asyncio.sleep(4)
        await self.kill_blockers()

        try:
            await self.page.wait_for_selector("#prompt-textarea", timeout=20000)
        except:
            await self.kill_blockers()
            await self.page.wait_for_selector("#prompt-textarea", timeout=10000)

    async def close_browser(self):
        if self.context: await self.context.close()
        if self.playwright: await self.playwright.stop()

    async def submit_prompt(self, prompt: str):
        await self.kill_blockers()
        textarea = await self.page.wait_for_selector("#prompt-textarea")
        await textarea.fill(prompt)
        await asyncio.sleep(1)

        send_btn = 'button[data-testid="send-button"]'
        await self.page.evaluate('selector => { const b = document.querySelector(selector); if(b) b.click(); }', send_btn)

        await asyncio.sleep(0.5)
        await self.page.keyboard.press("Enter")

        return await self.wait_for_response()

    async def wait_for_response(self):
        # 1. Wait for assistant to start
        await self.page.wait_for_selector('[data-message-author-role="assistant"]', timeout=45000)
        print("Assistant is responding...")

        # 2. Loop until done, killing blockers repeatedly
        # This solves the problem of a modal appearing halfway through typing
        finish_selectors = 'button[data-testid="send-button"]:not([disabled]), button[aria-label="Share chat"], button:has-text("Regenerate")'

        for _ in range(36): # 3 minutes total (36 * 5s)
            try:
                # Check if we are done
                done = await self.page.query_selector(finish_selectors)
                if done and await done.is_visible():
                    print("Generation complete.")
                    break
            except:
                pass

            # Not done yet? Kill any new modals that appeared
            await self.kill_blockers()
            await asyncio.sleep(5)

        await asyncio.sleep(2)
        messages = await self.page.query_selector_all('[data-message-author-role="assistant"]')
        last_message = messages[-1]
        text = await last_message.inner_text()

        links = []
        for a in await last_message.query_selector_all('a[href^="http"]'):
            href = await a.get_attribute("href")
            if href and "openai.com" not in href: links.append(href)

        return text, list(set(links))

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
        targets = companies if (requires_company and companies) else [None]

        for company in targets:
            prompt_text = p["template"]
            if company:
                prompt_text = prompt_text.replace("{{CompanyName}}", company)

            print(f"\n🚀 Fresh Session: {p['id']} ({company or 'General'})")
            await runner.open_browser(args.headless)

            result = {
                "prompt_id": p["id"],
                "company": company,
                "answer": "FAILED",
                "sources": [],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            try:
                text, sources = await runner.submit_prompt(prompt_text)
                result["answer"] = text
                result["sources"] = sources
                print(f"✅ Success.")
            except Exception as e:
                print(f"❌ Error: {e}")
                result["error"] = str(e)
            finally:
                safe_name = str(company or 'general').replace(" ", "_")
                with open(run_folder / f"{p['id']}_{safe_name}.json", "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                await runner.close_browser()

            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
