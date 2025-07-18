#!/bin/bash

# Script to parse Android test result XML files in a repository
# Usage: ./parse_android_tests.sh [directory]

# Set directory to search in (default: current directory)
SEARCH_DIR="${1:-.}"

# Check if xmlstarlet is installed
if ! command -v xmlstarlet &> /dev/null; then
    echo "Error: xmlstarlet is not installed. Please install it first."
    echo "  Ubuntu/Debian: sudo apt-get install xmlstarlet"
    echo "  macOS: brew install xmlstarlet"
    echo "  CentOS/RHEL: sudo yum install xmlstarlet"
    exit 1
fi

# Find all XML test result files
echo "Searching for Android test result XML files in $SEARCH_DIR..."
TEST_FILES=$(find "$SEARCH_DIR" -name "TEST-*.xml" -o -name "*-test-results.xml" -o -name "*AndroidTest*.xml")

# Check if any files were found
if [ -z "$TEST_FILES" ]; then
    echo "No Android test result XML files found."
    exit 0
fi

# Count files found
FILE_COUNT=$(echo "$TEST_FILES" | wc -l)
echo "Found $FILE_COUNT test result XML files."

# Initialize counters
TOTAL_TESTS=0
TOTAL_FAILURES=0
TOTAL_ERRORS=0
TOTAL_SKIPPED=0
TOTAL_TIME=0

# Process each file
# echo -e "\nProcessing test results:"
# echo "================================"

for FILE in $TEST_FILES; do
    echo -e "\nFile: $FILE"
    
    # Extract test suite name
    SUITE_NAME=$(xmlstarlet sel -t -v "/testsuite/@name" "$FILE" 2>/dev/null)
    if [ -z "$SUITE_NAME" ]; then
        SUITE_NAME=$(basename "$FILE" | sed 's/TEST-//g' | sed 's/.xml//g')
    fi
    
    # Extract test counts
    TESTS=$(xmlstarlet sel -t -v "/testsuite/@tests" "$FILE" 2>/dev/null)
    FAILURES=$(xmlstarlet sel -t -v "/testsuite/@failures" "$FILE" 2>/dev/null)
    ERRORS=$(xmlstarlet sel -t -v "/testsuite/@errors" "$FILE" 2>/dev/null)
    SKIPPED=$(xmlstarlet sel -t -v "/testsuite/@skipped" "$FILE" 2>/dev/null)
    TIME=$(xmlstarlet sel -t -v "/testsuite/@time" "$FILE" 2>/dev/null)
    
    # Handle empty values
    TESTS=${TESTS:-0}
    FAILURES=${FAILURES:-0}
    ERRORS=${ERRORS:-0}
    SKIPPED=${SKIPPED:-0}
    TIME=${TIME:-0}
    
    # Update totals
    TOTAL_TESTS=$((TOTAL_TESTS + TESTS))
    TOTAL_FAILURES=$((TOTAL_FAILURES + FAILURES))
    TOTAL_ERRORS=$((TOTAL_ERRORS + ERRORS))
    TOTAL_SKIPPED=$((TOTAL_SKIPPED + SKIPPED))
    TOTAL_TIME=$(echo "$TOTAL_TIME + $TIME" | bc)
    
    # Print summary for this file
    echo "  Test Suite: $SUITE_NAME"
    echo "  Tests: $TESTS, Failures: $FAILURES, Errors: $ERRORS, Skipped: $SKIPPED, Time: ${TIME}s"
    
    # Print all test cases
    echo "  All test cases:"
    xmlstarlet sel -t -m "//testcase" \
        -v "concat(@name, ' (', @classname, ')')" \
        -i "failure" -o " - FAILED" -b \
        -i "error" -o " - ERROR" -b \
        -i "skipped" -o " - SKIPPED" -b \
        -n "$FILE" | sed 's/^/    - /'
    
    # List failed tests with details if any
    if [ "$FAILURES" -gt 0 ] || [ "$ERRORS" -gt 0 ]; then
        echo "  Failed tests details:"
        xmlstarlet sel -t -m "//testcase[failure or error]" \
            -v "concat(@name, ' (', @classname, ')')" -n \
            -i "failure" -o "    Failure: " -v "failure/@message" -n -b \
            -i "error" -o "    Error: " -v "error/@message" -n -b \
            -n "$FILE" | sed 's/^/    - /'
    fi
done

# Print overall summary
echo -e "\n================================"
echo "OVERALL SUMMARY:"
echo "Total Test Files: $FILE_COUNT"
echo "Total Tests: $TOTAL_TESTS"
echo "Total Failures: $TOTAL_FAILURES"
echo "Total Errors: $TOTAL_ERRORS"
echo "Total Skipped: $TOTAL_SKIPPED"
echo "Total Time: ${TOTAL_TIME}s"

# Calculate success rate
SUCCESS=$((TOTAL_TESTS - TOTAL_FAILURES - TOTAL_ERRORS))
if [ "$TOTAL_TESTS" -gt 0 ]; then
    SUCCESS_RATE=$(echo "scale=2; ($SUCCESS * 100) / $TOTAL_TESTS" | bc)
    echo "Success Rate: ${SUCCESS_RATE}%"
fi

exit 0