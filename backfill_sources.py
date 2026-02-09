#!/usr/bin/env python3
"""
Backfill sources_analysis table from existing result files.

This script processes all existing JSON result files and uploads
their sources to BigQuery.

Usage:
    python backfill_sources.py
    python backfill_sources.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from bq_helper import (
    upload_sources,
    ensure_all_tables_exist,
)


def process_results_folder(folder_path: Path, dry_run: bool = False) -> dict:
    """Process all JSON files in a results folder."""
    stats = {"files": 0, "sources": 0, "errors": 0}

    run_folder_name = folder_path.name

    for fname in os.listdir(folder_path):
        if not fname.endswith(".json"):
            continue

        fpath = folder_path / fname
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            sources = data.get("sources", [])
            if not sources:
                continue

            stats["files"] += 1
            stats["sources"] += len(sources)

            if not dry_run:
                success = upload_sources(data, run_folder_name)
                if not success:
                    stats["errors"] += 1
                    print(f"  Failed to upload sources from {fname}")
            else:
                print(f"  Would upload {len(sources)} sources from {fname}")

        except Exception as e:
            stats["errors"] += 1
            print(f"  Error processing {fname}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill sources_analysis from existing results")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without uploading")
    parser.add_argument("--folder", type=str, help="Process only a specific folder")
    args = parser.parse_args()

    results_root = Path("results")
    if not results_root.exists():
        print("No results folder found")
        return

    # Ensure tables exist
    if not args.dry_run:
        print("Ensuring BigQuery tables exist...")
        ensure_all_tables_exist()

    total_stats = {"folders": 0, "files": 0, "sources": 0, "errors": 0}

    # Get folders to process
    if args.folder:
        folders = [results_root / args.folder]
    else:
        folders = sorted([
            f for f in results_root.iterdir()
            if f.is_dir() and not f.name.startswith(".")
        ])

    for folder in folders:
        if not folder.exists():
            print(f"Folder not found: {folder}")
            continue

        print(f"\nProcessing {folder.name}...")
        stats = process_results_folder(folder, args.dry_run)

        if stats["files"] > 0:
            total_stats["folders"] += 1
            total_stats["files"] += stats["files"]
            total_stats["sources"] += stats["sources"]
            total_stats["errors"] += stats["errors"]
            print(f"  Processed {stats['files']} files with {stats['sources']} sources")

    print(f"\n{'DRY RUN ' if args.dry_run else ''}Summary:")
    print(f"  Folders processed: {total_stats['folders']}")
    print(f"  Files with sources: {total_stats['files']}")
    print(f"  Total sources: {total_stats['sources']}")
    if total_stats["errors"]:
        print(f"  Errors: {total_stats['errors']}")


if __name__ == "__main__":
    main()
