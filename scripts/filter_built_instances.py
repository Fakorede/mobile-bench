#!/usr/bin/env python3
"""
Script to filter out instances from a dataset that already have built images.
"""

import json
import re
from pathlib import Path


def extract_pr_numbers_from_images(images_file: Path) -> set[int]:
    """
    Extract PR numbers from the images.txt file.
    Format: mobiledevbench/element-hq_mb_element-x-android:pr-<number>
    """
    pr_numbers = set()
    
    with open(images_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and non-PR images (like base image)
            if not line or ':pr-' not in line:
                continue
            
            # Extract PR number using regex
            match = re.search(r':pr-(\d+)$', line)
            if match:
                pr_number = int(match.group(1))
                pr_numbers.add(pr_number)
    
    return pr_numbers


def filter_dataset(input_file: Path, output_file: Path, pr_numbers_to_exclude: set[int]):
    """
    Filter JSONL dataset by excluding instances with PR numbers that have built images.
    """
    included_count = 0
    excluded_count = 0
    
    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line in infile:
            line = line.strip()
            if not line:
                continue
            
            instance = json.loads(line)
            pr_number = instance.get('number')
            
            if pr_number in pr_numbers_to_exclude:
                excluded_count += 1
                print(f"Excluding instance for PR #{pr_number}: {instance.get('instance_id', 'unknown')}")
            else:
                outfile.write(line + '\n')
                included_count += 1
    
    return included_count, excluded_count


def main():
    # Define paths
    base_dir = Path('/home/moshood/dev/mobile-bench')
    images_file = base_dir / 'scripts' / 'images.txt'
    input_dataset = base_dir / 'data' / 'instances' / 'all' / 'element-hq__element-x-android_instances_with_test_commands.jsonl'
    output_dataset = base_dir / 'data' / 'instances' / 'all' / 'element-hq__element-x-android_instances_with_test_commands_filtered.jsonl'
    
    # Extract PR numbers from images.txt
    print(f"Reading PR numbers from {images_file}...")
    pr_numbers = extract_pr_numbers_from_images(images_file)
    print(f"Found {len(pr_numbers)} PR numbers with built images")
    print(f"PR numbers: {sorted(pr_numbers)}")
    print()
    
    # Filter the dataset
    print(f"Filtering dataset from {input_dataset}...")
    print(f"Output will be written to {output_dataset}...")
    print()
    
    included, excluded = filter_dataset(input_dataset, output_dataset, pr_numbers)
    
    print()
    print("=" * 60)
    print(f"Filtering complete!")
    print(f"Included instances: {included}")
    print(f"Excluded instances: {excluded}")
    print(f"Total instances processed: {included + excluded}")
    print(f"Output file: {output_dataset}")
    print("=" * 60)


if __name__ == '__main__':
    main()
