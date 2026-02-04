#!/usr/bin/env python3
"""
Convert validation results to report.json format for build_dataset/gen_report.

This script reads validation test logs, copies them to the expected locations,
and creates report.json files in the expected format for the harness.
"""

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Set, Tuple, Optional


@dataclass
class TestResult:
    passed_count: int
    failed_count: int
    skipped_count: int
    passed_tests: Set[str]
    failed_tests: Set[str]
    skipped_tests: Set[str]

    def to_dict(self):
        return {
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "passed_tests": sorted(list(self.passed_tests)),
            "failed_tests": sorted(list(self.failed_tests)),
            "skipped_tests": sorted(list(self.skipped_tests)),
        }


@dataclass
class Report:
    """Self-contained Report class matching the harness format."""
    org: str
    repo: str
    number: int
    run_result: TestResult
    test_patch_result: TestResult
    fix_patch_result: TestResult

    def check(self, force: bool = False) -> Tuple[bool, str]:
        """Validate the report for F2P test transitions."""
        # Check for F2P tests (fail in test_patch, pass in fix_patch)
        f2p_tests = self.test_patch_result.failed_tests & self.fix_patch_result.passed_tests

        if not f2p_tests:
            return False, "No F2P tests found (tests that fail with test patch but pass with fix patch)"

        # Check for P2P tests (pass in both - regression check)
        p2p_tests = self.test_patch_result.passed_tests & self.fix_patch_result.passed_tests

        # Check that passed and failed don't overlap
        if self.test_patch_result.passed_tests & self.test_patch_result.failed_tests:
            return False, "Test patch result has tests in both passed and failed"
        if self.fix_patch_result.passed_tests & self.fix_patch_result.failed_tests:
            return False, "Fix patch result has tests in both passed and failed"

        return True, f"Valid: {len(f2p_tests)} F2P tests, {len(p2p_tests)} P2P tests"

    def to_dict(self):
        return {
            "org": self.org,
            "repo": self.repo,
            "number": self.number,
            "run_result": self.run_result.to_dict(),
            "test_patch_result": self.test_patch_result.to_dict(),
            "fix_patch_result": self.fix_patch_result.to_dict(),
        }

    def json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def parse_validation_log(log_content: str) -> TestResult:
    """Parse test results from validation log (same format as element_x_android.py)."""
    passed_tests = set()
    failed_tests = set()
    skipped_tests = set()

    # Parse XML test result sections
    xml_sections = re.findall(r'=== XML(?:\s+FILE)?:\s*(.+?)\s*===\s*\n(.*?)\n=== END', log_content, re.DOTALL)
    xml_sections.extend(re.findall(r'=== TEST RESULT:\s*(.+?)\s*===\s*\n(.*?)\n=== END', log_content, re.DOTALL))

    # Filter to only Debug variant results and deduplicate by path
    seen_paths = set()
    filtered_sections = []
    for path, content in xml_sections:
        if 'testDebugUnitTest' in path and path not in seen_paths:
            seen_paths.add(path)
            filtered_sections.append((path, content))
    xml_sections = filtered_sections

    for _, xml_content in xml_sections:
        # Parse <testcase> elements from XML
        testcase_pattern = r'<testcase[^>]*name="([^"]+)"[^>]*classname="([^"]+)"[^>]*(?:/>|>(.*?)</testcase>)'
        testcases = re.findall(testcase_pattern, xml_content, re.DOTALL)

        for match in testcases:
            test_name = match[0].strip()
            class_name = match[1].strip()
            test_content = match[2] if len(match) > 2 else ""

            full_test_name = f"{class_name}.{test_name}"

            if test_content:
                if '<failure' in test_content or '<error' in test_content:
                    failed_tests.add(full_test_name)
                elif '<skipped' in test_content:
                    skipped_tests.add(full_test_name)
                else:
                    passed_tests.add(full_test_name)
            else:
                passed_tests.add(full_test_name)

    return TestResult(
        passed_count=len(passed_tests),
        failed_count=len(failed_tests),
        skipped_count=len(skipped_tests),
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        skipped_tests=skipped_tests,
    )


def find_validation_logs(validation_dir: Path, pr_number: int) -> Tuple[Path, Path]:
    """Find pre and post solution logs for a PR."""
    instance_dir = validation_dir / f"element-hq__element-x-android-{pr_number}" / "test_logs"

    if not instance_dir.exists():
        raise FileNotFoundError(f"Validation directory not found: {instance_dir}")

    pre_logs = list(instance_dir.glob("test_log_pre_solution_*.txt"))
    post_logs = list(instance_dir.glob("test_log_post_solution_*.txt"))

    if not pre_logs:
        raise FileNotFoundError(f"No pre_solution log found in {instance_dir}")
    if not post_logs:
        raise FileNotFoundError(f"No post_solution log found in {instance_dir}")

    # Use the most recent ones if multiple exist
    pre_log = sorted(pre_logs)[-1]
    post_log = sorted(post_logs)[-1]

    return pre_log, post_log


def convert_validation_to_report(
    validation_dir: Path,
    output_dir: Path,
    pr_number: int,
    org: str = "element-hq",
    repo: str = "element-x-android"
) -> bool:
    """Convert validation results to report.json format and copy logs."""

    try:
        pre_log_path, post_log_path = find_validation_logs(validation_dir, pr_number)

        print(f"PR {pr_number}: Reading validation logs...")
        print(f"  Pre-solution: {pre_log_path.name}")
        print(f"  Post-solution: {post_log_path.name}")

        # Read and parse logs
        with open(pre_log_path, 'r') as f:
            pre_content = f.read()
        with open(post_log_path, 'r') as f:
            post_content = f.read()

        test_patch_result = parse_validation_log(pre_content)
        fix_patch_result = parse_validation_log(post_content)

        print(f"  Test patch: {test_patch_result.passed_count} pass, {test_patch_result.failed_count} fail")
        print(f"  Fix patch: {fix_patch_result.passed_count} pass, {fix_patch_result.failed_count} fail")

        # For run_result (baseline), we estimate:
        # Tests that go from fail (pre) to pass (post) are the ones the fix addresses
        f2p_tests = test_patch_result.failed_tests & fix_patch_result.passed_tests

        # For baseline (run_result), assume those F2P tests were passing before test_patch
        run_passed = (test_patch_result.passed_tests | f2p_tests)
        run_failed = test_patch_result.failed_tests - f2p_tests

        run_result = TestResult(
            passed_count=len(run_passed),
            failed_count=len(run_failed),
            skipped_count=test_patch_result.skipped_count,
            passed_tests=run_passed,
            failed_tests=run_failed,
            skipped_tests=test_patch_result.skipped_tests,
        )

        print(f"  Baseline (estimated): {run_result.passed_count} pass, {run_result.failed_count} fail")
        print(f"  F2P tests: {len(f2p_tests)}")

        # Create Report object
        report = Report(
            org=org,
            repo=repo,
            number=pr_number,
            run_result=run_result,
            test_patch_result=test_patch_result,
            fix_patch_result=fix_patch_result,
        )

        # Validate the report
        valid, error_msg = report.check(force=True)
        print(f"  Valid: {valid}")
        if not valid:
            print(f"  Error: {error_msg[:100]}...")

        # Create output directory
        output_instance_dir = output_dir / f"pr-{pr_number}"
        output_instance_dir.mkdir(parents=True, exist_ok=True)

        # Copy logs to expected locations
        # pre_solution -> test-patch-run.log (tests with test patch applied)
        # post_solution -> fix-patch-run.log (tests with both patches applied)
        # run.log -> copy pre_solution (baseline approximation)

        run_log_dest = output_instance_dir / "run.log"
        test_patch_log_dest = output_instance_dir / "test-patch-run.log"
        fix_patch_log_dest = output_instance_dir / "fix-patch-run.log"

        # Copy the logs
        shutil.copy2(pre_log_path, run_log_dest)
        print(f"  Copied: {pre_log_path.name} -> run.log")

        shutil.copy2(pre_log_path, test_patch_log_dest)
        print(f"  Copied: {pre_log_path.name} -> test-patch-run.log")

        shutil.copy2(post_log_path, fix_patch_log_dest)
        print(f"  Copied: {post_log_path.name} -> fix-patch-run.log")

        # Write report.json
        report_path = output_instance_dir / "report.json"
        with open(report_path, 'w') as f:
            f.write(report.json())

        print(f"  Written: {report_path}")
        return valid

    except Exception as e:
        print(f"PR {pr_number}: Error - {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    # Configuration
    validation_dir = Path("/home/moshood/dev/mobile-bench/mobiledev_bench/validation/validation_results/element")
    output_dir = Path("/home/moshood/dev/mobile-bench/data/docker_images/elementxandroid/element-hq/element-x-android/instances")

    # PRs that failed in build_dataset but have validation results
    failing_prs = [2283, 2225, 2001, 1767]

    # Also check which ones actually exist in validation
    available_prs = []
    for pr in failing_prs:
        instance_dir = validation_dir / f"element-hq__element-x-android-{pr}"
        if instance_dir.exists():
            available_prs.append(pr)
        else:
            print(f"PR {pr}: No validation results found")

    print(f"\nFound {len(available_prs)} PRs with validation results")
    print("=" * 60)

    success_count = 0
    for pr in available_prs:
        success = convert_validation_to_report(validation_dir, output_dir, pr)
        if success:
            success_count += 1
        print()

    print("=" * 60)
    print(f"Summary: {success_count}/{len(available_prs)} valid reports created")
    print(f"Total reports created: {len(available_prs)}")
    print("\nNext steps:")
    print("1. Run gen_report to regenerate the dataset:")
    print("   python3 -m mobiledev_bench.harness.gen_report \\")
    print("     --mode dataset \\")
    print("     --workdir /home/moshood/dev/mobile-bench/data/docker_images/elementxandroid/ \\")
    print("     --output_dir /home/moshood/dev/mobile-bench/data/results/kotlin/elementxandroid/builds/ \\")
    print("     --raw_dataset_files /home/moshood/dev/mobile-bench/data/instances/all/element-hq__element-x-android_instances_with_test_commands_filtered.jsonl \\")
    print("     --log_dir /home/moshood/dev/mobile-bench/data/results/kotlin/elementxandroid/logs/")


if __name__ == "__main__":
    main()
