#!/usr/bin/env python3

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from openai import AsyncOpenAI


class PromptRunner:
    def __init__(
        self,
        prompts_file: str,
        icp_file: str,
        buyer_persona_file: str,
        quantum_sensing_applications_file: str,
        model: str = "gpt-4.1"
    ):
        self.prompts_file = prompts_file
        self.icp_file = Path(icp_file)
        self.buyer_persona_file = Path(buyer_persona_file)
        self.quantum_sensing_applications_file = Path(quantum_sensing_applications_file)
        self.model = model
        self.client = AsyncOpenAI()

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

    # ---------- API Call ----------

    async def run_prompt(self, prompt: str) -> dict:
        response = await self.client.responses.create(
            model=self.model,
            tools=[
                {
                    "type": "web_search",
                    "search_context_size": "medium"
                }
            ],
            input=prompt,
            temperature=0.2,
        )

        answer_chunks = []
        sources = []

        for item in response.output:
            if item.type != "message":
                continue

            for block in item.content:
                if block.type == "output_text":
                    answer_chunks.append(block.text)

                    # Collect every citation occurrence
                    for ann in block.annotations or []:
                        if ann.type == "web_citation":
                            sources.append({
                                "url": ann.url,
                                "title": ann.title,
                                "publisher": ann.publisher,
                                "snippet": ann.snippet,
                            })

        return {
            "answer": "\n".join(answer_chunks).strip(),
            "sources": sources,  # duplicates preserved by design
            "response_id": response.id,
        }




# ====================== MAIN ======================

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--test", action="store_true", help="Run only the first prompt (and first company)")
    args = parser.parse_args()

    runner = PromptRunner(
        prompts_file="prompts/quantum/prompts_quantum_companies.json",
        icp_file="data/qnami/icp_qnami.txt",
        buyer_persona_file="data/qnami/buyer_persona_qnami.txt",
        quantum_sensing_applications_file="data/quantum-generic/applications_quantum_sensing.txt",
        model=args.model
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
    run_folder = results_root / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    run_folder.mkdir(parents=True, exist_ok=True)

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
                "model": args.model,
                "test_mode": args.test,
            }

            try:
                response = await runner.run_prompt(prompt_text)
                result["answer"] = response["answer"]
                result["sources"] = response["sources"]
                result["response_id"] = response["response_id"]

            except Exception as e:
                result["error"] = str(e)

            name = (company or "category").replace(" ", "_")
            output_path = run_folder / f"{p['id']}_{name}.json"

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            if args.test:
                return  # hard stop after first execution

            await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
