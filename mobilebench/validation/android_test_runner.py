#!/usr/bin/env python3
"""
Android Test Runner for JSONL Dataset

This script processes a JSONL file containing Android test instances and runs tests
in Docker containers to generate FAIL_TO_PASS and PASS_TO_PASS expectations.

Requirements:
- Docker installed and running
- mingc/android-build-box Docker image
- Input JSONL file with test instances

Usage:
    python android_test_runner.py <path_to_jsonl> <docker_context> <timeout_minutes> <preferred_variant> <github_token>

    python android_test_runner.py /home/researchuser/dev/mobile-bench/data/tasks/thunderbird-android-task-instances.jsonl "" 15 17 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
"""

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


class AndroidTestRunner:
    def __init__(self, docker_image="mingc/android-build-box", timeout_minutes=10, preferred_variant="debug", docker_context=None, custom_java_version=None, github_token=None):
        self.docker_image = docker_image
        self.timeout_seconds = timeout_minutes * 60
        self.work_dir = None  # Will be set in setup_workspace
        self.default_java_version = "17"
        self.preferred_variant = preferred_variant  # "debug", "release", or "auto"
        self.docker_context = docker_context  # Docker context to use
        self.custom_java_version = custom_java_version  # Override auto-detection
        self.github_token = github_token  # GitHub token for private packages
        
    def _get_docker_cmd_prefix(self):
        """Get Docker command prefix with context if specified."""
        if self.docker_context:
            return ["docker", "--context", self.docker_context]
        else:
            return ["docker"]
        
    def setup_workspace(self):
        """Create and setup the workspace directory."""
        # Use absolute path for work_dir
        self.work_dir = Path.cwd() / "android_test_workspace"
        
        if self.work_dir.exists():
            print(f"Existing workspace found at: {self.work_dir.absolute()}")
            try:
                # Try Docker cleanup first for permission issues
                docker_cmd_prefix = self._get_docker_cmd_prefix()
                cleanup_cmd = docker_cmd_prefix + [
                    "run", "--rm",
                    "-v", f"{self.work_dir.absolute()}:/workspace",
                    self.docker_image,
                    "bash", "-c", """
                    cd /workspace &&
                    echo "Fixing permissions for cleanup..." &&
                    find . -type f -exec chmod 666 {} + 2>/dev/null || true &&
                    find . -type d -exec chmod 777 {} + 2>/dev/null || true &&
                    echo "Permissions fixed"
                    """
                ]
                
                print("Fixing workspace permissions with Docker...")
                result = subprocess.run(cleanup_cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    print("Docker permission fix completed")
                else:
                    print(f"Docker permission fix warning: {result.stderr}")
                    
            except Exception as e:
                print(f"Docker permission fix failed: {e}")
            
            # Now try to remove the workspace
            try:
                shutil.rmtree(self.work_dir)
                print("Existing workspace removed")
            except PermissionError as e:
                print(f"Warning: Could not remove existing workspace due to permissions: {e}")
                print("Trying to continue with existing workspace...")
                # Don't fail - just use the existing workspace
            except Exception as e:
                print(f"Error removing workspace: {e}")
                print("Trying to continue with existing workspace...")
        
        # Create workspace if it doesn't exist
        self.work_dir.mkdir(exist_ok=True)
        print(f"Workspace ready at: {self.work_dir.absolute()}")
    
#     def setup_user_properties(self, repo_dir: Path) -> bool:
#         """Setup user.properties file for Bitwarden project."""
#         if not self.github_token:
#             print("No GitHub token provided - checking if user.properties already exists")
#             user_props_path = repo_dir / "user.properties"
#             if user_props_path.exists():
#                 print("Found existing user.properties file")
#                 return True
#             else:
#                 print("WARNING: No user.properties file found and no GitHub token provided")
#                 print("This may cause build failures for projects requiring GitHub Packages access")
#                 return False
        
#         try:
#             user_props_path = repo_dir / "user.properties"
#             user_props_content = f"""# Auto-generated user.properties for Android test runner
# gitHubToken={self.github_token}
# localSdk=false
# """
#             user_props_path.write_text(user_props_content)
#             print(f"Created user.properties file at: {user_props_path}")
#             return True
    def cleanup_workspace(self):
        """Clean up the workspace directory."""
        if self.work_dir and self.work_dir.exists():
            try:
                # Use Docker to clean up files with restricted permissions
                docker_cmd_prefix = self._get_docker_cmd_prefix()
                cleanup_cmd = docker_cmd_prefix + [
                    "run", "--rm",
                    "-v", f"{self.work_dir.absolute()}:/workspace",
                    self.docker_image,
                    "bash", "-c", """
                    cd /workspace &&
                    echo "Cleaning workspace..." &&
                    find . -type f -exec chmod 666 {} + 2>/dev/null || true &&
                    find . -type d -exec chmod 777 {} + 2>/dev/null || true &&
                    echo "Permissions updated"
                    """
                ]
                
                result = subprocess.run(cleanup_cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    print("Docker workspace cleanup completed")
                else:
                    print(f"Docker workspace cleanup warning: {result.stderr}")
                    
            except Exception as e:
                print(f"Docker workspace cleanup failed: {e}")
            
            # Now try to remove with Python
            try:
                shutil.rmtree(self.work_dir)
                print("Workspace cleaned up successfully")
            except PermissionError as e:
                print(f"Warning: Could not fully clean workspace due to permissions: {e}")
                print("Some files may remain in the workspace directory")
            except Exception as e:
                print(f"Error cleaning workspace: {e}")
        else:
            print("No workspace to clean up")
    
    def ensure_docker_image(self):
        """Ensure the Docker image is available locally."""
        print(f"Checking for Docker image: {self.docker_image}")
        
        docker_cmd = self._get_docker_cmd_prefix()
        
        # First, check if Docker is running
        try:
            subprocess.run(
                docker_cmd + ["info"],
                capture_output=True,
                check=True,
                timeout=10
            )
        except subprocess.CalledProcessError:
            raise RuntimeError("Docker is not running or not accessible. Please start Docker and try again.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker command timed out. Docker may not be responding.")
        except FileNotFoundError:
            raise RuntimeError("Docker command not found. Please install Docker and try again.")
        
        # Check if image exists locally
        try:
            result = subprocess.run(
                docker_cmd + ["images", "-q", self.docker_image],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Check if the command succeeded
            if result.returncode == 0:
                if result.stdout.strip():
                    print(f"Docker image {self.docker_image} found locally")
                    return
                else:
                    print(f"Docker image {self.docker_image} not found locally")
            else:
                print(f"Failed to check for Docker image. stderr: {result.stderr}")
                print("Attempting to pull the image anyway...")
            
            # Try to pull the image
            print(f"Pulling Docker image: {self.docker_image}")
            pull_result = subprocess.run(
                docker_cmd + ["pull", self.docker_image],
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes timeout for pulling
            )
            
            if pull_result.returncode == 0:
                print(f"Successfully pulled {self.docker_image}")
            else:
                error_msg = f"Failed to pull Docker image {self.docker_image}"
                if pull_result.stderr:
                    error_msg += f". Error: {pull_result.stderr}"
                raise RuntimeError(error_msg)
                
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker command timed out. This might be due to network issues or Docker not responding.")
        except Exception as e:
            raise RuntimeError(f"Unexpected error while ensuring Docker image: {e}")
    
    def clone_repository(self, repo_url: str, repo_dir: Path) -> bool:
        """Clone repository if it doesn't exist or refresh if it does."""
        # Ensure we're working with absolute paths
        repo_dir = repo_dir.resolve()
        
        if repo_dir.exists():
            print(f"Repository directory exists at: {repo_dir}")
            # Check if it's a valid git repository
            if (repo_dir / ".git").exists():
                print("Valid git repository found, trying to clean and fetch...")
                try:
                    # More aggressive cleanup for submodule issues
                    subprocess.run(["git", "submodule", "foreach", "--recursive", "git", "reset", "--hard"], cwd=repo_dir, check=False, timeout=120)
                    subprocess.run(["git", "reset", "--hard"], cwd=repo_dir, check=True, timeout=60)
                    subprocess.run(["git", "clean", "-fdx"], cwd=repo_dir, check=False, timeout=60)
                    subprocess.run(["git", "fetch", "--all"], cwd=repo_dir, check=True, timeout=120)
                    subprocess.run(["git", "submodule", "update", "--init", "--recursive", "--force"], cwd=repo_dir, check=False, timeout=180)
                    print("Repository updated successfully")
                    return True
                except subprocess.CalledProcessError as e:
                    print(f"Failed to fetch repository updates: {e}")
                    print("Removing corrupted repository and re-cloning...")
                    shutil.rmtree(repo_dir)
                except subprocess.TimeoutExpired:
                    print("Repository update timed out, re-cloning...")
                    shutil.rmtree(repo_dir)
            else:
                print("Invalid repository directory found, removing and re-cloning...")
                shutil.rmtree(repo_dir)
            
        print(f"Cloning repository: {repo_url}")
        print(f"Target directory: {repo_dir}")
        try:
            # Ensure parent directory exists
            repo_dir.parent.mkdir(parents=True, exist_ok=True)
            
            # Clone with specific options for better submodule handling
            subprocess.run([
                "git", "clone", "--recursive", "--depth", "1000", repo_url, str(repo_dir)
            ], check=True, timeout=600)  # 10 minute timeout
            
            # Verify the clone was successful
            if not repo_dir.exists():
                print(f"Clone failed: directory {repo_dir} does not exist")
                return False
                
            if not (repo_dir / ".git").exists():
                print(f"Clone failed: {repo_dir} is not a valid git repository")
                return False
                
            print(f"Successfully cloned repository to: {repo_dir}")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Failed to clone repository: {e}")
            # Clean up partial clone if it exists
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            return False
        except subprocess.TimeoutExpired:
            print("Repository cloning timed out")
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            return False
    
    def detect_gradle_version(self, repo_dir: Path) -> Optional[str]:
        """Detect Gradle version from gradle-wrapper.properties."""
        # Ensure we're using absolute path
        repo_dir = repo_dir.resolve()
        gradle_props = repo_dir / "gradle" / "wrapper" / "gradle-wrapper.properties"
        
        print(f"Looking for Gradle properties at: {gradle_props}")
        
        if gradle_props.exists():
            try:
                content = gradle_props.read_text()
                match = re.search(r'gradle-(\d+\.\d+(?:\.\d+)?)-', content)
                if match:
                    version = match.group(1)
                    print(f"Detected Gradle version: {version}")
                    return version
                else:
                    print("No Gradle version pattern found in properties file")
            except Exception as e:
                print(f"Error reading gradle properties: {e}")
        else:
            print(f"Gradle wrapper properties file not found at: {gradle_props}")
        
        # Try alternative locations
        alt_locations = [
            repo_dir / "app" / "gradle" / "wrapper" / "gradle-wrapper.properties",
            repo_dir / "gradle-wrapper.properties"
        ]
        
        for alt_location in alt_locations:
            if alt_location.exists():
                try:
                    content = alt_location.read_text()
                    match = re.search(r'gradle-(\d+\.\d+(?:\.\d+)?)-', content)
                    if match:
                        version = match.group(1)
                        print(f"Detected Gradle version from {alt_location}: {version}")
                        return version
                except Exception:
                    pass
        
        print("Could not detect Gradle version from any properties file")
        return None
    
    def detect_kotlin_usage(self, repo_dir: Path) -> bool:
        """Detect if the project uses Kotlin."""
        # Check build.gradle files for kotlin
        build_files = [
            repo_dir / "build.gradle",
            repo_dir / "app" / "build.gradle",
            repo_dir / "buildSrc" / "build.gradle.kts"
        ]
        
        for build_file in build_files:
            if build_file.exists():
                try:
                    content = build_file.read_text()
                    if "kotlin" in content.lower():
                        print("Kotlin detected in build files")
                        return True
                except Exception:
                    pass
        
        # Check for .kt or .kts files
        for kt_file in repo_dir.rglob("*.kt"):
            print("Kotlin files detected")
            return True
            
        for kts_file in repo_dir.rglob("*.kts"):
            print("Kotlin script files detected")
            return True
            
        return False
    
    def determine_java_version(self, gradle_version: Optional[str], has_kotlin: bool) -> str:
        """Determine compatible Java version based on Gradle version."""
        # If custom Java version is specified, use it and skip auto-detection
        if self.custom_java_version:
            print(f"Using custom Java version: {self.custom_java_version} (overriding auto-detection)")
            return self.custom_java_version
            
        java_version = self.default_java_version
        
        if not gradle_version:
            print(f"No Gradle version detected, using default Java {java_version}")
            return java_version
        
        try:
            # Extract major.minor version
            version_parts = gradle_version.split('.')
            major = int(version_parts[0])
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
            
            # Gradle-Java compatibility mapping with fallbacks
            if major < 5:
                java_version = "8"
            elif major < 7 or (major == 6 and minor < 9):
                java_version = "11"
            elif major < 8 or (major == 7 and minor < 5):
                java_version = "17"
            else:
                # For newer Gradle versions, try Java 21 but fallback to 17
                java_version = "17"  # Changed from "21" to "17" as fallback
                print(f"For Gradle {gradle_version}, would prefer Java 21 but using Java 17 for compatibility")
            
            # Special case for Kotlin
            if has_kotlin and major < 7 or (major == 7 and minor < 3):
                if java_version in ["17", "21"]:
                    java_version = "11"
                    print(f"Kotlin detected with Gradle {gradle_version}, using Java 11 for compatibility")
            
            print(f"For Gradle {gradle_version}, using Java {java_version}")
            
        except (ValueError, IndexError):
            print(f"Could not parse Gradle version {gradle_version}, using default Java {java_version}")
        
        return java_version
    
    def detect_test_variants(self, repo_dir: Path) -> List[str]:
        """Detect available test variants in the project."""
        variants = []
        
        # Ensure we're using absolute path
        repo_dir = repo_dir.resolve()
        
        # For Android projects, prioritize unit test tasks
        print("Analyzing project structure for test variants...")
        
        # Check if this is a multi-module project
        settings_gradle = repo_dir / "settings.gradle"
        if settings_gradle.exists():
            try:
                content = settings_gradle.read_text()
                if "include" in content and ":app" in content:
                    print("Multi-module Android project detected")
                    variants.extend([
                        "testDebugUnitTest",
                        "testReleaseUnitTest", 
                        ":app:testDebugUnitTest",
                        ":app:testReleaseUnitTest"
                    ])
            except Exception as e:
                print(f"Error reading settings.gradle: {e}")
        
        # Check build.gradle files for buildTypes
        build_files = [repo_dir / "app" / "build.gradle", repo_dir / "build.gradle"]
        for build_file in build_files:
            print(f"Checking build file: {build_file}")
            if build_file.exists():
                try:
                    content = build_file.read_text()
                    if "buildTypes" in content or "android {" in content:
                        # This is an Android module
                        if "debug" in content.lower():
                            variants.extend(["testDebugUnitTest", ":app:testDebugUnitTest"])
                        if "release" in content.lower():
                            variants.extend(["testReleaseUnitTest", ":app:testReleaseUnitTest"])
                except Exception as e:
                    print(f"Error reading build file {build_file}: {e}")
        
        # Remove duplicates while preserving order
        variants = list(dict.fromkeys(variants))
        
        # Default fallback - but prefer unit test tasks
        if not variants:
            variants = ["testDebugUnitTest", "testReleaseUnitTest", "test"]
            
        print(f"Detected test variants: {variants}")
        return variants
    
    def choose_preferred_variant(self, variants: List[str]) -> str:
        """Choose the preferred test variant to run."""
        # If user specified a preference, try to honor it
        if self.preferred_variant == "debug":
            for variant in variants:
                if "debug" in variant.lower():
                    print(f"Selected debug variant: {variant}")
                    return variant
        elif self.preferred_variant == "release":
            for variant in variants:
                if "release" in variant.lower():
                    print(f"Selected release variant: {variant}")
                    return variant
        
        # Default priority order: debug -> release -> generic test
        priority = ["testDebugUnitTest", "testReleaseUnitTest", "test"]
        
        for preferred in priority:
            if preferred in variants:
                print(f"Selected test variant: {preferred}")
                return preferred
                
        # If none of the preferred variants found, use the first available
        if variants:
            selected = variants[0]
            print(f"Using first available variant: {selected}")
            return selected
            
        # Ultimate fallback
        print("No specific variants found, using generic 'test'")
        return "test"

    def run_docker_tests(self, repo_dir: Path, commit_sha: str, java_version: str, label: str) -> Tuple[Dict[str, str], Dict[str, int]]:
        """Run tests in Docker container and return test results with statistics."""
        repo_abs_path = repo_dir.absolute()
        
        # Detect and choose test variant
        variants = self.detect_test_variants(repo_dir)
        test_task = self.choose_preferred_variant(variants)
        
        # Docker command to run tests
        docker_cmd_prefix = self._get_docker_cmd_prefix()
        docker_cmd = docker_cmd_prefix + [
            "run", "--rm",
            "--network", "host",
            "--dns", "8.8.8.8", 
            "--dns", "8.8.4.4",
            "-v", f"{repo_abs_path}:/project",
            "-e", f"HOME=/tmp",  # Use /tmp as home to avoid permission issues
            "-e", f"GRADLE_USER_HOME=/tmp/.gradle",  # Set Gradle home to /tmp
            self.docker_image,
            "bash", "-c", f"""
cd /project &&
echo "=== Container environment ready ===" &&
echo "=== Checking out commit {commit_sha} ===" &&

# Handle submodules more carefully
git submodule foreach --recursive 'git reset --hard' || true &&
git checkout --force {commit_sha} &&
git submodule update --init --recursive --force || true &&

echo "=== Setting Java version to {java_version} ===" &&

# Initialize jenv if available
if command -v jenv &> /dev/null; then
    eval "$(jenv init -)"
    echo 'Available Java versions in jenv:'
    jenv versions || echo 'Failed to list jenv versions'
    jenv global {java_version} || jenv global {java_version}.0 || echo 'Failed to set Java version with jenv'
    echo 'Current Java version after jenv:'
    java -version 2>&1
    echo 'JAVA_HOME after jenv:'
    echo $JAVA_HOME
else
    echo 'jenv not available, checking default Java version:'
    java -version 2>&1
    echo 'JAVA_HOME:'
    echo $JAVA_HOME
    
    # Try to set Java version manually if jenv is not available
    case {java_version} in
        8)
            export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
            ;;
        11)
            export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
            ;;
        17)
            export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
            ;;
        21)
            export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
            ;;
    esac
    
    if [ -d "$JAVA_HOME" ]; then
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "Set JAVA_HOME to: $JAVA_HOME"
        echo "Java version after manual setup:"
        java -version 2>&1
    else
        echo "Warning: Java {java_version} not found at expected location"
        echo "Available Java installations:"
        ls -la /usr/lib/jvm/ || echo "No JVM directory found"
    fi
fi

# Set ANDROID_SDK_ROOT if needed
if [ -d '/opt/android-sdk' ]; then
    export ANDROID_SDK_ROOT='/opt/android-sdk'
    echo 'Set ANDROID_SDK_ROOT to /opt/android-sdk'
fi

# Set additional environment variables for Android builds
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_HOME='/opt/android-sdk'
export PATH="$PATH:/opt/android-sdk/platform-tools:/opt/android-sdk/tools"

# Fix HOME and Gradle directories
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle || true

echo "=== Cleaning previous builds ===" &&
rm -rf build/ || true &&
rm -rf app/build/ || true &&
rm -rf */build/ || true &&
rm -rf .gradle/ || true &&
rm -rf /tmp/.gradle/caches/ || true &&
rm -rf /tmp/.gradle/daemon/ || true &&

echo "=== Configuring Gradle ===" &&
mkdir -p /tmp/.gradle &&
echo 'org.gradle.daemon=false' > /tmp/.gradle/gradle.properties &&
echo 'org.gradle.parallel=false' >> /tmp/.gradle/gradle.properties &&
echo 'org.gradle.configureondemand=false' >> /tmp/.gradle/gradle.properties &&
echo 'org.gradle.jvmargs=-Xmx2g -XX:MaxMetaspaceSize=256m -XX:+UseG1GC' >> /tmp/.gradle/gradle.properties &&
echo 'org.gradle.workers.max=2' >> /tmp/.gradle/gradle.properties &&
echo 'android.enableJetifier=true' >> /tmp/.gradle/gradle.properties &&
echo 'android.useAndroidX=true' >> /tmp/.gradle/gradle.properties &&

echo "=== Killing any existing Gradle daemons ===" &&
./gradlew --stop 2>/dev/null || true &&
pkill -f gradle 2>/dev/null || true &&

echo "=== Running Gradle tests with multiple tasks ===" &&
if [ -f './gradlew' ]; then
    chmod +x ./gradlew
    echo "=== First attempting to download dependencies ===" &&
    timeout 300 ./gradlew --no-daemon --stacktrace dependencies || echo "Dependencies download completed/failed, continuing..." &&
    echo "=== Now running app module tests specifically ===" &&
    timeout {self.timeout_seconds} ./gradlew :app:testDebugUnitTest --no-daemon --stacktrace --info --continue || true &&
    echo "=== Running other module tests ===" &&
    timeout {self.timeout_seconds} ./gradlew testDebugUnitTest --no-daemon --stacktrace --info --continue || true &&
    echo "=== Fallback: trying individual module tests ===" &&
    timeout {self.timeout_seconds} ./gradlew :data:testDebugUnitTest :network:testDebugUnitTest :authenticatorbridge:testDebugUnitTest --no-daemon --stacktrace --info --continue || true
else
    if [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
        timeout {self.timeout_seconds} gradle :app:testDebugUnitTest testDebugUnitTest --no-daemon --stacktrace --info --continue || true
    else
        echo 'No Gradle build files found'
    fi
fi &&

echo "=== Parsing test results ===" &&
find . -name "TEST-*.xml" -type f 2>/dev/null | head -20 | while read file; do
    echo "=== XML FILE START: $file ===" 
    cat "$file"
    echo "=== XML FILE END: $file ==="
    echo ""
done

# Also show directory structure of test results
echo "=== Test Results Directory Structure ===" &&
find . -name "*test*" -type d 2>/dev/null | head -10 &&
find . -name "*.xml" -type f 2>/dev/null | head -10
"""
        ]
        
        print(f"Running Docker tests for {label} (commit: {commit_sha[:8]})")
        
        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + 60  # Extra buffer for Docker overhead
            )
            
            print(f"Docker command completed with return code: {result.returncode}")
            
            if result.stdout:
                print(f"Test output for {label}:")
                print(result.stdout[-2000:])  # Show last 2000 chars to avoid too much output
            
            if result.stderr:
                print(f"Test errors for {label}:")
                print(result.stderr[-1000:])
            
            return self.parse_test_results(result.stdout)
            
        except subprocess.TimeoutExpired:
            print(f"Docker test execution timed out for {label}")
            return {}, {"total_tests": 0, "passed_tests": 0, "failed_tests": 0, "error_tests": 0, "skipped_tests": 0}
        except Exception as e:
            print(f"Error running Docker tests for {label}: {e}")
            return {}, {"total_tests": 0, "passed_tests": 0, "failed_tests": 0, "error_tests": 0, "skipped_tests": 0}
    
    def parse_test_results(self, test_output: str) -> Tuple[Dict[str, str], Dict[str, int]]:
        """Parse test results from Docker output and return results with statistics."""
        test_results = {}
        stats = {
            "total_tests": 0,
            "passed_tests": 0, 
            "failed_tests": 0,
            "error_tests": 0,
            "skipped_tests": 0
        }
        
        # Method 1: Parse XML content directly from output
        xml_pattern = r'<testcase[^>]+name="([^"]+)"[^>]+classname="([^"]+)"[^>]*(?:/>|>.*?</testcase>)'
        xml_matches = re.findall(xml_pattern, test_output, re.DOTALL)
        
        for match in xml_matches:
            test_name = match[0].strip()
            class_name = match[1].strip()
            
            # Check if this test case has failure/error tags
            test_case_xml = re.search(
                rf'<testcase[^>]+name="{re.escape(test_name)}"[^>]+classname="{re.escape(class_name)}"[^>]*>.*?</testcase>',
                test_output, re.DOTALL
            )
            
            status = "PASSED"  # Default
            if test_case_xml:
                test_xml_content = test_case_xml.group(0)
                if '<failure' in test_xml_content:
                    status = "FAILED"
                elif '<error' in test_xml_content:
                    status = "ERROR"
                elif '<skipped' in test_xml_content:
                    status = "SKIPPED"
            
            # Format as ClassName::testMethodName  
            full_test_name = f"{class_name}::{test_name}"
            test_results[full_test_name] = status
            
            # Update statistics
            stats["total_tests"] += 1
            if status == "PASSED":
                stats["passed_tests"] += 1
            elif status == "FAILED":
                stats["failed_tests"] += 1
            elif status == "ERROR":
                stats["error_tests"] += 1
            elif status == "SKIPPED":
                stats["skipped_tests"] += 1
        
        # Method 2: Look for test case lines in the format from our parsing script
        test_pattern = r'^\s*-\s+(.+?)\s+\(([^)]+)\)(?:\s+-\s+(FAILED|ERROR|SKIPPED))?'
        
        for line in test_output.split('\n'):
            match = re.match(test_pattern, line.strip())
            if match:
                test_name = match.group(1).strip()
                class_name = match.group(2).strip()
                status = match.group(3) if match.group(3) else "PASSED"
                
                # Format as ClassName::testMethodName
                full_test_name = f"{class_name}::{test_name}"
                
                # Only add if not already found (XML parsing takes precedence)
                if full_test_name not in test_results:
                    test_results[full_test_name] = status
                    
                    # Update statistics
                    stats["total_tests"] += 1
                    if status == "PASSED":
                        stats["passed_tests"] += 1
                    elif status == "FAILED":
                        stats["failed_tests"] += 1
                    elif status == "ERROR":
                        stats["error_tests"] += 1
                    elif status == "SKIPPED":
                        stats["skipped_tests"] += 1
        
        print(f"Test Statistics:")
        print(f"  Total Tests: {stats['total_tests']}")
        print(f"  Passed: {stats['passed_tests']}")
        print(f"  Failed: {stats['failed_tests']}")
        print(f"  Errors: {stats['error_tests']}")
        print(f"  Skipped: {stats['skipped_tests']}")
        
        if test_results:
            print("Sample parsed tests:")
            for i, (test, status) in enumerate(list(test_results.items())[:3]):
                print(f"  {test} -> {status}")
        
        return test_results, stats
    
    def apply_patch(self, repo_dir: Path, patch_content: str, test_patch_content: str = "") -> bool:
        """Apply patch and test_patch to the repository."""
        try:
            # Apply main patch
            if patch_content.strip():
                print("Applying main patch...")
                patch_process = subprocess.run(
                    ["git", "apply", "--whitespace=fix", "-"],
                    input=patch_content,
                    text=True,
                    cwd=repo_dir,
                    capture_output=True
                )
                
                if patch_process.returncode != 0:
                    print(f"Failed to apply main patch: {patch_process.stderr}")
                    return False
            
            # Apply test patch if provided
            if test_patch_content.strip():
                print("Applying test patch...")
                test_patch_process = subprocess.run(
                    ["git", "apply", "--whitespace=fix", "-"],
                    input=test_patch_content,
                    text=True,
                    cwd=repo_dir,
                    capture_output=True
                )
                
                if test_patch_process.returncode != 0:
                    print(f"Failed to apply test patch: {test_patch_process.stderr}")
                    return False
            
            print("Patches applied successfully")
            return True
            
        except Exception as e:
            print(f"Error applying patches: {e}")
            return False
    
    def cleanup_repo(self, repo_dir: Path):
        """Clean up repository build artifacts and caches."""
        print(f"Cleaning up repository: {repo_dir}")
        
        # Use Docker to clean files with proper permissions FIRST
        try:
            docker_cmd_prefix = self._get_docker_cmd_prefix()
            
            # Clean as root inside Docker to handle root-owned files
            cleanup_cmd = docker_cmd_prefix + [
                "run", "--rm",
                "-v", f"{repo_dir.absolute()}:/project", 
                self.docker_image,
                "bash", "-c", """
                cd /project && 
                echo "Cleaning all build artifacts as root..." &&
                find . -name "build" -type d -exec rm -rf {} + 2>/dev/null || true &&
                find . -name ".gradle" -type d -exec rm -rf {} + 2>/dev/null || true &&
                rm -rf build/ app/build/ */build/ .gradle/ 2>/dev/null || true &&
                echo "Fixing ownership of remaining files..." &&
                chown -R $(stat -c '%u:%g' /project) . 2>/dev/null || chown -R 1000:1000 . 2>/dev/null || true &&
                chmod -R u+rwX . 2>/dev/null || true &&
                echo "Docker cleanup completed"
                """
            ]
            
            result = subprocess.run(cleanup_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"Docker cleanup warning: {result.stderr}")
            else:
                print("Docker cleanup completed successfully")
                
        except Exception as e:
            print(f"Docker cleanup failed: {e}")
        
        # Second pass: Git cleanup with better error handling
        try:
            # Fix git safe directory issue first
            subprocess.run([
                "git", "config", "--global", "--add", "safe.directory", str(repo_dir)
            ], check=False, timeout=10)
            
            # Use git stash to handle any uncommitted changes
            subprocess.run(["git", "stash", "--include-untracked"], cwd=repo_dir, check=False, timeout=30)
            subprocess.run(["git", "reset", "--hard"], cwd=repo_dir, check=True, timeout=30)
            
            # Git clean should work now that Docker fixed permissions
            result = subprocess.run(["git", "clean", "-fdx"], cwd=repo_dir, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                print("Git state reset completed")
            else:
                print(f"Git clean -fdx warning (non-critical): {result.stderr}")
                
        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not fully reset git state: {e}")
            print("This may not affect test execution")
        except subprocess.TimeoutExpired:
            print("Warning: Git cleanup timed out")
    
    def process_instance(self, instance: Dict) -> Optional[Dict]:
        """Process a single test instance."""
        instance_id = instance.get("instance_id", "unknown")
        repo = instance.get("repo", "")
        base_commit = instance.get("base_commit", "")
        patch = instance.get("patch", "")
        test_patch = instance.get("test_patch", "")
        
        # Extract all additional fields from input
        pull_number = instance.get("pull_number", "")
        issue_numbers = instance.get("issue_numbers", "")
        problem_statement = instance.get("problem_statement", "")
        hints_text = instance.get("hints_text", "")
        created_at = instance.get("created_at", "")
        
        print(f"\n=== Processing instance: {instance_id} ===")
        print(f"Repository: {repo}")
        print(f"Pull Request: {pull_number}")
        print(f"Base commit: {base_commit[:8] if base_commit else 'N/A'}")
        
        if not repo or not base_commit:
            print("Missing required fields (repo or base_commit)")
            return None
        
        # Setup repository
        repo_name = repo.replace("/", "__")
        repo_dir = self.work_dir / repo_name
        repo_url = f"https://github.com/{repo}.git"
        
        print(f"Repository directory: {repo_dir.absolute()}")
        
        if not self.clone_repository(repo_url, repo_dir):
            return None
        
        # Verify repository directory exists and is valid
        if not repo_dir.exists():
            print(f"Repository directory does not exist after cloning: {repo_dir.absolute()}")
            return None
            
        if not (repo_dir / ".git").exists():
            print(f"Repository directory is not a valid git repository: {repo_dir.absolute()}")
            return None
        
        try:
            # Setup user.properties for projects that need it (like Bitwarden)
            # self.setup_user_properties(repo_dir)
            
            # Detect project configuration
            gradle_version = self.detect_gradle_version(repo_dir)
            has_kotlin = self.detect_kotlin_usage(repo_dir)
            java_version = self.determine_java_version(gradle_version, has_kotlin)
            
            # Test base commit
            print("\n--- Testing base commit ---")
            self.cleanup_repo(repo_dir)
            base_results, base_stats = self.run_docker_tests(repo_dir, base_commit, java_version, "base")
            
            if not base_results:
                print("No test results from base commit")
                return None
            
            # Apply patches and test
            print("\n--- Applying patches and testing ---")
            self.cleanup_repo(repo_dir)
            
            # Force checkout base commit again with aggressive cleanup
            try:
                # First ensure we're in a clean state
                subprocess.run(["git", "reset", "--hard"], cwd=repo_dir, check=True, timeout=30)
                subprocess.run(["git", "clean", "-fdx"], cwd=repo_dir, check=True, timeout=30)
                
                # Now checkout the base commit
                subprocess.run(["git", "checkout", "--force", base_commit], cwd=repo_dir, check=True, timeout=30)
                print(f"Successfully checked out base commit: {base_commit[:8]}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to checkout base commit: {e}")
                return None
            except subprocess.TimeoutExpired:
                print("Git checkout timed out")
                return None
            
            if not self.apply_patch(repo_dir, patch, test_patch):
                print("Failed to apply patches")
                return None
            
            gold_results, gold_stats = self.run_docker_tests(repo_dir, "HEAD", java_version, "patched")
            
            if not gold_results:
                print("No test results from patched version")
                return None
            
            # Generate expectations
            fail_to_pass = []
            pass_to_pass = []
            
            # Get all tests that exist in both results
            all_tests = set(base_results.keys()) | set(gold_results.keys())
            
            for test in all_tests:
                base_status = base_results.get(test, "UNKNOWN")
                gold_status = gold_results.get(test, "UNKNOWN")
                
                if base_status == "FAILED" and gold_status == "PASSED":
                    fail_to_pass.append(test)
                elif base_status == "PASSED" and gold_status == "PASSED":
                    pass_to_pass.append(test)
            
            result = {
                # Original input fields
                "instance_id": instance_id,
                "repo": repo,
                "pull_number": pull_number,
                "base_commit": base_commit,
                "patch": patch,
                "test_patch": test_patch,
                "problem_statement": problem_statement,
                "hints_text": hints_text,
                "created_at": created_at,
                "issue_numbers": issue_numbers,
                
                # Generated test results
                "FAIL_TO_PASS": sorted(fail_to_pass),
                "PASS_TO_PASS": sorted(pass_to_pass),
                
                # Test execution statistics
                "base_test_stats": base_stats,
                "gold_test_stats": gold_stats,
                
                # Environment information
                "java_version": java_version,
                "gradle_version": gradle_version or "unknown"
            }
            
            print(f"\nResults Summary:")
            print(f"  FAIL_TO_PASS: {len(fail_to_pass)} tests")
            print(f"  PASS_TO_PASS: {len(pass_to_pass)} tests")
            print(f"  Base Tests - Total: {base_stats['total_tests']}, Passed: {base_stats['passed_tests']}, Failed: {base_stats['failed_tests']}")
            print(f"  Gold Tests - Total: {gold_stats['total_tests']}, Passed: {gold_stats['passed_tests']}, Failed: {gold_stats['failed_tests']}")
            
            return result
            
        except Exception as e:
            print(f"Error processing instance {instance_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # Cleanup
            try:
                self.cleanup_repo(repo_dir)
            except Exception as e:
                print(f"Error during cleanup: {e}")
    
    def process_jsonl_file(self, input_file: str, output_file: str):
        """Process JSONL file and generate results."""
        self.setup_workspace()
        self.ensure_docker_image()
        
        results = []
        
        try:
            with open(input_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        instance = json.loads(line.strip())
                        result = self.process_instance(instance)
                        
                        if result:
                            results.append(result)
                            
                            # Write incremental results
                            with open(output_file, 'w') as out_f:
                                for r in results:
                                    out_f.write(json.dumps(r) + '\n')
                            
                            print(f"Processed {len(results)} instances so far")
                        else:
                            print(f"Failed to process instance on line {line_num}")
                    
                    except json.JSONDecodeError as e:
                        print(f"Invalid JSON on line {line_num}: {e}")
                    except Exception as e:
                        print(f"Error processing line {line_num}: {e}")
        
        finally:
            self.cleanup_workspace()
        
        print(f"\nProcessing complete! Generated {len(results)} results in {output_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python android_test_runner.py <input_jsonl> [output_jsonl] [timeout_minutes] [java_version] [github_token]")
        print("  input_jsonl: Path to input JSONL file (required)")
        print("  output_jsonl: Path to output JSONL file (optional, defaults to input_file + '_test_results.jsonl')")
        print("  timeout_minutes: Test timeout in minutes (optional, default: 10)")
        print("  java_version: Custom Java version (8, 11, 17, 21) - overrides auto-detection (optional)")
        print("  github_token: GitHub Personal Access Token for private packages (optional)")
        print("")
        print("Examples:")
        print("  python android_test_runner.py input.jsonl")
        print("  python android_test_runner.py input.jsonl output.jsonl")
        print("  python android_test_runner.py input.jsonl output.jsonl 15")
        print("  python android_test_runner.py input.jsonl output.jsonl 15 17")
        print("  python android_test_runner.py input.jsonl output.jsonl 15 17 ghp_xxxxxxxxxxxx")
        print("")
        print("Environment Variables:")
        print("  GITHUB_TOKEN: Alternative way to provide GitHub token")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    # Generate default output filename if not provided
    if len(sys.argv) > 2 and sys.argv[2]:
        output_file = sys.argv[2]
    else:
        input_path = Path(input_file)
        output_file = str(input_path.parent / f"{input_path.stem}_test_results.jsonl")
    
    timeout_minutes = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else 10
    custom_java_version = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
    github_token = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else os.environ.get('GITHUB_TOKEN')
    
    if not Path(input_file).exists():
        print(f"Input file not found: {input_file}")
        sys.exit(1)
    
    if custom_java_version and custom_java_version not in ["8", "11", "17", "21"]:
        print("Invalid Java version. Use 8, 11, 17, or 21")
        sys.exit(1)
    
    print(f"Input file: {input_file}")
    print(f"Output file: {output_file}")
    print(f"Timeout: {timeout_minutes} minutes")
    print(f"Java version: {custom_java_version or 'auto-detect'}")
    
    if github_token:
        print("GitHub token provided for private package access")
    else:
        print("No GitHub token provided - may cause build failures for some projects")
    
    runner = AndroidTestRunner(
        timeout_minutes=timeout_minutes, 
        preferred_variant="debug",  # Default to debug
        docker_context=None,        # Auto-detect or use default
        custom_java_version=custom_java_version,
        github_token=github_token
    )
    runner.process_jsonl_file(input_file, output_file)


if __name__ == "__main__":
    main()