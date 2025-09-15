#!/usr/bin/env python3
"""
Parallel test execution strategy for Android validation.
"""

import re
import json
import logging
import time
from typing import Dict, List, Tuple, Optional, Any
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
    gradle_command: str = ""


class AndroidTestingParallel:
    """Handles Android test execution with parallel optimization."""
    
    def __init__(self, containers_manager, config_parser):
        self.containers = containers_manager
        self.config_parser = config_parser
        
    def run_tests_from_patch(self, instance_id: str, test_patch: str, 
                           config: Dict[str, str], phase: str = "UNKNOWN", workdir: str = "/workspace") -> Tuple[TestExecutionResult, List[str]]:
        """Run tests based on test patch content with module-specific optimization."""
        
        # Log the test phase at the beginning
        logger.info(f"=== STARTING {phase} TEST PHASE for {instance_id} ===")
        
        # Extract module information directly from patch file paths
        module_tests, skipped_instrumented_tests = self.config_parser.extract_test_tasks_from_patch_by_module(test_patch)
        
        # CRITICAL: Validate that modules still exist after solution patch application
        # This prevents "project not found" errors when solution patches change project structure
        logger.info(f"[{instance_id}] Validating module availability for {phase} phase...")
        module_tests = self._validate_and_fix_module_tests(instance_id, module_tests, workdir)
        
        # Count total unit tests after validation
        total_unit_tests = sum(len(tests) for tests in module_tests.values())
        
        if not module_tests:
            logger.warning(f"No valid unit test modules found for {instance_id} in {phase} phase")
            if skipped_instrumented_tests:
                logger.info(f"Only instrumented tests found, all {len(skipped_instrumented_tests)} skipped for {instance_id}")
            
            return TestExecutionResult(
                total_tests=0, passed=0, failed=0, skipped=0, errors=0,
                duration=0.0, exit_code=0, raw_output=f"No valid unit test modules found after project validation in {phase} phase",
                test_results=[], build_successful=True, gradle_command=""
            ), skipped_instrumented_tests
        
        logger.info(f"Running {total_unit_tests} unit tests across {len(module_tests)} modules for {instance_id} in {phase} phase")
        logger.info(f"Test distribution by module: {dict((k, len(v)) for k, v in module_tests.items())}")
        if skipped_instrumented_tests:
            logger.info(f"Skipped {len(skipped_instrumented_tests)} instrumented tests for {instance_id}")
        
        # Use module-specific execution strategy
        test_result = self.run_module_specific_tests(instance_id, config, module_tests, phase, workdir)
        return test_result, skipped_instrumented_tests
    
    def _detect_build_variants_for_testing(self, instance_id: str, target_modules: List[str] = None) -> Dict[str, any]:
        """
        Detect build variants for testing - using the same sophisticated logic as build_utils.py.
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

            # Apply module-specific variant selection rules (same as build_utils.py)
            for module in modules_to_query:
                logger.info(f"[{instance_id}]: Detecting build variants for module: {module}")

                # Apply hardcoded rules based on module patterns  
                module_tasks = []
                
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
                
                # Store module-specific variants
                module_variants[module] = module_tasks
                all_test_tasks.extend(module_tasks)
                logger.info(f"[{instance_id}]: Module {module} final tasks: {module_tasks}")

            # Store module-specific variants in the result
            variants_info["module_variants"] = module_variants
                
            if all_test_tasks:
                variants_info["test_variants"] = list(set(all_test_tasks))  # Remove duplicates
                logger.info(f"[{instance_id}] Detected test variants: {all_test_tasks}")
            
            # Extract build flavors and types from task names (same logic as build_utils.py)
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

    def _detect_available_projects(self, instance_id: str, workdir: str = "/workspace") -> List[str]:
        """
        Detect currently available projects/modules in the workspace.
        This is crucial after solution patches that might change project structure.
        """
        try:
            # Run gradle projects command to get current project structure
            projects_command = f"""
cd {workdir} &&
timeout 30 ./gradlew projects --quiet 2>/dev/null || echo "Failed to get projects"
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id, projects_command, workdir=workdir, timeout=45
            )
            
            available_projects = []
            if exit_code == 0 and output:
                lines = output.split('\n')
                for line in lines:
                    line = line.strip()
                    # Look for project entries like "Project ':core'" or "+--- Project ':core'"
                    if 'project' in line.lower() and ':' in line:
                        # Extract project name
                        parts = line.split("'")
                        if len(parts) >= 2:
                            project_name = parts[1]  # Should be like ":core"
                            if project_name.startswith(':') and project_name != ':':
                                available_projects.append(project_name)
                
            logger.info(f"[{instance_id}] Available projects detected: {available_projects}")
            return available_projects
            
        except Exception as e:
            logger.warning(f"[{instance_id}] Failed to detect available projects: {e}")
            return []

    def _validate_and_fix_module_tests(self, instance_id: str, module_tests: Dict[str, List[str]], workdir: str = "/workspace") -> Dict[str, List[str]]:
        """
        Validate that modules still exist and remove/fix any that don't.
        This is essential after solution patches that might change project structure.
        """
        available_projects = self._detect_available_projects(instance_id, workdir)
        if not available_projects:
            logger.warning(f"[{instance_id}] Could not detect available projects, proceeding with original modules")
            return module_tests
        
        validated_module_tests = {}
        removed_modules = []
        
        for module, test_classes in module_tests.items():
            if module in available_projects:
                validated_module_tests[module] = test_classes
            else:
                removed_modules.append(module)
                logger.warning(f"[{instance_id}] Module {module} no longer available, removing from test execution")
        
        if removed_modules:
            logger.info(f"[{instance_id}] Removed unavailable modules: {removed_modules}")
            logger.info(f"[{instance_id}] Available modules for testing: {list(available_projects)}")
        
        return validated_module_tests
   
    def run_module_specific_tests(self, instance_id: str, config: Dict[str, str], 
                                 module_tests: Dict[str, List[str]], phase: str = "UNKNOWN", workdir: str = "/workspace") -> TestExecutionResult:
        """
        Run tests targeting specific modules with their test classes.
        
        ENHANCED VERSION: Uses the same sophisticated variant detection and selection logic as build_utils.py.
        """
        
        start_time = time.time()
        java_version = config.get('java_version', '17')
        
        # Log the test phase information
        logger.info(f"=== {phase} TEST EXECUTION STARTING ===")
        
        # Extract target modules for variant detection
        target_modules = list(module_tests.keys())
        
        # Detect build variants dynamically using the same logic as build_utils.py
        logger.info(f"Detecting build variants for {instance_id}")
        build_variants = self._detect_build_variants_for_testing(instance_id, target_modules)
        
        # Get module-specific variants (same as build_utils.py)
        module_variants = build_variants.get("module_variants", {})
        logger.info(f"Module-specific variants detected: {module_variants}")
        
        available_variants = build_variants.get("test_variants", ["testDebugUnitTest"])
        logger.info(f"Available test variants: {available_variants}")
        logger.info(f"Detected flavors: {build_variants.get('flavors', [])}")
        logger.info(f"Detected build types: {build_variants.get('build_types', [])}")
        
        # Build module-specific test commands using the same logic as build_utils.py
        module_commands = []
        for module, test_classes in module_tests.items():
            if test_classes:
                # Get available test variants for this specific module (same as build_utils.py)
                available_variants_for_module = module_variants.get(module, build_variants.get("test_variants", ["testDebugUnitTest"]))
                logger.info(f"Available variants for module {module}: {available_variants_for_module}")
                
                # Find appropriate unit test variant for this module following exact requirements:
                # 1. If module has testDebugUnitTest -> use testDebugUnitTest
                # 2. If module has testFossDebugUnitTest -> use testFossDebugUnitTest
                unit_variant = None
                
                # Apply module-specific variant selection rules 
                if module in [":app-thunderbird", ":app-k9mail"]:
                    # App modules should use testFossDebugUnitTest
                    if 'testFossDebugUnitTest' in available_variants_for_module:
                        unit_variant = 'testFossDebugUnitTest'
                        logger.info(f"Selected testFossDebugUnitTest for {module} (app module rule)")
                elif module == ":AnkiDroid":
                    # AnkiDroid module should use testPlayDebugUnitTest
                    if 'testPlayDebugUnitTest' in available_variants_for_module:
                        unit_variant = 'testPlayDebugUnitTest'
                        logger.info(f"Selected testPlayDebugUnitTest for {module} (AnkiDroid module rule)")
                elif module == ":WordPress":
                    # WordPress Android module should use testWordPressVanillaDebugUnitTest
                    if 'testWordPressVanillaDebugUnitTest' in available_variants_for_module:
                        unit_variant = 'testWordPressVanillaDebugUnitTest'
                        logger.info(f"Selected testWordPressVanillaDebugUnitTest for {module} (WordPress module rule)")
                elif module.startswith(":feature:") or module == ":legacy:core":
                    # Feature modules and legacy:core should use testDebugUnitTest
                    if 'testDebugUnitTest' in available_variants_for_module:
                        unit_variant = 'testDebugUnitTest'
                        logger.info(f"Selected testDebugUnitTest for {module} (feature/legacy module rule)")
                else:
                    # Default modules use testDebugUnitTest
                    if 'testDebugUnitTest' in available_variants_for_module:
                        unit_variant = 'testDebugUnitTest'
                        logger.info(f"Selected testDebugUnitTest for {module} (default rule)")
                
                # Strategy 2: If neither exact variant found, look for other test variants (excluding detekt)
                if not unit_variant:
                    simple_test_variants = []
                    for variant in available_variants_for_module:
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
                
                # Strategy 3: Fallback to any unittest variant (including detekt) if no test variants found
                if not unit_variant:
                    matching_variants = []
                    for variant in available_variants_for_module:
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
                
                # Create test filters for this module
                test_filters = ' '.join([f'--tests "{test_class}"' for test_class in test_classes])
                
                # Build task (consistent with build_utils.py logic)
                if module == ":app":
                    # For :app module, don't add module prefix (consistent with build_utils.py)
                    module_commands.append(f'{unit_variant} {test_filters}')
                else:
                    # For other modules, add module prefix (consistent with build_utils.py)
                    module_commands.append(f'{module}:{unit_variant} {test_filters}')
                
                logger.info(f"Generated command for module {module}: {unit_variant} with {len(test_classes)} test classes")

        if not module_commands:
            logger.warning(f"No module commands generated for {instance_id}")
            return TestExecutionResult(
                total_tests=0, passed=0, failed=0, skipped=0, errors=0,
                duration=0.0, exit_code=0, raw_output="No module commands generated",
                test_results=[], build_successful=True, gradle_command=""
            )
        
        gradle_test_command = ' '.join(module_commands)
        total_timeout = min(1800, len(module_commands) * 600)  # 10 minutes per module, max 30 minutes
        
        logger.info(f"Final Gradle command: ./gradlew {gradle_test_command}")
        
        test_command = f"""
cd {workdir} &&
echo "=== Running module-specific tests - PHASE: {phase} ===" &&
echo "Test Phase: {phase}" &&
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
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.lang.invoke=ALL-UNNAMED --add-opens java.prefs/java.util.prefs=ALL-UNNAMED --add-opens java.base/java.nio.charset=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED
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
            workdir=workdir,
            timeout=total_timeout + 60  # Buffer time
        )
        
        total_duration = time.time() - start_time
        logger.info(f"Module-specific test execution completed in {total_duration:.2f}s with exit code {exit_code}")
        
        # Check for critical project structure errors that completely prevent test execution
        # Only treat as error if exit code indicates failure AND we have project not found errors
        if exit_code != 0 and "project" in output.lower() and "not found" in output.lower():
            logger.error(f"[{instance_id}] Project structure changed after solution patch application")
            logger.error(f"[{instance_id}] Original modules: {list(module_tests.keys())}")
            
            # Try to detect current available projects and provide helpful info
            available_projects = self._detect_available_projects(instance_id)
            logger.error(f"[{instance_id}] Currently available projects: {available_projects}")
            
            # Return a special error result indicating project structure change
            return TestExecutionResult(
                total_tests=0, passed=0, failed=0, skipped=0, errors=1,
                duration=total_duration, exit_code=exit_code, 
                raw_output=f"SOLUTION PATCH CHANGED PROJECT STRUCTURE - Original modules {list(module_tests.keys())} no longer available. Current projects: {available_projects}. Full output: {output}",
                test_results=[], build_successful=False, gradle_command=gradle_test_command
            )
        elif "project" in output.lower() and "not found" in output.lower():
            # Log project structure changes as informational, but continue processing
            logger.error(f"[{instance_id}] Project structure changed after solution patch application")
            logger.error(f"[{instance_id}] Original modules: {list(module_tests.keys())}")
            
            # Try to detect current available projects and provide helpful info
            available_projects = self._detect_available_projects(instance_id)
            logger.error(f"[{instance_id}] Currently available projects: {available_projects}")
        
        # Parse results
        test_results = self._parse_test_results(output)
        execution_result = self._create_execution_result(test_results, exit_code, output, total_duration, gradle_test_command)
        
        # Save test log with phase information
        command_info = {
            'execution_type': 'MODULE_SPECIFIC',
            'gradle_command': gradle_test_command,
            'modules': list(module_tests.keys()),
            'test_classes': [class_name for classes in module_tests.values() for class_name in classes]
        }
        
        self._save_test_log(instance_id, execution_result, phase, command_info)
        
        return execution_result

    def run_parallel_tests(self, instance_id: str, config: Dict[str, str], 
                          test_tasks: List[str], phase: str = "UNKNOWN") -> Tuple[TestExecutionResult, List[str]]:
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
            test_result = self.run_module_specific_tests(instance_id, config, module_tests, phase)
            return test_result, []  # No instrumented tests detected in fallback mode
        else:
            # Use module-based approach for single test or fallback
            test_result = self._run_module_based_tests(instance_id, config, test_tasks, start_time, phase)
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
                                  test_classes: List[str], start_time: float, 
                                  phase: str = "UNKNOWN") -> TestExecutionResult:
        """Run all test classes in a single Gradle invocation for maximum parallelism."""
        
        java_version = config.get('java_version', '17')
        
        # Build single command with all test classes
        test_filters = ' '.join([f'--tests "{test_class}"' for test_class in test_classes])
        
        # Use simplified variant detection for fallback
        try:
            build_variants = self._detect_build_variants_for_testing(instance_id)
            available_variants = build_variants.get("test_variants", ["testDebugUnitTest"])
            
            # Find appropriate unit test variant with deterministic selection
            unit_variant = "testDebugUnitTest"  # fallback default
            matching_variants = []
            for variant in available_variants:
                if 'unittest' in variant.lower() and 'debug' in variant.lower():
                    matching_variants.append(variant)
            
            if matching_variants:
                # Sort for deterministic selection - prefer longer/more specific variants
                matching_variants.sort(key=lambda x: (-len(x), x.lower()))
                unit_variant = matching_variants[0]
            
            logger.info(f"Using variant for combined tests: {unit_variant}")
        except Exception as e:
            logger.warning(f"Variant detection failed, using default: {e}")
            unit_variant = "testDebugUnitTest"
        
        # Increased timeout for combined execution
        total_timeout = 3600  # 60 minutes for combined tests
        
        test_command = f"""
cd /workspace &&
echo "=== Running combined parallel tests - PHASE: {phase} ===" &&

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
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m -XX:+UseG1GC --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.lang.invoke=ALL-UNNAMED --add-opens java.prefs/java.util.prefs=ALL-UNNAMED --add-opens java.base/java.nio.charset=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED
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
    timeout {total_timeout} ./gradlew {unit_variant} {test_filters} --no-daemon --stacktrace --info --continue --parallel || echo "Combined test execution completed with issues"
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
        gradle_command = f"./gradlew {unit_variant} {test_filters}"
        execution_result = self._create_execution_result(test_results, exit_code, output, total_duration, gradle_command)
        
        # Save test log with phase information
        command_info = {
            'execution_type': 'COMBINED_PARALLEL',
            'gradle_command': gradle_command,
            'modules': [],
            'test_classes': test_classes
        }
        
        self._save_test_log(instance_id, execution_result, phase, command_info)
        
        return execution_result
    
    def _run_module_based_tests(self, instance_id: str, config: Dict[str, str], 
                               test_tasks: List[str], start_time: float, 
                               phase: str = "UNKNOWN") -> TestExecutionResult:
        """Run tests grouped by module for better parallelism."""
        
        java_version = config.get('java_version', '17')
        
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
        
        # Use simplified variant detection for fallback
        try:
            build_variants = self._detect_build_variants_for_testing(instance_id)
            available_variants = build_variants.get("test_variants", ["testDebugUnitTest"])
            
            # Find appropriate unit test variant with deterministic selection
            unit_variant = "testDebugUnitTest"  # fallback default
            matching_variants = []
            for variant in available_variants:
                if 'unittest' in variant.lower() and 'debug' in variant.lower():
                    matching_variants.append(variant)
            
            if matching_variants:
                # Sort for deterministic selection - prefer longer/more specific variants
                matching_variants.sort(key=lambda x: (-len(x), x.lower()))
                unit_variant = matching_variants[0]
            
            logger.info(f"Using variant for module-based tests: {unit_variant}")
        except Exception as e:
            logger.warning(f"Variant detection failed, using default: {e}")
            unit_variant = "testDebugUnitTest"
        
        module_tasks = [f"{module}:{unit_variant}" for module in modules]
        
        test_command = f"""
cd /workspace &&
echo "=== Running module-based parallel tests - PHASE: {phase} ===" &&

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
        gradle_command = ' '.join(module_tasks)
        execution_result = self._create_execution_result(test_results, exit_code, output, total_duration, gradle_command)
        
        # Save test log with phase information
        command_info = {
            'execution_type': 'MODULE_BASED_FALLBACK',
            'gradle_command': gradle_command,
            'modules': list(modules),
            'test_classes': []  # Not easily extractable from test_tasks in this fallback method
        }
        
        self._save_test_log(instance_id, execution_result, phase, command_info)
        
        return execution_result
    
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
                               duration: float, gradle_command: str = "") -> TestExecutionResult:
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
            test_results=test_results, build_successful=build_successful,
            gradle_command=gradle_command
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
    
    def _save_test_log(self, instance_id: str, test_result: TestExecutionResult, 
                      phase: str, command_info: Dict[str, Any] = None) -> str:
        """
        Save test execution log for an instance.
        
        Args:
            instance_id: ID of the instance
            test_result: The test result to save
            phase: Test phase (TEST-PRE-SOLUTION, TEST-POST-SOLUTION)
            command_info: Optional dictionary with command information
            
        Returns:
            Path to the saved log file
        """
        import time
        from pathlib import Path
        
        # Create test logs directory
        results_dir = Path("validation_results")
        instance_test_dir = results_dir / instance_id / "test_logs"
        instance_test_dir.mkdir(exist_ok=True, parents=True)
        
        # Create filename with phase identifier
        phase_suffix = phase.replace("TEST-", "").replace("-", "_").lower()
        log_file = instance_test_dir / f"test_log_{phase_suffix}_{int(time.time())}.txt"
        
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"Android Test Execution Log\n")
                f.write(f"Instance ID: {instance_id}\n")
                f.write(f"Test Phase: {phase}\n")
                f.write(f"Test Success: {test_result.build_successful}\n")
                f.write(f"Exit Code: {test_result.exit_code}\n")
                f.write(f"Duration: {test_result.duration:.2f} seconds\n")
                f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total Tests: {test_result.total_tests}\n")
                f.write(f"Passed: {test_result.passed}\n")
                f.write(f"Failed: {test_result.failed}\n")
                f.write(f"Skipped: {test_result.skipped}\n")
                f.write(f"Errors: {test_result.errors}\n")
                
                # Add command info if provided
                if command_info:
                    f.write(f"Execution Type: {command_info.get('execution_type', 'MODULE_SPECIFIC')}\n")
                    f.write(f"Gradle Command: {command_info.get('gradle_command', 'UNKNOWN')}\n")
                    f.write(f"Test Modules: {command_info.get('modules', [])}\n")
                    f.write(f"Test Classes: {command_info.get('test_classes', [])}\n")
                    if 'error' in command_info:
                        f.write(f"Error: {command_info['error']}\n")
                
                f.write("=" * 60 + "\n")
                f.write("TEST OUTPUT:\n")
                f.write("=" * 60 + "\n")
                f.write(test_result.raw_output)
                
                if test_result.test_results:
                    f.write("\n" + "=" * 60 + "\n")
                    f.write("DETAILED TEST RESULTS:\n")
                    f.write("=" * 60 + "\n")
                    for test in test_result.test_results:
                        f.write(f"{test.class_name}.{test.test_name}: {test.status}\n")
                        if test.failure_message:
                            f.write(f"  Failure: {test.failure_message}\n")
                        if test.error_message:
                            f.write(f"  Error: {test.error_message}\n")
                        if test.duration > 0:
                            f.write(f"  Duration: {test.duration:.3f}s\n")
                        f.write("\n")
            
            logger.info(f"Test log saved to: {log_file}")
            return str(log_file)
        except Exception as e:
            logger.error(f"Failed to save test log for {instance_id}: {e}")
            return ""