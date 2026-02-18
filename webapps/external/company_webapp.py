#!/usr/bin/env python3
"""
Company Evaluation Web App

A local Flask web app that displays company evaluation results:
- Interactive spider chart
- Click on dimensions to drill into individual prompts
- View AI answers and sources per prompt

Usage:
    python company_webapp.py
    python company_webapp.py --port 5002
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urllib.parse import urlparse

from flask import Flask, render_template_string, jsonify, request, redirect, url_for

from company_analysis import (
    CATEGORIES,
    AI_WEIGHTS,
    _normalize_ai_name,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Company group registry — maps list files to display labels
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent

COMPANY_GROUPS = {
    "quantum_computing_photonics_companies.txt": "Quantum Computing — Photonics",
    "quantum_sensing_companies.txt": "Quantum Sensing",
}


def _load_company_groups():
    """Read company list files and return grouped company data.

    Returns:
        (groups_by_company, all_companies_grouped) where:
        - groups_by_company[company_name] = {
            "group_label": str,
            "peers": [other_companies_in_same_file]
          }
        - all_companies_grouped = [
            {"label": group_label, "companies": [company_names]}
          ]
    """
    groups_by_company = {}
    all_companies_grouped = []

    for filename, label in COMPANY_GROUPS.items():
        filepath = PROJECT_ROOT / filename
        if not filepath.exists():
            continue
        companies = [
            line.strip() for line in filepath.read_text().splitlines()
            if line.strip()
        ]
        all_companies_grouped.append({"label": label, "companies": companies})
        for company in companies:
            peers = [c for c in companies if c != company]
            groups_by_company[company] = {"group_label": label, "peers": peers}

    return groups_by_company, all_companies_grouped


# Prompt keywords for external display (instead of full prompt text)
PROMPT_KEYWORDS = {
    "P10": "Company Overview",
    "P11": "Technical Capabilities",
    "P12": "Team & Leadership",
    "P13": "Funding & Investment",
    "P14": "Competitive Position",
    "P15": "Market Traction",
    "P16": "IP & Patents",
    "P17": "Partnerships",
    "P18": "Team Background",
    "P19": "Talent Attraction",
    "P20": "Technology Differentiation",
    "P21": "Publication Record",
    "P22": "Patent Portfolio",
    "P23": "Customer Validation",
    "P24": "Revenue Traction",
    "P25": "Investor Interest",
    "P26": "VC Backing",
    "P27": "Market Perception",
}

# Source type patterns
SOURCE_TYPE_PATTERNS = {
    "Quantum Media": ["spinquanta", "quantum.org", "thequantuminsider"],
    "Tech Media": ["techcrunch", "wired", "arstechnica", "theverge", "zdnet"],
    "Financial Media": ["bloomberg", "reuters", "wsj", "ft.com", "cnbc", "forbes"],
    "VC / Investment Firm": ["ventures", "capital", "vc", "crunchbase"],
    "Academic / Research": ["arxiv", "nature.com", "science.org", "ieee"],
    "Social / UGC": ["linkedin", "twitter", "x.com", "reddit", "medium.com"],
}


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or ""
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return ""


def _categorize_source(domain: str) -> str:
    domain_lower = domain.lower()
    for category, patterns in SOURCE_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in domain_lower:
                return category
    return "Other"


DIMENSION_WEIGHTS = {
    "Team & Ability to Attract Talent": 0.30,
    "Quality of Existing IP": 0.30,
    "TRL / Traction": 0.20,
    "Investor Perception": 0.20,
}


def find_latest_company_folder(platform_suffix, results_dir="results"):
    """Find the most recent results folder for a given company platform suffix.

    Looks for folders ending with e.g. '_chatgpt', '_gemini', '_perplexity'
    but NOT '_chatgpt_vc', '_gemini_vc', '_perplexity_vc'.
    """
    results_path = Path(results_dir)
    if not results_path.exists():
        return None
    matching = sorted(
        [
            d for d in results_path.iterdir()
            if d.is_dir()
            and d.name.endswith(f"_{platform_suffix}")
            and not d.name.endswith(f"_{platform_suffix}_vc")
        ],
        key=lambda d: d.name,
        reverse=True,
    )
    return str(matching[0]) if matching else None


def _load_all_company_data(company_filter=None):
    """Load company evaluation data from BigQuery, with local file fallback.

    Args:
        company_filter: Optional set of company names. When provided, only load
                        data for these companies (much faster).
    """
    raw_responses = {}
    company_names = set()

    # Try loading from monthly summary table first, fall back to raw BQ tables
    try:
        from bq_helper import load_company_data_from_monthly
        raw_responses, company_names = load_company_data_from_monthly(
            company_filter=company_filter,
        )
        if raw_responses:
            print(f"Loaded {len(company_names)} companies from monthly summary table")
        else:
            raise ValueError("No data in monthly summary table")
    except Exception as e:
        print(f"Monthly summary load failed ({e}), trying raw BQ tables")
        try:
            from bq_helper import load_company_data_from_bq
            raw_responses, company_names = load_company_data_from_bq(
                company_filter=company_filter,
            )
            print(f"Loaded {len(company_names)} companies from BigQuery")
        except Exception as e2:
            print(f"BigQuery load failed ({e2}), falling back to local files")

    # Fallback / supplement: also load from local result files
    folders = {
        "chatgpt": find_latest_company_folder("chatgpt"),
        "gemini": find_latest_company_folder("gemini"),
        "perplexity": find_latest_company_folder("perplexity"),
    }
    for platform, folder in folders.items():
        if not folder or not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(folder, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("prompt_id", "")
            company = data.get("company")
            # Skip companies not in the filter
            if company_filter and company and company not in company_filter:
                continue
            if company:
                company_names.add(company)
            ai = _normalize_ai_name(data.get("model", ""))
            # Local files take precedence (overwrite BQ data if both exist)
            raw_responses[(ai, pid, company)] = data

    scored_prompts = {}
    for cat in CATEGORIES:
        for pid in cat["prompts"]:
            for platform in ["chatgpt", "gemini", "perplexity"]:
                for company in company_names:
                    resp = raw_responses.get((platform, pid, company))
                    if resp:
                        # Prefer pre-computed score from monthly table
                        score = resp.get("score")
                        if score is None:
                            answer = resp.get("answer", "")
                            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer)]
                            score = next((n for n in numbers if n <= 10), None)
                        if score is not None:
                            scored_prompts.setdefault(company, {}).setdefault(pid, {})[platform] = score

    company_results = {}
    for company in company_names:
        categories_data = []
        for cat in CATEGORIES:
            cat_key = cat["analysis_key"]
            prompt_details = []
            prompt_weighted_scores = []

            for pid in cat["prompts"]:
                platform_scores = scored_prompts.get(company, {}).get(pid, {})
                w_sum = 0.0
                w_total = 0.0
                for ai, weight in AI_WEIGHTS.items():
                    if ai in platform_scores:
                        w_sum += platform_scores[ai] * weight
                        w_total += weight
                weighted = round(w_sum / w_total, 1) if w_total > 0 else None
                if weighted is not None:
                    prompt_weighted_scores.append(weighted)

                platform_answers = []
                for ai in ["chatgpt", "gemini", "perplexity"]:
                    resp = raw_responses.get((ai, pid, company))
                    if resp:
                        platform_answers.append({
                            "platform": ai,
                            "score": platform_scores.get(ai),
                            "answer": resp.get("answer", ""),
                            "question": resp.get("question", ""),
                            "sources": resp.get("sources", []),
                        })

                prompt_details.append({
                    "prompt_id": pid,
                    "label": cat["prompt_labels"][pid],
                    "weighted_score": weighted,
                    "platform_answers": platform_answers,
                })

            cat_score = (
                round(sum(prompt_weighted_scores) / len(prompt_weighted_scores), 1)
                if prompt_weighted_scores else None
            )

            categories_data.append({
                "key": cat_key,
                "weight": DIMENSION_WEIGHTS[cat_key],
                "score": cat_score,
                "prompts": prompt_details,
            })

        composite_sum = sum(
            c["score"] * c["weight"]
            for c in categories_data
            if c["score"] is not None
        )
        composite = round(composite_sum, 1)

        company_results[company] = {
            "categories": categories_data,
            "composite": composite,
        }

    return company_results


PICKER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Company Evaluation — Select a Company</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: #0a0a0f;
      color: #e0e0e8;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }
    .app { max-width: 800px; margin: 0 auto; padding: 48px 32px 120px; }
    .header {
      text-align: center;
      margin-bottom: 56px;
      padding-bottom: 40px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #14b8a6; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.6rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 8px;
    }
    .header p {
      font-size: 0.85rem; color: #888;
    }
    .group-title {
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: #888; margin-bottom: 12px; margin-top: 32px;
    }
    .company-list { margin-bottom: 16px; }
    .company-item {
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 22px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      margin-bottom: 10px;
      text-decoration: none;
      color: #e0e0e8;
      transition: border-color 0.2s, background 0.2s;
    }
    .company-item:hover {
      border-color: rgba(20,184,166,0.4);
      background: rgba(20,184,166,0.04);
    }
    .company-item-name {
      font-weight: 600; font-size: 0.95rem;
    }
    .arrow { color: #555; font-size: 0.85rem; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <p class="header-label">Company Evaluation Scorecard</p>
      <h1>Select a Company</h1>
      <p>Pick a company to evaluate. You'll then choose competitors to compare against.</p>
    </div>

    {% for group in groups %}
    <div class="group-title">{{ group.label }}</div>
    <div class="company-list">
      {% for name in group.companies %}
      <a class="company-item" href="/select/{{ name }}">
        <span class="company-item-name">{{ name }}</span>
        <span class="arrow">&#8594;</span>
      </a>
      {% endfor %}
    </div>
    {% endfor %}
  </div>
</body>
</html>"""


SELECT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Select Competitors — {{ company_name }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: #0a0a0f;
      color: #e0e0e8;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }
    .app { max-width: 700px; margin: 0 auto; padding: 48px 32px 120px; }
    .back-link {
      display: inline-block; margin-bottom: 24px;
      font-size: 0.78rem; color: #14b8a6;
      text-decoration: none;
    }
    .back-link:hover { color: #5eead4; text-decoration: underline; }
    .header {
      text-align: center;
      margin-bottom: 40px;
      padding-bottom: 32px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #14b8a6; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.2rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 8px;
    }
    .header p {
      font-size: 0.85rem; color: #888;
    }
    .group-badge {
      display: inline-block;
      font-size: 0.7rem; font-weight: 600;
      padding: 4px 12px; border-radius: 12px;
      background: rgba(20,184,166,0.1);
      color: #5eead4; margin-top: 8px;
    }
    .section-title {
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: #888; margin-bottom: 16px;
    }
    .peer-list { margin-bottom: 32px; }
    .peer-item {
      display: flex; align-items: center; gap: 14px;
      padding: 14px 20px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: border-color 0.2s;
    }
    .peer-item:hover { border-color: rgba(20,184,166,0.3); }
    .peer-item input[type="checkbox"] {
      width: 18px; height: 18px;
      accent-color: #14b8a6;
      cursor: pointer;
    }
    .peer-item label {
      font-weight: 500; font-size: 0.9rem;
      cursor: pointer; flex: 1;
    }
    .load-btn {
      display: block; width: 100%;
      padding: 14px 28px;
      background: #14b8a6;
      color: #fff;
      border: none;
      border-radius: 10px;
      font-family: 'Inter', sans-serif;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    .load-btn:hover { background: #0d9488; }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">&larr; Back to company picker</a>

    <div class="header">
      <p class="header-label">Competitor Selection</p>
      <h1>{{ company_name }}</h1>
      <p>Select which competitors to include in the evaluation.</p>
      {% if group_label %}
      <div class="group-badge">{{ group_label }}</div>
      {% endif %}
    </div>

    <form id="selectForm" action="/dashboard" method="get">
      <input type="hidden" name="companies" id="companiesField" value="">

      <div class="section-title">Suggested Competitors (same group)</div>
      <div class="peer-list">
        {% for peer in peers %}
        <div class="peer-item" onclick="this.querySelector('input').click()">
          <input type="checkbox" class="peer-cb" value="{{ peer }}" checked id="peer-{{ loop.index0 }}">
          <label for="peer-{{ loop.index0 }}">{{ peer }}</label>
        </div>
        {% endfor %}
        {% if not peers %}
        <p style="color: #666; font-size: 0.85rem;">No other companies in this group.</p>
        {% endif %}
      </div>

      <button type="submit" class="load-btn">Load Data</button>
    </form>
  </div>
  <script>
    const form = document.getElementById('selectForm');
    const field = document.getElementById('companiesField');
    const mainCompany = '{{ company_name }}';

    form.addEventListener('submit', function(e) {
      const checked = Array.from(document.querySelectorAll('.peer-cb:checked'))
        .map(cb => cb.value);
      // Always include the main company
      const all = [mainCompany, ...checked];
      field.value = all.join(',');
    });
  </script>
</body>
</html>"""


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Company Evaluation (External) — {{ company_name }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; scroll-behavior: smooth; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: #0a0a0f;
      color: #e0e0e8;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }

    .app { max-width: 1100px; margin: 0 auto; padding: 48px 32px 120px; }

    .back-link {
      display: inline-block; margin-bottom: 24px;
      font-size: 0.78rem; color: #14b8a6;
      text-decoration: none;
    }
    .back-link:hover { color: #5eead4; text-decoration: underline; }

    /* Header */
    .header {
      text-align: center;
      margin-bottom: 56px;
      padding-bottom: 40px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #14b8a6; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.6rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 12px;
    }
    .composite-badge {
      display: inline-block;
      font-size: 0.8rem; font-weight: 600;
      padding: 6px 18px; border-radius: 20px;
      background: rgba(20,184,166,0.12);
      color: #5eead4; margin-top: 8px;
    }

    /* Layout */
    .main-grid {
      display: grid;
      grid-template-columns: 480px 1fr;
      gap: 48px;
      align-items: start;
    }
    @media (max-width: 960px) {
      .main-grid { grid-template-columns: 1fr; }
    }

    /* Spider chart */
    .chart-container {
      position: sticky; top: 32px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 32px;
    }
    .chart-container canvas { width: 100% !important; height: auto !important; }

    /* Right panel */
    .detail-panel { min-width: 0; }

    /* Category cards */
    .cat-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      margin-bottom: 16px;
      overflow: hidden;
      transition: border-color 0.2s;
    }
    .cat-card:hover { border-color: rgba(20,184,166,0.3); }
    .cat-card.active { border-color: rgba(20,184,166,0.5); }
    .cat-card-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 22px; cursor: pointer;
      user-select: none;
    }
    .cat-card-header:hover { background: rgba(255,255,255,0.02); }
    .cat-name {
      font-weight: 600; font-size: 0.88rem; color: #e0e0e8;
      flex: 1;
    }
    .cat-meta {
      display: flex; align-items: center; gap: 12px;
      font-size: 0.75rem; color: #888;
    }
    .cat-score-pill {
      font-weight: 700; font-size: 0.82rem;
      padding: 3px 10px; border-radius: 6px;
    }
    .score-strong { background: rgba(34,197,94,0.12); color: #4ade80; }
    .score-moderate { background: rgba(250,204,21,0.12); color: #fde047; }
    .score-weak { background: rgba(239,68,68,0.12); color: #f87171; }
    .chevron {
      transition: transform 0.2s;
      color: #555; font-size: 0.8rem;
    }
    .cat-card.active .chevron { transform: rotate(180deg); }

    /* Expanded prompt area */
    .cat-body { display: none; padding: 0 22px 22px; }
    .cat-card.active .cat-body { display: block; }

    .prompt-card {
      background: rgba(0,0,0,0.2);
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 10px;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .prompt-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 18px; cursor: pointer;
    }
    .prompt-header:hover { background: rgba(255,255,255,0.02); }
    .prompt-label {
      font-size: 0.8rem; font-weight: 500; color: #c0c0cc;
    }
    .prompt-id {
      font-size: 0.68rem; font-weight: 600; color: #14b8a6;
      margin-right: 8px;
    }
    .prompt-score-sm {
      font-size: 0.72rem; font-weight: 600; color: #888;
    }

    /* Answer panels */
    .prompt-body { display: none; padding: 0 18px 18px; }
    .prompt-card.open .prompt-body { display: block; }

    .question-box {
      background: rgba(20,184,166,0.06);
      border-left: 3px solid #14b8a6;
      padding: 12px 16px; margin-bottom: 16px;
      border-radius: 0 8px 8px 0;
      font-size: 0.78rem; color: #5eead4;
      line-height: 1.5;
    }

    .ai-answer {
      margin-bottom: 16px;
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 8px;
      overflow: hidden;
    }
    .ai-answer-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 10px 14px;
      background: rgba(255,255,255,0.03);
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .ai-platform {
      font-size: 0.7rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.08em;
    }
    .ai-platform.chatgpt { color: #10b981; }
    .ai-platform.gemini { color: #3b82f6; }
    .ai-platform.perplexity { color: #a78bfa; }
    .ai-score {
      font-size: 0.75rem; font-weight: 700;
    }
    .ai-answer-text {
      padding: 14px 16px;
      font-size: 0.78rem; color: #b0b0bc;
      line-height: 1.65;
      white-space: pre-wrap;
    }
    .sources-section {
      padding: 10px 16px 14px;
      border-top: 1px solid rgba(255,255,255,0.04);
    }
    .sources-label {
      font-size: 0.65rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.08em;
      color: #666; margin-bottom: 6px;
    }
    .source-link {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 0.72rem; color: #2dd4bf;
      text-decoration: none; margin-right: 14px;
      margin-bottom: 4px;
      transition: color 0.15s;
    }
    .source-link:hover { color: #5eead4; text-decoration: underline; }
    .source-domain {
      font-size: 0.65rem; color: #555;
    }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">&larr; Back to all companies</a>

    <div class="header">
      <p class="header-label">Company Evaluation Scorecard</p>
      <h1>{{ company_name }}</h1>
      <div class="composite-badge">Weighted Composite: {{ composite }} / 10</div>
    </div>

    <div class="main-grid">
      <div class="chart-container">
        <canvas id="spiderChart"></canvas>
      </div>

      <div class="detail-panel">
        {% for cat in categories %}
        <div class="cat-card" data-cat-idx="{{ loop.index0 }}" id="cat-{{ loop.index0 }}">
          <div class="cat-card-header" onclick="toggleCat({{ loop.index0 }})">
            <span class="cat-name">{{ cat.key }}</span>
            <div class="cat-meta">
              <span>{{ (cat.weight * 100) | int }}%</span>
              {% if cat.score is not none %}
              <span class="cat-score-pill {{ 'score-strong' if cat.score >= 7.5 else ('score-moderate' if cat.score >= 5 else 'score-weak') }}">
                {{ cat.score }}
              </span>
              {% endif %}
              <span class="chevron">&#9662;</span>
            </div>
          </div>
          <div class="cat-body">
            {% for prompt in cat.prompts %}
            <div class="prompt-card" id="prompt-{{ prompt.prompt_id }}">
              <div class="prompt-header" onclick="togglePrompt(this)">
                <div>
                  <span class="prompt-id">{{ prompt.prompt_id }}</span>
                  <span class="prompt-label">{{ prompt.label }}</span>
                </div>
                <span class="prompt-score-sm">
                  {% if prompt.weighted_score is not none %}{{ prompt.weighted_score }}{% else %}—{% endif %}
                </span>
              </div>
              <div class="prompt-body">
                {% if prompt.platform_answers %}
                <div class="question-box" style="color: #666; font-style: italic;">Prompt content available in internal version only</div>
                {% endif %}
                {% for pa in prompt.platform_answers %}
                <div class="ai-answer">
                  <div class="ai-answer-header">
                    <span class="ai-platform {{ pa.platform }}">{{ pa.platform }}</span>
                    <span class="ai-score {{ 'score-strong' if pa.score and pa.score >= 7.5 else ('score-moderate' if pa.score and pa.score >= 5 else 'score-weak') }}">
                      {% if pa.score is not none %}{{ pa.score }} / 10{% else %}—{% endif %}
                    </span>
                  </div>
                  <div class="ai-answer-text" style="color: #666; font-style: italic;">Response content available in internal version only</div>
                  {% if pa.sources %}
                  <div class="sources-section">
                    <div class="sources-label">Sources</div>
                    {% for s in pa.sources %}
                    <a class="source-link" href="{{ s.url }}" target="_blank" rel="noopener">
                      {{ s.title or s.publisher or s.url }}
                      {% if s.publisher %}<span class="source-domain">({{ s.publisher }})</span>{% endif %}
                    </a>
                    {% endfor %}
                  </div>
                  {% endif %}
                </div>
                {% endfor %}
              </div>
            </div>
            {% endfor %}
          </div>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script>
    const categories = {{ categories_json | safe }};
    const labels = categories.map(c => c.key);
    const scores = categories.map(c => c.score || 0);

    const ctx = document.getElementById('spiderChart').getContext('2d');
    const chart = new Chart(ctx, {
      type: 'radar',
      data: {
        labels: labels,
        datasets: [{
          label: '{{ company_name }}',
          data: scores,
          backgroundColor: 'rgba(20, 184, 166, 0.12)',
          borderColor: 'rgba(20, 184, 166, 0.7)',
          borderWidth: 2,
          pointBackgroundColor: 'rgba(20, 184, 166, 0.9)',
          pointBorderColor: '#0a0a0f',
          pointBorderWidth: 2,
          pointRadius: 5,
          pointHoverRadius: 8,
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
        },
        scales: {
          r: {
            min: 0,
            max: 10,
            ticks: {
              stepSize: 2,
              color: 'rgba(255,255,255,0.2)',
              backdropColor: 'transparent',
              font: { size: 10 },
            },
            grid: {
              color: 'rgba(255,255,255,0.06)',
            },
            angleLines: {
              color: 'rgba(255,255,255,0.06)',
            },
            pointLabels: {
              color: 'rgba(255,255,255,0.6)',
              font: { size: 11, weight: '500' },
              padding: 16,
            },
          }
        },
        onClick: (event, elements) => {
          if (elements.length > 0) {
            const idx = elements[0].index;
            scrollToCat(idx);
          }
        },
        onHover: (event, elements) => {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
      }
    });

    document.getElementById('spiderChart').addEventListener('click', function(e) {
      const rect = this.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const scale = chart.scales.r;
      const cx = scale.xCenter;
      const cy = scale.yCenter;

      for (let i = 0; i < labels.length; i++) {
        const angle = scale.getIndexAngle(i) - Math.PI / 2;
        const outerRadius = scale.drawingArea + 40;
        const lx = cx + Math.cos(angle) * outerRadius;
        const ly = cy + Math.sin(angle) * outerRadius;
        const dist = Math.sqrt((x - lx) ** 2 + (y - ly) ** 2);
        if (dist < 50) {
          scrollToCat(i);
          return;
        }
      }
    });

    function scrollToCat(idx) {
      document.querySelectorAll('.cat-card').forEach(c => c.classList.remove('active'));
      const target = document.getElementById('cat-' + idx);
      if (target) {
        target.classList.add('active');
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }

    function toggleCat(idx) {
      const card = document.getElementById('cat-' + idx);
      card.classList.toggle('active');
    }

    function togglePrompt(headerEl) {
      headerEl.closest('.prompt-card').classList.toggle('open');
    }
  </script>
</body>
</html>"""


INDEX_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Company Evaluations (External)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: #0a0a0f;
      color: #e0e0e8;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }
    .app { max-width: 800px; margin: 0 auto; padding: 48px 32px 120px; }
    .header {
      text-align: center;
      margin-bottom: 56px;
      padding-bottom: 40px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #14b8a6; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.6rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
    }

    /* Company List */
    .section-title {
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: #888; margin-bottom: 16px;
    }
    .company-list { margin-bottom: 48px; }
    .company-item {
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 22px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      margin-bottom: 10px;
      text-decoration: none;
      color: #e0e0e8;
      transition: border-color 0.2s, background 0.2s;
    }
    .company-item:hover {
      border-color: rgba(20,184,166,0.4);
      background: rgba(20,184,166,0.04);
    }
    .company-item-name {
      font-weight: 600; font-size: 0.95rem;
    }
    .company-item-meta {
      display: flex; align-items: center; gap: 12px;
      font-size: 0.78rem;
    }
    .composite-pill {
      font-weight: 700; font-size: 0.78rem;
      padding: 3px 10px; border-radius: 6px;
      background: rgba(20,184,166,0.12); color: #5eead4;
    }
    .arrow { color: #555; font-size: 0.85rem; }

    /* Compare section */
    .compare-section {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 28px;
    }
    .compare-row {
      display: flex; align-items: flex-end; gap: 16px;
      flex-wrap: wrap;
    }
    .compare-field { flex: 1; min-width: 200px; }
    .compare-field label {
      display: block;
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.1em; text-transform: uppercase;
      color: #888; margin-bottom: 8px;
    }
    .compare-field select {
      width: 100%;
      padding: 10px 14px;
      background: rgba(0,0,0,0.3);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 8px;
      color: #e0e0e8;
      font-family: 'Inter', sans-serif;
      font-size: 0.85rem;
      appearance: none;
      cursor: pointer;
    }
    .compare-field select:focus {
      outline: none;
      border-color: rgba(20,184,166,0.5);
    }
    .compare-btn {
      padding: 10px 28px;
      background: #14b8a6;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-family: 'Inter', sans-serif;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
      white-space: nowrap;
    }
    .compare-btn:hover { background: #0d9488; }
    .compare-btn:disabled {
      opacity: 0.4; cursor: not-allowed;
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <p class="header-label">Company Evaluation Scorecard</p>
      <h1>All Evaluated Companies</h1>
    </div>

    <div class="section-title">Individual Scorecards</div>
    <div class="company-list">
      {% for name, data in company_data.items() | sort %}
      <a class="company-item" href="/company/{{ name }}">
        <span class="company-item-name">{{ name }}</span>
        <div class="company-item-meta">
          <span class="composite-pill">{{ data.composite }} / 10</span>
          <span class="arrow">&#8594;</span>
        </div>
      </a>
      {% endfor %}
    </div>

    <div class="section-title">Compare Two Companies</div>
    <div class="compare-section">
      <form class="compare-row" action="/compare" method="get">
        <div class="compare-field">
          <label>First Company</label>
          <select name="c1" id="c1">
            <option value="">Select a company...</option>
            {% for name in names_sorted %}
            <option value="{{ name }}">{{ name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="compare-field">
          <label>Second Company</label>
          <select name="c2" id="c2">
            <option value="">Select a company...</option>
            {% for name in names_sorted %}
            <option value="{{ name }}">{{ name }}</option>
            {% endfor %}
          </select>
        </div>
        <button type="submit" class="compare-btn" id="compareBtn" disabled>Compare</button>
      </form>
    </div>
  </div>
  <script>
    const c1 = document.getElementById('c1');
    const c2 = document.getElementById('c2');
    const btn = document.getElementById('compareBtn');
    function updateBtn() {
      btn.disabled = !(c1.value && c2.value && c1.value !== c2.value);
    }
    c1.addEventListener('change', updateBtn);
    c2.addEventListener('change', updateBtn);
  </script>
</body>
</html>"""


COMPARE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Compare (External) — {{ c1_name }} vs {{ c2_name }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; scroll-behavior: smooth; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: #0a0a0f;
      color: #e0e0e8;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }

    .app { max-width: 1200px; margin: 0 auto; padding: 48px 32px 120px; }

    .back-link {
      display: inline-block; margin-bottom: 24px;
      font-size: 0.78rem; color: #14b8a6;
      text-decoration: none;
    }
    .back-link:hover { color: #5eead4; text-decoration: underline; }

    /* Header */
    .header {
      text-align: center;
      margin-bottom: 56px;
      padding-bottom: 40px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #14b8a6; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.2rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 16px;
    }
    .compare-composites {
      display: flex; justify-content: center; gap: 24px;
      margin-top: 12px; flex-wrap: wrap;
    }
    .composite-badge {
      display: inline-block;
      font-size: 0.8rem; font-weight: 600;
      padding: 6px 18px; border-radius: 20px;
    }
    .composite-c1 {
      background: rgba(20,184,166,0.12); color: #5eead4;
    }
    .composite-c2 {
      background: rgba(244,114,182,0.12); color: #f9a8d4;
    }

    /* Chart */
    .chart-section {
      display: flex; justify-content: center;
      margin-bottom: 48px;
    }
    .chart-container {
      width: 560px; max-width: 100%;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 32px;
    }
    .chart-container canvas { width: 100% !important; height: auto !important; }

    /* Category cards */
    .cat-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      margin-bottom: 16px;
      overflow: hidden;
      transition: border-color 0.2s;
    }
    .cat-card:hover { border-color: rgba(20,184,166,0.3); }
    .cat-card.active { border-color: rgba(20,184,166,0.5); }
    .cat-card-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 22px; cursor: pointer;
      user-select: none;
    }
    .cat-card-header:hover { background: rgba(255,255,255,0.02); }
    .cat-name {
      font-weight: 600; font-size: 0.88rem; color: #e0e0e8;
      flex: 1;
    }
    .cat-meta {
      display: flex; align-items: center; gap: 10px;
      font-size: 0.75rem; color: #888;
    }
    .cat-weight { font-size: 0.72rem; color: #666; }
    .cat-score-pill {
      font-weight: 700; font-size: 0.78rem;
      padding: 3px 10px; border-radius: 6px;
    }
    .pill-c1 { background: rgba(20,184,166,0.12); color: #5eead4; }
    .pill-c2 { background: rgba(244,114,182,0.12); color: #f9a8d4; }
    .score-strong { background: rgba(34,197,94,0.12); color: #4ade80; }
    .score-moderate { background: rgba(250,204,21,0.12); color: #fde047; }
    .score-weak { background: rgba(239,68,68,0.12); color: #f87171; }
    .diff-indicator {
      font-size: 0.68rem; font-weight: 600;
      padding: 2px 6px; border-radius: 4px;
    }
    .diff-positive { background: rgba(34,197,94,0.1); color: #4ade80; }
    .diff-negative { background: rgba(239,68,68,0.1); color: #f87171; }
    .diff-neutral { background: rgba(255,255,255,0.05); color: #888; }
    .chevron {
      transition: transform 0.2s;
      color: #555; font-size: 0.8rem;
    }
    .cat-card.active .chevron { transform: rotate(180deg); }

    /* Expanded body */
    .cat-body { display: none; padding: 0 22px 22px; }
    .cat-card.active .cat-body { display: block; }

    .prompt-card {
      background: rgba(0,0,0,0.2);
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 10px;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .prompt-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 18px; cursor: pointer;
    }
    .prompt-header:hover { background: rgba(255,255,255,0.02); }
    .prompt-label {
      font-size: 0.8rem; font-weight: 500; color: #c0c0cc;
    }
    .prompt-id {
      font-size: 0.68rem; font-weight: 600; color: #14b8a6;
      margin-right: 8px;
    }
    .prompt-scores {
      display: flex; gap: 8px; align-items: center;
      font-size: 0.72rem; font-weight: 600;
    }
    .prompt-score-c1 { color: #5eead4; }
    .prompt-score-c2 { color: #f9a8d4; }
    .prompt-score-sep { color: #555; }

    /* Answer panels */
    .prompt-body { display: none; padding: 0 18px 18px; }
    .prompt-card.open .prompt-body { display: block; }

    .question-box {
      background: rgba(20,184,166,0.06);
      border-left: 3px solid #14b8a6;
      padding: 12px 16px; margin-bottom: 16px;
      border-radius: 0 8px 8px 0;
      font-size: 0.78rem; color: #5eead4;
      line-height: 1.5;
    }

    .company-answers-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 768px) {
      .company-answers-grid { grid-template-columns: 1fr; }
    }
    .col-label {
      font-size: 0.68rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.1em;
      padding: 6px 0; margin-bottom: 8px;
    }
    .col-label.c1 { color: #5eead4; }
    .col-label.c2 { color: #f9a8d4; }

    .ai-answer {
      margin-bottom: 12px;
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 8px;
      overflow: hidden;
    }
    .ai-answer-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 12px;
      background: rgba(255,255,255,0.03);
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .ai-platform {
      font-size: 0.68rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.08em;
    }
    .ai-platform.chatgpt { color: #10b981; }
    .ai-platform.gemini { color: #3b82f6; }
    .ai-platform.perplexity { color: #a78bfa; }
    .ai-score {
      font-size: 0.72rem; font-weight: 700;
    }
    .ai-answer-text {
      padding: 12px 14px;
      font-size: 0.75rem; color: #b0b0bc;
      line-height: 1.6;
      white-space: pre-wrap;
      max-height: 200px;
      overflow-y: auto;
    }
    .sources-section {
      padding: 8px 14px 10px;
      border-top: 1px solid rgba(255,255,255,0.04);
    }
    .sources-label {
      font-size: 0.62rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.08em;
      color: #666; margin-bottom: 4px;
    }
    .source-link {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 0.68rem; color: #2dd4bf;
      text-decoration: none; margin-right: 10px;
      margin-bottom: 3px;
    }
    .source-link:hover { color: #5eead4; text-decoration: underline; }
    .source-domain { font-size: 0.62rem; color: #555; }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">&larr; Back to all companies</a>

    <div class="header">
      <p class="header-label">Company Comparison</p>
      <h1>{{ c1_name }} vs {{ c2_name }}</h1>
      <div class="compare-composites">
        <span class="composite-badge composite-c1">{{ c1_name }}: {{ c1_composite }} / 10</span>
        <span class="composite-badge composite-c2">{{ c2_name }}: {{ c2_composite }} / 10</span>
      </div>
    </div>

    <!-- Overlaid Spider Chart -->
    <div class="chart-section">
      <div class="chart-container">
        <canvas id="spiderChart"></canvas>
      </div>
    </div>

    <!-- Side-by-side Category Cards -->
    <div class="detail-panel">
      {% for cat in merged_categories %}
      <div class="cat-card" data-cat-idx="{{ loop.index0 }}" id="cat-{{ loop.index0 }}">
        <div class="cat-card-header" onclick="toggleCat({{ loop.index0 }})">
          <span class="cat-name">{{ cat.key }}</span>
          <div class="cat-meta">
            <span class="cat-weight">{{ (cat.weight * 100) | int }}%</span>
            {% if cat.score1 is not none %}
            <span class="cat-score-pill pill-c1">{{ cat.score1 }}</span>
            {% endif %}
            {% if cat.score2 is not none %}
            <span class="cat-score-pill pill-c2">{{ cat.score2 }}</span>
            {% endif %}
            {% if cat.score1 is not none and cat.score2 is not none %}
              {% set diff = (cat.score1 - cat.score2) | round(1) %}
              {% if diff > 0 %}
              <span class="diff-indicator diff-positive">+{{ diff }}</span>
              {% elif diff < 0 %}
              <span class="diff-indicator diff-negative">{{ diff }}</span>
              {% else %}
              <span class="diff-indicator diff-neutral">=</span>
              {% endif %}
            {% endif %}
            <span class="chevron">&#9662;</span>
          </div>
        </div>
        <div class="cat-body">
          {% for prompt in cat.prompts %}
          <div class="prompt-card" id="prompt-{{ prompt.prompt_id }}">
            <div class="prompt-header" onclick="togglePrompt(this)">
              <div>
                <span class="prompt-id">{{ prompt.prompt_id }}</span>
                <span class="prompt-label">{{ prompt.label }}</span>
              </div>
              <div class="prompt-scores">
                <span class="prompt-score-c1">
                  {% if prompt.weighted_score1 is not none %}{{ prompt.weighted_score1 }}{% else %}&mdash;{% endif %}
                </span>
                <span class="prompt-score-sep">|</span>
                <span class="prompt-score-c2">
                  {% if prompt.weighted_score2 is not none %}{{ prompt.weighted_score2 }}{% else %}&mdash;{% endif %}
                </span>
              </div>
            </div>
            <div class="prompt-body">
              {% if prompt.platform_answers1 or prompt.platform_answers2 %}
              <div class="question-box" style="color: #666; font-style: italic;">Prompt content available in internal version only</div>
              {% endif %}
              <div class="company-answers-grid">
                <div>
                  <div class="col-label c1">{{ c1_name }}</div>
                  {% for pa in prompt.platform_answers1 %}
                  <div class="ai-answer">
                    <div class="ai-answer-header">
                      <span class="ai-platform {{ pa.platform }}">{{ pa.platform }}</span>
                      <span class="ai-score {{ 'score-strong' if pa.score and pa.score >= 7.5 else ('score-moderate' if pa.score and pa.score >= 5 else 'score-weak') }}">
                        {% if pa.score is not none %}{{ pa.score }} / 10{% else %}&mdash;{% endif %}
                      </span>
                    </div>
                    <div class="ai-answer-text" style="color: #666; font-style: italic;">Response content available in internal version only</div>
                    {% if pa.sources %}
                    <div class="sources-section">
                      <div class="sources-label">Sources</div>
                      {% for s in pa.sources %}
                      <a class="source-link" href="{{ s.url }}" target="_blank" rel="noopener">
                        {{ s.title or s.publisher or s.url }}
                        {% if s.publisher %}<span class="source-domain">({{ s.publisher }})</span>{% endif %}
                      </a>
                      {% endfor %}
                    </div>
                    {% endif %}
                  </div>
                  {% endfor %}
                </div>
                <div>
                  <div class="col-label c2">{{ c2_name }}</div>
                  {% for pa in prompt.platform_answers2 %}
                  <div class="ai-answer">
                    <div class="ai-answer-header">
                      <span class="ai-platform {{ pa.platform }}">{{ pa.platform }}</span>
                      <span class="ai-score {{ 'score-strong' if pa.score and pa.score >= 7.5 else ('score-moderate' if pa.score and pa.score >= 5 else 'score-weak') }}">
                        {% if pa.score is not none %}{{ pa.score }} / 10{% else %}&mdash;{% endif %}
                      </span>
                    </div>
                    <div class="ai-answer-text" style="color: #666; font-style: italic;">Response content available in internal version only</div>
                    {% if pa.sources %}
                    <div class="sources-section">
                      <div class="sources-label">Sources</div>
                      {% for s in pa.sources %}
                      <a class="source-link" href="{{ s.url }}" target="_blank" rel="noopener">
                        {{ s.title or s.publisher or s.url }}
                        {% if s.publisher %}<span class="source-domain">({{ s.publisher }})</span>{% endif %}
                      </a>
                      {% endfor %}
                    </div>
                    {% endif %}
                  </div>
                  {% endfor %}
                </div>
              </div>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script>
    const categories1 = {{ categories1_json | safe }};
    const categories2 = {{ categories2_json | safe }};
    const labels = categories1.map(c => c.key);
    const scores1 = categories1.map(c => c.score || 0);
    const scores2 = categories2.map(c => c.score || 0);

    const ctx = document.getElementById('spiderChart').getContext('2d');
    const chart = new Chart(ctx, {
      type: 'radar',
      data: {
        labels: labels,
        datasets: [
          {
            label: '{{ c1_name }}',
            data: scores1,
            backgroundColor: 'rgba(20, 184, 166, 0.1)',
            borderColor: 'rgba(20, 184, 166, 0.7)',
            borderWidth: 2,
            pointBackgroundColor: 'rgba(20, 184, 166, 0.9)',
            pointBorderColor: '#0a0a0f',
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 8,
          },
          {
            label: '{{ c2_name }}',
            data: scores2,
            backgroundColor: 'rgba(244, 114, 182, 0.1)',
            borderColor: 'rgba(244, 114, 182, 0.7)',
            borderWidth: 2,
            pointBackgroundColor: 'rgba(244, 114, 182, 0.9)',
            pointBorderColor: '#0a0a0f',
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 8,
          }
        ]
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: {
              color: 'rgba(255,255,255,0.6)',
              font: { size: 12, weight: '500' },
              padding: 20,
              usePointStyle: true,
              pointStyle: 'circle',
            }
          },
        },
        scales: {
          r: {
            min: 0,
            max: 10,
            ticks: {
              stepSize: 2,
              color: 'rgba(255,255,255,0.2)',
              backdropColor: 'transparent',
              font: { size: 10 },
            },
            grid: {
              color: 'rgba(255,255,255,0.06)',
            },
            angleLines: {
              color: 'rgba(255,255,255,0.06)',
            },
            pointLabels: {
              color: 'rgba(255,255,255,0.6)',
              font: { size: 11, weight: '500' },
              padding: 16,
            },
          }
        },
        onClick: (event, elements) => {
          if (elements.length > 0) {
            const idx = elements[0].index;
            scrollToCat(idx);
          }
        },
        onHover: (event, elements) => {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
      }
    });

    function scrollToCat(idx) {
      document.querySelectorAll('.cat-card').forEach(c => c.classList.remove('active'));
      const target = document.getElementById('cat-' + idx);
      if (target) {
        target.classList.add('active');
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }

    function toggleCat(idx) {
      document.getElementById('cat-' + idx).classList.toggle('active');
    }

    function togglePrompt(headerEl) {
      headerEl.closest('.prompt-card').classList.toggle('open');
    }
  </script>
</body>
</html>"""


@app.route("/")
def index():
    """Landing page — instant company picker (no BQ call)."""
    _, all_companies_grouped = _load_company_groups()
    if not all_companies_grouped:
        return "<h1>No company list files found.</h1>"

    return render_template_string(
        PICKER_TEMPLATE,
        groups=all_companies_grouped,
    )


@app.route("/select/<company_name>")
def select_competitors(company_name):
    """Show competitor suggestion page for a selected company."""
    groups_by_company, _ = _load_company_groups()
    info = groups_by_company.get(company_name, {})
    peers = info.get("peers", [])
    group_label = info.get("group_label", "")

    return render_template_string(
        SELECT_TEMPLATE,
        company_name=company_name,
        peers=peers,
        group_label=group_label,
    )


@app.route("/dashboard")
def dashboard():
    """Results page — loads only the selected companies from BQ."""
    companies_param = request.args.get("companies", "")
    if not companies_param:
        return redirect(url_for("index"))

    company_filter = set(c.strip() for c in companies_param.split(",") if c.strip())
    company_data = _load_all_company_data(company_filter=company_filter)
    if not company_data:
        return "<h1>No company evaluation data found for the selected companies.</h1>"

    names_sorted = sorted(company_data.keys())

    return render_template_string(
        INDEX_TEMPLATE,
        company_data=company_data,
        names_sorted=names_sorted,
    )


@app.route("/company/<company_name>")
def company_detail(company_name):
    company_data = _load_all_company_data(company_filter={company_name})
    if company_name not in company_data:
        return f"<h1>Company '{company_name}' not found.</h1>", 404

    data = company_data[company_name]
    categories_json = json.dumps(data["categories"])

    return render_template_string(
        HTML_TEMPLATE,
        company_name=company_name,
        composite=data["composite"],
        categories=data["categories"],
        categories_json=categories_json,
    )


@app.route("/compare")
def compare():
    c1_name = request.args.get("c1", "")
    c2_name = request.args.get("c2", "")

    company_data = _load_all_company_data(company_filter={c1_name, c2_name})

    if c1_name not in company_data or c2_name not in company_data:
        return "<h1>One or both companies not found. Please go back and try again.</h1>", 404

    data1 = company_data[c1_name]
    data2 = company_data[c2_name]

    merged_categories = []
    for c1, c2 in zip(data1["categories"], data2["categories"]):
        merged_prompts = []
        for p1, p2 in zip(c1["prompts"], c2["prompts"]):
            merged_prompts.append({
                "prompt_id": p1["prompt_id"],
                "label": p1["label"],
                "weighted_score1": p1["weighted_score"],
                "weighted_score2": p2["weighted_score"],
                "platform_answers1": p1["platform_answers"],
                "platform_answers2": p2["platform_answers"],
            })
        merged_categories.append({
            "key": c1["key"],
            "weight": c1["weight"],
            "score1": c1["score"],
            "score2": c2["score"],
            "prompts": merged_prompts,
        })

    return render_template_string(
        COMPARE_TEMPLATE,
        c1_name=c1_name,
        c2_name=c2_name,
        c1_composite=data1["composite"],
        c2_composite=data2["composite"],
        merged_categories=merged_categories,
        categories1_json=json.dumps(data1["categories"]),
        categories2_json=json.dumps(data2["categories"]),
    )


@app.route("/api/data")
def api_data():
    companies_param = request.args.get("companies", "")
    company_filter = None
    if companies_param:
        company_filter = set(c.strip() for c in companies_param.split(",") if c.strip())
    return jsonify(_load_all_company_data(company_filter=company_filter))


@app.route("/source-analysis")
def source_analysis():
    """Show source/citation analysis with per-prompt and per-company filtering (keywords only)."""
    selected_prompt = request.args.get("prompt", "all")
    selected_company = request.args.get("company", "all")
    company_filter = {selected_company} if selected_company != "all" else None
    company_data = _load_all_company_data(company_filter=company_filter)

    # Collect all available companies
    all_companies = sorted(company_data.keys())

    # Collect all available prompts
    all_prompts = set()
    for company, data in company_data.items():
        for cat in data["categories"]:
            for prompt in cat["prompts"]:
                all_prompts.add(prompt["prompt_id"])
    all_prompts = sorted(all_prompts, key=lambda x: (x[0], int(x[1:]) if x[1:].isdigit() else 0))

    source_counts = {}
    source_details = {}
    prompt_run_count = 0

    for company, data in company_data.items():
        # Filter by selected company
        if selected_company != "all" and company != selected_company:
            continue
        for cat in data["categories"]:
            for prompt in cat["prompts"]:
                if selected_prompt != "all" and prompt["prompt_id"] != selected_prompt:
                    continue
                for pa in prompt["platform_answers"]:
                    prompt_run_count += 1
                    for source in pa.get("sources", []):
                        url = source.get("url", "")
                        if not url:
                            continue
                        domain = _extract_domain(url)
                        if not domain:
                            continue
                        source_counts[domain] = source_counts.get(domain, 0) + 1
                        if domain not in source_details:
                            source_details[domain] = {"urls": set()}
                        source_details[domain]["urls"].add(url)

    total_citations = sum(source_counts.values())
    avg_per_run = round(total_citations / prompt_run_count, 1) if prompt_run_count > 0 else 0

    frequency_table = []
    for domain, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        category = _categorize_source(domain)
        avg_count = round(count / prompt_run_count, 2) if prompt_run_count > 0 else 0
        frequency_table.append({
            "domain": domain,
            "frequency": count,
            "avg_frequency": avg_count,
            "type": category,
        })

    by_type = {}
    for item in frequency_table:
        t = item["type"]
        if t not in by_type:
            by_type[t] = {"count": 0}
        by_type[t]["count"] += item["frequency"]
    by_type = dict(sorted(by_type.items(), key=lambda x: -x[1]["count"]))

    # Use keywords instead of full prompt text
    selected_prompt_keywords = PROMPT_KEYWORDS.get(selected_prompt, "") if selected_prompt != "all" else ""

    return render_template_string(
        SOURCE_ANALYSIS_TEMPLATE,
        frequency_table=frequency_table,
        by_type=by_type,
        total_citations=total_citations,
        unique_sources=len(source_counts),
        all_prompts=all_prompts,
        selected_prompt=selected_prompt,
        selected_prompt_keywords=selected_prompt_keywords,
        prompt_run_count=prompt_run_count,
        avg_per_run=avg_per_run,
        prompt_keywords=PROMPT_KEYWORDS,
        all_companies=all_companies,
        selected_company=selected_company,
    )


SOURCE_ANALYSIS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Source Analysis</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Inter', sans-serif; background: #0a0a0f; color: #e0e0e8; min-height: 100vh; line-height: 1.5; }
    .app { max-width: 1200px; margin: 0 auto; padding: 40px 32px 100px; }
    a { color: #14b8a6; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .header { margin-bottom: 40px; padding-bottom: 24px; border-bottom: 1px solid rgba(255,255,255,0.06); }
    .back-link { font-size: 0.75rem; color: #888; margin-bottom: 12px; display: inline-block; }
    .header h1 { font-size: 1.8rem; font-weight: 600; margin-bottom: 8px; }
    .header-subtitle { font-size: 0.9rem; color: #888; }
    .filter-section { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 20px 24px; margin-bottom: 32px; }
    .filter-label { font-size: 0.75rem; font-weight: 600; color: #888; text-transform: uppercase; margin-bottom: 12px; display: block; }
    .prompt-pills { display: flex; flex-wrap: wrap; gap: 6px; }
    .prompt-pill { padding: 6px 12px; border-radius: 6px; font-size: 0.72rem; font-weight: 600; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); color: #888; text-decoration: none; transition: all 0.15s; }
    .prompt-pill:hover { background: rgba(20,184,166,0.1); border-color: rgba(20,184,166,0.3); color: #14b8a6; text-decoration: none; }
    .prompt-pill.active { background: rgba(20,184,166,0.15); border-color: #14b8a6; color: #14b8a6; }
    .keyword-box { background: rgba(20,184,166,0.06); border: 1px solid rgba(20,184,166,0.15); border-radius: 10px; padding: 14px 18px; margin-bottom: 24px; font-size: 0.85rem; color: #14b8a6; font-weight: 500; }
    .summary-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }
    .summary-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 16px 24px; text-align: center; flex: 1; min-width: 120px; }
    .summary-value { font-size: 1.6rem; font-weight: 700; color: #14b8a6; }
    .summary-label { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #888; }
    .section-title { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #888; margin-bottom: 16px; }
    .source-bar-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
    .source-domain { width: 180px; font-size: 0.82rem; font-weight: 500; }
    .source-bar-container { flex: 1; height: 18px; background: rgba(255,255,255,0.04); border-radius: 4px; overflow: hidden; }
    .source-bar { height: 100%; background: linear-gradient(90deg, #14b8a6, #0d9488); border-radius: 4px; }
    .source-count { width: 50px; text-align: right; font-weight: 600; font-size: 0.82rem; color: #14b8a6; }
    .source-avg { width: 60px; text-align: right; font-size: 0.72rem; color: #888; }
    .no-data { text-align: center; padding: 60px 20px; color: #666; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <a href="/" class="back-link">&larr; Back to Companies</a>
      <h1>Source Analysis</h1>
      <p class="header-subtitle">Citation frequency {% if selected_company != 'all' %}for {{ selected_company }}{% endif %}{% if selected_prompt != 'all' %} ({{ selected_prompt }}){% endif %}{% if selected_company == 'all' and selected_prompt == 'all' %}across all companies and prompts{% endif %}</p>
    </div>
    <div class="filter-section">
      <span class="filter-label">Filter by Company:</span>
      <div class="prompt-pills">
        <a href="/source-analysis{% if selected_prompt != 'all' %}?prompt={{ selected_prompt }}{% endif %}" class="prompt-pill {{ 'active' if selected_company == 'all' else '' }}">All</a>
        {% for company in all_companies %}
        <a href="/source-analysis?company={{ company }}{% if selected_prompt != 'all' %}&prompt={{ selected_prompt }}{% endif %}" class="prompt-pill {{ 'active' if selected_company == company else '' }}">{{ company }}</a>
        {% endfor %}
      </div>
    </div>
    <div class="filter-section">
      <span class="filter-label">Filter by Prompt:</span>
      <div class="prompt-pills">
        <a href="/source-analysis{% if selected_company != 'all' %}?company={{ selected_company }}{% endif %}" class="prompt-pill {{ 'active' if selected_prompt == 'all' else '' }}">All</a>
        {% for pid in all_prompts %}
        <a href="/source-analysis?prompt={{ pid }}{% if selected_company != 'all' %}&company={{ selected_company }}{% endif %}" class="prompt-pill {{ 'active' if selected_prompt == pid else '' }}" title="{{ prompt_keywords.get(pid, '') }}">{{ pid }}</a>
        {% endfor %}
      </div>
    </div>
    {% if selected_prompt != 'all' and selected_prompt_keywords %}
    <div class="keyword-box">{{ selected_prompt }}: {{ selected_prompt_keywords }}</div>
    {% endif %}
    {% if frequency_table %}
    <div class="summary-row">
      <div class="summary-card"><div class="summary-value">{{ total_citations }}</div><div class="summary-label">Total Citations</div></div>
      <div class="summary-card"><div class="summary-value">{{ avg_per_run }}</div><div class="summary-label">Avg per Run</div></div>
      <div class="summary-card"><div class="summary-value">{{ unique_sources }}</div><div class="summary-label">Unique Sources</div></div>
      <div class="summary-card"><div class="summary-value">{{ prompt_run_count }}</div><div class="summary-label">Prompt Runs</div></div>
    </div>
    <h3 class="section-title">Top Sources ({{ frequency_table | length }} domains)</h3>
    {% for s in frequency_table[:30] %}
    <div class="source-bar-row">
      <div class="source-domain">{{ s.domain }}</div>
      <div class="source-bar-container"><div class="source-bar" style="width: {{ (s.frequency / frequency_table[0].frequency * 100) | int }}%"></div></div>
      <div class="source-count">{{ s.frequency }}</div>
      <div class="source-avg">{{ s.avg_frequency }}/run</div>
    </div>
    {% endfor %}
    {% else %}
    <div class="no-data"><p>No sources found for this prompt.</p><p><a href="/source-analysis">View all sources</a></p></div>
    {% endif %}
  </div>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Company Evaluation Web App")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"Starting Company Evaluation Web App on http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)
