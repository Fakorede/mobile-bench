#!/usr/bin/env python3
"""
Main evaluation engine for Android-bench.
"""

import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# Import our modules
from loader import load_dataset_and_predictions, TaskInstance, ModelPrediction
from parser import AndroidConfigParser
from containers import AndroidContainerManager
from executor import AndroidTestExecutor, TestExecutionResult
from logger import setup_logging, AndroidBenchLogger
from repository import create_repository_manager

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Complete evaluation result for a single instance."""
    instance_id: str
    model_name: str
    success: bool
    error_message: str = ""
    
    # Setup phase
    repo_cloned: bool = False
    config_parsed: bool = False
    container_created: bool = False
    base_commit_checked_out: bool = False
    
    # Test execution phase
    test_patch_applied: bool = False
    prediction_patch_applied: bool = False
    test_execution: Optional[TestExecutionResult] = None
    
    # Timing
    total_duration: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        
        # Handle TestExecutionResult object
        if self.test_execution:
            result['test_execution'] = {
                'total_tests': self.test_execution.total_tests,
                'passed': self.test_execution.passed,
                'failed': self.test_execution.failed,
                'skipped': self.test_execution.skipped,
                'errors': self.test_execution.errors,
                'duration': self.test_execution.duration,
                'exit_code': self.test_execution.exit_code,
                'build_successful': self.test_execution.build_successful,
                'passed_tests': self.test_execution.get_passed_tests(),
                'failed_tests': self.test_execution.get_failed_tests(),
                'skipped_tests': self.test_execution.get_skipped_tests(),
                'error_tests': self.test_execution.get_error_tests(),
                'detailed_test_results': [
                    {
                        'test_name': test.test_name,
                        'class_name': test.class_name,
                        'full_name': f"{test.class_name}.{test.test_name}",
                        'status': test.status,
                        'duration': test.duration,
                        'failure_message': test.failure_message,
                        'error_message': test.error_message
                    }
                    for test in self.test_execution.test_results
                ]
            }
        
        return result


class AndroidBenchEvaluator:
    """Main evaluation engine for Android-bench."""
    
    def __init__(self, output_dir: str = "android_evaluation_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize components
        self.container_manager = AndroidContainerManager()
        self.repo_manager = create_repository_manager()
        self.logger_manager = None
        
    def evaluate_dataset(
        self,
        dataset_path: str,
        predictions_path: str,
        run_id: str,
        instance_ids: Optional[List[str]] = None,
        max_instances: Optional[int] = None,
        max_workers: int = 1,
        log_level: str = "INFO"
    ) -> Dict[str, EvaluationResult]:
        """Evaluate dataset with model predictions."""
        
        # Setup logging
        self.logger_manager = setup_logging(str(self.output_dir), run_id, log_level)
        
        results = {}
        
        try:
            # Load dataset and predictions
            logger.info("Loading dataset and predictions...")
            instances, predictions = load_dataset_and_predictions(
                dataset_path,
                predictions_path,
                instance_ids=instance_ids,
                run_id=run_id,
                output_dir=str(self.output_dir),
                exclude_completed=True,
                exclude_empty_patches=True
            )
            
            # Filter instances if max_instances is specified
            if max_instances:
                instance_items = list(instances.items())[:max_instances]
                instances = dict(instance_items)
            
            logger.info(f"Evaluating {len(instances)} instances with {max_workers} workers")
            
            if max_workers == 1:
                # Sequential execution
                for i, (instance_id, instance) in enumerate(instances.items()):
                    logger.info(f"[{i+1}/{len(instances)}] Evaluating instance: {instance_id}")
                    
                    try:
                        prediction = predictions[instance_id]
                        result = self.evaluate_instance(instance, prediction)
                        results[instance_id] = result
                        
                        # Save intermediate result
                        self._save_instance_result(result)
                        
                        status = "✓" if result.success else "✗"
                        logger.info(f"{status} {instance_id}: {result.error_message if not result.success else 'Success'}")
                        
                    except Exception as e:
                        logger.error(f"Failed to evaluate {instance_id}: {e}")
                        logger.error(traceback.format_exc())
                        
                        results[instance_id] = EvaluationResult(
                            instance_id=instance_id,
                            model_name=predictions[instance_id].model_name,
                            success=False,
                            error_message=str(e)
                        )
            else:
                # Parallel execution
                results = self._evaluate_parallel(instances, predictions, max_workers)
            
            # Save final results
            self._save_final_results(results, run_id)
            
        except Exception as e:
            logger.error(f"Error during dataset evaluation: {e}")
            logger.error(traceback.format_exc())
        
        finally:
            # Cleanup resources
            logger.info("Cleaning up resources...")
            self.container_manager.cleanup_all()
            self.repo_manager.cleanup_all()
        
        return results
    
    def _evaluate_parallel(
        self,
        instances: Dict[str, TaskInstance],
        predictions: Dict[str, ModelPrediction],
        max_workers: int
    ) -> Dict[str, EvaluationResult]:
        """Evaluate instances in parallel."""
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_instance = {}
            for instance_id, instance in instances.items():
                prediction = predictions[instance_id]
                future = executor.submit(self.evaluate_instance, instance, prediction)
                future_to_instance[future] = instance_id
            
            # Collect results as they complete
            completed = 0
            total = len(instances)
            
            for future in as_completed(future_to_instance):
                instance_id = future_to_instance[future]
                completed += 1
                
                try:
                    result = future.result()
                    results[instance_id] = result
                    
                    # Save intermediate result
                    self._save_instance_result(result)
                    
                    status = "✓" if result.success else "✗"
                    logger.info(f"[{completed}/{total}] {status} {instance_id}: {result.error_message if not result.success else 'Success'}")
                    
                except Exception as e:
                    logger.error(f"Failed to evaluate {instance_id}: {e}")
                    logger.error(traceback.format_exc())
                    
                    results[instance_id] = EvaluationResult(
                        instance_id=instance_id,
                        model_name=predictions[instance_id].model_name,
                        success=False,
                        error_message=str(e)
                    )
        
        return results
    
    def evaluate_instance(self, instance: TaskInstance, prediction: ModelPrediction) -> EvaluationResult:
        """Evaluate a single instance."""
        instance_id = instance.instance_id
        result = EvaluationResult(
            instance_id=instance_id,
            model_name=prediction.model_name,
            success=False
        )
        
        start_time = time.time()
        repo_path = None
        
        # Setup instance logger
        if self.logger_manager:
            instance_logger = self.logger_manager.setup_instance_logger(
                instance_id, prediction.model_name
            )
        else:
            instance_logger = logger
        
        try:
            instance_logger.info(f"Starting evaluation for {instance_id}")
            
            # Step 1: Clone repository
            instance_logger.info("Cloning repository...")
            repo_path = self.repo_manager.clone_repository(
                instance_id, instance.repo, instance.base_commit
            )
            if not repo_path:
                result.error_message = "Failed to clone repository"
                return result
            result.repo_cloned = True
            
            # Step 2: Parse build configuration
            instance_logger.info("Parsing build configuration...")
            config_parser = AndroidConfigParser(repo_path)
            build_config = config_parser.parse_build_config()
            result.config_parsed = True
            instance_logger.info(f"Build configuration: {build_config}")
            
            # Step 3: Create executor and run evaluation
            instance_logger.info("Starting test execution...")
            executor = AndroidTestExecutor(self.container_manager, config_parser)
            
            try:
                test_result = executor.execute_instance(
                    instance_id, 
                    {
                        'base_commit': instance.base_commit,
                        'test_patch': instance.test_patch
                    },
                    {
                        'full_output': prediction.full_output
                    },
                    repo_path
                )
                
                result.test_execution = test_result
                result.container_created = True
                result.base_commit_checked_out = True
                
                # FIXED: Only mark patches as applied if they actually succeeded
                # We need to check the test_result to see if patches were actually applied
                # For now, we'll infer this from whether we got a successful test execution
                # or if the error message indicates patch failure
                
                if test_result.build_successful or test_result.total_tests > 0:
                    # If we got test results, assume patches were applied
                    result.test_patch_applied = True
                    result.prediction_patch_applied = True
                    result.success = True
                else:
                    # Check the error message to determine what failed
                    if "Failed to apply test patch" in test_result.raw_output:
                        result.test_patch_applied = False
                        result.prediction_patch_applied = False
                        result.error_message = "Failed to apply test patch"
                    elif "Failed to apply prediction patch" in test_result.raw_output:
                        result.test_patch_applied = True  # Test patch succeeded
                        result.prediction_patch_applied = False
                        result.error_message = "Failed to apply prediction patch"
                    elif "Failed to checkout base commit" in test_result.raw_output:
                        result.base_commit_checked_out = False
                        result.test_patch_applied = False
                        result.prediction_patch_applied = False
                        result.error_message = "Failed to checkout base commit"
                    else:
                        # Some other error occurred after patches were applied
                        result.test_patch_applied = True
                        result.prediction_patch_applied = True
                        result.error_message = "Test execution failed"
                    
                    result.success = False
                
            except Exception as executor_error:
                # Handle executor exceptions
                result.error_message = str(executor_error)
                result.success = False
                
                # Try to determine what step failed based on the error message
                error_str = str(executor_error).lower()
                if "clone" in error_str or "repository" in error_str:
                    result.repo_cloned = False
                elif "container" in error_str:
                    result.container_created = False
                elif "base commit" in error_str or "checkout" in error_str:
                    result.base_commit_checked_out = False
                    result.container_created = True
                elif "test patch" in error_str:
                    result.container_created = True
                    result.base_commit_checked_out = True
                    result.test_patch_applied = False
                elif "prediction patch" in error_str:
                    result.container_created = True
                    result.base_commit_checked_out = True
                    result.test_patch_applied = True
                    result.prediction_patch_applied = False
                else:
                    # Unknown error, assume we got far enough for basic setup
                    result.container_created = True
                    result.base_commit_checked_out = True
            
            # Save execution logs
            if self.logger_manager and result.test_execution:
                # Extract patches for saving
                prediction_patch = executor._extract_patch_from_prediction(prediction.full_output)
                
                self.logger_manager.save_execution_logs(
                    instance_id,
                    prediction.model_name,
                    result.test_execution.raw_output,
                    ""  # Container logs would be retrieved here if needed
                )
                
                self.logger_manager.save_patch_files(
                    instance_id,
                    prediction.model_name,
                    instance.test_patch,
                    prediction_patch
                )
                
                # Save detailed test results
                self.logger_manager.save_test_results(
                    instance_id,
                    prediction.model_name,
                    result.test_execution
                )
            
            if result.success:
                instance_logger.info(f"Evaluation completed successfully for {instance_id}")
                if result.test_execution:
                    instance_logger.info(f"Test results: {result.test_execution.passed}/{result.test_execution.total_tests} passed")
            else:
                instance_logger.error(f"Evaluation failed for {instance_id}: {result.error_message}")
            
        except Exception as e:
            result.error_message = str(e)
            instance_logger.error(f"Error evaluating {instance_id}: {e}")
            instance_logger.error(traceback.format_exc())
        
        finally:
            result.total_duration = time.time() - start_time
            
            # Cleanup repository
            if repo_path:
                self.repo_manager.cleanup_repository(instance_id)
        
        return result
    
    def _save_instance_result(self, result: EvaluationResult):
        """Save individual instance result."""
        if not self.logger_manager:
            return
            
        instance_dir = self.logger_manager.get_instance_log_dir(
            result.instance_id, result.model_name
        )
        instance_dir.mkdir(exist_ok=True, parents=True)
        
        result_file = instance_dir / "evaluation_result.json"
        with open(result_file, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
    
    def _save_final_results(self, results: Dict[str, EvaluationResult], run_id: str):
        """Save final summary results."""
        successful = [r for r in results.values() if r.success]
        failed = [r for r in results.values() if not r.success]
        
        # Calculate test statistics
        total_tests_run = sum(
            r.test_execution.total_tests for r in successful 
            if r.test_execution
        )
        total_tests_passed = sum(
            r.test_execution.passed for r in successful 
            if r.test_execution
        )
        total_tests_failed = sum(
            r.test_execution.failed for r in successful 
            if r.test_execution
        )
        
        # Calculate average durations
        avg_duration = sum(r.total_duration for r in successful) / len(successful) if successful else 0
        
        summary = {
            'run_id': run_id,
            'total_instances': len(results),
            'successful': len(successful),
            'failed': len(failed),
            'success_rate': len(successful) / len(results) * 100 if results else 0,
            
            'test_statistics': {
                'total_tests_run': total_tests_run,
                'total_tests_passed': total_tests_passed,
                'total_tests_failed': total_tests_failed,
                'test_pass_rate': total_tests_passed / total_tests_run * 100 if total_tests_run > 0 else 0,
            },
            
            'performance_metrics': {
                'avg_duration_seconds': avg_duration,
                'total_duration_hours': sum(r.total_duration for r in results.values()) / 3600,
            },
            
            'results': {k: v.to_dict() for k, v in results.items()}
        }
        
        # Save detailed summary
        summary_file = self.output_dir / run_id / "evaluation_summary.json"
        summary_file.parent.mkdir(exist_ok=True, parents=True)
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        # Save readable report
        report_lines = [
            "Android-Bench Evaluation Report",
            "=" * 40,
            f"Run ID: {run_id}",
            f"Total Instances: {summary['total_instances']}",
            f"Successful: {summary['successful']}",
            f"Failed: {summary['failed']}",
            f"Success Rate: {summary['success_rate']:.1f}%",
            "",
            "Test Statistics:",
            "-" * 20,
            f"Total Tests Run: {total_tests_run}",
            f"Total Tests Passed: {total_tests_passed}",
            f"Total Tests Failed: {total_tests_failed}",
            f"Test Pass Rate: {summary['test_statistics']['test_pass_rate']:.1f}%",
            "",
            "Performance Metrics:",
            "-" * 20,
            f"Average Duration: {avg_duration:.1f}s",
            f"Total Runtime: {summary['performance_metrics']['total_duration_hours']:.2f}h",
            "",
            "Failed Instances:",
            "-" * 17,
        ]
        
        for result in failed:
            report_lines.append(f"  - {result.instance_id}: {result.error_message}")
        
        report_file = self.output_dir / run_id / "evaluation_report.txt"
        with open(report_file, 'w') as f:
            f.write('\n'.join(report_lines))
        
        logger.info(f"Evaluation complete: {summary['successful']}/{summary['total_instances']} successful")
        logger.info(f"Test pass rate: {summary['test_statistics']['test_pass_rate']:.1f}%")
        logger.info(f"Results saved to: {self.output_dir / run_id}")


def main():
    """Main entry point for Android-bench evaluator."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Android-bench evaluation engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate entire dataset
  python evaluator.py dataset.jsonl predictions.jsonl --run-id my_run
  
  # Evaluate specific instances
  python evaluator.py dataset.jsonl predictions.jsonl --run-id my_run --instance-ids "AntennaPod__AntennaPod-5644"
  
  # Evaluate first 5 instances
  python evaluator.py dataset.jsonl predictions.jsonl --run-id my_run --max-instances 5
  
  # Parallel evaluation
  python evaluator.py dataset.jsonl predictions.jsonl --run-id my_run --max-workers 4
        """
    )
    
    parser.add_argument("dataset_path", help="Path to dataset JSONL file")
    parser.add_argument("predictions_path", help="Path to predictions JSONL file")
    parser.add_argument("--run-id", required=True, help="Unique run identifier")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to evaluate")
    parser.add_argument("--max-instances", type=int, help="Maximum number of instances to evaluate")
    parser.add_argument("--max-workers", type=int, default=1, help="Number of parallel workers")
    parser.add_argument("--output-dir", default="android_evaluation_results", 
                       help="Output directory for results")
    parser.add_argument("--log-level", default="INFO", 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not Path(args.dataset_path).exists():
        print(f"Error: Dataset file not found: {args.dataset_path}")
        return 1
    
    if not Path(args.predictions_path).exists():
        print(f"Error: Predictions file not found: {args.predictions_path}")
        return 1
    
    # Create evaluator
    evaluator = AndroidBenchEvaluator(args.output_dir)
    
    try:
        # Run evaluation
        results = evaluator.evaluate_dataset(
            args.dataset_path,
            args.predictions_path,
            args.run_id,
            instance_ids=args.instance_ids,
            max_instances=args.max_instances,
            max_workers=args.max_workers,
            log_level=args.log_level
        )
        
        # Print summary
        successful = len([r for r in results.values() if r.success])
        total = len(results)
        success_rate = successful / total * 100 if total > 0 else 0
        
        print(f"\nEvaluation Summary:")
        print(f"  Total: {total}")
        print(f"  Successful: {successful}")
        print(f"  Failed: {total - successful}")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Results saved to: {args.output_dir}/{args.run_id}")
        
        return 0 if successful > 0 else 1
        
    except KeyboardInterrupt:
        print("\nEvaluation interrupted by user")
        return 1
    except Exception as e:
        print(f"Evaluation failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())