#!/usr/bin/env python3
"""
Flexible analyzer for fail_to_pass, pass_to_pass, and fail_to_fail transitions across multiple projects.

This script can analyze a single project directory or multiple projects within
a parent directory structure. It computes fail_to_pass, pass_to_pass, and fail_to_fail
test transitions from test_analysis.json files.

Usage:
    python fail_to_pass_analyzer.py <path> [--recursive]
"""

import json
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict


def find_test_analysis_files(base_path, recursive=False):
    """
    Find all test_analysis.json files in the given path.
    
    Args:
        base_path (Path): Base directory to search
        recursive (bool): If True, search for projects in subdirectories
        
    Returns:
        dict: Mapping of project names to lists of test_analysis.json files
    """
    base_path = Path(base_path)
    projects = defaultdict(list)
    
    if recursive:
        # Look for projects in subdirectories
        for project_dir in base_path.iterdir():
            if not project_dir.is_dir():
                continue
                
            # Search for test_analysis.json files in instance subdirectories
            for instance_dir in project_dir.iterdir():
                if not instance_dir.is_dir():
                    continue
                    
                test_file = instance_dir / "test_analysis.json"
                if test_file.exists():
                    projects[project_dir.name].append(test_file)
    else:
        # Look for test_analysis.json files directly in subdirectories
        for instance_dir in base_path.iterdir():
            if not instance_dir.is_dir():
                continue
                
            test_file = instance_dir / "test_analysis.json"
            if test_file.exists():
                projects[base_path.name].append(test_file)
    
    return dict(projects)


def analyze_project_transitions(test_files):
    """
    Analyze fail_to_pass, pass_to_pass, and fail_to_fail transitions for a single project.
    
    Args:
        test_files (list): List of test_analysis.json file paths
        
    Returns:
        dict: Analysis results for the project
    """
    results = {
        'total_instances': len(test_files),
        'instances_with_fail_to_pass': 0,
        'total_fail_to_pass_transitions': 0,
        'max_fail_to_pass': 0,
        'instances_with_pass_to_pass': 0,
        'total_pass_to_pass_transitions': 0,
        'max_pass_to_pass': 0,
        'instances_with_fail_to_fail': 0,
        'total_fail_to_fail_transitions': 0,
        'max_fail_to_fail': 0,
        'instances_fail_to_pass': [],
        'instances_pass_to_pass': [],
        'instances_fail_to_fail': [],
        'error_count': 0
    }
    
    for test_file in test_files:
        instance_name = test_file.parent.name
        
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            fail_to_pass_count = data.get('test_transitions', {}).get('fail_to_pass', {}).get('count', 0)
            pass_to_pass_count = data.get('test_transitions', {}).get('pass_to_pass', {}).get('count', 0)
            fail_to_fail_count = data.get('test_transitions', {}).get('fail_to_fail', {}).get('count', 0)
            
            if fail_to_pass_count > 0:
                results['instances_with_fail_to_pass'] += 1
                results['total_fail_to_pass_transitions'] += fail_to_pass_count
                results['max_fail_to_pass'] = max(results['max_fail_to_pass'], fail_to_pass_count)
                results['instances_fail_to_pass'].append({
                    'instance': instance_name,
                    'count': fail_to_pass_count
                })
            
            if pass_to_pass_count > 0:
                results['instances_with_pass_to_pass'] += 1
                results['total_pass_to_pass_transitions'] += pass_to_pass_count
                results['max_pass_to_pass'] = max(results['max_pass_to_pass'], pass_to_pass_count)
                results['instances_pass_to_pass'].append({
                    'instance': instance_name,
                    'count': pass_to_pass_count
                })
            
            if fail_to_fail_count > 0:
                results['instances_with_fail_to_fail'] += 1
                results['total_fail_to_fail_transitions'] += fail_to_fail_count
                results['max_fail_to_fail'] = max(results['max_fail_to_fail'], fail_to_fail_count)
                results['instances_fail_to_fail'].append({
                    'instance': instance_name,
                    'count': fail_to_fail_count
                })
                
        except (json.JSONDecodeError, FileNotFoundError, IOError, KeyError, TypeError) as e:
            results['error_count'] += 1
            print(f"Warning: Error processing {test_file}: {e}")
    
    # Sort each list by count descending
    results['instances_fail_to_pass'].sort(key=lambda x: x['count'], reverse=True)
    results['instances_pass_to_pass'].sort(key=lambda x: x['count'], reverse=True)
    results['instances_fail_to_fail'].sort(key=lambda x: x['count'], reverse=True)
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Analyze fail_to_pass, pass_to_pass, and fail_to_fail transitions in test results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a single project directory
  python fail_to_pass_analyzer.py /path/to/project/Thunderbird
  
  # Analyze multiple projects recursively
  python fail_to_pass_analyzer.py /path/to/validated-tasks --recursive
        """
    )
    
    parser.add_argument('path', help='Path to analyze')
    parser.add_argument('--recursive', '-r', action='store_true',
                       help='Look for projects in subdirectories')
    
    args = parser.parse_args()
    
    try:
        projects = find_test_analysis_files(args.path, args.recursive)
        
        if not projects:
            print(f"No test_analysis.json files found in {args.path}")
            return
        
        print(f"Analysis Results for: {args.path}")
        print("=" * 80)
        
        total_projects = len(projects)
        total_instances = 0
        total_with_fail_to_pass = 0
        total_with_pass_to_pass = 0
        total_with_fail_to_fail = 0
        grand_total_fail_to_pass = 0
        grand_total_pass_to_pass = 0
        grand_total_fail_to_fail = 0
        
        for project_name, test_files in projects.items():
            results = analyze_project_transitions(test_files)
            
            total_instances += results['total_instances']
            total_with_fail_to_pass += results['instances_with_fail_to_pass']
            total_with_pass_to_pass += results['instances_with_pass_to_pass']
            total_with_fail_to_fail += results['instances_with_fail_to_fail']
            grand_total_fail_to_pass += results['total_fail_to_pass_transitions']
            grand_total_pass_to_pass += results['total_pass_to_pass_transitions']
            grand_total_fail_to_fail += results['total_fail_to_fail_transitions']
            
            print(f"\nProject: {project_name}")
            print(f"  Total instances: {results['total_instances']}")
            print(f"  Instances with fail_to_pass > 0: {results['instances_with_fail_to_pass']}")
            print(f"  Total fail_to_pass transitions: {results['total_fail_to_pass_transitions']}")
            print(f"  Max fail_to_pass in single instance: {results['max_fail_to_pass']}")
            print(f"  Instances with pass_to_pass > 0: {results['instances_with_pass_to_pass']}")
            print(f"  Total pass_to_pass transitions: {results['total_pass_to_pass_transitions']}")
            print(f"  Max pass_to_pass in single instance: {results['max_pass_to_pass']}")
            print(f"  Instances with fail_to_fail > 0: {results['instances_with_fail_to_fail']}")
            print(f"  Total fail_to_fail transitions: {results['total_fail_to_fail_transitions']}")
            print(f"  Max fail_to_fail in single instance: {results['max_fail_to_fail']}")
            
            if results['instances_with_fail_to_pass'] > 0 or results['instances_with_pass_to_pass'] > 0 or results['instances_with_fail_to_fail'] > 0:
                fail_percentage = results['instances_with_fail_to_pass'] / results['total_instances'] * 100
                pass_percentage = results['instances_with_pass_to_pass'] / results['total_instances'] * 100
                fail_to_fail_percentage = results['instances_with_fail_to_fail'] / results['total_instances'] * 100
                print(f"  Percentage with fail_to_pass transitions: {fail_percentage:.2f}%")
                print(f"  Percentage with pass_to_pass transitions: {pass_percentage:.2f}%")
                print(f"  Percentage with fail_to_fail transitions: {fail_to_fail_percentage:.2f}%")
                
                # Show all instances with fail_to_pass transitions
                if results['instances_fail_to_pass']:
                    print(f"\n  All instances with fail_to_pass > 0:")
                    for instance in results['instances_fail_to_pass']:
                        print(f"    - {instance['instance']}: {instance['count']}")
                
                # Show all instances with pass_to_pass transitions
                if results['instances_pass_to_pass']:
                    print(f"\n  All instances with pass_to_pass > 0:")
                    for instance in results['instances_pass_to_pass']:
                        print(f"    - {instance['instance']}: {instance['count']}")
                
                # Show all instances with fail_to_fail transitions
                if results['instances_fail_to_fail']:
                    print(f"\n  All instances with fail_to_fail > 0:")
                    for instance in results['instances_fail_to_fail']:
                        print(f"    - {instance['instance']}: {instance['count']}")
            
            if results['error_count'] > 0:
                print(f"  Errors encountered: {results['error_count']}")
        
        # Overall summary
        print(f"\n" + "=" * 80)
        print(f"OVERALL SUMMARY")
        print(f"Total projects analyzed: {total_projects}")
        print(f"Total instances analyzed: {total_instances}")
        print(f"Total instances with fail_to_pass > 0: {total_with_fail_to_pass}")
        print(f"Total instances with pass_to_pass > 0: {total_with_pass_to_pass}")
        print(f"Total instances with fail_to_fail > 0: {total_with_fail_to_fail}")
        print(f"Total fail_to_pass transitions: {grand_total_fail_to_pass}")
        print(f"Total pass_to_pass transitions: {grand_total_pass_to_pass}")
        print(f"Total fail_to_fail transitions: {grand_total_fail_to_fail}")
        
        if total_instances > 0:
            fail_percentage = total_with_fail_to_pass / total_instances * 100
            pass_percentage = total_with_pass_to_pass / total_instances * 100
            fail_to_fail_percentage = total_with_fail_to_fail / total_instances * 100
            print(f"Overall percentage with fail_to_pass transitions: {fail_percentage:.2f}%")
            print(f"Overall percentage with pass_to_pass transitions: {pass_percentage:.2f}%")
            print(f"Overall percentage with fail_to_fail transitions: {fail_to_fail_percentage:.2f}%")
            
            if total_with_fail_to_pass > 0:
                avg_fail_transitions = grand_total_fail_to_pass / total_with_fail_to_pass
                print(f"Average fail_to_pass transitions per instance (with fail_to_pass): {avg_fail_transitions:.2f}")
            
            if total_with_pass_to_pass > 0:
                avg_pass_transitions = grand_total_pass_to_pass / total_with_pass_to_pass
                print(f"Average pass_to_pass transitions per instance (with pass_to_pass): {avg_pass_transitions:.2f}")
            
            if total_with_fail_to_fail > 0:
                avg_fail_to_fail_transitions = grand_total_fail_to_fail / total_with_fail_to_fail
                print(f"Average fail_to_fail transitions per instance (with fail_to_fail): {avg_fail_to_fail_transitions:.2f}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()