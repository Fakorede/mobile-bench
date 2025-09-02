#!/usr/bin/env python3
"""
Parallel test execution strategy for Android validation.
"""

import re
import json
import logging
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Represents a single test result."""
    test_name: str
    class_name: str
    status: str  # PASSED, FAILED, SKIPPED, ERROR
    duration: float = 0.0
    failure_message: str = ""
    error_message: str = ""


@dataclass
class TestExecutionResult:
    """Represents complete test execution results."""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    exit_code: int
    raw_output: str
    test_results: List[TestResult]
    build_successful: bool = False


class AndroidTestingParallel:
    """Handles Android test execution with parallel optimization."""
    
    def __init__(self, containers_manager, config_parser):
        self.containers = containers_manager
        self.config_parser = config_parser
        
    def run_tests_from_patch(self, instance_id: str, test_patch: str, 
                           config: Dict[str, str]) -> Tuple[TestExecutionResult, List[str]]:
        """Run tests based on test patch content with module-specific optimization."""
        
        # Extract module information directly from patch file paths
        module_tests, skipped_instrumented_tests = self.config_parser.extract_test_tasks_from_patch_by_module(test_patch)
        
        # Count total unit tests
        total_unit_tests = sum(len(tests) for tests in module_tests.values())
        
        if not module_tests:
            logger.warning(f"No unit test classes found in patch for {instance_id}")
            if skipped_instrumented_tests:
                logger.info(f"Only instrumented tests found, all {len(skipped_instrumented_tests)} skipped for {instance_id}")
            
            return TestExecutionResult(
                total_tests=0, passed=0, failed=0, skipped=0, errors=0,
                duration=0.0, exit_code=0, raw_output="No unit test classes found in test patch",
                test_results=[], build_successful=True
            ), skipped_instrumented_tests
        
        logger.info(f"Running {total_unit_tests} unit tests across {len(module_tests)} modules for {instance_id}")
        logger.info(f"Test distribution by module: {dict((k, len(v)) for k, v in module_tests.items())}")
        if skipped_instrumented_tests:
            logger.info(f"Skipped {len(skipped_instrumented_tests)} instrumented tests for {instance_id}")
        
        # Use module-specific execution strategy
        test_result = self.run_module_specific_tests(instance_id, config, module_tests)
        return test_result, skipped_instrumented_tests
    
    def _detect_build_variants_for_testing(self, instance_id: str) -> Dict[str, any]:
        """
        Detect build variants for testing - simplified version of build_utils logic.
        This should ideally be extracted to a shared utility.
        """
        variants_info = {
            "flavors": ["debug"],
            "build_types": ["debug"],
            "modules": [":app"],
            "test_variants": ["testDebugUnitTest"]
        }
        
        try:
            # Try to get project info from Gradle
            gradle_info_command = """
cd /workspace &&
if [ -f './gradlew' ]; then
    timeout 60 ./gradlew tasks --group=verification --quiet 2>/dev/null || \
    echo "Could not get task info"
fi
"""
            
            exit_code, output = self.containers.exec_command(
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
                        
                        # Remove build types
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
   
    def run_module_specific_tests(self, instance_id: str, config: Dict[str, str], 
                                 module_tests: Dict[str, List[str]]) -> TestExecutionResult:
        """
        Run tests targeting specific modules with their test classes.
        
        FIXED VERSION: No longer hardcoded to WordPress, integrates with build variant detection.
        """
        
        start_time = time.time()
        java_version = config.get('java_version', '17')
        
        # Detect build variants dynamically (like build_utils.py does)
        logger.info(f"Detecting build variants for {instance_id}")
        build_variants = self._detect_build_variants_for_testing(instance_id)
        available_variants = build_variants.get("test_variants", ["testDebugUnitTest"])
        
        logger.info(f"Available test variants: {available_variants}")
        logger.info(f"Detected flavors: {build_variants.get('flavors', [])}")
        logger.info(f"Detected build types: {build_variants.get('build_types', [])}")
        
        # Build module-specific test commands
        module_commands = []
        for module, test_classes in module_tests.items():
            if test_classes:
                # Find appropriate unit test variant (same logic as build_utils.py)
                unit_variant = None
                for variant in available_variants:
                    if 'unittest' in variant.lower() and 'debug' in variant.lower():
                        unit_variant = variant
                        break
                
                # Fallback to first unit test variant or default
                if not unit_variant:
                    unit_variants = [v for v in available_variants if 'unittest' in v.lower()]
                    unit_variant = unit_variants[0] if unit_variants else "testDebugUnitTest"
                
                logger.info(f"Selected variant for module {module}: {unit_variant}")
                
                # Create test filters for this module
                test_filters = ' '.join([f'--tests "{test_class}"' for test_class in test_classes])
                
                # Build task (consistent with build_utils.py logic)
                if module == ":app":
                    # For :app module, don't add module prefix (consistent with build_utils.py)
                    module_commands.append(f'{unit_variant} {test_filters}')
                else:
                    # For other modules, add module prefix
                    module_commands.append(f'{module}:{unit_variant} {test_filters}')
                
                logger.info(f"Generated command for module {module}: {unit_variant} with {len(test_classes)} test classes")

        if not module_commands:
            logger.warning(f"No module commands generated for {instance_id}")
            return TestExecutionResult(
                total_tests=0, passed=0, failed=0, skipped=0, errors=0,
                duration=0.0, exit_code=0, raw_output="No module commands generated",
                test_results=[], build_successful=True
            )
        
        gradle_test_command = ' '.join(module_commands)
        total_timeout = min(1800, len(module_commands) * 600)  # 10 minutes per module, max 30 minutes
        
        logger.info(f"Final Gradle command: ./gradlew {gradle_test_command}")
        
        test_command = f"""
cd /workspace &&
echo "=== Running module-specific tests ===" &&
echo "Instance: {instance_id}" &&
echo "Modules: {list(module_tests.keys())}" &&
echo "Command: ./gradlew {gradle_test_command}" &&
echo "Detected variants: {available_variants}" &&
echo "Detected flavors: {build_variants.get('flavors', [])}" &&

# Java setup
echo "=== Setting Java version to {java_version} ===" &&
case {java_version} in
    8) export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 ;;
    11) export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 ;;
    17) export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ;;
    21) export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ;;
esac
if [ -d "$JAVA_HOME" ]; then export PATH="$JAVA_HOME/bin:$PATH"; fi

# Android environment setup
echo "=== Setting up Android environment ===" &&
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_ROOT='/opt/android-sdk'
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle

# Configure Gradle for module-specific execution
echo "=== Configuring Gradle for module-specific execution ===" &&
cat > /tmp/.gradle/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.configureondemand=true
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Stopping existing Gradle daemons ===" &&
./gradlew --stop 2>/dev/null || true &&

if [ -f './gradlew' ]; then
    chmod +x ./gradlew
    
    echo "=== Running module-specific tests ===" &&
    echo "Executing: ./gradlew {gradle_test_command} --no-daemon --stacktrace --continue --parallel" &&
    timeout {total_timeout} ./gradlew {gradle_test_command} --no-daemon --stacktrace --continue --parallel || echo "Module-specific test execution completed"
else
    echo "ERROR: No gradlew found in workspace"
fi &&

echo "=== Test execution completed ===" &&
echo "Exit code: $?" &&

echo "=== Collecting test results ===" &&
find . -name "TEST-*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== XML FILE: $file ===" 
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END XML FILE ==="
done &&

find . -path "*/test-results/*" -name "*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== TEST RESULT: $file ===" 
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END TEST RESULT ==="
done
"""
        
        logger.info(f"Executing module-specific tests for {instance_id}")
        logger.info(f"Modules being tested: {list(module_tests.keys())}")
        logger.info(f"Total test classes: {sum(len(classes) for classes in module_tests.values())}")
        
        exit_code, output = self.containers.exec_command(
            instance_id,
            test_command,
            workdir="/workspace",
            timeout=total_timeout + 60  # Buffer time
        )
        
        total_duration = time.time() - start_time
        logger.info(f"Module-specific test execution completed in {total_duration:.2f}s with exit code {exit_code}")
        
        # Parse results
        test_results = self._parse_test_results(output)
        return self._create_execution_result(test_results, exit_code, output, total_duration)

    def run_parallel_tests(self, instance_id: str, config: Dict[str, str], 
                          test_tasks: List[str]) -> Tuple[TestExecutionResult, List[str]]:
        """
        Fallback method for backward compatibility.
        Try to extract modules from test tasks if patch-based extraction fails.
        """
        
        start_time = time.time()
        
        # Extract test classes from tasks
        test_classes = self._extract_test_classes_from_tasks(test_tasks)
        
        if test_classes and len(test_classes) > 1:
            # Use module-based approach for multiple test classes
            module_tests = {}
            for test_class in test_classes:
                module = self._infer_module_from_class(test_class)
                if module not in module_tests:
                    module_tests[module] = []
                module_tests[module].append(test_class)
            
            logger.info(f"Using inferred modules for {instance_id}: {dict(module_tests)}")
            test_result = self.run_module_specific_tests(instance_id, config, module_tests)
            return test_result, []  # No instrumented tests detected in fallback mode
        else:
            # Use module-based approach for single test or fallback
            test_result = self._run_module_based_tests(instance_id, config, test_tasks, start_time)
            return test_result, []  # No instrumented tests detected in fallback mode
    
    def _infer_module_from_class(self, test_class: str) -> str:
        """Infer the Gradle module from the test class package structure (fallback method)."""
        # Try to extract from package structure
        # e.g., net.thunderbird.feature.notification.impl -> :feature:notification:impl
        parts = test_class.split('.')
        
        # Handle common Android/Java package patterns
        if len(parts) >= 3:
            # Skip common root packages
            if parts[0] in ['net', 'com', 'org', 'de'] and len(parts) >= 4:
                # Skip org/company name (e.g., net.thunderbird, com.example, de.danoeh.antennapod)
                start_idx = 2
                if parts[0] == 'de' and len(parts) >= 5:  # de.danoeh.antennapod case
                    start_idx = 3
                
                module_parts = parts[start_idx:]
                # Remove class name (last part)
                module_parts = module_parts[:-1] if module_parts else []
                if module_parts:
                    return ':' + ':'.join(module_parts)
            else:
                # Handle cases without common prefixes
                module_parts = parts[:-1]  # Remove class name
                if module_parts:
                    return ':' + ':'.join(module_parts)
        
        # Default fallback
        return ':app'

    def _extract_test_classes_from_tasks(self, test_tasks: List[str]) -> List[str]:
        """Extract individual test class names from test tasks."""
        test_classes = []
        
        for task in test_tasks:
            # Extract class name from "--tests ClassName" pattern
            match = re.search(r'--tests\s+([^\s]+)', task)
            if match:
                test_classes.append(match.group(1))
        
        return test_classes
    
    def _run_combined_gradle_tests(self, instance_id: str, config: Dict[str, str], 
                                  test_classes: List[str], start_time: float) -> TestExecutionResult:
        """Run all test classes in a single Gradle invocation for maximum parallelism."""
        
        java_version = config.get('java_version', '17')
        test_variant = config.get('test_variant', 'debug')
        
        # Build single command with all test classes
        test_filters = ' '.join([f'--tests "{test_class}"' for test_class in test_classes])
        
        # Increased timeout for combined execution
        total_timeout = 3600  # 60 minutes for combined tests
        
        test_command = f"""
cd /workspace &&
echo "=== Running combined parallel tests ===" &&

# Java setup (same as before)
echo "=== Setting Java version to {java_version} ===" &&
if command -v jenv &> /dev/null; then
    eval "$(jenv init -)"
    jenv global {java_version} || jenv global {java_version}.0 || echo 'Failed to set Java version with jenv'
else
    case {java_version} in
        8) export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 ;;
        11) export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 ;;
        17) export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ;;
        21) export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ;;
    esac
    if [ -d "$JAVA_HOME" ]; then
        export PATH="$JAVA_HOME/bin:$PATH"
    fi
fi

# Environment setup
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_HOME='/opt/android-sdk'
export ANDROID_SDK_ROOT='/opt/android-sdk'
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle

# Clean builds
echo "=== Cleaning previous builds ===" &&
rm -rf build/ app/build/ */build/ .gradle/ /tmp/.gradle/caches/ /tmp/.gradle/daemon/ || true

# Configure Gradle for parallel execution
echo "=== Configuring Gradle for parallel execution ===" &&
cat > /tmp/.gradle/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.configureondemand=false
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Stopping existing Gradle daemons ===" &&
./gradlew --stop 2>/dev/null || true &&

if [ -f './gradlew' ]; then
    chmod +x ./gradlew
    
    echo "=== Downloading dependencies ===" &&
    timeout 600 ./gradlew --no-daemon dependencies || echo "Dependencies download completed/failed, continuing..." &&
    
    echo "=== Running all tests in parallel ===" &&
    echo "Test filters: {test_filters}" &&
    timeout {total_timeout} ./gradlew test{test_variant.capitalize()}UnitTest {test_filters} --no-daemon --stacktrace --info --continue --parallel || echo "Combined test execution completed with issues"
else
    echo "No gradlew found"
fi &&

echo "=== Collecting test results ===" &&
find . -name "TEST-*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== XML FILE: $file ===" 
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END XML FILE ==="
done &&

find . -path "*/test-results/*" -name "*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== TEST RESULT: $file ===" 
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END TEST RESULT ==="
done
"""
        
        logger.info(f"Executing combined parallel tests for {instance_id}")
        
        exit_code, output = self.containers.exec_command(
            instance_id,
            test_command,
            workdir="/workspace",
            timeout=total_timeout + 60  # Buffer time
        )
        
        total_duration = time.time() - start_time
        logger.info(f"Combined test execution completed in {total_duration:.2f}s with exit code {exit_code}")
        
        # Parse results
        test_results = self._parse_test_results(output)
        return self._create_execution_result(test_results, exit_code, output, total_duration)
    
    def _run_module_based_tests(self, instance_id: str, config: Dict[str, str], 
                               test_tasks: List[str], start_time: float) -> TestExecutionResult:
        """Run tests grouped by module for better parallelism."""
        
        java_version = config.get('java_version', '17')
        test_variant = config.get('test_variant', 'debug')
        
        # Group tasks by module
        modules = set()
        for task in test_tasks:
            if '--tests' in task:
                # Extract potential module from class name
                match = re.search(r'--tests\s+([^\s]+)', task)
                if match:
                    class_name = match.group(1)
                    # Infer module from package structure
                    if '.' in class_name:
                        parts = class_name.split('.')
                        if len(parts) >= 3:  # e.g., net.thunderbird.feature -> :feature
                            potential_module = f":{parts[2]}" if len(parts) > 2 else ""
                            if potential_module:
                                modules.add(potential_module)
        
        if not modules:
            modules = {":app", ":feature:*"}  # Default modules
        
        module_tasks = [f"{module}:test{test_variant.capitalize()}UnitTest" for module in modules]
        
        test_command = f"""
cd /workspace &&
echo "=== Running module-based parallel tests ===" &&

# Java and environment setup (same as combined)
echo "=== Setting Java version to {java_version} ===" &&
case {java_version} in
    8) export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 ;;
    11) export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 ;;
    17) export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ;;
    21) export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ;;
esac
if [ -d "$JAVA_HOME" ]; then export PATH="$JAVA_HOME/bin:$PATH"; fi

export ANDROID_HOME='/opt/android-sdk'
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle

# Configure for parallel execution
cat > /tmp/.gradle/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m -XX:+UseG1GC
EOF

if [ -f './gradlew' ]; then
    chmod +x ./gradlew
    ./gradlew --stop 2>/dev/null || true
    
    echo "=== Running module tests: {' '.join(module_tasks)} ===" &&
    timeout 2400 ./gradlew {' '.join(module_tasks)} --no-daemon --stacktrace --continue --parallel || echo "Module tests completed"
fi &&

# Collect results (same as before)
find . -name "TEST-*.xml" -type f 2>/dev/null | while read file; do
    echo "=== XML: $file ===" && cat "$file" 2>/dev/null && echo "=== END ==="
done
"""
        
        exit_code, output = self.containers.exec_command(
            instance_id, test_command, workdir="/workspace", timeout=2500
        )
        
        total_duration = time.time() - start_time
        test_results = self._parse_test_results(output)
        return self._create_execution_result(test_results, exit_code, output, total_duration)
    
    def _parse_test_results(self, output: str) -> List[TestResult]:
        """Parse test results from output with deduplication."""
        test_results = []
        seen_tests = set()  # Track unique test identifiers
        
        # Parse XML sections
        xml_sections = re.findall(r'=== XML(?:\s+FILE)?:\s*(.+?)\s*===\s*\n(.*?)\n=== END', output, re.DOTALL)
        xml_sections.extend(re.findall(r'=== TEST RESULT:\s*(.+?)\s*===\s*\n(.*?)\n=== END', output, re.DOTALL))
        
        logger.debug(f"Found {len(xml_sections)} XML sections to parse")
        
        for file_path, xml_content in xml_sections:
            parsed_tests = self._parse_xml_content(xml_content)
            logger.debug(f"Parsed {len(parsed_tests)} tests from {file_path}")
            
            # Deduplicate tests based on class + method combination
            for test in parsed_tests:
                # Create unique identifier for each test
                test_key = f"{test.class_name}.{test.test_name}"
                
                if test_key not in seen_tests:
                    seen_tests.add(test_key)
                    test_results.append(test)
                    logger.debug(f"Added test: {test_key} ({test.status})")
                else:
                    logger.debug(f"Skipping duplicate test: {test_key}")
        
        logger.info(f"Final test results: {len(test_results)} unique tests")
        return test_results
    
    def _parse_xml_content(self, xml_content: str) -> List[TestResult]:
        """Parse XML test results."""
        test_results = []
        testcase_pattern = r'<testcase[^>]*name="([^"]+)"[^>]*classname="([^"]+)"[^>]*(?:time="([^"]*)")?[^>]*(?:/>|>(.*?)</testcase>)'
        testcases = re.findall(testcase_pattern, xml_content, re.DOTALL)
        
        for match in testcases:
            test_name, class_name = match[0].strip(), match[1].strip()
            duration = float(match[2]) if match[2] else 0.0
            test_content = match[3] if len(match) > 3 else ""
            
            status = "PASSED"
            failure_msg = error_msg = ""
            
            if test_content:
                if '<failure' in test_content:
                    status = "FAILED"
                    failure_match = re.search(r'<failure[^>]*>(.*?)</failure>', test_content, re.DOTALL)
                    if failure_match:
                        failure_msg = failure_match.group(1).strip()
                elif '<error' in test_content:
                    status = "ERROR"
                    error_match = re.search(r'<error[^>]*>(.*?)</error>', test_content, re.DOTALL)
                    if error_match:
                        error_msg = error_match.group(1).strip()
                elif '<skipped' in test_content:
                    status = "SKIPPED"
            
            test_results.append(TestResult(
                test_name=test_name, class_name=class_name, status=status,
                duration=duration, failure_message=failure_msg, error_message=error_msg
            ))
        
        return test_results
    
    def _create_execution_result(self, test_results: List[TestResult], 
                               exit_code: int, raw_output: str, 
                               duration: float) -> TestExecutionResult:
        """Create execution result summary."""
        total_tests = len(test_results)
        passed = len([t for t in test_results if t.status == 'PASSED'])
        failed = len([t for t in test_results if t.status == 'FAILED'])
        skipped = len([t for t in test_results if t.status == 'SKIPPED'])
        errors = len([t for t in test_results if t.status == 'ERROR'])
        
        build_successful = ('BUILD SUCCESSFUL' in raw_output or 
                          ('BUILD FAILED' not in raw_output and exit_code == 0))
        
        return TestExecutionResult(
            total_tests=total_tests, passed=passed, failed=failed,
            skipped=skipped, errors=errors, duration=duration,
            exit_code=exit_code, raw_output=raw_output,
            test_results=test_results, build_successful=build_successful
        )
    
    def compare_test_results(self, pre_results: TestExecutionResult, 
                           post_results: TestExecutionResult) -> Dict[str, List[str]]:
        """Compare test results (same as original)."""
        pre_tests = {f"{t.class_name}.{t.test_name}": t.status 
                    for t in pre_results.test_results}
        post_tests = {f"{t.class_name}.{t.test_name}": t.status 
                     for t in post_results.test_results}
        
        fail_to_pass = []
        pass_to_pass = []
        pass_to_fail = []
        fail_to_fail = []
        
        all_tests = set(pre_tests.keys()) | set(post_tests.keys())
        
        for test_name in all_tests:
            pre_status = pre_tests.get(test_name, 'NOT_FOUND')
            post_status = post_tests.get(test_name, 'NOT_FOUND')
            
            if pre_status in ['FAILED', 'ERROR'] and post_status == 'PASSED':
                fail_to_pass.append(test_name)
            elif pre_status == 'PASSED' and post_status == 'PASSED':
                pass_to_pass.append(test_name)
            elif pre_status == 'PASSED' and post_status in ['FAILED', 'ERROR']:
                pass_to_fail.append(test_name)
            elif pre_status in ['FAILED', 'ERROR'] and post_status in ['FAILED', 'ERROR']:
                fail_to_fail.append(test_name)
        
        return {
            'fail_to_pass': fail_to_pass,
            'pass_to_pass': pass_to_pass,
            'pass_to_fail': pass_to_fail,
            'fail_to_fail': fail_to_fail
        }