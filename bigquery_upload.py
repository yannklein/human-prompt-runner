#!/usr/bin/env python3
"""
BigQuery Upload Script

Uploads results data to BigQuery for long-term storage and analysis.
Routes each result to its per-prompt table via bq_helper.
Supports incremental uploads and full re-uploads.

Usage:
    python bigquery_upload.py --project firgun-478006 --dataset ai_evaluations
    python bigquery_upload.py --project firgun-478006 --dataset ai_evaluations --full-reload
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from bq_helper import (
    ensure_all_tables_exist,
    upload_result,
    upload_sources,
    PROMPT_TABLE_CONFIG,
)


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


def upload_folder(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    folder_path: str,
):
    """Upload a single folder's results to per-prompt BigQuery tables."""
    folder = Path(folder_path)
    folder_name = folder.name

    print(f"Processing {folder_name}...")

    uploaded_count = 0
    sources_count = 0

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

        # Skip unknown prompt IDs
        if prompt_id not in PROMPT_TABLE_CONFIG:
            print(f"  Warning: Unknown prompt_id '{prompt_id}' in {json_file.name}, skipping")
            continue

        # Upload result to per-prompt table
        if upload_result(data, folder_name, project_id, dataset_id):
            uploaded_count += 1

        # Upload sources to per-prompt sources table
        if upload_sources(data, folder_name, project_id, dataset_id):
            src_count = len(data.get("sources", []))
            sources_count += src_count

    if uploaded_count == 0:
        print(f"  No results uploaded from {folder_name}")
        return

    print(f"  Uploaded {uploaded_count} results, {sources_count} sources to per-prompt tables")

    # Add run metadata
    run_date = _extract_date_from_folder(folder_name)
    run_type = _get_run_type(folder_name)

    # Detect platform from first result file
    platform = None
    for json_file in folder.glob("*.json"):
        if json_file.name.startswith("."):
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            model = data.get("model", "")
            if model:
                platform = _normalize_ai_name(model)
                break
        except Exception:
            continue

    run_row = {
        "run_folder": folder_name,
        "run_date": run_date,
        "platform": platform,
        "run_type": run_type,
        "total_prompts": uploaded_count,
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
    """Upload all results to BigQuery per-prompt tables."""
    client = bigquery.Client(project=project_id)

    # Create dataset and all per-prompt tables
    create_dataset_if_not_exists(client, dataset_id)
    ensure_all_tables_exist(project_id, dataset_id)
    create_or_update_table(client, dataset_id, "runs", RUNS_SCHEMA)

    # Get already uploaded folders
    if full_reload:
        uploaded = set()
        print("Full reload requested - truncating runs table...")
        client.query(f"TRUNCATE TABLE `{project_id}.{dataset_id}.runs`").result()
        # Truncate all per-prompt tables
        for cfg in PROMPT_TABLE_CONFIG.values():
            for suffix in ("", "_sources"):
                tbl = f"{cfg['table']}{suffix}"
                try:
                    client.query(f"TRUNCATE TABLE `{project_id}.{dataset_id}.{tbl}`").result()
                except Exception:
                    pass  # Table may not exist yet
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

        upload_folder(client, project_id, dataset_id, str(folder))
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
