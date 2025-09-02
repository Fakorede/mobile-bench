#!/usr/bin/env python3
"""
build_utils.py - Gradle Build Management Utilities

This module handles gradle test execution for Android validation.
"""

import logging
import time
from pathlib import Path
from typing import Optional, List, Set, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Result of gradle build execution."""
    success: bool
    exit_code: int
    output: str
    duration: float
    log_file_path: Optional[str] = None


class AndroidBuildManager:
    """Manages Android gradle builds and logging."""
    
    def __init__(self, results_dir: str = "validation_results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True)
    
    def _should_run_tests_instead_of_build(self, test_patch: str) -> bool:
        """
        Determine if we should run tests instead of just compilation based on patch content.
        """
        if not test_patch or not test_patch.strip():
            return False
        
        test_files = self._extract_test_files_from_patch(test_patch)
        
        # If we have test files, we should run tests
        if test_files:
            logger.debug(f"Found {len(test_files)} test files in patch - will run targeted tests")
            return True
        
        # Check if patch modifies existing test files (not just adds new ones)
        lines = test_patch.split('\n')
        for line in lines:
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                file_path = line.split('/', 1)[1] if '/' in line else ""
                if self._is_test_file(file_path):
                    logger.debug(f"Found modified test file {file_path} - will run targeted tests")
                    return True
        
        return False

    def run_tests_for_instance(self, containers_manager, instance_id: str, 
                              timeout: int = 600, test_patch: str = None) -> BuildResult:
        """
        Run tests for the Android project. Only runs tests, no building or compilation.
        
        Args:
            containers_manager: The container manager instance
            instance_id: ID of the instance being validated
            timeout: Test timeout in seconds (default 10 minutes)
            test_patch: Optional test patch to extract specific test targets
            
        Returns:
            BuildResult with success status, logs, and timing info
        """
        logger.info(f"Starting test execution for instance {instance_id}")
        start_time = time.time()
        
        # Check if there are test files in the patch
        if not test_patch or not test_patch.strip():
            logger.info(f"[{instance_id}] No test patch provided - no tests to run, continuing to next instance")
            return BuildResult(
                success=True,
                exit_code=0,
                output="No test patch provided - no tests to run",
                duration=time.time() - start_time
            )
        
        # Extract test files from patch
        test_files = self._extract_test_files_from_patch(test_patch)
        if not test_files:
            logger.info(f"[{instance_id}] No test files found in patch - no tests to run, continuing to next instance")
            return BuildResult(
                success=True,
                exit_code=0,
                output="No test files found in patch - no tests to run",
                duration=time.time() - start_time
            )
        
        logger.info(f"[{instance_id}] Found {len(test_files)} test files - running targeted tests")
        logger.info(f"[{instance_id}] Test files: {test_files}")
        
        # Analyze project structure for variants and flavors
        build_variants = self._detect_build_variants(containers_manager, instance_id)
        test_tasks = self._generate_test_tasks(test_files, build_variants)
        
        if not test_tasks:
            logger.info(f"[{instance_id}] Could not generate test tasks - no tests to run, continuing to next instance")
            return BuildResult(
                success=True,
                exit_code=0,
                output="Could not generate test tasks - no tests to run",
                duration=time.time() - start_time
            )
        
        logger.info(f"[{instance_id}] Generated test tasks: {test_tasks}")
        
        # Build the test execution command (ONLY test tasks, no build/compile tasks)
        gradle_command = f"./gradlew {' '.join(test_tasks)} --stacktrace --info --no-daemon --continue"
        logger.info(f"[{instance_id}] TEST-ONLY COMMAND: {gradle_command}")
        
        # Execute the tests
        test_command = f"""
cd /workspace &&
echo "=== Starting Test-Only Execution ===" &&
echo "Instance ID: {instance_id}" &&
echo "Working directory: $(pwd)" &&

# Java version detection
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
echo "Using Java: $(java -version 2>&1 | head -1)"

# Android environment
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_ROOT='/opt/android-sdk'
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle

# Gradle configuration for tests only
cat > /tmp/.gradle/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Stopping existing Gradle daemons ===" &&
./gradlew --stop 2>/dev/null || true &&

echo "=== Executing tests only (no build/compilation) ===" &&
echo "Command: {gradle_command}" &&
{gradle_command} 2>&1

echo "=== Test execution completed ===" &&
echo "Exit code: $?"
        """
        
        try:
            exit_code, output = containers_manager.exec_command(
                instance_id,
                test_command,
                workdir="/workspace",
                timeout=max(timeout, 900)  # At least 15 minutes for tests
            )
            
            duration = time.time() - start_time
            success = self._analyze_test_success(output, exit_code)
            
            logger.info(f"Test execution completed for {instance_id}: "
                       f"success={success}, duration={duration:.1f}s")
            
            # Save test log
            command_info = {
                "instance_id": instance_id,
                "build_type": "TEST_ONLY",
                "gradle_command": gradle_command,
                "targets": test_tasks,
                "test_files_found": test_files,
                "build_variants": build_variants
            }
            
            log_file = self._save_test_log(instance_id, 
                                         BuildResult(success, exit_code, output, duration),
                                         command_info)
            
            return BuildResult(
                success=success,
                exit_code=exit_code,
                output=output,
                duration=duration,
                log_file_path=log_file
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_output = f"Test execution failed: {str(e)}"
            logger.error(f"Test execution failed for {instance_id}: {e}")
            
            return BuildResult(
                success=False,
                exit_code=1,
                output=error_output,
                duration=duration
            )

    def _detect_build_variants(self, containers_manager, instance_id: str) -> Dict[str, Any]:
        """
        Detect build variants, flavors, and configurations from the project.
        """
        variants_info = {
            "flavors": ["debug"],  # Default
            "build_types": ["debug"],  # Default
            "modules": [":app"],  # Default
            "test_variants": ["testDebugUnitTest"]
        }
        
        try:
            # Try to get project info from Gradle
            gradle_info_command = """
    cd /workspace &&
    if [ -f './gradlew' ]; then
        timeout 60 ./gradlew :app:tasks --group=verification --quiet 2>/dev/null || \
        timeout 60 ./gradlew tasks --group=verification --quiet 2>/dev/null || \
        echo "Could not get task info"
    fi
    """
            
            exit_code, output = containers_manager.exec_command(
                instance_id, gradle_info_command, workdir="/workspace", timeout=90
            )
            
            if exit_code == 0 and output:
                # Parse available test tasks to infer variants
                test_tasks = []
                for line in output.split('\n'):
                    if 'test' in line.lower() and ('unittest' in line.lower() or 'debug' in line.lower()):
                        task_name = line.strip().split()[0] if line.strip() else ""
                        if task_name and ':' not in task_name:  # Simple task name
                            test_tasks.append(task_name)
                
                if test_tasks:
                    variants_info["test_variants"] = test_tasks[:5]  # Limit to avoid too many
                    logger.info(f"[{instance_id}] Detected test variants: {test_tasks}")
                
                # Extract build flavors and types from task names
                flavors = set()
                build_types = set()
                for task in test_tasks:
                    # Parse patterns like "testDebugUnitTest", "testReleaseUnitTest", "testFreeDebugUnitTest"
                    task_lower = task.lower()
                    if 'test' in task_lower and 'unittest' in task_lower:
                        # Remove 'test' prefix and 'unittest' suffix
                        middle = task_lower.replace('test', '').replace('unittest', '')
                        if 'debug' in middle:
                            build_types.add('debug')
                            middle = middle.replace('debug', '')
                        if 'release' in middle:
                            build_types.add('release')
                            middle = middle.replace('release', '')
                        if middle:  # Remaining part might be flavor
                            flavors.add(middle.capitalize())
                
                if flavors:
                    variants_info["flavors"] = list(flavors)
                if build_types:
                    variants_info["build_types"] = list(build_types)
                    
        except Exception as e:
            logger.warning(f"[{instance_id}] Could not detect build variants: {e}")
        
        return variants_info

    def _generate_test_tasks(self, test_files: List[str], build_variants: Dict[str, Any]) -> List[str]:
        """
        Generate appropriate Gradle test tasks for the given test files and variants.
        """
        tasks = []
        
        # Group test files by module
        module_tests = {}
        for test_file in test_files:
            module = self._extract_module_from_path(test_file)
            test_class = self._extract_test_class_from_file(test_file)
            
            if module not in module_tests:
                module_tests[module] = {"unit": [], "instrumented": []}
            
            if test_class:
                if self._is_instrumented_test(test_file):
                    pass
                    # module_tests[module]["instrumented"].append(test_class)
                else:
                    module_tests[module]["unit"].append(test_class)
        
        # Generate tasks for each module
        for module, test_dict in module_tests.items():
            unit_tests = test_dict["unit"]
            instrumented_tests = test_dict["instrumented"]
            
            # Available test variants from detection
            available_variants = build_variants.get("test_variants", ["testDebugUnitTest"])
            
            # Process unit tests
            if unit_tests:
                # Find appropriate unit test variant
                unit_variant = None
                for variant in available_variants:
                    if 'unittest' in variant.lower() and 'debug' in variant.lower():
                        unit_variant = variant
                        break
                
                # Fallback to first unit test variant or default
                if not unit_variant:
                    unit_variants = [v for v in available_variants if 'unittest' in v.lower()]
                    unit_variant = unit_variants[0] if unit_variants else "testDebugUnitTest"
                
                # Build the task
                if module == ":app":
                    base_task = unit_variant
                else:
                    base_task = f"{module}:{unit_variant}"
                
                # Add test class filters
                test_filters = ' '.join([f'--tests "{tc}"' for tc in unit_tests])
                full_task = f"{base_task} {test_filters}".strip()
                tasks.append(full_task)
                
                logger.info(f"Generated unit test task for {module}: {full_task}")
            
            # Process instrumented tests
            # if instrumented_tests:
            #     # Find appropriate instrumented test variant
            #     instrumented_variant = None
            #     for variant in available_variants:
            #         if any(keyword in variant.lower() for keyword in ['connected', 'android', 'instrumented']):
            #             instrumented_variant = variant
            #             break
                
            #     # Fallback to default instrumented test variant
            #     if not instrumented_variant:
            #         instrumented_variant = "connectedDebugAndroidTest"
                
            #     # Build the task
            #     if module == ":app":
            #         base_task = instrumented_variant
            #     else:
            #         base_task = f"{module}:{instrumented_variant}"
                
            #     # For instrumented tests, use different filtering approach
            #     # Some projects support class filtering, others don't
            #     test_filters = ' '.join([f'--tests "{tc}"' for tc in instrumented_tests])
            #     full_task = f"{base_task} {test_filters}".strip()
            #     tasks.append(full_task)
                
            #     logger.info(f"Generated instrumented test task for {module}: {full_task}")
        
        return tasks

    def _extract_test_class_from_file(self, test_file: str) -> Optional[str]:
        """
        Extract the test class name from a test file path.
        
        Examples:
        - app/src/test/java/com/example/MyTest.java -> com.example.MyTest
        - net/download/service/src/test/java/de/danoeh/antennapod/net/download/service/episode/autodownload/DbReaderTest.java 
        -> de.danoeh.antennapod.net.download.service.episode.autodownload.DbReaderTest
        """
        try:
            # Get the file name without extension
            file_name = test_file.split('/')[-1]
            if file_name.endswith('.java'):
                class_name = file_name[:-5]
            elif file_name.endswith('.kt'):
                class_name = file_name[:-3]
            else:
                return None
            
            # Extract package from path
            parts = test_file.split('/')
            
            # Find the start of package structure (after src/test/java or src/androidTest/java)
            package_start = -1
            for i, part in enumerate(parts):
                if part in ['java', 'kotlin'] and i > 0:
                    prev_part = parts[i-1]
                    if prev_part in ['test', 'androidTest', 'main']:
                        package_start = i + 1
                        break
            
            if package_start >= 0 and package_start < len(parts) - 1:
                package_parts = parts[package_start:-1]  # Exclude the file name
                package_name = '.'.join(package_parts)
                return f"{package_name}.{class_name}"
            else:
                # Fallback: just return the class name
                return class_name
                
        except Exception as e:
            logger.warning(f"Could not extract class name from {test_file}: {e}")
            return None

    def _analyze_test_success(self, output: str, exit_code: int) -> bool:
        """
        Analyze test output to determine if tests ran successfully.
        Success means tests executed (even if some failed), not compilation failure.
        """
        # Check for test execution indicators in output
        test_execution_indicators = [
            "test results",
            "tests completed",
            "BUILD SUCCESSFUL",
            "TEST-*.xml",
            "test summary",
            "tests ran",
            "> Task :test",
            "XML RESULT:",
            "test execution summary"
        ]
        
        # Check for compilation failures vs test failures
        compilation_failures = [
            "compilation failed",
            "could not compile",
            "cannot find symbol",
            "package does not exist",
            "BUILD FAILED"
        ]
        
        output_lower = output.lower()
        
        # If we see test execution indicators, consider it successful even with failures
        if any(indicator in output_lower for indicator in test_execution_indicators):
            logger.info("Test execution detected - marking as successful even with possible test failures")
            return True
        
        # If we see compilation failures, it's not successful
        if any(failure in output_lower for failure in compilation_failures):
            logger.warning("Compilation failure detected - marking as unsuccessful")
            return False
        
        # If exit code is 0, assume tests ran successfully
        if exit_code == 0:
            return True

        # Default: if exit code is not 0 and no clear indicators, consider failed
        logger.warning(f"No clear test execution indicators found, exit code {exit_code} - marking as unsuccessful")
        return False

    def _save_test_log(self, instance_id: str, test_result: BuildResult, 
                      command_info: Dict[str, Any] = None) -> str:
        """
        Save test execution log for an instance.
        
        Args:
            instance_id: ID of the instance
            test_result: The test result to save
            command_info: Optional dictionary with command information
            
        Returns:
            Path to the saved log file
        """
        instance_test_dir = self.results_dir / instance_id / "test_logs"
        instance_test_dir.mkdir(exist_ok=True, parents=True)
        log_file = instance_test_dir / f"test_log_{int(time.time())}.txt"
        
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"Android Test Execution Log\n")
                f.write(f"Instance ID: {instance_id}\n")
                f.write(f"Test Success: {test_result.success}\n")
                f.write(f"Exit Code: {test_result.exit_code}\n")
                f.write(f"Duration: {test_result.duration:.2f} seconds\n")
                f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                
                # Add command info if provided
                if command_info:
                    f.write(f"Execution Type: {command_info.get('build_type', 'TEST_ONLY')}\n")
                    f.write(f"Gradle Command: {command_info.get('gradle_command', 'UNKNOWN')}\n")
                    f.write(f"Test Tasks: {command_info.get('targets', [])}\n")
                    f.write(f"Test Files Found: {command_info.get('test_files_found', [])}\n")
                    if 'error' in command_info:
                        f.write(f"Error: {command_info['error']}\n")
                
                f.write("=" * 60 + "\n")
                f.write("TEST OUTPUT:\n")
                f.write("=" * 60 + "\n")
                f.write(test_result.output)
                
                if not test_result.success:
                    f.write("\n" + "=" * 60 + "\n")
                    f.write("ERROR ANALYSIS:\n")
                    f.write("=" * 60 + "\n")
                    self._analyze_test_errors(f, test_result.output)
            
            logger.info(f"Test log saved to: {log_file}")
            return str(log_file)
        except Exception as e:
            logger.error(f"Failed to save test log for {instance_id}: {e}")
            return ""

    def _analyze_test_errors(self, f, output: str):
        """Analyze and write test error information to log file."""
        lines = output.split('\n')
        
        f.write("Key error indicators:\n")
        for line in lines:
            line_lower = line.lower()
            if any(error in line_lower for error in ['error:', 'failed:', 'exception', 'cannot find']):
                f.write(f"  {line}\n")
    
    # def _determine_build_targets(self, test_patch: str) -> List[str]:
    #     """
    #     Determine specific gradle build targets based on test patch content.
        
    #     Args:
    #         test_patch: The test patch content to analyze
            
    #     Returns:
    #         List of gradle build targets (e.g., ['app:testDebugUnitTest', 'app:assembleDebug'])
    #     """
    #     if not test_patch or not test_patch.strip():
    #         return []
        
    #     build_targets = set()
    #     test_files = self._extract_test_files_from_patch(test_patch)
        
    #     for test_file in test_files:
    #         targets = self._file_to_build_targets(test_file)
    #         build_targets.update(targets)
        
    #     # Always include basic assembly for compilation check
    #     if build_targets:
    #         # Add compile tasks to ensure compilation works
    #         modules = self._extract_modules_from_targets(build_targets)
    #         for module in modules:
    #             build_targets.add(f"{module}:compileDebugSources")
        
    #     return sorted(list(build_targets))
    
    def _extract_test_files_from_patch(self, test_patch: str) -> List[str]:
        """Extract test file paths from patch content."""
        import re
        
        # Patterns to match file paths in patch
        file_patterns = [
            r'\+\+\+ b/(.+\.(?:java|kt))',
            r'diff --git a/.+ b/(.+\.(?:java|kt))'
        ]
        
        test_files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, test_patch)
            for match in matches:
                # Only include actual test files
                if self._is_test_file(match):
                    test_files.add(match)
        
        return list(test_files)
    
    def _is_test_file(self, file_path: str) -> bool:
        """Check if a file is a test file."""
        file_lower = file_path.lower()
        
        # Test file indicators
        test_indicators = [
            '/test/',
            '/androidtest/',
            '/instrumentedtest/',
            'test.java',
            'test.kt',
            'tests.java',
            'tests.kt'
        ]
        
        return any(indicator in file_lower for indicator in test_indicators)
    
    def _file_to_build_targets(self, test_file: str) -> List[str]:
        """
        Convert a test file path to appropriate gradle build targets.
        
        Args:
            test_file: Path to test file (e.g., 'app/src/test/java/com/example/MyTest.java')
            
        Returns:
            List of gradle targets for this test file
        """
        targets = []
        
        # Extract module from file path
        module = self._extract_module_from_path(test_file)
        
        # Determine test type and build appropriate targets
        if self._is_unit_test(test_file):
            # Unit test targets
            targets.extend([
                f"{module}:testDebugUnitTest",
                f"{module}:compileDebugUnitTestSources"
            ])
        elif self._is_instrumented_test(test_file):
            # Instrumented test targets  
            targets.extend([
                f"{module}:assembleDebugAndroidTest",
                f"{module}:compileDebugAndroidTestSources"
            ])
        
        # Always include basic compilation
        targets.append(f"{module}:compileDebugSources")
        
        return targets
    
    def _extract_module_from_path(self, file_path: str) -> str:
        """
        Extract gradle module from file path.
        
        Examples:
        - app/src/test/java/... -> :app
        - net/download/service/src/test/java/... -> :net:download:service
        - feature/notifications/src/test/java/... -> :feature:notifications
        """
        parts = file_path.split('/')
        
        # Find where 'src' appears (this usually marks the end of module path)
        module_parts = []
        for part in parts:
            if part == 'src':
                break
            module_parts.append(part)
        
        if not module_parts:
            return ":app"  # Default fallback
        
        # Handle common patterns
        if len(module_parts) == 1:
            # Single part like "app" -> ":app"
            return f":{module_parts[0]}"
        else:
            # Multiple parts like ["net", "download", "service"] -> ":net:download:service"
            return ":" + ":".join(module_parts)
    
    def _is_unit_test(self, file_path: str) -> bool:
        """Check if file is a unit test."""
        return '/test/' in file_path and '/androidtest/' not in file_path
    
    def _is_instrumented_test(self, test_file: str) -> bool:
        """
        Determine if a test file is an instrumented test based on its path.
        """
        test_file_lower = test_file.lower()
        
        # Instrumented test indicators
        instrumented_indicators = [
            '/androidtest/',
            '/instrumentedtest/',
            'androidtest.java',
            'androidtest.kt',
            '/androidTest/',  # Note the capital T
            'src/androidTest'
        ]
        
        return any(indicator in test_file_lower for indicator in instrumented_indicators)
    
    def _extract_modules_from_targets(self, targets: List[str]) -> Set[str]:
        """Extract unique modules from build targets."""
        modules = set()
        for target in targets:
            if ':' in target:
                module = target.split(':')[0]
                if module:  # Skip empty string for targets starting with ':'
                    modules.add(module)
        return modules
    
    # def _analyze_build_errors(self, file_handle, build_output: str):
    #     """Analyze and categorize build errors in the log."""
        
    #     error_patterns = [
    #         ("Compilation Errors", r"error: (.+)"),
    #         ("Missing Symbols", r"error: cannot find symbol\s+symbol:\s+(.+)"),
    #         ("Missing Packages", r"error: package (.+) does not exist"),
    #         ("Unresolved Types", r"error: (.+) cannot be resolved to a type"),
    #         ("Missing Methods", r"error: The method (.+) is undefined"),
    #         ("Build Failures", r"FAILURE: (.+)"),
    #         ("Execution Failed", r"Execution failed for task (.+)")
    #     ]
        
    #     found_errors = {}
    #     for category, pattern in error_patterns:
    #         import re
    #         matches = re.findall(pattern, build_output, re.MULTILINE)
    #         if matches:
    #             found_errors[category] = matches[:5]  # Limit to first 5 of each type
        
    #     if found_errors:
    #         for category, errors in found_errors.items():
    #             file_handle.write(f"\n{category}:\n")
    #             for i, error in enumerate(errors, 1):
    #                 file_handle.write(f"  {i}. {error}\n")
    #     else:
    #         file_handle.write("No specific error patterns detected.\n")
    
    # def get_build_summary(self, log_file_path: str) -> dict:
    #     """
    #     Extract a summary from a build log file.
        
    #     Args:
    #         log_file_path: Path to the build log file
            
    #     Returns:
    #         Dictionary with build summary information
    #     """
    #     try:
    #         with open(log_file_path, 'r', encoding='utf-8') as f:
    #             content = f.read()
            
    #         # Extract basic info
    #         summary = {
    #             "success": "Build Success: True" in content,
    #             "duration": 0.0,
    #             "instance_id": "",
    #             "error_count": 0,
    #             "main_errors": []
    #         }
            
    #         # Parse duration
    #         import re
    #         duration_match = re.search(r"Duration: ([\d.]+) seconds", content)
    #         if duration_match:
    #             summary["duration"] = float(duration_match.group(1))
            
    #         # Parse instance ID
    #         id_match = re.search(r"Instance ID: (.+)", content)
    #         if id_match:
    #             summary["instance_id"] = id_match.group(1)
            
    #         # Count errors
    #         error_matches = re.findall(r"error:", content)
    #         summary["error_count"] = len(error_matches)
            
    #         # Extract main error messages (first 3)
    #         main_errors = re.findall(r"error: (.+)", content)
    #         summary["main_errors"] = main_errors[:3]
            
    #         return summary
            
    #     except Exception as e:
    #         logger.error(f"Error reading build summary from {log_file_path}: {e}")
    #         return {"success": False, "error": str(e)}


# def create_build_summary_report(results_dir: str = "validation_results") -> str:
#     """
#     Create a comprehensive summary report of all build commands and results.
    
#     Args:
#         results_dir: Directory containing build log files
        
#     Returns:
#         Path to the generated summary report
#     """
#     results_path = Path(results_dir)
#     build_logs = list(results_path.glob("*_build_log.txt"))
    
#     summary_file = results_path / "build_commands_summary.txt"
    
#     try:
#         with open(summary_file, 'w', encoding='utf-8') as f:
#             f.write("=" * 80 + "\n")
#             f.write("ANDROID BENCH BUILD COMMANDS SUMMARY\n")
#             f.write("=" * 80 + "\n")
#             f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
#             f.write(f"Total Instances: {len(build_logs)}\n\n")
            
#             # Parse each build log and extract command info
#             targeted_builds = 0
#             default_builds = 0
#             failed_builds = 0
#             command_summary = {}
            
#             for log_file in sorted(build_logs):
#                 instance_id = log_file.stem.replace("_build_log", "")
                
#                 try:
#                     with open(log_file, 'r', encoding='utf-8') as log:
#                         content = log.read()
                    
#                     # Extract build information
#                     build_success = "Build Success: True" in content
#                     build_type = "UNKNOWN"
#                     gradle_command = "UNKNOWN"
#                     targets = []
                    
#                     lines = content.split('\n')
#                     for line in lines:
#                         if line.startswith("Build Type:"):
#                             build_type = line.split(":", 1)[1].strip()
#                         elif line.startswith("Gradle Command:"):
#                             gradle_command = line.split(":", 1)[1].strip()
#                         elif line.startswith("Targets:"):
#                             targets_str = line.split(":", 1)[1].strip()
#                             targets = [t.strip() for t in targets_str.split(",") if t.strip()]
                    
#                     # Count build types
#                     if build_type == "TARGETED":
#                         targeted_builds += 1
#                     elif build_type == "DEFAULT":
#                         default_builds += 1
                    
#                     if not build_success:
#                         failed_builds += 1
                    
#                     # Track command frequency
#                     if gradle_command not in command_summary:
#                         command_summary[gradle_command] = []
#                     command_summary[gradle_command].append({
#                         "instance_id": instance_id,
#                         "success": build_success,
#                         "targets": targets
#                     })
                    
#                     # Write individual instance info
#                     status = "✓" if build_success else "✗"
#                     f.write(f"{status} {instance_id:30} | {build_type:8} | {gradle_command}\n")
                    
#                 except Exception as e:
#                     f.write(f"✗ {instance_id:30} | ERROR   | Failed to parse log: {e}\n")
#                     failed_builds += 1
            
#             # Summary statistics
#             f.write("\n" + "=" * 80 + "\n")
#             f.write("BUILD STATISTICS:\n")
#             f.write("=" * 80 + "\n")
#             f.write(f"Targeted Builds: {targeted_builds}\n")
#             f.write(f"Default Builds:  {default_builds}\n")
#             f.write(f"Failed Builds:   {failed_builds}\n")
#             f.write(f"Success Rate:    {((len(build_logs) - failed_builds) / len(build_logs) * 100):.1f}%\n")
            
#             # Command frequency analysis
#             f.write("\n" + "=" * 80 + "\n")
#             f.write("COMMAND FREQUENCY ANALYSIS:\n")
#             f.write("=" * 80 + "\n")
            
#             for command, instances in sorted(command_summary.items(), key=lambda x: len(x[1]), reverse=True):
#                 if command != "UNKNOWN":
#                     success_count = sum(1 for inst in instances if inst["success"])
#                     f.write(f"\nCommand: {command}\n")
#                     f.write(f"  Used by: {len(instances)} instances\n")
#                     f.write(f"  Success: {success_count}/{len(instances)} ({success_count/len(instances)*100:.1f}%)\n")
                    
#                     # Show unique target combinations
#                     unique_targets = set(tuple(sorted(inst["targets"])) for inst in instances)
#                     f.write(f"  Unique target combinations: {len(unique_targets)}\n")
#                     for targets in sorted(unique_targets):
#                         f.write(f"    - {', '.join(targets) if targets else 'None'}\n")
            
#             f.write("\n" + "=" * 80 + "\n")
#             f.write("END OF REPORT\n")
#             f.write("=" * 80 + "\n")
        
#         logger.info(f"Build summary report saved to: {summary_file}")
#         return str(summary_file)
        
#     except Exception as e:
#         logger.error(f"Failed to create build summary report: {e}")
#         return ""

# Utility function for quick integration
def run_build_step(containers_manager, instance_id: str, 
                   test_patch: str = None, results_dir: str = "validation_results") -> BuildResult:
    """
    Convenience function to run a build test step with automatic test detection.
    Will only run tests if test files are detected in the patch, otherwise logs and continues.
    
    Args:
        containers_manager: Container manager instance
        instance_id: Instance ID to build
        test_patch: Optional test patch to determine specific build targets
        results_dir: Directory to save results
        
    Returns:
        BuildResult object
    """
    build_manager = AndroidBuildManager(results_dir)
    return build_manager.run_tests_for_instance(containers_manager, instance_id, test_patch=test_patch)


# def run_targeted_build_step(containers_manager, instance_id: str, 
#                            test_patch: str, results_dir: str = "validation_results") -> BuildResult:
#     """
#     Convenience function to run a targeted build based on test patch.
    
#     Args:
#         containers_manager: Container manager instance
#         instance_id: Instance ID to build
#         test_patch: Test patch to analyze for build targets
#         results_dir: Directory to save results
        
#     Returns:
#         BuildResult object
#     """
#     build_manager = AndroidBuildManager(results_dir)
#     return build_manager.run_tests_for_instance(containers_manager, instance_id, 600, test_patch)


# def analyze_all_builds(results_dir: str = "validation_results") -> dict:
#     """
#     Analyze all build logs in the results directory.
    
#     Args:
#         results_dir: Directory containing build log files
        
#     Returns:
#         Dictionary with overall build analysis
#     """
#     results_path = Path(results_dir)

#     build_logs = []
#     for instance_dir in results_path.iterdir():
#         if instance_dir.is_dir():
#             build_logs_dir = instance_dir / "build_logs"  
#             if build_logs_dir.exists():
#                 build_logs.extend(build_logs_dir.glob("*.txt"))
    
#     analysis = {
#         "total_builds": len(build_logs),
#         "successful_builds": 0,
#         "failed_builds": 0,
#         "average_duration": 0.0,
#         "common_errors": {},
#         "instances_with_failures": [],
#         "longest_build": {"instance": "", "duration": 0.0},
#         "shortest_build": {"instance": "", "duration": float('inf')}
#     }
    
#     if not build_logs:
#         return analysis
    
#     total_duration = 0.0
#     build_manager = AndroidBuildManager(results_dir)
    
#     for log_file in build_logs:
#         summary = build_manager.get_build_summary(str(log_file))
#         instance_id = summary.get("instance_id", log_file.stem.replace("_build_log", ""))
        
#         if summary.get("success", False):
#             analysis["successful_builds"] += 1
#         else:
#             analysis["failed_builds"] += 1
#             analysis["instances_with_failures"].append(instance_id)
            
#             # Count error types
#             for error in summary.get("main_errors", []):
#                 error_key = error[:50] + "..." if len(error) > 50 else error
#                 analysis["common_errors"][error_key] = analysis["common_errors"].get(error_key, 0) + 1
        
#         # Track duration statistics
#         duration = summary.get("duration", 0.0)
#         total_duration += duration
        
#         if duration > analysis["longest_build"]["duration"]:
#             analysis["longest_build"] = {"instance": instance_id, "duration": duration}
        
#         if duration < analysis["shortest_build"]["duration"] and duration > 0:
#             analysis["shortest_build"] = {"instance": instance_id, "duration": duration}
    
#     # Calculate averages
#     if analysis["total_builds"] > 0:
#         analysis["average_duration"] = total_duration / analysis["total_builds"]
#         analysis["success_rate"] = (analysis["successful_builds"] / analysis["total_builds"]) * 100
    
#     # Sort common errors by frequency
#     analysis["common_errors"] = dict(sorted(
#         analysis["common_errors"].items(), 
#         key=lambda x: x[1], 
#         reverse=True
#     )[:10])  # Top 10 most common errors
    
#     return analysis