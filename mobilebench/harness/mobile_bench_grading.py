#!/usr/bin/env python3

"""
Mobile-Bench Grading System
Comprehensive grading and evaluation logic for mobile-bench results.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
import docker


class TestStatus(Enum):
    """Test execution status"""
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"
    NOT_RUN = "NOT_RUN"


class EvaluationStatus(Enum):
    """Overall evaluation status"""
    PATCH_APPLY_SUCCESS = "PATCH_APPLY_SUCCESS"
    PATCH_APPLY_FAIL = "PATCH_APPLY_FAIL"
    BUILD_SUCCESS = "BUILD_SUCCESS"
    BUILD_FAIL = "BUILD_FAIL"
    TEST_SUCCESS = "TEST_SUCCESS"
    TEST_FAIL = "TEST_FAIL"
    TEST_TIMEOUT = "TEST_TIMEOUT"
    CONTAINER_ERROR = "CONTAINER_ERROR"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class TestCase:
    """Individual test case result"""
    name: str
    class_name: str
    status: TestStatus
    execution_time: float = 0.0
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    failure_details: Optional[str] = None
    
    @property
    def full_name(self) -> str:
        """Get full test name with class"""
        return f"{self.class_name}::{self.name}" if self.class_name else self.name
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'class_name': self.class_name,
            'status': self.status.value,
            'execution_time': self.execution_time,
            'error_message': self.error_message,
            'error_type': self.error_type,
            'failure_details': self.failure_details,
            'full_name': self.full_name
        }


@dataclass
class TestSuite:
    """Test suite results"""
    name: str
    tests: List[TestCase] = field(default_factory=list)
    execution_time: float = 0.0
    setup_time: float = 0.0
    teardown_time: float = 0.0
    
    @property
    def total_tests(self) -> int:
        return len(self.tests)
    
    @property
    def passed_tests(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.PASSED)
    
    @property
    def failed_tests(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.FAILED)
    
    @property
    def error_tests(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.ERROR)
    
    @property
    def skipped_tests(self) -> int:
        return sum(1 for t in self.tests if t.status == TestStatus.SKIPPED)
    
    @property
    def success_rate(self) -> float:
        return self.passed_tests / self.total_tests if self.total_tests > 0 else 0.0
    
    def get_failed_tests(self) -> List[TestCase]:
        """Get list of failed tests"""
        return [t for t in self.tests if t.status in [TestStatus.FAILED, TestStatus.ERROR]]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'total_tests': self.total_tests,
            'passed_tests': self.passed_tests,
            'failed_tests': self.failed_tests,
            'error_tests': self.error_tests,
            'skipped_tests': self.skipped_tests,
            'success_rate': self.success_rate,
            'execution_time': self.execution_time,
            'setup_time': self.setup_time,
            'teardown_time': self.teardown_time,
            'tests': [t.to_dict() for t in self.tests]
        }


@dataclass
class EvaluationResult:
    """Complete evaluation result for an instance"""
    instance_id: str
    status: EvaluationStatus
    
    # Execution details
    patch_applied: bool = False
    build_successful: bool = False
    tests_executed: bool = False
    
    # Test results
    test_suites: List[TestSuite] = field(default_factory=list)
    
    # Performance metrics
    total_execution_time: float = 0.0
    patch_time: float = 0.0
    build_time: float = 0.0
    test_time: float = 0.0
    
    # Error information
    error_message: Optional[str] = None
    error_logs: List[str] = field(default_factory=list)
    
    # Expected vs actual results
    expected_pass_tests: Set[str] = field(default_factory=set)
    expected_fail_tests: Set[str] = field(default_factory=set)
    
    # Resolution status
    resolved: bool = False
    resolution_details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_tests(self) -> int:
        return sum(suite.total_tests for suite in self.test_suites)
    
    @property
    def passed_tests(self) -> int:
        return sum(suite.passed_tests for suite in self.test_suites)
    
    @property
    def failed_tests(self) -> int:
        return sum(suite.failed_tests for suite in self.test_suites)
    
    @property
    def error_tests(self) -> int:
        return sum(suite.error_tests for suite in self.test_suites)
    
    @property
    def skipped_tests(self) -> int:
        return sum(suite.skipped_tests for suite in self.test_suites)
    
    @property
    def overall_success_rate(self) -> float:
        return self.passed_tests / self.total_tests if self.total_tests > 0 else 0.0
    
    def get_all_failed_tests(self) -> List[TestCase]:
        """Get all failed tests across all suites"""
        failed_tests = []
        for suite in self.test_suites:
            failed_tests.extend(suite.get_failed_tests())
        return failed_tests
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'instance_id': self.instance_id,
            'status': self.status.value,
            'patch_applied': self.patch_applied,
            'build_successful': self.build_successful,
            'tests_executed': self.tests_executed,
            'total_tests': self.total_tests,
            'passed_tests': self.passed_tests,
            'failed_tests': self.failed_tests,
            'error_tests': self.error_tests,
            'skipped_tests': self.skipped_tests,
            'overall_success_rate': self.overall_success_rate,
            'total_execution_time': self.total_execution_time,
            'patch_time': self.patch_time,
            'build_time': self.build_time,
            'test_time': self.test_time,
            'error_message': self.error_message,
            'error_logs': self.error_logs,
            'expected_pass_tests': list(self.expected_pass_tests),
            'expected_fail_tests': list(self.expected_fail_tests),
            'resolved': self.resolved,
            'resolution_details': self.resolution_details,
            'test_suites': [suite.to_dict() for suite in self.test_suites]
        }


class AndroidTestResultParser:
    """Parses Android test results from various formats"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def parse_junit_xml(self, xml_content: str) -> Optional[TestSuite]:
        """Parse JUnit XML test results"""
        try:
            root = ET.fromstring(xml_content)
            
            # Handle both <testsuite> and <testsuites> root elements
            if root.tag == 'testsuites':
                suites = []
                for suite_elem in root.findall('testsuite'):
                    suite = self._parse_testsuite_element(suite_elem)
                    if suite:
                        suites.append(suite)
                return suites[0] if suites else None
            elif root.tag == 'testsuite':
                return self._parse_testsuite_element(root)
            
        except ET.ParseError as e:
            self.logger.warning(f"Failed to parse XML: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing test results: {e}")
        
        return None
    
    def _parse_testsuite_element(self, suite_elem: ET.Element) -> TestSuite:
        """Parse a single testsuite element"""
        suite_name = suite_elem.get('name', 'Unknown')
        execution_time = float(suite_elem.get('time', 0.0))
        
        suite = TestSuite(
            name=suite_name,
            execution_time=execution_time
        )
        
        # Parse test cases
        for testcase_elem in suite_elem.findall('testcase'):
            test_case = self._parse_testcase_element(testcase_elem)
            if test_case:
                suite.tests.append(test_case)
        
        return suite
    
    def _parse_testcase_element(self, testcase_elem: ET.Element) -> TestCase:
        """Parse a single testcase element"""
        name = testcase_elem.get('name', 'Unknown')
        class_name = testcase_elem.get('classname', '')
        execution_time = float(testcase_elem.get('time', 0.0))
        
        # Determine test status
        status = TestStatus.PASSED
        error_message = None
        error_type = None
        failure_details = None
        
        # Check for failure
        failure_elem = testcase_elem.find('failure')
        if failure_elem is not None:
            status = TestStatus.FAILED
            error_message = failure_elem.get('message', '')
            error_type = failure_elem.get('type', '')
            failure_details = failure_elem.text
        
        # Check for error
        error_elem = testcase_elem.find('error')
        if error_elem is not None:
            status = TestStatus.ERROR
            error_message = error_elem.get('message', '')
            error_type = error_elem.get('type', '')
            failure_details = error_elem.text
        
        # Check for skipped
        skipped_elem = testcase_elem.find('skipped')
        if skipped_elem is not None:
            status = TestStatus.SKIPPED
            error_message = skipped_elem.get('message', '')
        
        return TestCase(
            name=name,
            class_name=class_name,
            status=status,
            execution_time=execution_time,
            error_message=error_message,
            error_type=error_type,
            failure_details=failure_details
        )
    
    def parse_container_test_results(self, container: docker.models.containers.Container, repo_path: str) -> List[TestSuite]:
        """Parse test results from container filesystem"""
        suites = []
        
        try:
            # Find test result files
            result = container.exec_run(
                f"find {repo_path} -name 'TEST-*.xml' -o -name '*test-results.xml' -o -name '*AndroidTest*.xml'",
                workdir=repo_path
            )
            
            if result.exit_code != 0:
                self.logger.warning("No test result files found")
                return suites
            
            test_files = result.output.decode('utf-8').strip().split('\n')
            test_files = [f.strip() for f in test_files if f.strip()]
            
            for test_file in test_files:
                # Read test file content
                file_result = container.exec_run(f"cat {test_file}")
                if file_result.exit_code == 0:
                    xml_content = file_result.output.decode('utf-8')
                    suite = self.parse_junit_xml(xml_content)
                    if suite:
                        suites.append(suite)
                
        except Exception as e:
            self.logger.error(f"Failed to parse container test results: {e}")
        
        return suites


class AndroidEvaluationGrader:
    """Grades Android evaluation results"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.parser = AndroidTestResultParser()
    
    def grade_evaluation(self, 
                        container: docker.models.containers.Container,
                        repo_path: str,
                        expected_pass_tests: Set[str],
                        expected_fail_tests: Set[str],
                        execution_log: str = "") -> EvaluationResult:
        """Grade a complete evaluation"""
        
        result = EvaluationResult(
            instance_id="",  # Will be set by caller
            status=EvaluationStatus.CONTAINER_ERROR,
            expected_pass_tests=expected_pass_tests,
            expected_fail_tests=expected_fail_tests
        )
        
        try:
            # Parse test results
            result.test_suites = self.parser.parse_container_test_results(container, repo_path)
            result.tests_executed = len(result.test_suites) > 0
            
            # Determine overall status
            result.status = self._determine_status(result, execution_log)
            
            # Check resolution
            result.resolved, result.resolution_details = self._check_resolution(result)
            
        except Exception as e:
            result.error_message = str(e)
            result.status = EvaluationStatus.CONTAINER_ERROR
            self.logger.error(f"Failed to grade evaluation: {e}")
        
        return result
    
    def _determine_status(self, result: EvaluationResult, execution_log: str) -> EvaluationStatus:
        """Determine overall evaluation status"""
        
        # Check for container errors
        if "CONTAINER_ERROR" in execution_log:
            return EvaluationStatus.CONTAINER_ERROR
        
        # Check for patch application
        if "PATCH_APPLY_FAIL" in execution_log or "Failed to apply patch" in execution_log:
            return EvaluationStatus.PATCH_APPLY_FAIL
        
        result.patch_applied = True
        
        # Check for build failures
        if "BUILD_FAIL" in execution_log or "Build failed" in execution_log:
            return EvaluationStatus.BUILD_FAIL
        
        result.build_successful = True
        
        # Check for test timeout
        if "TEST_TIMEOUT" in execution_log or "Test timed out" in execution_log:
            return EvaluationStatus.TEST_TIMEOUT
        
        # Check test results
        if result.tests_executed:
            if result.failed_tests == 0 and result.error_tests == 0:
                return EvaluationStatus.TEST_SUCCESS
            else:
                return EvaluationStatus.TEST_FAIL
        
        return EvaluationStatus.TEST_FAIL
    
    def _check_resolution(self, result: EvaluationResult) -> Tuple[bool, Dict[str, Any]]:
        """Check if the evaluation resolves the issue"""
        details = {
            'expected_pass_results': {},
            'expected_fail_results': {},
            'resolution_type': 'unknown'
        }
        
        # Get all test names from results
        actual_test_results = {}
        for suite in result.test_suites:
            for test in suite.tests:
                actual_test_results[test.full_name] = test.status
        
        # Check expected pass tests
        pass_resolution = True
        for expected_pass in result.expected_pass_tests:
            if expected_pass in actual_test_results:
                status = actual_test_results[expected_pass]
                details['expected_pass_results'][expected_pass] = status.value
                if status != TestStatus.PASSED:
                    pass_resolution = False
            else:
                details['expected_pass_results'][expected_pass] = TestStatus.NOT_RUN.value
                pass_resolution = False
        
        # Check expected fail tests
        fail_resolution = True
        for expected_fail in result.expected_fail_tests:
            if expected_fail in actual_test_results:
                status = actual_test_results[expected_fail]
                details['expected_fail_results'][expected_fail] = status.value
                if status != TestStatus.PASSED:
                    fail_resolution = False
            else:
                details['expected_fail_results'][expected_fail] = TestStatus.NOT_RUN.value
                fail_resolution = False
        
        # Determine resolution type and overall resolution
        resolved = False
        if result.expected_pass_tests and result.expected_fail_tests:
            # Both types of tests expected
            resolved = pass_resolution and fail_resolution
            details['resolution_type'] = 'full' if resolved else 'partial'
        elif result.expected_pass_tests:
            # Only pass tests expected
            resolved = pass_resolution
            details['resolution_type'] = 'pass_only'
        elif result.expected_fail_tests:
            # Only fail tests expected
            resolved = fail_resolution
            details['resolution_type'] = 'fail_to_pass'
        else:
            # No specific tests expected, check overall success
            resolved = result.overall_success_rate > 0.8  # 80% success threshold
            details['resolution_type'] = 'general'
        
        details['pass_resolution'] = pass_resolution
        details['fail_resolution'] = fail_resolution
        details['overall_success_rate'] = result.overall_success_rate
        
        return resolved, details


class AndroidTestMetrics:
    """Calculates various metrics for Android test results"""
    
    @staticmethod
    def calculate_coverage_metrics(result: EvaluationResult) -> Dict[str, float]:
        """Calculate test coverage metrics"""
        metrics = {
            'test_execution_rate': 0.0,
            'test_success_rate': 0.0,
            'expected_test_coverage': 0.0,
            'resolution_score': 0.0
        }
        
        if result.total_tests > 0:
            metrics['test_execution_rate'] = 1.0  # All found tests were executed
            metrics['test_success_rate'] = result.overall_success_rate
        
        # Calculate expected test coverage
        total_expected = len(result.expected_pass_tests) + len(result.expected_fail_tests)
        if total_expected > 0:
            covered_tests = 0
            for suite in result.test_suites:
                for test in suite.tests:
                    if (test.full_name in result.expected_pass_tests or 
                        test.full_name in result.expected_fail_tests):
                        covered_tests += 1
            metrics['expected_test_coverage'] = covered_tests / total_expected
        
        # Calculate resolution score
        if result.resolved:
            metrics['resolution_score'] = 1.0
        else:
            # Partial credit based on test success rate
            metrics['resolution_score'] = result.overall_success_rate * 0.5
        
        return metrics
    
    @staticmethod
    def calculate_performance_metrics(result: EvaluationResult) -> Dict[str, float]:
        """Calculate performance metrics"""
        return {
            'total_execution_time': result.total_execution_time,
            'patch_time': result.patch_time,
            'build_time': result.build_time,
            'test_time': result.test_time,
            'avg_test_time': result.test_time / result.total_tests if result.total_tests > 0 else 0.0,
            'time_efficiency': result.total_tests / result.total_execution_time if result.total_execution_time > 0 else 0.0
        }
    
    @staticmethod
    def calculate_quality_metrics(result: EvaluationResult) -> Dict[str, Any]:
        """Calculate code quality metrics"""
        failed_tests = result.get_all_failed_tests()
        
        # Categorize failures
        compilation_errors = [t for t in failed_tests if 'compilation' in (t.error_message or '').lower()]
        runtime_errors = [t for t in failed_tests if 'runtime' in (t.error_message or '').lower()]
        assertion_failures = [t for t in failed_tests if 'assert' in (t.error_message or '').lower()]
        
        return {
            'compilation_error_count': len(compilation_errors),
            'runtime_error_count': len(runtime_errors),
            'assertion_failure_count': len(assertion_failures),
            'error_diversity': len(set(t.error_type for t in failed_tests if t.error_type)),
            'most_common_error': AndroidTestMetrics._get_most_common_error(failed_tests),
            'error_patterns': AndroidTestMetrics._analyze_error_patterns(failed_tests)
        }
    
    @staticmethod
    def _get_most_common_error(failed_tests: List[TestCase]) -> Optional[str]:
        """Get the most common error type"""
        if not failed_tests:
            return None
        
        error_counts = {}
        for test in failed_tests:
            error_type = test.error_type or 'Unknown'
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        return max(error_counts.items(), key=lambda x: x[1])[0] if error_counts else None
    
    @staticmethod
    def _analyze_error_patterns(failed_tests: List[TestCase]) -> List[Dict[str, Any]]:
        """Analyze patterns in test failures"""
        patterns = []
        
        # Group by error message keywords
        error_keywords = {}
        for test in failed_tests:
            if test.error_message:
                words = re.findall(r'\b\w+\b', test.error_message.lower())
                for word in words:
                    if len(word) > 3:  # Filter out short words
                        error_keywords[word] = error_keywords.get(word, 0) + 1
        
        # Find most common keywords
        common_keywords = sorted(error_keywords.items(), key=lambda x: x[1], reverse=True)[:5]
        
        for keyword, count in common_keywords:
            patterns.append({
                'keyword': keyword,
                'frequency': count,
                'percentage': count / len(failed_tests) * 100
            })
        
        return patterns


class MobileBenchGradingReport:
    """Generates comprehensive grading reports"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def generate_instance_report(self, result: EvaluationResult) -> Dict[str, Any]:
        """Generate detailed report for a single instance"""
        coverage_metrics = AndroidTestMetrics.calculate_coverage_metrics(result)
        performance_metrics = AndroidTestMetrics.calculate_performance_metrics(result)
        quality_metrics = AndroidTestMetrics.calculate_quality_metrics(result)
        
        report = {
            'instance_id': result.instance_id,
            'summary': {
                'status': result.status.value,
                'resolved': result.resolved,
                'patch_applied': result.patch_applied,
                'build_successful': result.build_successful,
                'tests_executed': result.tests_executed
            },
            'test_results': {
                'total_tests': result.total_tests,
                'passed_tests': result.passed_tests,
                'failed_tests': result.failed_tests,
                'error_tests': result.error_tests,
                'skipped_tests': result.skipped_tests,
                'success_rate': result.overall_success_rate
            },
            'metrics': {
                'coverage': coverage_metrics,
                'performance': performance_metrics,
                'quality': quality_metrics
            },
            'resolution_details': result.resolution_details,
            'test_suites': [suite.to_dict() for suite in result.test_suites],
            'failed_tests': [test.to_dict() for test in result.get_all_failed_tests()],
            'execution_info': {
                'total_time': result.total_execution_time,
                'patch_time': result.patch_time,
                'build_time': result.build_time,
                'test_time': result.test_time,
                'error_message': result.error_message,
                'error_logs': result.error_logs
            }
        }
        
        return report
    
    def generate_aggregate_report(self, results: List[EvaluationResult]) -> Dict[str, Any]:
        """Generate aggregate report across multiple instances"""
        if not results:
            return {'error': 'No results provided'}
        
        total_instances = len(results)
        
        # Aggregate basic statistics
        patch_success = sum(1 for r in results if r.patch_applied)
        build_success = sum(1 for r in results if r.build_successful)
        test_execution = sum(1 for r in results if r.tests_executed)
        resolved_instances = sum(1 for r in results if r.resolved)
        
        # Aggregate test statistics
        total_tests = sum(r.total_tests for r in results)
        total_passed = sum(r.passed_tests for r in results)
        total_failed = sum(r.failed_tests for r in results)
        total_errors = sum(r.error_tests for r in results)
        
        # Status distribution
        status_counts = {}
        for result in results:
            status = result.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Performance statistics
        execution_times = [r.total_execution_time for r in results if r.total_execution_time > 0]
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0
        
        # Calculate aggregate metrics
        aggregate_metrics = {
            'patch_success_rate': patch_success / total_instances,
            'build_success_rate': build_success / total_instances,
            'test_execution_rate': test_execution / total_instances,
            'resolution_rate': resolved_instances / total_instances,
            'overall_test_pass_rate': total_passed / total_tests if total_tests > 0 else 0,
            'avg_execution_time': avg_execution_time,
            'total_execution_time': sum(execution_times)
        }
        
        report = {
            'summary': {
                'total_instances': total_instances,
                'patch_success': patch_success,
                'build_success': build_success,
                'test_execution': test_execution,
                'resolved_instances': resolved_instances,
                'total_tests': total_tests,
                'total_passed': total_passed,
                'total_failed': total_failed,
                'total_errors': total_errors
            },
            'rates': aggregate_metrics,
            'status_distribution': status_counts,
            'performance': {
                'avg_execution_time': avg_execution_time,
                'min_execution_time': min(execution_times) if execution_times else 0,
                'max_execution_time': max(execution_times) if execution_times else 0,
                'total_execution_time': sum(execution_times)
            },
            'detailed_results': [result.to_dict() for result in results]
        }
        
        return report
    
    def save_report(self, report: Dict[str, Any], output_path: Path, format: str = 'json'):
        """Save report to file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() == 'json':
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        self.logger.info(f"Report saved to {output_path}")


class MobileBenchValidator:
    """Validates mobile-bench evaluation results"""
    
    @staticmethod
    def validate_result(result: EvaluationResult) -> Tuple[bool, List[str]]:
        """Validate evaluation result"""
        errors = []
        
        # Check required fields
        if not result.instance_id:
            errors.append("instance_id is required")
        
        # Check status consistency
        if result.status == EvaluationStatus.TEST_SUCCESS and result.failed_tests > 0:
            errors.append("Status is TEST_SUCCESS but there are failed tests")
        
        if result.status == EvaluationStatus.BUILD_SUCCESS and not result.build_successful:
            errors.append("Status indicates build success but build_successful is False")
        
        # Check test consistency
        calculated_total = result.passed_tests + result.failed_tests + result.error_tests + result.skipped_tests
        if calculated_total != result.total_tests:
            errors.append(f"Test count mismatch: calculated {calculated_total}, reported {result.total_tests}")
        
        # Check time consistency
        if result.total_execution_time < 0:
            errors.append("Total execution time cannot be negative")
        
        if (result.patch_time + result.build_time + result.test_time) > result.total_execution_time * 1.1:
            errors.append("Sum of phase times exceeds total execution time")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_test_suite(suite: TestSuite) -> Tuple[bool, List[str]]:
        """Validate test suite"""
        errors = []
        
        if not suite.name:
            errors.append("Test suite name is required")
        
        calculated_total = len(suite.tests)
        if calculated_total != suite.total_tests:
            errors.append(f"Test count mismatch in suite {suite.name}")
        
        for test in suite.tests:
            test_valid, test_errors = MobileBenchValidator.validate_test_case(test)
            if not test_valid:
                errors.extend([f"Test {test.name}: {error}" for error in test_errors])
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_test_case(test: TestCase) -> Tuple[bool, List[str]]:
        """Validate individual test case"""
        errors = []
        
        if not test.name:
            errors.append("Test name is required")
        
        if test.execution_time < 0:
            errors.append("Execution time cannot be negative")
        
        if test.status in [TestStatus.FAILED, TestStatus.ERROR] and not test.error_message:
            errors.append("Failed/error tests should have error message")
        
        return len(errors) == 0, errors