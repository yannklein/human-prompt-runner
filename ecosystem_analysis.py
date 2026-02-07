#!/usr/bin/env python3
"""
Ecosystem Analysis Module

Analyzes ecosystem-level data from P1-P9 prompts (company ecosystem) and VP1-VP5 prompts (VC ecosystem).
Supports time-series analysis across multiple runs.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Optional


def _normalize_ai_name(model_name: str) -> str:
    """Normalize model name to standard AI platform name."""
    model_lower = model_name.lower()
    if "chatgpt" in model_lower:
        return "chatgpt"
    elif "gemini" in model_lower:
        return "gemini"
    elif "perplexity" in model_lower:
        return "perplexity"
    return model_name


def _extract_date_from_folder(folder_name: str) -> Optional[datetime]:
    """Extract datetime from folder name like '2026-01-28_10-35-01_gemini'."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", folder_name)
    if match:
        date_str = match.group(1)
        time_str = match.group(2).replace("-", ":")
        return datetime.fromisoformat(f"{date_str}T{time_str}")
    return None


def _extract_platform_from_folder(folder_name: str) -> Optional[str]:
    """Extract platform from folder name suffix."""
    if folder_name.endswith("_chatgpt_vc"):
        return "chatgpt_vc"
    elif folder_name.endswith("_gemini_vc"):
        return "gemini_vc"
    elif folder_name.endswith("_perplexity_vc"):
        return "perplexity_vc"
    elif folder_name.endswith("_chatgpt"):
        return "chatgpt"
    elif folder_name.endswith("_gemini"):
        return "gemini"
    elif folder_name.endswith("_perplexity"):
        return "perplexity"
    return None


ECOSYSTEM_COMPANY_PROMPTS = {
    "P1": "Top Applications",
    "P2": "Top Countries",
    "P3": "Most Promising Companies",
    "P4": "Best Teams",
    "P5": "Leading Labs/Universities",
    "P6": "Key Figures/Founders",
    "P7": "Commercialization Challenges",
    "P8": "Latest Breakthroughs",
    "P9": "Predicted Breakthroughs",
}

ECOSYSTEM_VC_PROMPTS = {
    "VP1": "Top VCs in Category",
    "VP2": "Investment Thesis",
    "VP3": "Portfolio Companies",
    "VP4": "Key Partners/Advisors",
    "VP5": "Reputation in Ecosystem",
}


def find_all_ecosystem_folders(results_dir: str = "results") -> list[dict]:
    """Find all folders containing ecosystem data (P1-P9 files).

    Returns a list of dicts with folder info sorted by date.
    """
    results_path = Path(results_dir)
    if not results_path.exists():
        return []

    folders = []
    for d in results_path.iterdir():
        if not d.is_dir():
            continue

        # Check for ecosystem files (P1-P9 with _category suffix)
        ecosystem_files = list(d.glob("P[1-9]_*.json"))
        if not ecosystem_files:
            continue

        folder_date = _extract_date_from_folder(d.name)
        platform = _extract_platform_from_folder(d.name)

        # Try to get platform from first file if not in folder name
        if not platform and ecosystem_files:
            with open(ecosystem_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
                platform = _normalize_ai_name(data.get("model", "unknown"))

        folders.append({
            "path": str(d),
            "name": d.name,
            "date": folder_date,
            "platform": platform or "unknown",
            "ecosystem_file_count": len(ecosystem_files),
        })

    return sorted(folders, key=lambda x: x["date"] or datetime.min)


def load_ecosystem_data_from_folder(folder_path: str) -> dict:
    """Load all ecosystem data from a single folder.

    Returns dict with prompt_id -> data mapping.
    """
    folder = Path(folder_path)
    data = {}

    for json_file in folder.glob("P[1-9]_*.json"):
        with open(json_file, "r", encoding="utf-8") as f:
            content = json.load(f)

        prompt_id = content.get("prompt_id")
        if prompt_id:
            data[prompt_id] = {
                "prompt_id": prompt_id,
                "question": content.get("question", ""),
                "answer": content.get("answer", ""),
                "timestamp": content.get("timestamp"),
                "model": _normalize_ai_name(content.get("model", "")),
                "sources": content.get("sources", []),
            }

    return data


def load_all_ecosystem_data(results_dir: str = "results") -> dict:
    """Load ecosystem data from all runs, organized by date and platform.

    Returns dict with structure:
    {
        "runs": [
            {
                "date": datetime,
                "date_str": "2026-01-28",
                "platform": "chatgpt",
                "folder": "2026-01-28_12-31-31_chatgpt",
                "prompts": {
                    "P1": {...},
                    "P2": {...},
                    ...
                }
            },
            ...
        ],
        "by_prompt": {
            "P1": [
                {"date": ..., "platform": ..., "data": ...},
                ...
            ],
            ...
        }
    }
    """
    folders = find_all_ecosystem_folders(results_dir)

    runs = []
    by_prompt = defaultdict(list)

    for folder_info in folders:
        prompts_data = load_ecosystem_data_from_folder(folder_info["path"])

        run = {
            "date": folder_info["date"],
            "date_str": folder_info["date"].strftime("%Y-%m-%d") if folder_info["date"] else "unknown",
            "platform": folder_info["platform"],
            "folder": folder_info["name"],
            "prompts": prompts_data,
        }
        runs.append(run)

        # Index by prompt for time-series analysis
        for prompt_id, prompt_data in prompts_data.items():
            by_prompt[prompt_id].append({
                "date": folder_info["date"],
                "date_str": run["date_str"],
                "platform": folder_info["platform"],
                "data": prompt_data,
            })

    return {
        "runs": runs,
        "by_prompt": dict(by_prompt),
    }


def _normalize_entity_name(name: str) -> str:
    """Normalize entity name for comparison."""
    # Remove common suffixes and clean up
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # Remove trailing parentheses
    name = re.sub(r"[*_\"]", "", name)  # Remove markdown/quotes
    name = name.replace("‑", "-")  # Normalize unicode non-breaking hyphen
    # Remove common company suffixes for better matching
    name = re.sub(r",?\s*(Inc\.?|Corp\.?|Ltd\.?|LLC|GmbH|AG)\.?\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()  # Normalize whitespace
    return name.lower()


def _extract_entity_from_title(title: str) -> dict:
    """Extract entity name and type from a ranking title."""
    # Clean the title - remove markdown and normalize whitespace/tabs
    title = re.sub(r"[*_]", "", title).strip()
    title = re.sub(r"\t+", " ", title)  # Replace tabs with space

    # Try to extract entity name (usually the first part before explanatory text)
    # Pattern: "Entity Name - description" or "Entity Name: description"
    # Note: Use " - " or tab as separator, handle various dash types including unicode non-breaking hyphen
    match = re.match(r"^(.+?)\s+[\-–—‑:]\s+.+$", title)
    if match:
        entity = match.group(1).strip()
    else:
        # Fallback: take until comma or the whole thing if no comma
        parts = title.split(",", 1)
        entity = parts[0].strip()

    # Remove common prefixes
    entity = re.sub(r"^(?:The\s+|A\s+|An\s+)", "", entity, flags=re.IGNORECASE)

    # Remove trailing parenthetical notes like "(formerly X)"
    entity = re.sub(r"\s*\([^)]*(?:formerly|combined|including)[^)]*\)\s*$", "", entity, flags=re.IGNORECASE)

    # Detect entity type based on patterns
    entity_type = "unknown"

    # Known quantum computing/sensing companies (common names that don't have obvious suffixes)
    known_companies = [
        # Quantum computing
        "IonQ", "Rigetti", "D-Wave", "Xanadu", "PsiQuantum", "Zapata", "QC Ware",
        "Classiq", "Q-CTRL", "Quantum Machines", "ColdQuanta", "Atom Computing",
        "QuEra", "Pasqal", "Alpine Quantum", "Quantinuum", "IBM Quantum", "Google Quantum",
        "Microsoft Quantum", "Amazon Braket", "Honeywell", "Intel",
        # Quantum sensing
        "Qnami", "AOSense", "Nomad Atomics", "QuSpin", "EuQlid", "Infleqtion",
        "SandboxAQ", "Exail", "Muquans", "Q.ANT", "Lockheed Martin", "Vector Atomic",
    ]
    # Normalize unicode hyphens for comparison
    entity_normalized = entity.replace("‑", "-").lower()
    is_known_company = any(
        c.lower() in entity_normalized or entity_normalized in c.lower()
        for c in known_companies
    )

    if is_known_company:
        entity_type = "company"
    elif re.search(r"(?:Inc\.?|Corp\.?|Ltd\.?|LLC|GmbH|AG|SA|BV|Co\.|Company|Technologies|Labs?|Quantum\s*AI|Systems|Computing|Atomics?)", entity, re.IGNORECASE):
        entity_type = "company"
    elif re.search(r"(?:University|Institute|College|Lab(?:oratory)?|Center|Centre|MIT|ETH|Stanford|Harvard|Oxford|Cambridge|Caltech|Berkeley)", entity, re.IGNORECASE):
        entity_type = "institution"
    elif re.search(r"(?:USA|UK|United States|United Kingdom|China|Germany|Japan|Canada|Australia|Switzerland|Netherlands|France|Israel|Singapore|South Korea|India)", entity, re.IGNORECASE):
        entity_type = "country"
    elif re.search(r"(?:Dr\.|Prof\.|PhD|CEO|Founder|Mr\.|Ms\.)", title, re.IGNORECASE):
        entity_type = "person"

    return {
        "name": entity[:100],
        "normalized": _normalize_entity_name(entity),
        "type": entity_type,
        "full_title": title[:200],
    }


def extract_rankings_from_answer(answer: str) -> list[dict]:
    """Extract ranked items from an answer text.

    Returns list of dicts with rank, entity info, and explanation.
    """
    rankings = []

    # Split into lines for better parsing
    lines = answer.split("\n")
    current_rank = None
    current_title = ""
    current_explanation = ""

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check for tabular format: "1\tCompany\tCategory\tDescription"
        # This is common in Gemini outputs
        if "\t" in line_stripped:
            parts = line_stripped.split("\t")
            if len(parts) >= 2 and parts[0].isdigit():
                # Save previous item
                if current_rank is not None and current_title:
                    entity = _extract_entity_from_title(current_title)
                    rankings.append({
                        "rank": current_rank,
                        "entity": entity,
                        "title": current_title[:200],
                        "explanation": current_explanation.strip()[:800],
                    })

                current_rank = int(parts[0])
                current_title = parts[1].strip()  # Company name is second column
                # Rest of columns become explanation
                current_explanation = " ".join(parts[2:]) if len(parts) > 2 else ""
                continue

        # Check for numbered item start
        # Patterns: "1. Title", "1) Title", "1: Title", "#1 Title", "Rank 1: Title"
        rank_match = re.match(r"^(?:#|Rank\s*)?(\d+)[\.\)\:\s]+(.+)$", line_stripped, re.IGNORECASE)

        if rank_match:
            # Save previous item if exists
            if current_rank is not None and current_title:
                entity = _extract_entity_from_title(current_title)
                rankings.append({
                    "rank": current_rank,
                    "entity": entity,
                    "title": current_title[:200],
                    "explanation": current_explanation.strip()[:800],
                })

            current_rank = int(rank_match.group(1))
            current_title = rank_match.group(2).strip()
            current_explanation = ""
        elif current_rank is not None:
            # Continuation of explanation
            current_explanation += " " + line_stripped

    # Don't forget the last item
    if current_rank is not None and current_title:
        entity = _extract_entity_from_title(current_title)
        rankings.append({
            "rank": current_rank,
            "entity": entity,
            "title": current_title[:200],
            "explanation": current_explanation.strip()[:800],
        })

    # Deduplicate by rank
    seen_ranks = set()
    unique_rankings = []
    for r in sorted(rankings, key=lambda x: x["rank"]):
        if r["rank"] not in seen_ranks:
            seen_ranks.add(r["rank"])
            unique_rankings.append(r)

    return unique_rankings


def compare_rankings_over_time(prompt_data_list: list[dict]) -> dict:
    """Compare rankings for a prompt across multiple time points.

    Returns analysis of how rankings changed over time.
    """
    timeline = []
    all_entities = {}  # normalized_name -> entity info

    for entry in prompt_data_list:
        rankings = extract_rankings_from_answer(entry["data"]["answer"])

        # Build entity lookup
        entities_in_run = {}
        for r in rankings:
            norm_name = r["entity"]["normalized"]
            entities_in_run[norm_name] = r["rank"]
            if norm_name not in all_entities:
                all_entities[norm_name] = r["entity"]

        timeline.append({
            "date": entry["date_str"],
            "platform": entry["platform"],
            "folder": entry.get("folder", ""),
            "rankings": rankings,
            "entities_ranked": entities_in_run,
            "sources": entry["data"].get("sources", []),
        })

    # Track position changes for each entity
    entity_history = {}
    for norm_name, entity_info in all_entities.items():
        positions = []
        for t in timeline:
            pos = t["entities_ranked"].get(norm_name)
            positions.append({
                "date": t["date"],
                "platform": t["platform"],
                "position": pos,
            })
        entity_history[norm_name] = {
            "entity": entity_info,
            "positions": positions,
        }

    return {
        "timeline": timeline,
        "entity_history": entity_history,
        "all_entities": all_entities,
        "total_entities_seen": len(all_entities),
    }


def compare_two_snapshots(data1: dict, data2: dict) -> dict:
    """Compare rankings between two specific snapshots.

    Returns detailed analysis of changes including:
    - New entries, removed entries, position changes
    - Source differences
    - Explanation of likely reasons for changes
    """
    rankings1 = extract_rankings_from_answer(data1["answer"])
    rankings2 = extract_rankings_from_answer(data2["answer"])

    # Build entity lookups
    entities1 = {r["entity"]["normalized"]: r for r in rankings1}
    entities2 = {r["entity"]["normalized"]: r for r in rankings2}

    all_entities = set(entities1.keys()) | set(entities2.keys())

    changes = []
    for norm_name in all_entities:
        r1 = entities1.get(norm_name)
        r2 = entities2.get(norm_name)

        if r1 and r2:
            # Both present - check for position change
            rank_change = r1["rank"] - r2["rank"]
            if rank_change != 0:
                changes.append({
                    "type": "moved",
                    "entity": r2["entity"],
                    "old_rank": r1["rank"],
                    "new_rank": r2["rank"],
                    "change": rank_change,  # Positive = moved up
                    "old_explanation": r1.get("explanation", ""),
                    "new_explanation": r2.get("explanation", ""),
                })
            else:
                changes.append({
                    "type": "unchanged",
                    "entity": r2["entity"],
                    "rank": r2["rank"],
                })
        elif r1 and not r2:
            # Removed from rankings
            changes.append({
                "type": "removed",
                "entity": r1["entity"],
                "old_rank": r1["rank"],
                "old_explanation": r1.get("explanation", ""),
            })
        elif r2 and not r1:
            # New entry
            changes.append({
                "type": "new",
                "entity": r2["entity"],
                "new_rank": r2["rank"],
                "new_explanation": r2.get("explanation", ""),
            })

    # Sort changes by significance
    def change_priority(c):
        if c["type"] == "new":
            return (0, c["new_rank"])
        elif c["type"] == "removed":
            return (1, c["old_rank"])
        elif c["type"] == "moved":
            return (2, -abs(c["change"]))
        else:
            return (3, c.get("rank", 99))

    changes.sort(key=change_priority)

    # Compare sources
    sources1 = {s.get("url", ""): s for s in data1.get("sources", [])}
    sources2 = {s.get("url", ""): s for s in data2.get("sources", [])}

    new_sources = [s for url, s in sources2.items() if url not in sources1]
    removed_sources = [s for url, s in sources1.items() if url not in sources2]

    # Generate change summary
    summary_parts = []
    moved_up = [c for c in changes if c["type"] == "moved" and c["change"] > 0]
    moved_down = [c for c in changes if c["type"] == "moved" and c["change"] < 0]
    new_entries = [c for c in changes if c["type"] == "new"]
    removed_entries = [c for c in changes if c["type"] == "removed"]

    if new_entries:
        names = [c["entity"]["name"] for c in new_entries[:3]]
        summary_parts.append(f"New: {', '.join(names)}")
    if removed_entries:
        names = [c["entity"]["name"] for c in removed_entries[:3]]
        summary_parts.append(f"Dropped: {', '.join(names)}")
    if moved_up:
        names = [f"{c['entity']['name']} (+{c['change']})" for c in moved_up[:3]]
        summary_parts.append(f"Moved up: {', '.join(names)}")
    if moved_down:
        names = [f"{c['entity']['name']} ({c['change']})" for c in moved_down[:3]]
        summary_parts.append(f"Moved down: {', '.join(names)}")

    return {
        "changes": changes,
        "summary": "; ".join(summary_parts) if summary_parts else "No significant changes",
        "stats": {
            "total_in_old": len(rankings1),
            "total_in_new": len(rankings2),
            "new_entries": len(new_entries),
            "removed_entries": len(removed_entries),
            "moved_up": len(moved_up),
            "moved_down": len(moved_down),
            "unchanged": len([c for c in changes if c["type"] == "unchanged"]),
        },
        "source_changes": {
            "new_sources": new_sources,
            "removed_sources": removed_sources,
        },
        "date1": data1.get("timestamp", ""),
        "date2": data2.get("timestamp", ""),
    }


def get_latest_ecosystem_snapshot(results_dir: str = "results") -> dict:
    """Get the most recent ecosystem data across all platforms.

    Groups by platform and returns the latest data point for each.
    """
    all_data = load_all_ecosystem_data(results_dir)

    latest_by_platform = {}
    for run in reversed(all_data["runs"]):
        platform = run["platform"]
        if platform not in latest_by_platform:
            latest_by_platform[platform] = run

    return {
        "platforms": latest_by_platform,
        "prompt_labels": ECOSYSTEM_COMPANY_PROMPTS,
    }


# Source type categorization
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
    "Pitch / Valuation Platform": [
        "quickmarketpitch", "dealroom", "pitchbook", "crunchbase",
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
    "Consulting / Strategy": [
        "mckinsey", "bcg.com", "bain.com", "deloitte", "pwc.com", "ey.com", "kpmg",
    ],
    "Market Research / Data": [
        "statista", "grandviewresearch", "marketsandmarkets", "mordorintelligence",
        "biforesight", "idc.com", "gartner", "forrester", "futuremarketsinc",
        "skyquestt", "dataintelo", "industryresearch", "transparencymarketresearch",
        "alliedmarketresearch", "verifiedmarketreports", "researchandmarkets",
    ],
    "Government / Policy": [
        "gov.uk", "gov.us", "europa.eu", "nist.gov", "darpa", "nsf.gov",
    ],
    "Podcast / Media Network": [
        "epodcastnetwork", "podcast", "spotify", "apple.com/podcast",
    ],
}


def _categorize_source(domain: str) -> str:
    """Categorize a source domain by type."""
    domain_lower = domain.lower()
    for category, patterns in SOURCE_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in domain_lower:
                return category
    return "Other"


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return ""
    # Remove protocol
    url = re.sub(r"^https?://", "", url)
    # Remove www.
    url = re.sub(r"^www\.", "", url)
    # Get domain (before first /)
    domain = url.split("/")[0]
    return domain.lower()


def gather_prompt_results(prompt_id: str, results_dir: str = "results") -> dict:
    """Gather all results for a specific prompt across all runs.

    Returns a table-like structure with Date, Source (AI), Entity, Categorisation, Explanation.
    """
    all_data = load_all_ecosystem_data(results_dir)

    if prompt_id not in all_data["by_prompt"]:
        return {"rows": [], "entities": {}, "prompt_id": prompt_id}

    rows = []
    entities_seen = {}  # Track all unique entities

    for entry in all_data["by_prompt"][prompt_id]:
        date_str = entry["date_str"]
        platform = entry["platform"]
        answer = entry["data"]["answer"]

        rankings = extract_rankings_from_answer(answer)

        for r in rankings:
            entity_name = r["entity"]["name"]
            entity_type = r["entity"]["type"]
            normalized = r["entity"]["normalized"]

            # Track entity occurrences
            if normalized not in entities_seen:
                entities_seen[normalized] = {
                    "name": entity_name,
                    "type": entity_type,
                    "appearances": 0,
                    "ranks": [],
                }
            entities_seen[normalized]["appearances"] += 1
            entities_seen[normalized]["ranks"].append(r["rank"])

            rows.append({
                "date": date_str,
                "source": platform,
                "rank": r["rank"],
                "entity": entity_name,
                "entity_type": entity_type,
                "explanation": r.get("explanation", "")[:300],
            })

    # Calculate average rank for each entity
    for entity_data in entities_seen.values():
        ranks = entity_data["ranks"]
        entity_data["avg_rank"] = sum(ranks) / len(ranks) if ranks else 0
        entity_data["best_rank"] = min(ranks) if ranks else 0

    return {
        "prompt_id": prompt_id,
        "prompt_label": ECOSYSTEM_COMPANY_PROMPTS.get(prompt_id, prompt_id),
        "rows": rows,
        "entities": entities_seen,
        "total_responses": len(all_data["by_prompt"][prompt_id]),
    }


def gather_prompt_sources(prompt_id: str, results_dir: str = "results") -> dict:
    """Gather all sources used for a specific prompt across all runs.

    Returns source frequency analysis with categorization.
    """
    all_data = load_all_ecosystem_data(results_dir)

    if prompt_id not in all_data["by_prompt"]:
        return {"sources": [], "by_type": {}, "prompt_id": prompt_id}

    source_counts = {}  # domain -> count
    source_details = {}  # domain -> {urls: set, titles: set}
    sources_by_run = []  # For the detailed sources table

    for entry in all_data["by_prompt"][prompt_id]:
        date_str = entry["date_str"]
        platform = entry["platform"]
        sources = entry["data"].get("sources", [])

        for source in sources:
            url = source.get("url", "")
            title = source.get("title", "")
            domain = _extract_domain(url)

            if not domain:
                continue

            # Count by domain
            source_counts[domain] = source_counts.get(domain, 0) + 1

            # Track details
            if domain not in source_details:
                source_details[domain] = {"urls": set(), "titles": set()}
            source_details[domain]["urls"].add(url)
            if title:
                source_details[domain]["titles"].add(title[:100])

            # Add to detailed list
            sources_by_run.append({
                "date": date_str,
                "source": platform,
                "domain": domain,
                "url": url,
                "title": title[:100] if title else "",
            })

    # Build frequency table with categorization
    frequency_table = []
    for domain, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        category = _categorize_source(domain)
        frequency_table.append({
            "domain": domain,
            "frequency": count,
            "type": category,
            "sample_urls": list(source_details[domain]["urls"])[:3],
        })

    # Aggregate by type
    by_type = {}
    for item in frequency_table:
        t = item["type"]
        if t not in by_type:
            by_type[t] = {"count": 0, "domains": []}
        by_type[t]["count"] += item["frequency"]
        by_type[t]["domains"].append(item["domain"])

    return {
        "prompt_id": prompt_id,
        "prompt_label": ECOSYSTEM_COMPANY_PROMPTS.get(prompt_id, prompt_id),
        "frequency_table": frequency_table,
        "by_type": by_type,
        "sources_detail": sources_by_run,
        "total_citations": sum(source_counts.values()),
        "unique_domains": len(source_counts),
    }


def get_prompt_intelligence(prompt_id: str, results_dir: str = "results") -> dict:
    """Get full intelligence report for a prompt.

    Combines results, sources, and analysis.
    """
    results = gather_prompt_results(prompt_id, results_dir)
    sources = gather_prompt_sources(prompt_id, results_dir)

    # Top entities by frequency
    top_entities = sorted(
        results["entities"].items(),
        key=lambda x: (-x[1]["appearances"], x[1]["avg_rank"])
    )[:15]

    # Top sources by frequency
    top_sources = sources["frequency_table"][:20]

    # Source type distribution
    type_distribution = [
        {"type": t, "count": data["count"], "domains": len(data["domains"])}
        for t, data in sorted(sources["by_type"].items(), key=lambda x: -x[1]["count"])
    ]

    return {
        "prompt_id": prompt_id,
        "prompt_label": results["prompt_label"],
        "summary": {
            "total_responses": results["total_responses"],
            "unique_entities": len(results["entities"]),
            "total_citations": sources["total_citations"],
            "unique_sources": sources["unique_domains"],
        },
        "top_entities": [
            {
                "name": name,
                "appearances": data["appearances"],
                "avg_rank": round(data["avg_rank"], 1),
                "best_rank": data["best_rank"],
                "type": data["type"],
            }
            for name, data in top_entities
        ],
        "top_sources": top_sources,
        "source_types": type_distribution,
        "results_table": results["rows"],
        "sources_table": sources["sources_detail"],
    }


if __name__ == "__main__":
    # Test loading
    print("Finding ecosystem folders...")
    folders = find_all_ecosystem_folders()
    print(f"Found {len(folders)} folders with ecosystem data:")
    for f in folders:
        print(f"  {f['name']}: {f['ecosystem_file_count']} files, platform={f['platform']}")

    print("\nLoading all ecosystem data...")
    all_data = load_all_ecosystem_data()
    print(f"Loaded {len(all_data['runs'])} runs")

    print("\nPrompt coverage:")
    for prompt_id, entries in all_data["by_prompt"].items():
        print(f"  {prompt_id}: {len(entries)} data points")

    print("\nLatest snapshot:")
    snapshot = get_latest_ecosystem_snapshot()
    for platform, run in snapshot["platforms"].items():
        print(f"  {platform}: {run['date_str']} ({len(run['prompts'])} prompts)")
