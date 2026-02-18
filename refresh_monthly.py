#!/usr/bin/env python3
"""
Monthly Summary Refresh Script

Refreshes the company_monthly_summary BigQuery table from raw per-prompt tables.
For past months, generates AI synthesis via Claude API.
For the current month, uses the last available explanation.

Usage:
    python refresh_monthly.py                          # refresh all
    python refresh_monthly.py --company "Photonic Inc." # refresh one company
    python refresh_monthly.py --dry-run                 # show what would be updated
"""

import argparse

from bq_helper import ensure_all_tables_exist, refresh_monthly_summaries


def main():
    parser = argparse.ArgumentParser(
        description="Refresh company monthly summary table in BigQuery"
    )
    parser.add_argument(
        "--company",
        type=str,
        help="Only refresh data for this company (can be specified multiple times)",
        action="append",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing to BigQuery",
    )
    args = parser.parse_args()

    # Ensure all tables exist (including the monthly summary table)
    print("Ensuring all tables exist...")
    ensure_all_tables_exist()

    company_filter = set(args.company) if args.company else None
    if company_filter:
        print(f"Filtering to companies: {company_filter}")

    print("Refreshing monthly summaries...")
    stats = refresh_monthly_summaries(
        company_filter=company_filter,
        dry_run=args.dry_run,
    )

    print("\nResults:")
    print(f"  Rows processed:   {stats['rows_processed']}")
    print(f"  Rows synthesized: {stats['rows_synthesized']}")
    print(f"  Rows written:     {stats['rows_written']}")

    if args.dry_run:
        print("\n(Dry run - no changes were made)")


if __name__ == "__main__":
    main()
