#!/usr/bin/env python3
"""
Enhanced Android-bench validation engine with resume functionality and incremental saving.

Key Enhancements:
- Resume from previous execution state
- Incremental statistics saving
- Progress checkpoints
- State persistence across interruptions
- Final validation summary and report generation
"""

import json
import os
import sys
import time
import asyncio
import logging
import argparse
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from dataclasses import asdict

from validator_utils import (
    AndroidBenchValidator, 
    ValidationResult,
    logger
)

class ResumeableValidator(AndroidBenchValidator):
    """Enhanced validator with resume and incremental saving capabilities."""
    
    def __init__(self, output_dir: str, docker_context: Optional[str] = None, keep_containers: bool = False):
        super().__init__(output_dir, docker_context)
        self.progress_file = Path(self.output_dir) / "validation_progress.json"
        self.checkpoint_file = Path(self.output_dir) / "validation_checkpoint.json"
        self.statistics_file = Path(self.output_dir) / "incremental_statistics.json"
        self.keep_containers = keep_containers
        
        # Ensure output directory exists
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize progress tracking
        self.completed_instances: Set[str] = set()
        self.failed_instances: Set[str] = set()
        self.current_statistics = self._initialize_statistics()
    
    def _initialize_statistics(self) -> Dict[str, Any]:
        """Initialize statistics structure."""
        return {
            'metadata': {
                'start_time': datetime.now().isoformat(),
                'completed_instances': 0,
                'success_rate': 0.0
            },
            'test_statistics': {
                'total_tests_fixed': 0,
                'total_tests_broken': 0,
                'total_instrumented_skipped': 0,
                'transition_counts': {
                    'fail_to_pass': 0,
                    'pass_to_pass': 0,
                    'pass_to_fail': 0,
                    'fail_to_fail': 0
                },
                'unique_tests_found': set()
            },
            'performance_metrics': {
                'instance_durations': {}
            },
            # 'completed_instances_details': {},
            # 'failed_instances_details': {}
        }
    
    def _load_progress(self) -> bool:
        """Load progress from previous execution."""
        try:
            if self.progress_file.exists():
                with open(self.progress_file, 'r') as f:
                    progress_data = json.load(f)
                
                self.completed_instances = set(progress_data.get('completed_instances', []))
                self.failed_instances = set(progress_data.get('failed_instances', []))
                
                logger.info(f"Loaded progress: {len(self.completed_instances)} completed, "
                           f"{len(self.failed_instances)} failed instances")
                return True
            
            if self.statistics_file.exists():
                with open(self.statistics_file, 'r') as f:
                    stats_data = json.load(f)
                
                # Convert set back from list for JSON compatibility
                if 'test_statistics' in stats_data and 'unique_tests_found' in stats_data['test_statistics']:
                    stats_data['test_statistics']['unique_tests_found'] = set(
                        stats_data['test_statistics']['unique_tests_found']
                    )
                
                self.current_statistics = stats_data
                logger.info("Loaded previous statistics")
                return True
                
        except Exception as e:
            logger.warning(f"Could not load progress: {e}")
            
        return False
    
    def _save_progress(self):
        """Save current progress."""
        try:
            progress_data = {
                'completed_instances': list(self.completed_instances),
                'failed_instances': list(self.failed_instances),
                'last_update': datetime.now().isoformat()
            }
            
            with open(self.progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")
    
    def _save_incremental_statistics(self):
        """Save current statistics incrementally."""
        try:
            # Convert set to list for JSON serialization
            stats_copy = self.current_statistics.copy()
            if 'test_statistics' in stats_copy and 'unique_tests_found' in stats_copy['test_statistics']:
                stats_copy['test_statistics']['unique_tests_found'] = list(
                    stats_copy['test_statistics']['unique_tests_found']
                )
            
            stats_copy['metadata']['last_update'] = datetime.now().isoformat()
            
            with open(self.statistics_file, 'w') as f:
                json.dump(stats_copy, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save incremental statistics: {e}")
    
    def _update_statistics(self, instance_id: str, result: ValidationResult):
        """Update incremental statistics with new result."""
        if result.success:
            self.current_statistics['metadata']['completed_instances'] += 1
            
            # Update test statistics
            test_stats = self.current_statistics['test_statistics']
            test_stats['total_tests_fixed'] += result.fail_to_pass_count
            test_stats['total_tests_broken'] += result.pass_to_fail_count
            test_stats['total_instrumented_skipped'] += len(result.skipped_instrumented_tests)
            
            # Update transition counts
            transitions = test_stats['transition_counts']
            transitions['fail_to_pass'] += result.fail_to_pass_count
            transitions['pass_to_pass'] += result.pass_to_pass_count
            transitions['pass_to_fail'] += result.pass_to_fail_count
            transitions['fail_to_fail'] += result.fail_to_fail_count
            
            # Collect unique tests
            unique_tests = test_stats['unique_tests_found']
            if not isinstance(unique_tests, set):
                unique_tests = set(unique_tests) if unique_tests else set()
                test_stats['unique_tests_found'] = unique_tests
            
            # Add tests from current result
            unique_tests.update(result.pre_passed_tests)
            unique_tests.update(result.pre_failed_tests)
            unique_tests.update(result.post_passed_tests)
            unique_tests.update(result.post_failed_tests)
            
            # # Store completed instance details
            # self.current_statistics['completed_instances_details'][instance_id] = {
            #     'success': True,
            #     'duration': result.total_duration,
            #     'tests_fixed': result.fail_to_pass_count,
            #     'tests_broken': result.pass_to_fail_count,
            #     'completion_time': datetime.now().isoformat()
            # }
            # Update performance metrics
            self.current_statistics['performance_metrics']['instance_durations'][instance_id] = result.total_duration
            
            # Update success rate
            completed = self.current_statistics['metadata']['completed_instances']
            total = completed + len(self.failed_instances)
            self.current_statistics['metadata']['success_rate'] = completed / total if total > 0 else 0
        # else:
        #     self.current_statistics['metadata']['failed_instances'] += 1
        #     self.current_statistics['failed_instances_details'][instance_id] = {
        #         'success': False,
        #         'error_message': result.error_message,
        #         'duration': result.total_duration,
        #         'completion_time': datetime.now().isoformat()
        #     }
        
        # Update performance metrics
        # perf_metrics = self.current_statistics['performance_metrics']
        # perf_metrics['total_duration_seconds'] += result.total_duration
        # perf_metrics['instance_durations'][instance_id] = result.total_duration
        
        # completed = self.current_statistics['metadata']['completed_instances']
        # if completed > 0:
        #     perf_metrics['average_duration_seconds'] = perf_metrics['total_duration_seconds'] / completed
        
        # # Update remaining instances
        # total = self.current_statistics['metadata']['total_instances']
        # completed_total = completed + self.current_statistics['metadata']['failed_instances']
        # self.current_statistics['metadata']['remaining_instances'] = total - completed_total
    
    def _save_checkpoint(self, results: Dict[str, ValidationResult]):
        """Save detailed checkpoint with all current results."""
        try:
            checkpoint_data = {
                'timestamp': datetime.now().isoformat(),
                'completed_instances': list(self.completed_instances),
                'failed_instances': list(self.failed_instances),
                'current_statistics': self.current_statistics,
                'results_summary': {
                    instance_id: {
                        'success': result.success,
                        'error_message': result.error_message,
                        'total_duration': result.total_duration,
                        'tests_fixed': result.fail_to_pass_count if result.success else 0,
                        'tests_broken': result.pass_to_fail_count if result.success else 0
                    }
                    for instance_id, result in results.items()
                }
            }
            
            with open(self.checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f, indent=2)
                
            logger.info(f"Saved checkpoint with {len(results)} results")
            
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
    
    async def validate_dataset(self, dataset_file: str, instance_ids: Optional[List[str]] = None,
                        exclude_instance_ids: Optional[List[str]] = None,
                        max_instances: Optional[int] = None) -> Dict[str, ValidationResult]:
        """Enhanced dataset validation with resume functionality."""
        
        # Load progress from previous run
        self._load_progress()
        
        # Load dataset
        instances = self._load_dataset(dataset_file)
        
        # Filter instances based on arguments
        if instance_ids:
            normalized_ids = normalize_instance_ids(instance_ids, dataset_context=dataset_file)
            print(f"Filtering instances by IDs: {normalized_ids}")
            instances = [inst for inst in instances if inst['instance_id'] in normalized_ids]
        
        if exclude_instance_ids:
            normalized_exclude = normalize_instance_ids(exclude_instance_ids, dataset_context=dataset_file)
            instances = [inst for inst in instances if inst['instance_id'] not in normalized_exclude]
        
        if max_instances:
            instances = instances[:max_instances]
        
        # Filter out already completed instances
        remaining_instances = [
            inst for inst in instances 
            if inst['instance_id'] not in self.completed_instances and 
               inst['instance_id'] not in self.failed_instances
        ]
        
        logger.info(f"Dataset validation: {len(instances)} total instances, "
                   f"{len(remaining_instances)} remaining to process")
        
        if not remaining_instances:
            logger.info("All instances already completed. Loading existing results...")
            return self._load_existing_results(instances)
        
        # Initialize statistics metadata
        if not self.current_statistics['metadata']['start_time']:
            self.current_statistics['metadata']['start_time'] = datetime.now().isoformat()
        self.current_statistics['metadata']['total_instances'] = len(instances)
        
        results = {}
        
        try:
            # Process remaining instances
            for i, instance in enumerate(remaining_instances, 1):
                instance_id = instance['instance_id']
                
                logger.info(f"Processing {i}/{len(remaining_instances)}: {instance_id}")
                
                try:
                    result = await self.validate_instance(instance)
                    results[instance_id] = result
                    
                    # Update tracking sets
                    if result.success:
                        self.completed_instances.add(instance_id)
                        status = "✓ SUCCESS"
                    else:
                        self.failed_instances.add(instance_id)
                        status = "✗ FAILED"
                    
                    # Update statistics incrementally
                    self._update_statistics(instance_id, result)
                    
                    # Save progress after each instance
                    self._save_progress()
                    self._save_incremental_statistics()
                    
                    # Log progress
                    if result.success and result.pre_test_execution and result.post_test_execution:
                        pre_tests = f"{result.pre_test_execution.passed}/{result.pre_test_execution.total_tests}"
                        post_tests = f"{result.post_test_execution.passed}/{result.post_test_execution.total_tests}"
                        logger.info(f"{status} {instance_id}: Pre-tests: {pre_tests}, "
                                   f"Post-tests: {post_tests}, Fixed: {result.fail_to_pass_count}")
                    else:
                        logger.info(f"{status} {instance_id}: {result.error_message}")
                    
                    # Save checkpoint every 10 instances
                    if i % 10 == 0:
                        self._save_checkpoint(results)
                        logger.info(f"Checkpoint saved at {i}/{len(remaining_instances)} instances")
                
                except Exception as e:
                    logger.error(f"Failed to validate {instance_id}: {e}")
                    logger.error(traceback.format_exc())
                    
                    # Create failed result
                    failed_result = ValidationResult(
                        instance_id=instance_id,
                        success=False,
                        error_message=str(e)
                    )
                    results[instance_id] = failed_result
                    self.failed_instances.add(instance_id)
                    self._update_statistics(instance_id, failed_result)
                    self._save_progress()
                    self._save_incremental_statistics()
                
                finally:
                    # Cleanup container after each instance (keep if --keep-containers flag is set)
                    if self.keep_containers:
                        logger.info(f"Keeping container for {instance_id} for manual debugging (--keep-containers flag)")
                        self.containers.cleanup_container(instance_id, keep_persistent=True, preserve_for_debug=True)
                    else:
                        logger.info(f"Cleaning up container for {instance_id}")
                        self.containers.cleanup_container(instance_id, keep_persistent=False, preserve_for_debug=False)
            
            # Final checkpoint save
            self._save_checkpoint(results)
            
            # Load any existing results and merge
            all_results = self._load_existing_results(instances)
            all_results.update(results)
            
            # Generate final summary and report
            self._generate_final_summary_and_report(all_results)
            
            return all_results
            
        except Exception as e:
            logger.error(f"Error during dataset validation: {e}")
            logger.error(traceback.format_exc())
            # Save what we have so far
            self._save_checkpoint(results)
            raise
        
        finally:
            # Final cleanup
            if self.keep_containers:
                logger.info("Keeping all containers for manual debugging (--keep-containers flag)")
                self.containers.cleanup_all(keep_persistent=True) # MARKER
            else:
                logger.info("Performing final cleanup of all containers")
                self.containers.cleanup_all(keep_persistent=False)
    
    def _load_existing_results(self, instances: List[Dict[str, Any]]) -> Dict[str, ValidationResult]:
        """Load existing results from previous runs."""
        results = {}
        
        for instance in instances:
            instance_id = instance['instance_id']
            instance_dir = Path(self.output_dir) / instance_id
            
            if instance_dir.exists():
                # Try to reconstruct result from saved files
                try:
                    result = self._reconstruct_result_from_files(instance_id, instance_dir)
                    if result:
                        results[instance_id] = result
                except Exception as e:
                    logger.warning(f"Could not reconstruct result for {instance_id}: {e}")
        
        return results
    
    def _reconstruct_result_from_files(self, instance_id: str, instance_dir: Path) -> Optional[ValidationResult]:
        """Reconstruct a ValidationResult from saved files."""
        try:
            # Check if test analysis exists
            analysis_file = instance_dir / "test_analysis.json"
            if not analysis_file.exists():
                return None
            
            with open(analysis_file, 'r') as f:
                analysis_data = json.load(f)
            
            # Create ValidationResult
            result = ValidationResult(instance_id=instance_id, success=True)
            
            # Populate from analysis data
            transitions = analysis_data.get('test_transitions', {})
            result.fail_to_pass_count = transitions.get('fail_to_pass', {}).get('count', 0)
            result.pass_to_pass_count = transitions.get('pass_to_pass', {}).get('count', 0)
            result.pass_to_fail_count = transitions.get('pass_to_fail', {}).get('count', 0)
            result.fail_to_fail_count = transitions.get('fail_to_fail', {}).get('count', 0)
            
            result.fail_to_pass_tests = transitions.get('fail_to_pass', {}).get('tests', [])
            result.pass_to_pass_tests = transitions.get('pass_to_pass', {}).get('tests', [])
            result.pass_to_fail_tests = transitions.get('pass_to_fail', {}).get('tests', [])
            result.fail_to_fail_tests = transitions.get('fail_to_fail', {}).get('tests', [])
            
            execution = analysis_data.get('execution_summary', {})
            result.pre_passed_tests = execution.get('pre_execution', {}).get('passed_tests', [])
            result.pre_failed_tests = execution.get('pre_execution', {}).get('failed_tests', [])
            result.post_passed_tests = execution.get('post_execution', {}).get('passed_tests', [])
            result.post_failed_tests = execution.get('post_execution', {}).get('failed_tests', [])
            
            result.skipped_instrumented_tests = analysis_data.get('skipped_instrumented_tests', {}).get('tests', [])
            
            # Get duration from statistics if available
            if instance_id in self.current_statistics['performance_metrics']['instance_durations']:
                result.total_duration = self.current_statistics['performance_metrics']['instance_durations'][instance_id]
            
            return result
            
        except Exception as e:
            logger.warning(f"Error reconstructing result for {instance_id}: {e}")
            return None
    
    def _generate_final_summary_and_report(self, results: Dict[str, ValidationResult]):
        """Generate final validation summary and report."""
        logger.info("Generating final validation summary and report...")
        
        # Calculate final statistics
        successful_results = [r for r in results.values() if r.success]
        failed_results = [r for r in results.values() if not r.success]
        
        total_instances = len(results)
        successful_count = len(successful_results)
        failed_count = len(failed_results)
        success_rate = (successful_count / total_instances * 100) if total_instances > 0 else 0
        
        # Aggregate test statistics
        total_fail_to_pass = sum(r.fail_to_pass_count for r in successful_results)
        total_pass_to_pass = sum(r.pass_to_pass_count for r in successful_results)
        total_pass_to_fail = sum(r.pass_to_fail_count for r in successful_results)
        total_fail_to_fail = sum(r.fail_to_fail_count for r in successful_results)
       
        # Performance metrics
        total_duration = sum(r.total_duration for r in results.values() if r.total_duration)
        avg_duration = total_duration / len(results) if len(results) > 0 else 0
        
        # Collect all unique tests
        all_tests_found = set()
        for result in successful_results:
            for test_list in [result.pre_passed_tests, result.pre_failed_tests,
                             result.post_passed_tests, result.post_failed_tests]:
                if test_list:
                    all_tests_found.update(test_list)
        
        # Create comprehensive summary
        summary = {
            'validation_metadata': {
                'completion_time': datetime.now().isoformat(),
                'total_duration_hours': total_duration / 3600,
                'execution_summary': f"Completed {successful_count}/{total_instances} instances successfully"
            },
            'overall_statistics': {
                'total_instances': total_instances,
                'successful': successful_count,
                'failed': failed_count,
                'success_rate': success_rate
            },
            'test_transition_statistics': {
                'fail_to_pass': total_fail_to_pass,
                'pass_to_pass': total_pass_to_pass,
                'pass_to_fail': total_pass_to_fail,
                'fail_to_fail': total_fail_to_fail,
                'summary': {
                    'total_tests_fixed': total_fail_to_pass,
                    'total_tests_broken': total_pass_to_fail,
                    'total_tests_maintained': total_pass_to_pass,
                    'total_tests_still_failing': total_fail_to_fail,
                    'unique_tests_found': len(all_tests_found)
                }
            },
            'performance_metrics': {
                'avg_duration_seconds': avg_duration,
                'total_duration_hours': total_duration / 3600,
                'longest_instance': max(results.values(), key=lambda r: r.total_duration or 0).instance_id if results else None,
                'shortest_instance': min(results.values(), key=lambda r: r.total_duration or float('inf')).instance_id if results else None
            },
            'detailed_results': {k: asdict(v) for k, v in results.items()}
        }
        
        # Save final summary
        summary_file = Path(self.output_dir) / "final_validation_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        # Generate comprehensive report
        report_lines = [
            "AndroidBench Validation Report",
            "=" * 60,
            f"Execution completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total runtime: {total_duration / 3600:.2f} hours",
            "",
            "Overall Results:",
            "-" * 16,
            f"Total Instances: {total_instances}",
            f"Successful: {successful_count}",
            f"Failed: {failed_count}",
            f"Success Rate: {success_rate:.1f}%",
            "",
            "Test Statistics:",
            "-" * 16,
            f"Unique Tests Found: {len(all_tests_found)}",
            f"Total Tests Fixed: {total_fail_to_pass}",
            f"Total Tests Broken: {total_pass_to_fail}",
            f"Total Tests Maintained: {total_pass_to_pass}",
            f"Total Tests Still Failing: {total_fail_to_fail}",
            "",
            "Test Transition Summary:",
            "-" * 23,
            f"  Tests Fixed (Fail→Pass): {total_fail_to_pass}",
            f"  Tests Maintained (Pass→Pass): {total_pass_to_pass}",
            f"  Tests Broken (Pass→Fail): {total_pass_to_fail}",
            f"  Tests Still Failing (Fail→Fail): {total_fail_to_fail}",
            "",
            "Performance Metrics:",
            "-" * 20,
            f"Average Instance Duration: {avg_duration:.1f}s",
            f"Total Execution Time: {total_duration / 3600:.2f}h",
            "",
        ]
        
        if failed_results:
            report_lines.extend([
                "Failed Instances:",
                "-" * 17,
            ])
            for result in failed_results:
                report_lines.append(f"  - {result.instance_id}: {result.error_message}")
            report_lines.append("")
        
        report_lines.extend([
            "Files Generated:",
            "-" * 16,
            f"  - final_validation_summary.json: Comprehensive results",
            f"  - validation_report.txt: This human-readable report",
            f"  - incremental_statistics.json: Running statistics",
            f"  - validation_progress.json: Execution progress",
            f"  - Individual instance directories with detailed test analysis",
            "",
            "Resume Information:",
            "-" * 18,
            "To resume from interruption, simply re-run the same command.",
            "The validator will automatically skip completed instances.",
            "",
        ])
        
        report_content = "\n".join(report_lines)
        
        # Save report
        report_file = Path(self.output_dir) / "validation_report.txt"
        with open(report_file, 'w') as f:
            f.write(report_content)
        
        logger.info(f"Generated final report: {report_file}")

# Configuration for instance ID normalization patterns
INSTANCE_ID_PATTERNS = {
    'thunderbird': 'thunderbird__thunderbird-android-',
    'AntennaPod': 'AntennaPod__AntennaPod-',
    'wordPress': 'wordpress-mobile__WordPress-Android-',
    'Tusky': 'tuskyapp__Tusky-',
    # Add more patterns as needed
}

def normalize_instance_ids(instance_ids: list, patterns: dict = None, dataset_context: str = None) -> set:
    """
    Normalize instance IDs using configurable patterns.
    
    Args:
        instance_ids: List of instance IDs to normalize
        patterns: Dict mapping app names to their prefixes
        dataset_context: Optional context about which dataset we're working with
    
    Returns:
        Set of normalized instance IDs
    """
    if patterns is None:
        patterns = INSTANCE_ID_PATTERNS
    
    normalized_ids = set()
    
    for instance_id in instance_ids:
        normalized_ids.add(instance_id)
        
        # If it's just a number, try to determine which pattern to use
        if instance_id.isdigit():
            # If we have dataset context, prioritize the matching pattern
            if dataset_context:
                for app_name, prefix in patterns.items():
                    if app_name.lower() in dataset_context.lower():
                        normalized_ids.add(f'{prefix}{instance_id}')
                        break
            else:
                # Try all patterns if no context
                for prefix in patterns.values():
                    normalized_ids.add(f'{prefix}{instance_id}')
        else:
            # For non-numeric IDs, try smart matching
            for app_name, prefix in patterns.items():
                if not instance_id.startswith(prefix):
                    # Check various conditions for a match
                    should_add = False
                    
                    # Direct app name match
                    if app_name.lower() in instance_id.lower():
                        should_add = True
                    
                    # Check for word parts (e.g., "WordPress" matches "wordpress")
                    app_words = app_name.lower().replace('-', ' ').replace('_', ' ').split()
                    id_lower = instance_id.lower()
                    if any(word in id_lower for word in app_words):
                        should_add = True
                    
                    if should_add:
                        normalized_ids.add(f'{prefix}{instance_id}')
    
    return normalized_ids

async def main():
    parser = argparse.ArgumentParser(
        description="Enhanced Android-bench validation engine with resume functionality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Enhanced Features:
  - Resume from interruptions automatically
  - Incremental statistics saving during execution
  - Progress checkpoints every 10 instances
  - Comprehensive final summary and report
  - State persistence across sessions
  - Individual test tracking with detailed analysis

Examples:
  # Basic validation (will resume if interrupted)
  python enhanced_validator.py dataset.jsonl

  # Validate specific instances
  python enhanced_validator.py dataset.jsonl --instance-ids "6044" "6045"

  # Custom output directory
  python enhanced_validator.py dataset.jsonl --output-dir enhanced_results

  # Resume after interruption (automatic)
  python enhanced_validator.py dataset.jsonl --output-dir previous_results
        """
    )
        
    """Main entry point for the enhanced validator with resume functionality."""
    parser.add_argument("dataset_file", help="Path to dataset JSONL file")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to validate")
    parser.add_argument("--exclude-instance-ids", nargs="+", help="Instance IDs to exclude from validation")
    parser.add_argument("--max-instances", type=int, help="Maximum number of instances to validate")
    parser.add_argument("--output-dir", default="android_validation_results_enhanced", help="Output directory")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--docker-context", help="Docker context to use")
    parser.add_argument("--keep-containers", action="store_true", 
                       help="Keep containers running after tests for manual debugging")
    parser.add_argument("--force-restart", action="store_true", 
                       help="Force restart from beginning, ignoring previous progress")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not Path(args.dataset_file).exists():
        print(f"Error: Dataset file not found: {args.dataset_file}")
        sys.exit(1)
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    
    # Create enhanced validator
    validator = ResumeableValidator(
        args.output_dir, 
        args.docker_context,
        args.keep_containers
    )
    
    # Clear previous progress if force restart requested
    if args.force_restart:
        logger.info("Force restart requested - clearing previous progress")
        for file_to_clear in [validator.progress_file, validator.checkpoint_file, validator.statistics_file]:
            if file_to_clear.exists():
                file_to_clear.unlink()
                logger.info(f"Cleared {file_to_clear}")
    
    try:
        # Run enhanced validation
        results = await validator.validate_dataset(
            args.dataset_file, 
            args.instance_ids, 
            args.exclude_instance_ids,
            args.max_instances
        )
        
        # Print final summary
        successful = len([r for r in results.values() if r.success])
        total = len(results)
        success_rate = successful / total * 100 if total > 0 else 0
        
        # Calculate test statistics
        total_tests_fixed = sum(r.fail_to_pass_count for r in results.values() if r.success)
        total_tests_broken = sum(r.pass_to_fail_count for r in results.values() if r.success)
        total_instrumented_skipped = sum(len(r.skipped_instrumented_tests) for r in results.values() if r.success and r.skipped_instrumented_tests)
        
        print(f"\nEnhanced Validation Complete!")
        print(f"  Total: {total}")
        print(f"  Successful: {successful}")
        print(f"  Failed: {total - successful}")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Tests Fixed: {total_tests_fixed}")
        print(f"  Tests Broken: {total_tests_broken}")
        print(f"  Instrumented Tests Skipped: {total_instrumented_skipped}")
        print(f"  Results saved to: {args.output_dir}")
        print(f"\nKey files generated:")
        print(f"  - final_validation_summary.json: Comprehensive results")
        print(f"  - validation_report.txt: Human-readable report")
        print(f"  - incremental_statistics.json: Running statistics")
        print(f"  - validation_progress.json: Resume information")
        
        # Show container debugging info if containers are kept
        if args.keep_containers:
            print(f"\n🐳 CONTAINERS KEPT FOR DEBUGGING:")
            print(f"  Use 'docker ps' to see running containers")
            print(f"  Connect with: docker exec -it -w / <container_name> /bin/bash")
            print(f"  Container names typically start with 'android-bench-'")
            print(f"  📁 PRESERVED DIRECTORIES:")
            print(f"    /workspace - Pre-solution test state (with build artifacts)")
            print(f"    /workspace_post - Post-solution test state (final working solution)")
            print(f"  Remember to clean up containers manually when done!")
        
        # Exit with appropriate code
        sys.exit(0 if successful > 0 else 1)
        
    except KeyboardInterrupt:
        print("\nValidation interrupted by user")
        print("Progress has been saved. Re-run the same command to resume.")
        validator.containers.cleanup_all(keep_persistent=validator.keep_containers, preserve_for_debug=validator.keep_containers)
        sys.exit(1)
    except Exception as e:
        print(f"Validation failed: {e}")
        logger.error(traceback.format_exc())
        validator.containers.cleanup_all(keep_persistent=validator.keep_containers, preserve_for_debug=validator.keep_containers)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())