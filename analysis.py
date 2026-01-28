import os
import json
import re
import pandas as pd
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def extract_results_from_folder(folder_path):
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

            # Extract all numbers in order
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer_text)]

            if not numbers:
                result = None
            elif numbers[0] > 10 and len(numbers) > 1:
                result = numbers[1]
            else:
                result = numbers[0]

            timestamp = data.get("timestamp")
            date = (
                datetime.fromisoformat(timestamp.replace("Z", ""))
                .date()
                .isoformat()
                if timestamp else None
            )

            rows.append({
                "company": data.get("company"),
                "prompt_id": data.get("prompt_id"),
                "date": date,
                "result": result
            })

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("No matching data found.")

    company_name = df["company"].iloc[0]
    date_str = df["date"].iloc[0]

    output_file = f"results_{company_name}_{date_str}.csv"
    df.to_csv(output_file, index=False)

    return df, output_file


def generate_analysis_from_results_csv(results_csv_path):
    df = pd.read_csv(results_csv_path)

    required_prompts = {f"P{i}" for i in range(18, 28)}
    if not required_prompts.issubset(set(df["prompt_id"])):
        raise ValueError("Missing required prompt IDs in results CSV.")

    company_name = df["company"].iloc[0]
    date_str = df["date"].iloc[0]

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
        "Prompt ID": "P18–P20",
        "category": "Team & Ability to Attract Talent",
        "score": team_score
    })

    # 2. Quality of Existing IP
    ip_score = (get_result("P21") + get_result("P22")) / 2
    analysis_rows.append({
        "company": company_name,
        "Prompt ID": "P21–P22",
        "category": "Quality of Existing IP",
        "score": ip_score
    })

    # 3. TRL / Traction
    trl_score = (get_result("P23") + get_result("P24")) / 2
    analysis_rows.append({
        "company": company_name,
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
        "Prompt ID": "P25–P27",
        "category": "Investor Perception",
        "score": investor_score
    })

    analysis_df = pd.DataFrame(analysis_rows)

    output_file = f"results/analysis_results/{company_name}_{date_str}_analysis.csv"
    analysis_df.to_csv(output_file, index=False)

    return analysis_df, output_file



def create_spider_chart_from_analysis_csv(analysis_csv_path):
    df = pd.read_csv(analysis_csv_path)

    # Validation
    if not {"company", "category", "score"}.issubset(df.columns):
        raise ValueError("CSV must contain company, category, and score columns.")

    company_name = df["company"].iloc[0]

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

    # Title
    ax.set_title(company_name, fontsize=14, pad=20)

    ax.xaxis.grid(True)
    ax.yaxis.grid(True)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    #folder_path = "results/2026-01-24_12-13-58"
    #df, output_file = extract_results_from_folder(folder_path)
    #print(f"Results saved to {output_file}")
    #print(df)
    #generate_analysis_from_results_csv("results_Qnami_2026-01-24.csv")
    create_spider_chart_from_analysis_csv('/Users/cedricdeschaut/code/extract_sources/human-prompt-runner/Qnami_2026-01-24_analysis.csv')
