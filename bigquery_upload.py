#!/usr/bin/env python3
"""
BigQuery Upload Script

Uploads results data to BigQuery for long-term storage and analysis.
Supports incremental uploads and full re-uploads.

Usage:
    python bigquery_upload.py --project firgun-478006 --dataset ai_evaluations
    python bigquery_upload.py --project firgun-478006 --dataset ai_evaluations --full-reload
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.cloud import bigquery
from google.cloud.exceptions import NotFound


# Schema definitions
RESULTS_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED", description="Unique row ID"),
    bigquery.SchemaField("prompt_id", "STRING", mode="REQUIRED", description="Prompt identifier (P1, VP6, etc.)"),
    bigquery.SchemaField("entity_type", "STRING", mode="REQUIRED", description="company or vc"),
    bigquery.SchemaField("entity_name", "STRING", mode="NULLABLE", description="Company or VC name"),
    bigquery.SchemaField("question", "STRING", mode="NULLABLE", description="The full question asked"),
    bigquery.SchemaField("answer", "STRING", mode="NULLABLE", description="AI response"),
    bigquery.SchemaField("score", "FLOAT64", mode="NULLABLE", description="Extracted numeric score (1-10)"),
    bigquery.SchemaField("model", "STRING", mode="NULLABLE", description="AI model used"),
    bigquery.SchemaField("platform", "STRING", mode="NULLABLE", description="Normalized platform name"),
    bigquery.SchemaField("run_timestamp", "TIMESTAMP", mode="NULLABLE", description="When the prompt was run"),
    bigquery.SchemaField("run_folder", "STRING", mode="NULLABLE", description="Source folder name"),
    bigquery.SchemaField("sources", "JSON", mode="NULLABLE", description="Cited sources as JSON"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED", description="When uploaded to BQ"),
]

RUNS_SCHEMA = [
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED", description="Folder name"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE", description="Run date"),
    bigquery.SchemaField("platform", "STRING", mode="NULLABLE", description="AI platform"),
    bigquery.SchemaField("run_type", "STRING", mode="NULLABLE", description="company, vc, or ecosystem"),
    bigquery.SchemaField("total_prompts", "INT64", mode="NULLABLE", description="Number of prompts in run"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED", description="When uploaded to BQ"),
]


def _normalize_ai_name(model_name: str) -> str:
    """Normalize model name to standard AI platform name."""
    model_lower = model_name.lower()
    if "chatgpt" in model_lower or "gpt" in model_lower:
        return "chatgpt"
    elif "gemini" in model_lower:
        return "gemini"
    elif "perplexity" in model_lower:
        return "perplexity"
    return model_name


def _extract_score(answer: str) -> Optional[float]:
    """Extract first valid score (1-10) from answer text."""
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer)]
    return next((n for n in numbers if n <= 10), None)


def _extract_date_from_folder(folder_name: str) -> Optional[str]:
    """Extract date from folder name."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", folder_name)
    return match.group(1) if match else None


def _get_run_type(folder_name: str) -> str:
    """Determine run type from folder name."""
    if "_vc" in folder_name:
        return "vc"
    elif any(x in folder_name for x in ["_chatgpt", "_gemini", "_perplexity"]):
        return "company"
    return "ecosystem"


def create_dataset_if_not_exists(client: bigquery.Client, dataset_id: str):
    """Create dataset if it doesn't exist."""
    dataset_ref = client.dataset(dataset_id)
    try:
        client.get_dataset(dataset_ref)
        print(f"Dataset {dataset_id} already exists")
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset)
        print(f"Created dataset {dataset_id}")


def create_or_update_table(
    client: bigquery.Client, dataset_id: str, table_id: str, schema: list, force_recreate: bool = False
):
    """Create table with schema, or update schema if table exists."""
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        existing_table = client.get_table(table_ref)
        if force_recreate or not existing_table.schema:
            # Drop and recreate if no schema or force_recreate
            print(f"Recreating table {table_id} (no schema or force_recreate)...")
            client.delete_table(table_ref)
            table = bigquery.Table(table_ref, schema=schema)
            client.create_table(table)
            print(f"Recreated table {table_id}")
        else:
            print(f"Table {table_id} already exists with schema")
    except NotFound:
        table = bigquery.Table(table_ref, schema=schema)
        client.create_table(table)
        print(f"Created table {table_id}")


def get_uploaded_folders(client: bigquery.Client, dataset_id: str) -> set:
    """Get set of already uploaded folder names."""
    query = f"""
        SELECT DISTINCT run_folder
        FROM `{client.project}.{dataset_id}.runs`
    """
    try:
        results = client.query(query).result()
        return {row.run_folder for row in results}
    except NotFound:
        return set()


def load_results_from_folder(folder_path: str) -> list[dict]:
    """Load all JSON results from a folder."""
    folder = Path(folder_path)
    folder_name = folder.name
    run_date = _extract_date_from_folder(folder_name)
    upload_time = datetime.now(timezone.utc).isoformat()

    results = []
    for json_file in folder.glob("*.json"):
        if json_file.name.startswith("."):
            continue

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"  Warning: Could not parse {json_file.name}")
            continue

        prompt_id = data.get("prompt_id", "")
        if not prompt_id:
            continue

        # Determine entity type
        entity_name = data.get("company") or data.get("vc")
        if prompt_id.startswith("VP"):
            entity_type = "vc"
        elif entity_name:
            entity_type = "company"
        else:
            entity_type = "ecosystem"

        answer = data.get("answer", "")
        model = data.get("model", "")

        # Create unique ID
        row_id = f"{folder_name}_{prompt_id}_{entity_name or 'category'}_{model}"
        row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)

        results.append({
            "id": row_id,
            "prompt_id": prompt_id,
            "entity_type": entity_type,
            "entity_name": entity_name,
            "question": data.get("question"),
            "answer": answer,
            "score": _extract_score(answer) if answer else None,
            "model": model,
            "platform": _normalize_ai_name(model),
            "run_timestamp": data.get("timestamp"),
            "run_folder": folder_name,
            "sources": json.dumps(data.get("sources", [])),
            "uploaded_at": upload_time,
        })

    return results


def upload_folder(
    client: bigquery.Client,
    dataset_id: str,
    folder_path: str,
):
    """Upload a single folder's results to BigQuery."""
    folder = Path(folder_path)
    folder_name = folder.name

    print(f"Processing {folder_name}...")

    # Load results
    results = load_results_from_folder(folder_path)
    if not results:
        print(f"  No results found in {folder_name}")
        return

    # Upload results
    results_table = f"{client.project}.{dataset_id}.results"
    errors = client.insert_rows_json(results_table, results)
    if errors:
        print(f"  Errors uploading results: {errors[:3]}")
    else:
        print(f"  Uploaded {len(results)} result rows")

    # Add run metadata
    run_date = _extract_date_from_folder(folder_name)
    run_type = _get_run_type(folder_name)
    platform = None
    if results:
        platform = results[0].get("platform")

    run_row = {
        "run_folder": folder_name,
        "run_date": run_date,
        "platform": platform,
        "run_type": run_type,
        "total_prompts": len(results),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    runs_table = f"{client.project}.{dataset_id}.runs"
    errors = client.insert_rows_json(runs_table, [run_row])
    if errors:
        print(f"  Errors uploading run metadata: {errors}")


def upload_all(
    project_id: str,
    dataset_id: str,
    results_dir: str = "results",
    full_reload: bool = False,
):
    """Upload all results to BigQuery."""
    client = bigquery.Client(project=project_id)

    # Create dataset and tables
    create_dataset_if_not_exists(client, dataset_id)
    create_or_update_table(client, dataset_id, "results", RESULTS_SCHEMA)
    create_or_update_table(client, dataset_id, "runs", RUNS_SCHEMA)

    # Get already uploaded folders
    if full_reload:
        uploaded = set()
        # Truncate tables for full reload
        print("Full reload requested - truncating tables...")
        client.query(f"TRUNCATE TABLE `{project_id}.{dataset_id}.results`").result()
        client.query(f"TRUNCATE TABLE `{project_id}.{dataset_id}.runs`").result()
    else:
        uploaded = get_uploaded_folders(client, dataset_id)
        print(f"Found {len(uploaded)} already uploaded folders")

    # Find all result folders
    results_path = Path(results_dir)
    folders = [
        d for d in results_path.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "analysis_results"
    ]

    # Upload new folders
    new_count = 0
    for folder in sorted(folders, key=lambda x: x.name):
        if folder.name in uploaded:
            continue

        upload_folder(client, dataset_id, str(folder))
        new_count += 1

    print(f"\nDone! Uploaded {new_count} new folders")

    # Print summary
    query = f"""
        SELECT
            run_type,
            COUNT(*) as runs,
            SUM(total_prompts) as total_prompts
        FROM `{project_id}.{dataset_id}.runs`
        GROUP BY run_type
    """
    print("\nSummary:")
    for row in client.query(query).result():
        print(f"  {row.run_type}: {row.runs} runs, {row.total_prompts} prompts")


def main():
    parser = argparse.ArgumentParser(description="Upload results to BigQuery")
    parser.add_argument(
        "--project", "-p",
        default="firgun-478006",
        help="GCP project ID"
    )
    parser.add_argument(
        "--dataset", "-d",
        default="ai_evaluations",
        help="BigQuery dataset name"
    )
    parser.add_argument(
        "--results-dir", "-r",
        default="results",
        help="Path to results directory"
    )
    parser.add_argument(
        "--full-reload",
        action="store_true",
        help="Truncate and reload all data"
    )

    args = parser.parse_args()

    print(f"Uploading to {args.project}.{args.dataset}")
    print(f"Results directory: {args.results_dir}")

    upload_all(
        project_id=args.project,
        dataset_id=args.dataset,
        results_dir=args.results_dir,
        full_reload=args.full_reload,
    )


if __name__ == "__main__":
    main()
