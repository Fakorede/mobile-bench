#!/usr/bin/env python3
"""
Android project configuration parser for build requirements detection.
"""

import re
import os
import logging
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidConfig:
    """Parses Android project configuration to extract build requirements."""
    
    # Based on mingc/android-build-box:latest available versions
    SUPPORTED_JAVA_VERSIONS = ['8', '11', '17']
    SUPPORTED_GRADLE_VERSIONS = ['6.9', '7.0', '7.1', '7.2', '7.3', '7.4', '7.5', '7.6', '8.0', '8.1']
    SUPPORTED_SDK_VERSIONS = range(21, 35)  # API 21-35
    DEFAULT_BUILD_TOOLS = '35.0.0'
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.config = self._get_default_config()
        
    def _get_default_config(self) -> Dict[str, str]:
        """Return default configuration based on mingc/android-build-box."""
        return {
            'java_version': '17',
            'gradle_version': '8.6',
            'compile_sdk': '35',
            'target_sdk': '35',
            'min_sdk': '21',
            'build_tools': self.DEFAULT_BUILD_TOOLS,
            'ndk_version': None,
            'jvm_args': '-Xmx4096m',
            'test_variant': 'debug'
        }
    
    def parse_build_config(self) -> Dict[str, str]:
        """Parse all configuration files and return build requirements."""
        logger.info(f"Parsing Android configuration for {self.project_path}")
        
        # Parse in order of priority (AGP version detection is critical)
        self._parse_gradle_wrapper()
        self._parse_gradle_properties()
        self._parse_project_gradle()  # This now detects AGP and sets Java accordingly
        self._parse_app_gradle()
        self._determine_test_variant()
        
        # Final validation and adjustment
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
            patterns = [
                r'gradle-(\d+\.\d+(?:\.\d+)?)-',
                r'distributionUrl=.*gradle-(\d+\.\d+(?:\.\d+)?)-'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    version = match.group(1)
                    if version in self.SUPPORTED_GRADLE_VERSIONS:
                        self.config['gradle_version'] = version
                        logger.info(f"Found Gradle version: {version}")
                    else:
                        # Find closest supported version
                        closest = self._find_closest_version(version, self.SUPPORTED_GRADLE_VERSIONS)
                        self.config['gradle_version'] = closest
                        logger.warning(f"Gradle {version} not supported, using {closest}")
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
        for gradle_file in ['build.gradle', 'build.gradle.kts']:
            project_gradle = self.project_path / gradle_file
            if project_gradle.exists():
                break
        else:
            logger.warning("Project build.gradle not found")
            return
            
        try:
            content = project_gradle.read_text(encoding='utf-8')
            
            # First check AGP version which determines minimum Java requirement
            agp_version = self._detect_agp_version(content)
            if agp_version:
                required_java = self._get_java_version_for_agp(agp_version)
                if required_java:
                    self.config['java_version'] = required_java
                    logger.info(f"AGP {agp_version} requires Java {required_java}")
            
            # Extract Java version from various patterns (but AGP takes precedence)
            java_patterns = [
                r'sourceCompatibility\s*[=:]\s*JavaVersion\.VERSION_(\d+)',
                r'targetCompatibility\s*[=:]\s*JavaVersion\.VERSION_(\d+)',
                r'jvmTarget\s*[=:]\s*["\'](\d+)["\']',
                r'JavaVersion\.VERSION_(\d+)',
                r'compileOptions\s*\{[^}]*sourceCompatibility\s*[=:]\s*JavaVersion\.VERSION_(\d+)',
                r'kotlinOptions\s*\{[^}]*jvmTarget\s*[=:]\s*["\'](\d+)["\']'
            ]
            
            # Only override AGP decision if explicitly specified and higher
            for pattern in java_patterns:
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    java_version = match.group(1)
                    if java_version in self.SUPPORTED_JAVA_VERSIONS:
                        # Only use if higher than AGP requirement
                        if not agp_version or int(java_version) >= int(self.config['java_version']):
                            self.config['java_version'] = java_version
                            logger.info(f"Found explicit Java version: {java_version}")
                    else:
                        # Map to supported version
                        mapped_version = self._map_java_version(java_version)
                        if not agp_version or int(mapped_version) >= int(self.config['java_version']):
                            self.config['java_version'] = mapped_version
                            logger.warning(f"Java {java_version} mapped to {mapped_version}")
                    break
                    
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
        self._check_version_catalogs()
        
        return None
    
    def _check_version_catalogs(self) -> Optional[str]:
        """Check gradle/libs.versions.toml for AGP version."""
        version_catalog = self.project_path / "gradle" / "libs.versions.toml"
        if version_catalog.exists():
            try:
                content = version_catalog.read_text(encoding='utf-8')
                agp_patterns = [
                    r'agp\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
                    r'android-gradle\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
                    r'androidGradlePlugin\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']'
                ]
                
                for pattern in agp_patterns:
                    match = re.search(pattern, content)
                    if match:
                        agp_version = match.group(1)
                        logger.info(f"Detected AGP version from catalog: {agp_version}")
                        return agp_version
            except Exception as e:
                logger.warning(f"Error reading version catalog: {e}")
        
        return None
    
    def _get_java_version_for_agp(self, agp_version: str) -> Optional[str]:
        """Get required Java version for Android Gradle Plugin version."""
        try:
            version_parts = [int(x) for x in agp_version.split('.')]
            major = version_parts[0]
            minor = version_parts[1] if len(version_parts) > 1 else 0
            
            # AGP version to Java version mapping
            # Based on official Android Gradle Plugin requirements
            if major >= 8 or (major == 7 and minor >= 4):
                # AGP 7.4+ requires Java 17
                return '17'
            elif major >= 7 or (major == 4 and minor >= 2):
                # AGP 4.2+ to 7.3 requires Java 11
                return '11'
            else:
                # Older AGP versions can use Java 8
                return '8'
                
        except Exception as e:
            logger.warning(f"Error parsing AGP version {agp_version}: {e}")
            return None
    
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
        for gradle_file in ['app/build.gradle', 'app/build.gradle.kts']:
            app_gradle = self.project_path / gradle_file
            if app_gradle.exists():
                break
        else:
            logger.warning("App build.gradle not found")
            return
            
        try:
            content = app_gradle.read_text(encoding='utf-8')
            
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
                    
        except Exception as e:
            logger.error(f"Error parsing app build.gradle: {e}")
    
    def _determine_test_variant(self):
        """Determine the appropriate test variant (prefer debug)."""
        for gradle_file in ['app/build.gradle', 'app/build.gradle.kts']:
            app_gradle = self.project_path / gradle_file
            if app_gradle.exists():
                break
        else:
            return
            
        try:
            content = app_gradle.read_text(encoding='utf-8')
            
            # Look for buildTypes section
            build_types_match = re.search(r'buildTypes\s*\{([^}]+)\}', content, re.DOTALL)
            if build_types_match:
                build_types_content = build_types_match.group(1)
                
                # Check for debug variant
                if 'debug' in build_types_content.lower():
                    self.config['test_variant'] = 'debug'
                elif 'release' in build_types_content.lower():
                    self.config['test_variant'] = 'release'
                    logger.warning("Using release variant for testing")
                    
        except Exception as e:
            logger.error(f"Error determining test variant: {e}")
    
    def _validate_config(self):
        """Validate and adjust configuration for mingc/android-build-box compatibility."""
        # Ensure Java version is supported
        if self.config['java_version'] not in self.SUPPORTED_JAVA_VERSIONS:
            self.config['java_version'] = '17'  # Default safe choice
            
        # Ensure Gradle version is supported
        if self.config['gradle_version'] not in self.SUPPORTED_GRADLE_VERSIONS:
            self.config['gradle_version'] = '8.6'  # Default safe choice
            
        # Ensure SDK versions are in range
        for sdk_key in ['compile_sdk', 'target_sdk', 'min_sdk']:
            sdk_val = int(self.config[sdk_key])
            if sdk_val not in self.SUPPORTED_SDK_VERSIONS:
                self.config[sdk_key] = '35'  # Default safe choice
    
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
                # Example: app/src/test/java/com/example/MyTest.java
                # becomes: com.example.MyTest
                class_name = self._convert_file_to_class_name(test_file)
            
                if class_name:
                    # Determine test type
                    if 'androidtest' in test_file_lower or '/androidTest/' in test_file:
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
            # # Run all connected tests (safest but slower)
            # test_tasks.append(f'connected{variant}AndroidTest')

            # Use system property to filter (if supported by the project)
            for class_name in instrumented_test_classes:
                test_tasks.append(f'connected{variant}AndroidTest -Pandroid.testInstrumentationRunnerArguments.class={class_name}')

            # OR, Use adb commands (more complex but precise)
            # TODO: This would require additional implementation

        if not test_tasks:
            logger.warning("No test tasks extracted from patch - patch may not contain test files")
            logger.debug(f"Test patch content preview: {test_patch[:500]}...")

        return test_tasks

    def _convert_file_to_class_name(self, test_file: str) -> Optional[str]:
        """Convert file path to fully qualified class name."""
        # Handle standard Android test structure
        if '/src/test/' in test_file:
            # Example: app/src/test/java/com/example/MyTest.java
            parts = test_file.split('/src/test/')
            if len(parts) == 2:
                test_path = parts[1]
                # Remove java/ or kotlin/ prefix if present
                if test_path.startswith('java/'):
                    class_path = test_path[5:]  # Remove 'java/'
                elif test_path.startswith('kotlin/'):
                    class_path = test_path[7:]  # Remove 'kotlin/'
                else:
                    class_path = test_path
                
                # Convert file path to class name
                class_name = class_path.replace('/', '.').replace('.java', '').replace('.kt', '')
                return class_name
        
        elif '/src/androidTest/' in test_file:
            # Example: app/src/androidTest/java/com/example/MyInstrumentedTest.java
            parts = test_file.split('/src/androidTest/')
            if len(parts) == 2:
                test_path = parts[1]
                # Remove java/ or kotlin/ prefix if present
                if test_path.startswith('java/'):
                    class_path = test_path[5:]
                elif test_path.startswith('kotlin/'):
                    class_path = test_path[7:]
                else:
                    class_path = test_path
                
                class_name = class_path.replace('/', '.').replace('.java', '').replace('.kt', '')
                return class_name
        
        # Handle non-standard structures or relative paths
        elif test_file.endswith('.java') or test_file.endswith('.kt'):
            # Try to extract package and class from file content or path
            logger.debug(f"Non-standard test file structure: {test_file}")
            # For now, just use the filename as class name
            filename = test_file.split('/')[-1]
            class_name = filename.replace('.java', '').replace('.kt', '')
            return class_name
        
        return None


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python config.py <project_path>")
        sys.exit(1)
        
    logging.basicConfig(level=logging.INFO)
    
    config = AndroidConfig(sys.argv[1])
    result = config.parse_build_config()
    
    print("Android Build Configuration:")
    for key, value in result.items():
        print(f"  {key}: {value}")