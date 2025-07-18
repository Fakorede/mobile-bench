import os
import pandas as pd
import re
import glob

def count_pr_numbers(csv_file):
    """Count unique PR numbers in the CSV file"""
    df = pd.read_csv(csv_file)
    unique_prs = df['pr_number'].nunique()
    return unique_prs

def extract_test_counts(text):
    """Extract test and failure counts from the test report text"""
    if not isinstance(text, str) or text == "No tests found":
        return 0, 0
    
    # Use regex to find all "Tests: X; Failures: Y" patterns
    test_patterns = re.findall(r'Tests: (\d+); Failures: (\d+)', text)
    
    total_tests = 0
    total_failures = 0
    
    for tests, failures in test_patterns:
        total_tests += int(tests)
        total_failures += int(failures)
    
    return total_tests, total_failures

def analyze_csv_file(csv_file):
    """Analyze a single CSV file"""
    try:
        df = pd.read_csv(csv_file)
        
        # Count unique PR numbers
        unique_prs = count_pr_numbers(csv_file)
        
        # Initialize counters
        fail_to_pass_tests = 0
        fail_to_pass_failures = 0
        pass_to_pass_tests = 0
        pass_to_pass_failures = 0
        
        # Process each row
        for _, row in df.iterrows():
            # Process fail_to_pass column
            if 'fail_to_pass' in df.columns and pd.notna(row['fail_to_pass']):
                tests, failures = extract_test_counts(row['fail_to_pass'])
                fail_to_pass_tests += tests
                fail_to_pass_failures += failures
            
            # Process pass_to_pass column
            if 'pass_to_pass' in df.columns and pd.notna(row['pass_to_pass']):
                tests, failures = extract_test_counts(row['pass_to_pass'])
                pass_to_pass_tests += tests
                pass_to_pass_failures += failures
        
        # Calculate totals
        total_tests = fail_to_pass_tests + pass_to_pass_tests
        total_failures = fail_to_pass_failures + pass_to_pass_failures
        
        return {
            'file': os.path.basename(csv_file),
            'pr_count': unique_prs,
            'fail_to_pass': {
                'tests': fail_to_pass_tests,
                'failures': fail_to_pass_failures
            },
            'pass_to_pass': {
                'tests': pass_to_pass_tests,
                'failures': pass_to_pass_failures
            },
            'total': {
                'tests': total_tests,
                'failures': total_failures
            }
        }
    except Exception as e:
        print(f"Error analyzing {csv_file}: {str(e)}")
        return None

def analyze_folder(folder_path):
    """Analyze all CSV files in a folder"""
    # Find all CSV files in the folder
    csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in {folder_path}")
        return
    
    results = []
    
    # Process each CSV file
    for csv_file in csv_files:
        result = analyze_csv_file(csv_file)
        if result:
            results.append(result)
            
            # Print the results for this file
            print(f"\nResults for {result['file']}:")
            print(f"PR Count: {result['pr_count']}")
            print("\nTest Counts:")
            print(f"  fail_to_pass: {result['fail_to_pass']['tests']} Tests, {result['fail_to_pass']['failures']} Failures")
            print(f"  pass_to_pass: {result['pass_to_pass']['tests']} Tests, {result['pass_to_pass']['failures']} Failures")
            print(f"  TOTAL: {result['total']['tests']} Tests, {result['total']['failures']} Failures")
    
    return results

if __name__ == "__main__":
    folder_path = "/home/thefabdev/dev/mobile-bench/data/2024"
    
    print("Test Analysis Results")
    print("=" * 50)
    
    results = analyze_folder(folder_path)
    
    if results:
        # Print overall summary
        total_prs = sum(r['pr_count'] for r in results)
        total_fail_to_pass_tests = sum(r['fail_to_pass']['tests'] for r in results)
        total_fail_to_pass_failures = sum(r['fail_to_pass']['failures'] for r in results)
        total_pass_to_pass_tests = sum(r['pass_to_pass']['tests'] for r in results)
        total_pass_to_pass_failures = sum(r['pass_to_pass']['failures'] for r in results)
        total_tests = sum(r['total']['tests'] for r in results)
        total_failures = sum(r['total']['failures'] for r in results)
        
        print("\nOVERALL SUMMARY")
        print("=" * 50)
        print(f"Total CSV files processed: {len(results)}")
        print(f"Total PR Count: {total_prs}")
        print("\nAggregate Test Counts:")
        print(f"  fail_to_pass: {total_fail_to_pass_tests} Tests, {total_fail_to_pass_failures} Failures")
        print(f"  pass_to_pass: {total_pass_to_pass_tests} Tests, {total_pass_to_pass_failures} Failures")
        print(f"  GRAND TOTAL: {total_tests} Tests, {total_failures} Failures")