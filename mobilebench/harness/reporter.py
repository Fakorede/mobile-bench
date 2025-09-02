#!/usr/bin/env python3
"""
Results reporting and analysis utilities for Android-bench.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TestStatistics:
    """Test execution statistics."""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    pass_rate: float
    passed_tests: List[str]
    failed_tests: List[str]
    skipped_tests: List[str]
    error_tests: List[str]
    
    @classmethod
    def from_result(cls, result_dict: dict):
        test_exec = result_dict.get('test_execution', {})
        total = test_exec.get('total_tests', 0)
        passed = test_exec.get('passed', 0)
        failed = test_exec.get('failed', 0)
        skipped = test_exec.get('skipped', 0)
        errors = test_exec.get('errors', 0)
        
        pass_rate = (passed / total * 100) if total > 0 else 0
        
        # Get test lists
        passed_tests = test_exec.get('passed_tests', [])
        failed_tests = test_exec.get('failed_tests', [])
        skipped_tests = test_exec.get('skipped_tests', [])
        error_tests = test_exec.get('error_tests', [])
        
        return cls(
            total, passed, failed, skipped, errors, pass_rate,
            passed_tests, failed_tests, skipped_tests, error_tests
        )


@dataclass
class InstanceResult:
    """Single instance evaluation result."""
    instance_id: str
    model_name: str
    success: bool
    error_message: str
    duration: float
    test_stats: Optional[TestStatistics]
    
    @classmethod
    def from_dict(cls, result_dict: dict):
        test_stats = None
        if result_dict.get('test_execution'):
            test_stats = TestStatistics.from_result(result_dict)
        
        return cls(
            instance_id=result_dict['instance_id'],
            model_name=result_dict['model_name'],
            success=result_dict['success'],
            error_message=result_dict.get('error_message', ''),
            duration=result_dict.get('total_duration', 0),
            test_stats=test_stats
        )


class AndroidBenchReporter:
    """Generates reports and analysis for Android-bench evaluation results."""
    
    def __init__(self, results_dir: str):
        self.results_dir = Path(results_dir)
        if not self.results_dir.exists():
            raise FileNotFoundError(f"Results directory not found: {results_dir}")
    
    def load_run_results(self, run_id: str) -> Dict[str, InstanceResult]:
        """Load results for a specific run."""
        run_dir = self.results_dir / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        
        summary_file = run_dir / "evaluation_summary.json"
        if not summary_file.exists():
            raise FileNotFoundError(f"Summary file not found: {summary_file}")
        
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        results = {}
        for instance_id, result_data in summary['results'].items():
            results[instance_id] = InstanceResult.from_dict(result_data)
        
        return results
    
    def list_available_runs(self) -> List[str]:
        """List all available run IDs."""
        runs = []
        for item in self.results_dir.iterdir():
            if item.is_dir() and (item / "evaluation_summary.json").exists():
                runs.append(item.name)
        return sorted(runs)
    
    def generate_summary_report(self, run_id: str) -> str:
        """Generate a comprehensive summary report for a run."""
        results = self.load_run_results(run_id)
        
        # Basic statistics
        total_instances = len(results)
        successful = len([r for r in results.values() if r.success])
        failed = total_instances - successful
        success_rate = (successful / total_instances * 100) if total_instances > 0 else 0
        
        # Test statistics (only for successful runs)
        successful_results = [r for r in results.values() if r.success and r.test_stats]
        
        if successful_results:
            total_tests = sum(r.test_stats.total_tests for r in successful_results)
            total_passed = sum(r.test_stats.passed for r in successful_results)
            total_failed = sum(r.test_stats.failed for r in successful_results)
            total_skipped = sum(r.test_stats.skipped for r in successful_results)
            total_errors = sum(r.test_stats.errors for r in successful_results)
            overall_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        else:
            total_tests = total_passed = total_failed = total_skipped = total_errors = 0
            overall_pass_rate = 0
        
        # Duration statistics
        durations = [r.duration for r in results.values() if r.duration > 0]
        avg_duration = sum(durations) / len(durations) if durations else 0
        total_duration = sum(durations)
        
        # Error analysis
        error_counts = {}
        for result in results.values():
            if not result.success and result.error_message:
                # Categorize errors
                error_type = self._categorize_error(result.error_message)
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        # Generate report
        report_lines = [
            f"Android-Bench Evaluation Report",
            f"=" * 50,
            f"Run ID: {run_id}",
            f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "📊 Overall Statistics",
            "-" * 20,
            f"Total Instances: {total_instances}",
            f"Successful Evaluations: {successful} ({success_rate:.1f}%)",
            f"Failed Evaluations: {failed} ({100-success_rate:.1f}%)",
            "",
            "🧪 Test Execution Statistics",
            "-" * 30,
            f"Total Tests Run: {total_tests:,}",
            f"Tests Passed: {total_passed:,} ({overall_pass_rate:.1f}%)",
            f"Tests Failed: {total_failed:,}",
            f"Tests Skipped: {total_skipped:,}",
            f"Test Errors: {total_errors:,}",
            "",
            "⏱️ Performance Metrics",
            "-" * 20,
            f"Average Duration per Instance: {avg_duration:.1f}s",
            f"Total Evaluation Time: {total_duration/3600:.2f}h",
            "",
        ]
        
        # Add error analysis if there are failures
        if error_counts:
            report_lines.extend([
                "❌ Error Analysis",
                "-" * 15,
            ])
            for error_type, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / failed * 100) if failed > 0 else 0
                report_lines.append(f"{error_type}: {count} ({percentage:.1f}%)")
            report_lines.append("")
        
        # Add top performing instances (by test pass rate)
        if successful_results:
            top_performers = sorted(
                successful_results, 
                key=lambda x: x.test_stats.pass_rate if x.test_stats else 0, 
                reverse=True
            )[:10]
            
            report_lines.extend([
                "🏆 Top Performing Instances (by test pass rate)",
                "-" * 45,
            ])
            for result in top_performers:
                if result.test_stats:
                    report_lines.append(
                        f"{result.instance_id}: "
                        f"{result.test_stats.passed}/{result.test_stats.total_tests} tests passed "
                        f"({result.test_stats.pass_rate:.1f}%)"
                    )
            report_lines.append("")
        
        # Add worst performing instances
        if successful_results:
            worst_performers = sorted(
                successful_results,
                key=lambda x: x.test_stats.pass_rate if x.test_stats else 0
            )[:10]
            
            report_lines.extend([
                "⚠️ Instances with Low Test Pass Rates",
                "-" * 35,
            ])
            for result in worst_performers:
                if result.test_stats:
                    report_lines.append(
                        f"{result.instance_id}: "
                        f"{result.test_stats.passed}/{result.test_stats.total_tests} tests passed "
                        f"({result.test_stats.pass_rate:.1f}%)"
                    )
        
        return "\n".join(report_lines)
    
    def generate_detailed_test_report(self, run_id: str, instance_id: str = None) -> str:
        """Generate a detailed test-level report for specific instances."""
        results = self.load_run_results(run_id)
        
        if instance_id:
            # Report for specific instance
            if instance_id not in results:
                raise ValueError(f"Instance {instance_id} not found in run {run_id}")
            
            result = results[instance_id]
            return self._generate_instance_test_detail(result)
        else:
            # Report for all instances with test details
            report_lines = [
                f"Detailed Test Report for Run: {run_id}",
                "=" * 60,
                f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
            ]
            
            for instance_id, result in results.items():
                if result.success and result.test_stats:
                    report_lines.extend([
                        f"Instance: {instance_id}",
                        "-" * len(f"Instance: {instance_id}"),
                        self._generate_instance_test_detail(result),
                        "",
                    ])
            
            return "\n".join(report_lines)
    
    def _generate_instance_test_detail(self, result: InstanceResult) -> str:
        """Generate detailed test report for a single instance."""
        if not result.test_stats:
            return f"No test data available for {result.instance_id}"
        
        lines = [
            f"Model: {result.model_name}",
            f"Duration: {result.duration:.1f}s",
            f"Test Summary: {result.test_stats.passed}/{result.test_stats.total_tests} passed ({result.test_stats.pass_rate:.1f}%)",
            "",
        ]
        
        # Add passed tests
        if result.test_stats.passed_tests:
            lines.extend([
                f"✅ Passed Tests ({len(result.test_stats.passed_tests)}):",
            ])
            for test in result.test_stats.passed_tests:
                lines.append(f"  ✓ {test}")
            lines.append("")
        
        # Add failed tests
        if result.test_stats.failed_tests:
            lines.extend([
                f"❌ Failed Tests ({len(result.test_stats.failed_tests)}):",
            ])
            for test in result.test_stats.failed_tests:
                lines.append(f"  ✗ {test}")
            lines.append("")
        
        # Add skipped tests
        if result.test_stats.skipped_tests:
            lines.extend([
                f"⏭️ Skipped Tests ({len(result.test_stats.skipped_tests)}):",
            ])
            for test in result.test_stats.skipped_tests:
                lines.append(f"  ⏭ {test}")
            lines.append("")
        
        # Add error tests
        if result.test_stats.error_tests:
            lines.extend([
                f"💥 Tests with Errors ({len(result.test_stats.error_tests)}):",
            ])
            for test in result.test_stats.error_tests:
                lines.append(f"  💥 {test}")
            lines.append("")
        
        return "\n".join(lines)
        
        return "\n".join(report_lines)
    
    def _categorize_error(self, error_message: str) -> str:
        """Categorize error messages into types."""
        error_lower = error_message.lower()
        
        if "clone" in error_lower or "repository" in error_lower:
            return "Repository Clone Error"
        elif "docker" in error_lower or "container" in error_lower:
            return "Container Error"
        elif "patch" in error_lower:
            return "Patch Application Error"
        elif "build" in error_lower or "gradle" in error_lower:
            return "Build Error"
        elif "test" in error_lower:
            return "Test Execution Error"
        elif "timeout" in error_lower:
            return "Timeout Error"
        else:
            return "Other Error"
    
    def generate_comparison_report(self, run_ids: List[str]) -> str:
        """Generate a comparison report between multiple runs."""
        if len(run_ids) < 2:
            raise ValueError("At least 2 run IDs required for comparison")
        
        run_results = {}
        for run_id in run_ids:
            try:
                run_results[run_id] = self.load_run_results(run_id)
            except FileNotFoundError:
                logger.warning(f"Could not load results for run: {run_id}")
                continue
        
        if len(run_results) < 2:
            raise ValueError("Could not load results for at least 2 runs")
        
        report_lines = [
            "Android-Bench Comparison Report",
            "=" * 50,
            f"Comparing {len(run_results)} runs",
            f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        
        # Create comparison table
        comparison_data = []
        for run_id, results in run_results.items():
            total = len(results)
            successful = len([r for r in results.values() if r.success])
            success_rate = (successful / total * 100) if total > 0 else 0
            
            # Test statistics
            successful_results = [r for r in results.values() if r.success and r.test_stats]
            if successful_results:
                total_tests = sum(r.test_stats.total_tests for r in successful_results)
                total_passed = sum(r.test_stats.passed for r in successful_results)
                test_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
            else:
                total_tests = 0
                test_pass_rate = 0
            
            # Duration
            durations = [r.duration for r in results.values() if r.duration > 0]
            avg_duration = sum(durations) / len(durations) if durations else 0
            
            comparison_data.append({
                'Run ID': run_id,
                'Total Instances': total,
                'Success Rate (%)': f"{success_rate:.1f}",
                'Total Tests': total_tests,
                'Test Pass Rate (%)': f"{test_pass_rate:.1f}",
                'Avg Duration (s)': f"{avg_duration:.1f}"
            })
        
        # Convert to DataFrame for better formatting
        df = pd.DataFrame(comparison_data)
        
        report_lines.extend([
            "📊 Comparison Summary",
            "-" * 20,
            df.to_string(index=False),
            "",
        ])
        
        return "\n".join(report_lines)
    
    def export_to_csv(self, run_id: str, output_file: Optional[str] = None, include_test_details: bool = False) -> str:
        """Export results to CSV format."""
        results = self.load_run_results(run_id)
        
        csv_data = []
        for result in results.values():
            row = {
                'instance_id': result.instance_id,
                'model_name': result.model_name,
                'success': result.success,
                'error_message': result.error_message,
                'duration': result.duration,
            }
            
            if result.test_stats:
                row.update({
                    'total_tests': result.test_stats.total_tests,
                    'passed_tests': result.test_stats.passed,
                    'failed_tests': result.test_stats.failed,
                    'skipped_tests': result.test_stats.skipped,
                    'error_tests': result.test_stats.errors,
                    'test_pass_rate': result.test_stats.pass_rate,
                })
                
                if include_test_details:
                    # Add test lists as pipe-separated strings
                    row.update({
                        'passed_test_list': '|'.join(result.test_stats.passed_tests),
                        'failed_test_list': '|'.join(result.test_stats.failed_tests),
                        'skipped_test_list': '|'.join(result.test_stats.skipped_tests),
                        'error_test_list': '|'.join(result.test_stats.error_tests),
                    })
            
            csv_data.append(row)
        
        df = pd.DataFrame(csv_data)
        
        if output_file is None:
            output_file = f"android_bench_results_{run_id}.csv"
        
        df.to_csv(output_file, index=False)
        logger.info(f"Results exported to: {output_file}")
        
        return output_file


def main():
    """CLI for generating reports."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Android-bench results reporter")
    parser.add_argument("results_dir", help="Path to results directory")
    parser.add_argument("--run-id", help="Specific run ID to analyze")
    parser.add_argument("--compare", nargs="+", help="Compare multiple run IDs")
    parser.add_argument("--list-runs", action="store_true", help="List available runs")
    parser.add_argument("--export-csv", help="Export results to CSV")
    parser.add_argument("--include-test-details", action="store_true", help="Include detailed test lists in CSV export")
    parser.add_argument("--detailed-tests", action="store_true", help="Generate detailed test-level report")
    parser.add_argument("--instance-id", help="Specific instance for detailed test report")
    parser.add_argument("--output", help="Output file for reports")
    
    args = parser.parse_args()
    
    try:
        reporter = AndroidBenchReporter(args.results_dir)
        
        if args.list_runs:
            runs = reporter.list_available_runs()
            print("Available runs:")
            for run in runs:
                print(f"  - {run}")
            return
        
        if args.compare:
            report = reporter.generate_comparison_report(args.compare)
        elif args.detailed_tests and args.run_id:
            report = reporter.generate_detailed_test_report(args.run_id, args.instance_id)
        elif args.run_id:
            report = reporter.generate_summary_report(args.run_id)
        else:
            print("Please specify --run-id or --compare")
            return
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            print(f"Report saved to: {args.output}")
        else:
            print(report)
        
        if args.export_csv and args.run_id:
            reporter.export_to_csv(args.run_id, include_test_details=args.include_test_details)
    
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())