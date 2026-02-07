#!/usr/bin/env python3
"""
BigQuery Helper Module

Provides functions for uploading prompt results directly to BigQuery.
Used by the prompt runners to save results in real-time.
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

# Default BigQuery settings
DEFAULT_PROJECT = "firgun-478006"
DEFAULT_DATASET = "ai_evaluations"

# Cached client
_client = None


def get_client(project_id: str = DEFAULT_PROJECT) -> bigquery.Client:
    """Get or create a BigQuery client."""
    global _client
    if _client is None:
        _client = bigquery.Client(project=project_id)
    return _client


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
    if not answer:
        return None
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer)]
    return next((n for n in numbers if n <= 10), None)


def upload_result(
    result: dict,
    run_folder: str,
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> bool:
    """
    Upload a single result to BigQuery.

    Args:
        result: Dict with prompt_id, company/vc, question, answer, timestamp, model, sources
        run_folder: Name of the run folder (e.g., "2026-02-06_12-00-00_chatgpt")
        project_id: GCP project ID
        dataset_id: BigQuery dataset name

    Returns:
        True if upload succeeded, False otherwise
    """
    client = get_client(project_id)
    table_ref = f"{project_id}.{dataset_id}.results"

    prompt_id = result.get("prompt_id", "")
    entity_name = result.get("company") or result.get("vc")
    answer = result.get("answer", "")
    model = result.get("model", "")

    # Determine entity type
    if prompt_id.startswith("VP"):
        entity_type = "vc"
    elif entity_name:
        entity_type = "company"
    else:
        entity_type = "ecosystem"

    # Create unique ID
    row_id = f"{run_folder}_{prompt_id}_{entity_name or 'category'}_{model}"
    row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)

    row = {
        "id": row_id,
        "prompt_id": prompt_id,
        "entity_type": entity_type,
        "entity_name": entity_name,
        "question": result.get("question"),
        "answer": answer,
        "score": _extract_score(answer) if answer and answer != "FAILED" else None,
        "model": model,
        "platform": _normalize_ai_name(model),
        "run_timestamp": result.get("timestamp"),
        "run_folder": run_folder,
        "sources": json.dumps(result.get("sources", [])),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        errors = client.insert_rows_json(table_ref, [row])
        if errors:
            print(f"BigQuery upload errors: {errors}")
            return False
        return True
    except Exception as e:
        print(f"BigQuery upload failed: {e}")
        return False


def ensure_tables_exist(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
):
    """Ensure the BigQuery dataset and tables exist."""
    client = get_client(project_id)

    # Check/create dataset
    dataset_ref = client.dataset(dataset_id)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset)
        print(f"Created dataset {dataset_id}")

    # Schema for results table
    results_schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("prompt_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("question", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("answer", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("score", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("model", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("platform", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("run_timestamp", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("run_folder", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("sources", "JSON", mode="NULLABLE"),
        bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    # Check/create results table
    table_ref = client.dataset(dataset_id).table("results")
    try:
        client.get_table(table_ref)
    except NotFound:
        table = bigquery.Table(table_ref, schema=results_schema)
        client.create_table(table)
        print(f"Created table {dataset_id}.results")


def get_completed_prompts(
    run_folder: str,
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> set:
    """
    Get set of completed prompt keys (prompt_id_entity_name) for a run folder.
    Used for resume functionality.
    """
    client = get_client(project_id)
    query = f"""
    SELECT prompt_id, entity_name
    FROM `{project_id}.{dataset_id}.results`
    WHERE run_folder = @run_folder
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_folder", "STRING", run_folder)
        ]
    )
    try:
        results = client.query(query, job_config=job_config).result()
        completed = set()
        for row in results:
            name = (row.entity_name or "category").replace(" ", "_")
            completed.add(f"{row.prompt_id}_{name}")
        return completed
    except Exception as e:
        print(f"Warning: Could not query completed prompts: {e}")
        return set()


def get_run_folder_name(platform: str, run_type: str = "") -> str:
    """Generate a run folder name for the current timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_{platform}"
    if run_type:
        suffix += f"_{run_type}"
    return f"{timestamp}{suffix}"
