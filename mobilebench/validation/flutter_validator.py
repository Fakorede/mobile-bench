#!/usr/bin/env python3
"""
Flutter validation engine for Dart-based mobile apps.
Extends the Android validation pipeline to support Flutter projects.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class FlutterTestResult:
    """Represents a single Flutter test result."""
    test_name: str
    file_path: str
    status: str  # PASSED, FAILED, SKIPPED, ERROR
    duration: float = 0.0
    failure_message: str = ""
    
    def to_dict(self) -> dict:
        return {
            'test_name': self.test_name,
            'file_path': self.file_path,
            'status': self.status,
            'duration': self.duration,
            'failure_message': self.failure_message
        }


@dataclass
class FlutterTestExecutionResult:
    """Represents complete Flutter test execution results."""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    exit_code: int
    raw_output: str
    test_results: List[FlutterTestResult]
    flutter_command: str = ""
    
    def to_dict(self) -> dict:
        return {
            'total_tests': self.total_tests,
            'passed': self.passed,
            'failed': self.failed,
            'skipped': self.skipped,
            'errors': self.errors,
            'duration': self.duration,
            'exit_code': self.exit_code,
            'flutter_command': self.flutter_command,
            'test_results': [t.to_dict() for t in self.test_results]
        }


@dataclass
class FlutterValidationResult:
    """Validation result for a Flutter instance."""
    instance_id: str
    repo: str
    success: bool
    
    # Test execution results
    pre_solution_tests: Optional[FlutterTestExecutionResult] = None
    post_solution_tests: Optional[FlutterTestExecutionResult] = None
    
    # Test transitions
    tests_fixed: List[str] = field(default_factory=list)
    tests_broken: List[str] = field(default_factory=list)
    tests_still_failing: List[str] = field(default_factory=list)
    tests_still_passing: List[str] = field(default_factory=list)
    
    # Build status
    pre_build_failed: bool = False
    post_build_failed: bool = False
    
    # Metadata
    error_message: str = ""
    validation_time: float = 0.0
    flutter_version: str = ""
    dart_version: str = ""
    init_output: str = ""  # Initialization logs
    
    def to_dict(self) -> dict:
        return {
            'instance_id': self.instance_id,
            'repo': self.repo,
            'success': self.success,
            'pre_solution_tests': self.pre_solution_tests.to_dict() if self.pre_solution_tests else None,
            'post_solution_tests': self.post_solution_tests.to_dict() if self.post_solution_tests else None,
            'test_transitions': {
                'fail_to_pass': {
                    'count': len(self.tests_fixed),
                    'tests': self.tests_fixed
                },
                'pass_to_pass': {
                    'count': len(self.tests_still_passing),
                    'tests': self.tests_still_passing
                },
                'pass_to_fail': {
                    'count': len(self.tests_broken),
                    'tests': self.tests_broken
                },
                'fail_to_fail': {
                    'count': len(self.tests_still_failing),
                    'tests': self.tests_still_failing
                }
            },
            'error_message': self.error_message,
            'validation_time': self.validation_time,
            'flutter_version': self.flutter_version,
            'dart_version': self.dart_version,
            'init_output': self.init_output
        }


class FlutterContainerManager:
    """Manages Docker containers for Flutter builds and tests.
    
    Supports two modes:
    1. Reusable container mode (default): A single container is created once with Flutter
       pre-initialized, and repos are mounted/swapped for each instance. Much faster.
    2. Per-instance mode: Creates a new container for each instance (legacy behavior).
    """
    
    BASE_IMAGE = "mingc/android-build-box:latest"
    REUSABLE_CONTAINER_NAME = "flutter-bench-reusable"
    
    def __init__(self, docker_context: str = None, reuse_container: bool = True):
        self.containers: Dict[str, Dict] = {}
        self.docker_context = docker_context
        self.reuse_container = reuse_container
        self._reusable_container_ready = False
        self._flutter_initialized = False
        self._current_repo_path: Optional[str] = None
        self._current_flutter_date: Optional[str] = None  # Track which date's Flutter version we have
        
    def _get_docker_cmd_prefix(self) -> List[str]:
        if self.docker_context:
            return ["docker", "--context", self.docker_context]
        return ["docker"]
    
    def _container_exists(self, container_name: str) -> bool:
        """Check if a container exists and is running."""
        try:
            cmd = self._get_docker_cmd_prefix() + [
                "inspect", "-f", "{{.State.Running}}", container_name
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0 and "true" in result.stdout.lower()
        except Exception:
            return False
    
    def ensure_reusable_container(self) -> bool:
        """Ensure the reusable container exists and is running."""
        if self._reusable_container_ready:
            return True
        
        container_name = self.REUSABLE_CONTAINER_NAME
        
        # Check if container already exists and is running
        if self._container_exists(container_name):
            logger.info(f"Reusing existing container: {container_name}")
            self._reusable_container_ready = True
            return True
        
        # Remove any stopped container with the same name
        self._remove_container(container_name)
        
        logger.info(f"Creating reusable Flutter container: {container_name}")
        
        try:
            # Create container without mounting any repo yet
            # We'll copy files instead of mounting to allow swapping repos
            cmd = self._get_docker_cmd_prefix() + [
                "run", "-d",
                "--name", container_name,
                "-v", "flutter-pub-cache:/root/.pub-cache",
                "-w", "/project",
                self.BASE_IMAGE,
                "tail", "-f", "/dev/null"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                logger.error(f"Failed to create reusable container: {result.stderr}")
                return False
            
            # Create /project directory
            self._exec_in_reusable("mkdir -p /project")
            
            self._reusable_container_ready = True
            logger.info(f"Reusable container ready: {container_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating reusable container: {e}")
            return False
    
    # Latest stable Flutter version (update as needed)
    LATEST_FLUTTER_VERSION = "3.27.4"
    
    # Available Flutter versions for constraint matching (oldest to newest)
    # Based on https://docs.flutter.dev/release/archive
    AVAILABLE_FLUTTER_VERSIONS = [
        # Flutter 2.x (Dart 2.12-2.16)
        "2.0.6",   # Dart 2.12.3
        "2.2.3",   # Dart 2.13.4
        "2.5.3",   # Dart 2.14.4
        "2.8.1",   # Dart 2.15.1
        "2.10.5",  # Dart 2.16.2
        # Flutter 3.x with Dart 2.x
        "3.0.5",   # Dart 2.17.6
        "3.3.10",  # Dart 2.18.6
        "3.7.12",  # Dart 2.19.6 (last Dart 2.x)
        # Flutter 3.x with Dart 3.x
        "3.10.6",  # Dart 3.0.6
        "3.13.9",  # Dart 3.1.5
        "3.16.9",  # Dart 3.2.6
        "3.19.6",  # Dart 3.3.4
        "3.22.3",  # Dart 3.4.4
        "3.24.5",  # Dart 3.5.4
        "3.27.4",  # Dart 3.6.2
    ]
    
    def _get_flutter_version_for_constraint(self, min_version: str) -> str:
        """Get the best Flutter version that satisfies the SDK constraint.
        
        Args:
            min_version: Minimum Flutter version required (e.g., '3.10.0')
            
        Returns:
            A Flutter version string that satisfies the constraint.
        """
        if not min_version:
            return self.LATEST_FLUTTER_VERSION
        
        # Parse the minimum version
        try:
            min_parts = [int(x) for x in min_version.split('.')[:3]]
            while len(min_parts) < 3:
                min_parts.append(0)
            min_tuple = tuple(min_parts)
        except ValueError:
            logger.warning(f"Could not parse min version: {min_version}")
            return self.LATEST_FLUTTER_VERSION
        
        # Find the oldest version that satisfies the constraint
        # We want the oldest compatible version to avoid API breaks from newer Flutter
        for version in self.AVAILABLE_FLUTTER_VERSIONS:
            try:
                v_parts = [int(x) for x in version.split('.')[:3]]
                while len(v_parts) < 3:
                    v_parts.append(0)
                v_tuple = tuple(v_parts)
                
                if v_tuple >= min_tuple:
                    logger.info(f"Selected Flutter {version} (oldest compatible) for constraint >={min_version}")
                    return version
            except ValueError:
                continue
        
        logger.warning(f"No Flutter version found >= {min_version}, using latest")
        return self.LATEST_FLUTTER_VERSION
    
    def initialize_flutter_once(self, flutter_channel: str = "main", 
                                target_date: str = None) -> Tuple[bool, str]:
        """Initialize Flutter in the reusable container.
        
        Args:
            flutter_channel: Flutter channel/version - can be "main", "stable", or a specific version like "3.22.3"
            target_date: Deprecated, ignored.
        """
        # Determine which Flutter version to use
        if flutter_channel == "main":
            flutter_version = "main"
        elif flutter_channel in ("stable", "beta"):
            flutter_version = self.LATEST_FLUTTER_VERSION
        else:
            # Assume it's a version number directly
            flutter_version = flutter_channel
        
        # If we have a different version, we need to reinitialize
        if self._flutter_initialized and self._current_flutter_date != flutter_version:
            logger.info(f"Switching Flutter version from {self._current_flutter_date} to {flutter_version}")
            self._flutter_initialized = False
        
        if self._flutter_initialized:
            return True, "Flutter already initialized"
        
        if not self._reusable_container_ready:
            if not self.ensure_reusable_container():
                return False, "Failed to create reusable container"
        
        logger.info(f"Initializing Flutter {flutter_version} in reusable container...")
        
        # Build initialization commands
        commands = [
            # Configure git to trust directories
            "git config --global --add safe.directory /project",
            "git config --global --add safe.directory /opt/flutter",
            # Fetch all tags and branches
            "cd /opt/flutter && git fetch --all --tags 2>/dev/null || true",
        ]
        
        if flutter_version == "main":
            # For main channel, fetch and checkout main, then upgrade
            commands.extend([
                "cd /opt/flutter && git fetch origin main:main 2>/dev/null || git fetch origin main",
                "cd /opt/flutter && git checkout main",
                "cd /opt/flutter && flutter upgrade --force 2>&1 || flutter --version",
            ])
        else:
            # For stable versions, checkout the specific tag
            commands.extend([
                f"cd /opt/flutter && git checkout {flutter_version} 2>/dev/null || git checkout tags/{flutter_version}",
                # Clean any cached artifacts that might be incompatible
                "rm -rf /opt/flutter/bin/cache/dart-sdk* 2>/dev/null || true",
                # Run flutter to download proper artifacts
                "flutter precache --force 2>&1 || true",
            ])
        
        commands.extend([
            "flutter --version",
            "dart --version",
            "apt-get update -qq && apt-get install -y -qq libsqlite3-dev 2>&1 || true",
        ])
        
        all_output = []
        for cmd in commands:
            logger.info(f"Running: {cmd[:60]}...")
            exit_code, output = self._exec_in_reusable(cmd, timeout=600)
            all_output.append(f"$ {cmd}\n{output}")
            
            if exit_code != 0:
                # Allow certain commands to fail without stopping
                if "precache" not in cmd and "git fetch" not in cmd and "apt-get" not in cmd:
                    full_output = "\n".join(all_output)
                    logger.error(f"Flutter initialization failed at: {cmd}")
                    return False, full_output
        
        self._flutter_initialized = True
        self._current_flutter_date = flutter_version  # Track version, not date
        logger.info(f"Flutter {flutter_version} initialized successfully in reusable container")
        return True, "\n".join(all_output)
    
    def _exec_in_reusable(self, command: str, workdir: str = "/project", 
                          timeout: int = 300) -> Tuple[int, str]:
        """Execute a command in the reusable container."""
        container_name = self.REUSABLE_CONTAINER_NAME
        wrapped_command = f'export PATH="/opt/flutter/bin:$PATH" && {command}'
        
        try:
            cmd = self._get_docker_cmd_prefix() + [
                "exec", "-w", workdir,
                container_name,
                "bash", "-c", wrapped_command
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            output = result.stdout + result.stderr
            return result.returncode, output
            
        except subprocess.TimeoutExpired:
            return -1, f"Command timed out after {timeout}s"
        except Exception as e:
            return -1, str(e)
    
    def setup_repo_in_container(self, instance_id: str, repo_path: str) -> bool:
        """Copy repo files into the reusable container and setup for testing."""
        if not self._reusable_container_ready:
            if not self.ensure_reusable_container():
                return False
        
        logger.info(f"Setting up repo in container for {instance_id}...")
        
        try:
            container_name = self.REUSABLE_CONTAINER_NAME
            
            # Clean up previous repo files
            exit_code, _ = self._exec_in_reusable("rm -rf /project/* /project/.[!.]* 2>/dev/null || true")
            
            # Copy new repo into container
            cmd = self._get_docker_cmd_prefix() + [
                "cp", "-a", f"{repo_path}/.", f"{container_name}:/project/"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                logger.error(f"Failed to copy repo to container: {result.stderr}")
                return False
            
            # Register this instance
            self.containers[instance_id] = {
                'name': container_name,
                'repo_path': repo_path,
                'initialized': self._flutter_initialized,
                'using_reusable': True
            }
            
            self._current_repo_path = repo_path
            logger.info(f"Repo copied to container for {instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up repo in container: {e}")
            return False
    
    def prepare_repo_for_instance(self, instance_id: str, repo_path: str, 
                                   base_commit: str) -> bool:
        """Prepare repository for a specific instance in the reusable container.
        
        This copies the repo, resets to base commit, and cleans up any stale state.
        """
        # Copy repo files into container
        if not self.setup_repo_in_container(instance_id, repo_path):
            return False
        
        # Configure git to trust the /project directory (must be done before checkout)
        self._exec_in_reusable("git config --global --add safe.directory /project")
        
        # Checkout the base commit
        logger.info(f"Checking out base commit: {base_commit}")
        exit_code, output = self._exec_in_reusable(f"git checkout {base_commit}")
        if exit_code != 0:
            logger.error(f"Failed to checkout base commit: {output}")
            return False
        
        # Reset to clean state (in case there are any modifications)
        self._exec_in_reusable("git reset --hard HEAD")
        self._exec_in_reusable("git clean -fdx")
        
        return True
    
    # Map Dart SDK versions to compatible Flutter versions
    # Based on official Flutter release data from:
    # https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json
    DART_TO_FLUTTER_MAP = [
        # (dart_major, dart_minor, flutter_version)
        # Dart 2.x versions (null-safety introduced in 2.12)
        (2, 12, "2.0.6"),    # Dart 2.12.x -> Flutter 2.0.x (null-safety introduced)
        (2, 13, "2.2.3"),    # Dart 2.13.x -> Flutter 2.2.x
        (2, 14, "2.5.3"),    # Dart 2.14.x -> Flutter 2.5.x
        (2, 15, "2.8.1"),    # Dart 2.15.x -> Flutter 2.8.x
        (2, 16, "2.10.5"),   # Dart 2.16.x -> Flutter 2.10.x
        (2, 17, "3.0.5"),    # Dart 2.17.x -> Flutter 3.0.x
        (2, 18, "3.3.10"),   # Dart 2.18.x -> Flutter 3.3.x
        (2, 19, "3.7.12"),   # Dart 2.19.x -> Flutter 3.7.x (LAST Dart 2.x)
        # Dart 3.x versions
        (3, 0, "3.10.6"),    # Dart 3.0.x -> Flutter 3.10.x
        (3, 1, "3.13.9"),    # Dart 3.1.x -> Flutter 3.13.x
        (3, 2, "3.16.9"),    # Dart 3.2.x -> Flutter 3.16.x
        (3, 3, "3.19.6"),    # Dart 3.3.x -> Flutter 3.19.x
        (3, 4, "3.22.3"),    # Dart 3.4.x -> Flutter 3.22.x
        (3, 5, "3.24.5"),    # Dart 3.5.x -> Flutter 3.24.x
        (3, 6, "3.27.4"),    # Dart 3.6.x -> Flutter 3.27.x
        (3, 7, "3.29.3"),    # Dart 3.7.x -> Flutter 3.29.x
    ]
    
    def _get_flutter_version_for_dart_sdk(self, dart_version: str) -> Optional[str]:
        """Estimate Flutter version from Dart SDK constraint.
        
        Args:
            dart_version: Minimum Dart version required (e.g., '2.17.0', '3.0.0')
            
        Returns:
            A compatible Flutter version, or None if cannot be determined.
        """
        if not dart_version:
            return None
        
        try:
            parts = [int(x) for x in dart_version.split('.')[:2]]
            dart_major, dart_minor = parts[0], parts[1] if len(parts) > 1 else 0
        except (ValueError, IndexError):
            logger.warning(f"Could not parse Dart version: {dart_version}")
            return None
        
        # Find the Flutter version that matches this Dart SDK
        for d_major, d_minor, flutter_version in self.DART_TO_FLUTTER_MAP:
            if dart_major == d_major and dart_minor == d_minor:
                logger.info(f"Mapped Dart SDK {dart_version} -> Flutter {flutter_version}")
                return flutter_version
        
        # If exact match not found, find the closest compatible version
        # (the first Flutter version that uses a Dart SDK >= the required one)
        for d_major, d_minor, flutter_version in self.DART_TO_FLUTTER_MAP:
            if (d_major > dart_major) or (d_major == dart_major and d_minor >= dart_minor):
                logger.info(f"Mapped Dart SDK >={dart_version} -> Flutter {flutter_version} (closest match)")
                return flutter_version
        
        logger.warning(f"No Flutter version found for Dart SDK {dart_version}")
        return None
    
    def get_flutter_sdk_constraint_from_container(self) -> Optional[str]:
        """Read Flutter SDK constraint from pubspec.yaml inside the container.
        
        This should be called AFTER prepare_repo_for_instance to ensure we read
        from the correct commit.
        
        If no explicit Flutter constraint is found, attempts to estimate
        from the Dart SDK constraint.
        
        Returns:
            The minimum Flutter version required (e.g., '3.10.0'), or None if not found.
        """
        # Read pubspec.yaml from container
        exit_code, output = self._exec_in_reusable("cat /project/pubspec.yaml 2>/dev/null || echo ''")
        
        if exit_code != 0 or not output.strip():
            logger.warning("Could not read pubspec.yaml from container")
            return None
        
        content = output
        
        # Look for flutter constraint in environment section
        # Format examples:
        #   environment:
        #     sdk: ">=2.12.0 <3.0.0"
        #     flutter: ">=2.0.0"
        #
        # Or:
        #   environment:
        #     flutter: ^3.10.0
        
        # Try to find environment section with flutter constraint
        env_pattern = re.compile(
            r'environment:\s*\n(?:[^\n]*\n)*?\s*flutter:\s*["\']?([^"\'^\n]+)',
            re.MULTILINE
        )
        match = env_pattern.search(content)
        
        if not match:
            # Try simpler pattern - look for flutter: under environment
            simple_pattern = re.compile(
                r'environment:.*?flutter:\s*["\']?[>=^]*\s*(\d+\.\d+(?:\.\d+)?)',
                re.DOTALL
            )
            match = simple_pattern.search(content)
        
        if match:
            constraint = match.group(1).strip()
            # Extract the minimum version from constraint
            # Handle formats like: >=3.10.0, ^3.10.0, 3.10.0, >=3.10.0 <4.0.0
            version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', constraint)
            if version_match:
                version = version_match.group(1)
                logger.info(f"Found Flutter SDK constraint in container: {constraint} -> min version: {version}")
                return version
        
        # No explicit Flutter constraint found - try to estimate from Dart SDK
        logger.info("No explicit Flutter constraint, checking Dart SDK constraint...")
        
        # Look for sdk (Dart SDK) constraint in environment section
        # Format: sdk: ">=2.17.0 <3.0.0" or sdk: ^3.0.0
        dart_pattern = re.compile(
            r'environment:.*?sdk:\s*["\']?([^"\'\\n]+)',
            re.DOTALL
        )
        dart_match = dart_pattern.search(content)
        
        if dart_match:
            dart_constraint = dart_match.group(1).strip()
            logger.info(f"Found Dart SDK constraint: {dart_constraint}")
            
            # Extract minimum version from constraint
            min_version_match = re.search(r'>=?\s*(\d+\.\d+(?:\.\d+)?)', dart_constraint)
            if not min_version_match:
                # Try without >= prefix (e.g., ^3.0.0)
                min_version_match = re.search(r'[\^]?(\d+\.\d+(?:\.\d+)?)', dart_constraint)
            
            if not min_version_match:
                logger.warning(f"Could not parse Dart SDK constraint: {dart_constraint}")
                return None
                
            dart_min_version = min_version_match.group(1)
            
            try:
                min_parts = [int(x) for x in dart_min_version.split('.')[:2]]
                dart_min_major, dart_min_minor = min_parts[0], min_parts[1] if len(min_parts) > 1 else 0
                
                # Check for upper bound to determine maximum allowed Dart version
                # Format: <3.13.0 or <4.0.0
                upper_match = re.search(r'<\s*(\d+)\.(\d+)', dart_constraint)
                dart_max_major, dart_max_minor = None, None
                
                if upper_match:
                    dart_max_major = int(upper_match.group(1))
                    dart_max_minor = int(upper_match.group(2))
                    logger.info(f"Dart SDK upper bound: <{dart_max_major}.{dart_max_minor}")
                
                # Check if this is a pre-null-safety project
                # Pre-null-safety means Dart SDK < 2.12
                # Note: >=2.17.0 <3.0.0 is NOT pre-null-safety, it's just Dart 2.x compatible
                is_pre_null_safety = (dart_min_major == 2 and dart_min_minor < 12)
                
                if is_pre_null_safety:
                    # Use Flutter 2.10.5 - the last stable that supports non-null-safe code
                    logger.info(f"Pre-null-safety project detected (min Dart {dart_min_major}.{dart_min_minor}), using Flutter 2.10.5")
                    return "2.10.5"
                
                # Check if project is limited to Dart 2.x (upper bound <3.0.0)
                # These projects should use Flutter 3.7.12 (last Flutter with Dart 2.x)
                if dart_max_major == 3 and dart_max_minor == 0:
                    # Upper bound is <3.0.0 - use last Dart 2.x Flutter (3.7.12 with Dart 2.19)
                    logger.info(f"Dart 2.x only project (sdk: {dart_constraint}), using Flutter 3.7.12 (Dart 2.19)")
                    return "3.7.12"
                
                # For modern projects with upper bound (e.g., <3.13.0), use the NEWEST
                # Flutter version that satisfies the constraint, not the oldest
                if dart_max_major is not None:
                    # Find the newest Flutter version whose Dart SDK is < upper bound
                    best_flutter = None
                    for d_major, d_minor, flutter_version in self.DART_TO_FLUTTER_MAP:
                        # Check if this Dart version is within bounds
                        if d_major < dart_max_major or (d_major == dart_max_major and d_minor < dart_max_minor):
                            # And >= minimum
                            if d_major > dart_min_major or (d_major == dart_min_major and d_minor >= dart_min_minor):
                                best_flutter = flutter_version  # Keep updating to get newest
                    
                    if best_flutter:
                        logger.info(f"Selected newest compatible Flutter {best_flutter} for Dart constraint {dart_constraint}")
                        return best_flutter
                    
            except (ValueError, IndexError):
                pass
            
            # Fallback: use minimum version mapping
            flutter_version = self._get_flutter_version_for_dart_sdk(dart_min_version)
            if flutter_version:
                return flutter_version
        
        logger.info("No Flutter or Dart SDK constraint found in pubspec.yaml")
        return None
    
    def run_pub_get(self, instance_id: str, allow_upgrade: bool = True) -> Tuple[bool, str]:
        """Run flutter pub get for the current repo.
        
        Returns:
            Tuple of (success, output)
        """
        logger.info("Running flutter pub get...")
        exit_code, output = self._exec_in_reusable("flutter pub get", timeout=300)
        
        if exit_code == 0:
            logger.info("flutter pub get completed successfully")
            return True, output
        
        # Check if it's a resolvable dependency conflict
        if allow_upgrade and ("version solving failed" in output or "requires SDK version" in output):
            logger.warning("Dependency conflict detected, trying flutter pub upgrade...")
            
            # Try pub upgrade to resolve conflicts
            exit_code2, output2 = self._exec_in_reusable(
                "flutter pub upgrade --major-versions 2>&1 || flutter pub upgrade 2>&1",
                timeout=300
            )
            
            if exit_code2 == 0:
                logger.info("flutter pub upgrade succeeded")
                return True, output2
            
            # If upgrade also fails, try with --offline to skip resolution
            logger.warning("flutter pub upgrade also failed, trying with existing packages...")
            exit_code3, output3 = self._exec_in_reusable(
                "flutter pub get --offline 2>&1 || true",
                timeout=60
            )
            
            # Return the original error
            logger.error(f"flutter pub get failed: {output[:500]}")
            return False, output
        
        logger.error(f"flutter pub get failed: {output[:500]}")
        return False, output
    
    def cleanup_repo(self, instance_id: str):
        """Clean up git state in container (but keep container running)."""
        if instance_id in self.containers and self.containers[instance_id].get('using_reusable'):
            logger.info(f"Cleaning up repo state for {instance_id}")
            # Reset git state
            self._exec_in_reusable("git reset --hard HEAD 2>/dev/null || true")
            self._exec_in_reusable("git clean -fdx 2>/dev/null || true")
            del self.containers[instance_id]
    
    # ============ Legacy per-instance container methods ============
    
    def create_container(self, instance_id: str, repo_path: str) -> bool:
        """Create a container for an instance. Uses reusable container if enabled."""
        if self.reuse_container:
            return self.setup_repo_in_container(instance_id, repo_path)
        
        # Legacy: create new container per instance
        container_name = f"flutter-bench-{instance_id.replace('/', '-').replace('__', '-').lower()}"
        
        # Remove existing container if present
        self._remove_container(container_name)
        
        try:
            cmd = self._get_docker_cmd_prefix() + [
                "run", "-d",
                "--name", container_name,
                "-v", f"{repo_path}:/project",
                "-v", "flutter-pub-cache:/root/.pub-cache",
                "-w", "/project",
                self.BASE_IMAGE,
                "tail", "-f", "/dev/null"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                logger.error(f"Failed to create container: {result.stderr}")
                return False
            
            self.containers[instance_id] = {
                'name': container_name,
                'repo_path': repo_path,
                'initialized': False,
                'using_reusable': False
            }
            
            logger.info(f"Created container {container_name} for {instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating container: {e}")
            return False
    
    def initialize_flutter(self, instance_id: str, flutter_channel: str = "main") -> Tuple[bool, str]:
        """Initialize Flutter in the container. Returns (success, output)."""
        if instance_id not in self.containers:
            logger.error(f"Container not found for {instance_id}")
            return False, "Container not found"
        
        # If using reusable container, just run pub get (Flutter already initialized)
        if self.containers[instance_id].get('using_reusable'):
            if not self._flutter_initialized:
                success, output = self.initialize_flutter_once(flutter_channel)
                if not success:
                    return False, output
            
            # Run pub get for this specific repo
            pub_success, pub_output = self.run_pub_get(instance_id)
            return pub_success, pub_output
        
        # Legacy: full initialization for per-instance container
        container_name = self.containers[instance_id]['name']
        
        commands = [
            f"cd /opt/flutter && git fetch origin {flutter_channel}:{flutter_channel} 2>/dev/null || true",
            f"cd /opt/flutter && git checkout {flutter_channel}",
            "cd /opt/flutter && flutter upgrade --force",
            "flutter --version",
            "dart --version",
            "apt-get update -qq && apt-get install -y -qq libsqlite3-dev",
            "cd /project && flutter pub get",
        ]
        
        all_output = []
        for cmd in commands:
            logger.info(f"Running: {cmd[:60]}...")
            exit_code, output = self.exec_command(instance_id, cmd, timeout=600)
            all_output.append(f"$ {cmd}\n{output}")
            
            if exit_code != 0:
                if "flutter upgrade" not in cmd and "git fetch" not in cmd:
                    full_output = "\n".join(all_output)
                    logger.error(f"Flutter initialization failed at: {cmd}")
                    logger.error(f"Output: {output[:500]}")
                    return False, full_output
        
        self.containers[instance_id]['initialized'] = True
        logger.info(f"Flutter initialized for {instance_id}")
        return True, "\n".join(all_output)
    
    def exec_command(self, instance_id: str, command: str, 
                     workdir: str = "/project", timeout: int = 300) -> Tuple[int, str]:
        """Execute a command in the container."""
        if instance_id not in self.containers:
            return -1, f"Container not found for {instance_id}"
        
        # If using reusable container, delegate to reusable exec
        if self.containers[instance_id].get('using_reusable'):
            return self._exec_in_reusable(command, workdir, timeout)
        
        container_name = self.containers[instance_id]['name']
        
        # Wrap command to ensure Flutter is in PATH
        wrapped_command = f'export PATH="/opt/flutter/bin:$PATH" && {command}'
        
        try:
            cmd = self._get_docker_cmd_prefix() + [
                "exec", "-w", workdir,
                container_name,
                "bash", "-c", wrapped_command
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            
            output = result.stdout + result.stderr
            return result.returncode, output
            
        except subprocess.TimeoutExpired:
            return -1, f"Command timed out after {timeout}s"
        except Exception as e:
            return -1, str(e)
    
    def get_flutter_version(self, instance_id: str) -> Tuple[str, str]:
        """Get Flutter and Dart versions."""
        exit_code, output = self.exec_command(
            instance_id, 
            "flutter --version --machine 2>/dev/null || flutter --version"
        )
        
        flutter_version = ""
        dart_version = ""
        
        if exit_code == 0:
            # Try to parse JSON format first
            try:
                version_info = json.loads(output)
                flutter_version = version_info.get('frameworkVersion', '')
                dart_version = version_info.get('dartSdkVersion', '')
            except json.JSONDecodeError:
                # Parse text output
                flutter_match = re.search(r'Flutter (\d+\.\d+\.\d+)', output)
                dart_match = re.search(r'Dart (\d+\.\d+\.\d+)', output)
                if flutter_match:
                    flutter_version = flutter_match.group(1)
                if dart_match:
                    dart_version = dart_match.group(1)
        
        return flutter_version, dart_version
    
    def _remove_container(self, container_name: str):
        """Remove a container if it exists."""
        try:
            cmd = self._get_docker_cmd_prefix() + ["rm", "-f", container_name]
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception:
            pass
    
    def cleanup_container(self, instance_id: str):
        """Clean up container for an instance."""
        if instance_id not in self.containers:
            return
        
        container_info = self.containers[instance_id]
        
        if container_info.get('using_reusable'):
            # For reusable container, just clean up repo state, don't destroy container
            self.cleanup_repo(instance_id)
        else:
            # Legacy: destroy the per-instance container
            container_name = container_info['name']
            self._remove_container(container_name)
            del self.containers[instance_id]
            logger.info(f"Cleaned up container for {instance_id}")
    
    def cleanup_all(self):
        """Clean up all containers."""
        for instance_id in list(self.containers.keys()):
            self.cleanup_container(instance_id)
    
    def destroy_reusable_container(self):
        """Destroy the reusable container (call at end of validation batch)."""
        if self._reusable_container_ready:
            logger.info(f"Destroying reusable container: {self.REUSABLE_CONTAINER_NAME}")
            self._remove_container(self.REUSABLE_CONTAINER_NAME)
            self._reusable_container_ready = False
            self._flutter_initialized = False
            self._current_repo_path = None
            self._current_flutter_date = None


class FlutterTestRunner:
    """Runs Flutter tests and parses results."""
    
    def __init__(self, container_manager: FlutterContainerManager):
        self.containers = container_manager
    
    def run_tests(self, instance_id: str, test_files: List[str] = None,
                  phase: str = "UNKNOWN") -> FlutterTestExecutionResult:
        """Run Flutter tests."""
        import time
        start_time = time.time()
        
        logger.info(f"=== STARTING {phase} FLUTTER TEST PHASE for {instance_id} ===")
        
        # Build the test command
        # Note: flags must come BEFORE test file paths for older Flutter versions
        if test_files:
            # Run specific test files
            test_paths = " ".join(test_files)
            command = f"flutter test --reporter expanded {test_paths} 2>&1"
        else:
            # Run all tests
            command = "flutter test --reporter expanded 2>&1"
        
        exit_code, output = self.containers.exec_command(
            instance_id, command, timeout=600
        )
        
        duration = time.time() - start_time
        
        # Parse test results
        test_results = self._parse_test_output(output)
        
        # Calculate summary
        passed = sum(1 for t in test_results if t.status == 'PASSED')
        failed = sum(1 for t in test_results if t.status == 'FAILED')
        skipped = sum(1 for t in test_results if t.status == 'SKIPPED')
        errors = sum(1 for t in test_results if t.status == 'ERROR')
        
        result = FlutterTestExecutionResult(
            total_tests=len(test_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration=duration,
            exit_code=exit_code,
            raw_output=output,
            test_results=test_results,
            flutter_command=command
        )
        
        logger.info(f"[{instance_id}] {phase} tests: {passed} passed, {failed} failed, "
                   f"{skipped} skipped, {errors} errors (exit code: {exit_code})")
        
        return result
    
    def run_specific_tests(self, instance_id: str, test_names: List[str],
                          phase: str = "UNKNOWN") -> FlutterTestExecutionResult:
        """Run specific tests by name pattern."""
        import time
        start_time = time.time()
        
        # Use --name flag for filtering
        name_patterns = " ".join([f'--name "{name}"' for name in test_names])
        command = f"flutter test --reporter expanded {name_patterns} 2>&1"
        
        exit_code, output = self.containers.exec_command(
            instance_id, command, timeout=600
        )
        
        duration = time.time() - start_time
        test_results = self._parse_test_output(output)
        
        passed = sum(1 for t in test_results if t.status == 'PASSED')
        failed = sum(1 for t in test_results if t.status == 'FAILED')
        skipped = sum(1 for t in test_results if t.status == 'SKIPPED')
        errors = sum(1 for t in test_results if t.status == 'ERROR')
        
        return FlutterTestExecutionResult(
            total_tests=len(test_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration=duration,
            exit_code=exit_code,
            raw_output=output,
            test_results=test_results,
            flutter_command=command
        )
    
    def _parse_test_output(self, output: str) -> List[FlutterTestResult]:
        """Parse Flutter test output to extract individual test results."""
        # Flutter expanded reporter format:
        # MM:SS +passed -failed: test description
        # Examples:
        #   00:00 +0: loading /project/test/widgets/action_sheet_test.dart  <- file being loaded
        #   00:19 +131: message action sheet QuoteAndReplyButton in channel narrow with empty topic  <- test starts
        #   00:20 +131 -1: message action sheet QuoteAndReplyButton in channel narrow with empty topic [E]  <- test failed
        #   00:25 +174: All tests passed!
        #
        # Key insight: A test may appear multiple times (start, then complete with status marker)
        # We need to use the FINAL status for each test (with [E] or [S] markers, or infer from counters)
        
        # Extract file path from loading line
        # Format: MM:SS +N: loading /path/to/test_file.dart
        loading_pattern = re.compile(r'^\d{2}:\d{2}\s+\+\d+:\s+loading\s+(.+\.dart)\s*$', re.MULTILINE)
        file_path = ""
        loading_match = loading_pattern.search(output)
        if loading_match:
            file_path = loading_match.group(1).strip()
            # Convert /project/test/... to relative path test/...
            if file_path.startswith('/project/'):
                file_path = file_path[9:]  # Remove '/project/'
        
        # Pattern for individual test lines
        # Format: MM:SS +N [-N]: test description [optional status marker]
        test_line_pattern = re.compile(
            r'^\d{2}:\d{2}\s+\+(\d+)(?:\s+-(\d+))?:\s+(.+?)(?:\s+\[([ES])\])?\s*$',
            re.MULTILINE
        )
        
        # First pass: collect all test occurrences with their final status
        test_status_map = {}  # test_name -> (status, failure_msg)
        prev_failed = 0
        
        for match in test_line_pattern.finditer(output):
            current_passed = int(match.group(1))
            current_failed = int(match.group(2)) if match.group(2) else 0
            test_name = match.group(3).strip()
            status_marker = match.group(4)  # 'E' for error, 'S' for skipped
            
            # Skip summary lines
            if test_name in ('All tests passed!', 'Some tests failed.'):
                continue
            
            # Skip loading lines
            if test_name.startswith('loading '):
                continue
            
            # Determine status for THIS occurrence
            if status_marker == 'E':
                status = 'FAILED'
            elif status_marker == 'S':
                status = 'SKIPPED'
            elif current_failed > prev_failed:
                status = 'FAILED'
            else:
                status = 'PASSED'
            
            # Extract failure message if test failed
            failure_msg = ""
            if status == 'FAILED':
                # Look for exception details after the test line with [E] marker
                error_section = re.search(
                    rf'{re.escape(test_name)}\s*\[E\].*?\n(.*?)(?=\n\d{{2}}:\d{{2}}\s+\+|\nAll tests passed|\nSome tests failed|$)',
                    output, re.DOTALL
                )
                if error_section:
                    error_text = error_section.group(1).strip()
                    if 'EXCEPTION CAUGHT' in error_text or 'TestFailure' in error_text or 'Test failed' in error_text:
                        failure_msg = error_text[:1000]
            
            # Update the test status - later occurrences override earlier ones
            # This ensures we capture the [E] marker status even if test appeared earlier without it
            if test_name not in test_status_map:
                test_status_map[test_name] = (status, failure_msg)
            elif status == 'FAILED':
                # Failed status always overrides (the [E] marker appearance)
                test_status_map[test_name] = (status, failure_msg)
            elif status == 'SKIPPED' and test_status_map[test_name][0] == 'PASSED':
                # Skipped overrides passed
                test_status_map[test_name] = (status, failure_msg)
            # Otherwise keep the existing status (don't override FAILED with PASSED)
            
            prev_failed = current_failed
        
        # Build results list
        results = []
        for test_name, (status, failure_msg) in test_status_map.items():
            results.append(FlutterTestResult(
                test_name=test_name,
                file_path=file_path,
                status=status,
                failure_message=failure_msg if status == 'FAILED' else ""
            ))
        
        # Fallback: Try the checkmark format (some Flutter versions use this)
        if not results:
            seen_tests = set()  # Track unique test names for fallback parsing
            # Pattern for checkmark format
            # ✓ Test description (duration)
            # ✗ Test description (duration)
            passed_pattern = re.compile(r'[✓✔]\s+(.+?)\s*(?:\((\d+(?:\.\d+)?)\s*(?:ms|s)\))?$', re.MULTILINE)
            failed_pattern = re.compile(r'[✗✘]\s+(.+?)\s*(?:\((\d+(?:\.\d+)?)\s*(?:ms|s)\))?$', re.MULTILINE)
            skipped_pattern = re.compile(r'[○◯]\s+(.+?)(?:\s+\[S\])?\s*$', re.MULTILINE)
            
            for match in passed_pattern.finditer(output):
                test_name = match.group(1).strip()
                if test_name not in seen_tests:
                    seen_tests.add(test_name)
                    duration_str = match.group(2) or "0"
                    try:
                        duration = float(duration_str) / 1000 if 'ms' in (match.group(0) or '') else float(duration_str)
                    except ValueError:
                        duration = 0.0
                    
                    results.append(FlutterTestResult(
                        test_name=test_name,
                        file_path=file_path,
                        status='PASSED',
                        duration=duration
                    ))
            
            for match in failed_pattern.finditer(output):
                test_name = match.group(1).strip()
                if test_name not in seen_tests:
                    seen_tests.add(test_name)
                    results.append(FlutterTestResult(
                        test_name=test_name,
                        file_path=file_path,
                        status='FAILED'
                    ))
            
            for match in skipped_pattern.finditer(output):
                test_name = match.group(1).strip()
                if test_name not in seen_tests:
                    seen_tests.add(test_name)
                    results.append(FlutterTestResult(
                        test_name=test_name,
                        file_path=file_path,
                        status='SKIPPED'
                    ))
        
        # Final fallback: parse summary line if no individual tests found
        if not results:
            test_summary = re.search(r'(\d+) tests? passed.*?(\d+) failed', output)
            if test_summary:
                passed_count = int(test_summary.group(1))
                failed_count = int(test_summary.group(2))
                
                for i in range(passed_count):
                    results.append(FlutterTestResult(
                        test_name=f"test_{i+1}",
                        file_path=file_path,
                        status='PASSED'
                    ))
                for i in range(failed_count):
                    results.append(FlutterTestResult(
                        test_name=f"failed_test_{i+1}",
                        file_path=file_path,
                        status='FAILED'
                    ))
        
        logger.info(f"Parsed {len(results)} test results: "
                   f"{sum(1 for t in results if t.status == 'PASSED')} passed, "
                   f"{sum(1 for t in results if t.status == 'FAILED')} failed, "
                   f"{sum(1 for t in results if t.status == 'SKIPPED')} skipped")
        
        return results


class FlutterConfigParser:
    """Parses Flutter project configuration."""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
    
    def parse_pubspec(self) -> Dict[str, Any]:
        """Parse pubspec.yaml for project configuration."""
        pubspec_path = self.project_path / "pubspec.yaml"
        
        if not pubspec_path.exists():
            logger.warning(f"pubspec.yaml not found at {pubspec_path}")
            return {}
        
        try:
            import yaml
            with open(pubspec_path) as f:
                return yaml.safe_load(f)
        except ImportError:
            # Fallback: basic parsing without yaml library
            config = {}
            with open(pubspec_path) as f:
                content = f.read()
                
                name_match = re.search(r'^name:\s*(.+)$', content, re.MULTILINE)
                if name_match:
                    config['name'] = name_match.group(1).strip()
                
                sdk_match = re.search(r"sdk:\s*['\"]?>=?(\d+\.\d+\.\d+)", content)
                if sdk_match:
                    config['sdk_version'] = sdk_match.group(1)
            
            return config
        except Exception as e:
            logger.error(f"Error parsing pubspec.yaml: {e}")
            return {}
    
    def get_flutter_channel(self) -> str:
        """Determine which Flutter channel the project needs."""
        # Check for .flutter-version or similar
        version_file = self.project_path / ".flutter-version"
        if version_file.exists():
            with open(version_file) as f:
                version = f.read().strip()
                if 'main' in version or 'master' in version:
                    return 'main'
                elif 'beta' in version:
                    return 'beta'
        
        # Default to stable, but some projects (like zulip) need main
        return "stable"
    
    def get_flutter_sdk_constraint(self) -> Optional[str]:
        """Extract Flutter SDK version constraint from pubspec.yaml.
        
        Returns the minimum Flutter version required, e.g., '3.10.0' or '2.17.0'.
        Returns None if no constraint is found.
        """
        pubspec_path = self.project_path / "pubspec.yaml"
        if not pubspec_path.exists():
            return None
        
        try:
            with open(pubspec_path) as f:
                content = f.read()
            
            # Look for flutter constraint in environment section
            # Format examples:
            #   flutter: ">=3.10.0"
            #   flutter: '>=3.0.0 <4.0.0'
            #   flutter: ^3.10.0
            #   flutter: 3.10.0
            
            # Try to find environment section with flutter constraint
            env_pattern = re.compile(
                r'environment:\s*\n(?:[^\n]*\n)*?\s*flutter:\s*["\']?([^"\'^\n]+)',
                re.MULTILINE
            )
            match = env_pattern.search(content)
            
            if not match:
                # Try simpler pattern for direct flutter version constraint
                simple_pattern = re.compile(
                    r'^\s*flutter:\s*["\']?[>=^]*\s*(\d+\.\d+(?:\.\d+)?)',
                    re.MULTILINE
                )
                match = simple_pattern.search(content)
            
            if match:
                constraint = match.group(1).strip()
                # Extract the minimum version from constraint
                # Handle formats like: >=3.10.0, ^3.10.0, 3.10.0, >=3.10.0 <4.0.0
                version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', constraint)
                if version_match:
                    version = version_match.group(1)
                    logger.info(f"Found Flutter SDK constraint: {constraint} -> min version: {version}")
                    return version
            
            return None
            
        except Exception as e:
            logger.warning(f"Error parsing Flutter SDK constraint: {e}")
            return None
    
    def extract_test_files_from_patch(self, test_patch: str) -> List[str]:
        """Extract test file paths from a test patch."""
        test_files = []
        
        # Pattern to match file paths in diff headers
        file_pattern = re.compile(r'^(?:---|\+\+\+) [ab]/(.+_test\.dart)$', re.MULTILINE)
        
        for match in file_pattern.finditer(test_patch):
            file_path = match.group(1)
            if file_path not in test_files:
                test_files.append(file_path)
        
        return test_files
    
    def is_flutter_project(self) -> bool:
        """Check if this is a Flutter project."""
        pubspec_path = self.project_path / "pubspec.yaml"
        if not pubspec_path.exists():
            return False
        
        with open(pubspec_path) as f:
            content = f.read()
            return 'flutter:' in content or 'flutter_test:' in content


class FlutterValidator:
    """Main Flutter validation engine."""
    
    def __init__(self, output_dir: str = "flutter_validation_results",
                 docker_context: str = None,
                 reuse_container: bool = True):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.containers = FlutterContainerManager(docker_context)
        self.test_runner = FlutterTestRunner(self.containers)
        self.reuse_container = reuse_container
        self._flutter_channel = None  # Cache channel for reusable container
    
    def validate_instance(self, instance: Dict[str, Any]) -> FlutterValidationResult:
        """Validate a single Flutter instance (auto-selects reusable or legacy mode)."""
        if self.reuse_container:
            return self.validate_instance_reusable(instance)
        else:
            return self.validate_instance_legacy(instance)
    
    def validate_instance_reusable(self, instance: Dict[str, Any]) -> FlutterValidationResult:
        """Validate a single Flutter instance using the reusable container."""
        import time
        start_time = time.time()
        
        instance_id = instance.get('instance_id', 'unknown')
        repo = instance.get('repo', '')
        base_commit = instance.get('base_commit', '')
        
        logger.info(f"{'='*60}")
        logger.info(f"Validating Flutter instance (reusable): {instance_id}")
        logger.info(f"{'='*60}")
        
        result = FlutterValidationResult(
            instance_id=instance_id,
            repo=repo,
            success=False
        )
        
        repo_path = None
        
        try:
            # 1. Clone repository locally
            repo_path = self._clone_repository(instance)
            if not repo_path:
                result.error_message = "Failed to clone repository"
                return result
            
            # 2. Check if it's a Flutter project (basic check on local clone)
            config_parser = FlutterConfigParser(repo_path)
            if not config_parser.is_flutter_project():
                result.error_message = "Not a Flutter project"
                return result
            
            # 3. Extract test files from patch (can be done early, doesn't depend on Flutter version)
            test_patch = instance.get('test_patch', '')
            test_files = config_parser.extract_test_files_from_patch(test_patch)
            
            if not test_files:
                logger.warning(f"No test files found in patch for {instance_id}, skipping instance")
                result.error_message = "No test files found in patch - skipping instance"
                return result
            else:
                logger.info(f"Found {len(test_files)} test file(s): {test_files}")
            
            # 4. Get or create reusable container (one-time)
            if not self.containers.ensure_reusable_container():
                result.error_message = "Failed to create/get reusable container"
                return result
            
            # 5. Copy repo to container and checkout base commit FIRST
            # This ensures we read pubspec.yaml from the correct commit
            if not self.containers.prepare_repo_for_instance(instance_id, repo_path, base_commit):
                result.error_message = "Failed to prepare repository in container"
                return result
            
            # 6. NOW read Flutter SDK constraint from pubspec.yaml inside the container
            # This is done AFTER checkout to ensure we get the correct version for this commit
            use_main_channel = False
            if 'zulip' in repo.lower():
                use_main_channel = True  # Zulip uses bleeding-edge Flutter
            
            flutter_sdk_constraint = self.containers.get_flutter_sdk_constraint_from_container()
            
            if use_main_channel:
                target_flutter_version = "main"  # Use latest main for dev-focused projects
            elif flutter_sdk_constraint:
                # Use the SDK constraint from pubspec.yaml to select the right version
                target_flutter_version = self.containers._get_flutter_version_for_constraint(
                    flutter_sdk_constraint
                )
                logger.info(f"Using Flutter version {target_flutter_version} based on pubspec.yaml constraint: >={flutter_sdk_constraint}")
            else:
                # Fallback to latest stable
                target_flutter_version = self.containers.LATEST_FLUTTER_VERSION
                logger.info(f"No Flutter/Dart SDK constraint found in pubspec.yaml, using latest: {target_flutter_version}")
            
            # 7. Initialize Flutter SDK (reinitialize if version changed)
            current_version = self.containers._current_flutter_date  # This stores version/channel
            need_reinit = (current_version != target_flutter_version)
            
            if need_reinit or not self.containers._flutter_initialized:
                logger.info(f"Initializing Flutter {target_flutter_version}...")
                init_success, init_output = self.containers.initialize_flutter_once(
                    target_flutter_version
                )
                result.init_output = init_output
                
                if not init_success:
                    result.error_message = "Failed to initialize Flutter"
                    return result
            
            # 8. Run pub get for this instance (AFTER Flutter is initialized with correct version)
            pub_success, pub_output = self.containers.run_pub_get(instance_id)
            if not pub_success:
                result.error_message = "Failed to run pub get"
                return result
            
            # Get versions
            result.flutter_version, result.dart_version = \
                self.containers.get_flutter_version(instance_id)
            
            # 9. Apply test patch and run PRE-solution tests
            if not self._apply_patch(instance_id, test_patch, "test"):
                result.error_message = "Failed to apply test patch"
                return result
            
            result.pre_solution_tests = self.test_runner.run_tests(
                instance_id, test_files if test_files else None, phase="PRE-SOLUTION"
            )
            
            # 10. Apply solution patch
            solution_patch = instance.get('patch', '')
            if not self._apply_patch(instance_id, solution_patch, "solution"):
                result.error_message = "Failed to apply solution patch"
                return result
            
            # 11. Run POST-solution tests
            result.post_solution_tests = self.test_runner.run_tests(
                instance_id, test_files if test_files else None, phase="POST-SOLUTION"
            )
            
            # 12. Analyze test transitions
            self._analyze_test_transitions(result)
            
            # 13. Determine success
            result.success = self._determine_success(result)
            
        except Exception as e:
            logger.exception(f"Error validating {instance_id}")
            result.error_message = str(e)
        
        finally:
            # Cleanup - for reusable mode, this just clears state, doesn't destroy container
            result.validation_time = time.time() - start_time
            self._save_result(result)
            
            if repo_path:
                self._cleanup_repository(repo_path)
            self.containers.cleanup_container(instance_id)
        
        return result
    
    def validate_instance_legacy(self, instance: Dict[str, Any]) -> FlutterValidationResult:
        """Validate a single Flutter instance."""
        import time
        start_time = time.time()
        
        instance_id = instance.get('instance_id', 'unknown')
        repo = instance.get('repo', '')
        
        logger.info(f"{'='*60}")
        logger.info(f"Validating Flutter instance: {instance_id}")
        logger.info(f"{'='*60}")
        
        result = FlutterValidationResult(
            instance_id=instance_id,
            repo=repo,
            success=False
        )
        
        repo_path = None
        
        try:
            # 1. Clone repository
            repo_path = self._clone_repository(instance)
            if not repo_path:
                result.error_message = "Failed to clone repository"
                return result
            
            # 2. Check if it's a Flutter project
            config_parser = FlutterConfigParser(repo_path)
            if not config_parser.is_flutter_project():
                result.error_message = "Not a Flutter project"
                return result
            
            # 3. Create container
            if not self.containers.create_container(instance_id, repo_path):
                result.error_message = "Failed to create Docker container"
                return result
            
            # 4. Initialize Flutter - use SDK constraint from pubspec.yaml
            flutter_sdk_constraint = config_parser.get_flutter_sdk_constraint()
            
            # Override for known projects that need main channel
            if 'zulip' in repo.lower():
                flutter_channel = 'main'
            elif flutter_sdk_constraint:
                # Use the SDK constraint from pubspec.yaml to select the right version
                flutter_channel = self.containers._get_flutter_version_for_constraint(
                    flutter_sdk_constraint
                )
                logger.info(f"Using Flutter version {flutter_channel} based on pubspec.yaml constraint: >={flutter_sdk_constraint}")
            else:
                # Fallback to latest stable
                flutter_channel = self.containers.LATEST_FLUTTER_VERSION
                logger.info(f"No Flutter/Dart SDK constraint found, using latest: {flutter_channel}")
            
            init_success, init_output = self.containers.initialize_flutter(instance_id, flutter_channel)
            
            # Save initialization logs
            result.init_output = init_output
            
            if not init_success:
                result.error_message = "Failed to initialize Flutter"
                return result
            
            # Get versions
            result.flutter_version, result.dart_version = \
                self.containers.get_flutter_version(instance_id)
            
            # 5. Extract test files from patch
            test_patch = instance.get('test_patch', '')
            test_files = config_parser.extract_test_files_from_patch(test_patch)
            
            if not test_files:
                logger.warning(f"No test files found in patch for {instance_id}, skipping instance")
                result.error_message = "No test files found in patch - skipping instance"
                return result
            else:
                logger.info(f"Found {len(test_files)} test file(s): {test_files}")
            
            # 6. Apply test patch and run PRE-solution tests
            if not self._apply_patch(instance_id, test_patch, "test"):
                result.error_message = "Failed to apply test patch"
                return result
            
            result.pre_solution_tests = self.test_runner.run_tests(
                instance_id, test_files if test_files else None, phase="PRE-SOLUTION"
            )
            
            # 7. Apply solution patch
            solution_patch = instance.get('patch', '')
            if not self._apply_patch(instance_id, solution_patch, "solution"):
                result.error_message = "Failed to apply solution patch"
                return result
            
            # 8. Run POST-solution tests
            result.post_solution_tests = self.test_runner.run_tests(
                instance_id, test_files if test_files else None, phase="POST-SOLUTION"
            )
            
            # 9. Analyze test transitions
            self._analyze_test_transitions(result)
            
            # 10. Determine success
            result.success = self._determine_success(result)
            
        except Exception as e:
            logger.exception(f"Error validating {instance_id}")
            result.error_message = str(e)
        
        finally:
            # Cleanup
            result.validation_time = time.time() - start_time
            self._save_result(result)
            
            if repo_path:
                self._cleanup_repository(repo_path)
            self.containers.cleanup_container(instance_id)
        
        return result
    
    def _clone_repository(self, instance: Dict[str, Any]) -> Optional[str]:
        """Clone repository to a temporary directory."""
        repo = instance.get('repo', '')
        base_commit = instance.get('base_commit', '')
        
        if not repo or not base_commit:
            logger.error("Missing repo or base_commit")
            return None
        
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp(prefix="flutter-bench-")
            
            # Clone repository (full clone to ensure all commits are available)
            clone_url = f"https://github.com/{repo}.git"
            result = subprocess.run(
                ["git", "clone", clone_url, temp_dir],
                capture_output=True, text=True, timeout=600
            )
            
            if result.returncode != 0:
                logger.error(f"Clone failed: {result.stderr}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            
            # Checkout base commit
            result = subprocess.run(
                ["git", "-C", temp_dir, "checkout", base_commit],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"Checkout failed: {result.stderr}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            
            logger.info(f"Cloned {repo} at {base_commit}")
            return temp_dir
            
        except Exception as e:
            logger.error(f"Error cloning repository: {e}")
            return None
    
    def _apply_patch(self, instance_id: str, patch: str, patch_type: str) -> bool:
        """Apply a patch to the repository."""
        if not patch or not patch.strip():
            logger.info(f"No {patch_type} patch to apply")
            return True
        
        # Write patch to local temp file first, then copy to container
        # This avoids "Argument list too long" errors for large patches
        import tempfile
        
        container_patch_file = f"/tmp/{patch_type}_patch.diff"
        
        try:
            # Write patch to local temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False) as f:
                f.write(patch)
                local_patch_file = f.name
            
            # Copy patch file to container
            container_name = self.containers.REUSABLE_CONTAINER_NAME
            cmd = self.containers._get_docker_cmd_prefix() + [
                "cp", local_patch_file, f"{container_name}:{container_patch_file}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            # Clean up local temp file
            import os
            os.unlink(local_patch_file)
            
            if result.returncode != 0:
                logger.error(f"Failed to copy patch file to container: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to write patch file: {e}")
            return False
        
        # Apply patch
        exit_code, output = self.containers.exec_command(
            instance_id,
            f"git apply --verbose {container_patch_file} 2>&1"
        )
        
        if exit_code != 0:
            # Try with more lenient options
            exit_code, output = self.containers.exec_command(
                instance_id,
                f"git apply --verbose --reject --whitespace=fix {container_patch_file} 2>&1"
            )
        
        if exit_code != 0:
            logger.error(f"Failed to apply {patch_type} patch: {output}")
            return False
        
        logger.info(f"Applied {patch_type} patch successfully")
        
        # Run pub get after applying patch
        exit_code, output = self.containers.exec_command(
            instance_id, "flutter pub get 2>&1"
        )
        
        return True
    
    def _analyze_test_transitions(self, result: FlutterValidationResult):
        """Analyze how tests transitioned between pre and post solution."""
        if not result.pre_solution_tests or not result.post_solution_tests:
            return
        
        pre_results = {t.test_name: t.status for t in result.pre_solution_tests.test_results}
        post_results = {t.test_name: t.status for t in result.post_solution_tests.test_results}
        
        all_tests = set(pre_results.keys()) | set(post_results.keys())
        
        for test in all_tests:
            pre_status = pre_results.get(test, 'MISSING')
            post_status = post_results.get(test, 'MISSING')
            
            pre_passed = pre_status == 'PASSED'
            post_passed = post_status == 'PASSED'
            
            if not pre_passed and post_passed:
                result.tests_fixed.append(test)
            elif pre_passed and not post_passed:
                result.tests_broken.append(test)
            elif not pre_passed and not post_passed:
                result.tests_still_failing.append(test)
            elif pre_passed and post_passed:
                result.tests_still_passing.append(test)
    
    def _determine_success(self, result: FlutterValidationResult) -> bool:
        """Determine if validation was successful."""
        # Success criteria:
        # 1. At least one test was fixed (fail -> pass)
        # 2. No tests were broken (pass -> fail)
        # 3. Post-solution tests have better or equal pass rate
        
        if not result.pre_solution_tests or not result.post_solution_tests:
            return False
        
        # Check for broken tests
        if result.tests_broken:
            logger.warning(f"Tests broken by solution: {result.tests_broken}")
            return False
        
        # Check for fixed tests
        if result.tests_fixed:
            logger.info(f"Tests fixed by solution: {result.tests_fixed}")
            return True
        
        # Check overall pass rate improvement
        pre_pass_rate = result.pre_solution_tests.passed / max(1, result.pre_solution_tests.total_tests)
        post_pass_rate = result.post_solution_tests.passed / max(1, result.post_solution_tests.total_tests)
        
        return post_pass_rate >= pre_pass_rate
    
    def _save_result(self, result: FlutterValidationResult):
        """Save validation result to disk."""
        instance_dir = self.output_dir / result.instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        
        # Save result JSON
        result_file = instance_dir / "validation_result.json"
        with open(result_file, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        
        # Save initialization logs
        if result.init_output:
            init_log = instance_dir / "flutter_init.log"
            with open(init_log, 'w') as f:
                f.write(result.init_output)
        
        # Save raw test outputs
        if result.pre_solution_tests:
            pre_log = instance_dir / "pre_solution_tests.log"
            with open(pre_log, 'w') as f:
                f.write(result.pre_solution_tests.raw_output)
        
        if result.post_solution_tests:
            post_log = instance_dir / "post_solution_tests.log"
            with open(post_log, 'w') as f:
                f.write(result.post_solution_tests.raw_output)
        
        logger.info(f"Saved results to {instance_dir}")
    
    def _cleanup_repository(self, repo_path: str):
        """Clean up cloned repository."""
        try:
            shutil.rmtree(repo_path, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Error cleaning up repo: {e}")
    
    def validate_dataset(self, dataset_file: str, 
                         instance_ids: List[str] = None,
                         exclude_ids: List[str] = None,
                         skip_existing: bool = False,
                         max_instances: int = None) -> Dict[str, FlutterValidationResult]:
        """Validate multiple instances from a dataset file."""
        results = {}
        
        # Load dataset
        instances = []
        with open(dataset_file) as f:
            for line in f:
                if line.strip():
                    instances.append(json.loads(line))
        
        # Filter instances if specified
        if instance_ids:
            instances = [i for i in instances if i.get('instance_id') in instance_ids]
        
        # Exclude specific instances
        if exclude_ids:
            instances = [i for i in instances if i.get('instance_id') not in exclude_ids]
        
        # Skip instances that already have results
        if skip_existing:
            existing = set()
            if self.output_dir.exists():
                for d in self.output_dir.iterdir():
                    if d.is_dir() and (d / "validation_result.json").exists():
                        existing.add(d.name)
            if existing:
                logger.info(f"Skipping {len(existing)} instances with existing results")
                instances = [i for i in instances if i.get('instance_id') not in existing]
        
        if max_instances:
            instances = instances[:max_instances]
        
        # Sort by created_at date (month) to minimize Flutter SDK switches
        # Instances from the same month will use the same Flutter version
        instances.sort(key=lambda x: x.get('created_at', '')[:7])  # Sort by YYYY-MM
        
        logger.info(f"Validating {len(instances)} Flutter instances")
        
        try:
            for instance in instances:
                instance_id = instance.get('instance_id', 'unknown')
                result = self.validate_instance(instance)
                results[instance_id] = result
        finally:
            # Clean up reusable container at the end of batch processing
            if self.reuse_container:
                self.containers.destroy_reusable_container()
        
        # Save summary
        self._save_summary(results)
        
        return results
    
    def _save_summary(self, results: Dict[str, FlutterValidationResult]):
        """Save validation summary."""
        summary = {
            'total': len(results),
            'successful': sum(1 for r in results.values() if r.success),
            'failed': sum(1 for r in results.values() if not r.success),
            'results': {k: v.to_dict() for k, v in results.items()}
        }
        
        summary_file = self.output_dir / "validation_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Validation complete: {summary['successful']}/{summary['total']} successful")


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Flutter Validation Engine")
    parser.add_argument("dataset_file", help="Path to dataset JSONL file")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to validate")
    parser.add_argument("--exclude-instances", nargs="+", help="Instance IDs to exclude")
    parser.add_argument("--skip-existing", action="store_true", 
                        help="Skip instances that already have results in output dir")
    parser.add_argument("--max-instances", type=int, help="Maximum instances to validate")
    parser.add_argument("--output-dir", default="flutter_validation_results", help="Output directory")
    parser.add_argument("--docker-context", help="Docker context to use")
    parser.add_argument("--no-reuse", action="store_true", 
                        help="Don't reuse container between instances (slower but more isolated)")
    
    args = parser.parse_args()
    
    validator = FlutterValidator(
        output_dir=args.output_dir,
        docker_context=args.docker_context,
        reuse_container=not args.no_reuse
    )
    
    results = validator.validate_dataset(
        args.dataset_file,
        instance_ids=args.instance_ids,
        exclude_ids=args.exclude_instances,
        skip_existing=args.skip_existing,
        max_instances=args.max_instances
    )
    
    # Print summary
    successful = sum(1 for r in results.values() if r.success)
    print(f"\n{'='*60}")
    print(f"Flutter Validation Complete")
    print(f"{'='*60}")
    print(f"Total: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(results) - successful}")
    print(f"Results saved to: {args.output_dir}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
