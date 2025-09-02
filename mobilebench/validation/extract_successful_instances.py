#!/usr/bin/env python3
"""
Script to extract instances where both test_patch_applied and solution_patch_applied are True
from a validation summary JSON file.
"""

import json
import sys
from typing import Dict, Any, List

def load_validation_data(file_path: str) -> Dict[str, Any]:
    """Load validation data from JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in file '{file_path}': {e}")
        sys.exit(1)

def extract_successfully_patched_instances(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract instances where both test_patch_applied and solution_patch_applied are True.
    
    Args:
        data: The validation summary data
    
    Returns:
        List of instances that meet the criteria
    """
    successfully_patched = []
    
    if 'results' not in data:
        print("Error: No 'results' key found in the data.")
        return successfully_patched
    
    for instance_id, instance_data in data['results'].items():
        # Check if both patches were applied successfully
        test_patch_applied = instance_data.get('test_patch_applied', False)
        solution_patch_applied = instance_data.get('solution_patch_applied', False)
        
        if test_patch_applied and solution_patch_applied:
            # Add instance_id to the data for easier identification
            instance_data['instance_id'] = instance_id
            successfully_patched.append(instance_data)
    
    return successfully_patched

def print_summary(instances: List[Dict[str, Any]]) -> None:
    """Print a summary of the extracted instances."""
    print(f"\nFound {len(instances)} instances where both patches were applied successfully:")
    print("-" * 60)
    
    for i, instance in enumerate(instances, 1):
        instance_id = instance.get('instance_id', 'Unknown')
        success = instance.get('success', False)
        duration = instance.get('total_duration', 0)
        
        print(f"{i:2d}. {instance_id}")
        print(f"    Success: {success}")
        print(f"    Duration: {duration:.2f} seconds")
        
        # Show test execution results if available
        pre_test = instance.get('pre_test_execution', {})
        post_test = instance.get('post_test_execution', {})
        
        if pre_test:
            print(f"    Pre-test: {pre_test.get('total_tests', 0)} tests, "
                  f"exit code: {pre_test.get('exit_code', 'N/A')}")
        
        if post_test:
            print(f"    Post-test: {post_test.get('total_tests', 0)} tests, "
                  f"exit code: {post_test.get('exit_code', 'N/A')}")
        
        print()

def save_filtered_results(instances: List[Dict[str, Any]], output_file: str) -> None:
    """Save the filtered results to a JSON file."""
    # Extract just the numeric part of instance IDs
    instance_ids = []
    for instance in instances:
        instance_id = instance.get('instance_id', '')
        # Extract the number after the last dash (e.g., "tuskyapp__Tusky-4993" -> "4993")
        if '--' in instance_id:
            numeric_id = instance_id.split('--')[-1]
        elif '-' in instance_id:
            numeric_id = instance_id.split('-')[-1]
        else:
            numeric_id = instance_id
        
        # Try to convert to integer, fallback to string if not numeric
        try:
            instance_ids.append(int(numeric_id))
        except ValueError:
            instance_ids.append(numeric_id)
    
    output_data = {
        "filtered_count": len(instances),
        "filter_criteria": "test_patch_applied=True AND solution_patch_applied=True",
        "instance_ids": instance_ids,
        "instances": instances
    }
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"Filtered results saved to: {output_file}")
    except IOError as e:
        print(f"Error saving to file '{output_file}': {e}")

def main():
    """Main function to execute the script."""
    # Default input file (can be modified or passed as command line argument)
    input_file = "/home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod/validation_summary.json"
    output_file = "/home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod/successfully_patched_instances.json"

    # Handle command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    
    print(f"Loading data from: {input_file}")
    
    # Load and process the data
    data = load_validation_data(input_file)
    successfully_patched = extract_successfully_patched_instances(data)
    
    # Print summary
    print_summary(successfully_patched)
    
    # Save filtered results
    if successfully_patched:
        save_filtered_results(successfully_patched, output_file)
    else:
        print("No instances found matching the criteria.")
    
    # Print overall statistics
    total_instances = len(data.get('results', {}))
    success_rate = (len(successfully_patched) / total_instances * 100) if total_instances > 0 else 0
    
    print(f"\nOverall Statistics:")
    print(f"Total instances: {total_instances}")
    print(f"Successfully patched: {len(successfully_patched)}")
    print(f"Success rate: {success_rate:.1f}%")

if __name__ == "__main__":
    main()