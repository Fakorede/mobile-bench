#!/usr/bin/env python3

"""
Mobile-Bench Utilities
Supporting utilities for the Mobile-Bench evaluation harness.
"""

import json
import logging
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import docker
import requests
from dataclasses import dataclass


@dataclass
class AndroidProjectInfo:
    """Information about an Android project structure"""
    has_gradlew: bool = False
    has_build_gradle: bool = False
    has_kotlin: bool = False
    gradle_version: Optional[str] = None
    min_sdk: Optional[int] = None
    target_sdk: Optional[int] = None
    compile_sdk: Optional[int] = None
    build_tools_version: Optional[str] = None
    dependencies: List[str] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class AndroidProjectAnalyzer:
    """Analyzes Android project structure and configuration"""
    
    @staticmethod
    def analyze_project(container, repo_path: str) -> AndroidProjectInfo:
        """Analyze Android project structure and extract configuration"""
        info = AndroidProjectInfo()
        
        # Check for gradlew
        result = container.exec_run(f"test -f {repo_path}/gradlew")
        info.has_gradlew = result.exit_code == 0
        
        # Check for build.gradle files
        result = container.exec_run(f"find {repo_path} -name 'build.gradle*' | head -1")
        info.has_build_gradle = result.exit_code == 0 and result.output.decode('utf-8').strip()
        
        # Check for Kotlin files
        result = container.exec_run(f"find {repo_path} -name '*.kt' -o -name '*.kts' | head -1")
        info.has_kotlin = result.exit_code == 0 and result.output.decode('utf-8').strip()
        
        # Extract Gradle version
        info.gradle_version = AndroidProjectAnalyzer._extract_gradle_version(container, repo_path)
        
        # Extract Android configuration
        android_config = AndroidProjectAnalyzer._extract_android_config(container, repo_path)
        info.min_sdk = android_config.get('minSdk')
        info.target_sdk = android_config.get('targetSdk')
        info.compile_sdk = android_config.get('compileSdk')
        info.build_tools_version = android_config.get('buildToolsVersion')
        
        # Extract dependencies
        info.dependencies = AndroidProjectAnalyzer._extract_dependencies(container, repo_path)
        
        return info
    
    @staticmethod
    def _extract_gradle_version(container, repo_path: str) -> Optional[str]:
        """Extract Gradle version from wrapper properties"""
        try:
            result = container.exec_run(
                f"cat {repo_path}/gradle/wrapper/gradle-wrapper.properties",
                workdir=repo_path
            )
            if result.exit_code == 0:
                content = result.output.decode('utf-8')
                match = re.search(r'gradle-([0-9]+\.[0-9]+(?:\.[0-9]+)?)-', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None
    
    @staticmethod
    def _extract_android_config(container, repo_path: str) -> Dict[str, Any]:
        """Extract Android configuration from build.gradle files"""
        config = {}
        
        # Look for app/build.gradle first, then build.gradle
        build_files = ['app/build.gradle', 'build.gradle', 'app/build.gradle.kts', 'build.gradle.kts']
        
        for build_file in build_files:
            try:
                result = container.exec_run(f"cat {repo_path}/{build_file}")
                if result.exit_code == 0:
                    content = result.output.decode('utf-8')
                    
                    # Extract SDK versions
                    patterns = {
                        'minSdk': r'minSdk(?:Version)?\s*[=:]\s*(\d+)',
                        'targetSdk': r'targetSdk(?:Version)?\s*[=:]\s*(\d+)',
                        'compileSdk': r'compileSdk(?:Version)?\s*[=:]\s*(\d+)',
                        'buildToolsVersion': r'buildToolsVersion\s*[=:]\s*["\']([^"\']+)["\']'
                    }
                    
                    for key, pattern in patterns.items():
                        match = re.search(pattern, content)
                        if match:
                            value = match.group(1)
                            config[key] = int(value) if key != 'buildToolsVersion' else value
                    
                    break
            except Exception:
                continue
        
        return config
    
    @staticmethod
    def _extract_dependencies(container, repo_path: str) -> List[str]:
        """Extract dependencies from build.gradle files"""
        dependencies = []
        
        build_files = ['app/build.gradle', 'build.gradle', 'app/build.gradle.kts', 'build.gradle.kts']
        
        for build_file in build_files:
            try:
                result = container.exec_run(f"cat {repo_path}/{build_file}")
                if result.exit_code == 0:
                    content = result.output.decode('utf-8')
                    
                    # Extract dependencies
                    dep_pattern = r'(?:implementation|api|compile|testImplementation|androidTestImplementation)\s+["\']([^"\']+)["\']'
                    matches = re.findall(dep_pattern, content)
                    dependencies.extend(matches)
            except Exception:
                continue
        
        return list(set(dependencies))  # Remove duplicates


class AndroidTestResultParser:
    """Parses Android test results from XML files"""
    
    @staticmethod
    def parse_test_results(container, repo_path: str) -> Dict[str, Any]:
        """Parse Android test results from XML files"""
        results = {
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'errors': 0,
            'skipped': 0,
            'execution_time': 0.0,
            'test_suites': [],
            'failed_tests': []
        }
        
        # Find test result XML files
        result = container.exec_run(
            f"find {repo_path} -name 'TEST-*.xml' -o -name '*test-results.xml' -o -name '*AndroidTest*.xml'",
            workdir=repo_path
        )
        
        if result.exit_code != 0:
            return results
        
        test_files = result.output.decode('utf-8').strip().split('\n')
        test_files = [f for f in test_files if f.strip()]
        
        for test_file in test_files:
            suite_results = AndroidTestResultParser._parse_test_file(container, test_file)
            if suite_results:
                results['test_suites'].append(suite_results)
                results['total_tests'] += suite_results.get('tests', 0)
                results['passed'] += suite_results.get('passed', 0)
                results['failed'] += suite_results.get('failures', 0)
                results['errors'] += suite_results.get('errors', 0)
                results['skipped'] += suite_results.get('skipped', 0)
                results['execution_time'] += suite_results.get('time', 0.0)
                results['failed_tests'].extend(suite_results.get('failed_tests', []))
        
        return results
    
    @staticmethod
    def _parse_test_file(container, test_file: str) -> Optional[Dict[str, Any]]:
        """Parse individual test result XML file"""
        try:
            result = container.exec_run(f"cat {test_file}")
            if result.exit_code != 0:
                return None
            
            xml_content = result.output.decode('utf-8')
            root = ET.fromstring(xml_content)
            
            # Extract testsuite information
            suite_info = {
                'name': root.get('name', ''),
                'tests': int(root.get('tests', 0)),
                'failures': int(root.get('failures', 0)),
                'errors': int(root.get('errors', 0)),
                'skipped': int(root.get('skipped', 0)),
                'time': float(root.get('time', 0.0)),
                'passed': 0,
                'failed_tests': []
            }
            
            # Calculate passed tests
            suite_info['passed'] = suite_info['tests'] - suite_info['failures'] - suite_info['errors'] - suite_info['skipped']
            
            # Extract failed test cases
            for testcase in root.findall('.//testcase'):
                test_name = testcase.get('name', '')
                class_name = testcase.get('classname', '')
                
                failure = testcase.find('failure')
                error = testcase.find('error')
                
                if failure is not None or error is not None:
                    failure_info = {
                        'test_name': test_name,
                        'class_name': class_name,
                        'type': 'failure' if failure is not None else 'error',
                        'message': ''
                    }
                    
                    if failure is not None:
                        failure_info['message'] = failure.get('message', failure.text or '')
                    elif error is not None:
                        failure_info['message'] = error.get('message', error.text or '')
                    
                    suite_info['failed_tests'].append(failure_info)
            
            return suite_info
            
        except Exception as e:
            logging.warning(f"Failed to parse test file {test_file}: {e}")
            return None


class PatchValidator:
    """Validates and preprocesses patches for Android projects"""
    
    @staticmethod
    def validate_patch(patch: str) -> Tuple[bool, str]:
        """Validate patch format and content"""
        if not patch or not patch.strip():
            return False, "Empty patch"
        
        # Check for basic patch format
        if not ('diff --git' in patch or '--- a/' in patch or '+++ b/' in patch):
            return False, "Invalid patch format - missing patch headers"
        
        # Check for potentially problematic patterns
        problematic_patterns = [
            r'rm -rf /',  # Dangerous file operations
            r'sudo ',     # Sudo commands
            r'chmod 777', # Overly permissive permissions
        ]
        
        for pattern in problematic_patterns:
            if re.search(pattern, patch, re.IGNORECASE):
                return False, f"Patch contains potentially dangerous pattern: {pattern}"
        
        return True, "Valid patch"
    
    @staticmethod
    def preprocess_patch(patch: str) -> str:
        """Preprocess patch to handle common issues"""
        if not patch:
            return patch
        
        # Normalize line endings
        patch = patch.replace('\r\n', '\n').replace('\r', '\n')
        
        # Remove trailing whitespace
        lines = patch.split('\n')
        lines = [line.rstrip() for line in lines]
        patch = '\n'.join(lines)
        
        # Ensure patch ends with newline
        if not patch.endswith('\n'):
            patch += '\n'
        
        return patch


class ContainerManager:
    """Manages Docker containers for testing"""
    
    def __init__(self, docker_client: docker.DockerClient):
        self.client = docker_client
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def create_test_container(self, instance_id: str, image: str = "mingc/android-build-box:latest") -> docker.models.containers.Container:
        """Create a new test container"""
        container_name = f"mobile_bench_{instance_id}_{hash(instance_id) % 10000}"
        
        try:
            # Remove existing container with same name
            try:
                existing = self.client.containers.get(container_name)
                existing.stop()
                existing.remove()
            except docker.errors.NotFound:
                pass
            
            container = self.client.containers.create(
                image=image,
                name=container_name,
                detach=True,
                tty=True,
                stdin_open=True,
                network_mode="host",
                dns=["8.8.8.8", "8.8.4.4"],
                environment={
                    "ANDROID_SDK_ROOT": "/opt/android-sdk",
                    "ANDROID_HOME": "/opt/android-sdk",
                    "GRADLE_OPTS": "-Xmx4g -Dorg.gradle.daemon=false",
                    "JAVA_OPTS": "-Xmx2g"
                },
                working_dir="/workspace",
                volumes={
                    "/tmp": {"bind": "/tmp", "mode": "rw"}
                }
            )
            
            return container
            
        except Exception as e:
            self.logger.error(f"Failed to create container {container_name}: {e}")
            raise
    
    def cleanup_container(self, container: docker.models.containers.Container):
        """Clean up container and associated resources"""
        try:
            container.stop(timeout=10)
        except Exception as e:
            self.logger.warning(f"Failed to stop container {container.name}: {e}")
        
        try:
            container.remove(force=True)
        except Exception as e:
            self.logger.warning(f"Failed to remove container {container.name}: {e}")
    
    def execute_with_timeout(self, 
                           container: docker.models.containers.Container,
                           command: str,
                           timeout: int = 300,
                           workdir: Optional[str] = None) -> Tuple[int, str]:
        """Execute command in container with timeout"""
        try:
            result = container.exec_run(
                command,
                workdir=workdir,
                timeout=timeout,
                stream=False
            )
            return result.exit_code, result.output.decode('utf-8', errors='replace')
        except Exception as e:
            return -1, str(e)


class ReportGenerator:
    """Generates detailed reports for evaluation results"""
    
    @staticmethod
    def generate_html_report(report_data: Dict[str, Any], output_path: str):
        """Generate HTML report from evaluation data"""
        html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Mobile-Bench Evaluation Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background: #f0f0f0; padding: 20px; border-radius: 5px; }
        .summary { display: flex; justify-content: space-between; margin: 20px 0; }
        .metric { text-align: center; padding: 10px; background: #e8f4f8; border-radius: 5px; }
        .metric h3 { margin: 0; color: #2c3e50; }
        .metric .value { font-size: 2em; font-weight: bold; color: #3498db; }
        .results-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .results-table th, .results-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .results-table th { background-color: #f2f2f2; }
        .status-success { color: #27ae60; font-weight: bold; }
        .status-failure { color: #e74c3c; font-weight: bold; }
        .status-error { color: #f39c12; font-weight: bold; }
        .collapsible { cursor: pointer; padding: 10px; background: #f1f1f1; border: none; width: 100%; text-align: left; }
        .collapsible:hover { background: #ddd; }
        .content { padding: 0 18px; display: none; overflow: hidden; background: #f9f9f9; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Mobile-Bench Evaluation Report</h1>
        <p><strong>Run ID:</strong> {run_id}</p>
        <p><strong>Timestamp:</strong> {timestamp}</p>
    </div>
    
    <div class="summary">
        <div class="metric">
            <h3>Total Instances</h3>
            <div class="value">{total_instances}</div>
        </div>
        <div class="metric">
            <h3>Patch Success Rate</h3>
            <div class="value">{patch_success_rate:.1%}</div>
        </div>
        <div class="metric">
            <h3>Build Success Rate</h3>
            <div class="value">{build_success_rate:.1%}</div>
        </div>
        <div class="metric">
            <h3>Test Success Rate</h3>
            <div class="value">{test_success_rate:.1%}</div>
        </div>
    </div>
    
    <h2>Detailed Results</h2>
    <table class="results-table">
        <thead>
            <tr>
                <th>Instance ID</th>
                <th>Status</th>
                <th>Patch Applied</th>
                <th>Build Success</th>
                <th>Tests Run</th>
                <th>Tests Passed</th>
                <th>Tests Failed</th>
                <th>Execution Time</th>
            </tr>
        </thead>
        <tbody>
            {results_rows}
        </tbody>
    </table>
    
    <script>
        var coll = document.getElementsByClassName("collapsible");
        for (var i = 0; i < coll.length; i++) {
            coll[i].addEventListener("click", function() {
                this.classList.toggle("active");
                var content = this.nextElementSibling;
                if (content.style.display === "block") {
                    content.style.display = "none";
                } else {
                    content.style.display = "block";
                }
            });
        }
    </script>
</body>
</html>
"""
        
        # Generate results rows
        results_rows = ""
        for result in report_data['detailed_results']:
            status_class = {
                'TEST_SUCCESS': 'status-success',
                'TEST_FAIL': 'status-failure',
                'PATCH_APPLY_FAIL': 'status-error',
                'BUILD_FAIL': 'status-error',
                'CONTAINER_ERROR': 'status-error',
                'TEST_TIMEOUT': 'status-error'
            }.get(result['status'], 'status-error')
            
            results_rows += f"""
            <tr>
                <td>{result['instance_id']}</td>
                <td class="{status_class}">{result['status']}</td>
                <td>{'✓' if result['patch_applied'] else '✗'}</td>
                <td>{'✓' if result['build_successful'] else '✗'}</td>
                <td>{result['tests_run']}</td>
                <td>{result['tests_passed']}</td>
                <td>{result['tests_failed']}</td>
                <td>{result['execution_time']:.1f}s</td>
            </tr>
            """
        
        # Format the HTML
        html_content = html_template.format(
            run_id=report_data['run_id'],
            timestamp=report_data['timestamp'],
            total_instances=report_data['summary']['total_instances'],
            patch_success_rate=report_data['summary']['patch_success_rate'],
            build_success_rate=report_data['summary']['build_success_rate'],
            test_success_rate=report_data['summary']['test_success_rate'],
            results_rows=results_rows
        )
        
        # Save HTML report
        with open(output_path, 'w') as f:
            f.write(html_content)
    
    @staticmethod
    def generate_csv_report(report_data: Dict[str, Any], output_path: str):
        """Generate CSV report from evaluation data"""
        import csv
        
        with open(output_path, 'w', newline='') as csvfile:
            fieldnames = [
                'instance_id', 'status', 'patch_applied', 'build_successful',
                'tests_run', 'tests_passed', 'tests_failed', 'tests_skipped',
                'execution_time', 'error_message'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in report_data['detailed_results']:
                writer.writerow({
                    'instance_id': result['instance_id'],
                    'status': result['status'],
                    'patch_applied': result['patch_applied'],
                    'build_successful': result['build_successful'],
                    'tests_run': result['tests_run'],
                    'tests_passed': result['tests_passed'],
                    'tests_failed': result['tests_failed'],
                    'tests_skipped': result['tests_skipped'],
                    'execution_time': result['execution_time'],
                    'error_message': result['error_message']
                })


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            *([logging.FileHandler(log_file)] if log_file else [])
        ]
    )


def validate_environment():
    """Validate that the environment is properly set up"""
    # Check Docker availability
    try:
        docker.from_env().ping()
    except Exception as e:
        raise RuntimeError(f"Docker is not available: {e}")
    
    # Check if Android build box image is available
    try:
        client = docker.from_env()
        client.images.get("mingc/android-build-box:latest")
    except docker.errors.ImageNotFound:
        logging.warning("Android build box image not found, will attempt to pull")
    except Exception as e:
        raise RuntimeError(f"Failed to check Docker images: {e}")


def calculate_metrics(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate additional metrics from results"""
    if not results:
        return {}
    
    total = len(results)
    
    # Success rates
    patch_success = sum(1 for r in results if r['patch_applied'])
    build_success = sum(1 for r in results if r['build_successful'])
    test_success = sum(1 for r in results if r['status'] == 'TEST_SUCCESS')
    
    # Test metrics
    total_tests = sum(r['tests_run'] for r in results)
    total_passed = sum(r['tests_passed'] for r in results)
    total_failed = sum(r['tests_failed'] for r in results)
    
    # Execution time metrics
    execution_times = [r['execution_time'] for r in results if r['execution_time'] > 0]
    avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0
    
    return {
        'patch_success_rate': patch_success / total,
        'build_success_rate': build_success / total,
        'test_success_rate': test_success / total,
        'overall_test_pass_rate': total_passed / total_tests if total_tests > 0 else 0,
        'avg_execution_time': avg_execution_time,
        'total_execution_time': sum(execution_times)
    }