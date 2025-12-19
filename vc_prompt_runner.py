#!/usr/bin/env python3
"""
VC Prompt Runner - A terminal application that runs VC-focused prompts through ChatGPT
using Playwright browser automation.
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser


class PromptRunner:
    """Handles running prompts through ChatGPT via Playwright."""

    def __init__(self, variables: dict[str, str], prompts_file: str = "prompts.json"):
        self.variables = variables
        self.prompts_file = prompts_file
        self.prompts = self._load_prompts()
        self.system_prompt = self._build_system_prompt()
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.response_count_before_prompt = 0  # Track responses before each prompt

    def _load_prompts(self) -> list[dict]:
        """Load prompts from JSON file."""
        prompts_path = Path(self.prompts_file)
        if not prompts_path.exists():
            raise FileNotFoundError(f"Prompts file not found: {self.prompts_file}")

        with open(prompts_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data.get("prompts", [])

    def _build_system_prompt(self) -> str:
        """Build system prompt with variable substitution."""
        company_field = self.variables.get("companyField", "technology")
        return f"You are a VC in the {company_field} field. Add sources to your answer."

    def _substitute_variables(self, template: str) -> str:
        """Replace {{variable}} placeholders with actual values."""
        result = template
        for var_name, var_value in self.variables.items():
            placeholder = f"{{{{{var_name}}}}}"
            result = result.replace(placeholder, var_value)
        return result

    def _can_run_prompt(self, prompt_config: dict) -> bool:
        """Check if all required variables for a prompt are available."""
        required_vars = prompt_config.get("required_vars", [])
        return all(var in self.variables and self.variables[var] for var in required_vars)

    def get_runnable_prompts(self) -> list[dict]:
        """Get list of prompts that can be run with available variables."""
        runnable = []
        for prompt_config in self.prompts:
            if self._can_run_prompt(prompt_config):
                substituted_prompt = self._substitute_variables(prompt_config["template"])
                runnable.append({
                    "id": prompt_config["id"],
                    "prompt": substituted_prompt,
                    "expects_score": prompt_config.get("expects_score", False),
                })
        return runnable

    async def init_browser(self, headless: bool = False):
        """Initialize Playwright browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await self.context.new_page()

    async def close_browser(self):
        """Close browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def navigate_to_chatgpt(self):
        """Navigate to ChatGPT and wait for page to load."""
        print("Navigating to ChatGPT...")
        await self.page.goto("https://chatgpt.com/", wait_until="networkidle")
        await asyncio.sleep(2)

    async def wait_for_login(self):
        """Wait for user to log in if necessary."""
        # Check if we're on a login page or need authentication
        try:
            # Look for the main textarea which indicates we're logged in
            textarea = await self.page.wait_for_selector(
                'textarea[id="prompt-textarea"], div[id="prompt-textarea"]',
                timeout=5000
            )
            if textarea:
                print("ChatGPT is ready.")
                return
        except Exception:
            pass

        print("\n" + "=" * 60)
        print("Please log in to ChatGPT in the browser window.")
        print("Press Enter once you're logged in and see the chat interface...")
        print("=" * 60 + "\n")
        input()

        # Wait for the textarea to appear after login
        await self.page.wait_for_selector(
            'textarea[id="prompt-textarea"], div[id="prompt-textarea"]',
            timeout=60000
        )
        print("Login detected. Continuing...")

    async def set_custom_instructions(self):
        """Attempt to set custom instructions/system prompt."""
        # Note: ChatGPT's custom instructions are set in settings
        # For this implementation, we'll prepend the system context to each prompt
        print(f"System context: {self.system_prompt}")

    async def submit_prompt(self, prompt: str) -> str:
        """Submit a prompt to ChatGPT and get the response."""
        # Combine system prompt with user prompt
        full_prompt = f"[Context: {self.system_prompt}]\n\n{prompt}"

        # Count existing responses BEFORE submitting
        existing_responses = await self.page.query_selector_all(
            '[data-message-author-role="assistant"]'
        )
        self.response_count_before_prompt = len(existing_responses)
        print(f"Existing responses in chat: {self.response_count_before_prompt}")

        # Find and fill the textarea
        textarea_selector = 'textarea[id="prompt-textarea"], div[id="prompt-textarea"], #prompt-textarea'
        await self.page.wait_for_selector(textarea_selector, state="visible")

        # Clear any existing text and type the new prompt
        textarea = await self.page.query_selector(textarea_selector)

        # Use fill for textarea, or handle contenteditable div
        try:
            await textarea.fill(full_prompt)
        except Exception:
            # If it's a contenteditable div, use different approach
            await textarea.click()
            await self.page.keyboard.type(full_prompt, delay=5)

        await asyncio.sleep(0.5)

        # Click the submit button
        submit_button = await self.page.query_selector(
            'button[data-testid="send-button"], button[aria-label="Send prompt"]'
        )
        if submit_button:
            await submit_button.click()
        else:
            # Try pressing Enter
            await self.page.keyboard.press("Enter")

        # Wait for response to complete
        response = await self._wait_for_response()
        return response

    async def _wait_for_response(self) -> str:
        """Wait for ChatGPT response to complete and extract it."""
        print("Waiting for response...")

        # Wait for the response to start appearing
        await asyncio.sleep(2)

        # Wait for the streaming to stop by checking for the "Stop generating" button to disappear
        # or waiting for the response to stabilize
        max_wait_time = 120  # Maximum wait time in seconds
        check_interval = 2
        elapsed = 0
        last_response = ""
        stable_count = 0

        while elapsed < max_wait_time:
            await asyncio.sleep(check_interval)
            elapsed += check_interval

            # Get the latest response
            current_response = await self._extract_latest_response()

            # Check if response has stabilized (same content for 2 consecutive checks)
            if current_response == last_response and current_response:
                stable_count += 1
                if stable_count >= 2:
                    print("Response complete.")
                    return current_response
            else:
                stable_count = 0

            last_response = current_response

            # Also check if the stop button is gone (alternative completion signal)
            stop_button = await self.page.query_selector('button[aria-label="Stop generating"]')
            if not stop_button and current_response:
                await asyncio.sleep(1)  # Small buffer
                return await self._extract_latest_response()

        return last_response

    async def _extract_latest_response(self) -> str:
        """Extract the latest response from ChatGPT including markdown and sources."""
        # Get all response containers
        response_containers = await self.page.query_selector_all(
            '[data-message-author-role="assistant"]'
        )

        if not response_containers:
            return ""

        # Check if we have a NEW response (more than before we submitted)
        if len(response_containers) <= self.response_count_before_prompt:
            return ""  # No new response yet

        # Get only the NEW response (the one after our prompt)
        new_response = response_containers[self.response_count_before_prompt]

        # Extract the HTML content to preserve formatting
        html_content = await new_response.inner_html()

        # Convert HTML to markdown-style text
        markdown_response = self._html_to_markdown(html_content)

        return markdown_response

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML response to markdown format, preserving links."""
        # This is a simplified conversion - handles common elements
        result = html

        # Handle bold
        result = re.sub(r'<strong>(.*?)</strong>', r'**\1**', result, flags=re.DOTALL)
        result = re.sub(r'<b>(.*?)</b>', r'**\1**', result, flags=re.DOTALL)

        # Handle italic
        result = re.sub(r'<em>(.*?)</em>', r'*\1*', result, flags=re.DOTALL)
        result = re.sub(r'<i>(.*?)</i>', r'*\1*', result, flags=re.DOTALL)

        # Handle links - preserve the URL
        result = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', result, flags=re.DOTALL)

        # Handle headers
        result = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', result, flags=re.DOTALL)
        result = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', result, flags=re.DOTALL)
        result = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', result, flags=re.DOTALL)

        # Handle code blocks
        result = re.sub(r'<pre><code[^>]*>(.*?)</code></pre>', r'```\n\1\n```', result, flags=re.DOTALL)
        result = re.sub(r'<code>(.*?)</code>', r'`\1`', result, flags=re.DOTALL)

        # Handle lists
        result = re.sub(r'<li>(.*?)</li>', r'- \1\n', result, flags=re.DOTALL)
        result = re.sub(r'<ul[^>]*>', '', result)
        result = re.sub(r'</ul>', '\n', result)
        result = re.sub(r'<ol[^>]*>', '', result)
        result = re.sub(r'</ol>', '\n', result)

        # Handle paragraphs and breaks
        result = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', result, flags=re.DOTALL)
        result = re.sub(r'<br\s*/?>', '\n', result)
        result = re.sub(r'<div[^>]*>', '', result)
        result = re.sub(r'</div>', '\n', result)

        # Remove remaining HTML tags
        result = re.sub(r'<[^>]+>', '', result)

        # Clean up whitespace
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = result.strip()

        # Decode HTML entities
        result = result.replace('&amp;', '&')
        result = result.replace('&lt;', '<')
        result = result.replace('&gt;', '>')
        result = result.replace('&quot;', '"')
        result = result.replace('&#39;', "'")
        result = result.replace('&nbsp;', ' ')

        return result

    def extract_sources(self, response: str) -> list[str]:
        """Extract source URLs from the response."""
        # Find all URLs in markdown link format [text](url)
        markdown_links = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', response)
        sources = [url for _, url in markdown_links]

        # Also find standalone URLs
        standalone_urls = re.findall(r'(?<!\()https?://[^\s\)\]]+', response)

        # Combine and deduplicate while preserving order
        all_sources = []
        seen = set()
        for url in sources + standalone_urls:
            if url not in seen:
                all_sources.append(url)
                seen.add(url)

        return all_sources

    def extract_score(self, response: str, expects_score: bool) -> Optional[int]:
        """Extract numerical score from response if expected."""
        if not expects_score:
            return None

        # Look for score patterns - ordered by specificity (most specific first)
        patterns = [
            # "Score: **7**/10" or "**7/10**"
            r'\*\*(\d+)\s*[/]\s*10\*\*',
            r'\*\*(\d+)\*\*\s*[/]\s*10',
            # "Score: 7/10" or "7/10"
            r'(?:score|rating)[:\s]*(\d+)\s*[/]\s*10',
            r'(\d+)\s*[/]\s*10',
            # "Score: 7 out of 10"
            r'(?:score|rating)[:\s]*(\d+)\s*(?:out of)\s*10',
            r'(\d+)\s*(?:out of)\s*10',
            # "**Score: 7**" or "Score: **7**"
            r'\*\*(?:score|rating)[:\s]*(\d+)\*\*',
            r'(?:score|rating)[:\s]*\*\*(\d+)\*\*',
            # "I would rate this a 7" or "I give it a 7"
            r'(?:rate|give|assign)[^.]{0,30}(?:a\s+)?(\d+)',
            # Just "Score: 7" or "Rating: 7"
            r'(?:score|rating)[:\s]*(\d+)',
            # Bold number at start of response (common pattern)
            r'^[*\s]*\*\*(\d+)\*\*',
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE | re.MULTILINE)
            if match:
                score = int(match.group(1))
                if 1 <= score <= 10:
                    return score

        return None

    async def start_new_chat(self):
        """Start a new chat session."""
        print("Starting new chat...")

        # Always navigate to base URL to ensure fresh chat
        # Adding a cache-busting parameter to force fresh load
        await self.page.goto("https://chatgpt.com/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Wait for the textarea to be ready
        textarea_selector = 'textarea[id="prompt-textarea"], div[id="prompt-textarea"], #prompt-textarea'
        await self.page.wait_for_selector(textarea_selector, state="visible", timeout=30000)

        # Verify no assistant messages exist (fresh chat)
        response_containers = await self.page.query_selector_all(
            '[data-message-author-role="assistant"]'
        )

        if len(response_containers) > 0:
            print(f"Warning: Found {len(response_containers)} existing responses after new chat navigation")
            # Try clicking the new chat button as backup
            try:
                new_chat_btn = await self.page.query_selector(
                    'a[data-testid="create-new-chat-button"], nav a[href="/"], button:has-text("New chat")'
                )
                if new_chat_btn:
                    await new_chat_btn.click()
                    await asyncio.sleep(2)
                    await self.page.wait_for_selector(textarea_selector, state="visible", timeout=30000)
            except Exception as e:
                print(f"Could not click new chat button: {e}")

        # Reset counter for fresh chat
        self.response_count_before_prompt = 0
        print("New chat ready.")


class ResultsManager:
    """Manages the output results."""

    def __init__(self, company_field: str, company_name: str):
        self.company_field = company_field or "general"
        self.company_name = company_name or "unknown"
        self.results: list[dict] = []

    def add_result(self, prompt: str, answer: str, sources: list[str], score: Optional[int]):
        """Add a result to the collection."""
        self.results.append({
            "prompt": prompt,
            "answer": answer,
            "sources": sources,
            "score": score
        })

    def get_output_filename(self) -> str:
        """Generate output filename."""
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        # Clean up names for filename
        field_clean = re.sub(r'[^\w\-]', '_', self.company_field)
        name_clean = re.sub(r'[^\w\-]', '_', self.company_name)
        return f"{field_clean}-{name_clean}-{date_str}.json"

    def save(self, output_dir: str = "."):
        """Save results to JSON file."""
        filename = self.get_output_filename()
        filepath = Path(output_dir) / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        print(f"\nResults saved to: {filepath}")
        return filepath


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="VC Prompt Runner - Run VC-focused prompts through ChatGPT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --companyField "quantum computing" --CompanyName "IonQ"
  %(prog)s --companyField "AI" --CompanyName "OpenAI" --CompanyProblems "LLM scaling"
  %(prog)s --companyField "biotech" --CompanyName "Moderna" --headless
        """
    )

    # Variable arguments
    parser.add_argument(
        "--companyField",
        type=str,
        help="The industry/field (e.g., 'quantum computing', 'AI', 'biotech')"
    )
    parser.add_argument(
        "--CompanyName",
        type=str,
        help="Name of the company to analyze"
    )
    parser.add_argument(
        "--CompanyProblems",
        type=str,
        help="Problems the company claims to solve"
    )
    parser.add_argument(
        "--CompanyICP",
        type=str,
        help="Company's Ideal Customer Profile"
    )
    parser.add_argument(
        "--BuyersPersona",
        type=str,
        help="Company's target buyer persona"
    )

    # Configuration arguments
    parser.add_argument(
        "--prompts-file",
        type=str,
        default="prompts.json",
        help="Path to prompts JSON file (default: prompts.json)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory for results (default: current directory)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for ChatGPT)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which prompts would run without executing"
    )
    parser.add_argument(
        "--prompt-ids",
        type=str,
        nargs="+",
        help="Only run specific prompt IDs"
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_arguments()

    # Build variables dictionary from arguments
    variables = {}
    if args.companyField:
        variables["companyField"] = args.companyField
    if args.CompanyName:
        variables["CompanyName"] = args.CompanyName
    if args.CompanyProblems:
        variables["CompanyProblems"] = args.CompanyProblems
    if args.CompanyICP:
        variables["CompanyICP"] = args.CompanyICP
    if args.BuyersPersona:
        variables["BuyersPersona"] = args.BuyersPersona

    if not variables:
        print("Error: At least one variable argument is required.")
        print("Use --help for more information.")
        sys.exit(1)

    # Initialize prompt runner
    try:
        runner = PromptRunner(variables, args.prompts_file)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Get runnable prompts
    runnable_prompts = runner.get_runnable_prompts()

    # Filter by specific IDs if provided
    if args.prompt_ids:
        runnable_prompts = [p for p in runnable_prompts if p["id"] in args.prompt_ids]

    if not runnable_prompts:
        print("No prompts can be run with the provided variables.")
        print("\nAvailable variables provided:")
        for k, v in variables.items():
            print(f"  --{k}: {v}")
        sys.exit(1)

    print(f"\nFound {len(runnable_prompts)} prompts to run:")
    for i, p in enumerate(runnable_prompts, 1):
        preview = p["prompt"][:60] + "..." if len(p["prompt"]) > 60 else p["prompt"]
        print(f"  {i}. [{p['id']}] {preview}")

    if args.dry_run:
        print("\n[Dry run mode - no prompts will be executed]")
        sys.exit(0)

    # Initialize results manager
    results_manager = ResultsManager(
        variables.get("companyField", ""),
        variables.get("CompanyName", "")
    )

    # Start browser and run prompts
    try:
        await runner.init_browser(headless=args.headless)
        await runner.navigate_to_chatgpt()
        await runner.wait_for_login()

        for i, prompt_config in enumerate(runnable_prompts, 1):
            print(f"\n{'='*60}")
            print(f"Running prompt {i}/{len(runnable_prompts)}: {prompt_config['id']}")
            print(f"{'='*60}")
            print(f"Prompt: {prompt_config['prompt'][:100]}...")

            # Start new chat for each prompt
            if i > 1:
                await runner.start_new_chat()

            # Submit prompt and get response
            response = await runner.submit_prompt(prompt_config["prompt"])

            # Extract sources and score
            sources = runner.extract_sources(response)
            score = runner.extract_score(response, prompt_config["expects_score"])

            # Add to results
            results_manager.add_result(
                prompt=prompt_config["prompt"],
                answer=response,
                sources=sources,
                score=score
            )

            print(f"\nResponse length: {len(response)} characters")
            print(f"Sources found: {len(sources)}")
            if score is not None:
                print(f"Score extracted: {score}/10")

            # Small delay between prompts
            await asyncio.sleep(2)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Saving partial results...")
    except Exception as e:
        print(f"\nError occurred: {e}")
        print("Saving partial results...")
    finally:
        # Save results
        if results_manager.results:
            results_manager.save(args.output_dir)

        # Cleanup
        await runner.close_browser()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
