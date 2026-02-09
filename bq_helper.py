#!/usr/bin/env python3
"""
BigQuery Helper Module

Provides functions for uploading prompt results directly to BigQuery.
Used by the prompt runners to save results in real-time.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

# Default BigQuery settings
DEFAULT_PROJECT = "firgun-478006"
DEFAULT_DATASET = "ai_evaluations"

# Source type categorization patterns (from ecosystem_analysis.py)
SOURCE_TYPE_PATTERNS = {
    "Quantum Media": [
        "spinquanta", "quantum.org", "thequantuminsider", "quantumcomputingreport",
        "entangledfuture", "postquantum", "quantumzeitgeist", "quantumtech",
    ],
    "Tech Media": [
        "techcrunch", "wired", "arstechnica", "theverge", "zdnet", "cnet",
        "venturebeat", "tech.eu", "sifted", "tomshardware", "engadget",
        "thenextweb", "techradar",
    ],
    "Financial Media": [
        "bloomberg", "reuters", "wsj", "ft.com", "cnbc", "fortune", "forbes",
        "businessinsider", "marketwatch", "yahoo.com/finance", "agbi.com",
        "barrons", "economist", "financialtimes",
    ],
    "VC / Investment Firm": [
        "gai-ventures", "quantonation", "quantumvalley", "photonventures",
        "playground.global", "amadeus", "dcvc", "bessemer", "a16z", "sequoia",
        "lightspeed", "greylock", "khosla", "nea.com", "accel",
    ],
    "Startup Media / Funding Blog": [
        "eu-startups", "techfundingnews", "dealroom", "crunchbase", "pitchbook",
        "cbinsights", "tracxn", "f6s.com",
    ],
    "Press Release Network": [
        "businesswire", "prnewswire", "globenewswire", "accesswire",
    ],
    "Academic / Research": [
        "arxiv", "nature.com", "science.org", "ieee", "acm.org", "springer",
        "wiley", "researchgate", "scholar.google", "sciencedirect", "pubmed",
    ],
    "Social / UGC": [
        "linkedin", "twitter", "x.com", "reddit", "medium.com", "substack",
    ],
    "General Knowledge": [
        "wikipedia", "britannica",
    ],
    "Corporate / Vendor": [
        "ibm.com", "google.com", "microsoft.com", "amazon.com", "quantware",
        "ionq.com", "rigetti.com", "honeywell", "qnami", "aosense", "infleqtion",
    ],
    "Market Research / Data": [
        "statista", "grandviewresearch", "marketsandmarkets", "mordorintelligence",
        "biforesight", "idc.com", "gartner", "forrester", "futuremarketsinc",
    ],
    "Government / Policy": [
        "gov.uk", "gov.us", "europa.eu", "nist.gov", "darpa", "nsf.gov",
    ],
}

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


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or ""
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return ""


def _categorize_source(domain: str) -> str:
    """Categorize a source domain by type."""
    domain_lower = domain.lower()
    for category, patterns in SOURCE_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in domain_lower:
                return category
    return "Other"


def _extract_date_from_folder(folder_name: str) -> Optional[str]:
    """Extract date string (YYYY-MM-DD) from folder name."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", folder_name)
    return match.group(1) if match else None


def ensure_all_tables_exist(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
):
    """Ensure all BigQuery tables exist (results, entity_mentions, sources_analysis)."""
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

    # Schema for entity_mentions table
    entity_mentions_schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("prompt_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_normalized", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("entity_type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("mention_rank", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("explanation", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    # Schema for sources_analysis table
    sources_analysis_schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("prompt_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("domain", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("title", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("source_type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    # Check/create entity_mentions table
    em_table_ref = client.dataset(dataset_id).table("entity_mentions")
    try:
        client.get_table(em_table_ref)
    except NotFound:
        table = bigquery.Table(em_table_ref, schema=entity_mentions_schema)
        client.create_table(table)
        print(f"Created table {dataset_id}.entity_mentions")

    # Check/create sources_analysis table
    sa_table_ref = client.dataset(dataset_id).table("sources_analysis")
    try:
        client.get_table(sa_table_ref)
    except NotFound:
        table = bigquery.Table(sa_table_ref, schema=sources_analysis_schema)
        client.create_table(table)
        print(f"Created table {dataset_id}.sources_analysis")

    # Also ensure the main results table exists
    ensure_tables_exist(project_id, dataset_id)


def upload_entity_mention(
    run_folder: str,
    prompt_id: str,
    platform: str,
    entity_name: str,
    entity_normalized: str = "",
    entity_type: str = "",
    mention_rank: Optional[int] = None,
    explanation: str = "",
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> bool:
    """
    Upload a single entity mention to BigQuery.

    Args:
        run_folder: Name of the run folder
        prompt_id: Prompt ID (P1-P9, VP1-VP20, etc.)
        platform: AI platform (chatgpt, gemini, perplexity)
        entity_name: Name of the entity
        entity_normalized: Normalized entity name for dedup
        entity_type: Type (company, institution, person, etc.)
        mention_rank: Position in ranked list
        explanation: Context/description

    Returns:
        True if upload succeeded, False otherwise
    """
    client = get_client(project_id)
    table_ref = f"{project_id}.{dataset_id}.entity_mentions"

    run_date = _extract_date_from_folder(run_folder)

    row = {
        "id": str(uuid.uuid4()),
        "run_folder": run_folder,
        "run_date": run_date,
        "prompt_id": prompt_id,
        "platform": _normalize_ai_name(platform),
        "entity_name": entity_name[:500] if entity_name else "",
        "entity_normalized": entity_normalized[:500] if entity_normalized else "",
        "entity_type": entity_type[:100] if entity_type else "",
        "mention_rank": mention_rank,
        "explanation": explanation[:2000] if explanation else "",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        errors = client.insert_rows_json(table_ref, [row])
        if errors:
            print(f"Entity mention upload errors: {errors}")
            return False
        return True
    except Exception as e:
        print(f"Entity mention upload failed: {e}")
        return False


def upload_sources(
    result: dict,
    run_folder: str,
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> bool:
    """
    Upload all sources from a result to BigQuery.

    Args:
        result: Dict with prompt_id, sources, model, and optionally company/vc
        run_folder: Name of the run folder

    Returns:
        True if all uploads succeeded, False if any failed
    """
    sources = result.get("sources", [])
    if not sources:
        return True

    client = get_client(project_id)
    table_ref = f"{project_id}.{dataset_id}.sources_analysis"

    prompt_id = result.get("prompt_id", "")
    platform = _normalize_ai_name(result.get("model", ""))
    entity_name = result.get("company") or result.get("vc") or ""
    run_date = _extract_date_from_folder(run_folder)

    rows = []
    for source in sources:
        url = source.get("url", "")
        if not url:
            continue

        domain = _extract_domain(url)
        if not domain:
            continue

        title = source.get("title", "") or source.get("publisher", "")
        source_type = _categorize_source(domain)

        rows.append({
            "id": str(uuid.uuid4()),
            "run_folder": run_folder,
            "run_date": run_date,
            "prompt_id": prompt_id,
            "platform": platform,
            "entity_name": entity_name[:500] if entity_name else None,
            "url": url[:2000],
            "domain": domain[:500],
            "title": title[:500] if title else None,
            "source_type": source_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        })

    if not rows:
        return True

    try:
        errors = client.insert_rows_json(table_ref, rows)
        if errors:
            print(f"Sources upload errors: {errors}")
            return False
        return True
    except Exception as e:
        print(f"Sources upload failed: {e}")
        return False
