#!/usr/bin/env python3
"""
Main Android-bench validation engine using subprocess approach.
Compatible with mingc/android-build-box image.
"""

import json
import logging
import os
import sys
import traceback
import time
import tempfile
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

# Import our subprocess-compatible modules
from config import AndroidConfig
from containers import AndroidContainers
from repository import AndroidRepository
from testing import AndroidTesting, TestExecutionResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('android_validation.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Complete validation result for a single instance."""
    instance_id: str
    success: bool
    error_message: str = ""
    
    # Setup phase
    repo_cloned: bool = False
    config_parsed: bool = False
    container_created: bool = False
    base_commit_checked_out: bool = False
    
    # Test execution phase
    test_patch_applied: bool = False
    pre_test_execution: Optional[TestExecutionResult] = None
    solution_patch_applied: bool = False
    post_test_execution: Optional[TestExecutionResult] = None
    
    # Test transition Analysis
    fail_to_pass_tests: list = None
    pass_to_pass_tests: list = None
    pass_to_fail_tests: list = None
    fail_to_fail_tests: list = None

    # Test transition counts
    fail_to_pass_count: int = 0     # Count of tests that were fixed
    pass_to_pass_count: int = 0     # Count of tests that remained passing
    pass_to_fail_count: int = 0     # Count of tests that broke
    fail_to_fail_count: int = 0     # Count of tests that remained failing
    
    # Metrics
    total_duration: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        
        # Handle TestExecutionResult objects
        if self.pre_test_execution:
            result['pre_test_execution'] = {
                'total_tests': self.pre_test_execution.total_tests,
                'passed': self.pre_test_execution.passed,
                'failed': self.pre_test_execution.failed,
                'skipped': self.pre_test_execution.skipped,
                'errors': self.pre_test_execution.errors,
                'duration': self.pre_test_execution.duration,
                'exit_code': self.pre_test_execution.exit_code,
                'build_successful': self.pre_test_execution.build_successful
            }
        
        if self.post_test_execution:
            result['post_test_execution'] = {
                'total_tests': self.post_test_execution.total_tests,
                'passed': self.post_test_execution.passed,
                'failed': self.post_test_execution.failed,
                'skipped': self.post_test_execution.skipped,
                'errors': self.post_test_execution.errors,
                'duration': self.post_test_execution.duration,
                'exit_code': self.post_test_execution.exit_code,
                'build_successful': self.post_test_execution.build_successful
            }
        
        return result


class AndroidBenchValidator:
    """Main validation engine for Android-bench dataset using subprocess approach."""
    
    def __init__(self, output_dir: str = "android_validation_results", docker_context: str = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize components with subprocess approach
        self.containers = AndroidContainers(docker_context=docker_context)
        self.repository = AndroidRepository(self.containers)
        
        # Will be initialized per instance
        self.config_parser = None
        self.testing = None
    
    def validate_dataset(self, dataset_file: str, instance_ids: list = None, 
                        max_instances: int = None) -> Dict[str, ValidationResult]:
        """Validate entire dataset or specific instances."""
        results = {}
        
        try:
            # Load dataset
            instances = self._load_dataset(dataset_file)
            
            # Filter instances if specified
            if instance_ids:
                instances = [inst for inst in instances if inst['instance_id'] in instance_ids]
            
            if max_instances:
                instances = instances[:max_instances]
            
            logger.info(f"Validating {len(instances)} instances")
            
            for i, instance in enumerate(instances):
                instance_id = instance['instance_id']
                logger.info(f"[{i+1}/{len(instances)}] Validating instance: {instance_id}")
                
                try:
                    result = self.validate_instance(instance)
                    results[instance_id] = result
                    
                    # Save intermediate results
                    self._save_instance_result(result)
                    
                    # Log progress
                    status = "✓" if result.success else "✗"
                    logger.info(f"{status} {instance_id}: {result.error_message if not result.success else 'Success'}")
                    
                except Exception as e:
                    logger.error(f"Failed to validate {instance_id}: {e}")
                    logger.error(traceback.format_exc())
                    
                    results[instance_id] = ValidationResult(
                        instance_id=instance_id,
                        success=False,
                        error_message=str(e)
                    )
                
                finally:
                    # Cleanup container for this instance
                    self.containers.cleanup_container(instance_id)
            
            # Save final results
            self._save_final_results(results)
            
        except Exception as e:
            logger.error(f"Error during dataset validation: {e}")
            logger.error(traceback.format_exc())
        
        finally:
            # Cleanup all containers
            self.containers.cleanup_all()
        
        return results
    
    def validate_instance(self, instance: Dict[str, Any]) -> ValidationResult:
        """Validate a single task instance following the specified workflow."""
        instance_id = instance['instance_id']
        result = ValidationResult(instance_id=instance_id, success=False)
        
        start_time = time.time()
        repo_path = None
        
        try:
            logger.info(f"Starting validation for {instance_id}")
            
            # Step 1: Clone repository
            repo_path = self._clone_repository(instance)
            if not repo_path:
                result.error_message = "Failed to clone repository"
                return result
            result.repo_cloned = True
            
            # Step 2: Parse build configuration
            self.config_parser = AndroidConfig(repo_path)
            build_config = self.config_parser.parse_build_config()
            result.config_parsed = True
            
            logger.info(f"Build configuration: {build_config}")
            
            # Step 3: Create and start container
            if not self.containers.create_container(instance_id, build_config, repo_path):
                result.error_message = "Failed to create container"
                return result
            result.container_created = True

            if not self.containers.start_container(instance_id):
                result.error_message = "Failed to start container"
                return result

            # Install SDK components
            self.containers.install_sdk_components(instance_id, build_config)
            
            # Initialize testing module with config
            self.testing = AndroidTesting(self.containers, self.config_parser)
            
            # Step 4: Checkout base commit and reset to clean state
            if not self.repository.checkout_base_commit(instance_id, instance['base_commit']):
                result.error_message = "Failed to checkout base commit"
                return result
            result.base_commit_checked_out = True
            
            # Step 5: Apply test patch
            test_patch_success, test_patch_output = self.repository.apply_patch(
                instance_id, instance['test_patch'], "test_patch"
            )
            if not test_patch_success:
                result.error_message = f"Failed to apply test patch: {test_patch_output}"
                return result
            result.test_patch_applied = True
            
            # Step 6: Run tests to generate logpre (baseline)
            logger.info(f"Running pre-solution tests for {instance_id}")
            pre_test_results = self.testing.run_tests_from_patch(
                instance_id, instance['test_patch'], build_config
            )
            result.pre_test_execution = pre_test_results
            
            # Save pre-test logs
            self._save_test_logs(instance_id, "pre", pre_test_results.raw_output)

            # Step 6.5: Reset to clean state before applying solution patch
            logger.info(f"Resetting to clean state before applying solution patch for {instance_id}")
            if not self.repository.reset_to_clean_state(instance_id):
                logger.warning(f"Failed to reset to clean state for {instance_id}, continuing anyway")
            
            # Re-apply test patch after reset (since reset removes all changes)
            test_patch_success, test_patch_output = self.repository.apply_patch(
                instance_id, instance['test_patch'], "test_patch_reapply"
            )
            if not test_patch_success:
                result.error_message = f"Failed to re-apply test patch after reset: {test_patch_output}"
                return result
            
            # Step 7: Apply solution patch (now on clean state + test patch)
            solution_patch_success, solution_patch_output = self.repository.apply_patch(
                instance_id, instance['patch'], "solution_patch"
            )
            if not solution_patch_success:
                result.error_message = f"Failed to apply solution patch: {solution_patch_output}"
                return result
            result.solution_patch_applied = True
            
            # Step 8: Run tests to generate logpost (after solution)
            logger.info(f"Running post-solution tests for {instance_id}")
            post_test_results = self.testing.run_tests_from_patch(
                instance_id, instance['test_patch'], build_config
            )
            result.post_test_execution = post_test_results
            
            # Save post-test logs
            self._save_test_logs(instance_id, "post", post_test_results.raw_output)
            
            # Step 9: Analyze test results
            test_comparison = self.testing.compare_test_results(pre_test_results, post_test_results)

            # Set the test lists
            result.fail_to_pass_tests = test_comparison['fail_to_pass']
            result.pass_to_pass_tests = test_comparison['pass_to_pass']
            result.pass_to_fail_tests = test_comparison['pass_to_fail']
            result.fail_to_fail_tests = test_comparison['fail_to_fail']
            
            # Set the counts
            result.fail_to_pass_count = len(test_comparison['fail_to_pass'])
            result.pass_to_pass_count = len(test_comparison['pass_to_pass'])
            result.pass_to_fail_count = len(test_comparison['pass_to_fail'])
            result.fail_to_fail_count = len(test_comparison['fail_to_fail'])
            
            # Mark as successful
            result.success = True
            result.total_duration = time.time() - start_time
            
            logger.info(f"Validation completed for {instance_id}")
            logger.info(f"  Fail-to-pass: {result.fail_to_pass_count}")
            logger.info(f"  Pass-to-pass: {result.pass_to_pass_count}")
            logger.info(f"  Pass-to-fail: {result.pass_to_fail_count}")
            logger.info(f"  Fail-to-fail: {result.fail_to_fail_count}")
            
        except Exception as e:
            result.error_message = str(e)
            result.total_duration = time.time() - start_time
            logger.error(f"Error validating {instance_id}: {e}")
            raise
        
        finally:
            # Cleanup temporary repository
            if repo_path and os.path.exists(repo_path):
                try:
                    self._cleanup_repository(repo_path)
                except Exception as e:
                    logger.warning(f"Failed to cleanup repo path {repo_path}: {e}")
        
        return result
    
    def _load_dataset(self, dataset_file: str) -> list:
        """Load dataset from JSON or JSONL file."""
        instances = []
        
        with open(dataset_file, 'r', encoding='utf-8') as f:
            if dataset_file.endswith('.jsonl'):
                for line in f:
                    line = line.strip()
                    if line:
                        instances.append(json.loads(line))
            else:
                instances = json.load(f)
        
        logger.info(f"Loaded {len(instances)} instances from {dataset_file}")
        return instances
    
    def _clone_repository(self, instance: Dict[str, Any]) -> Optional[str]:
        """Clone repository to temporary directory with proper permissions."""
        repo = instance['repo']
        instance_id = instance['instance_id']
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix=f"android_bench_{instance_id}_")
        
        try:
            # Clone repository with proper configuration
            clone_url = f"https://github.com/{repo}.git"
            
            logger.info(f"Cloning {repo} to {temp_dir}")
            
            # Setup git configuration
            git_config_commands = [
                ["git", "config", "--global", "--add", "safe.directory", "*"],
                ["git", "config", "--global", "user.email", "validator@android-bench.local"],
                ["git", "config", "--global", "user.name", "Android Bench Validator"]
            ]
            
            for cmd in git_config_commands:
                try:
                    subprocess.run(cmd, check=False, timeout=10)
                except Exception:
                    pass  # Ignore git config failures
            
            # Clone repository
            clone_cmd = ["git", "clone", "--recursive", "--depth", "1000", clone_url, temp_dir]
            result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode != 0:
                logger.error(f"Failed to clone repository: {result.stderr}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            
            # Set proper permissions
            os.chmod(temp_dir, 0o755)
            for root, dirs, files in os.walk(temp_dir):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o755)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o644)
            
            logger.info(f"Successfully cloned {repo}")
            return temp_dir
            
        except subprocess.TimeoutExpired:
            logger.error(f"Repository cloning timed out for {repo}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        except Exception as e:
            logger.error(f"Error cloning repository {repo}: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
    
    def _cleanup_repository(self, repo_path: str):
        """Clean up repository with Docker assistance for permission issues."""
        try:
            # Use Docker to fix permissions first
            docker_cmd = self.containers._get_docker_cmd_prefix() + [
                "run", "--rm",
                "-v", f"{repo_path}:/cleanup",
                self.containers.BASE_IMAGE,
                "bash", "-c", """
                cd /cleanup &&
                echo "Fixing permissions for cleanup..." &&
                find . -type f -exec chmod 666 {} + 2>/dev/null || true &&
                find . -type d -exec chmod 777 {} + 2>/dev/null || true &&
                echo "Permissions fixed"
                """
            ]
            
            result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.debug("Docker permission fix completed")
            else:
                logger.warning(f"Docker permission fix warning: {result.stderr}")
                
        except Exception as e:
            logger.warning(f"Docker permission fix failed: {e}")
        
        # Now try to remove the directory
        try:
            shutil.rmtree(repo_path)
            logger.debug(f"Successfully cleaned up repository: {repo_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup repository {repo_path}: {e}")
    
    def _save_final_results(self, results: Dict[str, ValidationResult]):
        """Save final summary results."""
        successful = [r for r in results.values() if r.success]
        failed = [r for r in results.values() if not r.success]
        
        # Calculate aggregate test statistics
        total_fail_to_pass = sum(r.fail_to_pass_count for r in successful)
        total_pass_to_pass = sum(r.pass_to_pass_count for r in successful)
        total_pass_to_fail = sum(r.pass_to_fail_count for r in successful)
        total_fail_to_fail = sum(r.fail_to_fail_count for r in successful)
        
        # Calculate average durations
        avg_duration = sum(r.total_duration for r in successful) / len(successful) if successful else 0
        
        summary = {
            'total_instances': len(results),
            'successful': len(successful),
            'failed': len(failed),
            'success_rate': len(successful) / len(results) * 100 if results else 0,
            
            # Enhanced test statistics
            'test_statistics': {
                'total_fail_to_pass': total_fail_to_pass,
                'total_pass_to_pass': total_pass_to_pass,
                'total_pass_to_fail': total_pass_to_fail,
                'total_fail_to_fail': total_fail_to_fail,
                'avg_fail_to_pass_per_instance': total_fail_to_pass / len(successful) if successful else 0,
                'avg_pass_to_pass_per_instance': total_pass_to_pass / len(successful) if successful else 0,
                'avg_pass_to_fail_per_instance': total_pass_to_fail / len(successful) if successful else 0,
                'avg_fail_to_fail_per_instance': total_fail_to_fail / len(successful) if successful else 0,
            },
            
            'performance_metrics': {
                'avg_duration_seconds': avg_duration,
                'total_duration_hours': sum(r.total_duration for r in results.values()) / 3600,
            },
            
            'results': {k: v.to_dict() for k, v in results.items()}
        }
        
        # Save detailed summary
        summary_file = self.output_dir / "validation_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        # Save enhanced report
        report_lines = [
            "Android-Bench Validation Report (Subprocess Approach)",
            "=" * 50,
            f"Total Instances: {summary['total_instances']}",
            f"Successful: {summary['successful']}",
            f"Failed: {summary['failed']}",
            f"Success Rate: {summary['success_rate']:.1f}%",
            "",
            "Test Transition Statistics:",
            "-" * 30,
            f"Total Tests Fixed (Fail→Pass): {total_fail_to_pass}",
            f"Total Tests Maintained (Pass→Pass): {total_pass_to_pass}",
            f"Total Tests Broken (Pass→Fail): {total_pass_to_fail}",
            f"Total Tests Still Failing (Fail→Fail): {total_fail_to_fail}",
            "",
            f"Average per Instance:",
            f"  - Tests Fixed: {total_fail_to_pass / len(successful):.1f}" if successful else "  - Tests Fixed: 0",
            f"  - Tests Maintained: {total_pass_to_pass / len(successful):.1f}" if successful else "  - Tests Maintained: 0",
            f"  - Tests Broken: {total_pass_to_fail / len(successful):.1f}" if successful else "  - Tests Broken: 0",
            f"  - Tests Still Failing: {total_fail_to_fail / len(successful):.1f}" if successful else "  - Tests Still Failing: 0",
            "",
            "Performance Metrics:",
            "-" * 20,
            f"Average Duration: {avg_duration:.1f}s",
            f"Total Runtime: {sum(r.total_duration for r in results.values()) / 3600:.2f}h",
            "",
            "Failed Instances:",
            "-" * 17,
        ]
        
        for result in failed:
            report_lines.append(f"  - {result.instance_id}: {result.error_message}")
        
        report_file = self.output_dir / "validation_report.txt"
        with open(report_file, 'w') as f:
            f.write('\n'.join(report_lines))
        
        logger.info(f"Validation complete: {summary['successful']}/{summary['total_instances']} successful")
        logger.info(f"Total tests fixed: {total_fail_to_pass}, broken: {total_pass_to_fail}")
        logger.info(f"Results saved to: {self.output_dir}")

    def _save_instance_result(self, result: ValidationResult):
        """Save individual instance result."""
        instance_dir = self.output_dir / result.instance_id
        instance_dir.mkdir(exist_ok=True, parents=True)
        
        result_file = instance_dir / "validation_result.json"
        with open(result_file, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
    
    def _save_test_logs(self, instance_id: str, phase: str, logs: str):
        """Save test execution logs."""
        instance_dir = self.output_dir / instance_id
        instance_dir.mkdir(exist_ok=True, parents=True)
        
        log_file = instance_dir / f"test_logs_{phase}.txt"
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(logs)

def main():
    """Main entry point for the Android-bench validator (subprocess approach)."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Android-bench validation engine (subprocess approach)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate entire dataset
  python validator_subprocess.py dataset.jsonl
  
  # Validate specific instances
  python validator_subprocess.py dataset.jsonl --instance-ids "AntennaPod__AntennaPod-5644" "App2__App2-1234"
  
  # Validate first 5 instances
  python validator_subprocess.py dataset.jsonl --max-instances 5
  
  # Custom output directory
  python validator_subprocess.py dataset.jsonl --output-dir my_results
  
  # Debug logging
  python validator_subprocess.py dataset.jsonl --log-level DEBUG
  
  # Custom Docker context
  python validator_subprocess.py dataset.jsonl --docker-context my-context
        """
    )
    
    parser.add_argument("dataset_file", help="Path to dataset JSONL file")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to validate")
    parser.add_argument("--max-instances", type=int, help="Maximum number of instances to validate")
    parser.add_argument("--output-dir", default="android_validation_results", help="Output directory")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    parser.add_argument("--docker-context", help="Docker context to use")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not Path(args.dataset_file).exists():
        print(f"Error: Dataset file not found: {args.dataset_file}")
        sys.exit(1)
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    
    # Create validator
    validator = AndroidBenchValidator(args.output_dir, args.docker_context)
    
    try:
        # Run validation
        results = validator.validate_dataset(
            args.dataset_file, 
            args.instance_ids, 
            args.max_instances
        )
        
        # Print summary
        successful = len([r for r in results.values() if r.success])
        total = len(results)
        success_rate = successful / total * 100 if total > 0 else 0
        
        print(f"\nValidation Summary (Subprocess Approach):")
        print(f"  Total: {total}")
        print(f"  Successful: {successful}")
        print(f"  Failed: {total - successful}")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Results saved to: {args.output_dir}")
        
        # Exit with appropriate code
        sys.exit(0 if successful > 0 else 1)
        
    except KeyboardInterrupt:
        print("\nValidation interrupted by user")
        validator.containers.cleanup_all()
        sys.exit(1)
    except Exception as e:
        print(f"Validation failed: {e}")
        validator.containers.cleanup_all()
        sys.exit(1)


if __name__ == "__main__":
    main()