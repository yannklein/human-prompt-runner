#!/usr/bin/env python3
"""
BigQuery Helper Module

Provides functions for uploading prompt results directly to BigQuery.
Each prompt gets its own table (+ a companion _sources table).
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

# ---------------------------------------------------------------------------
# Per-prompt table configuration
# ---------------------------------------------------------------------------
# schema_type is one of: ecosystem_ranked, company_no_score, company_with_score,
#                         vc_no_score, vc_with_score

PROMPT_TABLE_CONFIG = {
    # Ecosystem ranked (P1-P9, VP1)
    "P1":  {"table": "P1_top_applications",              "schema_type": "ecosystem_ranked"},
    "P2":  {"table": "P2_top_countries",                  "schema_type": "ecosystem_ranked"},
    "P3":  {"table": "P3_most_promising_companies",       "schema_type": "ecosystem_ranked"},
    "P4":  {"table": "P4_best_teams",                     "schema_type": "ecosystem_ranked"},
    "P5":  {"table": "P5_leading_labs",                   "schema_type": "ecosystem_ranked"},
    "P6":  {"table": "P6_key_figures",                    "schema_type": "ecosystem_ranked"},
    "P7":  {"table": "P7_commercialization_challenges",   "schema_type": "ecosystem_ranked"},
    "P8":  {"table": "P8_latest_breakthroughs",           "schema_type": "ecosystem_ranked"},
    "P9":  {"table": "P9_predicted_breakthroughs",        "schema_type": "ecosystem_ranked"},
    "VP1": {"table": "VP1_top_vcs",                       "schema_type": "ecosystem_ranked"},
    # Company no score (P10, P11, P14-P17)
    "P10": {"table": "P10_company_overview",              "schema_type": "company_no_score"},
    "P11": {"table": "P11_competitive_differentiation",   "schema_type": "company_no_score"},
    "P14": {"table": "P14_strengths",                     "schema_type": "company_no_score"},
    "P15": {"table": "P15_weaknesses",                    "schema_type": "company_no_score"},
    "P16": {"table": "P16_opportunities",                 "schema_type": "company_no_score"},
    "P17": {"table": "P17_threats",                       "schema_type": "company_no_score"},
    # Company with score (P12, P13, P18-P27)
    "P12": {"table": "P12_icp_alignment",                 "schema_type": "company_with_score"},
    "P13": {"table": "P13_buyer_persona_alignment",       "schema_type": "company_with_score"},
    "P18": {"table": "P18_academic_strength",             "schema_type": "company_with_score"},
    "P19": {"table": "P19_ecosystem_quality",             "schema_type": "company_with_score"},
    "P20": {"table": "P20_execution_capabilities",        "schema_type": "company_with_score"},
    "P21": {"table": "P21_patents_quality",               "schema_type": "company_with_score"},
    "P22": {"table": "P22_ip_uniqueness",                 "schema_type": "company_with_score"},
    "P23": {"table": "P23_product_development",           "schema_type": "company_with_score"},
    "P24": {"table": "P24_sales_performance",             "schema_type": "company_with_score"},
    "P25": {"table": "P25_vc_quality",                    "schema_type": "company_with_score"},
    "P26": {"table": "P26_10x_potential",                 "schema_type": "company_with_score"},
    "P27": {"table": "P27_reinvestment_likelihood",       "schema_type": "company_with_score"},
    # VC no score (VP2-VP5)
    "VP2": {"table": "VP2_investment_thesis",             "schema_type": "vc_no_score"},
    "VP3": {"table": "VP3_portfolio_companies",           "schema_type": "vc_no_score"},
    "VP4": {"table": "VP4_key_partners",                  "schema_type": "vc_no_score"},
    "VP5": {"table": "VP5_reputation",                    "schema_type": "vc_no_score"},
    # VC with score (VP6-VP20)
    "VP6":  {"table": "VP6_deep_tech_track_record",       "schema_type": "vc_with_score"},
    "VP7":  {"table": "VP7_technical_expertise",          "schema_type": "vc_with_score"},
    "VP8":  {"table": "VP8_quantum_understanding",        "schema_type": "vc_with_score"},
    "VP9":  {"table": "VP9_fund_structure",               "schema_type": "vc_with_score"},
    "VP10": {"table": "VP10_follow_on_capability",        "schema_type": "vc_with_score"},
    "VP11": {"table": "VP11_lp_base",                     "schema_type": "vc_with_score"},
    "VP12": {"table": "VP12_talent_pipeline",             "schema_type": "vc_with_score"},
    "VP13": {"table": "VP13_strategic_partners",          "schema_type": "vc_with_score"},
    "VP14": {"table": "VP14_grant_access",                "schema_type": "vc_with_score"},
    "VP15": {"table": "VP15_narrative_discipline",        "schema_type": "vc_with_score"},
    "VP16": {"table": "VP16_signaling_power",             "schema_type": "vc_with_score"},
    "VP17": {"table": "VP17_hype_resistance",             "schema_type": "vc_with_score"},
    "VP18": {"table": "VP18_patience_setbacks",           "schema_type": "vc_with_score"},
    "VP19": {"table": "VP19_pivot_tolerance",             "schema_type": "vc_with_score"},
    "VP20": {"table": "VP20_down_round_behavior",         "schema_type": "vc_with_score"},
}

# ---------------------------------------------------------------------------
# Schema definitions per type
# ---------------------------------------------------------------------------

_ECOSYSTEM_RANKED_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("entity_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("entity_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("rank", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("explanation", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("raw_answer", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
]

_COMPANY_NO_SCORE_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("explanation", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
]

_COMPANY_WITH_SCORE_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("score", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("explanation", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
]

_VC_NO_SCORE_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("vc_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("explanation", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
]

_VC_WITH_SCORE_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("vc_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("score", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("explanation", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
]

_SOURCES_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_folder", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("run_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("entity_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("domain", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("title", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("source_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("uploaded_at", "TIMESTAMP", mode="REQUIRED"),
]

_COMPANY_MONTHLY_SUMMARY_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("month", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("prompt_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("avg_score", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("run_count", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("synthesis", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("is_final", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
]

COMPANY_MONTHLY_SUMMARY_TABLE = "company_monthly_summary"

SCHEMA_TYPE_MAP = {
    "ecosystem_ranked": _ECOSYSTEM_RANKED_SCHEMA,
    "company_no_score": _COMPANY_NO_SCORE_SCHEMA,
    "company_with_score": _COMPANY_WITH_SCORE_SCHEMA,
    "vc_no_score": _VC_NO_SCORE_SCHEMA,
    "vc_with_score": _VC_WITH_SCORE_SCHEMA,
}

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_client(project_id: str = DEFAULT_PROJECT) -> bigquery.Client:
    """Get or create a BigQuery client."""
    global _client
    if _client is None:
        _client = bigquery.Client(project=project_id)
    return _client


def get_table_name(prompt_id: str) -> Optional[str]:
    """Return the per-prompt result table name, or None if unknown."""
    cfg = PROMPT_TABLE_CONFIG.get(prompt_id)
    return cfg["table"] if cfg else None


def get_sources_table_name(prompt_id: str) -> Optional[str]:
    """Return the per-prompt sources table name, or None if unknown."""
    cfg = PROMPT_TABLE_CONFIG.get(prompt_id)
    return f"{cfg['table']}_sources" if cfg else None


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


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
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


def get_run_folder_name(platform: str, run_type: str = "") -> str:
    """Generate a run folder name for the current timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_{platform}"
    if run_type:
        suffix += f"_{run_type}"
    return f"{timestamp}{suffix}"


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def ensure_tables_exist(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
):
    """Legacy: ensure the old unified results table exists (kept for backward compat)."""
    client = get_client(project_id)

    dataset_ref = client.dataset(dataset_id)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset)
        print(f"Created dataset {dataset_id}")

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

    table_ref = client.dataset(dataset_id).table("results")
    try:
        client.get_table(table_ref)
    except NotFound:
        table = bigquery.Table(table_ref, schema=results_schema)
        client.create_table(table)
        print(f"Created table {dataset_id}.results")


def _ensure_table(client, dataset_id: str, table_name: str, schema: list):
    """Create a table if it doesn't exist."""
    table_ref = client.dataset(dataset_id).table(table_name)
    try:
        client.get_table(table_ref)
    except NotFound:
        table = bigquery.Table(table_ref, schema=schema)
        client.create_table(table)
        print(f"Created table {dataset_id}.{table_name}")


def ensure_all_tables_exist(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
):
    """Ensure the dataset and all per-prompt tables (result + sources) exist."""
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

    # Create per-prompt result + sources tables
    for prompt_id, cfg in PROMPT_TABLE_CONFIG.items():
        schema = SCHEMA_TYPE_MAP[cfg["schema_type"]]
        _ensure_table(client, dataset_id, cfg["table"], schema)
        _ensure_table(client, dataset_id, f"{cfg['table']}_sources", _SOURCES_SCHEMA)

    # Monthly summary table
    _ensure_table(client, dataset_id, COMPANY_MONTHLY_SUMMARY_TABLE, _COMPANY_MONTHLY_SUMMARY_SCHEMA)

    # Also keep legacy tables around for historical data
    ensure_tables_exist(project_id, dataset_id)


# ---------------------------------------------------------------------------
# Upload: results
# ---------------------------------------------------------------------------

def upload_result(
    result: dict,
    run_folder: str,
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> bool:
    """
    Upload a single result to the appropriate per-prompt BigQuery table.

    For ecosystem_ranked prompts (P1-P9, VP1), entity extraction is performed
    and one row per entity is inserted. For other types, a single row is inserted.

    Args:
        result: Dict with prompt_id, company/vc, question, answer, timestamp, model, sources
        run_folder: Name of the run folder
        project_id: GCP project ID
        dataset_id: BigQuery dataset name

    Returns:
        True if upload succeeded, False otherwise
    """
    client = get_client(project_id)

    prompt_id = result.get("prompt_id", "")
    cfg = PROMPT_TABLE_CONFIG.get(prompt_id)
    if not cfg:
        print(f"Warning: Unknown prompt_id '{prompt_id}', skipping upload")
        return False

    table_name = cfg["table"]
    schema_type = cfg["schema_type"]
    table_ref = f"{project_id}.{dataset_id}.{table_name}"

    answer = result.get("answer", "")
    model = result.get("model", "")
    platform = _normalize_ai_name(model)
    run_date = _extract_date_from_folder(run_folder)
    now = datetime.now(timezone.utc).isoformat()

    if schema_type == "ecosystem_ranked":
        return _upload_ecosystem_ranked(
            client, table_ref, result, run_folder, run_date, platform, now
        )
    elif schema_type == "company_no_score":
        company = result.get("company") or ""
        row_id = f"{run_folder}_{prompt_id}_{company}_{platform}"
        row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)
        row = {
            "id": row_id,
            "run_folder": run_folder,
            "run_date": run_date,
            "platform": platform,
            "company": company,
            "explanation": answer,
            "uploaded_at": now,
        }
    elif schema_type == "company_with_score":
        company = result.get("company") or ""
        row_id = f"{run_folder}_{prompt_id}_{company}_{platform}"
        row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)
        row = {
            "id": row_id,
            "run_folder": run_folder,
            "run_date": run_date,
            "platform": platform,
            "company": company,
            "score": _extract_score(answer) if answer and answer != "FAILED" else None,
            "explanation": answer,
            "uploaded_at": now,
        }
    elif schema_type == "vc_no_score":
        vc_name = result.get("vc") or ""
        row_id = f"{run_folder}_{prompt_id}_{vc_name}_{platform}"
        row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)
        row = {
            "id": row_id,
            "run_folder": run_folder,
            "run_date": run_date,
            "platform": platform,
            "vc_name": vc_name,
            "explanation": answer,
            "uploaded_at": now,
        }
    elif schema_type == "vc_with_score":
        vc_name = result.get("vc") or ""
        row_id = f"{run_folder}_{prompt_id}_{vc_name}_{platform}"
        row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)
        row = {
            "id": row_id,
            "run_folder": run_folder,
            "run_date": run_date,
            "platform": platform,
            "vc_name": vc_name,
            "score": _extract_score(answer) if answer and answer != "FAILED" else None,
            "explanation": answer,
            "uploaded_at": now,
        }
    else:
        print(f"Warning: Unknown schema_type '{schema_type}' for {prompt_id}")
        return False

    try:
        errors = client.insert_rows_json(table_ref, [row])
        if errors:
            print(f"BigQuery upload errors for {table_name}: {errors}")
            return False
        return True
    except Exception as e:
        print(f"BigQuery upload failed for {table_name}: {e}")
        return False


def _upload_ecosystem_ranked(
    client,
    table_ref: str,
    result: dict,
    run_folder: str,
    run_date: Optional[str],
    platform: str,
    now: str,
) -> bool:
    """Extract entities from answer and insert one row per entity into an ecosystem_ranked table."""
    answer = result.get("answer", "")
    prompt_id = result.get("prompt_id", "")

    # Lazy import to avoid circular imports
    try:
        from ecosystem_analysis import extract_rankings_from_answer
    except ImportError:
        extract_rankings_from_answer = None

    rows = []
    if extract_rankings_from_answer and answer and answer != "FAILED":
        try:
            entities = extract_rankings_from_answer(answer)
            for entity in entities:
                row_id = f"{run_folder}_{prompt_id}_{entity['entity']['name']}_{platform}"
                row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)
                rows.append({
                    "id": row_id,
                    "run_folder": run_folder,
                    "run_date": run_date,
                    "platform": platform,
                    "entity_name": entity["entity"]["name"][:500],
                    "entity_type": entity["entity"].get("type", "")[:100],
                    "rank": entity.get("rank"),
                    "explanation": entity.get("explanation", "")[:2000],
                    "raw_answer": answer,
                    "uploaded_at": now,
                })
        except Exception as e:
            print(f"  Warning: Entity extraction failed for {prompt_id}: {e}")

    # Fallback: if no entities extracted, insert one row with full answer
    if not rows:
        row_id = f"{run_folder}_{prompt_id}_extraction_failed_{platform}"
        row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)
        rows.append({
            "id": row_id,
            "run_folder": run_folder,
            "run_date": run_date,
            "platform": platform,
            "entity_name": "(extraction failed)",
            "entity_type": "",
            "rank": None,
            "explanation": "",
            "raw_answer": answer,
            "uploaded_at": now,
        })

    try:
        errors = client.insert_rows_json(table_ref, rows)
        if errors:
            print(f"BigQuery upload errors (ecosystem_ranked): {errors}")
            return False
        return True
    except Exception as e:
        print(f"BigQuery upload failed (ecosystem_ranked): {e}")
        return False


# ---------------------------------------------------------------------------
# Upload: sources
# ---------------------------------------------------------------------------

def upload_sources(
    result: dict,
    run_folder: str,
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> bool:
    """
    Upload all sources from a result to the appropriate per-prompt _sources table.

    Args:
        result: Dict with prompt_id, sources, model, and optionally company/vc
        run_folder: Name of the run folder

    Returns:
        True if all uploads succeeded, False if any failed
    """
    sources = result.get("sources", [])
    if not sources:
        return True

    prompt_id = result.get("prompt_id", "")
    sources_table = get_sources_table_name(prompt_id)
    if not sources_table:
        print(f"Warning: Unknown prompt_id '{prompt_id}' for sources upload, skipping")
        return False

    client = get_client(project_id)
    table_ref = f"{project_id}.{dataset_id}.{sources_table}"

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
            print(f"Sources upload errors for {sources_table}: {errors}")
            return False
        return True
    except Exception as e:
        print(f"Sources upload failed for {sources_table}: {e}")
        return False


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def get_completed_prompts(
    run_folder: str,
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
) -> set:
    """
    Get set of completed prompt keys (prompt_id_entity_name) for a run folder.
    Queries each per-prompt table.
    """
    client = get_client(project_id)
    completed = set()

    for prompt_id, cfg in PROMPT_TABLE_CONFIG.items():
        table_name = cfg["table"]
        schema_type = cfg["schema_type"]

        # Determine the entity column name based on schema type
        if schema_type == "ecosystem_ranked":
            entity_col = "entity_name"
        elif schema_type in ("company_no_score", "company_with_score"):
            entity_col = "company"
        else:  # vc_no_score, vc_with_score
            entity_col = "vc_name"

        query = f"""
        SELECT DISTINCT {entity_col} as entity_name
        FROM `{project_id}.{dataset_id}.{table_name}`
        WHERE run_folder = @run_folder
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("run_folder", "STRING", run_folder)
            ]
        )
        try:
            results = client.query(query, job_config=job_config).result()
            for row in results:
                name = (row.entity_name or "category").replace(" ", "_")
                completed.add(f"{prompt_id}_{name}")
        except Exception:
            # Table might not exist yet, that's fine
            pass

    return completed


# ---------------------------------------------------------------------------
# Load company data for webapps
# ---------------------------------------------------------------------------

def load_company_data_from_bq(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
    company_filter: Optional[set] = None,
) -> tuple:
    """
    Load company evaluation data from BigQuery per-prompt tables.

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset name
        company_filter: If provided, only load data for these company names

    Returns:
        (raw_responses, company_names) where:
        - raw_responses[(platform, prompt_id, company)] = {
            "prompt_id", "company", "answer", "question", "model",
            "sources": [{"url", "title", "publisher"}]
          }
        - company_names = set of all company names
    """
    client = get_client(project_id)
    raw_responses = {}
    company_names = set()

    # Company prompt IDs only
    company_prompts = {
        pid: cfg for pid, cfg in PROMPT_TABLE_CONFIG.items()
        if cfg["schema_type"] in ("company_no_score", "company_with_score")
    }

    for prompt_id, cfg in company_prompts.items():
        table_name = cfg["table"]
        full_table = f"`{project_id}.{dataset_id}.{table_name}`"
        sources_table = f"`{project_id}.{dataset_id}.{table_name}_sources`"

        # Build optional WHERE clause for company filtering
        company_where = ""
        if company_filter:
            escaped = [c.replace("'", "\\'") for c in company_filter]
            company_list = ", ".join(f"'{c}'" for c in escaped)
            company_where = f"WHERE t.company IN ({company_list})"

        # Query latest run per platform
        query = f"""
        WITH latest AS (
            SELECT platform, MAX(run_folder) AS run_folder
            FROM {full_table} GROUP BY platform
        )
        SELECT t.* FROM {full_table} t
        JOIN latest l ON t.platform = l.platform AND t.run_folder = l.run_folder
        {company_where}
        """

        try:
            rows = list(client.query(query).result())
        except Exception as e:
            print(f"Warning: Failed to query {table_name}: {e}")
            continue

        # Build result entries and collect run_folders for sources query
        run_folders_by_platform = {}
        for row in rows:
            platform = row.platform
            company = row.company
            company_names.add(company)
            run_folders_by_platform[platform] = row.run_folder

            entry = {
                "prompt_id": prompt_id,
                "company": company,
                "answer": row.explanation or "",
                "question": "",
                "model": platform,
                "sources": [],
            }
            raw_responses[(platform, prompt_id, company)] = entry

        # Query sources for matching run_folders
        if run_folders_by_platform:
            conditions = " OR ".join(
                f"(platform = '{p}' AND run_folder = '{rf}')"
                for p, rf in run_folders_by_platform.items()
            )
            src_query = f"""
            SELECT * FROM {sources_table}
            WHERE {conditions}
            """
            try:
                for srow in client.query(src_query).result():
                    key = (srow.platform, prompt_id, srow.entity_name)
                    if key in raw_responses:
                        raw_responses[key]["sources"].append({
                            "url": srow.url or "",
                            "title": srow.title or "",
                            "publisher": srow.domain or "",
                        })
            except Exception as e:
                print(f"Warning: Failed to query sources for {table_name}: {e}")

    return raw_responses, company_names


# ---------------------------------------------------------------------------
# Monthly summary: synthesis helper
# ---------------------------------------------------------------------------

def _synthesize_with_claude(explanations: list, prompt_id: str, company: str) -> str:
    """Call Claude API to synthesize multiple monthly explanations into one."""
    try:
        import anthropic
    except ImportError:
        print("Warning: anthropic package not installed, skipping synthesis")
        return explanations[-1] if explanations else ""

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    joined = "\n\n---\n\n".join(explanations)
    prompt = (
        f"You are synthesizing {len(explanations)} AI evaluations of the company "
        f'"{company}" for evaluation prompt {prompt_id}.\n\n'
        f"Here are the individual evaluations:\n\n{joined}\n\n"
        "Please synthesize these into a single concise summary that captures "
        "the key points, consensus findings, and any notable disagreements. "
        "Keep the same tone and level of detail as the originals. "
        "If scores are mentioned, note the range or average."
    )
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        print(f"Warning: Claude synthesis failed for {prompt_id}/{company}: {e}")
        return explanations[-1] if explanations else ""


# ---------------------------------------------------------------------------
# Monthly summary: refresh
# ---------------------------------------------------------------------------

def refresh_monthly_summaries(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
    company_filter: Optional[set] = None,
    dry_run: bool = False,
) -> dict:
    """
    Refresh the company_monthly_summary table from raw per-prompt tables.

    For each (month, prompt_id, company, platform):
      - Computes avg_score (for scored prompts) and run_count
      - For current (incomplete) month: uses the last available explanation
      - For past (completed) months not yet finalized: generates AI synthesis

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset name
        company_filter: If provided, only refresh for these companies
        dry_run: If True, don't write to BQ, just return what would be written

    Returns:
        dict with stats: {"rows_processed": int, "rows_synthesized": int, "rows_written": int}
    """
    client = get_client(project_id)

    current_month = datetime.now().strftime("%Y-%m")

    # Collect all company prompts
    company_prompts = {
        pid: cfg for pid, cfg in PROMPT_TABLE_CONFIG.items()
        if cfg["schema_type"] in ("company_no_score", "company_with_score")
    }

    # Load existing finalized rows so we never touch them
    existing_final = set()
    try:
        query = f"""
        SELECT id FROM `{project_id}.{dataset_id}.{COMPANY_MONTHLY_SUMMARY_TABLE}`
        WHERE is_final = TRUE
        """
        for row in client.query(query).result():
            existing_final.add(row.id)
        print(f"Found {len(existing_final)} already-finalized rows (will not touch)")
    except Exception:
        pass  # Table might not exist yet

    stats = {"rows_processed": 0, "rows_synthesized": 0, "rows_written": 0, "rows_skipped_final": 0}
    rows_to_upsert = []

    for prompt_id, cfg in company_prompts.items():
        table_name = cfg["table"]
        schema_type = cfg["schema_type"]
        has_score = schema_type == "company_with_score"
        full_table = f"`{project_id}.{dataset_id}.{table_name}`"

        score_select = "AVG(score) as avg_score," if has_score else "CAST(NULL AS FLOAT64) as avg_score,"

        company_where = ""
        if company_filter:
            escaped = [c.replace("'", "\\'") for c in company_filter]
            company_list = ", ".join(f"'{c}'" for c in escaped)
            company_where = f"AND company IN ({company_list})"

        query = f"""
        SELECT
            FORMAT_DATE('%Y-%m', run_date) as month,
            company,
            platform,
            {score_select}
            COUNT(*) as run_count,
            ARRAY_AGG(explanation ORDER BY run_folder DESC LIMIT 1)[OFFSET(0)] as last_explanation
        FROM {full_table}
        WHERE run_date IS NOT NULL
        {company_where}
        GROUP BY month, company, platform
        """

        try:
            results = list(client.query(query).result())
        except Exception as e:
            print(f"Warning: Failed to query {table_name}: {e}")
            continue

        for row in results:
            month = row.month
            company = row.company
            platform = row.platform
            row_id = f"{month}_{prompt_id}_{company}_{platform}"
            row_id = re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)

            stats["rows_processed"] += 1

            # Never touch already-finalized rows (past months locked in)
            if row_id in existing_final:
                stats["rows_skipped_final"] += 1
                continue

            is_final = False
            synthesis = row.last_explanation or ""

            # For past months, generate AI synthesis
            if month < current_month:
                # Query all explanations for this month to synthesize
                all_explanations_query = f"""
                SELECT explanation
                FROM {full_table}
                WHERE FORMAT_DATE('%Y-%m', run_date) = @month
                  AND company = @company
                  AND platform = @platform
                  AND explanation IS NOT NULL
                ORDER BY run_folder
                """
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("month", "STRING", month),
                        bigquery.ScalarQueryParameter("company", "STRING", company),
                        bigquery.ScalarQueryParameter("platform", "STRING", platform),
                    ]
                )
                try:
                    explanations = [
                        r.explanation for r in client.query(all_explanations_query, job_config=job_config).result()
                        if r.explanation
                    ]
                except Exception:
                    explanations = [synthesis] if synthesis else []

                if len(explanations) > 1 and not dry_run:
                    synthesis = _synthesize_with_claude(explanations, prompt_id, company)
                    stats["rows_synthesized"] += 1
                elif explanations:
                    synthesis = explanations[-1]

                is_final = True

            now = datetime.now(timezone.utc).isoformat()
            summary_row = {
                "id": row_id,
                "month": month,
                "prompt_id": prompt_id,
                "company": company,
                "platform": platform,
                "avg_score": row.avg_score,
                "run_count": row.run_count,
                "synthesis": synthesis,
                "is_final": is_final,
                "updated_at": now,
            }
            rows_to_upsert.append(summary_row)

    if dry_run:
        stats["rows_written"] = len(rows_to_upsert)
        print(f"[DRY RUN] Would write {len(rows_to_upsert)} rows to {COMPANY_MONTHLY_SUMMARY_TABLE}")
        print(f"[DRY RUN] Skipped {stats['rows_skipped_final']} finalized rows")
        for r in rows_to_upsert[:10]:
            print(f"  {r['id']} | score={r['avg_score']} | final={r['is_final']} | synthesis={r['synthesis'][:80] if r['synthesis'] else ''}...")
        if len(rows_to_upsert) > 10:
            print(f"  ... and {len(rows_to_upsert) - 10} more")
        return stats

    # Write strategy: use a temp table + MERGE DML.
    # This handles upserts correctly and protects finalized rows.
    # Steps:
    #   1. Load rows into a temp table via streaming insert
    #   2. MERGE from temp table into the real table
    #   3. Drop the temp table
    if rows_to_upsert:
        table_ref = f"{project_id}.{dataset_id}.{COMPANY_MONTHLY_SUMMARY_TABLE}"
        full_table = f"`{table_ref}`"
        temp_table_name = f"{COMPANY_MONTHLY_SUMMARY_TABLE}_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        temp_table_ref = f"{project_id}.{dataset_id}.{temp_table_name}"
        temp_full = f"`{temp_table_ref}`"

        # Step 1: Create temp table with same schema
        print(f"Creating temp table {temp_table_name}...")
        _ensure_table(client, dataset_id, temp_table_name, _COMPANY_MONTHLY_SUMMARY_SCHEMA)

        # Step 2: Stream rows into temp table
        print(f"Loading {len(rows_to_upsert)} rows into temp table...")
        batch_size = 500
        for i in range(0, len(rows_to_upsert), batch_size):
            batch = rows_to_upsert[i:i + batch_size]
            try:
                errors = client.insert_rows_json(temp_table_ref, batch)
                if errors:
                    print(f"Temp table insert errors: {errors[:3]}")
            except Exception as e:
                print(f"Temp table insert failed: {e}")

        # Step 3: Wait a moment for streaming buffer, then MERGE
        import time
        print("Waiting for streaming buffer to settle...")
        time.sleep(10)

        print("Running MERGE into target table...")
        merge_sql = f"""
        MERGE {full_table} AS target
        USING {temp_full} AS source
        ON target.id = source.id
        WHEN MATCHED AND target.is_final = FALSE THEN
            UPDATE SET
                avg_score = source.avg_score,
                run_count = source.run_count,
                synthesis = source.synthesis,
                is_final = source.is_final,
                updated_at = source.updated_at
        WHEN NOT MATCHED THEN
            INSERT (id, month, prompt_id, company, platform, avg_score, run_count, synthesis, is_final, updated_at)
            VALUES (source.id, source.month, source.prompt_id, source.company, source.platform,
                    source.avg_score, source.run_count, source.synthesis, source.is_final, source.updated_at)
        """
        try:
            job = client.query(merge_sql)
            job.result()
            stats["rows_written"] = len(rows_to_upsert)
            print(f"  MERGE complete: {job.num_dml_affected_rows} rows affected")
        except Exception as e:
            print(f"MERGE failed: {e}")
            print("Falling back to direct streaming insert (may create duplicates on re-run)...")
            for i in range(0, len(rows_to_upsert), batch_size):
                batch = rows_to_upsert[i:i + batch_size]
                try:
                    errors = client.insert_rows_json(table_ref, batch)
                    if not errors:
                        stats["rows_written"] += len(batch)
                except Exception as e2:
                    print(f"Fallback insert failed: {e2}")

        # Step 4: Drop temp table
        try:
            client.delete_table(temp_table_ref, not_found_ok=True)
            print(f"Dropped temp table {temp_table_name}")
        except Exception:
            print(f"Warning: Could not drop temp table {temp_table_name}")

    print(f"Monthly refresh complete: {stats}")
    return stats


# ---------------------------------------------------------------------------
# Monthly summary: load for webapps
# ---------------------------------------------------------------------------

def load_company_data_from_monthly(
    project_id: str = DEFAULT_PROJECT,
    dataset_id: str = DEFAULT_DATASET,
    company_filter: Optional[set] = None,
) -> tuple:
    """
    Load company evaluation data from the monthly summary table.

    Returns the same (raw_responses, company_names) tuple as load_company_data_from_bq()
    so the webapp processing code doesn't change.

    Args:
        project_id: GCP project ID
        dataset_id: BigQuery dataset name
        company_filter: If provided, only load data for these company names

    Returns:
        (raw_responses, company_names) where:
        - raw_responses[(platform, prompt_id, company)] = {
            "prompt_id", "company", "answer", "score", "question", "model",
            "sources": []
          }
        - company_names = set of all company names
    """
    client = get_client(project_id)
    raw_responses = {}
    company_names = set()

    full_table = f"`{project_id}.{dataset_id}.{COMPANY_MONTHLY_SUMMARY_TABLE}`"

    company_where = ""
    if company_filter:
        escaped = [c.replace("'", "\\'") for c in company_filter]
        company_list = ", ".join(f"'{c}'" for c in escaped)
        company_where = f"AND company IN ({company_list})"

    # Load the latest month's data for each (prompt_id, company, platform)
    query = f"""
    WITH latest_month AS (
        SELECT MAX(month) as max_month
        FROM {full_table}
        WHERE 1=1 {company_where}
    )
    SELECT s.*
    FROM {full_table} s, latest_month lm
    WHERE s.month = lm.max_month
    {company_where}
    """

    try:
        rows = list(client.query(query).result())
    except Exception as e:
        print(f"Warning: Failed to query {COMPANY_MONTHLY_SUMMARY_TABLE}: {e}")
        return raw_responses, company_names

    for row in rows:
        platform = row.platform
        prompt_id = row.prompt_id
        company = row.company
        company_names.add(company)

        entry = {
            "prompt_id": prompt_id,
            "company": company,
            "answer": row.synthesis or "",
            "score": row.avg_score,
            "question": "",
            "model": platform,
            "sources": [],
        }
        raw_responses[(platform, prompt_id, company)] = entry

    return raw_responses, company_names


# ---------------------------------------------------------------------------
# Legacy: upload_entity_mention (kept for backward compat)
# ---------------------------------------------------------------------------

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
    """Legacy: Upload a single entity mention to the old entity_mentions table."""
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
