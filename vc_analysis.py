import os
import json
import re
from html import escape
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime


def _normalize_ai_name(model_name):
    """Normalize model name to standard AI platform name."""
    model_lower = model_name.lower()
    if "chatgpt" in model_lower:
        return "chatgpt"
    elif "gemini" in model_lower:
        return "gemini"
    elif "perplexity" in model_lower:
        return "perplexity"
    return model_name


def extract_vc_results_from_folder(folder_path, skip_existing=True):
    """Extract VC evaluation results from a folder. Reads VP6-VP20 JSON files."""
    # Peek at first JSON to determine output filename for skip check
    sample_file = None
    for i in range(6, 21):
        prompt_id = f"VP{i}"
        matching = [f for f in os.listdir(folder_path) if f.endswith(".json") and prompt_id in f]
        if matching:
            sample_file = os.path.join(folder_path, matching[0])
            break

    if sample_file:
        with open(sample_file, "r", encoding="utf-8") as f:
            sample_data = json.load(f)
        vc_name = sample_data.get("vc")
        timestamp = sample_data.get("timestamp")
        date_str = (
            datetime.fromisoformat(timestamp.replace("Z", "")).date().isoformat()
            if timestamp else None
        )
        model = sample_data.get("model", "")
        ai_platform = _normalize_ai_name(model)

        output_file = f"results/analysis_results/vc_results/results_{vc_name}_{date_str}_{ai_platform}.csv"
        if skip_existing and os.path.exists(output_file):
            print(f"Skipping {folder_path} - output already exists: {output_file}")
            return pd.read_csv(output_file), output_file

    rows = []

    for i in range(6, 21):
        prompt_id = f"VP{i}"

        matching_files = [
            f for f in os.listdir(folder_path)
            if f.endswith(".json") and prompt_id in f
        ]

        for file_name in matching_files:
            file_path = os.path.join(folder_path, file_name)

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            answer_text = data.get("answer", "")

            # Extract first number that is <= 10 (valid score)
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer_text)]
            result = next((n for n in numbers if n <= 10), None)

            timestamp = data.get("timestamp")
            date = (
                datetime.fromisoformat(timestamp.replace("Z", ""))
                .date()
                .isoformat()
                if timestamp else None
            )

            # Extract AI platform from model field
            model = data.get("model", "")
            ai_platform = _normalize_ai_name(model)

            rows.append({
                "vc": data.get("vc"),
                "prompt_id": data.get("prompt_id"),
                "date": date,
                "AI": ai_platform,
                "result": result
            })

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("No matching VC data found.")

    vc_name = df["vc"].iloc[0]
    date_str = df["date"].iloc[0]
    ai_platform = df["AI"].iloc[0]

    os.makedirs("results/analysis_results/vc_results", exist_ok=True)
    output_file = f"results/analysis_results/vc_results/results_{vc_name}_{date_str}_{ai_platform}.csv"
    df.to_csv(output_file, index=False)

    return df, output_file


def extract_vc_results_from_multiple_folders(
    gemini_folder, perplexity_folder, chatgpt_folder, skip_existing=True
):
    """Extract VC results from all three AI platform folders and combine them."""
    all_dfs = []

    for folder in [gemini_folder, perplexity_folder, chatgpt_folder]:
        if folder and os.path.exists(folder):
            df, _ = extract_vc_results_from_folder(folder, skip_existing=skip_existing)
            all_dfs.append(df)

    if not all_dfs:
        raise ValueError("No valid VC folders provided.")

    combined_df = pd.concat(all_dfs, ignore_index=True)

    vc_name = combined_df["vc"].iloc[0]
    date_str = combined_df["date"].iloc[0]

    os.makedirs("results/analysis_results/vc_results", exist_ok=True)
    output_file = f"results/analysis_results/vc_results/results_{vc_name}_{date_str}_combined.csv"
    combined_df.to_csv(output_file, index=False)

    return combined_df, output_file


AI_WEIGHTS = {
    "chatgpt": 0.5,
    "gemini": 0.3,
    "perplexity": 0.2
}

# Dimension weights from VC_Side.html scorecard
VC_DIMENSION_WEIGHTS = {
    "Technical & Domain Credibility": 0.25,
    "Time Horizon & Fund Construction Fit": 0.25,
    "Platform Value Beyond Capital": 0.20,
    "Signaling & Narrative Discipline": 0.15,
    "Risk Tolerance & Governance Style": 0.15,
}

# Knockout dimensions: below threshold = automatic disqualification
VC_KNOCKOUT_DIMENSIONS = [
    "Technical & Domain Credibility",
    "Time Horizon & Fund Construction Fit",
]

VC_KNOCKOUT_THRESHOLD = 4.0

ANALYSIS_OUTPUT_DIR = "results/analysis_results"

AI_PLATFORMS = ["chatgpt", "gemini", "perplexity"]


VC_CATEGORIES = [
    {
        "analysis_key": "Technical & Domain Credibility",
        "prompts": ["VP6", "VP7", "VP8"],
        "prompt_labels": {
            "VP6": "Deep-tech investment track record",
            "VP7": "Technical expertise of partners",
            "VP8": "Understanding of real bottlenecks",
        },
    },
    {
        "analysis_key": "Time Horizon & Fund Construction Fit",
        "prompts": ["VP9", "VP10", "VP11"],
        "prompt_labels": {
            "VP9": "Fund structure & timeline compatibility",
            "VP10": "Follow-on capacity through later rounds",
            "VP11": "LP base patience & capital type",
        },
    },
    {
        "analysis_key": "Platform Value Beyond Capital",
        "prompts": ["VP12", "VP13", "VP14"],
        "prompt_labels": {
            "VP12": "Talent pipeline access",
            "VP13": "Strategic partner relationships",
            "VP14": "Non-dilutive capital track record",
        },
    },
    {
        "analysis_key": "Signaling & Narrative Discipline",
        "prompts": ["VP15", "VP16", "VP17"],
        "prompt_labels": {
            "VP15": "Narrative credibility & restraint",
            "VP16": "Trust by later-stage investors & strategics",
            "VP17": "Resistance to hype & premature claims",
        },
    },
    {
        "analysis_key": "Risk Tolerance & Governance Style",
        "prompts": ["VP18", "VP19", "VP20"],
        "prompt_labels": {
            "VP18": "Patience with technical setbacks",
            "VP19": "Support for strategic pivots",
            "VP20": "Constructive behavior in down rounds",
        },
    },
]

_VC_PERCEPTION_RISKS = {
    "Technical & Domain Credibility":
        "The VC may appear generalist rather than deep-tech native, "
        "lacking the domain fluency needed for quantum due diligence.",
    "Time Horizon & Fund Construction Fit":
        "The fund structure may not support the extended timelines "
        "quantum companies require, creating misaligned expectations.",
    "Platform Value Beyond Capital":
        "The VC may offer financial support but lack the strategic "
        "network needed to accelerate a quantum company.",
    "Signaling & Narrative Discipline":
        "The VC's signaling may attract attention but not the right "
        "kind \u2014 overhype erodes credibility with serious buyers.",
    "Risk Tolerance & Governance Style":
        "The VC may push for premature commercialization when patience "
        "and technical pivots are what the company needs.",
}


def generate_vc_analysis_from_results_csv(results_csv_path, skip_existing=True):
    """Generate VC analysis from a single AI platform's results CSV."""
    df = pd.read_csv(results_csv_path)

    required_prompts = {f"VP{i}" for i in range(6, 21)}
    if not required_prompts.issubset(set(df["prompt_id"])):
        raise ValueError("Missing required VC prompt IDs in results CSV.")

    vc_name = df["vc"].iloc[0]
    date_str = df["date"].iloc[0]
    ai_platform = df["AI"].iloc[0] if "AI" in df.columns else "unknown"

    os.makedirs(ANALYSIS_OUTPUT_DIR, exist_ok=True)
    output_file = f"{ANALYSIS_OUTPUT_DIR}/vc_results/{vc_name}_{date_str}_{ai_platform}_analysis.csv"
    if skip_existing and os.path.exists(output_file):
        print(f"Skipping VC analysis - output already exists: {output_file}")
        return pd.read_csv(output_file), output_file

    def get_result(pid):
        return float(df.loc[df["prompt_id"] == pid, "result"].iloc[0])

    analysis_rows = []

    for cat in VC_CATEGORIES:
        cat_key = cat["analysis_key"]
        prompt_scores = [get_result(pid) for pid in cat["prompts"]]
        cat_score = sum(prompt_scores) / len(prompt_scores)

        analysis_rows.append({
            "vc": vc_name,
            "AI": ai_platform,
            "Prompt ID": "\u2013".join(cat["prompts"]),
            "category": cat_key,
            "score": cat_score
        })

    analysis_df = pd.DataFrame(analysis_rows)
    analysis_df.to_csv(output_file, index=False)

    return analysis_df, output_file


def generate_vc_weighted_analysis_from_combined_csv(combined_csv_path, skip_existing=True):
    """
    Generate weighted VC analysis from a combined results CSV containing
    results from multiple AI platforms.
    Weights: ChatGPT=0.5, Gemini=0.3, Perplexity=0.2
    """
    df = pd.read_csv(combined_csv_path)

    required_prompts = {f"VP{i}" for i in range(6, 21)}
    if not required_prompts.issubset(set(df["prompt_id"])):
        raise ValueError("Missing required VC prompt IDs in results CSV.")

    if "AI" not in df.columns:
        raise ValueError("Combined CSV must contain 'AI' column.")

    vc_name = df["vc"].iloc[0]
    date_str = df["date"].iloc[0]

    os.makedirs(f"{ANALYSIS_OUTPUT_DIR}/vc_results", exist_ok=True)
    output_file = f"{ANALYSIS_OUTPUT_DIR}/vc_results/{vc_name}_{date_str}_weighted_analysis.csv"
    if skip_existing and os.path.exists(output_file):
        print(f"Skipping VC weighted analysis - output already exists: {output_file}")
        return pd.read_csv(output_file), output_file

    def get_weighted_result(pid):
        prompt_df = df[df["prompt_id"] == pid]
        weighted_sum = 0.0
        total_weight = 0.0

        for ai_platform, weight in AI_WEIGHTS.items():
            ai_rows = prompt_df[prompt_df["AI"] == ai_platform]
            if not ai_rows.empty:
                result = float(ai_rows["result"].iloc[0])
                weighted_sum += result * weight
                total_weight += weight

        if total_weight == 0:
            raise ValueError(f"No results found for prompt {pid}")

        return weighted_sum / total_weight

    analysis_rows = []

    for cat in VC_CATEGORIES:
        cat_key = cat["analysis_key"]
        prompt_scores = [get_weighted_result(pid) for pid in cat["prompts"]]
        cat_score = sum(prompt_scores) / len(prompt_scores)

        analysis_rows.append({
            "vc": vc_name,
            "AI": "weighted_combined",
            "Prompt ID": "\u2013".join(cat["prompts"]),
            "category": cat_key,
            "score": cat_score
        })

    analysis_df = pd.DataFrame(analysis_rows)
    analysis_df.to_csv(output_file, index=False)

    return analysis_df, output_file


def _weighted_prompt_score(prompt_id, platform_scores):
    """Compute weighted average for one prompt across AI platforms."""
    pairs = []
    for ai in AI_PLATFORMS:
        val = platform_scores.get((ai, prompt_id))
        if val is not None:
            pairs.append((val, AI_WEIGHTS[ai]))
    if not pairs:
        return None
    return sum(v * w for v, w in pairs) / sum(w for _, w in pairs)


def _signal_level(score):
    if score is None:
        return "not surfaced"
    if score >= 7.5:
        return "strong"
    if score >= 5:
        return "moderate"
    return "weak"


def create_vc_spider_chart_from_analysis_csv(analysis_csv_path):
    df = pd.read_csv(analysis_csv_path)

    if not {"vc", "category", "score"}.issubset(df.columns):
        raise ValueError("CSV must contain vc, category, and score columns.")

    vc_name = df["vc"].iloc[0]
    ai_platform = df["AI"].iloc[0] if "AI" in df.columns else ""

    categories = df["category"].tolist()
    scores = df["score"].astype(float).tolist()

    num_vars = len(categories)

    if num_vars < 3:
        raise ValueError("Spider chart requires at least 3 categories.")

    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()

    angles += angles[:1]
    scores += scores[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    ax.plot(angles, scores, linewidth=2)
    ax.fill(angles, scores, alpha=0.25)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, size=9)

    ax.set_ylim(0, 10)
    ax.set_yticklabels([])

    title = f"VC Scorecard: {vc_name} ({ai_platform})" if ai_platform else f"VC Scorecard: {vc_name}"
    ax.set_title(title, fontsize=14, pad=20)

    ax.xaxis.grid(True)
    ax.yaxis.grid(True)

    plt.tight_layout()

    chart_path = analysis_csv_path.replace(".csv", "_spider.png")
    fig.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Spider chart saved to {chart_path}")
    return chart_path


def generate_vc_memo_html(
    analysis_df, combined_df,
    gemini_folder, perplexity_folder, chatgpt_folder,
):
    """Generate an HTML memo report for VC evaluation."""
    vc = str(analysis_df["vc"].iloc[0])
    date_raw = str(
        combined_df["date"].iloc[0]
        if "date" in combined_df.columns else ""
    )
    date_iso = date_raw

    try:
        dt = datetime.fromisoformat(date_raw)
        date_display = dt.strftime("%B %Y")
    except (ValueError, TypeError):
        date_display = date_raw or "N/A"

    # Scores from analysis_df (already weighted)
    scores = {}
    for _, row in analysis_df.iterrows():
        scores[row["category"]] = round(float(row["score"]), 1)

    # Weighted composite using dimension weights
    weighted_composite = sum(
        scores.get(dim, 0) * w
        for dim, w in VC_DIMENSION_WEIGHTS.items()
    )
    composite = round(weighted_composite, 1) if scores else 0

    # Knockout check
    knockout_flags = []
    for dim in VC_KNOCKOUT_DIMENSIONS:
        dim_score = scores.get(dim)
        if dim_score is not None and dim_score < VC_KNOCKOUT_THRESHOLD:
            knockout_flags.append(dim)

    # Per-platform prompt scores from combined_df
    platform_scores = {}
    for _, row in combined_df.iterrows():
        platform_scores[(row["AI"], row["prompt_id"])] = row["result"]

    # Identify weakest categories
    sorted_cats = sorted(scores.items(), key=lambda x: x[1])
    weak_cats = [name for name, s in sorted_cats if s < 7]
    strongest = sorted_cats[-1][0] if sorted_cats else ""

    # Executive-summary gap bullets
    gap_bullets = "\n".join(
        f"        <li>{escape(name)} ({s} / 10)</li>"
        for name, s in sorted_cats[:3] if s < 8
    )

    # Knockout warning HTML
    knockout_html = ""
    if knockout_flags:
        knockout_dims = ", ".join(escape(d) for d in knockout_flags)
        knockout_html = f"""
    <div class="knockout-warning">
      <h3>Knockout Warning</h3>
      <p>
        This VC scores below the minimum threshold ({VC_KNOCKOUT_THRESHOLD} / 10)
        in: <strong>{knockout_dims}</strong>.
        Per the VC scorecard framework, any investor below threshold in
        Technical Credibility or Time Horizon is disqualified regardless of
        strength in other areas.
      </p>
    </div>
"""

    # Category sections
    category_sections = []
    missing_items = []
    priority_items = []

    for idx, cat in enumerate(VC_CATEGORIES, 1):
        cat_key = cat["analysis_key"]
        cat_score = scores.get(cat_key)
        dim_weight = VC_DIMENSION_WEIGHTS.get(cat_key, 0)
        weight_pct = int(dim_weight * 100)
        score_str = (
            f"{cat_score} / 10" if cat_score is not None else "N/A"
        )

        # Per-dimension signal bullets
        dim_bullets = []
        for pid in cat["prompts"]:
            dim_score = _weighted_prompt_score(pid, platform_scores)
            label = cat["prompt_labels"][pid]
            level = _signal_level(dim_score)
            dim_bullets.append(f"{label} ({level} signal)")
            if dim_score is not None and dim_score < 5:
                missing_items.append(label)

        bullets_html = "\n".join(
            f"        <li>{escape(b)}</li>" for b in dim_bullets
        )

        risk_text = _VC_PERCEPTION_RISKS.get(cat_key, "")

        if cat_score is not None and cat_score < 6:
            priority_items.append(cat_key)

        section = f"""    <section>
      <h2>{idx}. {escape(cat_key)} <span class="weight-badge">{weight_pct}%</span></h2>
      <p class="score">Score: {score_str}</p>

      <ul>
{bullets_html}
      </ul>

      <p class="perception-risk">
        <strong>Perception risk:</strong> {escape(risk_text)}
      </p>
    </section>

    <div class="divider"></div>
"""
        category_sections.append(section)

    # What the AI is likely missing
    if not missing_items:
        missing_items = [
            cat["prompt_labels"][pid]
            for cat in VC_CATEGORIES
            for pid in cat["prompts"]
            if (_weighted_prompt_score(pid, platform_scores) or 10) < 7
        ][:4]
    missing_bullets = "\n".join(
        f"        <li>{escape(m)}</li>" for m in missing_items[:5]
    )

    # What matters most
    if not priority_items:
        priority_items = [name for name, _ in sorted_cats[:2]]
    priority_bullets = "\n".join(
        f"        <li>{escape(p)}</li>" for p in priority_items[:4]
    )

    # Build full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VC Evaluation Memo &mdash; {escape(vc)}</title>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:\
ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:\
wght@400;500;600&display=swap" rel="stylesheet">

  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html {{ font-size: 18px; scroll-behavior: smooth; }}
    body {{
      font-family: 'EB Garamond', Georgia, serif;
      background: #fafafa; color: #1a1a1a;
      line-height: 1.7;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    .container {{
      max-width: 680px; margin: 0 auto;
      padding: 80px 24px 160px;
    }}
    .memo-header {{
      margin-bottom: 64px; padding-bottom: 48px;
      border-bottom: 1px solid #e0e0e0;
    }}
    .memo-label {{
      font-family: 'Inter', sans-serif;
      font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.12em; text-transform: uppercase;
      color: #888; margin-bottom: 24px;
    }}
    .memo-title {{
      font-size: 2.4rem; font-weight: 500;
      line-height: 1.2; margin-bottom: 32px;
      letter-spacing: -0.02em;
    }}
    .memo-meta {{
      font-family: 'Inter', sans-serif;
      font-size: 0.78rem; color: #666; line-height: 1.9;
    }}
    .memo-meta span {{ display: block; }}
    .memo-meta strong {{ font-weight: 500; color: #1a1a1a; }}
    section {{ margin-bottom: 56px; }}
    h2 {{
      font-size: 1.5rem; font-weight: 500;
      margin-bottom: 24px; letter-spacing: -0.01em;
    }}
    p {{ margin-bottom: 20px; color: #333; }}
    .composite-score {{
      font-family: 'Inter', sans-serif;
      font-size: 1rem; font-weight: 600; margin-bottom: 8px;
    }}
    .score-context {{
      font-family: 'Inter', sans-serif;
      font-size: 0.75rem; color: #666; margin-bottom: 24px;
    }}
    .score {{
      font-family: 'Inter', sans-serif;
      font-size: 0.85rem; font-weight: 600;
      padding: 12px 0;
      border-top: 1px solid #e8e8e8;
      border-bottom: 1px solid #e8e8e8;
      margin-bottom: 20px;
    }}
    .weight-badge {{
      font-family: 'Inter', sans-serif;
      font-size: 0.65rem; font-weight: 500;
      color: #888; vertical-align: middle;
      margin-left: 8px;
    }}
    ul {{
      list-style: none; margin: 24px 0; padding-left: 0;
    }}
    li {{
      position: relative; padding-left: 20px;
      margin-bottom: 12px;
    }}
    li::before {{
      content: ""; position: absolute;
      left: 0; top: 11px;
      width: 4px; height: 4px;
      background: #999; border-radius: 50%;
    }}
    .perception-risk {{
      font-style: italic; color: #555;
      margin-top: 24px; padding-left: 20px;
      border-left: 2px solid #ddd;
    }}
    .divider {{
      height: 1px; background: #e0e0e0; margin: 56px 0;
    }}
    .knockout-warning {{
      background: #fff3f3; border: 1px solid #e8c0c0;
      padding: 24px 32px; margin: 32px 0;
      border-radius: 4px;
    }}
    .knockout-warning h3 {{
      font-family: 'Inter', sans-serif;
      font-size: 0.85rem; font-weight: 600;
      color: #a33; margin-bottom: 12px;
      text-transform: uppercase; letter-spacing: 0.05em;
    }}
    .knockout-warning p {{
      color: #555; margin-bottom: 0;
    }}
    .strategic-implication {{
      background: #f5f5f5; padding: 32px;
      margin-top: 48px; border-radius: 4px;
    }}
    .scorecard-table {{
      width: 100%; border-collapse: collapse;
      margin: 24px 0; font-family: 'Inter', sans-serif;
      font-size: 0.8rem;
    }}
    .scorecard-table th, .scorecard-table td {{
      text-align: left; padding: 10px 12px;
      border-bottom: 1px solid #e8e8e8;
    }}
    .scorecard-table th {{
      font-weight: 600; color: #666;
      text-transform: uppercase; font-size: 0.7rem;
      letter-spacing: 0.05em;
    }}
    .scorecard-table td:last-child {{
      text-align: right; font-weight: 600;
    }}
    .memo-footer {{
      margin-top: 80px; padding-top: 32px;
      border-top: 1px solid #e0e0e0;
      font-family: 'Inter', sans-serif;
      font-size: 0.72rem; color: #999;
      text-align: center; line-height: 1.6;
    }}
    @media (max-width: 600px) {{
      html {{ font-size: 16px; }}
      .memo-title {{ font-size: 1.9rem; }}
      .container {{ padding: 48px 20px 120px; }}
    }}
  </style>
</head>

<body>
  <article class="container">

    <header class="memo-header">
      <p class="memo-label">VC Evaluation Memo &mdash; Quantum Investor Scorecard</p>
      <h1 class="memo-title">{escape(vc)}</h1>
      <div class="memo-meta">
        <span><strong>Date:</strong> {escape(date_display)}</span>
        <span><strong>Scope:</strong> Public information only</span>
        <span><strong>Framework:</strong> 5-dimension VC scorecard for quantum companies</span>
      </div>
    </header>

    <section>
      <h2>Executive Summary</h2>
      <p class="composite-score">\
Weighted Composite Score: {composite} / 10</p>
      <p class="score-context">
        This score reflects how AI systems perceive this VC&rsquo;s suitability \
as an investor for quantum deep-tech companies, based on publicly available information. \
Dimensions are weighted: Technical Credibility (25%), Time Horizon (25%), \
Platform Value (20%), Signaling (15%), Governance (15%).
      </p>
{knockout_html}
      <p>
        Based on publicly available information, {escape(vc)} \
is perceived as {'a credible deep-tech investor' if composite >= 6 else 'a potentially misaligned investor for quantum'}\
{f' with relative strength in {escape(strongest)}' if strongest else ''}. \
The areas requiring closest scrutiny are:
      </p>
      <ul>
{gap_bullets}
      </ul>

      <table class="scorecard-table">
        <thead>
          <tr><th>Dimension</th><th>Weight</th><th>Score</th></tr>
        </thead>
        <tbody>
"""

    for cat in VC_CATEGORIES:
        cat_key = cat["analysis_key"]
        dim_weight = VC_DIMENSION_WEIGHTS.get(cat_key, 0)
        cat_score = scores.get(cat_key)
        score_str = f"{cat_score}" if cat_score is not None else "N/A"
        html += f"""          <tr>
            <td>{escape(cat_key)}</td>
            <td>{int(dim_weight * 100)}%</td>
            <td>{score_str}</td>
          </tr>
"""

    html += f"""        </tbody>
      </table>
    </section>

    <div class="divider"></div>

{''.join(category_sections)}
    <section>
      <h2>What the AI Is Likely Missing</h2>
      <ul>
{missing_bullets}
      </ul>
      <p>
        AI models assess VCs based on public signals: press coverage, portfolio \
announcements, partner bios, and fund filings. Private dynamics \
&mdash; LP relationships, board behavior, founder references &mdash; \
are largely invisible and must be verified through direct diligence.
      </p>
    </section>

    <section>
      <h2>Key Questions to Ask This VC</h2>
      <ul>
        <li>&ldquo;What is the longest time to liquidity you have supported?&rdquo;</li>
        <li>&ldquo;How do you think about markups when milestones are scientific, not revenue-based?&rdquo;</li>
        <li>&ldquo;Who would you introduce us to in the first 30 days?&rdquo;</li>
        <li>&ldquo;Have you shut down a company too early before &mdash; and why?&rdquo;</li>
        <li>&ldquo;Were you constructive during down rounds or extensions?&rdquo;</li>
      </ul>
      <p>
        These questions surface information that AI cannot assess from public data.
      </p>
    </section>

    <section>
      <h2>Priority Areas for Further Diligence</h2>
      <p>
        Improving confidence in a small number of areas would have \
an outsized impact on whether this VC is the right partner \
for a quantum company.
      </p>
      <ul>
{priority_bullets}
      </ul>
      <p>
        These are prioritization signals, not recommendations.
      </p>
    </section>

    <div class="strategic-implication">
      <h2>Strategic Implication</h2>
      <p>
        {'If ' + escape(vc) + ' scores below threshold in Technical Credibility or Time Horizon, they should be excluded regardless of brand strength. ' if knockout_flags else ''}\
Based on public signals, {escape(vc)} \
{'appears to be a strong candidate for quantum investment partnership' if composite >= 7 else 'warrants careful diligence before being selected as a quantum investor' if composite >= 5 else 'presents significant alignment risks for a quantum company'}. \
Direct founder references and LP diligence are essential to validate these AI-derived signals.
      </p>
    </div>

    <footer class="memo-footer">
      This memo reflects AI-based perception as of \
{escape(date_display)}, derived solely from public information.<br>
      It is intended to support VC selection strategy, \
not to replace direct investor diligence.
    </footer>

  </article>
</body>
</html>"""

    os.makedirs(f"{ANALYSIS_OUTPUT_DIR}/vc_results", exist_ok=True)
    output_file = (
        f"{ANALYSIS_OUTPUT_DIR}/vc_results/{vc}_{date_iso}_memo.html"
    )
    with open(output_file, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"VC Memo saved to {output_file}")
    return output_file


def find_latest_vc_folder(platform_suffix, results_dir="results"):
    """Find the most recent results folder for a given VC platform suffix.

    Looks for folders ending with e.g. '_chatgpt_vc', '_gemini_vc', '_perplexity_vc'
    and returns the one with the latest timestamp.
    """
    results_path = Path(results_dir)
    if not results_path.exists():
        return None
    matching = sorted(
        [d for d in results_path.iterdir() if d.is_dir() and d.name.endswith(f"_{platform_suffix}")],
        key=lambda d: d.name,
        reverse=True,
    )
    return str(matching[0]) if matching else None


if __name__ == "__main__":
    gemini_folder = find_latest_vc_folder("gemini_vc")
    perplexity_folder = find_latest_vc_folder("perplexity_vc")
    chatgpt_folder = find_latest_vc_folder("chatgpt_vc")

    print(f"Gemini folder:    {gemini_folder}")
    print(f"Perplexity folder: {perplexity_folder}")
    print(f"ChatGPT folder:   {chatgpt_folder}")

    # 1. Combine results from all platforms
    combined_df, combined_file = extract_vc_results_from_multiple_folders(
        gemini_folder, perplexity_folder, chatgpt_folder
    )
    print(f"Combined results saved to {combined_file}")

    # 2. Generate weighted analysis
    analysis_df, analysis_file = generate_vc_weighted_analysis_from_combined_csv(
        combined_file
    )
    print(f"Weighted analysis saved to {analysis_file}")

    # 3. Generate HTML memo
    generate_vc_memo_html(
        analysis_df, combined_df,
        gemini_folder, perplexity_folder, chatgpt_folder
    )

    # 4. Create spider chart
    create_vc_spider_chart_from_analysis_csv(analysis_file)
