#!/usr/bin/env python3
"""
Android-bench validation engine with proper test result tracking and tuple handling.
"""

import asyncio
import datetime
import aiohttp
import re
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
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field

# Import optimized modules
from config import AndroidConfig
from containers import AndroidContainersPersistent
from repository import AndroidRepository
from testing import AndroidTestingParallel, TestExecutionResult
from build_utils import run_build_step, BuildResult
from stub_generator_utils import generate_and_apply_stubs, StubGenerationResult
from patch_based_stub_integration import generate_and_apply_patches

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
    """Validation result with test transitions only."""
    instance_id: str
    success: bool
    error_message: str = ""
    
    # Setup phase
    repo_cloned: bool = False
    config_parsed: bool = False
    container_created: bool = False
    base_commit_checked_out: bool = False

    build_result: Optional['BuildResult'] = None
    retry_build_result: Optional['BuildResult'] = None
    stub_generation_result: Optional['StubGenerationResult'] = None
    
    # Test execution phase
    test_patch_applied: bool = False
    pre_test_execution: Optional['TestExecutionResult'] = None
    solution_patch_applied: bool = False
    post_test_execution: Optional['TestExecutionResult'] = None
    
    # Test transition analysis with individual test tracking
    fail_to_pass_tests: List[str] = field(default_factory=list)
    pass_to_pass_tests: List[str] = field(default_factory=list)
    pass_to_fail_tests: List[str] = field(default_factory=list)
    fail_to_fail_tests: List[str] = field(default_factory=list)
    
    # Test lists by execution phase
    pre_passed_tests: List[str] = field(default_factory=list)
    pre_failed_tests: List[str] = field(default_factory=list)
    post_passed_tests: List[str] = field(default_factory=list)
    post_failed_tests: List[str] = field(default_factory=list)

    # Skipped tests
    skipped_instrumented_tests: List[str] = field(default_factory=list)

    # Test transition counts
    fail_to_pass_count: int = 0
    pass_to_pass_count: int = 0
    pass_to_fail_count: int = 0
    fail_to_fail_count: int = 0
    
    # Metrics
    total_duration: float = 0.0

    def compute_test_transitions(self):
        """Compute test transitions from pre and post test execution results."""
        if not self.pre_test_execution or not self.post_test_execution:
            logger.warning(f"Missing test execution results for {self.instance_id}")
            return
        
        # Extract test results and create test status mappings
        pre_tests = {
            f"{t.class_name}.{t.test_name}": t.status 
            for t in self.pre_test_execution.test_results
        }
        post_tests = {
            f"{t.class_name}.{t.test_name}": t.status 
            for t in self.post_test_execution.test_results
        }
        
        # Find all tests that appear in either pre or post execution
        all_tests = set(pre_tests.keys()) | set(post_tests.keys())
        
        # Reset transition lists
        self.fail_to_pass_tests = []
        self.pass_to_pass_tests = []
        self.pass_to_fail_tests = []
        self.fail_to_fail_tests = []
        
        # Compute transitions for each test
        for test_name in all_tests:
            pre_status = pre_tests.get(test_name, 'NOT_FOUND')
            post_status = post_tests.get(test_name, 'NOT_FOUND')
            
            # Classify test transitions
            if pre_status in ['FAILED', 'ERROR'] and post_status == 'PASSED':
                self.fail_to_pass_tests.append(test_name)
            elif pre_status == 'PASSED' and post_status == 'PASSED':
                self.pass_to_pass_tests.append(test_name)
            elif pre_status == 'PASSED' and post_status in ['FAILED', 'ERROR']:
                self.pass_to_fail_tests.append(test_name)
            elif pre_status in ['FAILED', 'ERROR'] and post_status in ['FAILED', 'ERROR']:
                self.fail_to_fail_tests.append(test_name)
            # Note: We ignore tests that are NOT_FOUND in one phase as they may be 
            # new tests introduced by patches or environment-specific
        
        # Update counts
        self.fail_to_pass_count = len(self.fail_to_pass_tests)
        self.pass_to_pass_count = len(self.pass_to_pass_tests)
        self.pass_to_fail_count = len(self.pass_to_fail_tests)
        self.fail_to_fail_count = len(self.fail_to_fail_tests)
        
        # Extract passed/failed test lists for each phase
        self.pre_passed_tests = [
            f"{t.class_name}.{t.test_name}" 
            for t in self.pre_test_execution.test_results 
            if t.status == 'PASSED'
        ]
        self.pre_failed_tests = [
            f"{t.class_name}.{t.test_name}" 
            for t in self.pre_test_execution.test_results 
            if t.status in ['FAILED', 'ERROR']
        ]
        self.post_passed_tests = [
            f"{t.class_name}.{t.test_name}" 
            for t in self.post_test_execution.test_results 
            if t.status == 'PASSED'
        ]
        self.post_failed_tests = [
            f"{t.class_name}.{t.test_name}" 
            for t in self.post_test_execution.test_results 
            if t.status in ['FAILED', 'ERROR']
        ]
        
        logger.info(f"Test transitions for {self.instance_id}:")
        logger.info(f"  Fail→Pass: {self.fail_to_pass_count}")
        logger.info(f"  Pass→Pass: {self.pass_to_pass_count}")
        logger.info(f"  Pass→Fail: {self.pass_to_fail_count}")
        logger.info(f"  Fail→Fail: {self.fail_to_fail_count}")


class AndroidBenchValidator:
    """AndroidBenchValidator validation engine with proper test result tracking and cleanup."""

    def __init__(self, output_dir: str = "android_validation_results", 
                 docker_context: str = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize components
        self.containers = AndroidContainersPersistent(docker_context=docker_context)
        self.repository = AndroidRepository(self.containers)
        
        # Will be initialized per instance
        self.config_parser = None
        self.testing = None
    
    async def validate_dataset(self, dataset_file: str, instance_ids: list = None, 
                        exclude_instance_ids: list = None, max_instances: int = None) -> Dict[str, ValidationResult]:
        """Validate entire dataset with proper cleanup."""
        results = {}
        
        try:
            # Load dataset
            instances = self._load_dataset(dataset_file)
            
            # Filter instances if specified
            if instance_ids:
                # Support flexible matching: allow including by full ID or just the numeric suffix
                included_instances = []
                for inst in instances:
                    instance_id = inst['instance_id']
                    # Check if instance should be included
                    should_include = False
                    for include_id in instance_ids:
                        # Exact match
                        if instance_id == include_id:
                            should_include = True
                            break
                        # Check if the include_id is a suffix (e.g., "6044" matches "thunderbird__thunderbird-android-6044")
                        if instance_id.endswith(f"-{include_id}") or instance_id.endswith(f"_{include_id}"):
                            should_include = True
                            break
                    
                    if should_include:
                        included_instances.append(inst)
                
                instances = included_instances
                logger.info(f"After including {len(instance_ids)} instance IDs: {len(instances)} instances selected")
            
            if exclude_instance_ids:
                # Support flexible matching: allow excluding by full ID or just the numeric suffix
                excluded_instances = []
                for inst in instances:
                    instance_id = inst['instance_id']
                    # Check if instance should be excluded
                    should_exclude = False
                    for exclude_id in exclude_instance_ids:
                        # Exact match
                        if instance_id == exclude_id:
                            should_exclude = True
                            break
                        # Check if the exclude_id is a suffix (e.g., "9508" matches "thunderbird__thunderbird-android-9508")
                        if instance_id.endswith(f"-{exclude_id}") or instance_id.endswith(f"_{exclude_id}"):
                            should_exclude = True
                            break
                    
                    if not should_exclude:
                        excluded_instances.append(inst)
                
                instances = excluded_instances
                logger.info(f"After excluding {len(exclude_instance_ids)} instance IDs: {len(instances)} instances remaining")
            
            if max_instances:
                instances = instances[:max_instances]
            
            logger.info(f"Validating {len(instances)} instances")
            
            for i, instance in enumerate(instances):
                instance_id = instance['instance_id']
                logger.info(f"[{i+1}/{len(instances)}] Validating instance: {instance_id}")
                
                try:
                    result = await self.validate_instance(instance)
                    results[instance_id] = result
                    
                    # Save intermediate results
                    self._save_instance_result(result)
                    
                    # Log progress with test details
                    status = "✓" if result.success else "✗"
                    if result.success:
                        pre_tests = f"{result.pre_test_execution.passed}/{result.pre_test_execution.total_tests}" if result.pre_test_execution else "0/0"
                        post_tests = f"{result.post_test_execution.passed}/{result.post_test_execution.total_tests}" if result.post_test_execution else "0/0"
                        logger.info(f"{status} {instance_id}: Pre-tests: {pre_tests}, Post-tests: {post_tests}, Fixed: {result.fail_to_pass_count}")
                    else:
                        logger.info(f"{status} {instance_id}: {result.error_message}")
                    
                except Exception as e:
                    logger.error(f"Failed to validate {instance_id}: {e}")
                    logger.error(traceback.format_exc())
                    
                    results[instance_id] = ValidationResult(
                        instance_id=instance_id,
                        success=False,
                        error_message=str(e)
                    )
                
                finally:
                    # Always cleanup container after each instance
                    logger.info(f"Cleaning up container for {instance_id}")
                    self.containers.cleanup_container(instance_id, keep_persistent=False)
            
            # Save final results
            _save_final_results(results, self.output_dir)
            
        except Exception as e:
            logger.error(f"Error during dataset validation: {e}")
            logger.error(traceback.format_exc())
        
        finally:
            # Final cleanup - remove all containers
            logger.info("Performing final cleanup of all containers")
            self.containers.cleanup_all(keep_persistent=False)
        
        return results
    
    async def validate_instance(self, instance: Dict) -> ValidationResult:
        """Validate a single task instance with proper test tracking."""
        instance_id = instance['instance_id']
        result = ValidationResult(instance_id=instance_id, success=False)
        
        start_time = time.time()
        repo_path = None
        
        try:
            logger.info(f"Starting validation for instance: {instance_id}")
            
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

            # Initialize testing module
            self.testing = AndroidTestingParallel(self.containers, self.config_parser)
            
            # Step 4: Checkout base commit
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

            # STEP 6a: Build project and save logs
            logger.info(f"Step 6a: Building project for {instance_id}")
            try:
                build_result = run_build_step(self.containers, instance_id, test_patch=instance['test_patch'], phase="BUILD-PRE-STUBS")
                result.build_result = build_result
                
                logger.info(f"Build completed: success={build_result.success}, "
                        f"duration={build_result.duration:.1f}s")
                
            except Exception as e:
                logger.error(f"Error in build step for {instance_id}: {e}")
                # Continue with validation even if build fails
                build_result = None

            # STEP 6b: Generate stubs if build failed OR if compilation errors detected
            should_generate_stubs = False
            stub_reason = ""
            
            if not build_result:
                should_generate_stubs = True
                stub_reason = "build step failed with exception"
            elif not build_result.success:
                should_generate_stubs = True
                stub_reason = "build marked as unsuccessful"
            elif self._has_compilation_errors(build_result.output):
                should_generate_stubs = True
                stub_reason = "compilation errors detected in build output"
            
            if should_generate_stubs:
                logger.info(f"Step 6b: Generating stubs for {instance_id} due to: {stub_reason}")
                
                try:
                    # Get API key
                    openrouter_key = os.getenv('OPENROUTER_API_KEY')
                    if not openrouter_key:
                        logger.warning(f"No OpenRouter API key found, skipping stub generation for {instance_id}")
                        result.stub_generation_result = None
                    else:
                        # Generate and apply stubs - use build output if available, otherwise empty string
                        build_log = build_result.output if build_result else ""
                        
                        # Choose stub generation approach based on configuration
                        stub_method = os.getenv('STUB_GENERATION_METHOD', 'patch_based')
                        
                        if stub_method == 'patch_based':
                            logger.info(f"Using patch-based stub generation for {instance_id}")
                            # Extract gradle command from build result to use same command for stub validation
                            gradle_cmd = build_result.gradle_command if build_result and build_result.gradle_command else None
                            stub_result = await generate_and_apply_patches(
                                containers_manager=self.containers,
                                instance_id=instance_id,
                                build_log=build_log,
                                test_patch=instance['test_patch'],
                                solution_patch=instance.get('patch', ''),
                                api_key=openrouter_key,
                                model="anthropic/claude-3.7-sonnet",
                                gradle_command=gradle_cmd
                            )
                        else:
                            logger.info(f"Using traditional file merging stub generation for {instance_id}")
                            stub_result = await generate_and_apply_stubs(
                                containers_manager=self.containers,
                                instance_id=instance_id,
                                build_log=build_log,
                                test_patch=instance['test_patch'],
                                solution_patch=instance.get('patch', ''),
                                api_key=openrouter_key,
                                model="anthropic/claude-3.7-sonnet"
                            )
                        
                        result.stub_generation_result = stub_result
                        
                        if stub_result.success:
                            logger.info(f"Stub generation successful for {instance_id}: "
                                    f"{len(stub_result.files_created)} files created, "
                                    f"cost=${stub_result.api_cost:.4f}")
                            
                            # Try building again after applying stubs
                            logger.info(f"Retrying build after applying stubs for {instance_id}")
                            retry_build_result = run_build_step(self.containers, instance_id, test_patch=instance['test_patch'], phase="BUILD-POST-STUBS")
                            result.retry_build_result = retry_build_result
                            
                            if retry_build_result.success and not self._has_compilation_errors(retry_build_result.output):
                                logger.info(f"Build successful and compilation errors resolved after stub generation for {instance_id}")
                            elif retry_build_result.success and self._has_compilation_errors(retry_build_result.output):
                                logger.warning(f"Build marked successful but compilation errors persist after stub generation for {instance_id}")
                            else:
                                logger.warning(f"Build still failing after stub generation for {instance_id}")
                        else:
                            logger.warning(f"Stub generation failed for {instance_id}: {stub_result.error_message}")
                            
                except Exception as e:
                    logger.error(f"Error in stub generation step for {instance_id}: {e}")
                    result.stub_generation_result = None
            else:
                logger.info(f"Step 6b: Skipping stub generation for {instance_id} - no build issues detected")

            logger.info(f"Step 6 completed for {instance_id}!")
            
            # Step 7: Run pre-solution tests (only test patch)
            logger.info(f"Running pre-solution tests for {instance_id}")
            self.containers.prepare_for_test_execution(instance_id, "pre")
            
            pre_test_results, pre_skipped_tests = self.testing.run_tests_from_patch(
                instance_id, instance['test_patch'], build_config, "TEST-PRE-SOLUTION"
            )
            result.pre_test_execution = pre_test_results
            result.skipped_instrumented_tests.extend(pre_skipped_tests)

            
            # # Extract individual test results for pre-execution
            # result.pre_passed_tests = [f"{t.class_name}.{t.test_name}" for t in pre_test_results.test_results if t.status == 'PASSED']
            # result.pre_failed_tests = [f"{t.class_name}.{t.test_name}" for t in pre_test_results.test_results if t.status in ['FAILED', 'ERROR']]
            
            # # Save pre-test logs and results
            # self._save_test_logs(instance_id, "pre", pre_test_results.raw_output)
            # self._save_test_results(instance_id, "pre", pre_test_results)

            # Step 8: Prepare fresh clone for post-solution tests 
            logger.info(f"Preparing fresh clone for post-solution tests for {instance_id}")
            
            # Clone fresh repository to separate directory on host
            clean_repo_path = self._clone_repository_for_post_solution(instance)
            if not clean_repo_path:
                result.error_message = "Failed to clone fresh repository for post-solution tests"
                return result
            
            try:
                # Copy fresh repository to container at /workspace_clean
                if not self.containers.copy_to_container(instance_id, clean_repo_path, "/workspace_clean"):
                    result.error_message = "Failed to copy fresh repository to container"
                    return result
                
                # Apply test patch to fresh clone inside container
                test_patch_success, _ = self.repository.apply_patch_to_path(
                    instance_id, instance['test_patch'], "test_patch_clean", "/workspace_clean"
                )
                if not test_patch_success:
                    result.error_message = "Failed to apply test patch to fresh clone"
                    return result
                
                # Apply solution patch to fresh clone inside container
                solution_patch_success, solution_patch_output = self.repository.apply_patch_to_path(
                    instance_id, instance['patch'], "solution_patch", "/workspace_clean"
                )
                if not solution_patch_success:
                    result.error_message = f"Failed to apply solution patch to fresh clone: {solution_patch_output}"
                    return result
                result.solution_patch_applied = True
                
            finally:
                # Clean up host copy of fresh repository
                self._cleanup_repository(clean_repo_path)
            
            # Step 9: Run post-solution tests from clean repository
            logger.info(f"Running post-solution tests for {instance_id}")
            self.containers.prepare_for_test_execution(instance_id, "post")
            
            # Run tests from clean workspace without directory switching
            try:
                post_test_results, post_skipped_tests = self.testing.run_tests_from_patch(
                    instance_id, instance['test_patch'], build_config, "TEST-POST-SOLUTION", workdir="/workspace_clean"
                )
                result.post_test_execution = post_test_results
                result.skipped_instrumented_tests.extend(post_skipped_tests)
            except Exception as e:
                logger.error(f"Failed to run post-solution tests from clean workspace: {e}")
                result.error_message = f"Failed to run post-solution tests: {str(e)}"
                return result
            
            # Remove duplicates from skipped tests
            result.skipped_instrumented_tests = list(set(result.skipped_instrumented_tests))
            
            # # Extract individual test results for post-execution
            # result.post_passed_tests = list(set([f"{t.class_name}.{t.test_name}" for t in post_test_results.test_results if t.status == 'PASSED']))
            # result.post_failed_tests = list(set([f"{t.class_name}.{t.test_name}" for t in post_test_results.test_results if t.status in ['FAILED', 'ERROR']]))

            # # Save post-test logs and results
            # self._save_test_logs(instance_id, "post", post_test_results.raw_output)
            # self._save_test_results(instance_id, "post", post_test_results)

            # Step 10: Compute test transitions
            result.compute_test_transitions()

            # Save test analysis
            _save_test_analysis(instance_id, result, self.output_dir)

            result.success = True
            logger.info(f"Validation completed successfully for {instance_id}")
            
            # Step 10: Analyze test transitions
            # if result.pre_test_execution and result.post_test_execution:
            #     pre_build_success = result.pre_test_execution.build_successful
            #     post_build_success = result.post_test_execution.build_successful
                
            #     if pre_build_success and post_build_success:
            #         # Both phases built successfully - normal test comparison
            #         test_comparison = self.testing.compare_test_results(
            #             result.pre_test_execution, result.post_test_execution
            #         )
                    
            #         # Set the transition lists
            #         result.fail_to_pass_tests = test_comparison['fail_to_pass']
            #         result.pass_to_pass_tests = test_comparison['pass_to_pass']
            #         result.pass_to_fail_tests = test_comparison['pass_to_fail']
            #         result.fail_to_fail_tests = test_comparison['fail_to_fail']
                    
            #     elif not pre_build_success and post_build_success:
            #         # Pre-solution: Build failed (compilation error)
            #         # Post-solution: Build succeeded with actual test results
            #         # Classify as "build_to_pass" or "build_to_fail"
            #         logger.info(f"Build failure resolved for {instance_id}")
                    
            #         # Separate tests that now pass vs fail after build resolution
            #         result.build_to_pass_tests = result.post_passed_tests.copy()
            #         result.build_to_fail_tests = result.post_failed_tests.copy()
                    
            #         # Clear regular transition lists since this is a build resolution case
            #         result.fail_to_pass_tests = []
            #         result.pass_to_pass_tests = []
            #         result.pass_to_fail_tests = []
            #         result.fail_to_fail_tests = []
                    
            #         result.build_failure_resolved = True
            #         logger.info(f"  {len(result.build_to_pass_tests)} tests now pass, {len(result.build_to_fail_tests)} tests now fail")
                    
            #     elif pre_build_success and not post_build_success:
            #         # Pre-solution: Build succeeded
            #         # Post-solution: Build failed (solution broke the build)
            #         logger.warning(f"Solution broke the build for {instance_id}")
                    
            #         # All pre-solution tests are now "unreachable" due to build failure
            #         result.pass_to_build_tests = result.pre_passed_tests.copy()
            #         # Note: We could also track fail_to_build_tests if needed
                    
            #         # Clear regular transition lists since this is a build regression case
            #         result.fail_to_pass_tests = []
            #         result.pass_to_pass_tests = []
            #         result.pass_to_fail_tests = []
            #         result.fail_to_fail_tests = []
                    
            #         result.solution_broke_build = True
            #         logger.warning(f"  {len(result.pass_to_build_tests)} previously passing tests now unreachable")
                    
            #     elif not pre_build_success and not post_build_success:
            #         # Both phases failed to build - no resolution
            #         logger.warning(f"Build failure persists for {instance_id} - solution did not fix compilation")
                    
            #         # This is a build_to_build case - no tests could run in either phase
            #         # We can try to infer what tests would have been affected from test patch
            #         inferred_tests = self._infer_tests_from_patch(instance['test_patch'])
            #         result.build_to_build_tests = inferred_tests
                    
            #         # Clear all other transition lists
            #         result.fail_to_pass_tests = []
            #         result.pass_to_pass_tests = []
            #         result.pass_to_fail_tests = []
            #         result.fail_to_fail_tests = []
            #         result.build_to_pass_tests = []
            #         result.pass_to_build_tests = []
            #         result.build_to_fail_tests = []
                    
            #         result.build_failure_persists = True
            #         logger.warning(f"  {len(result.build_to_build_tests)} tests remain unreachable due to persistent build failure")
            
            # else:
            #     # Fallback to normal comparison if one phase is missing
            #     logger.warning(f"Missing test execution results for {instance_id}")
            #     result.fail_to_pass_tests = []
            #     result.pass_to_pass_tests = []
            #     result.pass_to_fail_tests = []
            #     result.fail_to_fail_tests = []
            
            # Set the counts for regular test transitions
            # result.fail_to_pass_count = len(result.fail_to_pass_tests)
            # result.pass_to_pass_count = len(result.pass_to_pass_tests)
            # result.pass_to_fail_count = len(result.pass_to_fail_tests)
            # result.fail_to_fail_count = len(result.fail_to_fail_tests)
            
            # # Set the counts for build-related transitions
            # result.build_to_pass_count = len(result.build_to_pass_tests)
            # result.pass_to_build_count = len(result.pass_to_build_tests)
            # result.build_to_fail_count = len(result.build_to_fail_tests)
            # result.build_to_build_count = len(result.build_to_build_tests)
            
            # # Save test transition analysis
            # self._save_test_analysis(instance_id, result)
            
            # # Mark as successful
            # result.success = True
            # result.total_duration = time.time() - start_time
            
            # logger.info(f"Validation completed for {instance_id}")
            # logger.info(f"  Pre-tests: {len(result.pre_passed_tests)} passed, {len(result.pre_failed_tests)} failed")
            # logger.info(f"  Post-tests: {len(result.post_passed_tests)} passed, {len(result.post_failed_tests)} failed")
            # logger.info(f"  Transitions: {result.fail_to_pass_count} fixed, {result.pass_to_fail_count} broken")
            # logger.info(f"  Skipped instrumented tests: {len(result.skipped_instrumented_tests)}")
            
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Validation failed for {instance_id}: {e}")
        
        finally:
            # Cleanup temporary repository
            if repo_path and os.path.exists(repo_path):
                try:
                    self._cleanup_repository(repo_path)
                except Exception as e:
                    logger.warning(f"Failed to cleanup repo path {repo_path}: {e}")

            result.total_duration = time.time() - start_time
        
        return result
    
    def _has_compilation_errors(self, build_output: str) -> bool:
        """
        Check if build output contains compilation errors, even if marked as successful.
        
        Args:
            build_output: The build output string to analyze
            
        Returns:
            True if compilation errors are detected
        """
        if not build_output:
            return False
            
        output_lower = build_output.lower()
        
        # Common compilation error indicators
        compilation_error_indicators = [
            "cannot find symbol",
            "package does not exist", 
            "class not found",
            "method not found",
            "variable not found",
            "compilation failed",
            "could not compile",
            "error: cannot access",
            "error: package",
            "error: class",
            "error: method",
            "error: variable",
            "unresolved reference",
            "unresolved import",
            "undefined symbol",
            "no suitable method found",
            "incompatible types",
            "method does not override",
            "abstract method",
            "missing return statement"
        ]
        
        return any(error_indicator in output_lower for error_indicator in compilation_error_indicators)
    
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
        """Clone repository to temporary directory."""
        repo = instance['repo']
        instance_id = instance['instance_id']
        
        temp_dir = tempfile.mkdtemp(prefix=f"android_bench_{instance_id}_")
        
        try:
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
                    pass
            
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
    
    def _clone_repository_for_post_solution(self, instance: Dict[str, Any]) -> Optional[str]:
        """Clone a fresh repository specifically for post-solution tests."""
        repo = instance['repo']
        instance_id = instance['instance_id']
        base_commit = instance['base_commit']
        
        temp_dir = tempfile.mkdtemp(prefix=f"android_bench_clean_{instance_id}_")
        
        try:
            clone_url = f"https://github.com/{repo}.git"
            
            logger.info(f"Cloning fresh {repo} to {temp_dir} for post-solution tests")
            
            # Clone repository
            clone_cmd = ["git", "clone", "--recursive", "--depth", "1000", clone_url, temp_dir]
            result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode != 0:
                logger.error(f"Failed to clone fresh repository: {result.stderr}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            
            # Checkout base commit
            checkout_cmd = ["git", "checkout", base_commit]
            result = subprocess.run(checkout_cmd, cwd=temp_dir, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                # Try fetching more commits if shallow clone doesn't have the commit
                fetch_cmd = ["git", "fetch", "--unshallow"]
                fetch_result = subprocess.run(fetch_cmd, cwd=temp_dir, capture_output=True, text=True, timeout=300)
                
                if fetch_result.returncode == 0:
                    # Try checkout again
                    result = subprocess.run(checkout_cmd, cwd=temp_dir, capture_output=True, text=True, timeout=120)
                
                if result.returncode != 0:
                    logger.error(f"Failed to checkout base commit {base_commit}: {result.stderr}")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return None
            
            # Set proper permissions
            os.chmod(temp_dir, 0o755)
            for root, dirs, files in os.walk(temp_dir):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o755)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o644)
            
            logger.info(f"Successfully cloned fresh {repo} and checked out {base_commit}")
            return temp_dir
            
        except subprocess.TimeoutExpired:
            logger.error(f"Fresh repository cloning timed out for {repo}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        except Exception as e:
            logger.error(f"Error cloning fresh repository {repo}: {e}")
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
                find . -type f -exec chmod 666 {} + 2>/dev/null || true &&
                find . -type d -exec chmod 777 {} + 2>/dev/null || true
                """
            ]
            
            result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.debug("Docker permission fix completed")
                
        except Exception as e:
            logger.warning(f"Docker permission fix failed: {e}")
        
        try:
            shutil.rmtree(repo_path)
            logger.debug(f"Successfully cleaned up repository: {repo_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup repository {repo_path}: {e}")
    
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
        
        logger.info(f"Saved {phase} test logs to {log_file}")
    
    def _save_test_results(self, instance_id: str, phase: str, test_results: TestExecutionResult):
        """Save detailed test results to JSON file."""
        instance_dir = self.output_dir / instance_id
        instance_dir.mkdir(exist_ok=True, parents=True)
        
        # Save detailed test results
        results_data = {
            'phase': phase,
            'summary': {
                'total_tests': test_results.total_tests,
                'passed': test_results.passed,
                'failed': test_results.failed,
                'skipped': test_results.skipped,
                'errors': test_results.errors,
                'duration': test_results.duration,
                'exit_code': test_results.exit_code,
                'build_successful': test_results.build_successful
            },
            'individual_tests': [
                {
                    'test_name': test.test_name,
                    'class_name': test.class_name,
                    'full_name': f"{test.class_name}.{test.test_name}",
                    'status': test.status,
                    'duration': test.duration,
                    'failure_message': test.failure_message,
                    'error_message': test.error_message
                }
                for test in test_results.test_results
            ],
            'passed_tests': [f"{t.class_name}.{t.test_name}" for t in test_results.test_results if t.status == 'PASSED'],
            'failed_tests': [f"{t.class_name}.{t.test_name}" for t in test_results.test_results if t.status in ['FAILED', 'ERROR']],
            'skipped_tests': [f"{t.class_name}.{t.test_name}" for t in test_results.test_results if t.status == 'SKIPPED']
        }
        
        results_file = instance_dir / f"test_results_{phase}.json"
        with open(results_file, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"Saved {phase} test results to {results_file}")
        logger.info(f"  {test_results.passed} passed, {test_results.failed} failed, {test_results.skipped} skipped tests")
    
    def _infer_tests_from_patch(self, test_patch: str) -> List[str]:
        """Infer test names from patch content when build fails."""
        test_names = []
        
        # Look for test method patterns in the patch
        test_patterns = [
            r'@Test\s+public\s+void\s+(\w+)',  # Java test methods
            r'fun\s+(\w*[Tt]est\w*)\s*\(',      # Kotlin test methods
            r'void\s+(\w*[Tt]est\w*)\s*\(',     # C-style test methods
        ]
        
        for pattern in test_patterns:
            matches = re.findall(pattern, test_patch)
            test_names.extend(matches)
        
        # Look for class names that might contain tests
        class_pattern = r'class\s+(\w*[Tt]est\w*)'
        class_matches = re.findall(class_pattern, test_patch)
        
        # Generate qualified test names where possible
        qualified_tests = []
        for class_name in class_matches:
            for test_name in test_names:
                qualified_tests.append(f"{class_name}.{test_name}")
        
        # Return unique test names, preferring qualified names
        return list(set(qualified_tests)) if qualified_tests else list(set(test_names))

    def _switch_workspace_to_clean(self, instance_id: str) -> bool:
        """Switch workspace to clean directory by renaming directories."""
        try:
            switch_command = """
echo "=== Switching workspace to clean directory ===" &&
cd / &&
# Backup original workspace
if [ -d /workspace_original ]; then
    echo "Removing old backup..."
    rm -rf /workspace_original
fi &&
mv /workspace /workspace_original &&
# Move clean workspace to main workspace location
mv /workspace_clean /workspace &&
echo "=== Workspace switched to clean directory ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                switch_command,
                workdir="/",
                timeout=60
            )
            
            if exit_code == 0:
                logger.info(f"Successfully switched workspace to clean directory for {instance_id}")
                return True
            else:
                logger.error(f"Failed to switch workspace to clean directory: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error switching workspace for {instance_id}: {e}")
            return False

    def _switch_workspace_back(self, instance_id: str) -> bool:
        """Switch workspace back to original directory."""
        try:
            switch_command = """
echo "=== Switching workspace back to original ===" &&
cd / &&
# Remove the workspace directory (it was the clean one)
rm -rf /workspace &&
# Restore original workspace
mv /workspace_original /workspace &&
echo "=== Workspace restored to original ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                switch_command,
                workdir="/",
                timeout=60
            )
            
            if exit_code == 0:
                logger.info(f"Successfully switched workspace back to original for {instance_id}")
                return True
            else:
                logger.error(f"Failed to switch workspace back: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error switching workspace back for {instance_id}: {e}")
            return False


def _save_test_analysis(instance_id: str, result: ValidationResult, output_dir: Path):
    """Save test transition analysis."""
    instance_dir = output_dir / instance_id
    instance_dir.mkdir(exist_ok=True, parents=True)
    
    analysis_data = {
        'test_transitions': {
            'fail_to_pass': {
                'count': result.fail_to_pass_count,
                'tests': result.fail_to_pass_tests
            },
            'pass_to_pass': {
                'count': result.pass_to_pass_count,
                'tests': result.pass_to_pass_tests
            },
            'pass_to_fail': {
                'count': result.pass_to_fail_count,
                'tests': result.pass_to_fail_tests
            },
            'fail_to_fail': {
                'count': result.fail_to_fail_count,
                'tests': result.fail_to_fail_tests
            }
        },
        'execution_summary': {
            'pre_execution': {
                'passed_count': len(result.pre_passed_tests),
                'failed_count': len(result.pre_failed_tests),
                'passed_tests': result.pre_passed_tests,
                'failed_tests': result.pre_failed_tests,
                'gradle_command': result.pre_test_execution.gradle_command if result.pre_test_execution else ""
            },
            'post_execution': {
                'passed_count': len(result.post_passed_tests),
                'failed_count': len(result.post_failed_tests),
                'passed_tests': result.post_passed_tests,
                'failed_tests': result.post_failed_tests,
                'gradle_command': result.post_test_execution.gradle_command if result.post_test_execution else ""
            }
        },
        'skipped_instrumented_tests': {
            'count': len(result.skipped_instrumented_tests),
            'tests': result.skipped_instrumented_tests
        }
    }
    
    analysis_file = instance_dir / "test_analysis.json"
    with open(analysis_file, 'w') as f:
        json.dump(analysis_data, f, indent=2)
    
    logger.info(f"Saved test analysis to {analysis_file}")

def _save_final_results(self, results: Dict[str, ValidationResult], output_dir: Path):
    """Save final summary results with test transitions only."""
    successful = [r for r in results.values() if r.success]
    failed = [r for r in results.values() if not r.success]
    
    # Calculate aggregate test statistics (only test transitions)
    total_fail_to_pass = sum(r.fail_to_pass_count for r in successful)
    total_pass_to_pass = sum(r.pass_to_pass_count for r in successful)
    total_pass_to_fail = sum(r.pass_to_fail_count for r in successful)
    total_fail_to_fail = sum(r.fail_to_fail_count for r in successful)
    
    # Calculate test statistics
    all_tests_found = set()
    for result in successful:
        all_tests_found.update(result.pre_passed_tests)
        all_tests_found.update(result.pre_failed_tests)
        all_tests_found.update(result.post_passed_tests)
        all_tests_found.update(result.post_failed_tests)
    
    # Calculate durations
    total_duration = sum(r.total_duration for r in successful if r.total_duration > 0)
    avg_duration = total_duration / len(successful) if successful else 0
    
    # Create comprehensive summary
    summary = {
        'validation_metadata': {
            'completion_time': datetime.now().isoformat(),
            'total_duration_hours': total_duration / 3600,
            'execution_summary': f"Completed {len(successful)}/{len(results)} instances successfully"
        },
        'overall_statistics': {
            'total_instances': len(results),
            'successful': len(successful),
            'failed': len(failed),
            'success_rate': len(successful) / len(results) if results else 0
        },
        'test_transition_statistics': {
            'fail_to_pass': total_fail_to_pass,
            'pass_to_pass': total_pass_to_pass,
            'pass_to_fail': total_pass_to_fail,
            'fail_to_fail': total_fail_to_fail,
            'summary': {
                'total_tests_fixed': total_fail_to_pass,
                'total_tests_broken': total_pass_to_fail,
                'unique_tests_found': len(all_tests_found)
            }
        },
        'performance_metrics': {
            'avg_duration_seconds': avg_duration,
            'total_duration_hours': total_duration / 3600
        }
    }
    
    # Save summary
    summary_file = output_dir / "final_validation_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"Saved final validation summary to {summary_file}")


async def main():
    """Main entry point for the fixed Android-bench validator."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Android-bench validation engine (fixed with test tracking)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Fixed Features:
  - Individual test tracking with pass/fail lists
  - Separate log files for each execution phase
  - Container cleanup after each instance
  - Detailed test transition analysis
  - Proper test result parsing and saving
  - Fixed tuple handling for test results
  - Instrumented test tracking

Examples:
  # Basic validation with test tracking
  python validator_fixed.py dataset.jsonl
  
  # Validate specific instances (supports both full IDs and numeric suffixes)
  python validator_fixed.py dataset.jsonl --instance-ids "6044" "thunderbird__android-6045"
  
  # Exclude specific instances (supports both full IDs and numeric suffixes)
  python validator_fixed.py dataset.jsonl --exclude-instance-ids "9508" "9510" "thunderbird__android-9512"
  
  # Combine include and exclude (exclude takes precedence)
  python validator_fixed.py dataset.jsonl --instance-ids "inst1" "inst2" "inst3" --exclude-instance-ids "inst2"
  
  # Custom output directory
  python validator_fixed.py dataset.jsonl --output-dir fixed_results
        """
    )
    
    parser.add_argument("dataset_file", help="Path to dataset JSONL file")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to validate")
    parser.add_argument("--exclude-instance-ids", nargs="+", help="Instance IDs to exclude from validation")
    parser.add_argument("--max-instances", type=int, help="Maximum number of instances to validate")
    parser.add_argument("--output-dir", default="android_validation_results_fixed", help="Output directory")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--docker-context", help="Docker context to use")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not Path(args.dataset_file).exists():
        print(f"Error: Dataset file not found: {args.dataset_file}")
        sys.exit(1)
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    
    # Create validator
    validator = AndroidBenchValidator(
        args.output_dir, 
        args.docker_context
    )
    
    try:
        # Run validation
        results = await validator.validate_dataset(
            args.dataset_file, 
            args.instance_ids, 
            args.exclude_instance_ids,
            args.max_instances
        )
        
        # Print summary with test details
        successful = len([r for r in results.values() if r.success])
        total = len(results)
        success_rate = successful / total * 100 if total > 0 else 0
        
        # Calculate test statistics
        total_tests_fixed = sum(r.fail_to_pass_count for r in results.values() if r.success)
        total_tests_broken = sum(r.pass_to_fail_count for r in results.values() if r.success)
        total_instrumented_skipped = sum(len(r.skipped_instrumented_tests) for r in results.values() if r.success and r.skipped_instrumented_tests)
        
        print(f"\nFixed Validation Summary:")
        print(f"  Total: {total}")
        print(f"  Successful: {successful}")
        print(f"  Failed: {total - successful}")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Tests Fixed: {total_tests_fixed}")
        print(f"  Tests Broken: {total_tests_broken}")
        print(f"  Instrumented Tests Skipped: {total_instrumented_skipped}")
        print(f"  Results saved to: {args.output_dir}")
        
        # Exit with appropriate code
        sys.exit(0 if successful > 0 else 1)
        
    except KeyboardInterrupt:
        print("\nValidation interrupted by user")
        validator.containers.cleanup_all(keep_persistent=False)
        sys.exit(1)
    except Exception as e:
        print(f"Validation failed: {e}")
        validator.containers.cleanup_all(keep_persistent=False)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())