#!/usr/bin/env python3
"""
Script to add test_command field to dataset instances from validation results.

Usage:
    python add_test_commands.py <dataset_path> <validation_results_path> [output_path]

Example:
python3 add_test_commands.py \
    data/instances/all/RocketChat__Rocket.Chat.ReactNative_instances.jsonl \
    mobiledev_bench/validation/react_native_validation_results/RocketChat

python3 add_test_commands.py \
    data/instances/all/MetaMask__metamask-mobile_instances.jsonl \
    mobiledev_bench/validation/react_native_validation_results/metamask

python3 add_test_commands.py \
    data/instances/all/LemmyNet__jerboa_instances.jsonl \
    mobiledev_bench/validation/validation_results/

python3 add_test_commands.py \
    data/instances/all/mjaakko__NeoStumbler_instances.jsonl \
    mobiledev_bench/validation/validation_results/Neostumbler

python3 add_test_commands.py \
    data/instances/all/streetcomplete__StreetComplete_instances.jsonl \
    mobiledev_bench/validation/validation_results/StreetComplete
"""




import json
import sys
from pathlib import Path
from typing import Dict, Optional


def load_validation_result(validation_dir: Path, instance_id: str) -> Optional[str]:
    """
    Load the test_command from validation results for a given instance_id.

    Supports two formats:
    1. React Native: validation_result.json with test_command field
    2. Android: test_logs/*.txt with "Gradle Command:" line

    Args:
        validation_dir: Path to the validation results directory
        instance_id: The instance ID to look up

    Returns:
        The test_command string if found, None otherwise
    """
    instance_dir = validation_dir / instance_id

    if not instance_dir.exists():
        return None

    # Try React Native format first (validation_result.json)
    result_path = instance_dir / "validation_result.json"
    if result_path.exists():
        try:
            with open(result_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Try to get test_command from pre_solution_tests first, fallback to post_solution_tests
                test_command = data.get('pre_solution_tests', {}).get('test_command')
                if not test_command:
                    test_command = data.get('post_solution_tests', {}).get('test_command')
                return test_command
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Error reading {result_path}: {e}", file=sys.stderr)
            return None

    # Try Android format (test_logs/*.txt with "Gradle Command:" line)
    test_logs_dir = instance_dir / "test_logs"
    if test_logs_dir.exists() and test_logs_dir.is_dir():
        # Look for the most recent pre_solution test log
        log_files = sorted(test_logs_dir.glob("test_log_pre_solution_*.txt"))
        if not log_files:
            # Fallback to post_solution if pre_solution doesn't exist
            log_files = sorted(test_logs_dir.glob("test_log_post_solution_*.txt"))

        if log_files:
            try:
                with open(log_files[-1], 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith("Gradle Command:"):
                            # Extract the gradle command after "Gradle Command: "
                            gradle_cmd = line.split("Gradle Command:", 1)[1].strip()
                            return f"./gradlew {gradle_cmd}"
            except IOError as e:
                print(f"Warning: Error reading {log_files[-1]}: {e}", file=sys.stderr)
                return None

    return None


def process_dataset(dataset_path: Path, validation_dir: Path, output_path: Path) -> None:
    """
    Process the dataset and add test_command field from validation results.
    
    Args:
        dataset_path: Path to the input JSONL dataset file
        validation_dir: Path to the validation results directory
        output_path: Path to write the output JSONL file
    """
    if not dataset_path.exists():
        print(f"Error: Dataset file not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)
    
    if not validation_dir.exists():
        print(f"Error: Validation directory not found: {validation_dir}", file=sys.stderr)
        sys.exit(1)
    
    processed_count = 0
    updated_count = 0
    missing_count = 0
    
    with open(dataset_path, 'r', encoding='utf-8') as infile, \
         open(output_path, 'w', encoding='utf-8') as outfile:
        
        for line_num, line in enumerate(infile, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                instance = json.loads(line)
                instance_id = instance.get('instance_id')
                
                if not instance_id:
                    print(f"Warning: Line {line_num} missing instance_id, skipping", file=sys.stderr)
                    outfile.write(line + '\n')
                    continue
                
                # Get test_command from validation results
                test_command = load_validation_result(validation_dir, instance_id)
                
                if test_command:
                    # Add test_command field
                    instance['test_command'] = test_command
                    updated_count += 1
                else:
                    missing_count += 1
                    print(f"Warning: No validation result found for instance {instance_id}", file=sys.stderr)
                
                # Write updated instance
                outfile.write(json.dumps(instance, ensure_ascii=False) + '\n')
                processed_count += 1
                
            except json.JSONDecodeError as e:
                print(f"Warning: Error parsing line {line_num}: {e}", file=sys.stderr)
                outfile.write(line + '\n')
    
    print(f"\nProcessing complete:")
    print(f"  Total instances processed: {processed_count}")
    print(f"  Instances updated: {updated_count}")
    print(f"  Instances without validation results: {missing_count}")
    print(f"  Output written to: {output_path}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    dataset_path = Path(sys.argv[1])
    validation_dir = Path(sys.argv[2])
    
    # If output path not specified, create one based on input filename
    if len(sys.argv) >= 4:
        output_path = Path(sys.argv[3])
    else:
        output_path = dataset_path.parent / f"{dataset_path.stem}_with_test_commands.jsonl"
    
    process_dataset(dataset_path, validation_dir, output_path)


if __name__ == "__main__":
    main()
