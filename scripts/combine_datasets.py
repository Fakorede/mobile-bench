#!/usr/bin/env python3
"""
Script to combine all dataset files from mobiledev-bench/data/results/
and produce both JSONL and CSV versions.
"""

import json
import csv
import glob
import os
from pathlib import Path
from typing import List, Dict, Any


def find_dataset_files(base_path: str = "mobiledev-bench/data/results") -> List[str]:
    """Find all dataset.jsonl files in the results directory."""
    pattern = os.path.join(base_path, "**", "builds", "*_dataset.jsonl")
    files = glob.glob(pattern, recursive=True)
    return sorted(files)


def load_jsonl_file(filepath: str) -> List[Dict[str, Any]]:
    """Load a JSONL file and return list of records."""
    records = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Error parsing line {line_num} in {filepath}: {e}")
    return records


def flatten_record_for_csv(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested structures for CSV export."""
    flat = {}

    # Basic fields
    flat['org'] = record.get('org', '')
    flat['repo'] = record.get('repo', '')
    flat['number'] = record.get('number', '')
    flat['state'] = record.get('state', '')
    flat['title'] = record.get('title', '')
    flat['body'] = record.get('body', '')

    # Base information
    base = record.get('base', {})
    flat['base_label'] = base.get('label', '')
    flat['base_ref'] = base.get('ref', '')
    flat['base_sha'] = base.get('sha', '')

    # Resolved issues (combine into single field)
    resolved_issues = record.get('resolved_issues', [])
    flat['resolved_issues_count'] = len(resolved_issues)
    flat['resolved_issues_numbers'] = ','.join(str(issue.get('number', '')) for issue in resolved_issues)

    # Patches
    flat['fix_patch'] = record.get('fix_patch', '')
    flat['test_patch'] = record.get('test_patch', '')

    # Other fields
    flat['tag'] = record.get('tag', '')
    flat['number_interval'] = record.get('number_interval', '')
    flat['lang'] = record.get('lang', '')
    flat['test_command'] = record.get('test_command', '')

    # Fixed tests (flatten to JSON string for CSV)
    fixed_tests = record.get('fixed_tests', {})
    if fixed_tests:
        flat['fixed_tests_json'] = json.dumps(fixed_tests)
        flat['fixed_tests_count'] = len(fixed_tests)
    else:
        flat['fixed_tests_json'] = ''
        flat['fixed_tests_count'] = 0

    return flat


def convert_jsonl_to_csv(jsonl_path: str) -> str:
    """Convert a single JSONL file to CSV at the same location."""
    csv_path = jsonl_path.replace('.jsonl', '.csv')

    print(f"  Converting {os.path.basename(jsonl_path)} to CSV...")
    records = load_jsonl_file(jsonl_path)

    if not records:
        print(f"  Warning: No records found in {jsonl_path}")
        return csv_path

    # Flatten all records
    flat_records = [flatten_record_for_csv(record) for record in records]

    # Get all unique field names
    fieldnames = set()
    for record in flat_records:
        fieldnames.update(record.keys())
    fieldnames = sorted(fieldnames)

    # Write CSV
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_records)

    return csv_path


def combine_datasets(output_jsonl: str = "combined_dataset.jsonl",
                     output_csv: str = "combined_dataset.csv",
                     base_path: str = "mobiledev-bench/data/results",
                     convert_individual: bool = True):
    """Combine all dataset files and produce JSONL and CSV outputs."""

    print("Finding dataset files...")
    dataset_files = find_dataset_files(base_path)

    if not dataset_files:
        print(f"No dataset files found in {base_path}")
        return

    print(f"Found {len(dataset_files)} dataset files:")
    for f in dataset_files:
        print(f"  - {f}")

    # Convert individual files to CSV
    if convert_individual:
        print("\nConverting individual JSONL files to CSV...")
        for filepath in dataset_files:
            convert_jsonl_to_csv(filepath)

    print("\nCombining datasets...")
    all_records = []
    stats = {}

    for filepath in dataset_files:
        print(f"Processing {filepath}...")
        records = load_jsonl_file(filepath)
        all_records.extend(records)
        stats[filepath] = len(records)

    print(f"\nTotal records collected: {len(all_records)}")

    # Write combined JSONL
    print(f"\nWriting combined JSONL to {output_jsonl}...")
    with open(output_jsonl, 'w', encoding='utf-8') as f:
        for record in all_records:
            f.write(json.dumps(record) + '\n')

    # Write CSV
    print(f"Writing CSV to {output_csv}...")
    if all_records:
        # Flatten all records
        flat_records = [flatten_record_for_csv(record) for record in all_records]

        # Get all unique field names
        fieldnames = set()
        for record in flat_records:
            fieldnames.update(record.keys())
        fieldnames = sorted(fieldnames)

        with open(output_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_records)

    # Print statistics
    print("\n" + "="*60)
    print("Statistics by file:")
    print("="*60)
    for filepath, count in stats.items():
        print(f"{os.path.basename(filepath)}: {count} records")

    print("\n" + "="*60)
    print(f"Combined {len(all_records)} total records")
    print(f"Output files:")
    print(f"  - {output_jsonl}")
    print(f"  - {output_csv}")
    print("="*60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Combine dataset files from mobiledev-bench/data/results/"
    )
    parser.add_argument(
        "--base-path",
        default="mobiledev-bench/data/results",
        help="Base path to search for dataset files (default: mobiledev-bench/data/results)"
    )
    parser.add_argument(
        "--output-jsonl",
        default="combined_dataset.jsonl",
        help="Output JSONL file path (default: combined_dataset.jsonl)"
    )
    parser.add_argument(
        "--output-csv",
        default="combined_dataset.csv",
        help="Output CSV file path (default: combined_dataset.csv)"
    )
    parser.add_argument(
        "--skip-individual",
        action="store_true",
        help="Skip converting individual JSONL files to CSV"
    )

    args = parser.parse_args()

    combine_datasets(
        output_jsonl=args.output_jsonl,
        output_csv=args.output_csv,
        base_path=args.base_path,
        convert_individual=not args.skip_individual
    )
