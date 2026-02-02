import os
import json
import re
from html import escape
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


def extract_results_from_folder(folder_path, skip_existing=True):
    """Extract results from a folder. Skips if output file already exists when skip_existing=True."""
    # Peek at first JSON to determine output filename for skip check
    sample_file = None
    for i in range(18, 28):
        prompt_id = f"P{i}"
        matching = [f for f in os.listdir(folder_path) if f.endswith(".json") and prompt_id in f]
        if matching:
            sample_file = os.path.join(folder_path, matching[0])
            break

    if sample_file:
        with open(sample_file, "r", encoding="utf-8") as f:
            sample_data = json.load(f)
        company_name = sample_data.get("company")
        timestamp = sample_data.get("timestamp")
        date_str = (
            datetime.fromisoformat(timestamp.replace("Z", "")).date().isoformat()
            if timestamp else None
        )
        model = sample_data.get("model", "")
        ai_platform = _normalize_ai_name(model)

        output_file = f"results/analysis_results/company_results/results_{company_name}_{date_str}_{ai_platform}.csv"
        if skip_existing and os.path.exists(output_file):
            print(f"Skipping {folder_path} - output already exists: {output_file}")
            return pd.read_csv(output_file), output_file

    rows = []

    for i in range(18, 28):
        prompt_id = f"P{i}"

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
                "company": data.get("company"),
                "prompt_id": data.get("prompt_id"),
                "date": date,
                "AI": ai_platform,
                "result": result
            })

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("No matching data found.")

    company_name = df["company"].iloc[0]
    date_str = df["date"].iloc[0]
    ai_platform = df["AI"].iloc[0]

    output_file = f"results/analysis_results/company_results/results_{company_name}_{date_str}_{ai_platform}.csv"
    df.to_csv(output_file, index=False)

    return df, output_file


def extract_results_from_multiple_folders(
    gemini_folder, perplexity_folder, chatgpt_folder, skip_existing=True
):
    """Extract results from all three AI platform folders and combine them."""
    all_dfs = []

    for folder in [gemini_folder, perplexity_folder, chatgpt_folder]:
        if folder and os.path.exists(folder):
            df, _ = extract_results_from_folder(folder, skip_existing=skip_existing)
            all_dfs.append(df)

    if not all_dfs:
        raise ValueError("No valid folders provided.")

    combined_df = pd.concat(all_dfs, ignore_index=True)

    company_name = combined_df["company"].iloc[0]
    date_str = combined_df["date"].iloc[0]

    output_file = f"results/analysis_results/company_results/results_{company_name}_{date_str}_combined.csv"
    combined_df.to_csv(output_file, index=False)

    return combined_df, output_file


AI_WEIGHTS = {
    "chatgpt": 0.5,
    "gemini": 0.3,
    "perplexity": 0.2
}


ANALYSIS_OUTPUT_DIR = "results/analysis_results"


def generate_analysis_from_results_csv(results_csv_path, skip_existing=True):
    """Generate analysis from a single AI platform's results CSV."""
    df = pd.read_csv(results_csv_path)

    required_prompts = {f"P{i}" for i in range(18, 28)}
    if not required_prompts.issubset(set(df["prompt_id"])):
        raise ValueError("Missing required prompt IDs in results CSV.")

    company_name = df["company"].iloc[0]
    date_str = df["date"].iloc[0]
    ai_platform = df["AI"].iloc[0] if "AI" in df.columns else "unknown"

    # Check if output already exists
    os.makedirs(ANALYSIS_OUTPUT_DIR, exist_ok=True)
    output_file = f"{ANALYSIS_OUTPUT_DIR}/{company_name}_{date_str}_{ai_platform}_analysis.csv"
    if skip_existing and os.path.exists(output_file):
        print(f"Skipping analysis - output already exists: {output_file}")
        return pd.read_csv(output_file), output_file

    # Helper to fetch result by prompt ID
    def get_result(pid):
        return float(df.loc[df["prompt_id"] == pid, "result"].iloc[0])

    analysis_rows = []

    # 1. Team & Ability to Attract Talent
    team_score = (
        get_result("P18") * 0.5 +
        get_result("P19") * 0.33 +
        get_result("P20") * 0.17
    )
    analysis_rows.append({
        "company": company_name,
        "AI": ai_platform,
        "Prompt ID": "P18–P20",
        "category": "Team & Ability to Attract Talent",
        "score": team_score
    })

    # 2. Quality of Existing IP
    ip_score = (get_result("P21") + get_result("P22")) / 2
    analysis_rows.append({
        "company": company_name,
        "AI": ai_platform,
        "Prompt ID": "P21–P22",
        "category": "Quality of Existing IP",
        "score": ip_score
    })

    # 3. TRL / Traction
    trl_score = (get_result("P23") + get_result("P24")) / 2
    analysis_rows.append({
        "company": company_name,
        "AI": ai_platform,
        "Prompt ID": "P23–P24",
        "category": "TRL / Traction",
        "score": trl_score
    })

    # 4. Investor Perception
    investor_score = (
        get_result("P25") * 0.50 +
        get_result("P26") * 0.25 +
        get_result("P27") * 0.25
    )
    analysis_rows.append({
        "company": company_name,
        "AI": ai_platform,
        "Prompt ID": "P25–P27",
        "category": "Investor Perception",
        "score": investor_score
    })

    analysis_df = pd.DataFrame(analysis_rows)
    analysis_df.to_csv(output_file, index=False)

    return analysis_df, output_file


def generate_weighted_analysis_from_combined_csv(combined_csv_path, skip_existing=True):
    """
    Generate weighted analysis from a combined results CSV containing
    results from multiple AI platforms.
    Weights: ChatGPT=0.5, Gemini=0.3, Perplexity=0.2
    """
    df = pd.read_csv(combined_csv_path)

    required_prompts = {f"P{i}" for i in range(18, 28)}
    if not required_prompts.issubset(set(df["prompt_id"])):
        raise ValueError("Missing required prompt IDs in results CSV.")

    if "AI" not in df.columns:
        raise ValueError("Combined CSV must contain 'AI' column.")

    company_name = df["company"].iloc[0]
    date_str = df["date"].iloc[0]

    # Check if output already exists
    os.makedirs(ANALYSIS_OUTPUT_DIR, exist_ok=True)
    output_file = f"results/analysis_results/company_results/{company_name}_{date_str}_weighted_analysis.csv"
    if skip_existing and os.path.exists(output_file):
        print(f"Skipping weighted analysis - output already exists: {output_file}")
        return pd.read_csv(output_file), output_file

    # Helper to get weighted result by prompt ID across all AI platforms
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

    # 1. Team & Ability to Attract Talent
    team_score = (
        get_weighted_result("P18") * 0.66 +
        get_weighted_result("P19") * 0.50 +
        get_weighted_result("P20") * 0.33
    )
    analysis_rows.append({
        "company": company_name,
        "AI": "weighted_combined",
        "Prompt ID": "P18–P20",
        "category": "Team & Ability to Attract Talent",
        "score": team_score
    })

    # 2. Quality of Existing IP
    ip_score = (get_weighted_result("P21") + get_weighted_result("P22")) / 2
    analysis_rows.append({
        "company": company_name,
        "AI": "weighted_combined",
        "Prompt ID": "P21–P22",
        "category": "Quality of Existing IP",
        "score": ip_score
    })

    # 3. TRL / Traction
    trl_score = (get_weighted_result("P23") + get_weighted_result("P24")) / 2
    analysis_rows.append({
        "company": company_name,
        "AI": "weighted_combined",
        "Prompt ID": "P23–P24",
        "category": "TRL / Traction",
        "score": trl_score
    })

    # 4. Investor Perception
    investor_score = (
        get_weighted_result("P25") * 0.50 +
        get_weighted_result("P26") * 0.25 +
        get_weighted_result("P27") * 0.25
    )
    analysis_rows.append({
        "company": company_name,
        "AI": "weighted_combined",
        "Prompt ID": "P25–P27",
        "category": "Investor Perception",
        "score": investor_score
    })

    analysis_df = pd.DataFrame(analysis_rows)
    analysis_df.to_csv(output_file, index=False)

    return analysis_df, output_file



def create_spider_chart_from_analysis_csv(analysis_csv_path):
    df = pd.read_csv(analysis_csv_path)

    # Validation
    if not {"company", "category", "score"}.issubset(df.columns):
        raise ValueError("CSV must contain company, category, and score columns.")

    company_name = df["company"].iloc[0]
    ai_platform = df["AI"].iloc[0] if "AI" in df.columns else ""

    categories = df["category"].tolist()
    scores = df["score"].astype(float).tolist()

    num_vars = len(categories)

    if num_vars < 3:
        raise ValueError("Spider chart requires at least 3 categories.")

    # Angles
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()

    # Close the loop
    angles += angles[:1]
    scores += scores[:1]

    # Plot
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    ax.plot(angles, scores, linewidth=2)
    ax.fill(angles, scores, alpha=0.25)

    # Category labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories)

    # Radial axis: always 0–10
    ax.set_ylim(0, 10)

    # Remove radial value labels (keep grid lines)
    ax.set_yticklabels([])

    # Title with AI platform
    title = f"{company_name} ({ai_platform})" if ai_platform else company_name
    ax.set_title(title, fontsize=14, pad=20)

    ax.xaxis.grid(True)
    ax.yaxis.grid(True)

    plt.tight_layout()
    plt.show()


CATEGORIES = [
    {
        "analysis_key": "Team & Ability to Attract Talent",
        "prompts": ["P18", "P19", "P20"],
        "prompt_labels": {
            "P18": "Academic strength & h-index",
            "P19": "Ecosystem & talent attraction",
            "P20": "Execution capability",
        },
    },
    {
        "analysis_key": "Quality of Existing IP",
        "prompts": ["P21", "P22"],
        "prompt_labels": {
            "P21": "Patent quality & quantity",
            "P22": "IP uniqueness & leadership in approach",
        },
    },
    {
        "analysis_key": "TRL / Traction",
        "prompts": ["P23", "P24"],
        "prompt_labels": {
            "P23": "Product readiness vs. competitors",
            "P24": "Sales performance & partnerships",
        },
    },
    {
        "analysis_key": "Investor Perception",
        "prompts": ["P25", "P26", "P27"],
        "prompt_labels": {
            "P25": "Quality of VCs on cap table",
            "P26": "10x growth potential",
            "P27": "Investor reinvestment likelihood",
        },
    },
]

AI_PLATFORMS = ["chatgpt", "gemini", "perplexity"]

# Perception-risk templates keyed by category analysis_key
_PERCEPTION_RISKS = {
    "Team & Ability to Attract Talent":
        "The team may appear research-heavy rather than execution-ready.",
    "Quality of Existing IP":
        "IP may exist, but leadership in approach is not clearly established.",
    "TRL / Traction":
        "Progress may be real, but it is not legible.",
    "Investor Perception":
        "Fundraising momentum appears ambiguous.",
}


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


def generate_memo_html(
    analysis_df, combined_df,
    gemini_folder, perplexity_folder, chatgpt_folder,
):
    """Generate an HTML memo report matching sample_index.html structure."""
    company = str(analysis_df["company"].iloc[0])
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
    composite = (
        round(sum(scores.values()) / len(scores), 1) if scores else 0
    )

    # Per-platform prompt scores from combined_df
    platform_scores = {}
    for _, row in combined_df.iterrows():
        platform_scores[(row["AI"], row["prompt_id"])] = row["result"]

    # ── Identify weakest categories for summary & closing sections ───
    sorted_cats = sorted(scores.items(), key=lambda x: x[1])
    weak_cats = [name for name, s in sorted_cats if s < 7]
    strongest = sorted_cats[-1][0] if sorted_cats else ""

    # ── Executive-summary gap bullets ────────────────────────────────
    gap_bullets = "\n".join(
        f"        <li>{escape(name)} ({s} / 10)</li>"
        for name, s in sorted_cats[:3] if s < 8
    )

    # ── Category sections ────────────────────────────────────────────
    category_sections = []
    missing_items = []
    priority_items = []

    for idx, cat in enumerate(CATEGORIES, 1):
        cat_key = cat["analysis_key"]
        cat_score = scores.get(cat_key)
        score_str = (
            f"{cat_score} / 10" if cat_score is not None else "N/A"
        )

        # Per-dimension signal bullets
        dim_bullets = []
        for pid in cat["prompts"]:
            dim_score = _weighted_prompt_score(pid, platform_scores)
            label = cat["prompt_labels"][pid]
            level = _signal_level(dim_score)
            if dim_score is not None and dim_score < 5:
                dim_bullets.append(f"{label} ({level} signal)")
                missing_items.append(label)
            elif dim_score is not None and dim_score < 7:
                dim_bullets.append(
                    f"{label} ({level} signal)"
                )
            else:
                dim_bullets.append(f"{label} ({level} signal)")

        bullets_html = "\n".join(
            f"        <li>{escape(b)}</li>" for b in dim_bullets
        )

        # Perception risk
        risk_text = _PERCEPTION_RISKS.get(cat_key, "")

        # Priority items for "What Matters Most" — take weak ones
        if cat_score is not None and cat_score < 6:
            priority_items.append(cat_key)

        section = f"""    <section>
      <h2>{idx}. {escape(cat_key)}</h2>
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

    # ── What the AI is likely missing ────────────────────────────────
    if not missing_items:
        missing_items = [
            cat["prompt_labels"][pid]
            for cat in CATEGORIES
            for pid in cat["prompts"]
            if (_weighted_prompt_score(pid, platform_scores) or 10) < 7
        ][:4]
    missing_bullets = "\n".join(
        f"        <li>{escape(m)}</li>" for m in missing_items[:5]
    )

    # ── What matters most ────────────────────────────────────────────
    if not priority_items:
        priority_items = [name for name, _ in sorted_cats[:2]]
    priority_bullets = "\n".join(
        f"        <li>{escape(p)}</li>" for p in priority_items[:4]
    )

    # ── Build full HTML ──────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Perception &amp; Investability Memo — {escape(company)}</title>

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
    .strategic-implication {{
      background: #f5f5f5; padding: 32px;
      margin-top: 48px; border-radius: 4px;
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
      <p class="memo-label">AI Perception &amp; Investability Memo</p>
      <h1 class="memo-title">{escape(company)}</h1>
      <div class="memo-meta">
        <span><strong>Date:</strong> {escape(date_display)}</span>
        <span><strong>Scope:</strong> Public information only</span>
      </div>
    </header>

    <section>
      <h2>Executive Summary</h2>
      <p class="composite-score">\
Composite AI Perception Score: {composite} / 10</p>
      <p class="score-context">
        This score reflects how advanced AI systems interpret the \
company&rsquo;s public signals relative to comparable deep-tech startups.
      </p>

      <p>
        Based on publicly available information, {escape(company)} \
is perceived as {'a technically credible' if composite >= 5 else 'an under-signaled'} \
deep-tech company{f' with relative strength in {escape(strongest)}' if strongest else ''}. \
The largest gaps between likely internal quality and external perception are in:
      </p>
      <ul>
{gap_bullets}
      </ul>
      <p>
        These gaps are not necessarily reflective of underlying \
weakness, but they materially affect how the company is interpreted \
by AI-assisted investor research tools.
      </p>
    </section>

    <div class="divider"></div>

{''.join(category_sections)}
    <section>
      <h2>What the AI Is Likely Missing</h2>
      <ul>
{missing_bullets}
      </ul>
      <p>These are <em>signal gaps</em>, not necessarily substance gaps.</p>
    </section>

    <section>
      <h2>What Matters Most for the Next 6&ndash;12 Months</h2>
      <p>
        Improving perception in a small number of areas would have \
an outsized impact on how AI systems &mdash; and therefore \
investors &mdash; interpret the company.
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
        If investors rely heavily on AI-assisted research, \
{escape(company)} risks being filtered as \
{'technically credible but not yet compelling' if composite >= 5 else 'unclear or unconvincing'}, \
despite potentially stronger internal fundamentals.
      </p>
    </div>

    <footer class="memo-footer">
      This memo reflects AI-based perception as of \
{escape(date_display)}, derived solely from public information.<br>
      It is intended to support strategic discussion, \
not to assess internal quality.
    </footer>

  </article>
</body>
</html>"""

    os.makedirs(ANALYSIS_OUTPUT_DIR, exist_ok=True)
    output_file = (
        f"{ANALYSIS_OUTPUT_DIR}/{company}_{date_iso}_memo.html"
    )
    with open(output_file, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"Memo saved to {output_file}")
    return output_file


if __name__ == "__main__":
    # 1. Define AI platform folders
    gemini_folder = "results/2026-01-28_10-35-01_gemini"
    perplexity_folder = "results/2026-01-28_12-07-44_perplexity"
    chatgpt_folder = "results/2026-01-28_12-31-31_chatgpt"

    # 2. Combine results from all platforms (skips existing)
    combined_df, combined_file = extract_results_from_multiple_folders(
        gemini_folder, perplexity_folder, chatgpt_folder
    )
    print(f"Combined results saved to {combined_file}")

    # 3. Generate weighted analysis (ChatGPT=0.5, Gemini=0.3, Perplexity=0.2)
    analysis_df, analysis_file = generate_weighted_analysis_from_combined_csv(
        combined_file
    )
    print(f"Weighted analysis saved to {analysis_file}")

    # 4. Generate HTML memo
    generate_memo_html(
        analysis_df, combined_df,
        gemini_folder, perplexity_folder, chatgpt_folder
    )

    # 5. Create spider chart
    create_spider_chart_from_analysis_csv(analysis_file)
