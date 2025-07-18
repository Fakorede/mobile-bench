#!/usr/bin/env python3
"""
Android Test Results Processor

This script processes Android test results from a CSV file and extracts successful test runs,
comparing base vs merge test results to identify FAIL_TO_PASS and PASS_TO_PASS test cases.

Requirements:
- Input CSV file: bitwarden-repo-tests.csv (from project knowledge)
- Output: JSONL file with processed test results
"""

import csv
import json
import re
import sys
from typing import Dict, List, Set, Tuple, Optional
from pathlib import Path


def extract_test_cases_from_result(test_result: str) -> Dict[str, List[str]]:
    """
    Extract individual test cases from test result string.
    
    Args:
        test_result: Raw test result string containing test suite information
        
    Returns:
        Dictionary with test suite names as keys and lists of test cases as values
    """
    test_suites = {}
    
    # Skip if test failed to run
    if "Gradle build failed and test couldn't run" in test_result:
        return test_suites
    
    # Split by test suite sections (File: ... Test Suite: ...)
    suite_pattern = r'File: [^\n]+\s+Test Suite: ([^\n]+)\s+Tests: (\d+); Failures: (\d+); Errors: (\d+); Skipped: (\d+); Time: ([\d.]+)s\s+All test cases:\s+(.*?)(?=\s+File:|$)'
    
    matches = re.findall(suite_pattern, test_result, re.DOTALL)
    
    for match in matches:
        suite_name = match[0].strip()
        tests_count = int(match[1])
        failures = int(match[2])
        errors = int(match[3])
        test_cases_section = match[6].strip()
        
        # Extract individual test cases
        test_cases = []
        test_case_lines = test_cases_section.split('\n')
        
        for line in test_case_lines:
            line = line.strip()
            if line.startswith('- '):
                # Remove the leading "- " and extract test name and class
                test_info = line[2:].strip()
                
                # Skip failed/error/skipped markers
                if ' - FAILED' in test_info or ' - ERROR' in test_info or ' - SKIPPED' in test_info:
                    continue
                
                # Extract test case in format: testName (className)
                test_match = re.match(r'(.+?)\s+\(([^)]+)\)', test_info)
                if test_match:
                    test_name = test_match.group(1).strip()
                    class_name = test_match.group(2).strip()
                    # Format as ClassName::testMethodName
                    formatted_test = f"{class_name}::{test_name}"
                    test_cases.append(formatted_test)
        
        if test_cases:
            test_suites[suite_name] = test_cases
    
    return test_suites


def get_test_variant(test_result: str) -> Optional[str]:
    """
    Determine the test variant (debug or release) from test result.
    
    Args:
        test_result: Raw test result string
        
    Returns:
        'debug' or 'release' or None if cannot be determined
    """
    if "testDebugUnitTest" in test_result:
        return "debug"
    elif "testReleaseUnitTest" in test_result:
        return "release"
    return None


def flatten_test_suites(test_suites_dict: Dict[str, List[str]]) -> List[str]:
    """
    Merge all test cases from all test suites into a single list.
    
    Args:
        test_suites_dict: Dictionary with test suite names as keys and test cases as values
        
    Returns:
        Flat list of all test cases
    """
    all_tests = []
    for suite_tests in test_suites_dict.values():
        all_tests.extend(suite_tests)
    return all_tests


def process_csv_file(csv_file_path: str, output_jsonl_path: str) -> None:
    """
    Process the CSV file and generate JSONL output.
    
    Args:
        csv_file_path: Path to input CSV file
        output_jsonl_path: Path to output JSONL file
    """
    processed_records = []
    
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            base_test = row.get('base_test', '').strip()
            merge_test = row.get('merge_test', '').strip()
            
            # Skip rows where tests failed to run
            if ("Gradle build failed and test couldn't run" in base_test or 
                "Gradle build failed and test couldn't run" in merge_test):
                continue
            
            # Skip if either test result is empty
            if not base_test or not merge_test:
                continue
            
            # Extract test cases from both base and merge tests
            base_test_suites = extract_test_cases_from_result(base_test)
            merge_test_suites = extract_test_cases_from_result(merge_test)
            
            # Skip if no test cases found in either
            if not base_test_suites or not merge_test_suites:
                continue
            
            # Get test variants
            base_variant = get_test_variant(base_test)
            merge_variant = get_test_variant(merge_test)
            
            # Prefer debug variant, fall back to whatever is available
            # If both have multiple variants, prioritize debug
            preferred_variant = "debug"
            
            # Filter test suites by preferred variant if available
            base_filtered = {}
            merge_filtered = {}
            
            for suite_name, test_cases in base_test_suites.items():
                if preferred_variant == "debug" and "testDebugUnitTest" in base_test:
                    if "testDebugUnitTest" in base_test:
                        base_filtered[suite_name] = test_cases
                elif preferred_variant == "release" and "testReleaseUnitTest" in base_test:
                    if "testReleaseUnitTest" in base_test:
                        base_filtered[suite_name] = test_cases
                else:
                    # If preferred variant not found, use all
                    base_filtered[suite_name] = test_cases
            
            for suite_name, test_cases in merge_test_suites.items():
                if preferred_variant == "debug" and "testDebugUnitTest" in merge_test:
                    if "testDebugUnitTest" in merge_test:
                        merge_filtered[suite_name] = test_cases
                elif preferred_variant == "release" and "testReleaseUnitTest" in merge_test:
                    if "testReleaseUnitTest" in merge_test:
                        merge_filtered[suite_name] = test_cases
                else:
                    # If preferred variant not found, use all
                    merge_filtered[suite_name] = test_cases
            
            # If filtering resulted in empty sets, use original
            if not base_filtered:
                base_filtered = base_test_suites
            if not merge_filtered:
                merge_filtered = merge_test_suites
            
            # Merge all test cases into flat lists
            base_all_tests = set(flatten_test_suites(base_filtered))
            merge_all_tests = set(flatten_test_suites(merge_filtered))
            
            # Calculate FAIL_TO_PASS and PASS_TO_PASS
            # Note: Since we don't have explicit pass/fail status for individual tests,
            # we assume all extracted tests are passing tests.
            # FAIL_TO_PASS: tests that exist in merge but not in base (newly passing)
            # PASS_TO_PASS: tests that exist in both base and merge (consistently passing)
            
            fail_to_pass = list(merge_all_tests - base_all_tests)
            pass_to_pass = list(base_all_tests & merge_all_tests)
            
            # Create record
            record = {
                "repo_full_name": row.get('repo_full_name', ''),
                "pr_number": int(row.get('pr_number', 0)) if row.get('pr_number', '').isdigit() else 0,
                "sha": row.get('sha', ''),
                "filename": row.get('filename', ''),
                "merge_commit_sha": row.get('merge_commit_sha', ''),
                "base_sha": row.get('base_sha', ''),
                "FAIL_TO_PASS": sorted(fail_to_pass),
                "PASS_TO_PASS": sorted(pass_to_pass),
                "variant_used": preferred_variant,
                "base_total_tests": len(base_all_tests),
                "merge_total_tests": len(merge_all_tests)
            }
            
            # Only include records that have some test data
            if record["FAIL_TO_PASS"] or record["PASS_TO_PASS"]:
                processed_records.append(record)
    
    # Write JSONL output
    with open(output_jsonl_path, 'w', encoding='utf-8') as jsonl_file:
        for record in processed_records:
            jsonl_file.write(json.dumps(record) + '\n')
    
    print(f"Processed {len(processed_records)} successful test records")
    print(f"Output written to: {output_jsonl_path}")
    
    # Print example record
    if processed_records:
        print("\nExample record:")
        example = processed_records[0]
        print(f"Repository: {example['repo_full_name']}")
        print(f"PR: {example['pr_number']}")
        print(f"FAIL_TO_PASS: {example['FAIL_TO_PASS'][:3]}{'...' if len(example['FAIL_TO_PASS']) > 3 else ''}")
        print(f"PASS_TO_PASS: {example['PASS_TO_PASS'][:3]}{'...' if len(example['PASS_TO_PASS']) > 3 else ''}")


def main():
    """Main function to run the script."""
    # Default file paths
    csv_file_path = "bitwarden-repo-tests.csv"
    output_jsonl_path = "processed_test_results.jsonl"
    
    # Allow command line arguments
    if len(sys.argv) > 1:
        csv_file_path = sys.argv[1]
    if len(sys.argv) > 2:
        output_jsonl_path = sys.argv[2]
    
    # Check if input file exists
    if not Path(csv_file_path).exists():
        print(f"Error: Input CSV file '{csv_file_path}' not found.")
        print("Please ensure the bitwarden-repo-tests.csv file is in the current directory.")
        sys.exit(1)
    
    try:
        process_csv_file(csv_file_path, output_jsonl_path)
        print("Processing completed successfully!")
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()