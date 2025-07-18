#!/usr/bin/env python3

"""
Mobile-Bench Main Evaluator
Main evaluation script that coordinates all components of the mobile-bench system.
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Any
import docker

# Import mobile-bench modules
from mobile_bench_utils import (
    AndroidProjectAnalyzer, AndroidTestResultParser, PatchValidator,
    ContainerManager, ReportGenerator, setup_logging, validate_environment
)
from mobile_bench_test_spec import (
    AndroidTestSpec, AndroidTestSpecBuilder, AndroidTestSpecValidator,
    AndroidExecutionPlan, AndroidTestSpecManager
)
from mobile_bench_grading import (
    AndroidEvaluationGrader, MobileBenchGradingReport, EvaluationResult,
    EvaluationStatus, MobileBenchValidator
)


class MobileBenchEvaluator:
    """Main evaluator class that orchestrates the entire evaluation process"""
    
    def __init__(self, 
                 max_workers: int = 4,
                 timeout: int = 1800,
                 force_rebuild: bool = False,
                 cache_level: str = "none",
                 log_level: str = "INFO",
                 report_dir: Optional[Path] = None):
        
        self.max_workers = max_workers
        self.timeout = timeout
        self.force_rebuild = force_rebuild
        self.cache_level = cache_level
        self.report_dir = report_dir or Path("./mobile_bench_reports")
        
        # Setup logging
        setup_logging(log_level)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Setup directories
        self.report_dir.mkdir(exist_ok=True)
        self.log_dir = Path("./mobile_bench_logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # Validate environment
        validate_environment()
        
        # Initialize components
        self.docker_client = docker.from_env()
        self.container_manager = ContainerManager(self.docker_client)
        self.spec_builder = AndroidTestSpecBuilder()
        self.spec_manager = AndroidTestSpecManager()
        self.grader = AndroidEvaluationGrader()
        self.report_generator = MobileBenchGradingReport()
        
        # Pull Docker image
        self._pull_android_image()
    
    def _pull_android_image(self):
        """Pull the Android build Docker image if it doesn't exist"""
        image_name = "mingc/android-build-box:latest"
        
        try:
            # Check if image already exists
            try:
                existing_image = self.docker_client.images.get(image_name)
                self.logger.info(f"Docker image {image_name} already exists (ID: {existing_image.id[:12]})")
                return
            except docker.errors.ImageNotFound:
                # Image doesn't exist, proceed with pull
                self.logger.info(f"Docker image {image_name} not found locally")
            
            # Pull the image
            self.logger.info(f"Pulling Docker image: {image_name} (this may take several minutes)")
            self.docker_client.images.pull(image_name)
            self.logger.info("Docker image pulled successfully")
            
        except Exception as e:
            self.logger.warning(f"Failed to pull Docker image: {e}")
    
    def load_dataset(self, dataset_path: str) -> List[Dict[str, Any]]:
        """Load dataset from JSON or JSONL file"""
        dataset_path = Path(dataset_path)
        
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
        
        self.logger.info(f"Loading dataset from {dataset_path}")
        
        if dataset_path.suffix == '.json':
            with open(dataset_path, 'r') as f:
                dataset = json.load(f)
        elif dataset_path.suffix == '.jsonl':
            dataset = []
            with open(dataset_path, 'r') as f:
                for line in f:
                    if line.strip():
                        dataset.append(json.loads(line.strip()))
        else:
            raise ValueError("Dataset must be a .json or .jsonl file")
        
        self.logger.info(f"Loaded {len(dataset)} instances from dataset")
        return dataset
    
    def load_predictions(self, predictions_path: str) -> Dict[str, Dict[str, Any]]:
        """Load predictions from JSON or JSONL file"""
        predictions_path = Path(predictions_path)
        
        if not predictions_path.exists():
            raise FileNotFoundError(f"Predictions file not found: {predictions_path}")
        
        self.logger.info(f"Loading predictions from {predictions_path}")
        
        predictions = {}
        
        if predictions_path.suffix == '.json':
            with open(predictions_path, 'r') as f:
                pred_data = json.load(f)
                if isinstance(pred_data, dict):
                    predictions = pred_data
                else:
                    predictions = {pred['instance_id']: pred for pred in pred_data}
        elif predictions_path.suffix == '.jsonl':
            with open(predictions_path, 'r') as f:
                for line in f:
                    if line.strip():
                        pred = json.loads(line.strip())
                        predictions[pred['instance_id']] = pred
        
        self.logger.info(f"Loaded predictions for {len(predictions)} instances")
        return predictions
    
    def create_test_specifications(self, 
                                 instances: List[Dict[str, Any]], 
                                 predictions: Dict[str, Dict[str, Any]]) -> List[AndroidTestSpec]:
        """Create test specifications from instances and predictions"""
        self.logger.info("Creating test specifications...")
        
        valid_specs = []
        
        for instance in instances:
            instance_id = instance['instance_id']
            
            if instance_id not in predictions:
                self.logger.warning(f"No prediction found for instance {instance_id}")
                continue
            
            try:
                # Build test specification
                spec = self.spec_builder.build_from_instance(instance, predictions[instance_id])
                
                # Validate specification
                is_valid, errors = AndroidTestSpecValidator.validate(spec)
                if not is_valid:
                    self.logger.error(f"Invalid spec for {instance_id}: {errors}")
                    continue
                
                # Validate patch
                if spec.patch:
                    patch_valid, patch_error = PatchValidator.validate_patch(spec.patch)
                    if not patch_valid:
                        self.logger.error(f"Invalid patch for {instance_id}: {patch_error}")
                        continue
                    
                    # Preprocess patch
                    spec.patch = PatchValidator.preprocess_patch(spec.patch)
                
                valid_specs.append(spec)
                
                # Save specification
                self.spec_manager.save_spec(spec)
                
            except Exception as e:
                self.logger.error(f"Failed to create spec for {instance_id}: {e}")
        
        self.logger.info(f"Created {len(valid_specs)} valid test specifications")
        return valid_specs
    
    def run_single_evaluation(self, test_spec: AndroidTestSpec) -> EvaluationResult:
        """Run evaluation for a single test specification"""
        self.logger.info(f"Starting evaluation for {test_spec.instance_id}")
        
        start_time = time.time()
        result = EvaluationResult(
            instance_id=test_spec.instance_id,
            status=EvaluationStatus.CONTAINER_ERROR
        )
        
        container = None
        execution_log = []
        
        try:
            # Create container
            container = self.container_manager.create_test_container(test_spec.instance_id)
            container.start()
            
            execution_log.append("Container started successfully")
            
            # Create execution plan
            plan = AndroidExecutionPlan(test_spec)
            
            # Phase 1: Setup
            setup_start = time.time()
            setup_script = plan.generate_setup_script()
            exit_code, output = self.container_manager.execute_with_timeout(
                container, f"bash -c '{setup_script}'", timeout=300
            )
            
            if exit_code != 0:
                result.error_message = f"Setup failed: {output}"
                execution_log.append(f"Setup failed with exit code {exit_code}")
                return result
            
            result.patch_time = time.time() - setup_start
            execution_log.append("Setup completed successfully")
            
            # Phase 2: Apply patch
            patch_start = time.time()
            if test_spec.patch:
                patch_script = plan.generate_patch_script()
                exit_code, output = self.container_manager.execute_with_timeout(
                    container, f"bash -c '{patch_script}'", timeout=300, workdir=test_spec.workspace_path
                )
                
                if exit_code != 0:
                    result.status = EvaluationStatus.PATCH_APPLY_FAIL
                    result.error_message = f"Patch application failed: {output}"
                    execution_log.append("PATCH_APPLY_FAIL")
                    return result
                
                result.patch_applied = True
                execution_log.append("PATCH_APPLY_SUCCESS")
            else:
                result.patch_applied = True
                execution_log.append("No patch to apply")
            
            result.patch_time += time.time() - patch_start
            
            # Phase 3: Build
            build_start = time.time()
            build_script = plan.generate_build_script()
            exit_code, output = self.container_manager.execute_with_timeout(
                container, f"bash -c '{build_script}'", timeout=self.timeout, workdir=test_spec.workspace_path
            )
            
            result.build_time = time.time() - build_start
            
            if exit_code != 0:
                result.status = EvaluationStatus.BUILD_FAIL
                result.error_message = f"Build failed: {output}"
                execution_log.append("BUILD_FAIL")
                return result
            
            result.build_successful = True
            execution_log.append("BUILD_SUCCESS")
            
            # Phase 4: Run tests
            test_start = time.time()
            test_script = plan.generate_test_script()
            exit_code, output = self.container_manager.execute_with_timeout(
                container, f"bash -c '{test_script}'", timeout=self.timeout, workdir=test_spec.workspace_path
            )
            
            result.test_time = time.time() - test_start
            execution_log.append(f"Tests completed with exit code {exit_code}")
            
            # Phase 5: Grade results
            grading_result = self.grader.grade_evaluation(
                container, 
                test_spec.workspace_path,
                set(test_spec.expected_pass_tests),
                set(test_spec.expected_fail_tests),
                "\n".join(execution_log)
            )
            
            # Merge grading results
            result.test_suites = grading_result.test_suites
            result.tests_executed = grading_result.tests_executed
            result.resolved = grading_result.resolved
            result.resolution_details = grading_result.resolution_details
            
            # Determine final status
            if result.tests_executed:
                if result.failed_tests == 0 and result.error_tests == 0:
                    result.status = EvaluationStatus.TEST_SUCCESS
                else:
                    result.status = EvaluationStatus.TEST_FAIL
            else:
                result.status = EvaluationStatus.TEST_FAIL
            
            execution_log.append(f"Final status: {result.status.value}")
            
        except Exception as e:
            result.status = EvaluationStatus.CONTAINER_ERROR
            result.error_message = str(e)
            execution_log.append(f"CONTAINER_ERROR: {e}")
            self.logger.error(f"Error evaluating {test_spec.instance_id}: {e}")
            
        finally:
            result.total_execution_time = time.time() - start_time
            result.error_logs = execution_log
            
            # Cleanup container
            if container:
                self.container_manager.cleanup_container(container)
        
        self.logger.info(f"Completed evaluation for {test_spec.instance_id}: {result.status.value}")
        return result
    
    def run_batch_evaluation(self, test_specs: List[AndroidTestSpec]) -> List[EvaluationResult]:
        """Run evaluation for multiple test specifications in parallel"""
        self.logger.info(f"Starting batch evaluation of {len(test_specs)} instances with {self.max_workers} workers")
        
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all jobs
            future_to_spec = {
                executor.submit(self.run_single_evaluation, spec): spec 
                for spec in test_specs
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                try:
                    result = future.result()
                    results.append(result)
                    self.logger.info(f"Completed {spec.instance_id}: {result.status.value}")
                except Exception as e:
                    self.logger.error(f"Failed to evaluate {spec.instance_id}: {e}")
                    error_result = EvaluationResult(
                        instance_id=spec.instance_id,
                        status=EvaluationStatus.CONTAINER_ERROR,
                        error_message=str(e)
                    )
                    results.append(error_result)
        
        self.logger.info(f"Batch evaluation completed. {len(results)} results collected.")
        return results
    
    def generate_reports(self, results: List[EvaluationResult], run_id: str) -> Dict[str, Path]:
        """Generate comprehensive reports"""
        self.logger.info("Generating evaluation reports...")
        
        report_paths = {}
        
        # Generate aggregate report
        aggregate_report = self.report_generator.generate_aggregate_report(results)
        aggregate_report['run_id'] = run_id
        aggregate_report['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Save JSON report
        json_path = self.report_dir / f"{run_id}_aggregate_report.json"
        self.report_generator.save_report(aggregate_report, json_path, 'json')
        report_paths['json'] = json_path
        
        # Generate HTML report
        html_path = self.report_dir / f"{run_id}_report.html"
        ReportGenerator.generate_html_report(aggregate_report, str(html_path))
        report_paths['html'] = html_path
        
        # Generate CSV report
        csv_path = self.report_dir / f"{run_id}_results.csv"
        ReportGenerator.generate_csv_report(aggregate_report, str(csv_path))
        report_paths['csv'] = csv_path
        
        # Generate individual instance reports
        instance_reports_dir = self.report_dir / f"{run_id}_instances"
        instance_reports_dir.mkdir(exist_ok=True)
        
        for result in results:
            instance_report = self.report_generator.generate_instance_report(result)
            instance_path = instance_reports_dir / f"{result.instance_id}.json"
            with open(instance_path, 'w') as f:
                json.dump(instance_report, f, indent=2)
        
        report_paths['instances'] = instance_reports_dir
        
        self.logger.info(f"Reports generated and saved to {self.report_dir}")
        return report_paths
    
    def print_summary(self, results: List[EvaluationResult], run_id: str):
        """Print evaluation summary"""
        if not results:
            print("No results to summarize")
            return
        
        total = len(results)
        patch_success = sum(1 for r in results if r.patch_applied)
        build_success = sum(1 for r in results if r.build_successful)
        test_success = sum(1 for r in results if r.status == EvaluationStatus.TEST_SUCCESS)
        resolved = sum(1 for r in results if r.resolved)
        
        total_tests = sum(r.total_tests for r in results)
        total_passed = sum(r.passed_tests for r in results)
        total_failed = sum(r.failed_tests for r in results)
        
        avg_time = sum(r.total_execution_time for r in results) / total
        
        print("\n" + "="*80)
        print("MOBILE-BENCH EVALUATION SUMMARY")
        print("="*80)
        print(f"Run ID: {run_id}")
        print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("-"*80)
        print(f"Total Instances: {total}")
        print(f"Patch Success: {patch_success} ({patch_success/total:.1%})")
        print(f"Build Success: {build_success} ({build_success/total:.1%})")
        print(f"Test Success: {test_success} ({test_success/total:.1%})")
        print(f"Issues Resolved: {resolved} ({resolved/total:.1%})")
        print("-"*80)
        print(f"Total Tests Executed: {total_tests}")
        print(f"Tests Passed: {total_passed}")
        print(f"Tests Failed: {total_failed}")
        print(f"Overall Test Pass Rate: {total_passed/total_tests:.1%}" if total_tests > 0 else "No tests executed")
        print("-"*80)
        print(f"Average Execution Time: {avg_time:.1f} seconds")
        print("="*80)
    
    def run_evaluation(self,
                      dataset_path: str,
                      predictions_path: str,
                      run_id: str,
                      instance_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run complete evaluation pipeline"""
        
        self.logger.info(f"Starting Mobile-Bench evaluation: {run_id}")
        
        # Load data
        instances = self.load_dataset(dataset_path)
        predictions = self.load_predictions(predictions_path)
        
        # Filter by instance IDs if provided
        if instance_ids:
            instances = [inst for inst in instances if inst['instance_id'] in instance_ids]
            self.logger.info(f"Filtered to {len(instances)} instances based on provided IDs")
        
        # Create test specifications
        test_specs = self.create_test_specifications(instances, predictions)
        
        if not test_specs:
            raise ValueError("No valid test specifications created")
        
        # Run evaluations
        results = self.run_batch_evaluation(test_specs)
        
        # Validate results
        for result in results:
            is_valid, errors = MobileBenchValidator.validate_result(result)
            if not is_valid:
                self.logger.warning(f"Invalid result for {result.instance_id}: {errors}")
        
        # Generate reports
        report_paths = self.generate_reports(results, run_id)
        
        # Print summary
        self.print_summary(results, run_id)
        
        return {
            'run_id': run_id,
            'results': results,
            'report_paths': report_paths,
            'summary': {
                'total_instances': len(results),
                'patch_success_rate': sum(1 for r in results if r.patch_applied) / len(results),
                'build_success_rate': sum(1 for r in results if r.build_successful) / len(results),
                'test_success_rate': sum(1 for r in results if r.status == EvaluationStatus.TEST_SUCCESS) / len(results),
                'resolution_rate': sum(1 for r in results if r.resolved) / len(results)
            }
        }


def main():
    """Main entry point for the mobile-bench evaluator"""
    parser = argparse.ArgumentParser(
        description="Mobile-Bench Evaluation Harness for Android Projects",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Required arguments
    parser.add_argument(
        "--dataset_path",
        required=True,
        help="Path to dataset JSON/JSONL file containing test instances"
    )
    parser.add_argument(
        "--predictions_path", 
        required=True,
        help="Path to predictions JSON/JSONL file containing model patches"
    )
    parser.add_argument(
        "--run_id",
        required=True,
        help="Unique identifier for this evaluation run"
    )
    
    # Optional filtering
    parser.add_argument(
        "--instance_ids",
        nargs="+",
        help="Specific instance IDs to evaluate (space separated)"
    )
    
    # Execution configuration
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of parallel workers"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Timeout per instance in seconds"
    )
    parser.add_argument(
        "--force_rebuild",
        action="store_true",
        help="Force rebuild of Docker images"
    )
    parser.add_argument(
        "--cache_level",
        choices=["none", "base", "env", "instance"],
        default="none",
        help="Cache level for Docker operations"
    )
    
    # Logging and output
    parser.add_argument(
        "--log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level"
    )
    parser.add_argument(
        "--report_dir",
        type=Path,
        default=Path("./mobile_bench_reports"),
        help="Directory to save evaluation reports"
    )
    
    # Advanced options
    parser.add_argument(
        "--validate_only",
        action="store_true",
        help="Only validate test specifications without running evaluations"
    )
    parser.add_argument(
        "--resume",
        help="Resume evaluation from a previous run (provide run_id)"
    )
    
    args = parser.parse_args()
    
    try:
        # Create evaluator
        evaluator = MobileBenchEvaluator(
            max_workers=args.max_workers,
            timeout=args.timeout,
            force_rebuild=args.force_rebuild,
            cache_level=args.cache_level,
            log_level=args.log_level,
            report_dir=args.report_dir
        )
        
        if args.validate_only:
            # Validation mode
            print("Running in validation-only mode...")
            instances = evaluator.load_dataset(args.dataset_path)
            predictions = evaluator.load_predictions(args.predictions_path)
            
            if args.instance_ids:
                instances = [inst for inst in instances if inst['instance_id'] in args.instance_ids]
            
            test_specs = evaluator.create_test_specifications(instances, predictions)
            print(f"Successfully validated {len(test_specs)} test specifications")
            
        elif args.resume:
            # Resume mode
            print(f"Resuming evaluation from run: {args.resume}")
            # Implementation for resume functionality would go here
            # This would load previous state and continue evaluation
            print("Resume functionality not yet implemented")
            
        else:
            # Normal evaluation mode
            evaluation_result = evaluator.run_evaluation(
                dataset_path=args.dataset_path,
                predictions_path=args.predictions_path,
                run_id=args.run_id,
                instance_ids=args.instance_ids
            )
            
            print(f"\nEvaluation completed successfully!")
            print(f"Run ID: {evaluation_result['run_id']}")
            print(f"Reports available at: {args.report_dir}")
            
            # Print key metrics
            summary = evaluation_result['summary']
            print(f"\nKey Metrics:")
            print(f"  - Resolution Rate: {summary['resolution_rate']:.1%}")
            print(f"  - Patch Success Rate: {summary['patch_success_rate']:.1%}")
            print(f"  - Build Success Rate: {summary['build_success_rate']:.1%}")
            print(f"  - Test Success Rate: {summary['test_success_rate']:.1%}")
            
    except KeyboardInterrupt:
        print("\nEvaluation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Evaluation failed: {e}")
        logging.error(f"Evaluation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()