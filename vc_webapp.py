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
from pathlib import Path

from flask import Flask, render_template_string, jsonify

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
  </style>
</head>
<body>
  <div class="app">
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


@app.route("/")
def index():
    vc_data = _load_all_vc_data()
    if not vc_data:
        return "<h1>No VC evaluation data found. Run the VC evaluation runners first.</h1>"

    # For now, show the first (or only) VC
    vc_name = list(vc_data.keys())[0]
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
