#!/usr/bin/env python3
"""
Script to compare files modified in gold patches vs model-generated patches.

Usage:
    python3 scripts/compare_patch_files.py 
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/flutter/zulip/builds/zulip__zulip-flutter_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/patch_comparison_results.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set

try:
    import unidiff
except ImportError:
    print("Error: unidiff library not found. Install with: pip install unidiff")
    sys.exit(1)


def get_modified_files_from_patch(patch_text: str) -> Set[str]:
    """
    Extracts filenames that are modified in a patch.

    Args:
        patch_text: The patch content as a string

    Returns:
        Set of file paths modified in the patch
    """
    if not patch_text or not patch_text.strip():
        return set()

    try:
        patch_set = unidiff.PatchSet(patch_text)
        modified_files = {
            patch_file.source_file.split("a/", 1)[-1]
            for patch_file in patch_set
        }
        return modified_files
    except Exception as e:
        print(f"Warning: Failed to parse patch: {e}", file=sys.stderr)
        return set()


def load_jsonl(file_path: Path) -> List[Dict]:
    """Load JSONL file and return list of JSON objects."""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse line {line_num} in {file_path}: {e}", file=sys.stderr)
    return data


def compare_patches(dataset_file: Path, patch_file: Path) -> Dict:
    """
    Compare files modified in gold patches vs model-generated patches.

    Args:
        dataset_file: Path to dataset JSONL file containing gold patches
        patch_file: Path to JSONL file containing model-generated patches

    Returns:
        Dictionary with comparison results
    """
    print(f"Loading dataset from: {dataset_file}")
    gold_data = load_jsonl(dataset_file)
    print(f"Loaded {len(gold_data)} gold instances")

    print(f"Loading patches from: {patch_file}")
    model_data = load_jsonl(patch_file)
    print(f"Loaded {len(model_data)} model-generated patches")

    # Create lookup dictionaries by instance ID
    # Instance ID is constructed from org/repo/number
    gold_by_id = {}
    for item in gold_data:
        instance_id = item.get('instance_id') or item.get('id')
        if not instance_id and all(k in item for k in ['org', 'repo', 'number']):
            instance_id = f"{item['org']}/{item['repo']}:pr-{item['number']}"
        if instance_id:
            gold_by_id[instance_id] = item

    model_by_id = {}
    for item in model_data:
        instance_id = item.get('instance_id') or item.get('id')
        if not instance_id and all(k in item for k in ['org', 'repo', 'number']):
            instance_id = f"{item['org']}/{item['repo']}:pr-{item['number']}"
        if instance_id:
            model_by_id[instance_id] = item

    results = {
        'total_instances': 0,
        'instances_with_overlap': 0,
        'instances_without_overlap': 0,
        'instances_missing_model_patch': 0,
        'instances_missing_gold_patch': 0,
        'total_gold_files': 0,
        'total_model_files': 0,
        'total_overlapping_files': 0,
        'details': []
    }

    # Find common instance IDs
    common_ids = set(gold_by_id.keys()) & set(model_by_id.keys())
    print(f"\nFound {len(common_ids)} common instances")

    if len(common_ids) == 0:
        print("Warning: No common instance IDs found between datasets!")
        print(f"Sample gold IDs: {list(gold_by_id.keys())[:5]}")
        print(f"Sample model IDs: {list(model_by_id.keys())[:5]}")

    for instance_id in sorted(common_ids):
        gold_item = gold_by_id[instance_id]
        model_item = model_by_id[instance_id]

        # Extract patches - try both 'fix_patch' and 'patch' attributes
        gold_patch = gold_item.get('fix_patch') or gold_item.get('patch', '')
        model_patch = model_item.get('fix_patch') or model_item.get('patch') or model_item.get('model_patch', '')

        if not gold_patch:
            results['instances_missing_gold_patch'] += 1
            continue

        if not model_patch:
            results['instances_missing_model_patch'] += 1
            continue

        # Extract modified files
        gold_files = get_modified_files_from_patch(gold_patch)
        model_files = get_modified_files_from_patch(model_patch)

        # Calculate overlap
        overlapping_files = gold_files & model_files

        results['total_instances'] += 1
        results['total_gold_files'] += len(gold_files)
        results['total_model_files'] += len(model_files)
        results['total_overlapping_files'] += len(overlapping_files)

        if overlapping_files:
            results['instances_with_overlap'] += 1
        else:
            results['instances_without_overlap'] += 1

        # Store detailed results
        instance_result = {
            'instance_id': instance_id,
            'gold_files': sorted(gold_files),
            'model_files': sorted(model_files),
            'overlapping_files': sorted(overlapping_files),
            'gold_file_count': len(gold_files),
            'model_file_count': len(model_files),
            'overlap_count': len(overlapping_files),
            'overlap_percentage': (len(overlapping_files) / len(gold_files) * 100) if gold_files else 0
        }
        results['details'].append(instance_result)

    return results


def print_summary(results: Dict):
    """Print a summary of the comparison results."""
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total instances compared: {results['total_instances']}")
    print(f"Instances with file overlap: {results['instances_with_overlap']}")
    print(f"Instances without file overlap: {results['instances_without_overlap']}")
    print(f"Instances missing model patch: {results['instances_missing_model_patch']}")
    print(f"Instances missing gold patch: {results['instances_missing_gold_patch']}")
    print()
    print(f"Total gold patch files: {results['total_gold_files']}")
    print(f"Total model patch files: {results['total_model_files']}")
    print(f"Total overlapping files: {results['total_overlapping_files']}")

    if results['total_instances'] > 0:
        avg_overlap = results['instances_with_overlap'] / results['total_instances'] * 100
        print(f"\nAverage overlap rate: {avg_overlap:.2f}%")

    print("\n" + "="*80)


def main():
    parser = argparse.ArgumentParser(
        description="Compare files modified in gold patches vs model-generated patches"
    )
    parser.add_argument(
        "--dataset_file",
        type=Path,
        required=True,
        help="Path to dataset JSONL file containing gold patches"
    )
    parser.add_argument(
        "--patch_file",
        type=Path,
        required=True,
        help="Path to JSONL file containing model-generated patches"
    )
    parser.add_argument(
        "--output_file",
        type=Path,
        required=False,
        help="Path to output JSON file for detailed results"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed results for each instance"
    )

    args = parser.parse_args()

    # Validate input files exist
    if not args.dataset_file.exists():
        print(f"Error: Dataset file not found: {args.dataset_file}", file=sys.stderr)
        sys.exit(1)

    if not args.patch_file.exists():
        print(f"Error: Patch file not found: {args.patch_file}", file=sys.stderr)
        sys.exit(1)

    # Compare patches
    results = compare_patches(args.dataset_file, args.patch_file)

    # Print summary
    print_summary(results)

    # Print verbose details if requested
    if args.verbose:
        print("\nDETAILED RESULTS")
        print("="*80)
        for detail in results['details']:
            print(f"\nInstance: {detail['instance_id']}")
            print(f"  Gold files ({detail['gold_file_count']}): {', '.join(detail['gold_files'])}")
            print(f"  Model files ({detail['model_file_count']}): {', '.join(detail['model_files'])}")
            print(f"  Overlapping ({detail['overlap_count']}): {', '.join(detail['overlapping_files']) if detail['overlapping_files'] else 'None'}")
            print(f"  Overlap: {detail['overlap_percentage']:.1f}%")

    # Save to output file if specified
    if args.output_file:
        print(f"\nSaving detailed results to: {args.output_file}")
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("Results saved successfully")


if __name__ == "__main__":
    main()
