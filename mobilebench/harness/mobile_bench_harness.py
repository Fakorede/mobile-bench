#!/usr/bin/env python3

"""
Mobile-Bench Evaluation Harness
Comprehensive evaluation system for mobile (Android) patches using Docker containers.
Based on SWE-bench architecture with Android-specific adaptations.
"""

import argparse
import docker
import json
import logging
import os
import platform
import re
import subprocess
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import uuid

# Constants
DOCKER_IMAGE = "mingc/android-build-box:latest"
DEFAULT_TIMEOUT = 1800  # 30 minutes
LOG_DIR = Path("./mobile_bench_logs")
REPORT_DIR = Path("./mobile_bench_reports")

# Status constants
PATCH_APPLY_SUCCESS = "PATCH_APPLY_SUCCESS"
PATCH_APPLY_FAIL = "PATCH_APPLY_FAIL"
BUILD_SUCCESS = "BUILD_SUCCESS" 
BUILD_FAIL = "BUILD_FAIL"
TEST_SUCCESS = "TEST_SUCCESS"
TEST_FAIL = "TEST_FAIL"
TEST_TIMEOUT = "TEST_TIMEOUT"
CONTAINER_ERROR = "CONTAINER_ERROR"


@dataclass
class AndroidTestSpec:
    """Specification for an Android test instance"""
    instance_id: str
    repo_url: str
    base_commit: str
    patch: str
    test_commands: List[str]
    java_version: Optional[str] = None
    gradle_version: Optional[str] = None
    has_kotlin: bool = False
    timeout: int = DEFAULT_TIMEOUT


@dataclass
class TestResult:
    """Result of running a test instance"""
    instance_id: str
    status: str
    patch_applied: bool = False
    build_successful: bool = False
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    execution_time: float = 0.0
    error_message: str = ""
    detailed_results: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.detailed_results is None:
            self.detailed_results = {}


class AndroidVersionDetector:
    """Detects appropriate Java and Gradle versions for Android projects"""
    
    # Gradle to Java version mapping
    GRADLE_JAVA_MAPPING = {
        "8.0": "17", "8.1": "17", "8.2": "17", "8.3": "17", "8.4": "17", "8.5": "17",
        "7.6": "17", "7.5": "17", "7.4": "17", "7.3": "17", "7.2": "17", "7.1": "17", "7.0": "17",
        "6.9": "11", "6.8": "11", "6.7": "11", "6.6": "11", "6.5": "11", "6.4": "11", "6.3": "11", "6.2": "11", "6.1": "11", "6.0": "11",
        "5.6": "11", "5.5": "11", "5.4": "11", "5.3": "11", "5.2": "11", "5.1": "11", "5.0": "8",
        "4.10": "8", "4.9": "8", "4.8": "8", "4.7": "8", "4.6": "8", "4.5": "8", "4.4": "8", "4.3": "8", "4.2": "8", "4.1": "8", "4.0": "8"
    }
    
    @classmethod
    def detect_gradle_version(cls, container, repo_path: str) -> Optional[str]:
        """Detect Gradle version from wrapper properties or gradlew command"""
        try:
            # Try gradle wrapper properties first
            result = container.exec_run(
                f"cat {repo_path}/gradle/wrapper/gradle-wrapper.properties | grep distributionUrl",
                workdir=repo_path
            )
            if result.exit_code == 0:
                output = result.output.decode('utf-8')
                match = re.search(r'gradle-([0-9]+\.[0-9]+(?:\.[0-9]+)?)-', output)
                if match:
                    return match.group(1)
            
            # Try gradlew --version
            result = container.exec_run("./gradlew --version", workdir=repo_path)
            if result.exit_code == 0:
                output = result.output.decode('utf-8')
                match = re.search(r'Gradle ([0-9]+\.[0-9]+(?:\.[0-9]+)?)', output)
                if match:
                    return match.group(1)
                    
        except Exception as e:
            logging.warning(f"Failed to detect Gradle version: {e}")
            
        return None
    
    @classmethod
    def detect_kotlin_usage(cls, container, repo_path: str) -> bool:
        """Detect if project uses Kotlin"""
        try:
            result = container.exec_run(
                "find . -name '*.kt' -o -name '*.kts' | head -1",
                workdir=repo_path
            )
            return result.exit_code == 0 and result.output.decode('utf-8').strip()
        except Exception:
            return False
    
    @classmethod
    def determine_java_version(cls, gradle_version: Optional[str], has_kotlin: bool = False) -> str:
        """Determine appropriate Java version based on Gradle version and Kotlin usage"""
        if not gradle_version:
            return "17"  # Default for modern Android projects
            
        # Extract major.minor version
        version_parts = gradle_version.split('.')
        if len(version_parts) >= 2:
            major_minor = f"{version_parts[0]}.{version_parts[1]}"
            java_version = cls.GRADLE_JAVA_MAPPING.get(major_minor)
            if java_version:
                # Kotlin projects often need newer Java versions
                if has_kotlin and java_version == "8":
                    return "11"
                return java_version
        
        return "17"  # Default fallback


class AndroidTestRunner:
    """Handles running individual Android test instances"""
    
    def __init__(self, docker_client: docker.DockerClient, timeout: int = DEFAULT_TIMEOUT):
        self.client = docker_client
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def run_instance(self, test_spec: AndroidTestSpec) -> TestResult:
        """Run a single test instance"""
        start_time = time.time()
        result = TestResult(
            instance_id=test_spec.instance_id,
            status="RUNNING"
        )
        
        container = None
        repo_path = f"/tmp/{test_spec.instance_id}"
        
        try:
            # Create and start container
            container = self._create_container(test_spec.instance_id)
            container.start()
            
            # Clone repository
            self._clone_repository(container, test_spec.repo_url, repo_path, test_spec.base_commit)
            
            # Detect Android project configuration
            gradle_version = AndroidVersionDetector.detect_gradle_version(container, repo_path)
            has_kotlin = AndroidVersionDetector.detect_kotlin_usage(container, repo_path)
            java_version = AndroidVersionDetector.determine_java_version(gradle_version, has_kotlin)
            
            # Update test spec with detected versions
            test_spec.gradle_version = gradle_version
            test_spec.has_kotlin = has_kotlin
            test_spec.java_version = java_version
            
            self.logger.info(f"Instance {test_spec.instance_id}: Gradle {gradle_version}, Java {java_version}, Kotlin: {has_kotlin}")
            
            # Setup Java environment
            self._setup_java_environment(container, java_version)
            
            # Apply patch
            patch_success = self._apply_patch(container, repo_path, test_spec.patch)
            result.patch_applied = patch_success
            
            if not patch_success:
                result.status = PATCH_APPLY_FAIL
                return result
            
            # Build project
            build_success = self._build_project(container, repo_path)
            result.build_successful = build_success
            
            if not build_success:
                result.status = BUILD_FAIL
                return result
            
            # Run tests
            test_results = self._run_tests(container, repo_path, test_spec.test_commands)
            result.tests_run = test_results.get('total', 0)
            result.tests_passed = test_results.get('passed', 0)
            result.tests_failed = test_results.get('failed', 0)
            result.tests_skipped = test_results.get('skipped', 0)
            result.detailed_results = test_results.get('details', {})
            
            result.status = TEST_SUCCESS if result.tests_failed == 0 else TEST_FAIL
            
        except subprocess.TimeoutExpired:
            result.status = TEST_TIMEOUT
            result.error_message = f"Test execution timed out after {self.timeout} seconds"
        except Exception as e:
            result.status = CONTAINER_ERROR
            result.error_message = str(e)
            self.logger.error(f"Error running instance {test_spec.instance_id}: {e}")
            
        finally:
            result.execution_time = time.time() - start_time
            if container:
                try:
                    container.stop()
                    container.remove()
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup container: {e}")
                    
        return result
    
    def _create_container(self, instance_id: str) -> docker.models.containers.Container:
        """Create a new Docker container for testing"""
        container_name = f"mobile_bench_{instance_id}_{uuid.uuid4().hex[:8]}"
        
        return self.client.containers.create(
            image=DOCKER_IMAGE,
            name=container_name,
            detach=True,
            tty=True,
            network_mode="host",
            dns=["8.8.8.8", "8.8.4.4"],
            environment={
                "ANDROID_SDK_ROOT": "/opt/android-sdk",
                "GRADLE_OPTS": "-Xmx4g -Dorg.gradle.daemon=false"
            },
            working_dir="/project"
        )
    
    def _clone_repository(self, container, repo_url: str, repo_path: str, base_commit: str):
        """Clone and checkout the repository"""
        # Clone repository
        result = container.exec_run(f"git clone --recursive {repo_url} {repo_path}")
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to clone repository: {result.output.decode('utf-8')}")
        
        # Checkout base commit
        result = container.exec_run(f"git checkout {base_commit}", workdir=repo_path)
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to checkout commit {base_commit}: {result.output.decode('utf-8')}")
        
        # Update submodules
        container.exec_run("git submodule update --init --recursive", workdir=repo_path)
    
    def _setup_java_environment(self, container, java_version: str):
        """Setup Java environment using jenv if available"""
        # Try to set Java version with jenv
        result = container.exec_run("which jenv")
        if result.exit_code == 0:
            # Initialize jenv
            container.exec_run('eval "$(jenv init -)"')
            
            # Set Java version
            container.exec_run(f"jenv global {java_version}")
            # Try with .0 suffix if direct version fails
            container.exec_run(f"jenv global {java_version}.0")
    
    def _apply_patch(self, container, repo_path: str, patch: str) -> bool:
        """Apply the git patch"""
        if not patch or not patch.strip():
            return True  # Empty patch is considered successful
        
        # Write patch to temporary file
        patch_file = f"{repo_path}/temp_patch.patch"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.patch') as f:
            f.write(patch)
            temp_patch_path = f.name
        
        # Copy patch to container
        with open(temp_patch_path, 'rb') as f:
            container.put_archive(repo_path, f.read())
        
        # Try different patch application methods
        apply_commands = [
            "git apply --verbose",
            "git apply --verbose --reject",
            "patch --batch --fuzz=5 -p1 -i"
        ]
        
        for cmd in apply_commands:
            result = container.exec_run(f"{cmd} temp_patch.patch", workdir=repo_path)
            if result.exit_code == 0:
                # Clean up
                container.exec_run("rm temp_patch.patch", workdir=repo_path)
                os.unlink(temp_patch_path)
                return True
        
        # Clean up
        container.exec_run("rm temp_patch.patch", workdir=repo_path)
        os.unlink(temp_patch_path)
        return False
    
    def _build_project(self, container, repo_path: str) -> bool:
        """Build the Android project"""
        # Clean previous builds
        container.exec_run("rm -rf ~/.gradle/caches/", workdir=repo_path)
        
        # Make gradlew executable
        container.exec_run("chmod +x ./gradlew", workdir=repo_path)
        
        # Try to build the project
        build_commands = [
            "./gradlew build",
            "./gradlew assembleDebug",
            "gradle build"  # Fallback to system gradle
        ]
        
        for cmd in build_commands:
            result = container.exec_run(f"timeout {self.timeout} {cmd}", workdir=repo_path)
            if result.exit_code == 0:
                return True
        
        return False
    
    def _run_tests(self, container, repo_path: str, test_commands: List[str]) -> Dict[str, Any]:
        """Run tests and parse results"""
        if not test_commands:
            test_commands = ["./gradlew test", "gradle test"]
        
        results = {
            'total': 0,
            'passed': 0, 
            'failed': 0,
            'skipped': 0,
            'details': {}
        }
        
        for cmd in test_commands:
            result = container.exec_run(f"timeout {self.timeout} {cmd}", workdir=repo_path)
            # Continue even if tests fail - we want to parse the results
            
        # Parse test results using the Android test parser
        parser_result = container.exec_run(
            f"python3 -c \""
            "import xml.etree.ElementTree as ET; "
            "import glob; "
            "import json; "
            "files = glob.glob('**/TEST-*.xml', recursive=True); "
            "total = passed = failed = skipped = 0; "
            "details = {}; "
            "for f in files: "
            "  try: "
            "    tree = ET.parse(f); "
            "    root = tree.getroot(); "
            "    t = int(root.get('tests', 0)); "
            "    f_count = int(root.get('failures', 0)); "
            "    e_count = int(root.get('errors', 0)); "
            "    s_count = int(root.get('skipped', 0)); "
            "    total += t; "
            "    failed += f_count + e_count; "
            "    skipped += s_count; "
            "    passed += t - f_count - e_count - s_count; "
            "    details[f] = {'tests': t, 'failures': f_count, 'errors': e_count, 'skipped': s_count}; "
            "  except: pass; "
            "print(json.dumps({'total': total, 'passed': passed, 'failed': failed, 'skipped': skipped, 'details': details}))\"",
            workdir=repo_path
        )
        
        if parser_result.exit_code == 0:
            try:
                parsed_results = json.loads(parser_result.output.decode('utf-8'))
                results.update(parsed_results)
            except json.JSONDecodeError:
                pass
        
        return results


class MobileBenchHarness:
    """Main evaluation harness for Mobile-Bench"""
    
    def __init__(self, 
                 max_workers: int = 4,
                 timeout: int = DEFAULT_TIMEOUT,
                 force_rebuild: bool = False,
                 log_level: str = "INFO"):
        
        self.max_workers = max_workers
        self.timeout = timeout
        self.force_rebuild = force_rebuild
        
        # Setup logging
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Setup directories
        LOG_DIR.mkdir(exist_ok=True)
        REPORT_DIR.mkdir(exist_ok=True)
        
        # Initialize Docker client
        try:
            self.docker_client = docker.from_env()
            self._pull_docker_image()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Docker client: {e}")
    
    def _pull_docker_image(self):
        """Pull the Android build Docker image"""
        try:
            self.logger.info(f"Pulling Docker image: {DOCKER_IMAGE}")
            self.docker_client.images.pull(DOCKER_IMAGE)
            self.logger.info("Docker image pulled successfully")
        except Exception as e:
            self.logger.warning(f"Failed to pull Docker image: {e}")
    
    def load_dataset(self, dataset_path: str) -> List[Dict]:
        """Load dataset from JSON or JSONL file"""
        dataset_path = Path(dataset_path)
        
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
        
        if dataset_path.suffix == '.json':
            with open(dataset_path, 'r') as f:
                return json.load(f)
        elif dataset_path.suffix == '.jsonl':
            instances = []
            with open(dataset_path, 'r') as f:
                for line in f:
                    instances.append(json.loads(line.strip()))
            return instances
        else:
            raise ValueError("Dataset must be a .json or .jsonl file")
    
    def load_predictions(self, predictions_path: str) -> Dict[str, Dict]:
        """Load predictions from JSON or JSONL file"""
        predictions_path = Path(predictions_path)
        
        if not predictions_path.exists():
            raise FileNotFoundError(f"Predictions file not found: {predictions_path}")
        
        predictions = {}
        
        if predictions_path.suffix == '.json':
            with open(predictions_path, 'r') as f:
                pred_list = json.load(f)
                if isinstance(pred_list, dict):
                    predictions = pred_list
                else:
                    predictions = {pred['instance_id']: pred for pred in pred_list}
        elif predictions_path.suffix == '.jsonl':
            with open(predictions_path, 'r') as f:
                for line in f:
                    pred = json.loads(line.strip())
                    predictions[pred['instance_id']] = pred
        
        return predictions
    
    def create_test_specs(self, instances: List[Dict], predictions: Dict[str, Dict]) -> List[AndroidTestSpec]:
        """Create test specifications from instances and predictions"""
        test_specs = []
        
        for instance in instances:
            instance_id = instance['instance_id']
            
            if instance_id not in predictions:
                self.logger.warning(f"No prediction found for instance {instance_id}")
                continue
            
            prediction = predictions[instance_id]
            patch = prediction.get('patch', prediction.get('model_patch', ''))
            
            if not patch:
                self.logger.warning(f"Empty patch for instance {instance_id}")
                continue
            
            test_spec = AndroidTestSpec(
                instance_id=instance_id,
                repo_url=instance['repo'],
                base_commit=instance['base_commit'],
                patch=patch,
                test_commands=instance.get('test_commands', []),
                timeout=self.timeout
            )
            
            test_specs.append(test_spec)
        
        return test_specs
    
    def run_evaluation(self, 
                      dataset_path: str, 
                      predictions_path: str,
                      run_id: str,
                      instance_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the complete evaluation"""
        
        self.logger.info(f"Starting Mobile-Bench evaluation with run_id: {run_id}")
        
        # Load data
        instances = self.load_dataset(dataset_path)
        predictions = self.load_predictions(predictions_path)
        
        # Filter by instance IDs if provided
        if instance_ids:
            instances = [inst for inst in instances if inst['instance_id'] in instance_ids]
        
        # Create test specifications
        test_specs = self.create_test_specs(instances, predictions)
        
        if not test_specs:
            raise ValueError("No valid test specifications created")
        
        self.logger.info(f"Running {len(test_specs)} test instances with {self.max_workers} workers")
        
        # Run tests in parallel
        results = []
        test_runner = AndroidTestRunner(self.docker_client, self.timeout)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_spec = {
                executor.submit(test_runner.run_instance, spec): spec 
                for spec in test_specs
            }
            
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                try:
                    result = future.result()
                    results.append(result)
                    self.logger.info(f"Completed {spec.instance_id}: {result.status}")
                except Exception as e:
                    self.logger.error(f"Failed to run {spec.instance_id}: {e}")
                    error_result = TestResult(
                        instance_id=spec.instance_id,
                        status=CONTAINER_ERROR,
                        error_message=str(e)
                    )
                    results.append(error_result)
        
        # Generate reports
        report = self._generate_report(results, run_id, instances, predictions)
        
        self.logger.info(f"Evaluation completed. Report saved to {report['report_path']}")
        
        return report
    
    def _generate_report(self, 
                        results: List[TestResult], 
                        run_id: str,
                        instances: List[Dict],
                        predictions: Dict[str, Dict]) -> Dict[str, Any]:
        """Generate comprehensive evaluation report"""
        
        # Calculate statistics
        total_instances = len(results)
        successful_patches = sum(1 for r in results if r.patch_applied)
        successful_builds = sum(1 for r in results if r.build_successful)
        successful_tests = sum(1 for r in results if r.status == TEST_SUCCESS)
        
        total_tests_run = sum(r.tests_run for r in results)
        total_tests_passed = sum(r.tests_passed for r in results)
        total_tests_failed = sum(r.tests_failed for r in results)
        
        # Group results by status
        status_counts = {}
        for result in results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        
        # Detailed results
        detailed_results = []
        for result in results:
            detailed_results.append({
                'instance_id': result.instance_id,
                'status': result.status,
                'patch_applied': result.patch_applied,
                'build_successful': result.build_successful,
                'tests_run': result.tests_run,
                'tests_passed': result.tests_passed,
                'tests_failed': result.tests_failed,
                'tests_skipped': result.tests_skipped,
                'execution_time': result.execution_time,
                'error_message': result.error_message,
                'detailed_results': result.detailed_results
            })
        
        # Create final report
        report = {
            'run_id': run_id,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'summary': {
                'total_instances': total_instances,
                'successful_patches': successful_patches,
                'successful_builds': successful_builds, 
                'successful_tests': successful_tests,
                'patch_success_rate': successful_patches / total_instances if total_instances > 0 else 0,
                'build_success_rate': successful_builds / total_instances if total_instances > 0 else 0,
                'test_success_rate': successful_tests / total_instances if total_instances > 0 else 0,
                'total_tests_run': total_tests_run,
                'total_tests_passed': total_tests_passed,
                'total_tests_failed': total_tests_failed,
                'overall_test_pass_rate': total_tests_passed / total_tests_run if total_tests_run > 0 else 0
            },
            'status_breakdown': status_counts,
            'detailed_results': detailed_results
        }
        
        # Save report
        report_path = REPORT_DIR / f"{run_id}_evaluation_report.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        report['report_path'] = str(report_path)
        
        # Print summary
        self._print_summary(report)
        
        return report
    
    def _print_summary(self, report: Dict[str, Any]):
        """Print evaluation summary"""
        summary = report['summary']
        
        print("\n" + "="*80)
        print("MOBILE-BENCH EVALUATION SUMMARY")
        print("="*80)
        print(f"Run ID: {report['run_id']}")
        print(f"Timestamp: {report['timestamp']}")
        print("-"*80)
        print(f"Total Instances: {summary['total_instances']}")
        print(f"Successful Patches: {summary['successful_patches']} ({summary['patch_success_rate']:.1%})")
        print(f"Successful Builds: {summary['successful_builds']} ({summary['build_success_rate']:.1%})")
        print(f"Successful Tests: {summary['successful_tests']} ({summary['test_success_rate']:.1%})")
        print("-"*80)
        print(f"Total Tests Run: {summary['total_tests_run']}")
        print(f"Tests Passed: {summary['total_tests_passed']}")
        print(f"Tests Failed: {summary['total_tests_failed']}")
        print(f"Overall Test Pass Rate: {summary['overall_test_pass_rate']:.1%}")
        print("-"*80)
        print("Status Breakdown:")
        for status, count in report['status_breakdown'].items():
            print(f"  {status}: {count}")
        print("="*80)


def main():
    parser = argparse.ArgumentParser(description="Mobile-Bench Evaluation Harness")
    
    # Required arguments
    parser.add_argument("--dataset_path", required=True, help="Path to dataset JSON/JSONL file")
    parser.add_argument("--predictions_path", required=True, help="Path to predictions JSON/JSONL file")
    parser.add_argument("--run_id", required=True, help="Unique identifier for this evaluation run")
    
    # Optional arguments
    parser.add_argument("--instance_ids", nargs="+", help="Specific instance IDs to evaluate")
    parser.add_argument("--max_workers", type=int, default=4, help="Maximum number of parallel workers")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout per instance in seconds")
    parser.add_argument("--force_rebuild", action="store_true", help="Force rebuild of Docker images")
    parser.add_argument("--log_level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    
    args = parser.parse_args()
    
    try:
        harness = MobileBenchHarness(
            max_workers=args.max_workers,
            timeout=args.timeout,
            force_rebuild=args.force_rebuild,
            log_level=args.log_level
        )
        
        report = harness.run_evaluation(
            dataset_path=args.dataset_path,
            predictions_path=args.predictions_path,
            run_id=args.run_id,
            instance_ids=args.instance_ids
        )
        
        print(f"\nEvaluation completed successfully!")
        print(f"Report saved to: {report['report_path']}")
        
    except Exception as e:
        print(f"Evaluation failed: {e}")
        logging.error(f"Evaluation failed: {e}", exc_info=True)