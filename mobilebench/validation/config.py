#!/usr/bin/env python3
"""
Android project configuration parser with better Kotlin Multiplatform support
and improved test class filtering to exclude utility/helper classes.
"""

import re
import os
import logging
from typing import Dict, Optional, List, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidConfig:
    """Parses Android project configuration to extract build requirements."""
    
    # Based on mingc/android-build-box:latest available versions
    SUPPORTED_JAVA_VERSIONS = ['8', '11', '17', '21']
    SUPPORTED_GRADLE_VERSIONS = ['6.5', '6.9', '7.0', '7.1', '7.2', '7.3', '7.4', '7.5', '7.6', '8.0', '8.1']
    SUPPORTED_SDK_VERSIONS = range(16, 36)  # API 16-35 (expanded to support older projects)
    DEFAULT_BUILD_TOOLS = '35.0.0'
    
    def __init__(self, project_path: str, forced_java_version: str = None):
        self.project_path = Path(project_path)
        self.forced_java_version = forced_java_version
        self.config = self._get_default_config()
        
    def _get_default_config(self) -> Dict[str, str]:
        """Return default configuration based on mingc/android-build-box.
        These are FALLBACK values only - actual values should be detected from project."""
        return {
            'java_version': '8',  # Safe default - will be adjusted based on Gradle/AGP requirements
            'gradle_version': '7.4',  # Conservative default
            'compile_sdk': '30',  # Conservative default
            'target_sdk': '30',
            'min_sdk': '21',
            'build_tools': self.DEFAULT_BUILD_TOOLS,
            'ndk_version': None,
            'jvm_args': '-Xmx4096m',
            'test_variant': 'debug',
            'stub_generation_method': 'patch_based'  # 'patch_based' or 'file_merging'
        }
    
    def parse_build_config(self) -> Dict[str, str]:
        """Parse all configuration files and return build requirements."""
        logger.info(f"Parsing Android configuration for {self.project_path}")
        logger.info(f"Starting with default config: {self.config}")
        
        # Parse in order of priority (AGP version detection is critical)
        logger.info("Step 1: Parsing gradle wrapper...")
        self._parse_gradle_wrapper()
        logger.info(f"After gradle wrapper: {self.config}")
        
        logger.info("Step 2: Parsing gradle properties...")
        self._parse_gradle_properties()
        logger.info(f"After gradle properties: {self.config}")
        
        logger.info("Step 3: Parsing project gradle...")
        self._parse_project_gradle()  # This now detects AGP and sets Java accordingly
        logger.info(f"After project gradle: {self.config}")
        
        logger.info("Step 4: Parsing app gradle...")
        self._parse_app_gradle()
        logger.info(f"After app gradle: {self.config}")
        
        logger.info("Step 5: Determining test variant...")
        self._determine_test_variant()
        logger.info(f"After test variant: {self.config}")
        
        # Apply forced Java version if specified (overrides all auto-detection)
        if self.forced_java_version:
            logger.info(f"Step 6: Applying forced Java version: {self.forced_java_version}")
            self.config['java_version'] = self.forced_java_version
            logger.info(f"After forced Java version: {self.config}")
        
        # Final validation and adjustment
        logger.info("Validating config...")
        self._validate_config()
        
        logger.info(f"Final configuration: {self.config}")
        return self.config
    
    def _parse_gradle_wrapper(self):
        """Parse gradle-wrapper.properties for gradle version."""
        wrapper_file = self.project_path / "gradle" / "wrapper" / "gradle-wrapper.properties"
        
        if not wrapper_file.exists():
            logger.warning(f"Gradle wrapper not found: {wrapper_file}")
            return
            
        try:
            content = wrapper_file.read_text(encoding='utf-8')
            
            # Extract gradle version from distributionUrl
            # CRITICAL: Use the ACTUAL detected version for Java compatibility check
            # even if we map it to a different supported version for execution
            patterns = [
                r'gradle-(\d+\.\d+(?:\.\d+)?)-',
                r'distributionUrl=.*gradle-(\d+\.\d+(?:\.\d+)?)-'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    detected_version = match.group(1)
                    logger.info(f"Detected Gradle version from wrapper: {detected_version}")
                    
                    # Determine which version to use for execution
                    if detected_version in self.SUPPORTED_GRADLE_VERSIONS:
                        execution_version = detected_version
                        logger.info(f"Using detected Gradle version: {execution_version}")
                    else:
                        # Find closest supported version
                        execution_version = self._find_closest_version(detected_version, self.SUPPORTED_GRADLE_VERSIONS)
                        logger.warning(f"Gradle {detected_version} not in supported list, will use closest: {execution_version}")
                    
                    self.config['gradle_version'] = execution_version
                    
                    # CRITICAL: Use the ACTUAL detected version for Java compatibility
                    self._ensure_java_gradle_compatibility(detected_version)
                    break
                    
        except Exception as e:
            logger.error(f"Error parsing gradle wrapper: {e}")
    
    def _parse_gradle_properties(self):
        """Parse gradle.properties for JVM arguments."""
        gradle_props = self.project_path / "gradle.properties"
        
        if not gradle_props.exists():
            return
            
        try:
            content = gradle_props.read_text(encoding='utf-8')
            
            # Extract JVM args
            jvm_pattern = r'org\.gradle\.jvmargs\s*=\s*(.+)'
            match = re.search(jvm_pattern, content)
            if match:
                jvm_args = match.group(1).strip()
                # Clean up the args
                jvm_args = re.sub(r'["\']', '', jvm_args)
                self.config['jvm_args'] = jvm_args
                logger.info(f"Found JVM args: {jvm_args}")
                
        except Exception as e:
            logger.error(f"Error parsing gradle.properties: {e}")
    
    def _parse_project_gradle(self):
        """Parse project-level build.gradle for Java version and AGP version."""
        gradle_file_found = None
        for gradle_file in ['build.gradle', 'build.gradle.kts']:
            project_gradle = self.project_path / gradle_file
            if project_gradle.exists():
                gradle_file_found = project_gradle
                break
        else:
            print("DEBUG: Project build.gradle not found")
            return
            
        try:
            logger.info(f"Parsing project build file: {gradle_file_found}")
            content = project_gradle.read_text(encoding='utf-8')
            
            # First check AGP version which determines minimum Java requirement
            agp_version = self._detect_agp_version(content)
            agp_min_java = None
            if agp_version:
                agp_min_java = self._get_java_version_for_agp(agp_version)
                if agp_min_java:
                    logger.info(f"AGP {agp_version} requires minimum Java {agp_min_java}")
            else:
                logger.warning("No AGP version detected in project build file")
            
            # Extract Java version from various patterns
            # Use the detected value unless it conflicts with AGP minimum
            java_patterns = [
                # Java toolchain (modern Gradle/Android)
                r'java\s*\{[^}]*toolchain\.languageVersion\s*=\s*JavaLanguageVersion\.of\((\d+)\)',
                r'toolchain\s*\{[^}]*languageVersion\s*=\s*JavaLanguageVersion\.of\((\d+)\)',
                r'languageVersion\s*=\s*JavaLanguageVersion\.of\((\d+)\)',
                # Traditional compatibility settings
                r'sourceCompatibility\s*[=:]\s*JavaVersion\.VERSION_(\d+)',
                r'targetCompatibility\s*[=:]\s*JavaVersion\.VERSION_(\d+)',
                r'jvmTarget\s*[=:]\s*["\'](\d+)["\']',
                r'JavaVersion\.VERSION_(\d+)',
                r'compileOptions\s*\{[^}]*sourceCompatibility\s*[=:]\s*JavaVersion\.VERSION_(\d+)',
                r'kotlinOptions\s*\{[^}]*jvmTarget\s*[=:]\s*["\'](\d+)["\']',
                # Direct version numbers
                r'sourceCompatibility\s*[=:]\s*["\'](\d+)["\']',
                r'targetCompatibility\s*[=:]\s*["\'](\d+)["\']',
                r'javaVersion\s*[=:]\s*["\'](\d+)["\']'
            ]
            
            java_version_found = False
            for i, pattern in enumerate(java_patterns):
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    detected_java = match.group(1)
                    java_version_found = True
                    logger.info(f"Detected Java version {detected_java} from build file using pattern {i+1}")
                    
                    # Map to supported version if needed
                    if detected_java in self.SUPPORTED_JAVA_VERSIONS:
                        mapped_java = detected_java
                    else:
                        mapped_java = self._map_java_version(detected_java)
                        logger.warning(f"Java {detected_java} not in supported list, mapped to {mapped_java}")
                    
                    # Use detected value, but respect AGP minimum if we found one
                    if agp_min_java:
                        if int(mapped_java) < int(agp_min_java):
                            logger.warning(f"Detected Java {mapped_java} is below AGP minimum {agp_min_java}, using {agp_min_java}")
                            self.config['java_version'] = agp_min_java
                        else:
                            logger.info(f"Using detected Java {mapped_java} (meets AGP minimum {agp_min_java})")
                            self.config['java_version'] = mapped_java
                    else:
                        logger.info(f"Using detected Java {mapped_java}")
                        self.config['java_version'] = mapped_java
                    break
            
            # If no Java version detected but AGP requires a minimum, use that minimum
            if not java_version_found and agp_min_java:
                logger.info(f"No Java version detected in build file, using AGP minimum: {agp_min_java}")
                self.config['java_version'] = agp_min_java
            elif not java_version_found:
                logger.warning(f"No Java version patterns matched in {gradle_file_found}")
                logger.debug(f"File content preview (first 1000 chars): {content[:1000]}")
                # Keep default value (Java 8)
                    
        except Exception as e:
            logger.error(f"Error parsing project build.gradle: {e}")
    
    def _detect_agp_version(self, content: str) -> Optional[str]:
        """Detect Android Gradle Plugin version from build.gradle content."""
        # Common AGP version patterns
        agp_patterns = [
            r'com\.android\.tools\.build:gradle:(\d+\.\d+(?:\.\d+)?)',
            r'id\s*\(\s*["\']com\.android\.application["\']\s*\)\s*version\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
            r'id\s*["\']com\.android\.application["\']\s*version\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
            r'classpath\s*["\']com\.android\.tools\.build:gradle:(\d+\.\d+(?:\.\d+)?)["\']'
        ]
        
        for pattern in agp_patterns:
            match = re.search(pattern, content)
            if match:
                agp_version = match.group(1)
                logger.info(f"Detected AGP version: {agp_version}")
                return agp_version
        
        # Also check in gradle.properties or gradle/libs.versions.toml
        catalog_version = self._check_version_catalogs()
        if catalog_version:
            return catalog_version
        
        return None
    
    def _check_version_catalogs(self) -> Optional[str]:
        """Check gradle/libs.versions.toml for AGP version."""
        version_catalog = self.project_path / "gradle" / "libs.versions.toml"
        print(f"DEBUG: Checking version catalog: {version_catalog}")
        if version_catalog.exists():
            try:
                content = version_catalog.read_text(encoding='utf-8')
                print(f"DEBUG: Version catalog content preview: {content[:300]}...")
                agp_patterns = [
                    r'agp\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
                    r'android-gradle\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
                    r'androidGradlePlugin\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']'
                ]
                
                for i, pattern in enumerate(agp_patterns):
                    match = re.search(pattern, content)
                    print(f"DEBUG: Pattern {i+1} ({pattern}): {'Match' if match else 'No match'}")
                    if match:
                        agp_version = match.group(1)
                        print(f"DEBUG: Detected AGP version from catalog: {agp_version}")
                        return agp_version
            except Exception as e:
                print(f"DEBUG: Error reading version catalog: {e}")
        else:
            print(f"DEBUG: Version catalog does not exist")
        
        return None
    
    def _get_java_version_for_agp(self, agp_version: str) -> Optional[str]:
        """Get MINIMUM required Java version for Android Gradle Plugin version.
        Returns the minimum - actual version may be higher if detected from build files."""
        try:
            version_parts = [int(x) for x in agp_version.split('.')]
            major = version_parts[0]
            minor = version_parts[1] if len(version_parts) > 1 else 0
            
            # AGP version to MINIMUM Java version mapping
            # Based on official Android Gradle Plugin requirements
            if major >= 8 or (major == 7 and minor >= 4):
                # AGP 7.4+ requires minimum Java 17
                return '17'
            elif major >= 7 or (major == 4 and minor >= 2):
                # AGP 4.2+ to 7.3 requires minimum Java 11
                return '11'
            else:
                # Older AGP versions require minimum Java 8
                return '8'
                
        except Exception as e:
            logger.warning(f"Error parsing AGP version {agp_version}: {e}")
            return None
    
    def _ensure_java_gradle_compatibility(self, gradle_version: str):
        """
        Ensure Java version is compatible with Gradle version.
        Only adjusts if there's an incompatibility - doesn't force specific versions.
        
        Gradle version compatibility (official requirements):
        - Gradle 8.8+: Java 17-21
        - Gradle 8.5-8.7: Java 17-20  
        - Gradle 8.0-8.4: Java 17-19
        - Gradle 7.6: Java 8-19
        - Gradle 7.0-7.5: Java 8-18
        - Gradle 6.9: Java 8-15
        - Gradle 6.0-6.8: Java 8-14
        
        CRITICAL: Only enforce maximum/minimum bounds, let project config determine actual version!
        """
        try:
            gradle_parts = [int(x) for x in gradle_version.split('.')]
            gradle_major = gradle_parts[0]
            gradle_minor = gradle_parts[1] if len(gradle_parts) > 1 else 0
            
            current_java = int(self.config.get('java_version', '8'))
            
            # Gradle 6.x: Java 8-15 (does NOT support Java 17+!)
            if gradle_major == 6:
                if current_java > 15:
                    logger.warning(f"Gradle {gradle_version} max Java 15, current is {current_java}. Capping at 11")
                    self.config['java_version'] = '11'  # Safe max for Gradle 6.x
                # Otherwise keep detected version (8, 11, etc.)
            
            # Gradle 7.x: Java 8-19 (does NOT support Java 21!)
            elif gradle_major == 7:
                if current_java >= 21:
                    logger.warning(f"Gradle {gradle_version} max Java 19, current is {current_java}. Capping at 17")
                    self.config['java_version'] = '17'
                # Otherwise keep detected version
            
            # Gradle 8.0-8.4: Java 17-19 (requires minimum Java 17!)
            elif gradle_major == 8 and gradle_minor < 5:
                if current_java >= 21:
                    logger.warning(f"Gradle {gradle_version} max Java 19, current is {current_java}. Capping at 17")
                    self.config['java_version'] = '17'
                elif current_java < 17:
                    logger.warning(f"Gradle {gradle_version} requires min Java 17, current is {current_java}. Upgrading to 17")
                    self.config['java_version'] = '17'
            
            # Gradle 8.5+: Java 17+ (no upper limit in our supported range)
            elif gradle_major == 8 and gradle_minor >= 5:
                if current_java < 17:
                    logger.warning(f"Gradle {gradle_version} requires min Java 17, current is {current_java}. Upgrading to 17")
                    self.config['java_version'] = '17'
            
            # Gradle 5.x and below: Java 8-11
            elif gradle_major <= 5:
                if current_java > 11:
                    logger.warning(f"Gradle {gradle_version} max Java 11, current is {current_java}. Capping at 11")
                    self.config['java_version'] = '11'
                
        except Exception as e:
            logger.error(f"Error checking Gradle-Java compatibility: {e}")
    
    def _map_java_version(self, java_version: str) -> str:
        """Map unsupported Java version to closest supported version."""
        try:
            version_num = int(java_version)
            if version_num >= 17:
                return '17'
            elif version_num >= 11:
                return '11'
            else:
                return '8'
        except ValueError:
            return '11'  # Default fallback
    
    def _parse_app_gradle(self):
        """Parse app/build.gradle for Android SDK versions and NDK."""
        # Look for build.gradle files in multiple locations for multiplatform projects
        potential_build_files = [
            self.project_path / "app" / "build.gradle",
            self.project_path / "app" / "build.gradle.kts",
            self.project_path / "build.gradle",
            self.project_path / "build.gradle.kts"
        ]
        
        logger.info(f"Looking for app build files in: {[str(f) for f in potential_build_files]}")
        
        # Also check for android-specific modules
        for item in self.project_path.iterdir():
            if item.is_dir() and item.name.startswith('android'):
                potential_build_files.extend([
                    item / "build.gradle",
                    item / "build.gradle.kts"
                ])
        
        found_android_config = False
        
        for build_file in potential_build_files:
            if build_file.exists():
                try:
                    content = build_file.read_text(encoding='utf-8')
                    
                    # Check if this file contains Android configuration
                    if 'android {' in content or 'compileSdk' in content:
                        found_android_config = True
                        logger.info(f"Found Android config in: {build_file}")
                        
                        # Extract SDK versions
                        sdk_patterns = {
                            'compile_sdk': [
                                r'compileSdk(?:Version)?\s*[=:]\s*(\d+)',
                                r'compileSdkVersion\s*(\d+)'
                            ],
                            'target_sdk': [
                                r'targetSdk(?:Version)?\s*[=:]\s*(\d+)',
                                r'targetSdkVersion\s*(\d+)'
                            ],
                            'min_sdk': [
                                r'minSdk(?:Version)?\s*[=:]\s*(\d+)',
                                r'minSdkVersion\s*(\d+)'
                            ]
                        }
                        
                        for config_key, patterns in sdk_patterns.items():
                            for pattern in patterns:
                                match = re.search(pattern, content)
                                if match:
                                    sdk_version = match.group(1)
                                    if int(sdk_version) in self.SUPPORTED_SDK_VERSIONS:
                                        self.config[config_key] = sdk_version
                                        logger.info(f"Found {config_key}: {sdk_version}")
                                    else:
                                        # Clamp to supported range
                                        clamped = max(min(int(sdk_version), max(self.SUPPORTED_SDK_VERSIONS)), 
                                                    min(self.SUPPORTED_SDK_VERSIONS))
                                        self.config[config_key] = str(clamped)
                                        logger.warning(f"{config_key} {sdk_version} clamped to {clamped}")
                                    break
                        
                        # Extract NDK version
                        ndk_patterns = [
                            r'ndkVersion\s*[=:]\s*["\']([^"\']+)["\']',
                            r'ndk\s*\{\s*version\s*[=:]\s*["\']([^"\']+)["\']'
                        ]
                        
                        for pattern in ndk_patterns:
                            match = re.search(pattern, content)
                            if match:
                                self.config['ndk_version'] = match.group(1)
                                logger.info(f"Found NDK version: {match.group(1)}")
                                break
                        
                        break  # Found Android config, no need to check other files
                        
                except Exception as e:
                    logger.error(f"Error parsing build file {build_file}: {e}")
        
        if not found_android_config:
            logger.warning("No Android build configuration found")
    
    def _determine_test_variant(self):
        """Determine the appropriate test variant (prefer debug)."""
        # Look for build.gradle files that might contain buildTypes
        potential_build_files = [
            self.project_path / "app" / "build.gradle",
            self.project_path / "app" / "build.gradle.kts",
        ]
        
        # Also check android-specific modules
        for item in self.project_path.iterdir():
            if item.is_dir() and item.name.startswith('android'):
                potential_build_files.extend([
                    item / "build.gradle",
                    item / "build.gradle.kts"
                ])
        
        for build_file in potential_build_files:
            if build_file.exists():
                try:
                    content = build_file.read_text(encoding='utf-8')
                    
                    # Look for buildTypes section
                    build_types_match = re.search(r'buildTypes\s*\{([^}]+)\}', content, re.DOTALL)
                    if build_types_match:
                        build_types_content = build_types_match.group(1)
                        
                        # Check for debug variant
                        if 'debug' in build_types_content.lower():
                            self.config['test_variant'] = 'debug'
                            return
                        elif 'release' in build_types_content.lower():
                            self.config['test_variant'] = 'release'
                            logger.warning("Using release variant for testing")
                            return
                            
                except Exception as e:
                    logger.error(f"Error determining test variant from {build_file}: {e}")
    
    def _validate_config(self):
        """Validate and adjust configuration for mingc/android-build-box compatibility.
        Only adjusts when values are outside supported ranges - doesn't force upgrades."""
        # Ensure Java version is supported - if not, map to nearest
        if self.config['java_version'] not in self.SUPPORTED_JAVA_VERSIONS:
            old_version = self.config['java_version']
            self.config['java_version'] = self._map_java_version(old_version)
            logger.warning(f"Java version {old_version} not in supported list, mapped to {self.config['java_version']}")
            
        # Ensure Gradle version is supported - if not, find closest
        if self.config['gradle_version'] not in self.SUPPORTED_GRADLE_VERSIONS:
            old_version = self.config['gradle_version']
            self.config['gradle_version'] = self._find_closest_version(
                old_version, 
                self.SUPPORTED_GRADLE_VERSIONS
            )
            logger.warning(f"Gradle version {old_version} not in supported list, using closest: {self.config['gradle_version']}")
            
        # Ensure SDK versions are in range (but don't force upgrades)
        for sdk_key in ['compile_sdk', 'target_sdk', 'min_sdk']:
            sdk_val = int(self.config[sdk_key])
            if sdk_val not in self.SUPPORTED_SDK_VERSIONS:
                # Clamp to supported range instead of forcing to max
                clamped = max(min(sdk_val, max(self.SUPPORTED_SDK_VERSIONS)), 
                             min(self.SUPPORTED_SDK_VERSIONS))
                logger.warning(f"{sdk_key} {sdk_val} not in supported range ({min(self.SUPPORTED_SDK_VERSIONS)}-{max(self.SUPPORTED_SDK_VERSIONS)}), clamping to {clamped}")
                self.config[sdk_key] = str(clamped)
    
    def _find_closest_version(self, target: str, available: List[str]) -> str:
        """Find the closest available version to target."""
        target_parts = [int(x) for x in target.split('.')]
        
        best_match = available[0]
        best_score = float('inf')
        
        for version in available:
            version_parts = [int(x) for x in version.split('.')]
            
            # Calculate version distance
            score = 0
            for i, (t, v) in enumerate(zip(target_parts, version_parts)):
                score += abs(t - v) * (10 ** (len(target_parts) - i))
                
            if score < best_score:
                best_score = score
                best_match = version
                
        return best_match
    

    def extract_test_tasks_from_patch(self, test_patch: str) -> List[str]:
        """Extract test file paths and create targeted gradle test commands."""
        test_tasks = []

        if not test_patch or not test_patch.strip():
            logger.warning("Empty test patch provided")
            return test_tasks
        
        # Extract file paths from patch
        file_patterns = [
            r'\+\+\+ b/(.+\.java)',
            r'\+\+\+ b/(.+\.kt)',
            r'diff --git a/.+ b/(.+\.java)',
            r'diff --git a/.+ b/(.+\.kt)'
        ]
        
        test_files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, test_patch)
            test_files.update(matches)
        
        logger.debug(f"Found files in patch: {test_files}")

        variant = self.config['test_variant'].capitalize()

        # Separate unit tests and instrumented tests
        unit_test_classes = []
        instrumented_test_classes = []
        
        # Convert test files to specific gradle test commands
        for test_file in test_files:
            test_file_lower = test_file.lower()
            
            # Only process actual test files
            if 'test' not in test_file_lower:
                logger.debug(f"Skipping non-test file: {test_file}")
                continue
                
            # Convert file path to test class name
            if test_file.endswith('.java') or test_file.endswith('.kt'):
                class_name = self._convert_file_to_class_name(test_file)
            
                if class_name:
                    # Determine test type - handle Kotlin Multiplatform structure
                    if ('androidtest' in test_file_lower or '/androidTest/' in test_file or 
                        'instrumentedtest' in test_file_lower):
                        instrumented_test_classes.append(class_name)
                        logger.debug(f"Found instrumented test class: {class_name}")
                    else:
                        unit_test_classes.append(class_name)
                        logger.debug(f"Found unit test class: {class_name}")
                else:
                    logger.warning(f"Could not convert file to class name: {test_file}")
        
        # Create test tasks based on test type
        # For unit tests use --tests parameter
        if unit_test_classes:
            for class_name in unit_test_classes:
                test_tasks.append(f'test{variant}UnitTest --tests {class_name}')

        if instrumented_test_classes:
            # Use system property to filter (if supported by the project)
            for class_name in instrumented_test_classes:
                test_tasks.append(f'connected{variant}AndroidTest -Pandroid.testInstrumentationRunnerArguments.class={class_name}')

        # If no specific tests found, try to run all tests for the modules that contain test files
        if not test_tasks and test_files:
            modules = set()
            for test_file in test_files:
                # Extract module name from file path
                parts = test_file.split('/')
                if len(parts) > 1:
                    # For paths like "feature/notification/api/src/...", module is "feature:notification:api"
                    module_parts = []
                    for part in parts:
                        if part in ['src', 'main', 'test', 'androidTest', 'commonTest', 'commonMain']:
                            break
                        module_parts.append(part)
                    
                    if module_parts:
                        module = ':' + ':'.join(module_parts)
                        modules.add(module)
                        logger.debug(f"Detected module from {test_file}: {module}")
            
            # Add module-specific test tasks
            for module in modules:
                test_tasks.append(f'{module}:test{variant}UnitTest')
                logger.debug(f"Added module test task: {module}:test{variant}UnitTest")

        if not test_tasks:
            logger.warning("No test tasks extracted from patch - patch may not contain test files")
            logger.debug(f"Test patch content preview: {test_patch[:500]}...")

        return test_tasks
    
    def extract_module_from_file_path(self, file_path: str) -> str:
        """
        Extract Gradle module from test file path.
        
        Examples:
        - feature/notification/impl/src/commonTest/kotlin/... -> :feature:notification:impl
        - parser/media/src/test/java/... -> :parser:media
        - app/src/test/java/... -> :app
        - src/test/java/... -> : (root project)
        """
        # Normalize path separators
        path = file_path.replace('\\', '/')
        
        # Split path into components
        parts = path.split('/')
        
        # Find the src directory index to determine module path
        src_indices = [i for i, part in enumerate(parts) if part == 'src']
        
        if src_indices:
            # Use the first 'src' directory found
            src_index = src_indices[0]
            # Everything before 'src' is the module path
            module_parts = parts[:src_index]
            
            if module_parts:
                # Join with ':' and prepend with ':'
                return ':' + ':'.join(module_parts)
            else:
                # Root project if no parts before src
                return ':'
        else:
            # Fallback: try to detect common Android module patterns
            # Look for common test directory patterns
            test_indicators = ['test', 'androidTest', 'commonTest', 'unitTest']
            
            for i, part in enumerate(parts):
                if any(indicator in part.lower() for indicator in test_indicators):
                    # Take everything before the test directory as module
                    module_parts = parts[:i]
                    if module_parts:
                        return ':' + ':'.join(module_parts)
                    break
            
            # Ultimate fallback: assume it's app module
            return ':app'
        
    def extract_test_tasks_from_patch_by_module(self, test_patch: str) -> Tuple[Dict[str, List[str]], List[str]]:
        """Extract test tasks grouped by module from patch content, separating unit and instrumented tests."""
        
        if not test_patch or not test_patch.strip():
            logger.warning("Empty test patch provided")
            return {}, []
        
        # Extract test files from patch
        test_files = self._extract_test_files_from_patch(test_patch)
        
        if not test_files:
            logger.warning("No test files found in patch")
            return {}, []
        
        # Group by module (unit tests only) and track skipped instrumented tests
        module_tests = {}
        skipped_instrumented_tests = []
        total_unit_tests = 0
        
        for test_file in test_files:
            # Convert file path to class name
            class_name = self._convert_file_to_class_name(test_file)
            
            if class_name:
                # Check if this is an instrumented test
                if self._is_instrumented_test(test_file):
                    skipped_instrumented_tests.append(class_name)
                    logger.debug(f"Skipping instrumented test: {class_name}")
                else:
                    # Extract module from file path for unit tests only
                    module = self.extract_module_from_file_path(test_file)
                    
                    if module not in module_tests:
                        module_tests[module] = []
                    module_tests[module].append(class_name)
                    total_unit_tests += 1
        
        logger.info(f"Detected {total_unit_tests} unit tests across {len(module_tests)} modules: {module_tests}")
        if skipped_instrumented_tests:
            logger.info(f"Skipped {len(skipped_instrumented_tests)} instrumented tests: {skipped_instrumented_tests}")
        
        return module_tests, skipped_instrumented_tests
    
    def _is_instrumented_test(self, file_path: str) -> bool:
        """Check if a test file is an instrumented test (androidTest)."""
        file_lower = file_path.lower()
        
        # Check for instrumented test indicators
        instrumented_indicators = [
            '/androidtest/',
            '/instrumentedtest/',
            'androidtest.java',
            'androidtest.kt'
        ]
        
        return any(indicator in file_lower for indicator in instrumented_indicators)
    
    def _extract_test_files_from_patch(self, test_patch: str) -> List[str]:
        """Extract test file paths from patch content."""
        # Pattern to match file paths in patch
        file_patterns = [
            r'\+\+\+ b/(.+\.(?:java|kt))',  # Files being modified/added
            r'diff --git a/.+ b/(.+\.(?:java|kt))'  # Git diff format
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
        """Check if a file path represents a test file."""
        file_lower = file_path.lower()
        
        # Check for test file indicators
        test_indicators = [
            '/test/',
            '/androidtest/',
            '/commontest/',
            '/unittest/',
            'test.java',
            'test.kt',
            'tests.java',
            'tests.kt'
        ]
        
        return any(indicator in file_lower for indicator in test_indicators)

    def _convert_file_to_class_name(self, test_file: str) -> Optional[str]:
        """Convert file path to fully qualified class name, handling various test structures 
        and filtering out utility/helper classes that aren't actual test classes."""
        
        # First check if this is a utility/helper class that shouldn't be run as a test
        if not self._is_actual_test_class(test_file):
            return None
        
        # Handle different test source directories
        test_source_patterns = [
            '/src/test/java/',
            '/src/test/kotlin/',
            '/src/androidTest/java/',
            '/src/androidTest/kotlin/',
            '/src/commonTest/kotlin/',
            '/src/unitTest/java/',
            '/src/unitTest/kotlin/'
        ]
        
        for pattern in test_source_patterns:
            if pattern in test_file:
                # Split at the test source directory
                parts = test_file.split(pattern)
                if len(parts) == 2:
                    class_path = parts[1]
                    # Convert file path to class name
                    class_name = class_path.replace('/', '.').replace('.java', '').replace('.kt', '')
                    return class_name
        
        # Fallback: try to extract from any recognizable pattern
        # Look for common package structures
        if '/java/' in test_file or '/kotlin/' in test_file:
            # Find the last occurrence of /java/ or /kotlin/
            java_idx = test_file.rfind('/java/')
            kotlin_idx = test_file.rfind('/kotlin/')
            
            start_idx = max(java_idx, kotlin_idx)
            if start_idx != -1:
                # Take everything after /java/ or /kotlin/
                suffix_start = start_idx + (6 if java_idx > kotlin_idx else 8)  # len('/java/') or len('/kotlin/')
                class_path = test_file[suffix_start:]
                class_name = class_path.replace('/', '.').replace('.java', '').replace('.kt', '')
                return class_name
        
        # Last resort: just use the filename without extension
        # filename = test_file.split('/')[-1]
        # if filename.endswith('.java') or filename.endswith('.kt'):
        #     return filename.replace('.java', '').replace('.kt', '')
        filename = test_file.split('/')[-1]
        if filename.endswith('.java') or filename.endswith('.kt'):
            class_name = filename.replace('.java', '').replace('.kt', '')
            # Still filter utility classes even at this level
            if self._is_utility_class_name(class_name):
                logger.debug(f"Skipping utility class by filename: {class_name}")
                return None
            return class_name
        
        return None
    
    def _is_actual_test_class(self, file_path: str) -> bool:
        """Check if a file represents an actual test class with test methods,
        not a utility/helper/mock class."""
        
        # Get just the filename for checking
        filename = os.path.basename(file_path)
        
        # Check if it's a utility class that should be excluded
        if self._is_utility_class_name(filename):
            logger.debug(f"Skipping utility class: {filename}")
            return False
        
        # Additional check: try to read file content to see if it has actual test methods
        # This is more robust but slower - only use as final validation
        if self.project_path and os.path.exists(os.path.join(self.project_path, file_path)):
            return self._has_test_methods(os.path.join(self.project_path, file_path))
        
        # If we can't read the file, assume it's a test class if it passed other checks
        return True
    
    def _is_utility_class_name(self, filename: str) -> bool:
        """Check if a filename indicates it's a utility/helper class."""
        
        # Remove file extension for checking
        class_name = filename.replace('.java', '').replace('.kt', '')
        
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
        
        # Check if filename starts with any utility pattern
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
    
    def _has_test_methods(self, file_path: str) -> bool:
        """Check if a file actually contains test methods by scanning content."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Look for common test method indicators
            test_method_indicators = [
                '@Test',                    # JUnit 4/5
                '@ParameterizedTest',       # JUnit 5
                '@RepeatedTest',           # JUnit 5
                '@TestMethodOrder',        # JUnit 5
                '@TestInstance',           # JUnit 5
                'fun test',                # Kotlin test functions
                'fun `',                   # Kotlin test functions with backticks
                'void test',               # Java test methods
                'public void test',        # Java test methods
                'testSuite(',              # Some test frameworks
                'describe(',               # BDD-style tests
                'it(',                     # BDD-style tests
                'should(',                 # BDD-style tests
                'when(',                   # BDD-style tests
                'given(',                  # BDD-style tests
                'then(',                   # BDD-style tests
            ]
            
            # Count how many indicators we find
            indicator_count = sum(1 for indicator in test_method_indicators 
                                if indicator in content)
            
            # If we find multiple test indicators, it's likely a real test class
            if indicator_count >= 2:
                return True
            
            # Single @Test annotation is usually enough
            if '@Test' in content:
                return True
            
            # Check for test method naming patterns
            test_method_patterns = [
                r'fun test\w+\(',          # Kotlin: fun testSomething(
                r'fun `.*`\(',             # Kotlin: fun `should do something`(
                r'void test\w+\(',         # Java: void testSomething(
                r'public void test\w+\(',  # Java: public void testSomething(
            ]
            
            for pattern in test_method_patterns:
                if re.search(pattern, content):
                    return True
            
            # If no clear test indicators found, it's probably not a test class
            return False
            
        except Exception as e:
            logger.debug(f"Could not read file {file_path} to check for test methods: {e}")
            # If we can't read the file, err on the side of caution and include it
            # This prevents false negatives where we skip actual test files
            return True