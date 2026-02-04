#!/usr/bin/env python3
"""
Script to compare files modified in gold patches vs model-generated patches.

Usage:
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/flutter/zulip/builds/zulip__zulip-flutter_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/gpt_patch_comparison_results.csv

    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/flutter/talawa/builds/PalisadoesFoundation__talawa_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/talawa/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/talawa/gpt_patch_comparison_results.csv
    

    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/reactnative/rocketchat/builds/RocketChat__Rocket.Chat.ReactNative_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gpt_patch_comparison_results.csv

        
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/reactnative/expensify/builds/Expensify__App_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/expensify/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/expensify/gpt_patch_comparison_results.csv

    
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/reactnative/metamask/builds/MetaMask__metamask-mobile_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/metamask/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/metamask/gpt_patch_comparison_results.csv


    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/java/antennapod/builds/AntennaPod__AntennaPod_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/antennapod/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/antennapod/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/antennapod/gpt_patch_comparison_results.csv

    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/geto/builds/JackEblan__Geto_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/geto/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/geto/gpt_patch_comparison_results.csv

        
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/jerboa/builds/LemmyNet__jerboa_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_patch_comparison_results.csv
        
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/commons-app/builds/commons-app__apps-android-commons_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/commons-app/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/commons-app/gpt_patch_comparison_results.csv
        
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/medtimer/builds/Futsch1__medTimer_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/medtimer/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/medtimer/gpt_patch_comparison_results.csv
        
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/tusky/builds/tuskyapp__Tusky_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/tusky/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/tusky/gpt_patch_comparison_results.csv
        
    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/voice/builds/PaulWoitaschek__Voice_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/voice/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/voice/gpt_patch_comparison_results.csv
        

    python3 scripts/compare_patch_files.py \
        --dataset_file  /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/openhab/builds/openhab__openhab-android_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/openhab/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/openhab/gpt_patch_comparison_results.csv



    python3 scripts/compare_patch_files.py \
        --dataset_file /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/streetcomplete/builds/streetcomplete__StreetComplete_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/streetcomplete/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/streetcomplete/gpt_patch_comparison_results.csv

        
    python3 scripts/compare_patch_files.py \
        --dataset_file  /home/researchuser/dev/inri/mobiledev-bench/data/results/kotlin/neostumbler/builds/mjaakko__NeoStumbler_dataset.jsonl \
        --patch_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl \
        --output_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/neostumbler/gpt_patch_comparison_results.json \
        --csv_file /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/neostumbler/gpt_patch_comparison_results.csv


Step 2: combine csv files to excel (sonnet, gpt, qwen, gemini)
python3 scripts/combine_csv_to_excel.py \
    --csv_dir data/evaluation \
    --specific gpt




"""

import argparse
import csv
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


def get_file_extension(file_path: str) -> str:
    """
    Get the file extension from a file path.

    Args:
        file_path: Path to the file

    Returns:
        File extension (e.g., '.java', '.kt', '.xml') or 'no_extension'
    """
    from pathlib import Path as PathLib
    path = PathLib(file_path)
    if path.suffix:
        return path.suffix.lower()
    return 'no_extension'


def categorize_files_by_extension(files: Set[str]) -> Dict[str, int]:
    """
    Count files by their extension.

    Args:
        files: Set of file paths

    Returns:
        Dictionary mapping extension to count
    """
    from collections import defaultdict
    counts = defaultdict(int)
    for file_path in files:
        ext = get_file_extension(file_path)
        counts[ext] += 1
    return dict(counts)


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

    from collections import defaultdict

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

    # Aggregate extension counts across all instances
    aggregate_gold_extensions = defaultdict(int)
    aggregate_model_extensions = defaultdict(int)
    aggregate_overlap_extensions = defaultdict(int)

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

        # Categorize files by extension
        gold_extensions = categorize_files_by_extension(gold_files)
        model_extensions = categorize_files_by_extension(model_files)
        overlap_extensions = categorize_files_by_extension(overlapping_files)

        # Aggregate extension counts
        for ext, count in gold_extensions.items():
            aggregate_gold_extensions[ext] += count
        for ext, count in model_extensions.items():
            aggregate_model_extensions[ext] += count
        for ext, count in overlap_extensions.items():
            aggregate_overlap_extensions[ext] += count

        # Store detailed results
        instance_result = {
            'instance_id': instance_id,
            'gold_files': sorted(gold_files),
            'model_files': sorted(model_files),
            'overlapping_files': sorted(overlapping_files),
            'gold_file_count': len(gold_files),
            'model_file_count': len(model_files),
            'overlap_count': len(overlapping_files),
            'recall': (len(overlapping_files) / len(gold_files) * 100) if gold_files else 0,
            'precision': (len(overlapping_files) / len(model_files) * 100) if model_files else 0,
            'f1': (2 * len(overlapping_files) / (len(gold_files) + len(model_files)) * 100) if (gold_files or model_files) else 0,
            'gold_extensions': gold_extensions,
            'model_extensions': model_extensions,
            'overlap_extensions': overlap_extensions
        }
        results['details'].append(instance_result)

    # Add aggregated extension statistics to results
    results['extension_statistics'] = {
        'gold_extensions': dict(aggregate_gold_extensions),
        'model_extensions': dict(aggregate_model_extensions),
        'overlap_extensions': dict(aggregate_overlap_extensions)
    }

    return results


def save_to_csv(results: Dict, csv_file: Path):
    """
    Save comparison results to a CSV file.

    Args:
        results: Dictionary with comparison results
        csv_file: Path to output CSV file
    """
    print(f"\nSaving results to CSV: {csv_file}")
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Write header
        writer.writerow([
            'instance_id',
            'gold_file_count',
            'model_file_count',
            'overlap_count',
            'precision',
            'recall',
            'f1',
            'gold_files',
            'model_files',
            'overlapping_files',
            'gold_extensions',
            'model_extensions',
            'overlap_extensions'
        ])

        # Write data rows
        for detail in results['details']:
            # Format extensions as "ext: count" pairs
            gold_ext_str = '; '.join(f"{ext}: {count}" for ext, count in sorted(detail.get('gold_extensions', {}).items()))
            model_ext_str = '; '.join(f"{ext}: {count}" for ext, count in sorted(detail.get('model_extensions', {}).items()))
            overlap_ext_str = '; '.join(f"{ext}: {count}" for ext, count in sorted(detail.get('overlap_extensions', {}).items()))

            writer.writerow([
                detail['instance_id'],
                detail['gold_file_count'],
                detail['model_file_count'],
                detail['overlap_count'],
                f"{detail['precision']:.2f}",
                f"{detail['recall']:.2f}",
                f"{detail['f1']:.2f}",
                '; '.join(detail['gold_files']),
                '; '.join(detail['model_files']),
                '; '.join(detail['overlapping_files']),
                gold_ext_str,
                model_ext_str,
                overlap_ext_str
            ])

    print("CSV saved successfully")


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
        avg_precision = sum(d['precision'] for d in results['details']) / results['total_instances']
        avg_recall = sum(d['recall'] for d in results['details']) / results['total_instances']
        avg_f1 = sum(d['f1'] for d in results['details']) / results['total_instances']
        print(f"\nAverage Precision: {avg_precision:.2f}%")
        print(f"Average Recall:    {avg_recall:.2f}%")
        print(f"Average F1:        {avg_f1:.2f}%")

    # Print file type statistics
    if 'extension_statistics' in results:
        ext_stats = results['extension_statistics']
        print(f"\n{'='*80}")
        print("FILE TYPE BREAKDOWN")
        print(f"{'='*80}")

        all_extensions = set(ext_stats['gold_extensions'].keys()) | set(ext_stats['model_extensions'].keys())

        if all_extensions:
            print(f"{'Extension':<15} {'Gold':<10} {'Model':<10} {'Overlap':<10}")
            print(f"{'-'*45}")

            for ext in sorted(all_extensions):
                gold_count = ext_stats['gold_extensions'].get(ext, 0)
                model_count = ext_stats['model_extensions'].get(ext, 0)
                overlap_count = ext_stats['overlap_extensions'].get(ext, 0)
                print(f"{ext:<15} {gold_count:<10} {model_count:<10} {overlap_count:<10}")

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
        "--csv_file",
        type=Path,
        required=False,
        help="Path to output CSV file for detailed results"
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
            print(f"  Precision: {detail['precision']:.1f}%  Recall: {detail['recall']:.1f}%  F1: {detail['f1']:.1f}%")

    # Save to output file if specified
    if args.output_file:
        print(f"\nSaving detailed results to: {args.output_file}")
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("Results saved successfully")

    # Save to CSV file if specified
    if args.csv_file:
        save_to_csv(results, args.csv_file)


if __name__ == "__main__":
    main()
