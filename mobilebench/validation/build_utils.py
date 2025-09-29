#!/usr/bin/env python3
"""
build_utils.py - Gradle Build Management Utilities

This module handles gradle test execution for Android validation.
"""

import logging
import os
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
    gradle_command: Optional[str] = None


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
                              timeout: int = 600, test_patch: str = None, 
                              phase: str = "UNKNOWN") -> BuildResult:
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
                duration=time.time() - start_time,
                gradle_command=None
            )
        
        # Extract test files from patch
        test_files = self._extract_test_files_from_patch(test_patch)
        if not test_files:
            logger.info(f"[{instance_id}] No test files found in patch - no tests to run, continuing to next instance")
            return BuildResult(
                success=True,
                exit_code=0,
                output="No test files found in patch - no tests to run",
                duration=time.time() - start_time,
                gradle_command=None
            )
        
        logger.info(f"[{instance_id}] Found {len(test_files)} test files - running targeted tests")
        logger.info(f"[{instance_id}] Test files: {test_files}")

        # Determine target modules
        target_modules = list(set(self._extract_module_from_path(tf) for tf in test_files))
        
        # Analyze project structure for variants and flavors
        build_variants = self._detect_build_variants(containers_manager, instance_id, target_modules)
        test_tasks = self._generate_test_tasks(test_files, build_variants, instance_id)
        
        if not test_tasks:
            logger.info(f"[{instance_id}] Could not generate test tasks - no tests to run, continuing to next instance")
            return BuildResult(
                success=True,
                exit_code=0,
                output="Could not generate test tasks - no tests to run",
                duration=time.time() - start_time,
                gradle_command=None
            )
        
        logger.info(f"[{instance_id}] Generated test tasks: {test_tasks}")
        
        # Build the test execution command (ONLY test tasks, no build/compile tasks)
        gradle_command = f"./gradlew {' '.join(test_tasks)} --stacktrace --info --no-daemon --continue"
        logger.info(f"[{instance_id}] TEST-ONLY COMMAND: {gradle_command}")
        
        # Execute the tests
        test_command = f"""
cd /workspace &&
echo "=== Starting Test-Only Execution - PHASE: {phase} ===" &&
echo "Instance ID: {instance_id}" &&
echo "Test Phase: {phase}" &&
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
                                         BuildResult(success, exit_code, output, duration, gradle_command=gradle_command),
                                         command_info, phase)
            
            return BuildResult(
                success=success,
                exit_code=exit_code,
                output=output,
                duration=duration,
                log_file_path=log_file,
                gradle_command=gradle_command
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_output = f"Test execution failed: {str(e)}"
            logger.error(f"Test execution failed for {instance_id}: {e}")
            
            return BuildResult(
                success=False,
                exit_code=1,
                output=error_output,
                duration=duration,
                gradle_command=None
            )

    def _detect_build_variants(self, containers_manager, instance_id: str, target_modules: List[str] = None) -> Dict[str, Any]:
        """
        Detect build variants, flavors, and configurations from the project.
        Uses faster detection with fallbacks to avoid timeouts.
        """
        variants_info = {
            "flavors": ["debug"],  # Default
            "build_types": ["debug"],  # Default
            "modules": [":app"],  # Default
            "test_variants": ["testDebugUnitTest"],
            "module_variants": {}  # Store variants per module
        }

        # Determine which modules to query
        modules_to_query = target_modules or [":app"]

        try:
            all_test_tasks = []
            module_variants = {}

            # First, try a fast approach - check if build.gradle files exist to infer variants
            for module in modules_to_query:
                logger.info(f"[{instance_id}]: Detecting build variants for module: {module}")
                
                # Convert module to path
                module_path = module.replace(':', '/') if module.startswith(':') else module
                if module_path.startswith('/'):
                    module_path = module_path[1:]  # Remove leading slash
                
                # Try fast variant detection first by checking build files
                build_check_command = f"""
cd /workspace &&
# Check if module has foss/full flavors by looking at build files
if [ -d "{module_path}" ]; then
    # Check for flavor-specific configurations
    if grep -r "foss\\|full" {module_path}/build.gradle* {module_path}/src/ 2>/dev/null | head -5; then
        echo "HAS_FLAVORS=true"
    else
        echo "HAS_FLAVORS=false"
    fi
    echo "MODULE_EXISTS=true"
else
    echo "MODULE_EXISTS=false"
fi
"""
                
                exit_code, output = containers_manager.exec_command(
                    instance_id, build_check_command, workdir="/workspace", timeout=30
                )
                
                # Apply module-specific variant selection rules
                module_tasks = []
                
                # Apply hardcoded rules based on module patterns
                if module in [":app-thunderbird", ":app-k9mail"]:
                    # App modules use foss flavors
                    module_tasks = [
                        "testFossDebugUnitTest",
                        "testFullDebugUnitTest", 
                        "testFossReleaseUnitTest",
                        "testFullReleaseUnitTest"
                    ]
                    logger.info(f"[{instance_id}]: Module {module} configured for foss flavors - using foss/full variants")
                elif module == ":AnkiDroid":
                    # AnkiDroid module uses play variant with debug build type
                    module_tasks = [
                        "testPlayDebugUnitTest"
                    ]
                    logger.info(f"[{instance_id}]: Module {module} configured for play variant - using play debug variant")
                elif module == ":WordPress":
                    # WordPress Android module uses WordPressVanilla flavor with debug build type
                    module_tasks = [
                        "testWordPressVanillaDebugUnitTest"
                    ]
                    logger.info(f"[{instance_id}]: Module {module} configured for WordPress flavor - using WordPressVanilla variant")
                elif "antennapod" in str(instance_id).lower() and (module in [":model", ":event", ":ui:episodes", ":ui:common", ":ui:app-start-intent", ":ui:i18n", ":ui:notifications", ":storage:preferences", ":playback:base", ":parser:feed", ":parser:media", ":parser:transcript", ":net:sync:service-interface", ":net:sync:gpoddernet"]):
                    # Specific AntennaPod modules use debug variants
                    module_tasks = [
                        "testDebugUnitTest",
                        "testReleaseUnitTest"
                    ]
                    logger.info(f"[{instance_id}]: Module {module} configured for specific AntennaPod modules - using debug/release variants")
                elif "antennapod" in str(instance_id).lower():
                    # Other AntennaPod modules use free/play flavors
                    module_tasks = [
                        "testFreeDebugUnitTest",
                        "testPlayDebugUnitTest"
                    ]
                    logger.info(f"[{instance_id}]: Module {module} configured for general AntennaPod flavors - using free/play variants")
                elif module.startswith(":feature:") or module == ":legacy:core":
                    # Feature modules and legacy:core use simple variants
                    module_tasks = [
                        "testDebugUnitTest",
                        "testReleaseUnitTest"
                    ]
                    logger.info(f"[{instance_id}]: Module {module} configured for simple variants - using debug/release variants")
                else:
                    # Default fallback for other modules
                    module_tasks = ["testDebugUnitTest"]
                    logger.info(f"[{instance_id}]: Module {module} using default variants")
                
                # Try to verify with a quick gradle command if we have time
                if module_tasks and len(module_tasks) > 1:  # Only verify if we detected flavors
                    verify_command = f"""
cd /workspace &&
timeout 20 ./gradlew {module}:tasks --group=verification --console=plain 2>/dev/null | grep -E "test.*UnitTest" | head -10 || echo "VERIFICATION_FAILED"
"""
                    
                    verify_exit_code, verify_output = containers_manager.exec_command(
                        instance_id, verify_command, workdir="/workspace", timeout=30
                    )
                    
                    if verify_exit_code == 0 and "VERIFICATION_FAILED" not in verify_output and verify_output.strip():
                        # Parse actual tasks from verification
                        verified_tasks = []
                        for line in verify_output.split('\n'):
                            line = line.strip()
                            if 'test' in line.lower() and 'unittest' in line.lower():
                                # Extract task name (first word)
                                task_name = line.split()[0] if line.split() else ""
                                if task_name and ':' not in task_name:
                                    verified_tasks.append(task_name)
                        
                        if verified_tasks:
                            module_tasks = verified_tasks
                            logger.info(f"[{instance_id}]: Verified tasks for {module}: {verified_tasks}")
                
                # Store module-specific variants
                module_variants[module] = module_tasks
                all_test_tasks.extend(module_tasks)
                logger.info(f"[{instance_id}]: Module {module} final tasks: {module_tasks}")

            # Store module-specific variants in the result
            variants_info["module_variants"] = module_variants
                
            if all_test_tasks:
                variants_info["test_variants"] = list(set(all_test_tasks))  # Remove duplicates
                logger.info(f"[{instance_id}] Detected test variants: {all_test_tasks}")
            
            # Extract build flavors and types from task names
            flavors = set()
            build_types = set()
            for task in all_test_tasks:
                # Parse patterns like "testDebugUnitTest", "testWordPressVanillaDebugUnitTest", "testFreeDebugUnitTest"
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
                        # Handle WordPress specific flavors
                        if 'wordpressvanilla' in middle:
                            flavors.add('WordPressVanilla')
                        else:
                            flavors.add(middle.capitalize())
            
            if flavors:
                variants_info["flavors"] = list(flavors)
            if build_types:
                variants_info["build_types"] = list(build_types)
                    
        except Exception as e:
            logger.warning(f"[{instance_id}] Could not detect build variants: {e}")
        
        return variants_info

    def _generate_test_tasks(self, test_files: List[str], build_variants: Dict[str, Any], instance_id: str) -> List[str]:
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
        
        # Get module-specific variants
        module_variants = build_variants.get("module_variants", {})
        logger.info(f"Module-specific variants detected: {module_variants}")
        
        # Generate tasks for each module
        for module, test_dict in module_tests.items():
            unit_tests = test_dict["unit"]
            instrumented_tests = test_dict["instrumented"]
            
            # Get available test variants for this specific module
            available_variants = module_variants.get(module, build_variants.get("test_variants", ["testDebugUnitTest"]))
            logger.info(f"Available variants for module {module}: {available_variants}")
            
            # Process unit tests
            if unit_tests:
                # Find appropriate unit test variant for this module following exact requirements:
                # 1. If module has testDebugUnitTest -> use testDebugUnitTest
                # 2. If module has testFossDebugUnitTest -> use testFossDebugUnitTest
                unit_variant = None
                
                # Apply module-specific variant selection rules
                if module in [":app-thunderbird", ":app-k9mail"]:
                    # App modules should use testFossDebugUnitTest
                    if 'testFossDebugUnitTest' in available_variants:
                        unit_variant = 'testFossDebugUnitTest'
                        logger.info(f"Selected testFossDebugUnitTest for {module} (app module rule)")
                elif module == ":AnkiDroid":
                    # AnkiDroid module should use testPlayDebugUnitTest
                    if 'testPlayDebugUnitTest' in available_variants:
                        unit_variant = 'testPlayDebugUnitTest'
                        logger.info(f"Selected testPlayDebugUnitTest for {module} (AnkiDroid module rule)")
                elif module == ":WordPress":
                    # WordPress Android module should use testWordPressVanillaDebugUnitTest
                    if 'testWordPressVanillaDebugUnitTest' in available_variants:
                        unit_variant = 'testWordPressVanillaDebugUnitTest'
                        logger.info(f"Selected testWordPressVanillaDebugUnitTest for {module} (WordPress module rule)")
                elif "antennapod" in str(instance_id).lower() and (module in [":model", ":event", ":ui:episodes", ":ui:common", ":ui:app-start-intent", ":ui:i18n", ":ui:notifications", ":storage:preferences", ":playback:base", ":parser:feed", ":parser:media", ":parser:transcript", ":net:sync:service-interface", ":net:sync:gpoddernet"]):
                    # Specific AntennaPod modules should use testDebugUnitTest
                    if 'testDebugUnitTest' in available_variants:
                        unit_variant = 'testDebugUnitTest'
                        logger.info(f"Selected testDebugUnitTest for {module} (specific AntennaPod module rule)")
                elif "antennapod" in str(instance_id).lower():
                    # Other AntennaPod modules should use testFreeDebugUnitTest
                    if 'testFreeDebugUnitTest' in available_variants:
                        unit_variant = 'testFreeDebugUnitTest'
                        logger.info(f"Selected testFreeDebugUnitTest for {module} (general AntennaPod module rule)")
                elif module.startswith(":feature:") or module == ":legacy:core":
                    # Feature modules and legacy:core should use testDebugUnitTest
                    if 'testDebugUnitTest' in available_variants:
                        unit_variant = 'testDebugUnitTest'
                        logger.info(f"Selected testDebugUnitTest for {module} (feature/legacy module rule)")
                else:
                    # Default modules use testDebugUnitTest
                    if 'testDebugUnitTest' in available_variants:
                        unit_variant = 'testDebugUnitTest'
                        logger.info(f"Selected testDebugUnitTest for {module} (default rule)")
                
                # Strategy 2: If neither exact variant found, look for other test variants (excluding detekt)
                if not unit_variant:
                    simple_test_variants = []
                    for variant in available_variants:
                        if (variant.lower().startswith('test') and 
                            'unittest' in variant.lower() and 
                            'debug' in variant.lower() and
                            'detekt' not in variant.lower()):  # Exclude detekt tasks
                            simple_test_variants.append(variant)
                    
                    if simple_test_variants:
                        # Sort to prioritize: WordPressVanilla > foss > free > debug > full
                        def variant_sort_key(variant_name):
                            v_lower = variant_name.lower()
                            if 'wordpressvanilla' in v_lower:
                                return (0, len(variant_name), variant_name)  # Highest priority for WordPress
                            elif 'foss' in v_lower:
                                return (1, len(variant_name), variant_name)  # High priority
                            elif 'free' in v_lower:
                                return (2, len(variant_name), variant_name)  
                            elif 'debug' in v_lower and 'full' not in v_lower:
                                return (3, len(variant_name), variant_name)
                            elif 'full' in v_lower:
                                return (4, len(variant_name), variant_name)  # Lowest priority
                            else:
                                return (5, len(variant_name), variant_name)
                        
                        simple_test_variants.sort(key=variant_sort_key)
                        unit_variant = simple_test_variants[0]
                        logger.info(f"Found {len(simple_test_variants)} simple test variants for {module}: {simple_test_variants}, selected: {unit_variant}")
                
                # Strategy 3: Final fallback to any unittest variant (including detekt) if no test variants found
                if not unit_variant:
                    matching_variants = []
                    for variant in available_variants:
                        if 'unittest' in variant.lower() and 'debug' in variant.lower():
                            matching_variants.append(variant)
                    
                    if matching_variants:
                        # Sort to make selection deterministic and prefer certain variants
                        # Priority: WordPressVanilla > foss > free > debug > full (lower number = higher priority)
                        def variant_sort_key(variant_name):
                            v_lower = variant_name.lower()
                            if 'wordpressvanilla' in v_lower:
                                return (0, len(variant_name), variant_name)  # Highest priority for WordPress
                            elif 'foss' in v_lower:
                                return (1, len(variant_name), variant_name)  # High priority
                            elif 'free' in v_lower:
                                return (2, len(variant_name), variant_name)  
                            elif 'debug' in v_lower and 'full' not in v_lower:
                                return (3, len(variant_name), variant_name)
                            elif 'full' in v_lower:
                                return (4, len(variant_name), variant_name)  # Lowest priority
                            else:
                                return (5, len(variant_name), variant_name)
                        
                        matching_variants.sort(key=variant_sort_key)
                        unit_variant = matching_variants[0]
                        logger.info(f"Found {len(matching_variants)} fallback matching variants for {module}: {matching_variants}, selected: {unit_variant}")
                
                # Strategy 4: Absolute final fallback
                if not unit_variant:
                    unit_variant = "testDebugUnitTest"
                    logger.warning(f"No suitable variants found for {module}, falling back to default: {unit_variant}")
                
                logger.info(f"Selected variant for module {module}: {unit_variant}")
                
                # Build the task - always include module prefix for consistency
                base_task = f"{module}:{unit_variant}"
                
                # Add test class filters
                test_filters = ' '.join([f'--tests "{tc}"' for tc in unit_tests])
                full_task = f"{base_task} {test_filters}".strip()
                tasks.append(full_task)
                
                logger.info(f"Generated unit test task for {module}: {full_task}")
        
        return tasks

    def _extract_test_class_from_file(self, test_file: str) -> Optional[str]:
        """
        Extract the test class name from a test file path.
        
        Examples:
        - app/src/test/java/com/example/MyTest.java -> com.example.MyTest
        - net/download/service/src/test/java/de/danoeh/antennapod/net/download/service/episode/autodownload/DbReaderTest.java 
        -> de.danoeh.antennapod.net.download.service.episode.autodownload.DbReaderTest
        
        Filters out utility/helper classes that shouldn't be run as test classes.
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
            
            # Check if this is a utility/helper class that should be filtered out
            if self._is_utility_class_name(class_name):
                logger.debug(f"Skipping utility class: {class_name} from file {test_file}")
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
                full_class_name = f"{package_name}.{class_name}"
            else:
                # Fallback: just return the class name
                full_class_name = class_name
            
            # Additional check: verify this is an actual test class by examining the file
            if not self._is_actual_test_class(test_file):
                logger.debug(f"Skipping non-test class: {full_class_name} from file {test_file}")
                return None
                
            return full_class_name
                
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
            "BUILD FAILED",
            "build failed",
            "compilation error",
            "Execution failed for task"
        ]
        
        output_lower = output.lower()
        
        # CRITICAL FIX: Check for compilation failures FIRST, before test execution indicators
        # This ensures that BUILD FAILED always takes precedence over other indicators
        if any(failure in output_lower for failure in compilation_failures):
            logger.warning("Compilation failure detected - marking as unsuccessful")
            return False
        
        # If we see test execution indicators and no compilation failures, consider it successful
        if any(indicator in output_lower for indicator in test_execution_indicators):
            logger.info("Test execution detected - marking as successful even with possible test failures")
            return True
        
        # If exit code is 0 and no failures detected, assume tests ran successfully
        if exit_code == 0:
            logger.info("Exit code 0 with no compilation failures detected - marking as successful")
            return True

        # Default: if exit code is not 0 and no clear indicators, consider failed
        logger.warning(f"No clear test execution indicators found, exit code {exit_code} - marking as unsuccessful")
        return False

    def _save_test_log(self, instance_id: str, test_result: BuildResult, 
                      command_info: Dict[str, Any] = None, phase: str = "UNKNOWN") -> str:
        """
        Save test execution log for an instance.
        
        Args:
            instance_id: ID of the instance
            test_result: The test result to save
            command_info: Optional dictionary with command information
            phase: The execution phase (e.g., BUILD-PRE-SOLUTION, TEST-PRE-SOLUTION)
            
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
                f.write(f"Phase: {phase}\n")
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
    
    def _is_utility_class_name(self, class_name: str) -> bool:
        """
        Check if a class name indicates it's a utility/helper class that shouldn't be run as a test.
        
        Based on the filtering logic from config.py but simplified for build_utils usage.
        """
        # Patterns that indicate utility/helper classes (not actual test classes)
        utility_patterns = [
            'Mock',           # MockPop3Server, MockSmtpServer, MockHttpServer
            'Fake',           # FakeDataSource, FakeRepository
            'Stub',           # StubEmailProvider, StubNotificationService
            'Dummy',          # DummyObject, DummyData
            'Helper',         # TestHelper, DatabaseHelper
            'Util',           # TestUtil, StringUtil
            'Utils',          # TestUtils, FileUtils
            'Factory',        # TestFactory, ObjectFactory
            'Builder',        # TestBuilder, DataBuilder
            'Fixture',        # TestFixture, DataFixture
            'Base',           # BaseTest, BaseTestCase (often abstract)
            'Abstract',       # AbstractTest, AbstractTestCase
            'Support',        # TestSupport, SupportClass
            'Common',         # CommonTestData, CommonHelper
            'Shared',         # SharedTestData, SharedHelper
            'TestData',       # TestDataProvider, TestDataConstants
            'Constants',      # TestConstants, DatabaseConstants
            'Config',         # TestConfig, TestConfiguration
            'Setup',          # TestSetup, DatabaseSetup
            'Harness',        # TestHarness, FrameworkHarness
            'Framework',      # TestFramework, BaseFramework
            'Rule',           # TestRule, CustomRule (JUnit rules)
            'Extension',      # TestExtension, JUnitExtension
            'Listener',       # TestListener, ResultListener
            'Runner',         # TestRunner, CustomRunner
            'Suite',          # TestSuite, IntegrationTestSuite
            'Category',       # TestCategory, SlowTests
            'Tag',            # TestTags, CategoryTags
            'Matcher',        # CustomMatcher, TestMatcher
            'Assertion',      # CustomAssertion, TestAssertion
            'Verifier',       # TestVerifier, ResultVerifier
            'Provider',       # DataProvider, ServiceProvider
            'Generator',      # DataGenerator, TestDataGenerator
            'Creator',        # ObjectCreator, EntityCreator
            'Server',         # TestServer, MockServer
            'Client',         # TestClient, MockClient
            'Service',        # TestService, MockService (when not actual test classes)
            'Repository',     # TestRepository, MockRepository (when not actual test classes)
            'Database',       # TestDatabase, DatabaseTestSupport
            'Schema',         # TestSchema, DatabaseSchema
            'Migration',      # TestMigration, DatabaseMigration
            'Container',      # TestContainer, MockContainer
            'Context',        # TestContext, ApplicationContext
            'Environment',    # TestEnvironment, MockEnvironment
            'Interceptor',    # TestInterceptor, MockInterceptor
            'Adapter',        # TestAdapter, MockAdapter
            'Wrapper',        # TestWrapper, ServiceWrapper
            'Proxy',          # TestProxy, MockProxy
            'Handler',        # TestHandler, MockHandler
            'Processor',      # TestProcessor, DataProcessor
            'Validator',      # TestValidator, InputValidator
            'Converter',      # TestConverter, DataConverter
            'Transformer',    # TestTransformer, DataTransformer
            'Serializer',     # TestSerializer, JsonSerializer
            'Deserializer',   # TestDeserializer, JsonDeserializer
            'Parser',         # TestParser, XmlParser
            'Formatter',      # TestFormatter, DateFormatter
            'Calculator',     # TestCalculator, PriceCalculator
            'Engine',         # TestEngine, CalculationEngine
            'Manager',        # TestManager, ResourceManager (when not actual test classes)
            'Controller',     # TestController, MockController (when not actual test classes)
            'Component',      # TestComponent, MockComponent (when not actual test classes)
        ]
        
        # Check if class name starts with any utility pattern
        for pattern in utility_patterns:
            if class_name.startswith(pattern) or class_name.endswith(pattern):
                return True
        
        # Check for specific known problematic classes
        known_utility_classes = [
            'MockPop3Server',
            'MockSmtpServer', 
            'MockImapServer',
            'TestUtils',
            'TestHelper',
            'TestBase',
            'BaseTestCase',
            'AbstractTestCase',
            'TestConstants',
            'TestData',
            'TestConfig'
        ]
        
        if class_name in known_utility_classes:
            return True
        
        # Check for interface-like patterns (often not test classes)
        if (class_name.startswith('I') and len(class_name) > 1 and 
            class_name[1].isupper()):  # ITestInterface pattern
            return True
        
        return False
    
    def _is_actual_test_class(self, test_file: str) -> bool:
        """
        Check if a file represents an actual test class with test methods,
        not a utility/helper/mock class.
        
        This is a simplified version that doesn't read file contents for performance.
        The main filtering is done by _is_utility_class_name.
        """
        
        # Get just the filename for checking
        filename = os.path.basename(test_file)
        
        # Check if it's a utility class that should be excluded
        if filename.endswith('.java'):
            class_name = filename[:-5]
        elif filename.endswith('.kt'):
            class_name = filename[:-3]
        else:
            return False
        
        # Apply utility class filtering
        if self._is_utility_class_name(class_name):
            return False
        
        # If we can't definitively determine it's a utility class, assume it's a test class
        # This prevents false negatives where we skip actual test files
        return True
    
    def _extract_modules_from_targets(self, targets: List[str]) -> Set[str]:
        """Extract unique modules from build targets."""
        modules = set()
        for target in targets:
            if ':' in target:
                module = target.split(':')[0]
                if module:  # Skip empty string for targets starting with ':'
                    modules.add(module)
        return modules


# Utility function for quick integration
def run_build_step(containers_manager, instance_id: str, 
                   test_patch: str = None, results_dir: str = "validation_results",
                   phase: str = "UNKNOWN") -> BuildResult:
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
    return build_manager.run_tests_for_instance(containers_manager, instance_id, test_patch=test_patch, phase=phase)