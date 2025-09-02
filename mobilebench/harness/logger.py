#!/usr/bin/env python3
"""
Logging configuration and utilities for Android-bench evaluation.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


class AndroidBenchLogger:
    """Configures and manages logging for Android-bench evaluation."""
    
    def __init__(self, output_dir: str, run_id: str):
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.log_dir = self.output_dir / run_id / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup main logger
        self._setup_main_logger()
    
    def _setup_main_logger(self):
        """Setup the main application logger."""
        # Create main log file
        main_log_file = self.log_dir / "android_bench.log"
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Remove any existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # File handler (detailed)
        file_handler = logging.FileHandler(main_log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
        
        # Console handler (simpler)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)
        
        logging.info(f"Logging initialized - logs will be saved to {self.log_dir}")
    
    def setup_instance_logger(self, instance_id: str, model_name: str) -> logging.Logger:
        """Setup a dedicated logger for a specific instance."""
        # Create instance-specific log directory
        instance_log_dir = self.output_dir / self.run_id / model_name.replace("/", "__") / instance_id
        instance_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create instance logger
        logger_name = f"android_bench.{instance_id}"
        instance_logger = logging.getLogger(logger_name)
        instance_logger.setLevel(logging.DEBUG)
        
        # Remove any existing handlers for this logger
        for handler in instance_logger.handlers[:]:
            instance_logger.removeHandler(handler)
        
        # Create instance log file
        instance_log_file = instance_log_dir / "instance.log"
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        
        # File handler for instance
        file_handler = logging.FileHandler(instance_log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        instance_logger.addHandler(file_handler)
        
        # Don't propagate to parent logger to avoid duplication
        instance_logger.propagate = False
        
        return instance_logger
    
    def save_test_results(self, instance_id: str, model_name: str, 
                         test_execution_result) -> str:
        """Save detailed test results to a structured file."""
        # Import json at the top of the function since it's used here
        import json
        
        instance_log_dir = self.output_dir / self.run_id / model_name.replace("/", "__") / instance_id
        instance_log_dir.mkdir(parents=True, exist_ok=True)
        instance_log_dir = self.output_dir / self.run_id / model_name.replace("/", "__") / instance_id
        instance_log_dir.mkdir(parents=True, exist_ok=True)
        
        if not test_execution_result:
            return ""
        
        # Create detailed test results
        test_results_data = {
            'summary': {
                'total_tests': test_execution_result.total_tests,
                'passed': test_execution_result.passed,
                'failed': test_execution_result.failed,
                'skipped': test_execution_result.skipped,
                'errors': test_execution_result.errors,
                'duration': test_execution_result.duration,
                'exit_code': test_execution_result.exit_code,
                'build_successful': test_execution_result.build_successful
            },
            'test_lists': {
                'passed_tests': test_execution_result.get_passed_tests(),
                'failed_tests': test_execution_result.get_failed_tests(),
                'skipped_tests': test_execution_result.get_skipped_tests(),
                'error_tests': test_execution_result.get_error_tests()
            },
            'detailed_results': [
                {
                    'test_name': test.test_name,
                    'class_name': test.class_name,
                    'full_name': f"{test.class_name}.{test.test_name}",
                    'status': test.status,
                    'duration': test.duration,
                    'failure_message': test.failure_message,
                    'error_message': test.error_message
                }
                for test in test_execution_result.test_results
            ]
        }
        
        # Save as JSON
        test_results_file = instance_log_dir / "test_results.json"
        with open(test_results_file, 'w', encoding='utf-8') as f:
            json.dump(test_results_data, f, indent=2)
        
        # Save human-readable test summary
        summary_lines = [
            f"Test Execution Summary for {instance_id}",
            "=" * 50,
            f"Total Tests: {test_execution_result.total_tests}",
            f"Passed: {test_execution_result.passed}",
            f"Failed: {test_execution_result.failed}",
            f"Skipped: {test_execution_result.skipped}",
            f"Errors: {test_execution_result.errors}",
            f"Duration: {test_execution_result.duration:.2f}s",
            f"Build Successful: {test_execution_result.build_successful}",
            "",
        ]
        
        # Add passed tests
        passed_tests = test_execution_result.get_passed_tests()
        if passed_tests:
            summary_lines.extend([
                f"✅ Passed Tests ({len(passed_tests)}):",
                "-" * 30,
            ])
            for test in passed_tests:
                summary_lines.append(f"  ✓ {test}")
            summary_lines.append("")
        
        # Add failed tests
        failed_tests = test_execution_result.get_failed_tests()
        if failed_tests:
            summary_lines.extend([
                f"❌ Failed Tests ({len(failed_tests)}):",
                "-" * 30,
            ])
            for test in failed_tests:
                # Find the detailed test for failure message
                test_detail = next(
                    (t for t in test_execution_result.test_results 
                     if f"{t.class_name}.{t.test_name}" == test), 
                    None
                )
                summary_lines.append(f"  ✗ {test}")
                if test_detail and test_detail.failure_message:
                    # Truncate long failure messages
                    failure_msg = test_detail.failure_message[:200]
                    if len(test_detail.failure_message) > 200:
                        failure_msg += "..."
                    summary_lines.append(f"    → {failure_msg}")
            summary_lines.append("")
        
        # Add skipped tests
        skipped_tests = test_execution_result.get_skipped_tests()
        if skipped_tests:
            summary_lines.extend([
                f"⏭️ Skipped Tests ({len(skipped_tests)}):",
                "-" * 30,
            ])
            for test in skipped_tests:
                summary_lines.append(f"  ⏭ {test}")
            summary_lines.append("")
        
        # Add error tests
        error_tests = test_execution_result.get_error_tests()
        if error_tests:
            summary_lines.extend([
                f"💥 Tests with Errors ({len(error_tests)}):",
                "-" * 35,
            ])
            for test in error_tests:
                summary_lines.append(f"  💥 {test}")
            summary_lines.append("")
        
        test_summary_file = instance_log_dir / "test_summary.txt"
        with open(test_summary_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(summary_lines))
        
    def save_execution_logs(self, instance_id: str, model_name: str, 
                           test_output: str, container_logs: str = ""):
        """Save test execution logs for an instance."""
        instance_log_dir = self.output_dir / self.run_id / model_name.replace("/", "__") / instance_id
        instance_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Save test output
        test_output_file = instance_log_dir / "test_output.txt"
        with open(test_output_file, 'w', encoding='utf-8') as f:
            f.write(test_output)
        
        # Save container logs if available
        if container_logs:
            container_logs_file = instance_log_dir / "container.log"
            with open(container_logs_file, 'w', encoding='utf-8') as f:
                f.write(container_logs)
    
    def save_patch_files(self, instance_id: str, model_name: str, 
                        test_patch: str, prediction_patch: str):
        """Save patch files for debugging."""
        instance_log_dir = self.output_dir / self.run_id / model_name.replace("/", "__") / instance_id
        instance_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Save test patch
        test_patch_file = instance_log_dir / "test.patch"
        with open(test_patch_file, 'w', encoding='utf-8') as f:
            f.write(test_patch)
        
        # Save prediction patch
        prediction_patch_file = instance_log_dir / "prediction.patch"
        with open(prediction_patch_file, 'w', encoding='utf-8') as f:
            f.write(prediction_patch)
    
    def get_instance_log_dir(self, instance_id: str, model_name: str) -> Path:
        """Get the log directory for a specific instance."""
        return self.output_dir / self.run_id / model_name.replace("/", "__") / instance_id


def setup_logging(output_dir: str, run_id: str, log_level: str = "INFO") -> AndroidBenchLogger:
    """
    Setup logging for Android-bench evaluation.
    
    Args:
        output_dir: Base output directory
        run_id: Unique run identifier
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    
    Returns:
        AndroidBenchLogger instance
    """
    # Validate log level
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    
    # Create logger instance
    logger_manager = AndroidBenchLogger(output_dir, run_id)
    
    # Set the console handler level
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
            handler.setLevel(numeric_level)
    
    return logger_manager


if __name__ == "__main__":
    # Test the logging setup
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as temp_dir:
        logger_manager = setup_logging(temp_dir, "test_run", "DEBUG")
        
        # Test main logger
        logging.info("This is a test info message")
        logging.debug("This is a test debug message")
        logging.warning("This is a test warning message")
        
        # Test instance logger
        instance_logger = logger_manager.setup_instance_logger("test_instance", "test_model")
        instance_logger.info("This is an instance-specific message")
        
        # Test saving logs
        logger_manager.save_execution_logs(
            "test_instance", 
            "test_model", 
            "Test output", 
            "Container logs"
        )
        
        print(f"Logs saved to: {logger_manager.log_dir}")
        print(f"Instance logs saved to: {logger_manager.get_instance_log_dir('test_instance', 'test_model')}")