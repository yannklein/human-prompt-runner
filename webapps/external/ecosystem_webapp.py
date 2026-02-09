#!/usr/bin/env python3
"""
Ecosystem Analysis Web App

A local Flask web app that displays ecosystem-level analysis:
- Visual ranking cards with entity extraction
- Time-series comparison between dates
- Source change tracking
- Interactive visualizations

Usage:
    python ecosystem_webapp.py
    python ecosystem_webapp.py --port 5003
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urllib.parse import urlparse

from flask import Flask, render_template_string, jsonify, request

from ecosystem_analysis import (
    ECOSYSTEM_COMPANY_PROMPTS,
    load_all_ecosystem_data,
    extract_rankings_from_answer,
    compare_rankings_over_time,
    compare_two_snapshots,
    get_prompt_intelligence,
)

app = Flask(__name__)

# Prompt keywords for external display (instead of full prompt text)
PROMPT_KEYWORDS = {
    "P1": "Top Applications",
    "P2": "Top Countries",
    "P3": "Most Promising Companies",
    "P4": "Best Teams",
    "P5": "Leading Labs/Universities",
    "P6": "Key Technologies",
    "P7": "Major Trends",
    "P8": "Critical Challenges",
    "P9": "Funding Landscape",
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


def _load_data():
    """Load all ecosystem data."""
    return load_all_ecosystem_data()


INDEX_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ecosystem Intelligence (External)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
      color: #e0e0e8;
      line-height: 1.6;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }
    .app { max-width: 1200px; margin: 0 auto; padding: 48px 32px 120px; }

    .header {
      text-align: center;
      margin-bottom: 56px;
      padding-bottom: 40px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #f59e0b; margin-bottom: 16px;
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
    .header-link {
      display: inline-block; margin-top: 16px;
      padding: 8px 18px; border-radius: 8px;
      background: rgba(245,158,11,0.1);
      border: 1px solid rgba(245,158,11,0.3);
      color: #f59e0b; font-size: 0.78rem; font-weight: 500;
      text-decoration: none; transition: all 0.2s;
    }
    .header-link:hover {
      background: rgba(245,158,11,0.2);
      border-color: rgba(245,158,11,0.5);
      text-decoration: none;
    }

    .stats-row {
      display: flex; justify-content: center; gap: 32px;
      margin-bottom: 48px; flex-wrap: wrap;
    }
    .stat-card {
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      padding: 20px 32px;
      text-align: center;
    }
    .stat-value {
      font-size: 2rem; font-weight: 700;
      color: #f59e0b;
    }
    .stat-label {
      font-size: 0.72rem; font-weight: 600;
      letter-spacing: 0.1em; text-transform: uppercase;
      color: #888;
    }

    .section-title {
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: #888; margin-bottom: 16px;
      margin-top: 32px;
    }

    .prompt-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 16px;
      margin-bottom: 48px;
    }
    .prompt-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      padding: 20px;
      text-decoration: none;
      color: #e0e0e8;
      transition: all 0.2s;
    }
    .prompt-card:hover {
      border-color: rgba(245,158,11,0.4);
      background: rgba(245,158,11,0.04);
      transform: translateY(-2px);
    }
    .prompt-id {
      font-size: 0.68rem; font-weight: 700;
      color: #f59e0b;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    .prompt-title {
      font-weight: 600; font-size: 0.95rem;
      margin-bottom: 8px;
    }
    .prompt-meta {
      font-size: 0.75rem; color: #888;
      display: flex; gap: 12px;
    }

    .prompt-card-wrapper { display: flex; flex-direction: column; }
    .intel-link {
      font-size: 0.72rem; color: #888;
      text-decoration: none; padding: 8px 20px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-top: none;
      border-radius: 0 0 12px 12px;
      transition: all 0.2s;
    }
    .intel-link:hover {
      color: #f59e0b; background: rgba(245,158,11,0.06);
    }
    .prompt-card-wrapper .prompt-card {
      border-radius: 12px 12px 0 0;
    }

    .runs-list { margin-bottom: 32px; }
    .run-item {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 18px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      margin-bottom: 8px;
      text-decoration: none;
      color: #e0e0e8;
      transition: all 0.2s;
    }
    .run-item:hover {
      border-color: rgba(245,158,11,0.3);
      background: rgba(245,158,11,0.03);
    }
    .run-date { font-weight: 600; font-size: 0.88rem; }
    .run-meta { display: flex; gap: 12px; align-items: center; }
    .platform-badge {
      font-size: 0.68rem; font-weight: 600;
      padding: 3px 10px; border-radius: 6px;
      text-transform: uppercase;
    }
    .platform-badge.chatgpt { background: rgba(16,185,129,0.12); color: #10b981; }
    .platform-badge.gemini { background: rgba(59,130,246,0.12); color: #3b82f6; }
    .platform-badge.perplexity { background: rgba(167,139,250,0.12); color: #a78bfa; }
    .platform-badge.unknown { background: rgba(255,255,255,0.08); color: #888; }
    .prompts-count { font-size: 0.75rem; color: #888; }
    .arrow { color: #555; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <p class="header-label">Ecosystem Intelligence</p>
      <h1>Quantum Sensing Landscape</h1>
      <p class="header-subtitle">AI-powered analysis tracking how the ecosystem evolves over time</p>
      <a href="/source-analysis" class="header-link">Source Analysis</a>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ total_runs }}</div>
        <div class="stat-label">Analysis Runs</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ total_prompts }}</div>
        <div class="stat-label">Dimensions Tracked</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ platforms | length }}</div>
        <div class="stat-label">AI Platforms</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ date_range }}</div>
        <div class="stat-label">Days of Data</div>
      </div>
    </div>

    <div class="section-title">Ecosystem Dimensions</div>
    <div class="prompt-grid">
      {% for pid, label in prompt_labels.items() %}
      <div class="prompt-card-wrapper">
        <a class="prompt-card" href="/prompt/{{ pid }}">
          <div class="prompt-id">{{ pid }}</div>
          <div class="prompt-title">{{ label }}</div>
          <div class="prompt-meta">
            <span>{{ prompt_counts.get(pid, 0) }} snapshots</span>
          </div>
        </a>
        <a class="intel-link" href="/prompt/{{ pid }}/intelligence">View Intelligence →</a>
      </div>
      {% endfor %}
    </div>

    <div class="section-title">Recent Analysis Runs</div>
    <div class="runs-list">
      {% for run in runs[-10:] | reverse %}
      <a class="run-item" href="/run/{{ run.folder }}">
        <div class="run-date">{{ run.date_str }}</div>
        <div class="run-meta">
          <span class="platform-badge {{ run.platform }}">{{ run.platform }}</span>
          <span class="prompts-count">{{ run.prompts | length }} prompts</span>
          <span class="arrow">→</span>
        </div>
      </a>
      {% endfor %}
    </div>
  </div>
</body>
</html>"""


PROMPT_DETAIL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ prompt_id }} — {{ prompt_label }} (External)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; scroll-behavior: smooth; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
      color: #e0e0e8;
      line-height: 1.6;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }
    .app { max-width: 1400px; margin: 0 auto; padding: 48px 32px 120px; }

    .back-link {
      display: inline-block; margin-bottom: 24px;
      font-size: 0.78rem; color: #f59e0b;
      text-decoration: none;
    }
    .back-link:hover { color: #fbbf24; text-decoration: underline; }

    .header {
      margin-bottom: 32px;
      padding-bottom: 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #f59e0b; margin-bottom: 12px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.2rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 8px;
    }
    .header-subtitle { font-size: 0.88rem; color: #888; }
    .intel-button {
      display: inline-block; margin-top: 12px;
      padding: 8px 16px; border-radius: 6px;
      background: rgba(245,158,11,0.1);
      border: 1px solid rgba(245,158,11,0.3);
      color: #f59e0b; font-size: 0.78rem; font-weight: 500;
      text-decoration: none; transition: all 0.2s;
    }
    .intel-button:hover {
      background: rgba(245,158,11,0.2);
      border-color: rgba(245,158,11,0.5);
    }

    /* Compare selector */
    .compare-section {
      background: rgba(245,158,11,0.05);
      border: 1px solid rgba(245,158,11,0.2);
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 32px;
    }
    .compare-title {
      font-size: 0.75rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.1em;
      color: #f59e0b; margin-bottom: 12px;
    }
    .compare-row {
      display: flex; gap: 16px; align-items: flex-end;
      flex-wrap: wrap;
    }
    .compare-field { flex: 1; min-width: 200px; }
    .compare-field label {
      display: block; font-size: 0.72rem;
      color: #888; margin-bottom: 6px;
    }
    .compare-field select {
      width: 100%; padding: 10px 14px;
      background: rgba(0,0,0,0.3);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 8px;
      color: #e0e0e8;
      font-size: 0.85rem;
      cursor: pointer;
    }
    .compare-btn {
      padding: 10px 24px;
      background: #f59e0b;
      color: #000;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.2s;
    }
    .compare-btn:hover { background: #fbbf24; }
    .compare-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    /* Tabs */
    .tabs {
      display: flex; gap: 4px;
      margin-bottom: 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding-bottom: 0;
    }
    .tab {
      padding: 12px 20px;
      background: transparent;
      border: none;
      color: #888;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      transition: all 0.2s;
    }
    .tab:hover { color: #e0e0e8; }
    .tab.active {
      color: #f59e0b;
      border-bottom-color: #f59e0b;
    }

    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* Rankings grid */
    .rankings-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 16px;
    }
    .snapshot-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      overflow: hidden;
    }
    .snapshot-header {
      padding: 14px 18px;
      background: rgba(255,255,255,0.02);
      border-bottom: 1px solid rgba(255,255,255,0.04);
      display: flex; justify-content: space-between; align-items: center;
    }
    .snapshot-date { font-weight: 600; font-size: 0.9rem; }
    .platform-badge {
      font-size: 0.65rem; font-weight: 700;
      padding: 3px 10px; border-radius: 6px;
      text-transform: uppercase;
    }
    .platform-badge.chatgpt { background: rgba(16,185,129,0.12); color: #10b981; }
    .platform-badge.gemini { background: rgba(59,130,246,0.12); color: #3b82f6; }
    .platform-badge.perplexity { background: rgba(167,139,250,0.12); color: #a78bfa; }
    .snapshot-body { padding: 16px 18px; }

    /* Entity ranking items */
    .entity-list { }
    .entity-item {
      display: flex; gap: 12px;
      padding: 12px 0;
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .entity-item:last-child { border-bottom: none; }
    .entity-rank {
      width: 32px; height: 32px;
      display: flex; align-items: center; justify-content: center;
      background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
      color: #000;
      font-weight: 700;
      font-size: 0.85rem;
      border-radius: 8px;
      flex-shrink: 0;
    }
    .entity-rank.top3 {
      background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
    }
    .entity-content { flex: 1; min-width: 0; }
    .entity-name {
      font-weight: 600; font-size: 0.9rem;
      color: #f0f0f8;
      margin-bottom: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .entity-type {
      font-size: 0.68rem;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .entity-explanation {
      font-size: 0.78rem;
      color: #999;
      margin-top: 6px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    /* Comparison view */
    .comparison-container {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 24px;
      align-items: start;
    }
    @media (max-width: 1000px) {
      .comparison-container {
        grid-template-columns: 1fr;
      }
      .changes-column { order: -1; }
    }

    .comparison-column {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      overflow: hidden;
    }
    .comparison-header {
      padding: 16px 20px;
      background: rgba(255,255,255,0.03);
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .comparison-title {
      font-weight: 600; font-size: 0.9rem;
      margin-bottom: 4px;
    }
    .comparison-meta {
      font-size: 0.75rem; color: #888;
    }
    .comparison-body { padding: 16px 20px; }

    /* Changes column */
    .changes-column {
      background: rgba(245,158,11,0.05);
      border: 1px solid rgba(245,158,11,0.2);
      border-radius: 12px;
      padding: 20px;
      min-width: 280px;
    }
    .changes-title {
      font-size: 0.75rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.1em;
      color: #f59e0b; margin-bottom: 16px;
    }
    .change-item {
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .change-item:last-child { border-bottom: none; }
    .change-badge {
      display: inline-block;
      font-size: 0.65rem; font-weight: 700;
      padding: 2px 8px; border-radius: 4px;
      margin-right: 8px;
      text-transform: uppercase;
    }
    .change-badge.new { background: rgba(34,197,94,0.15); color: #4ade80; }
    .change-badge.removed { background: rgba(239,68,68,0.15); color: #f87171; }
    .change-badge.up { background: rgba(34,197,94,0.15); color: #4ade80; }
    .change-badge.down { background: rgba(239,68,68,0.15); color: #f87171; }
    .change-entity { font-weight: 500; font-size: 0.85rem; }
    .change-detail {
      font-size: 0.75rem; color: #888;
      margin-top: 4px;
    }

    /* Source changes */
    .sources-section {
      margin-top: 20px;
      padding-top: 16px;
      border-top: 1px solid rgba(255,255,255,0.06);
    }
    .sources-title {
      font-size: 0.72rem; font-weight: 600;
      color: #888; text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 10px;
    }
    .source-item {
      font-size: 0.75rem;
      padding: 6px 0;
      display: flex; align-items: center; gap: 8px;
    }
    .source-item a {
      color: #f59e0b;
      text-decoration: none;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .source-item a:hover { text-decoration: underline; }
    .source-badge {
      font-size: 0.6rem; font-weight: 700;
      padding: 2px 6px; border-radius: 3px;
      flex-shrink: 0;
    }
    .source-badge.new { background: rgba(34,197,94,0.15); color: #4ade80; }
    .source-badge.removed { background: rgba(239,68,68,0.15); color: #f87171; }

    /* No data state */
    .no-data {
      text-align: center;
      padding: 60px 20px;
      color: #666;
    }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">← Back to Ecosystem</a>

    <div class="header">
      <p class="header-label">{{ prompt_id }}</p>
      <h1>{{ prompt_label }}</h1>
      <p class="header-subtitle">{{ data_points | length }} snapshots across {{ platforms | length }} platforms</p>
      <a href="/prompt/{{ prompt_id }}/intelligence" class="intel-button">View Source Intelligence →</a>
    </div>

    <div class="compare-section">
      <div class="compare-title">Compare Two Snapshots</div>
      <div class="compare-row">
        <div class="compare-field">
          <label>From (older)</label>
          <select id="date1">
            <option value="">Select snapshot...</option>
            {% for entry in data_points %}
            <option value="{{ loop.index0 }}">{{ entry.date_str }} ({{ entry.platform }})</option>
            {% endfor %}
          </select>
        </div>
        <div class="compare-field">
          <label>To (newer)</label>
          <select id="date2">
            <option value="">Select snapshot...</option>
            {% for entry in data_points %}
            <option value="{{ loop.index0 }}" {% if loop.last %}selected{% endif %}>{{ entry.date_str }} ({{ entry.platform }})</option>
            {% endfor %}
          </select>
        </div>
        <button class="compare-btn" onclick="compareSnapshots()">Compare</button>
      </div>
    </div>

    <div class="tabs">
      <button class="tab active" onclick="showTab('latest')">Latest Rankings</button>
      <button class="tab" onclick="showTab('timeline')">All Snapshots</button>
      <button class="tab" onclick="showTab('comparison')">Comparison</button>
    </div>

    <!-- Latest Rankings Tab -->
    <div class="tab-content active" id="tab-latest">
      <div class="rankings-grid">
        {% for platform, entry in latest_by_platform.items() %}
        <div class="snapshot-card">
          <div class="snapshot-header">
            <span class="snapshot-date">{{ entry.date_str }}</span>
            <span class="platform-badge {{ platform }}">{{ platform }}</span>
          </div>
          <div class="snapshot-body">
            <div class="entity-list">
              {% for r in entry.rankings[:10] %}
              <div class="entity-item">
                <div class="entity-rank {% if r.rank <= 3 %}top3{% endif %}">{{ r.rank }}</div>
                <div class="entity-content">
                  <div class="entity-name" title="{{ r.entity.full_title }}">{{ r.entity.name }}</div>
                  <div class="entity-type">{{ r.entity.type }}</div>
                  {% if r.explanation %}
                  <div class="entity-explanation">{{ r.explanation[:150] }}</div>
                  {% endif %}
                </div>
              </div>
              {% endfor %}
              {% if not entry.rankings %}
              <div class="no-data">No rankings extracted</div>
              {% endif %}
            </div>
          </div>
        </div>
        {% endfor %}
      </div>
    </div>

    <!-- Timeline Tab -->
    <div class="tab-content" id="tab-timeline">
      <div class="rankings-grid">
        {% for entry in data_points | reverse %}
        <div class="snapshot-card">
          <div class="snapshot-header">
            <span class="snapshot-date">{{ entry.date_str }}</span>
            <span class="platform-badge {{ entry.platform }}">{{ entry.platform }}</span>
          </div>
          <div class="snapshot-body">
            <div class="entity-list">
              {% for r in entry.rankings[:10] %}
              <div class="entity-item">
                <div class="entity-rank {% if r.rank <= 3 %}top3{% endif %}">{{ r.rank }}</div>
                <div class="entity-content">
                  <div class="entity-name">{{ r.entity.name }}</div>
                  <div class="entity-type">{{ r.entity.type }}</div>
                </div>
              </div>
              {% endfor %}
            </div>
          </div>
        </div>
        {% endfor %}
      </div>
    </div>

    <!-- Comparison Tab -->
    <div class="tab-content" id="tab-comparison">
      <div id="comparison-content">
        <div class="no-data">
          Select two snapshots above and click "Compare" to see how rankings changed.
        </div>
      </div>
    </div>
  </div>

  <script>
    const dataPoints = {{ data_points_json | safe }};

    function showTab(tabId) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById('tab-' + tabId).classList.add('active');
    }

    function compareSnapshots() {
      const idx1 = document.getElementById('date1').value;
      const idx2 = document.getElementById('date2').value;

      if (!idx1 || !idx2) {
        alert('Please select two snapshots to compare');
        return;
      }

      // Switch to comparison tab
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      document.querySelectorAll('.tab')[2].classList.add('active');
      document.getElementById('tab-comparison').classList.add('active');

      // Fetch comparison
      fetch(`/api/prompt/{{ prompt_id }}/compare?idx1=${idx1}&idx2=${idx2}`)
        .then(r => r.json())
        .then(data => renderComparison(data))
        .catch(err => {
          document.getElementById('comparison-content').innerHTML =
            '<div class="no-data">Error loading comparison</div>';
        });
    }

    function renderComparison(data) {
      const container = document.getElementById('comparison-content');

      let changesHtml = '';
      for (const change of data.changes.slice(0, 15)) {
        if (change.type === 'new') {
          changesHtml += `
            <div class="change-item">
              <span class="change-badge new">NEW</span>
              <span class="change-entity">${escapeHtml(change.entity.name)}</span>
              <div class="change-detail">Entered at #${change.new_rank}</div>
            </div>`;
        } else if (change.type === 'removed') {
          changesHtml += `
            <div class="change-item">
              <span class="change-badge removed">OUT</span>
              <span class="change-entity">${escapeHtml(change.entity.name)}</span>
              <div class="change-detail">Was at #${change.old_rank}</div>
            </div>`;
        } else if (change.type === 'moved') {
          const badge = change.change > 0 ? 'up' : 'down';
          const arrow = change.change > 0 ? '↑' : '↓';
          changesHtml += `
            <div class="change-item">
              <span class="change-badge ${badge}">${arrow}${Math.abs(change.change)}</span>
              <span class="change-entity">${escapeHtml(change.entity.name)}</span>
              <div class="change-detail">#${change.old_rank} → #${change.new_rank}</div>
            </div>`;
        }
      }

      if (!changesHtml) {
        changesHtml = '<div class="no-data">No significant changes detected</div>';
      }

      // Source changes
      let sourcesHtml = '';
      if (data.source_changes.new_sources.length > 0 || data.source_changes.removed_sources.length > 0) {
        sourcesHtml = '<div class="sources-section"><div class="sources-title">Source Changes</div>';
        for (const s of data.source_changes.new_sources.slice(0, 5)) {
          sourcesHtml += `
            <div class="source-item">
              <span class="source-badge new">NEW</span>
              <a href="${escapeHtml(s.url)}" target="_blank">${escapeHtml(s.title || s.url)}</a>
            </div>`;
        }
        for (const s of data.source_changes.removed_sources.slice(0, 5)) {
          sourcesHtml += `
            <div class="source-item">
              <span class="source-badge removed">REMOVED</span>
              <a href="${escapeHtml(s.url)}" target="_blank">${escapeHtml(s.title || s.url)}</a>
            </div>`;
        }
        sourcesHtml += '</div>';
      }

      function renderRankings(rankings) {
        return rankings.slice(0, 10).map(r => `
          <div class="entity-item">
            <div class="entity-rank ${r.rank <= 3 ? 'top3' : ''}">${r.rank}</div>
            <div class="entity-content">
              <div class="entity-name">${escapeHtml(r.entity.name)}</div>
              <div class="entity-type">${r.entity.type}</div>
            </div>
          </div>
        `).join('');
      }

      container.innerHTML = `
        <div class="comparison-container">
          <div class="comparison-column">
            <div class="comparison-header">
              <div class="comparison-title">${data.snapshot1.date_str}</div>
              <div class="comparison-meta">${data.snapshot1.platform} · ${data.stats.total_in_old} items</div>
            </div>
            <div class="comparison-body">
              <div class="entity-list">
                ${renderRankings(data.snapshot1.rankings)}
              </div>
            </div>
          </div>

          <div class="changes-column">
            <div class="changes-title">Changes</div>
            <div style="font-size: 0.82rem; color: #e0e0e8; margin-bottom: 16px;">
              ${escapeHtml(data.summary)}
            </div>
            ${changesHtml}
            ${sourcesHtml}
          </div>

          <div class="comparison-column">
            <div class="comparison-header">
              <div class="comparison-title">${data.snapshot2.date_str}</div>
              <div class="comparison-meta">${data.snapshot2.platform} · ${data.stats.total_in_new} items</div>
            </div>
            <div class="comparison-body">
              <div class="entity-list">
                ${renderRankings(data.snapshot2.rankings)}
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text || '';
      return div.innerHTML;
    }
  </script>
</body>
</html>"""


RUN_DETAIL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Run — {{ run.date_str }} ({{ run.platform }}) (External)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { font-size: 16px; scroll-behavior: smooth; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
      color: #e0e0e8;
      line-height: 1.6;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }
    .app { max-width: 1000px; margin: 0 auto; padding: 48px 32px 120px; }

    .back-link {
      display: inline-block; margin-bottom: 24px;
      font-size: 0.78rem; color: #f59e0b;
      text-decoration: none;
    }
    .back-link:hover { color: #fbbf24; text-decoration: underline; }

    .header {
      margin-bottom: 40px;
      padding-bottom: 32px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .header-label {
      font-size: 0.65rem; font-weight: 600;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: #f59e0b; margin-bottom: 12px;
    }
    .header h1 {
      font-family: 'EB Garamond', Georgia, serif;
      font-size: 2.2rem; font-weight: 500;
      color: #f0f0f8; letter-spacing: -0.02em;
      margin-bottom: 8px;
    }
    .header-meta {
      display: flex; gap: 16px; align-items: center;
    }
    .platform-badge {
      font-size: 0.72rem; font-weight: 700;
      padding: 4px 12px; border-radius: 6px;
      text-transform: uppercase;
    }
    .platform-badge.chatgpt { background: rgba(16,185,129,0.12); color: #10b981; }
    .platform-badge.gemini { background: rgba(59,130,246,0.12); color: #3b82f6; }
    .platform-badge.perplexity { background: rgba(167,139,250,0.12); color: #a78bfa; }
    .prompts-count { font-size: 0.85rem; color: #888; }

    .prompts-list { }
    .prompt-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      margin-bottom: 16px;
      overflow: hidden;
    }
    .prompt-card-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 16px 20px;
      cursor: pointer;
      transition: background 0.2s;
    }
    .prompt-card-header:hover { background: rgba(255,255,255,0.02); }
    .prompt-card.active { border-color: rgba(245,158,11,0.4); }
    .prompt-id-label { display: flex; gap: 12px; align-items: center; }
    .prompt-id {
      font-size: 0.7rem; font-weight: 700;
      color: #f59e0b;
    }
    .prompt-title { font-weight: 500; font-size: 0.9rem; }
    .chevron {
      color: #555; font-size: 0.8rem;
      transition: transform 0.2s;
    }
    .prompt-card.active .chevron { transform: rotate(180deg); }

    .prompt-card-body {
      display: none;
      padding: 0 20px 20px;
    }
    .prompt-card.active .prompt-card-body { display: block; }

    .question-box {
      background: rgba(245,158,11,0.06);
      border-left: 3px solid #f59e0b;
      padding: 12px 16px;
      border-radius: 0 8px 8px 0;
      font-size: 0.82rem;
      color: #fbbf24;
      margin-bottom: 16px;
    }
    .answer-box {
      font-size: 0.85rem;
      color: #b0b0bc;
      line-height: 1.7;
      white-space: pre-wrap;
      max-height: 500px;
      overflow-y: auto;
      padding: 16px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    }
  </style>
</head>
<body>
  <div class="app">
    <a class="back-link" href="/">← Back to Ecosystem</a>

    <div class="header">
      <p class="header-label">Analysis Run</p>
      <h1>{{ run.date_str }}</h1>
      <div class="header-meta">
        <span class="platform-badge {{ run.platform }}">{{ run.platform }}</span>
        <span class="prompts-count">{{ run.prompts | length }} prompts analyzed</span>
      </div>
    </div>

    <div class="prompts-list">
      {% for pid, pdata in run.prompts.items() | sort %}
      <div class="prompt-card" id="card-{{ pid }}">
        <div class="prompt-card-header" onclick="toggleCard('{{ pid }}')">
          <div class="prompt-id-label">
            <span class="prompt-id">{{ pid }}</span>
            <span class="prompt-title">{{ prompt_labels.get(pid, pid) }}</span>
          </div>
          <span class="chevron">▾</span>
        </div>
        <div class="prompt-card-body">
          <div class="question-box" style="color: #666; font-style: italic;">Prompt content available in internal version only</div>
          <div class="answer-box" style="color: #666; font-style: italic;">Response content available in internal version only</div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <script>
    function toggleCard(pid) {
      document.getElementById('card-' + pid).classList.toggle('active');
    }
  </script>
</body>
</html>"""


INTELLIGENCE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ prompt_id }} Intelligence - {{ prompt_label }} (External)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
      color: #e0e0e8;
      min-height: 100vh;
      line-height: 1.5;
    }
    .app { max-width: 1400px; margin: 0 auto; padding: 40px 32px 100px; }
    a { color: #f59e0b; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .header {
      margin-bottom: 40px;
      padding-bottom: 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .back-link { font-size: 0.75rem; color: #888; margin-bottom: 12px; display: inline-block; }
    .header h1 { font-size: 1.8rem; font-weight: 600; margin-bottom: 8px; }
    .header-subtitle { font-size: 0.9rem; color: #888; }

    .summary-row {
      display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px;
    }
    .summary-card {
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      padding: 16px 24px;
      text-align: center;
      flex: 1; min-width: 140px;
    }
    .summary-value { font-size: 1.8rem; font-weight: 700; color: #f59e0b; }
    .summary-label { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #888; }

    .tabs {
      display: flex; gap: 8px; margin-bottom: 24px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      padding-bottom: 8px;
    }
    .tab {
      padding: 8px 20px; border-radius: 8px 8px 0 0;
      background: transparent; border: none; color: #888;
      font-size: 0.85rem; font-weight: 500; cursor: pointer;
      transition: all 0.2s;
    }
    .tab:hover { color: #ccc; }
    .tab.active { background: rgba(245,158,11,0.12); color: #f59e0b; }

    .tab-content { display: none; }
    .tab-content.active { display: block; }

    .section { margin-bottom: 40px; }
    .section-title {
      font-size: 0.72rem; font-weight: 600;
      letter-spacing: 0.1em; text-transform: uppercase;
      color: #888; margin-bottom: 16px;
    }

    /* Results Table */
    .data-table {
      width: 100%; border-collapse: collapse;
      font-size: 0.82rem;
    }
    .data-table th {
      text-align: left; padding: 10px 12px;
      background: rgba(255,255,255,0.04);
      font-weight: 600; font-size: 0.7rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: #888; border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .data-table td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      vertical-align: top;
    }
    .data-table tr:hover td { background: rgba(255,255,255,0.02); }
    .rank-cell { font-weight: 700; color: #f59e0b; width: 50px; text-align: center; }
    .entity-cell { font-weight: 500; }
    .platform-badge {
      font-size: 0.65rem; font-weight: 600;
      padding: 2px 8px; border-radius: 4px;
      text-transform: uppercase;
    }
    .platform-badge.chatgpt { background: rgba(16,185,129,0.12); color: #10b981; }
    .platform-badge.gemini { background: rgba(59,130,246,0.12); color: #3b82f6; }
    .platform-badge.perplexity { background: rgba(167,139,250,0.12); color: #a78bfa; }
    .explanation-cell { color: #999; font-size: 0.78rem; max-width: 400px; }

    /* Entity Cards */
    .entity-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }
    .entity-card {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      padding: 16px;
      display: flex; align-items: center; gap: 14px;
    }
    .entity-rank {
      width: 40px; height: 40px;
      background: linear-gradient(135deg, #f59e0b, #d97706);
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 1rem; color: #000;
    }
    .entity-rank.silver { background: linear-gradient(135deg, #94a3b8, #64748b); color: #fff; }
    .entity-rank.bronze { background: linear-gradient(135deg, #b45309, #92400e); color: #fff; }
    .entity-info h4 { font-weight: 600; font-size: 0.9rem; margin-bottom: 4px; }
    .entity-stats { font-size: 0.75rem; color: #888; }

    /* Source Frequency */
    .source-bar-row {
      display: flex; align-items: center; gap: 12px;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .source-domain { width: 180px; font-size: 0.82rem; font-weight: 500; }
    .source-bar-container { flex: 1; height: 20px; background: rgba(255,255,255,0.04); border-radius: 4px; overflow: hidden; }
    .source-bar {
      height: 100%; background: linear-gradient(90deg, #f59e0b, #d97706);
      border-radius: 4px;
      transition: width 0.3s;
    }
    .source-count { width: 50px; text-align: right; font-weight: 600; font-size: 0.82rem; color: #f59e0b; }
    .source-type { width: 160px; font-size: 0.72rem; color: #888; text-align: right; }

    /* Chart Container */
    .chart-container {
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
    }
    .chart-title { font-size: 0.85rem; font-weight: 600; margin-bottom: 16px; }
    .chart-wrapper { height: 300px; }

    /* Source Type Pills */
    .type-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
    .type-pill {
      padding: 6px 14px; border-radius: 20px;
      font-size: 0.75rem; font-weight: 500;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .type-pill .count { color: #f59e0b; font-weight: 700; margin-left: 6px; }

    /* Filter */
    .filter-row {
      display: flex; gap: 12px; margin-bottom: 20px; align-items: center;
    }
    .filter-row label { font-size: 0.75rem; color: #888; }
    .filter-row select, .filter-row input {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 6px;
      padding: 6px 12px;
      color: #e0e0e8;
      font-size: 0.82rem;
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <a href="/" class="back-link">&larr; Back to Dashboard</a>
      <h1>{{ prompt_id }}: {{ prompt_label }}</h1>
      <p class="header-subtitle">Intelligence report showing which entities and sources are most frequently cited</p>
    </div>

    <div class="summary-row">
      <div class="summary-card">
        <div class="summary-value">{{ intel.summary.total_responses }}</div>
        <div class="summary-label">AI Responses</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ intel.summary.unique_entities }}</div>
        <div class="summary-label">Unique Entities</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ intel.summary.total_citations }}</div>
        <div class="summary-label">Source Citations</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{{ intel.summary.unique_sources }}</div>
        <div class="summary-label">Unique Sources</div>
      </div>
    </div>

    <div class="tabs">
      <button class="tab active" data-tab="entities">Top Entities</button>
      <button class="tab" data-tab="sources">Source Analysis</button>
      <button class="tab" data-tab="results">Results Table</button>
      <button class="tab" data-tab="sources-table">Sources Table</button>
    </div>

    <!-- TOP ENTITIES TAB -->
    <div id="tab-entities" class="tab-content active">
      <div class="section">
        <h3 class="section-title">Most Frequently Mentioned Entities</h3>
        <div class="entity-grid">
          {% for e in intel.top_entities %}
          <div class="entity-card">
            <div class="entity-rank {% if loop.index == 2 %}silver{% elif loop.index == 3 %}bronze{% endif %}">
              {{ loop.index }}
            </div>
            <div class="entity-info">
              <h4>{{ e.name }}</h4>
              <div class="entity-stats">
                {{ e.appearances }} mentions &middot; Avg rank {{ e.avg_rank }} &middot; Best #{{ e.best_rank }}
              </div>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
    </div>

    <!-- SOURCES TAB -->
    <div id="tab-sources" class="tab-content">
      <div class="section">
        <h3 class="section-title">Source Type Distribution</h3>
        <div class="type-pills">
          {% for t in intel.source_types %}
          <div class="type-pill">{{ t.type }}<span class="count">{{ t.count }}</span></div>
          {% endfor %}
        </div>

        <div class="chart-container">
          <div class="chart-title">Top Sources by Citation Frequency</div>
          <div class="chart-wrapper">
            <canvas id="sourcesChart"></canvas>
          </div>
        </div>
      </div>

      <div class="section">
        <h3 class="section-title">Source Frequency ({{ intel.top_sources | length }} sources)</h3>
        {% for s in intel.top_sources %}
        <div class="source-bar-row">
          <div class="source-domain">{{ s.domain }}</div>
          <div class="source-bar-container">
            <div class="source-bar" style="width: {{ (s.frequency / intel.top_sources[0].frequency * 100) | int }}%"></div>
          </div>
          <div class="source-count">{{ s.frequency }}</div>
          <div class="source-type">{{ s.type }}</div>
        </div>
        {% endfor %}
      </div>
    </div>

    <!-- RESULTS TABLE TAB -->
    <div id="tab-results" class="tab-content">
      <div class="section">
        <h3 class="section-title">All Results ({{ intel.results_table | length }} rows)</h3>
        <div class="filter-row">
          <label>Filter by platform:</label>
          <select id="filterPlatform" onchange="filterResults()">
            <option value="">All</option>
            <option value="chatgpt">ChatGPT</option>
            <option value="gemini">Gemini</option>
            <option value="perplexity">Perplexity</option>
          </select>
          <label>Filter by date:</label>
          <select id="filterDate" onchange="filterResults()">
            <option value="">All</option>
            {% for date in dates %}
            <option value="{{ date }}">{{ date }}</option>
            {% endfor %}
          </select>
        </div>
        <table class="data-table" id="resultsTable">
          <thead>
            <tr>
              <th>Date</th>
              <th>Source</th>
              <th>Rank</th>
              <th>Entity</th>
              <th>Explanation</th>
            </tr>
          </thead>
          <tbody>
            {% for row in intel.results_table %}
            <tr data-platform="{{ row.source }}" data-date="{{ row.date }}">
              <td>{{ row.date }}</td>
              <td><span class="platform-badge {{ row.source }}">{{ row.source }}</span></td>
              <td class="rank-cell">{{ row.rank }}</td>
              <td class="entity-cell">{{ row.entity }}</td>
              <td class="explanation-cell">{{ row.explanation[:200] }}{% if row.explanation|length > 200 %}...{% endif %}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- SOURCES TABLE TAB -->
    <div id="tab-sources-table" class="tab-content">
      <div class="section">
        <h3 class="section-title">All Source Citations ({{ intel.sources_table | length }} rows)</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>AI Source</th>
              <th>Domain</th>
              <th>URL</th>
            </tr>
          </thead>
          <tbody>
            {% for row in intel.sources_table[:200] %}
            <tr>
              <td>{{ row.date }}</td>
              <td><span class="platform-badge {{ row.source }}">{{ row.source }}</span></td>
              <td>{{ row.domain }}</td>
              <td><a href="{{ row.url }}" target="_blank">{{ row.url[:60] }}{% if row.url|length > 60 %}...{% endif %}</a></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    // Tab switching
    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
      });
    });

    // Filter results
    function filterResults() {
      const platform = document.getElementById('filterPlatform').value;
      const date = document.getElementById('filterDate').value;
      document.querySelectorAll('#resultsTable tbody tr').forEach(row => {
        const matchPlatform = !platform || row.dataset.platform === platform;
        const matchDate = !date || row.dataset.date === date;
        row.style.display = matchPlatform && matchDate ? '' : 'none';
      });
    }

    // Sources chart
    const topSources = {{ intel.top_sources | tojson }};
    const chartData = topSources.slice(0, 15);

    new Chart(document.getElementById('sourcesChart'), {
      type: 'bar',
      data: {
        labels: chartData.map(s => s.domain),
        datasets: [{
          label: 'Citations',
          data: chartData.map(s => s.frequency),
          backgroundColor: 'rgba(245, 158, 11, 0.7)',
          borderColor: 'rgba(245, 158, 11, 1)',
          borderWidth: 1,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#888' }
          },
          y: {
            grid: { display: false },
            ticks: { color: '#e0e0e8', font: { size: 11 } }
          }
        }
      }
    });
  </script>
</body>
</html>"""


@app.route("/")
def index():
    data = _load_data()

    total_runs = len(data["runs"])
    total_prompts = len(ECOSYSTEM_COMPANY_PROMPTS)
    platforms = set(r["platform"] for r in data["runs"])

    dates = [r["date"] for r in data["runs"] if r["date"]]
    date_range = (max(dates) - min(dates)).days + 1 if dates else 0

    prompt_counts = {pid: len(entries) for pid, entries in data["by_prompt"].items()}

    return render_template_string(
        INDEX_TEMPLATE,
        runs=data["runs"],
        total_runs=total_runs,
        total_prompts=total_prompts,
        platforms=platforms,
        date_range=date_range,
        prompt_labels=ECOSYSTEM_COMPANY_PROMPTS,
        prompt_counts=prompt_counts,
    )


@app.route("/prompt/<prompt_id>")
def prompt_detail(prompt_id):
    data = _load_data()

    if prompt_id not in data["by_prompt"]:
        return f"<h1>Prompt '{prompt_id}' not found.</h1>", 404

    data_points = data["by_prompt"][prompt_id]

    # Extract rankings for each entry
    for entry in data_points:
        entry["rankings"] = extract_rankings_from_answer(entry["data"]["answer"])
        entry["folder"] = entry.get("folder", "")

    platforms = set(e["platform"] for e in data_points)

    # Get latest by platform
    latest_by_platform = {}
    for entry in reversed(data_points):
        if entry["platform"] not in latest_by_platform:
            latest_by_platform[entry["platform"]] = entry

    # Prepare JSON for JavaScript
    data_points_json = json.dumps([
        {
            "date_str": e["date_str"],
            "platform": e["platform"],
            "rankings": e["rankings"],
        }
        for e in data_points
    ])

    return render_template_string(
        PROMPT_DETAIL_TEMPLATE,
        prompt_id=prompt_id,
        prompt_label=ECOSYSTEM_COMPANY_PROMPTS.get(prompt_id, prompt_id),
        data_points=data_points,
        data_points_json=data_points_json,
        platforms=platforms,
        latest_by_platform=latest_by_platform,
    )


@app.route("/run/<folder_name>")
def run_detail(folder_name):
    data = _load_data()

    run = None
    for r in data["runs"]:
        if r["folder"] == folder_name:
            run = r
            break

    if not run:
        return f"<h1>Run '{folder_name}' not found.</h1>", 404

    return render_template_string(
        RUN_DETAIL_TEMPLATE,
        run=run,
        prompt_labels=ECOSYSTEM_COMPANY_PROMPTS,
    )


@app.route("/prompt/<prompt_id>/intelligence")
def prompt_intelligence(prompt_id):
    """Show intelligence report for a prompt."""
    intel = get_prompt_intelligence(prompt_id)

    if not intel["summary"]["total_responses"]:
        return f"<h1>No data found for prompt '{prompt_id}'</h1>", 404

    # Get unique dates for filter
    dates = sorted(set(row["date"] for row in intel["results_table"]))

    return render_template_string(
        INTELLIGENCE_TEMPLATE,
        prompt_id=prompt_id,
        prompt_label=intel["prompt_label"],
        intel=intel,
        dates=dates,
    )


@app.route("/api/prompt/<prompt_id>/intelligence")
def api_prompt_intelligence(prompt_id):
    """API endpoint for prompt intelligence data."""
    intel = get_prompt_intelligence(prompt_id)
    return jsonify(intel)


@app.route("/api/data")
def api_data():
    return jsonify(_load_data())


@app.route("/api/prompt/<prompt_id>/compare")
def api_prompt_compare(prompt_id):
    """Compare two snapshots for a prompt."""
    data = _load_data()

    if prompt_id not in data["by_prompt"]:
        return jsonify({"error": "Prompt not found"}), 404

    idx1 = request.args.get("idx1", type=int)
    idx2 = request.args.get("idx2", type=int)

    data_points = data["by_prompt"][prompt_id]

    if idx1 is None or idx2 is None or idx1 >= len(data_points) or idx2 >= len(data_points):
        return jsonify({"error": "Invalid indices"}), 400

    entry1 = data_points[idx1]
    entry2 = data_points[idx2]

    comparison = compare_two_snapshots(entry1["data"], entry2["data"])

    # Add snapshot info
    rankings1 = extract_rankings_from_answer(entry1["data"]["answer"])
    rankings2 = extract_rankings_from_answer(entry2["data"]["answer"])

    comparison["snapshot1"] = {
        "date_str": entry1["date_str"],
        "platform": entry1["platform"],
        "rankings": rankings1,
    }
    comparison["snapshot2"] = {
        "date_str": entry2["date_str"],
        "platform": entry2["platform"],
        "rankings": rankings2,
    }

    return jsonify(comparison)


@app.route("/api/prompt/<prompt_id>/timeline")
def api_prompt_timeline(prompt_id):
    data = _load_data()

    if prompt_id not in data["by_prompt"]:
        return jsonify({"error": "Prompt not found"}), 404

    comparison = compare_rankings_over_time(data["by_prompt"][prompt_id])
    return jsonify(comparison)


@app.route("/source-analysis")
def source_analysis():
    """Show source/citation analysis with per-prompt filtering (keywords only)."""
    data = _load_data()
    selected_prompt = request.args.get("prompt", "all")

    # Collect all available prompts
    all_prompts = sorted(data["by_prompt"].keys(), key=lambda x: (x[0], int(x[1:]) if x[1:].isdigit() else 0))

    source_counts = {}
    source_details = {}
    prompt_run_count = 0

    for prompt_id, entries in data["by_prompt"].items():
        if selected_prompt != "all" and prompt_id != selected_prompt:
            continue
        for entry in entries:
            prompt_run_count += 1
            sources = entry.get("data", {}).get("sources", [])
            for source in sources:
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
    )


SOURCE_ANALYSIS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Source Analysis - Ecosystem</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%); color: #e0e0e8; min-height: 100vh; line-height: 1.5; }
    .app { max-width: 1200px; margin: 0 auto; padding: 40px 32px 100px; }
    a { color: #f59e0b; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .header { margin-bottom: 40px; padding-bottom: 24px; border-bottom: 1px solid rgba(255,255,255,0.06); }
    .back-link { font-size: 0.75rem; color: #888; margin-bottom: 12px; display: inline-block; }
    .header h1 { font-size: 1.8rem; font-weight: 600; margin-bottom: 8px; }
    .header-subtitle { font-size: 0.9rem; color: #888; }
    .filter-section { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 20px 24px; margin-bottom: 32px; }
    .filter-label { font-size: 0.75rem; font-weight: 600; color: #888; text-transform: uppercase; margin-bottom: 12px; display: block; }
    .prompt-pills { display: flex; flex-wrap: wrap; gap: 6px; }
    .prompt-pill { padding: 6px 12px; border-radius: 6px; font-size: 0.72rem; font-weight: 600; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); color: #888; text-decoration: none; transition: all 0.15s; }
    .prompt-pill:hover { background: rgba(245,158,11,0.1); border-color: rgba(245,158,11,0.3); color: #f59e0b; text-decoration: none; }
    .prompt-pill.active { background: rgba(245,158,11,0.15); border-color: #f59e0b; color: #f59e0b; }
    .keyword-box { background: rgba(245,158,11,0.06); border: 1px solid rgba(245,158,11,0.15); border-radius: 10px; padding: 14px 18px; margin-bottom: 24px; font-size: 0.85rem; color: #f59e0b; font-weight: 500; }
    .summary-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }
    .summary-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 16px 24px; text-align: center; flex: 1; min-width: 120px; }
    .summary-value { font-size: 1.6rem; font-weight: 700; color: #f59e0b; }
    .summary-label { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #888; }
    .section-title { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #888; margin-bottom: 16px; }
    .source-bar-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
    .source-domain { width: 180px; font-size: 0.82rem; font-weight: 500; }
    .source-bar-container { flex: 1; height: 18px; background: rgba(255,255,255,0.04); border-radius: 4px; overflow: hidden; }
    .source-bar { height: 100%; background: linear-gradient(90deg, #f59e0b, #d97706); border-radius: 4px; }
    .source-count { width: 50px; text-align: right; font-weight: 600; font-size: 0.82rem; color: #f59e0b; }
    .source-avg { width: 60px; text-align: right; font-size: 0.72rem; color: #888; }
    .no-data { text-align: center; padding: 60px 20px; color: #666; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <a href="/" class="back-link">&larr; Back to Ecosystem</a>
      <h1>Source Analysis</h1>
      <p class="header-subtitle">Citation frequency {% if selected_prompt != 'all' %}for {{ selected_prompt }}{% else %}across all prompts{% endif %}</p>
    </div>
    <div class="filter-section">
      <span class="filter-label">Filter by Prompt:</span>
      <div class="prompt-pills">
        <a href="/source-analysis" class="prompt-pill {{ 'active' if selected_prompt == 'all' else '' }}">All</a>
        {% for pid in all_prompts %}
        <a href="/source-analysis?prompt={{ pid }}" class="prompt-pill {{ 'active' if selected_prompt == pid else '' }}" title="{{ prompt_keywords.get(pid, '') }}">{{ pid }}</a>
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
    parser = argparse.ArgumentParser(description="Ecosystem Analysis Web App")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"Starting Ecosystem Analysis Web App on http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)
