#!/usr/bin/env python3
"""
Android test execution and result parsing for debug variant only.
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
    """Handles Android test execution for debug variant only."""
    
    def __init__(self, containers_manager, config_parser):
        self.containers = containers_manager
        self.config_parser = config_parser
        
    def run_tests_from_patch(self, instance_id: str, test_patch: str, 
                           config: Dict[str, str]) -> TestExecutionResult:
        """Run tests based on test patch content, debug variant only."""
        
        # Extract test tasks from patch
        test_tasks = self.config_parser.extract_test_tasks_from_patch(test_patch)
        
        # Filter to debug variant only
        debug_tasks = [task for task in test_tasks if 'debug' in task.lower()]

        if not debug_tasks:
            logger.warning(f"No debug test tasks found in patch for {instance_id}")
            logger.info(f"Available test tasks from patch: {test_tasks}")

            # Return empty test result
            return TestExecutionResult(
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
                duration=0.0,
                exit_code=0,
                raw_output="No debug test tasks found in test patch",
                test_results=[],
                build_successful=True
            )

            # OR Fail the validation
            # raise ValueError(f"No debug test tasks found in patch for {instance_id}")
        
        logger.info(f"Running debug test tasks for {instance_id}: {debug_tasks}")
        
        return self.run_specific_tests(instance_id, debug_tasks)
    
    def run_specific_tests(self, instance_id: str, test_tasks: List[str]) -> TestExecutionResult:
        """Run specific test tasks and return comprehensive results."""
        
        # Prepare environment for testing
        self._prepare_test_environment(instance_id)
        
        start_time = time.time()
        all_results = []
        combined_output = ""
        final_exit_code = 0
        
        for task in test_tasks:
            logger.info(f"Executing test task: {task}")
            
            # Run the specific test task
            exit_code, output = self._execute_gradle_test(instance_id, task)
            
            combined_output += f"\n{'='*50}\n"
            combined_output += f"Task: {task}\n"
            combined_output += f"Exit Code: {exit_code}\n"
            combined_output += f"{'='*50}\n"
            combined_output += output
            combined_output += f"\n{'='*50}\n"
            
            if exit_code != 0:
                final_exit_code = exit_code
            
            # Parse results from this task
            task_results = self._parse_test_results(output, task)
            all_results.extend(task_results)
        
        total_duration = time.time() - start_time
        
        # Combine and summarize all results
        combined_result = self._create_execution_result(
            all_results, final_exit_code, combined_output, total_duration
        )
        
        logger.info(f"Test execution completed: {combined_result.passed}/{combined_result.total_tests} passed")
        
        return combined_result
    
    def _prepare_test_environment(self, instance_id: str):
        """Prepare the environment for test execution."""
        logger.info(f"Preparing test environment for {instance_id}")
        
        # Clean previous builds
        exit_code, output = self.containers.exec_command(
            instance_id, 
            "./gradlew clean --no-daemon",
            workdir="/workspace"
        )
        if exit_code != 0:
            logger.warning(f"Clean failed: {output}")
        
        # Ensure gradlew is executable
        self.containers.exec_command(
            instance_id,
            "chmod +x gradlew",
            workdir="/workspace"
        )
        
        # Download dependencies (but don't fail if this doesn't work)
        exit_code, output = self.containers.exec_command(
            instance_id,
            "./gradlew dependencies --no-daemon --quiet",
            workdir="/workspace"
        )
        if exit_code != 0:
            logger.warning(f"Dependency download had issues: {output}")
    
    def _execute_gradle_test(self, instance_id: str, test_task: str) -> Tuple[int, str]:
        """Execute a specific gradle test task."""
        
        # Build the gradle command
        gradle_cmd = f"./gradlew {test_task} --no-daemon --stacktrace --continue"
        
        logger.info(f"Executing: {gradle_cmd}")
        
        # Execute with timeout (30 minutes max)
        start_time = time.time()
        exit_code, output = self.containers.exec_command(
            instance_id,
            gradle_cmd,
            workdir="/workspace"
        )
        
        execution_time = time.time() - start_time
        logger.info(f"Test execution completed in {execution_time:.2f}s with exit code {exit_code}")
        
        return exit_code, output
    
    def _parse_test_results(self, output: str, task_name: str) -> List[TestResult]:
        """Parse gradle test output to extract individual test results."""
        test_results = []
        
        # Try to parse from XML reports first (more reliable)
        xml_results = self._try_parse_xml_reports(output)
        if xml_results:
            return xml_results
        
        # Fallback to parsing console output
        return self._parse_console_output(output, task_name)
    
    def _try_parse_xml_reports(self, output: str) -> List[TestResult]:
        """Try to extract XML test report locations and parse them."""
        # Look for XML report file mentions in output
        xml_pattern = r'Test results saved to file://(.+\.xml)'
        matches = re.findall(xml_pattern, output)
        
        # For now, return empty list to use console parsing
        # In a full implementation, you would parse the XML files
        return []
    
    def _parse_console_output(self, output: str, task_name: str) -> List[TestResult]:
        """Parse test results from gradle console output."""
        test_results = []
        
        # Patterns for different test result formats
        patterns = {
            'test_execution': [
                r'(\w+(?:\.\w+)*) > (\w+) (PASSED|FAILED|SKIPPED)',
                r'(\w+(?:\.\w+)*) > (\w+) (PASSED|FAILED|SKIPPED) \((\d+\.?\d*)s\)',
                r'(\w+(?:\.\w+)*):(\w+) (PASSED|FAILED|SKIPPED)',
            ],
            'test_summary': [
                r'(\d+) tests completed, (\d+) failed, (\d+) skipped',
                r'Tests: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)',
            ]
        }
        
        # Parse individual test results
        for line in output.split('\n'):
            line = line.strip()
            
            for pattern in patterns['test_execution']:
                match = re.search(pattern, line)
                if match:
                    groups = match.groups()
                    class_name = groups[0]
                    test_name = groups[1]
                    status = groups[2]
                    duration = float(groups[3]) if len(groups) > 3 and groups[3] else 0.0
                    
                    # Look for failure/error details in subsequent lines
                    failure_msg = ""
                    error_msg = ""
                    
                    if status in ['FAILED', 'ERROR']:
                        failure_msg = self._extract_failure_message(output, class_name, test_name)
                    
                    test_result = TestResult(
                        test_name=test_name,
                        class_name=class_name,
                        status=status,
                        duration=duration,
                        failure_message=failure_msg,
                        error_message=error_msg if status == 'ERROR' else ""
                    )
                    test_results.append(test_result)
                    break
        
        return test_results
    
    def _extract_failure_message(self, output: str, class_name: str, test_name: str) -> str:
        """Extract failure message for a specific test."""
        # Look for failure details in the output
        failure_patterns = [
            rf'{class_name}\.{test_name}.*?FAILED.*?\n(.*?)\n',
            rf'{test_name}.*?FAILED.*?\n(.*?)\n',
            rf'> {test_name}.*?\n(.*?at .*?)\n'
        ]
        
        for pattern in failure_patterns:
            match = re.search(pattern, output, re.DOTALL)
            if match:
                return match.group(1).strip()
        
        return ""
    
    def _create_execution_result(self, test_results: List[TestResult], 
                               exit_code: int, raw_output: str, 
                               duration: float) -> TestExecutionResult:
        """Create a comprehensive test execution result."""
        
        total_tests = len(test_results)
        passed = len([t for t in test_results if t.status == 'PASSED'])
        failed = len([t for t in test_results if t.status == 'FAILED'])
        skipped = len([t for t in test_results if t.status == 'SKIPPED'])
        errors = len([t for t in test_results if t.status == 'ERROR'])
        
        # Determine if build was successful based on output
        build_successful = 'BUILD SUCCESSFUL' in raw_output
        
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
    print("Android Testing module loaded successfully")