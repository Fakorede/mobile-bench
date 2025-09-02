#!/usr/bin/env python3
"""
Android test execution and result parsing using subprocess approach.
Compatible with mingc/android-build-box image.
"""

import re
import json
import logging
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Represents a single test result."""
    test_name: str
    class_name: str
    status: str  # PASSED, FAILED, SKIPPED, ERROR
    duration: float = 0.0
    failure_message: str = ""
    error_message: str = ""


@dataclass
class TestExecutionResult:
    """Represents complete test execution results."""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    exit_code: int
    raw_output: str
    test_results: List[TestResult]
    build_successful: bool = False


class AndroidTesting:
    """Handles Android test execution using subprocess approach."""
    
    def __init__(self, containers_manager, config_parser):
        self.containers = containers_manager
        self.config_parser = config_parser
        
    def run_tests_from_patch(self, instance_id: str, test_patch: str, 
                           config: Dict[str, str]) -> TestExecutionResult:
        """Run tests based on test patch content."""
        
        # Extract test tasks from patch
        test_tasks = self.config_parser.extract_test_tasks_from_patch(test_patch)
        
        if not test_tasks:
            logger.warning(f"No test tasks found in patch for {instance_id}")
            
            # Return empty test result
            return TestExecutionResult(
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                duration=0.0,
                exit_code=0,
                raw_output="No test tasks found in test patch",
                test_results=[],
                build_successful=True
            )
        
        logger.info(f"Running test tasks for {instance_id}: {test_tasks}")
        
        return self.run_comprehensive_tests(instance_id, config)
    
    def run_comprehensive_tests(self, instance_id: str, config: Dict[str, str]) -> TestExecutionResult:
        """Run comprehensive Android tests using the proven subprocess approach."""
        
        start_time = time.time()
        
        # Get Java version from config
        java_version = config.get('java_version', '17')
        test_variant = config.get('test_variant', 'debug')
        
        # Build comprehensive test command similar to working android_test_runner.py
        test_command = f"""
cd /workspace &&
echo "=== Container environment ready ===" &&

echo "=== Setting Java version to {java_version} ===" &&

# Initialize jenv if available
if command -v jenv &> /dev/null; then
    eval "$(jenv init -)"
    echo 'Available Java versions in jenv:'
    jenv versions || echo 'Failed to list jenv versions'
    jenv global {java_version} || jenv global {java_version}.0 || echo 'Failed to set Java version with jenv'
    echo 'Current Java version after jenv:'
    java -version 2>&1
    echo 'JAVA_HOME after jenv:'
    echo $JAVA_HOME
else
    echo 'jenv not available, checking default Java version:'
    java -version 2>&1
    echo 'JAVA_HOME:'
    echo $JAVA_HOME
    
    # Try to set Java version manually if jenv is not available
    case {java_version} in
        8)
            export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
            ;;
        11)
            export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
            ;;
        17)
            export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
            ;;
        21)
            export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
            ;;
    esac
    
    if [ -d "$JAVA_HOME" ]; then
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "Set JAVA_HOME to: $JAVA_HOME"
        echo "Java version after manual setup:"
        java -version 2>&1
    else
        echo "Warning: Java {java_version} not found at expected location"
        echo "Available Java installations:"
        ls -la /usr/lib/jvm/ || echo "No JVM directory found"
    fi
fi

# Set ANDROID_SDK_ROOT if needed
if [ -d '/opt/android-sdk' ]; then
    export ANDROID_SDK_ROOT='/opt/android-sdk'
    echo 'Set ANDROID_SDK_ROOT to /opt/android-sdk'
fi

# Set additional environment variables for Android builds
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_HOME='/opt/android-sdk'
export PATH="$PATH:/opt/android-sdk/platform-tools:/opt/android-sdk/tools"

# Fix HOME and Gradle directories
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle || true

echo "=== Cleaning previous builds ===" &&
rm -rf build/ || true &&
rm -rf app/build/ || true &&
rm -rf */build/ || true &&
rm -rf .gradle/ || true &&
rm -rf /tmp/.gradle/caches/ || true &&
rm -rf /tmp/.gradle/daemon/ || true &&

echo "=== Configuring Gradle ===" &&
mkdir -p /tmp/.gradle &&
echo 'org.gradle.daemon=false' > /tmp/.gradle/gradle.properties &&
echo 'org.gradle.parallel=false' >> /tmp/.gradle/gradle.properties &&
echo 'org.gradle.configureondemand=false' >> /tmp/.gradle/gradle.properties &&
echo 'org.gradle.jvmargs=-Xmx2g -XX:MaxMetaspaceSize=256m -XX:+UseG1GC' >> /tmp/.gradle/gradle.properties &&
echo 'org.gradle.workers.max=2' >> /tmp/.gradle/gradle.properties &&
echo 'android.enableJetifier=true' >> /tmp/.gradle/gradle.properties &&
echo 'android.useAndroidX=true' >> /tmp/.gradle/gradle.properties &&

echo "=== Killing any existing Gradle daemons ===" &&
./gradlew --stop 2>/dev/null || true &&
pkill -f gradle 2>/dev/null || true &&

echo "=== Running Gradle tests ===" &&
if [ -f './gradlew' ]; then
    chmod +x ./gradlew
    echo "=== First attempting to download dependencies ===" &&
    timeout 300 ./gradlew --no-daemon --stacktrace dependencies || echo "Dependencies download completed/failed, continuing..." &&
    echo "=== Now running tests ===" &&
    timeout 600 ./gradlew test{test_variant.capitalize()}UnitTest --no-daemon --stacktrace --info --continue || true &&
    echo "=== Running app module tests specifically ===" &&
    timeout 600 ./gradlew :app:test{test_variant.capitalize()}UnitTest --no-daemon --stacktrace --info --continue || true &&
    echo "=== Running other module tests ===" &&
    timeout 600 ./gradlew :data:test{test_variant.capitalize()}UnitTest :network:test{test_variant.capitalize()}UnitTest :authenticatorbridge:test{test_variant.capitalize()}UnitTest --no-daemon --stacktrace --info --continue || true
else
    if [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
        timeout 600 gradle test{test_variant.capitalize()}UnitTest :app:test{test_variant.capitalize()}UnitTest --no-daemon --stacktrace --info --continue || true
    else
        echo 'No Gradle build files found'
    fi
fi &&

echo "=== Parsing test results ===" &&
find . -name "TEST-*.xml" -type f 2>/dev/null | head -20 | while read file; do
    echo "=== XML FILE START: $file ===" 
    cat "$file"
    echo "=== XML FILE END: $file ==="
    echo ""
done

# Also show directory structure of test results
echo "=== Test Results Directory Structure ===" &&
find . -name "*test*" -type d 2>/dev/null | head -10 &&
find . -name "*.xml" -type f 2>/dev/null | head -10
"""
        
        logger.info(f"Executing comprehensive Android tests for {instance_id}")
        
        # Execute with extended timeout
        exit_code, output = self.containers.exec_command(
            instance_id,
            test_command,
            workdir="/workspace",
            timeout=1200  # 20 minutes
        )
        
        total_duration = time.time() - start_time
        
        logger.info(f"Test execution completed in {total_duration:.2f}s with exit code {exit_code}")
        
        # Parse results from output
        test_results = self._parse_test_results(output)
        
        # Create execution result
        execution_result = self._create_execution_result(
            test_results, exit_code, output, total_duration
        )
        
        logger.info(f"Test execution completed: {execution_result.passed}/{execution_result.total_tests} passed")
        
        return execution_result
    
    def _parse_test_results(self, output: str) -> List[TestResult]:
        """Parse test results from Android test output."""
        test_results = []
        
        # Method 1: Parse XML content directly from output
        xml_pattern = r'<testcase[^>]+name="([^"]+)"[^>]+classname="([^"]+)"[^>]*(?:/>|>.*?</testcase>)'
        xml_matches = re.findall(xml_pattern, output, re.DOTALL)
        
        for match in xml_matches:
            test_name = match[0].strip()
            class_name = match[1].strip()
            
            # Check if this test case has failure/error tags
            test_case_xml = re.search(
                rf'<testcase[^>]+name="{re.escape(test_name)}"[^>]+classname="{re.escape(class_name)}"[^>]*>.*?</testcase>',
                output, re.DOTALL
            )
            
            status = "PASSED"  # Default
            failure_msg = ""
            error_msg = ""
            duration = 0.0
            
            if test_case_xml:
                test_xml_content = test_case_xml.group(0)
                
                # Extract duration
                time_match = re.search(r'time="([^"]+)"', test_xml_content)
                if time_match:
                    try:
                        duration = float(time_match.group(1))
                    except ValueError:
                        duration = 0.0
                
                # Check status
                if '<failure' in test_xml_content:
                    status = "FAILED"
                    failure_match = re.search(r'<failure[^>]*>(.*?)</failure>', test_xml_content, re.DOTALL)
                    if failure_match:
                        failure_msg = failure_match.group(1).strip()
                elif '<error' in test_xml_content:
                    status = "ERROR"
                    error_match = re.search(r'<error[^>]*>(.*?)</error>', test_xml_content, re.DOTALL)
                    if error_match:
                        error_msg = error_match.group(1).strip()
                elif '<skipped' in test_xml_content:
                    status = "SKIPPED"
            
            test_result = TestResult(
                test_name=test_name,
                class_name=class_name,
                status=status,
                duration=duration,
                failure_message=failure_msg,
                error_message=error_msg
            )
            test_results.append(test_result)
        
        # Method 2: Parse console output patterns
        console_patterns = [
            r'(\w+(?:\.\w+)*) > (\w+) (PASSED|FAILED|SKIPPED)',
            r'(\w+(?:\.\w+)*) > (\w+) (PASSED|FAILED|SKIPPED) \((\d+\.?\d*)s\)',
            r'(\w+(?:\.\w+)*):(\w+) (PASSED|FAILED|SKIPPED)',
        ]
        
        existing_tests = {f"{t.class_name}.{t.test_name}" for t in test_results}
        
        for line in output.split('\n'):
            line = line.strip()
            
            for pattern in console_patterns:
                match = re.search(pattern, line)
                if match:
                    groups = match.groups()
                    class_name = groups[0]
                    test_name = groups[1]
                    status = groups[2]
                    duration = float(groups[3]) if len(groups) > 3 and groups[3] else 0.0
                    
                    # Avoid duplicates
                    test_key = f"{class_name}.{test_name}"
                    if test_key not in existing_tests:
                        test_result = TestResult(
                            test_name=test_name,
                            class_name=class_name,
                            status=status,
                            duration=duration,
                            failure_message="",
                            error_message=""
                        )
                        test_results.append(test_result)
                        existing_tests.add(test_key)
                    break
        
        return test_results
    
    def _create_execution_result(self, test_results: List[TestResult], 
                               exit_code: int, raw_output: str, 
                               duration: float) -> TestExecutionResult:
        """Create a comprehensive test execution result."""
        
        total_tests = len(test_results)
        passed = len([t for t in test_results if t.status == 'PASSED'])
        failed = len([t for t in test_results if t.status == 'FAILED'])
        skipped = len([t for t in test_results if t.status == 'SKIPPED'])
        errors = len([t for t in test_results if t.status == 'ERROR'])
        
        # Determine if build was successful
        build_successful = ('BUILD SUCCESSFUL' in raw_output or 
                          'BUILD FAILED' not in raw_output)
        
        return TestExecutionResult(
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration=duration,
            exit_code=exit_code,
            raw_output=raw_output,
            test_results=test_results,
            build_successful=build_successful
        )
    
    def compare_test_results(self, pre_results: TestExecutionResult, 
                           post_results: TestExecutionResult) -> Dict[str, List[str]]:
        """Compare pre and post test results to find test state transitions."""
        
        # Create lookup maps
        pre_tests = {f"{t.class_name}.{t.test_name}": t.status 
                    for t in pre_results.test_results}
        post_tests = {f"{t.class_name}.{t.test_name}": t.status 
                     for t in post_results.test_results}
        
        fail_to_pass = []
        pass_to_pass = []
        pass_to_fail = []
        fail_to_fail = []
        removed_tests = []
        new_tests = []
        
        # Analyze test status changes
        all_tests = set(pre_tests.keys()) | set(post_tests.keys())
        
        for test_name in all_tests:
            pre_status = pre_tests.get(test_name, 'NOT_FOUND')
            post_status = post_tests.get(test_name, 'NOT_FOUND')
            
            if pre_status == 'NOT_FOUND':
                new_tests.append(test_name)
            elif post_status == 'NOT_FOUND':
                removed_tests.append(test_name)
            elif pre_status in ['FAILED', 'ERROR'] and post_status == 'PASSED':
                fail_to_pass.append(test_name)
            elif pre_status == 'PASSED' and post_status == 'PASSED':
                pass_to_pass.append(test_name)
            elif pre_status == 'PASSED' and post_status in ['FAILED', 'ERROR']:
                pass_to_fail.append(test_name)
            elif pre_status in ['FAILED', 'ERROR'] and post_status in ['FAILED', 'ERROR']:
                fail_to_fail.append(test_name)
        
        return {
            'fail_to_pass': fail_to_pass,
            'pass_to_pass': pass_to_pass,
            'pass_to_fail': pass_to_fail,
            'fail_to_fail': fail_to_fail,
            'removed_tests': removed_tests,
            'new_tests': new_tests
        }
    
    def save_test_results(self, result: TestExecutionResult, output_file: str):
        """Save test results to JSON file."""
        data = {
            'summary': {
                'total_tests': result.total_tests,
                'passed': result.passed,
                'failed': result.failed,
                'skipped': result.skipped,
                'errors': result.errors,
                'duration': result.duration,
                'exit_code': result.exit_code,
                'build_successful': result.build_successful
            },
            'tests': [
                {
                    'test_name': test.test_name,
                    'class_name': test.class_name,
                    'status': test.status,
                    'duration': test.duration,
                    'failure_message': test.failure_message,
                    'error_message': test.error_message
                }
                for test in result.test_results
            ]
        }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def format_test_summary(self, result: TestExecutionResult) -> str:
        """Format test results into readable summary."""
        summary = f"""
Android Test Execution Summary:
==============================
Total Tests: {result.total_tests}
Passed: {result.passed}
Failed: {result.failed}
Skipped: {result.skipped}
Errors: {result.errors}
Duration: {result.duration:.2f}s
Exit Code: {result.exit_code}
Build Successful: {result.build_successful}

"""
        
        if result.failed > 0 or result.errors > 0:
            summary += "Failed/Error Tests:\n"
            summary += "-------------------\n"
            for test in result.test_results:
                if test.status in ['FAILED', 'ERROR']:
                    summary += f"- {test.class_name}.{test.test_name}: {test.status}\n"
                    if test.failure_message:
                        summary += f"  Message: {test.failure_message[:100]}...\n"
        
        return summary


if __name__ == "__main__":
    # Test the testing module
    logging.basicConfig(level=logging.INFO)
    print("Android Testing (subprocess) module loaded successfully")