#!/usr/bin/env python3
"""
Analyze React Native validation results and provide a summary of test transitions.

An instance is considered successful if:

At least one test was fixed (fail → pass) — i.e., a test that failed before the solution now passes after applying the solution

No tests were broken (pass → fail) — no test that was passing before the solution should start failing after the solution

If no tests were explicitly fixed, the post-solution pass rate must be ≥ pre-solution pass rate

In simpler terms:

✅ Success = Fixed at least one failing test AND didn't break any passing tests
❌ Failure = Either no tests ran, or the solution broke existing tests, or no improvement was made

Usage:
    python analyze_react_native_results.py [results_dir] [--json] [--csv]

Examples:
    python analyze_react_native_results.py mobilebench/validation/react_native_validation_results

"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict


def analyze_results(results_dir: str):
    """Analyze all validation results in the given directory."""
    results_path = Path(results_dir)
    
    if not results_path.exists():
        print(f"Error: Directory not found: {results_dir}")
        sys.exit(1)
    
    # Collect all instance data
    instances = []
    errors = []
    
    # Process each instance directory
    for instance_dir in sorted(results_path.iterdir()):
        if not instance_dir.is_dir():
            continue
        
        result_file = instance_dir / "validation_result.json"
        if not result_file.exists():
            continue
        
        try:
            with open(result_file) as f:
                result = json.load(f)
        except json.JSONDecodeError:
            errors.append({'instance_id': instance_dir.name, 'error': 'Invalid JSON'})
            continue
        
        instance_id = result.get('instance_id', instance_dir.name)
        error_msg = result.get('error_message', '')
        
        if error_msg:
            errors.append({'instance_id': instance_id, 'error': error_msg})
            continue
        
        # Get test transitions
        transitions = result.get('test_transitions', {})
        
        instances.append({
            'instance_id': instance_id,
            'success': result.get('success', False),
            'fail_to_pass': transitions.get('fail_to_pass', {}).get('count', 0),
            'pass_to_pass': transitions.get('pass_to_pass', {}).get('count', 0),
            'pass_to_fail': transitions.get('pass_to_fail', {}).get('count', 0),
            'fail_to_fail': transitions.get('fail_to_fail', {}).get('count', 0),
            'node_version': result.get('node_version', ''),
            'package_manager': result.get('package_manager', ''),
            'validation_time': result.get('validation_time', 0),
        })
    
    return instances, errors


def print_summary(instances: list, errors: list):
    """Print a clean summary table."""
    
    # Filter out instances where all transitions are 0
    instances_with_tests = [
        inst for inst in instances 
        if inst['fail_to_pass'] > 0 or inst['pass_to_pass'] > 0 or 
           inst['pass_to_fail'] > 0 or inst['fail_to_fail'] > 0
    ]
    
    # Header
    print(f"{'Instance ID':<40} {'Success':<8} {'F→P':<6} {'P→P':<6} {'P→F':<6} {'F→F':<6} {'Node':<10} {'Time(s)':<8}")
    print("-" * 96)
    
    # Sort by fail_to_pass count (descending)
    for inst in sorted(instances_with_tests, key=lambda x: -x['fail_to_pass']):
        time_str = f"{inst['validation_time']:.1f}" if inst['validation_time'] else "-"
        print(f"{inst['instance_id']:<40} {str(inst['success']):<8} {inst['fail_to_pass']:<6} {inst['pass_to_pass']:<6} {inst['pass_to_fail']:<6} {inst['fail_to_fail']:<6} {inst['node_version']:<10} {time_str:<8}")
    
    # Summary stats
    print("-" * 96)
    total = len(instances) + len(errors)
    no_tests = len(instances) - len(instances_with_tests)
    successful = sum(1 for i in instances if i['success'])
    with_f2p = sum(1 for i in instances if i['fail_to_pass'] > 0)
    with_p2f = sum(1 for i in instances if i['pass_to_fail'] > 0)
    
    with_p2p = sum(1 for i in instances if i['pass_to_pass'] > 0)
    with_f2f = sum(1 for i in instances if i['fail_to_fail'] > 0)
    
    print(f"\nTotal: {total} | Ran tests: {len(instances_with_tests)} | No tests: {no_tests} | Errors: {len(errors)}")
    print(f"Successful: {successful} | With fail→pass: {with_f2p} | With pass→fail: {with_p2f}")
    print(f"With pass→pass: {with_p2p} | With fail→fail: {with_f2f}")
    
    if errors:
        # Group errors by type
        error_counts = defaultdict(list)
        for e in errors:
            # Truncate error for grouping
            error_key = e['error'][:80] if len(e['error']) > 80 else e['error']
            error_counts[error_key].append(e['instance_id'])
        
        print(f"\nError breakdown ({len(errors)} total):")
        for err, instance_ids in sorted(error_counts.items(), key=lambda x: -len(x[1])):
            print(f"  {len(instance_ids):3d}x {err}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze React Native validation results")
    parser.add_argument("results_dir", nargs="?", 
                        default="mobilebench/validation/react_native_validation_results",
                        help="Directory containing validation results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--csv", action="store_true", help="Output as CSV")
    
    args = parser.parse_args()
    
    instances, errors = analyze_results(args.results_dir)
    
    if args.json:
        print(json.dumps({'instances': instances, 'errors': errors}, indent=2))
    elif args.csv:
        print("instance_id,success,fail_to_pass,pass_to_pass,pass_to_fail,fail_to_fail,node_version,package_manager,validation_time")
        for inst in sorted(instances, key=lambda x: x['instance_id']):
            print(f"{inst['instance_id']},{inst['success']},{inst['fail_to_pass']},{inst['pass_to_pass']},{inst['pass_to_fail']},{inst['fail_to_fail']},{inst['node_version']},{inst['package_manager']},{inst['validation_time']:.1f}")
    else:
        print_summary(instances, errors)


if __name__ == "__main__":
    main()
