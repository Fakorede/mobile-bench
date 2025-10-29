#!/usr/bin/env python3
"""
Script to summarize validation results from JSON files.

Usage:
    python validation_summarizer.py <path_to_validated_tasks>
    
Example:
    python validation_summarizer.py data/validated-tasks/WordPress
"""

import json
import os
import sys
from pathlib import Path


def load_validation_results(json_path):
    """Load and parse validation results from a JSON file."""
    try:
        with open(json_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading {json_path}: {e}", file=sys.stderr)
        return None


def summarize_instance(instance_name, data):
    """
    Generate summary for a single instance.
    
    Args:
        instance_name: Name of the instance (e.g., 'wordpress-mobile__WordPress-Android-18967')
        data: Parsed JSON validation results
    
    Returns:
        Tuple of (summary_string, should_include)
        summary_string: "instance_name: Pre-tests: passed/total, Post-tests: passed/total, Fixed: count"
        should_include: Boolean indicating if this instance should be included in output
    """
    pre_exec = data.get('execution_summary', {}).get('pre_execution', {})
    post_exec = data.get('execution_summary', {}).get('post_execution', {})
    transitions = data.get('test_transitions', {})
    
    pre_passed = pre_exec.get('passed_count', 0)
    pre_failed = pre_exec.get('failed_count', 0)
    pre_total = pre_passed + pre_failed
    
    post_passed = post_exec.get('passed_count', 0)
    post_failed = post_exec.get('failed_count', 0)
    post_total = post_passed + post_failed
    
    # Fixed tests are those that went from fail to pass
    fixed_count = transitions.get('fail_to_pass', {}).get('count', 0)
    
    # Filter out instances where both pre and post tests are 0/0
    should_include = not (pre_total == 0 and post_total == 0)
    
    summary = f"{instance_name}: Pre-tests: {pre_passed}/{pre_total}, Post-tests: {post_passed}/{post_total}, Fixed: {fixed_count}"
    
    return summary, should_include


def find_validation_files(base_path):
    """
    Find all validation result JSON files in the directory structure.
    
    Expected structure:
        base_path/
            project-1/
                instance-name-1/
                    validation_results.json (or similar)
            project-2/
                instance-name-2/
                    validation_results.json
    
    Returns:
        List of tuples: (instance_name, json_file_path)
    """
    base_path = Path(base_path)
    results = []
    
    # Look for JSON files in subdirectories
    # Assuming structure: base_path/project/instance/result.json
    for project_dir in base_path.iterdir():
        if not project_dir.is_dir():
            continue
            
        for instance_dir in project_dir.iterdir():
            if not instance_dir.is_dir():
                continue
            
            instance_name = instance_dir.name
            
            # Look for JSON files in the instance directory
            json_files = list(instance_dir.glob('*.json'))
            
            if json_files:
                # Use the first JSON file found (or you can filter by name)
                results.append((instance_name, json_files[0]))
    
    return sorted(results, key=lambda x: x[0])


def main():
    if len(sys.argv) < 2:
        print("Usage: python validation_summarizer.py <path_to_validated_tasks>")
        print("Example: python validation_summarizer.py data/validated-tasks/WordPress")
        sys.exit(1)
    
    base_path = sys.argv[1]
    
    if not os.path.exists(base_path):
        print(f"Error: Path '{base_path}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    validation_files = find_validation_files(base_path)
    
    if not validation_files:
        print(f"No validation result files found in '{base_path}'", file=sys.stderr)
        sys.exit(1)
    
    # Process each instance and print summary (filtering out 0/0 cases)
    zero_fixed_count = 0
    total_included = 0
    
    for instance_name, json_path in validation_files:
        data = load_validation_results(json_path)
        
        if data is not None:
            summary, should_include = summarize_instance(instance_name, data)
            if should_include:
                print(summary)
                total_included += 1
                
                # Count instances with fixed = 0
                transitions = data.get('test_transitions', {})
                fixed_count = transitions.get('fail_to_pass', {}).get('count', 0)
                if fixed_count == 0:
                    zero_fixed_count += 1
    
    # Print summary statistics
    if total_included > 0:
        print(f"\nSummary: {zero_fixed_count} instances with Fixed = 0 (out of {total_included} total instances)")


if __name__ == '__main__':
    main()