import os
import json
import re
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
        get_result("P18") * 0.66 +
        get_result("P19") * 0.50 +
        get_result("P20") * 0.33
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

    # 4. Create spider chart
    create_spider_chart_from_analysis_csv(analysis_file)
