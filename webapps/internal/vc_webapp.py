#!/usr/bin/env python3
"""
VC Evaluation Web App

A local Flask web app that displays VC evaluation results:
- Interactive spider chart
- Click on dimensions to drill into individual prompts
- View AI answers and sources per prompt

Usage:
    python vc_webapp.py
    python vc_webapp.py --port 5001
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from collections import Counter
from urllib.parse import urlparse

from flask import Flask, render_template_string, jsonify, request

from vc_analysis import (
    VC_CATEGORIES,
    VC_DIMENSION_WEIGHTS,
    VC_KNOCKOUT_DIMENSIONS,
    VC_KNOCKOUT_THRESHOLD,
    AI_WEIGHTS,
    _normalize_ai_name,
    find_latest_vc_folder,
)

app = Flask(__name__)


# Source type classification patterns (reused from ecosystem_analysis.py)
SOURCE_TYPE_PATTERNS = {
    "Quantum Media": ["quantum", "spinquanta", "thequantuminsider", "qureca"],
    "Tech Media": ["techcrunch", "wired", "arstechnica", "theverge", "venturebeat", "zdnet", "cnet", "engadget"],
    "Financial Media": ["bloomberg", "reuters", "cnbc", "fortune", "forbes", "wsj", "ft.com", "marketwatch"],
    "VC / Investment Firm": ["ventures", "capital", "vc", "crunchbase", "pitchbook", "dealroom"],
    "Academic / Research": ["arxiv", "nature", "science", "edu", "ieee", "acm.org", "researchgate", "scholar"],
    "Startup Media": ["eu-startups", "sifted", "techfundingnews", "techeu", "tech.eu"],
    "Press Release": ["prnewswire", "businesswire", "globenewswire", "prbuzz"],
    "Corporate / Vendor": [],  # Fallback for company websites
    "Social / UGC": ["linkedin", "twitter", "x.com", "medium", "reddit", "substack"],
    "General Knowledge": ["wikipedia", "britannica"],
    "Government / Policy": ["gov", "europa.eu", "nsf.gov"],
}


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url


def _categorize_source(domain: str) -> str:
    """Categorize a source domain by type."""
    domain_lower = domain.lower()
    for source_type, patterns in SOURCE_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in domain_lower:
                return source_type
    return "Corporate / Vendor"


def _load_all_vc_data():
    """Load all VC evaluation data from the latest run folders."""
    folders = {
        "chatgpt": find_latest_vc_folder("chatgpt_vc"),
        "gemini": find_latest_vc_folder("gemini_vc"),
        "perplexity": find_latest_vc_folder("perplexity_vc"),
    }

    # Collect all raw JSON responses keyed by (platform, prompt_id, vc_name)
    raw_responses = {}
    vc_names = set()

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
            vc = data.get("vc")
            if vc:
                vc_names.add(vc)
            ai = _normalize_ai_name(data.get("model", ""))
            raw_responses[(ai, pid, vc)] = data

    # Build scored data for spider chart
    scored_prompts = {}
    for cat in VC_CATEGORIES:
        for pid in cat["prompts"]:
            for platform in ["chatgpt", "gemini", "perplexity"]:
                for vc in vc_names:
                    resp = raw_responses.get((platform, pid, vc))
                    if resp:
                        answer = resp.get("answer", "")
                        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer)]
                        score = next((n for n in numbers if n <= 10), None)
                        if score is not None:
                            scored_prompts.setdefault(vc, {}).setdefault(pid, {})[platform] = score

    # Compute weighted scores per prompt and per category
    vc_results = {}
    for vc in vc_names:
        categories_data = []
        for cat in VC_CATEGORIES:
            cat_key = cat["analysis_key"]
            prompt_details = []
            prompt_weighted_scores = []

            for pid in cat["prompts"]:
                platform_scores = scored_prompts.get(vc, {}).get(pid, {})
                # Weighted score across platforms
                w_sum = 0.0
                w_total = 0.0
                for ai, weight in AI_WEIGHTS.items():
                    if ai in platform_scores:
                        w_sum += platform_scores[ai] * weight
                        w_total += weight
                weighted = round(w_sum / w_total, 1) if w_total > 0 else None
                if weighted is not None:
                    prompt_weighted_scores.append(weighted)

                # Collect per-platform answers
                platform_answers = []
                for ai in ["chatgpt", "gemini", "perplexity"]:
                    resp = raw_responses.get((ai, pid, vc))
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
                "weight": VC_DIMENSION_WEIGHTS[cat_key],
                "score": cat_score,
                "prompts": prompt_details,
                "is_knockout": cat_key in VC_KNOCKOUT_DIMENSIONS,
            })

        # Composite
        composite_sum = sum(
            c["score"] * c["weight"]
            for c in categories_data
            if c["score"] is not None
        )
        composite = round(composite_sum, 1)

        knockout_flags = [
            c["key"] for c in categories_data
            if c["is_knockout"] and c["score"] is not None and c["score"] < VC_KNOCKOUT_THRESHOLD
        ]

        vc_results[vc] = {
            "categories": categories_data,
            "composite": composite,
            "knockout_flags": knockout_flags,
        }

    return vc_results


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VC Evaluation — {{ vc_name }}</title>
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
      color: #6366f1; margin-bottom: 16px;
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
      background: rgba(99,102,241,0.12);
      color: #a5b4fc; margin-top: 8px;
    }
    .knockout-banner {
      margin-top: 20px; padding: 14px 20px;
      background: rgba(239,68,68,0.1);
      border: 1px solid rgba(239,68,68,0.25);
      border-radius: 8px; color: #fca5a5;
      font-size: 0.8rem; font-weight: 500;
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
    .cat-card:hover { border-color: rgba(99,102,241,0.3); }
    .cat-card.active { border-color: rgba(99,102,241,0.5); }
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
      font-size: 0.68rem; font-weight: 600; color: #6366f1;
      margin-right: 8px;
    }
    .prompt-score-sm {
      font-size: 0.72rem; font-weight: 600; color: #888;
    }

    /* Answer panels */
    .prompt-body { display: none; padding: 0 18px 18px; }
    .prompt-card.open .prompt-body { display: block; }

    .question-box {
      background: rgba(99,102,241,0.06);
      border-left: 3px solid #6366f1;
      padding: 12px 16px; margin-bottom: 16px;
      border-radius: 0 8px 8px 0;
      font-size: 0.78rem; color: #a5b4fc;
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
      font-size: 0.72rem; color: #818cf8;
      text-decoration: none; margin-right: 14px;
      margin-bottom: 4px;
      transition: color 0.15s;
    }
    .source-link:hover { color: #a5b4fc; text-decoration: underline; }
    .source-domain {
      font-size: 0.65rem; color: #555;
    }
    .nav-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .nav-link { font-size: 0.78rem; color: #6366f1; text-decoration: none; }
    .nav-link:hover { color: #a5b4fc; text-decoration: underline; }
  </style>
</head>
<body>
  <div class="app">
    <div class="nav-row">
      <a class="nav-link" href="/">&larr; Back to all VCs</a>
      <a class="nav-link" href="/source-analysis">Source Analysis &rarr;</a>
    </div>
    <div class="header">
      <p class="header-label">VC Evaluation Scorecard</p>
      <h1>{{ vc_name }}</h1>
      <div class="composite-badge">Weighted Composite: {{ composite }} / 10</div>
      {% if knockout_flags %}
      <div class="knockout-banner">
        Knockout: scores below {{ knockout_threshold }} in
        {{ knockout_flags | join(', ') }}. This VC would be disqualified under the scorecard framework.
      </div>
      {% endif %}
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
                <div class="question-box">{{ prompt.platform_answers[0].question }}</div>
                {% endif %}
                {% for pa in prompt.platform_answers %}
                <div class="ai-answer">
                  <div class="ai-answer-header">
                    <span class="ai-platform {{ pa.platform }}">{{ pa.platform }}</span>
                    <span class="ai-score {{ 'score-strong' if pa.score and pa.score >= 7.5 else ('score-moderate' if pa.score and pa.score >= 5 else 'score-weak') }}">
                      {% if pa.score is not none %}{{ pa.score }} / 10{% else %}—{% endif %}
                    </span>
                  </div>
                  <div class="ai-answer-text">{{ pa.answer }}</div>
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
    // Data from server
    const categories = {{ categories_json | safe }};
    const labels = categories.map(c => c.key);
    const scores = categories.map(c => c.score || 0);

    // Spider chart
    const ctx = document.getElementById('spiderChart').getContext('2d');
    const chart = new Chart(ctx, {
      type: 'radar',
      data: {
        labels: labels,
        datasets: [{
          label: '{{ vc_name }}',
          data: scores,
          backgroundColor: 'rgba(99, 102, 241, 0.12)',
          borderColor: 'rgba(99, 102, 241, 0.7)',
          borderWidth: 2,
          pointBackgroundColor: 'rgba(99, 102, 241, 0.9)',
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

    // Click on chart labels (axis labels)
    document.getElementById('spiderChart').addEventListener('click', function(e) {
      const rect = this.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // Check each label position
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
      // Close all, open target
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
  <title>VC Evaluations</title>
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
      color: #6366f1; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.6rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
    }

    /* VC List */
    .section-title {
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: #888; margin-bottom: 16px;
    }
    .vc-list { margin-bottom: 48px; }
    .vc-item {
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
    .vc-item:hover {
      border-color: rgba(99,102,241,0.4);
      background: rgba(99,102,241,0.04);
    }
    .vc-item-name {
      font-weight: 600; font-size: 0.95rem;
    }
    .vc-item-meta {
      display: flex; align-items: center; gap: 12px;
      font-size: 0.78rem;
    }
    .composite-pill {
      font-weight: 700; font-size: 0.78rem;
      padding: 3px 10px; border-radius: 6px;
      background: rgba(99,102,241,0.12); color: #a5b4fc;
    }
    .knockout-pill {
      font-weight: 600; font-size: 0.72rem;
      padding: 3px 10px; border-radius: 6px;
      background: rgba(239,68,68,0.12); color: #f87171;
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
      border-color: rgba(99,102,241,0.5);
    }
    .compare-btn {
      padding: 10px 28px;
      background: #6366f1;
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
    .compare-btn:hover { background: #4f46e5; }
    .compare-btn:disabled {
      opacity: 0.4; cursor: not-allowed;
    }

    /* Analysis link */
    .analysis-link {
      display: inline-flex; align-items: center; gap: 8px;
      margin-top: 16px;
      padding: 10px 20px;
      background: rgba(99,102,241,0.08);
      border: 1px solid rgba(99,102,241,0.2);
      border-radius: 8px;
      font-size: 0.8rem; font-weight: 500;
      color: #a5b4fc;
      text-decoration: none;
      transition: background 0.2s, border-color 0.2s;
    }
    .analysis-link:hover {
      background: rgba(99,102,241,0.15);
      border-color: rgba(99,102,241,0.4);
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <p class="header-label">VC Evaluation Scorecard</p>
      <h1>All Evaluated VCs</h1>
      <a class="analysis-link" href="/source-analysis">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20V10M18 20V4M6 20v-4"/>
        </svg>
        Source Analysis
      </a>
    </div>

    <div class="section-title">Individual Scorecards</div>
    <div class="vc-list">
      {% for vc_name, data in vc_data.items() | sort %}
      <a class="vc-item" href="/vc/{{ vc_name }}">
        <span class="vc-item-name">{{ vc_name }}</span>
        <div class="vc-item-meta">
          {% if data.knockout_flags %}
          <span class="knockout-pill">Knockout</span>
          {% endif %}
          <span class="composite-pill">{{ data.composite }} / 10</span>
          <span class="arrow">&#8594;</span>
        </div>
      </a>
      {% endfor %}
    </div>

    <div class="section-title">Compare Two VCs</div>
    <div class="compare-section">
      <form class="compare-row" action="/compare" method="get">
        <div class="compare-field">
          <label>First VC</label>
          <select name="vc1" id="vc1">
            <option value="">Select a VC...</option>
            {% for vc_name in vc_names_sorted %}
            <option value="{{ vc_name }}">{{ vc_name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="compare-field">
          <label>Second VC</label>
          <select name="vc2" id="vc2">
            <option value="">Select a VC...</option>
            {% for vc_name in vc_names_sorted %}
            <option value="{{ vc_name }}">{{ vc_name }}</option>
            {% endfor %}
          </select>
        </div>
        <button type="submit" class="compare-btn" id="compareBtn" disabled>Compare</button>
      </form>
    </div>
  </div>
  <script>
    const vc1 = document.getElementById('vc1');
    const vc2 = document.getElementById('vc2');
    const btn = document.getElementById('compareBtn');
    function updateBtn() {
      btn.disabled = !(vc1.value && vc2.value && vc1.value !== vc2.value);
    }
    vc1.addEventListener('change', updateBtn);
    vc2.addEventListener('change', updateBtn);
  </script>
</body>
</html>"""


COMPARE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Compare — {{ vc1_name }} vs {{ vc2_name }}</title>
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
      font-size: 0.78rem; color: #6366f1;
      text-decoration: none;
    }
    .back-link:hover { color: #a5b4fc; text-decoration: underline; }

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
      color: #6366f1; margin-bottom: 16px;
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
    .composite-vc1 {
      background: rgba(99,102,241,0.12); color: #a5b4fc;
    }
    .composite-vc2 {
      background: rgba(16,185,129,0.12); color: #6ee7b7;
    }
    .knockout-banner {
      margin-top: 16px; padding: 10px 16px;
      background: rgba(239,68,68,0.1);
      border: 1px solid rgba(239,68,68,0.25);
      border-radius: 8px; color: #fca5a5;
      font-size: 0.78rem; font-weight: 500;
      text-align: center;
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
    .cat-card:hover { border-color: rgba(99,102,241,0.3); }
    .cat-card.active { border-color: rgba(99,102,241,0.5); }
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
    .pill-vc1 { background: rgba(99,102,241,0.12); color: #a5b4fc; }
    .pill-vc2 { background: rgba(16,185,129,0.12); color: #6ee7b7; }
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
      font-size: 0.68rem; font-weight: 600; color: #6366f1;
      margin-right: 8px;
    }
    .prompt-scores {
      display: flex; gap: 8px; align-items: center;
      font-size: 0.72rem; font-weight: 600;
    }
    .prompt-score-vc1 { color: #a5b4fc; }
    .prompt-score-vc2 { color: #6ee7b7; }
    .prompt-score-sep { color: #555; }

    /* Answer panels */
    .prompt-body { display: none; padding: 0 18px 18px; }
    .prompt-card.open .prompt-body { display: block; }

    .question-box {
      background: rgba(99,102,241,0.06);
      border-left: 3px solid #6366f1;
      padding: 12px 16px; margin-bottom: 16px;
      border-radius: 0 8px 8px 0;
      font-size: 0.78rem; color: #a5b4fc;
      line-height: 1.5;
    }

    .vc-answers-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 768px) {
      .vc-answers-grid { grid-template-columns: 1fr; }
    }
    .vc-col-label {
      font-size: 0.68rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.1em;
      padding: 6px 0; margin-bottom: 8px;
    }
    .vc-col-label.vc1 { color: #a5b4fc; }
    .vc-col-label.vc2 { color: #6ee7b7; }

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
      font-size: 0.68rem; color: #818cf8;
      text-decoration: none; margin-right: 10px;
      margin-bottom: 3px;
    }
    .source-link:hover { color: #a5b4fc; text-decoration: underline; }
    .source-domain { font-size: 0.62rem; color: #555; }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">&larr; Back to all VCs</a>

    <div class="header">
      <p class="header-label">VC Comparison</p>
      <h1>{{ vc1_name }} vs {{ vc2_name }}</h1>
      <div class="compare-composites">
        <span class="composite-badge composite-vc1">{{ vc1_name }}: {{ vc1_composite }} / 10</span>
        <span class="composite-badge composite-vc2">{{ vc2_name }}: {{ vc2_composite }} / 10</span>
      </div>
      {% if vc1_knockouts or vc2_knockouts %}
      <div class="knockout-banner">
        {% if vc1_knockouts %}{{ vc1_name }}: knockout in {{ vc1_knockouts | join(', ') }}.{% endif %}
        {% if vc1_knockouts and vc2_knockouts %}<br>{% endif %}
        {% if vc2_knockouts %}{{ vc2_name }}: knockout in {{ vc2_knockouts | join(', ') }}.{% endif %}
      </div>
      {% endif %}
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
            <span class="cat-score-pill pill-vc1">{{ cat.score1 }}</span>
            {% endif %}
            {% if cat.score2 is not none %}
            <span class="cat-score-pill pill-vc2">{{ cat.score2 }}</span>
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
                <span class="prompt-score-vc1">
                  {% if prompt.weighted_score1 is not none %}{{ prompt.weighted_score1 }}{% else %}&mdash;{% endif %}
                </span>
                <span class="prompt-score-sep">|</span>
                <span class="prompt-score-vc2">
                  {% if prompt.weighted_score2 is not none %}{{ prompt.weighted_score2 }}{% else %}&mdash;{% endif %}
                </span>
              </div>
            </div>
            <div class="prompt-body">
              {% if prompt.platform_answers1 or prompt.platform_answers2 %}
              {% set q = (prompt.platform_answers1[0].question if prompt.platform_answers1 else (prompt.platform_answers2[0].question if prompt.platform_answers2 else '')) %}
              {% if q %}
              <div class="question-box">{{ q }}</div>
              {% endif %}
              {% endif %}
              <div class="vc-answers-grid">
                <div>
                  <div class="vc-col-label vc1">{{ vc1_name }}</div>
                  {% for pa in prompt.platform_answers1 %}
                  <div class="ai-answer">
                    <div class="ai-answer-header">
                      <span class="ai-platform {{ pa.platform }}">{{ pa.platform }}</span>
                      <span class="ai-score {{ 'score-strong' if pa.score and pa.score >= 7.5 else ('score-moderate' if pa.score and pa.score >= 5 else 'score-weak') }}">
                        {% if pa.score is not none %}{{ pa.score }} / 10{% else %}&mdash;{% endif %}
                      </span>
                    </div>
                    <div class="ai-answer-text">{{ pa.answer }}</div>
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
                  <div class="vc-col-label vc2">{{ vc2_name }}</div>
                  {% for pa in prompt.platform_answers2 %}
                  <div class="ai-answer">
                    <div class="ai-answer-header">
                      <span class="ai-platform {{ pa.platform }}">{{ pa.platform }}</span>
                      <span class="ai-score {{ 'score-strong' if pa.score and pa.score >= 7.5 else ('score-moderate' if pa.score and pa.score >= 5 else 'score-weak') }}">
                        {% if pa.score is not none %}{{ pa.score }} / 10{% else %}&mdash;{% endif %}
                      </span>
                    </div>
                    <div class="ai-answer-text">{{ pa.answer }}</div>
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
            label: '{{ vc1_name }}',
            data: scores1,
            backgroundColor: 'rgba(99, 102, 241, 0.1)',
            borderColor: 'rgba(99, 102, 241, 0.7)',
            borderWidth: 2,
            pointBackgroundColor: 'rgba(99, 102, 241, 0.9)',
            pointBorderColor: '#0a0a0f',
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 8,
          },
          {
            label: '{{ vc2_name }}',
            data: scores2,
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            borderColor: 'rgba(16, 185, 129, 0.7)',
            borderWidth: 2,
            pointBackgroundColor: 'rgba(16, 185, 129, 0.9)',
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


SOURCE_ANALYSIS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Source Analysis — VC Evaluations</title>
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
      font-size: 0.78rem; color: #6366f1;
      text-decoration: none;
    }
    .back-link:hover { color: #a5b4fc; text-decoration: underline; }

    /* Header */
    .header {
      text-align: center;
      margin-bottom: 48px;
      padding-bottom: 40px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #6366f1; margin-bottom: 16px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.6rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 12px;
    }
    .header-subtitle {
      font-size: 0.9rem; color: #888;
    }

    /* Summary cards */
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 48px;
    }
    .summary-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      padding: 20px;
      text-align: center;
    }
    .summary-value {
      font-size: 2rem; font-weight: 700;
      color: #a5b4fc; margin-bottom: 4px;
    }
    .summary-label {
      font-size: 0.72rem; font-weight: 600;
      letter-spacing: 0.1em; text-transform: uppercase;
      color: #666;
    }

    /* Type pills */
    .type-pills {
      display: flex; flex-wrap: wrap; gap: 10px;
      margin-bottom: 40px;
      justify-content: center;
    }
    .type-pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 14px;
      background: rgba(99,102,241,0.08);
      border: 1px solid rgba(99,102,241,0.2);
      border-radius: 20px;
      font-size: 0.75rem; font-weight: 500;
      color: #a5b4fc;
    }
    .type-pill-count {
      background: rgba(99,102,241,0.2);
      padding: 2px 8px; border-radius: 10px;
      font-weight: 700;
    }

    /* Chart section */
    .chart-section {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 32px;
      margin-bottom: 40px;
    }
    .chart-title {
      font-size: 0.85rem; font-weight: 600;
      color: #e0e0e8; margin-bottom: 24px;
      text-align: center;
    }
    .chart-wrapper {
      position: relative;
      height: 400px;
      margin-bottom: 24px;
    }

    /* Frequency bars */
    .freq-list { margin-top: 32px; }
    .freq-item {
      display: grid;
      grid-template-columns: 200px 1fr 60px 140px;
      align-items: center;
      gap: 16px;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .freq-item:last-child { border-bottom: none; }
    .freq-domain {
      font-size: 0.8rem; font-weight: 500;
      color: #c0c0cc;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .freq-bar-container {
      height: 8px;
      background: rgba(255,255,255,0.05);
      border-radius: 4px;
      overflow: hidden;
    }
    .freq-bar {
      height: 100%;
      background: linear-gradient(90deg, #6366f1, #a5b4fc);
      border-radius: 4px;
      transition: width 0.3s ease;
    }
    .freq-count {
      font-size: 0.78rem; font-weight: 700;
      color: #a5b4fc; text-align: right;
    }
    .freq-type {
      font-size: 0.68rem; font-weight: 500;
      color: #888;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Filter section */
    .filter-section {
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 32px;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .filter-label { font-size: 0.75rem; font-weight: 600; color: #888; text-transform: uppercase; letter-spacing: 0.08em; }
    .prompt-pills { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }
    .prompt-pill {
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 600;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.08);
      color: #888;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.15s;
    }
    .prompt-pill:hover { background: rgba(99,102,241,0.1); border-color: rgba(99,102,241,0.3); color: #a5b4fc; }
    .prompt-pill.active { background: rgba(99,102,241,0.15); border-color: #6366f1; color: #a5b4fc; }
    .prompt-text-box {
      background: rgba(99,102,241,0.06);
      border: 1px solid rgba(99,102,241,0.15);
      border-radius: 10px;
      padding: 16px 20px;
      margin-bottom: 32px;
      font-size: 0.85rem;
      line-height: 1.6;
      color: #c0c0cc;
    }
    .prompt-text-label { font-size: 0.68rem; font-weight: 600; color: #6366f1; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
    .freq-avg { font-size: 0.68rem; color: #888; width: 60px; text-align: right; }
    .no-data { text-align: center; padding: 60px 20px; color: #666; font-size: 0.9rem; }

    @media (max-width: 768px) {
      .freq-item {
        grid-template-columns: 1fr 60px;
      }
      .freq-bar-container, .freq-type { display: none; }
    }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">&larr; Back to VC Evaluations</a>

    <div class="header">
      <p class="header-label">VC Evaluation Analysis</p>
      <h1>Source Analysis</h1>
      <p class="header-subtitle">Citation frequency {% if selected_vc != 'all' %}for {{ selected_vc }}{% endif %}{% if selected_prompt != 'all' %} ({{ selected_prompt }}){% endif %}{% if selected_vc == 'all' and selected_prompt == 'all' %}across all VCs and prompts{% endif %}</p>
    </div>

    <div class="filter-section">
      <span class="filter-label">Filter by VC:</span>
      <div class="prompt-pills">
        <a href="/source-analysis{% if selected_prompt != 'all' %}?prompt={{ selected_prompt }}{% endif %}" class="prompt-pill {{ 'active' if selected_vc == 'all' else '' }}">All</a>
        {% for vc in all_vcs %}
        <a href="/source-analysis?vc={{ vc }}{% if selected_prompt != 'all' %}&prompt={{ selected_prompt }}{% endif %}" class="prompt-pill {{ 'active' if selected_vc == vc else '' }}">{{ vc }}</a>
        {% endfor %}
      </div>
    </div>

    <div class="filter-section">
      <span class="filter-label">Filter by Prompt:</span>
      <div class="prompt-pills">
        <a href="/source-analysis{% if selected_vc != 'all' %}?vc={{ selected_vc }}{% endif %}" class="prompt-pill {{ 'active' if selected_prompt == 'all' else '' }}">All</a>
        {% for pid in all_prompts %}
        <a href="/source-analysis?prompt={{ pid }}{% if selected_vc != 'all' %}&vc={{ selected_vc }}{% endif %}" class="prompt-pill {{ 'active' if selected_prompt == pid else '' }}">{{ pid }}</a>
        {% endfor %}
      </div>
    </div>

    {% if selected_prompt != 'all' and selected_prompt_text %}
    <div class="prompt-text-box">
      <div class="prompt-text-label">Prompt {{ selected_prompt }}</div>
      {{ selected_prompt_text }}
    </div>
    {% endif %}

    {% if frequency_table %}
    <div class="summary-grid">
      <div class="summary-card">
        <div class="summary-value">{{ total_citations }}</div>
        <div class="summary-label">Total Citations</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ avg_per_run }}</div>
        <div class="summary-label">Avg per Run</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ unique_sources }}</div>
        <div class="summary-label">Unique Sources</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ prompt_run_count }}</div>
        <div class="summary-label">Prompt Runs</div>
      </div>
    </div>

    <div class="type-pills">
      {% for type_name, count in source_types.items() %}
      <span class="type-pill">
        {{ type_name }}
        <span class="type-pill-count">{{ count }}</span>
      </span>
      {% endfor %}
    </div>

    <div class="chart-section">
      <h3 class="chart-title">Top 25 Sources by Frequency</h3>
      <div class="chart-wrapper">
        <canvas id="sourceChart"></canvas>
      </div>

      <div class="freq-list">
        {% for item in frequency_table[:50] %}
        <div class="freq-item">
          <span class="freq-domain">{{ item.domain }}</span>
          <div class="freq-bar-container">
            <div class="freq-bar" style="width: {{ (item.frequency / max_frequency * 100) | int }}%"></div>
          </div>
          <span class="freq-count">{{ item.frequency }}</span>
          <span class="freq-avg">{{ item.avg_frequency }}/run</span>
          <span class="freq-type">{{ item.type }}</span>
        </div>
        {% endfor %}
      </div>
    </div>
    {% else %}
    <div class="no-data">
      <p>No sources found for prompt {{ selected_prompt }}.</p>
      <p style="margin-top: 8px;"><a href="/source-analysis" style="color: #6366f1;">View all sources</a></p>
    </div>
    {% endif %}
  </div>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script>
    const chartData = {{ chart_data | safe }};
    if (chartData.labels && chartData.labels.length > 0) {
    const ctx = document.getElementById('sourceChart').getContext('2d');
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: chartData.labels,
        datasets: [{
          label: 'Citations',
          data: chartData.values,
          backgroundColor: 'rgba(99, 102, 241, 0.6)',
          borderColor: 'rgba(99, 102, 241, 0.8)',
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 11 } },
          },
          y: {
            grid: { display: false },
            ticks: { color: 'rgba(255,255,255,0.7)', font: { size: 11 } },
          }
        }
      }
    });
    }
  </script>
</body>
</html>"""


@app.route("/")
def index():
    vc_data = _load_all_vc_data()
    if not vc_data:
        return "<h1>No VC evaluation data found. Run the VC evaluation runners first.</h1>"

    vc_names_sorted = sorted(vc_data.keys())

    return render_template_string(
        INDEX_TEMPLATE,
        vc_data=vc_data,
        vc_names_sorted=vc_names_sorted,
    )


@app.route("/vc/<vc_name>")
def vc_detail(vc_name):
    vc_data = _load_all_vc_data()
    if vc_name not in vc_data:
        return f"<h1>VC '{vc_name}' not found.</h1>", 404

    data = vc_data[vc_name]
    categories_json = json.dumps(data["categories"])

    return render_template_string(
        HTML_TEMPLATE,
        vc_name=vc_name,
        composite=data["composite"],
        knockout_flags=data["knockout_flags"],
        knockout_threshold=VC_KNOCKOUT_THRESHOLD,
        categories=data["categories"],
        categories_json=categories_json,
    )


@app.route("/compare")
def compare():
    vc1_name = request.args.get("vc1", "")
    vc2_name = request.args.get("vc2", "")

    vc_data = _load_all_vc_data()

    if vc1_name not in vc_data or vc2_name not in vc_data:
        return "<h1>One or both VCs not found. Please go back and try again.</h1>", 404

    data1 = vc_data[vc1_name]
    data2 = vc_data[vc2_name]

    # Merge categories for side-by-side display
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
            "is_knockout": c1["is_knockout"],
            "prompts": merged_prompts,
        })

    return render_template_string(
        COMPARE_TEMPLATE,
        vc1_name=vc1_name,
        vc2_name=vc2_name,
        vc1_composite=data1["composite"],
        vc2_composite=data2["composite"],
        vc1_knockouts=data1["knockout_flags"],
        vc2_knockouts=data2["knockout_flags"],
        merged_categories=merged_categories,
        categories1_json=json.dumps(data1["categories"]),
        categories2_json=json.dumps(data2["categories"]),
    )


@app.route("/source-analysis")
def source_analysis():
    """Show source/citation analysis with per-prompt and per-VC filtering."""
    vc_data = _load_all_vc_data()
    selected_prompt = request.args.get("prompt", "all")
    selected_vc = request.args.get("vc", "all")

    # Collect all available VCs
    all_vcs = sorted(vc_data.keys())

    # Collect all available prompts
    all_prompts = set()
    for vc_name, data in vc_data.items():
        for cat in data["categories"]:
            for prompt in cat["prompts"]:
                all_prompts.add(prompt["prompt_id"])
    all_prompts = sorted(all_prompts, key=lambda x: (x[:2], int(x[2:]) if x[2:].isdigit() else 0))

    # Collect sources and prompt texts (filtered by prompt and/or VC if specified)
    all_sources = []
    prompt_run_count = 0
    prompt_texts = {}
    for vc_name, data in vc_data.items():
        # Filter by selected VC
        if selected_vc != "all" and vc_name != selected_vc:
            continue
        for cat in data["categories"]:
            for prompt in cat["prompts"]:
                pid = prompt["prompt_id"]
                # Collect prompt text from the filtered VC
                if pid not in prompt_texts and prompt["platform_answers"]:
                    prompt_texts[pid] = prompt["platform_answers"][0].get("question", "")
                # Filter by selected prompt
                if selected_prompt != "all" and pid != selected_prompt:
                    continue
                for pa in prompt["platform_answers"]:
                    prompt_run_count += 1
                    for source in pa.get("sources", []):
                        url = source.get("url", "")
                        if url:
                            domain = _extract_domain(url)
                            all_sources.append({
                                "url": url,
                                "domain": domain,
                                "type": _categorize_source(domain),
                                "title": source.get("title", ""),
                            })

    # Count frequencies
    domain_counts = Counter(s["domain"] for s in all_sources)
    type_counts = Counter(s["type"] for s in all_sources)

    # Calculate averages
    total_citations = len(all_sources)
    avg_per_run = round(total_citations / prompt_run_count, 1) if prompt_run_count > 0 else 0

    # Build frequency table
    frequency_table = []
    for domain, count in domain_counts.most_common():
        source_type = next((s["type"] for s in all_sources if s["domain"] == domain), "Unknown")
        avg_count = round(count / prompt_run_count, 2) if prompt_run_count > 0 else 0
        frequency_table.append({
            "domain": domain,
            "frequency": count,
            "avg_frequency": avg_count,
            "type": source_type,
        })

    max_frequency = frequency_table[0]["frequency"] if frequency_table else 1

    # Chart data for top 25
    top_25 = frequency_table[:25]
    chart_data = {
        "labels": [item["domain"] for item in top_25],
        "values": [item["frequency"] for item in top_25],
    }

    # Get selected prompt text and replace VC names appropriately
    selected_prompt_text = prompt_texts.get(selected_prompt, "") if selected_prompt != "all" else ""
    if selected_prompt_text:
        # Replace any VC name in the prompt text
        for vc_name in all_vcs:
            if vc_name in selected_prompt_text:
                if selected_vc == "all":
                    selected_prompt_text = selected_prompt_text.replace(vc_name, "{{VC}}")
                else:
                    selected_prompt_text = selected_prompt_text.replace(vc_name, selected_vc)
                break

    return render_template_string(
        SOURCE_ANALYSIS_TEMPLATE,
        total_citations=total_citations,
        unique_sources=len(domain_counts),
        source_types=dict(type_counts.most_common()),
        frequency_table=frequency_table,
        max_frequency=max_frequency,
        chart_data=json.dumps(chart_data),
        all_prompts=all_prompts,
        selected_prompt=selected_prompt,
        selected_prompt_text=selected_prompt_text,
        prompt_run_count=prompt_run_count,
        avg_per_run=avg_per_run,
        all_vcs=all_vcs,
        selected_vc=selected_vc,
    )


@app.route("/api/data")
def api_data():
    return jsonify(_load_all_vc_data())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VC Evaluation Web App")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"Starting VC Evaluation Web App on http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)
