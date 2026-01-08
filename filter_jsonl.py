#!/usr/bin/env python3
"""
Script to filter OUT (remove) instances from a JSONL file based on the 'number' attribute.
Retains all instances EXCEPT those with the specified numbers.

Sample usage:
    # Remove instances, save remaining to file
    python3 filter_jsonl.py data/instances/all/MetaMask__metamask-mobile_instances_with_test_commands.jsonl --numbers 11850 14597

    # Filter with comma-separated numbers
    python3 filter_jsonl.py input.jsonl output.jsonl --numbers 11850,295

    # Print filtered results to stdout
    python3 filter_jsonl.py input.jsonl --numbers 11850 --print-only
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Set


def parse_numbers(numbers_input: List[str]) -> Set[int]:
    """
    Parse number arguments which can be comma-separated or space-separated.

    Args:
        numbers_input: List of number strings (can contain commas)

    Returns:
        Set of integers
    """
    numbers = set()
    for item in numbers_input:
        # Split by comma in case numbers are comma-separated
        for num_str in item.split(','):
            num_str = num_str.strip()
            if num_str:
                try:
                    numbers.add(int(num_str))
                except ValueError:
                    print(f"Warning: '{num_str}' is not a valid number, skipping.", file=sys.stderr)
    return numbers


def filter_jsonl(input_file: Path, output_file: Path, numbers: Set[int], print_only: bool = False) -> None:
    """
    Filter OUT instances from JSONL file based on 'number' attribute.
    Retains all instances EXCEPT those with numbers in the provided set.

    Args:
        input_file: Path to input JSONL file
        output_file: Path to output JSONL file (ignored if print_only is True)
        numbers: Set of numbers to exclude (filter out)
        print_only: If True, print to stdout instead of writing to file
    """
    if not input_file.exists():
        print(f"Error: Input file '{input_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    excluded_count = 0
    retained_count = 0
    total_count = 0

    # Open output file if not printing only
    output_handle = sys.stdout if print_only else open(output_file, 'w', encoding='utf-8')

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                total_count += 1

                try:
                    data = json.loads(line)

                    # Check if 'number' field exists
                    if 'number' not in data:
                        print(f"Warning: Line {line_num} does not have 'number' field, skipping.", file=sys.stderr)
                        continue

                    # Filter OUT (exclude) instances with specified numbers
                    if data['number'] not in numbers:
                        output_handle.write(json.dumps(data) + '\n')
                        retained_count += 1
                    else:
                        excluded_count += 1

                except json.JSONDecodeError as e:
                    print(f"Warning: Line {line_num} is not valid JSON: {e}, skipping.", file=sys.stderr)
                    continue

    finally:
        if not print_only:
            output_handle.close()

    # Print summary to stderr so it doesn't interfere with stdout output
    print(f"\nExcluded {excluded_count} instances, retained {retained_count} out of {total_count} total.", file=sys.stderr)
    if not print_only:
        print(f"Output written to: {output_file}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Filter OUT (exclude) instances from a JSONL file based on the 'number' attribute. Retains all instances EXCEPT those with specified numbers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Exclude instances 297 and 295, save remaining to output file
  python filter_jsonl.py input.jsonl output.jsonl --numbers 297 295

  # Same as above but with comma-separated numbers
  python filter_jsonl.py input.jsonl output.jsonl --numbers 297,295

  # Print retained instances to stdout instead of file
  python filter_jsonl.py input.jsonl --numbers 297 --print-only

  # Exclude multiple numbers and redirect to file
  python filter_jsonl.py input.jsonl --numbers 100 200 300 --print-only > filtered.jsonl
        """
    )

    parser.add_argument('input_file', type=Path, help='Input JSONL file path')
    parser.add_argument('output_file', type=Path, nargs='?', help='Output JSONL file path (not required with --print-only)')
    parser.add_argument('--numbers', '-n', nargs='+', required=True,
                        help='Numbers to exclude/filter out (space or comma-separated)')
    parser.add_argument('--print-only', '-p', action='store_true',
                        help='Print retained instances to stdout instead of writing to file')

    args = parser.parse_args()

    # Set default output file if not provided and not print-only
    if not args.print_only and not args.output_file:
        input_path = args.input_file
        # Insert "_filtered" before the file extension
        stem = input_path.stem
        suffix = input_path.suffix
        args.output_file = input_path.parent / f"{stem}_filtered{suffix}"
        print(f"No output file specified. Using: {args.output_file}", file=sys.stderr)

    # Parse numbers
    numbers = parse_numbers(args.numbers)

    if not numbers:
        print("Error: No valid numbers provided.", file=sys.stderr)
        sys.exit(1)

    print(f"Excluding instances with numbers: {sorted(numbers)}", file=sys.stderr)

    # Perform filtering
    filter_jsonl(args.input_file, args.output_file, numbers, args.print_only)


if __name__ == '__main__':
    main()
