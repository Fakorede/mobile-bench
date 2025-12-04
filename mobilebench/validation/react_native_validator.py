#!/usr/bin/env python3
"""
React Native validation engine for JavaScript/TypeScript-based mobile apps.
Extends the validation pipeline to support React Native projects.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import shutil
import asyncio
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
class ReactNativeTestResult:
    """Represents a single React Native test result."""
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
class ReactNativeTestExecutionResult:
    """Represents complete React Native test execution results."""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    exit_code: int
    raw_output: str
    test_results: List[ReactNativeTestResult]
    test_command: str = ""
    
    def to_dict(self) -> dict:
        return {
            'total_tests': self.total_tests,
            'passed': self.passed,
            'failed': self.failed,
            'skipped': self.skipped,
            'errors': self.errors,
            'duration': self.duration,
            'exit_code': self.exit_code,
            'test_command': self.test_command,
            'test_results': [t.to_dict() for t in self.test_results]
        }


@dataclass
class ReactNativeValidationResult:
    """Validation result for a React Native instance."""
    instance_id: str
    repo: str
    success: bool
    
    # Test execution results
    pre_solution_tests: Optional[ReactNativeTestExecutionResult] = None
    post_solution_tests: Optional[ReactNativeTestExecutionResult] = None
    
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
    node_version: str = ""
    npm_version: str = ""
    react_native_version: str = ""
    package_manager: str = ""  # npm, yarn, pnpm
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
            'node_version': self.node_version,
            'npm_version': self.npm_version,
            'react_native_version': self.react_native_version,
            'package_manager': self.package_manager,
            'init_output': self.init_output
        }


class ReactNativeContainerManager:
    """Manages Docker containers for React Native builds and tests.
    
    Supports two modes:
    1. Reusable container mode (default): A single container is created once with Node.js
       and Android SDK pre-initialized, and repos are mounted/swapped for each instance.
    2. Per-instance mode: Creates a new container for each instance (legacy behavior).
    
    React Native requires:
    - Node.js (for JavaScript runtime, npm/yarn, Metro bundler)
    - Android SDK (for building Android apps)
    - Java/JDK (required by Android SDK)
    
    For unit tests (Jest), only Node.js is typically needed.
    For integration tests or app builds, Android SDK is required.
    """
    
    # Docker image for React Native validation:
    # reactnativecommunity/react-native-android has Node.js + Android SDK pre-installed
    # We install nvm on top to allow switching Node.js versions per project
    DEFAULT_IMAGE = "reactnativecommunity/react-native-android:latest"
    REUSABLE_CONTAINER_NAME = "react-native-bench-reusable"
    
    def __init__(self, docker_context: str = None, reuse_container: bool = True):
        """
        Initialize the container manager.
        
        Args:
            docker_context: Docker context to use (optional)
            reuse_container: Whether to reuse container between instances
        """
        self.containers: Dict[str, Dict] = {}
        self.docker_context = docker_context
        self.reuse_container = reuse_container
        self._reusable_container_ready = False
        self._node_initialized = False
        self._current_repo_path: Optional[str] = None
        self._current_node_version: Optional[str] = None
        self._image_to_use = self.DEFAULT_IMAGE
        
    def _get_docker_cmd_prefix(self) -> List[str]:
        if self.docker_context:
            return ["docker", "--context", self.docker_context]
        return ["docker"]
    
    def _container_exists(self, container_name: str) -> bool:
        """Check if a container exists and is running."""
        try:
            result = subprocess.run(
                self._get_docker_cmd_prefix() + ["container", "inspect", container_name],
                capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _image_exists(self, image_name: str) -> bool:
        """Check if a Docker image exists locally or can be pulled."""
        try:
            result = subprocess.run(
                self._get_docker_cmd_prefix() + ["image", "inspect", image_name],
                capture_output=True, text=True
            )
            return result.returncode == 0
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
        
        logger.info(f"Creating reusable React Native container: {container_name}")
        
        # Pull the image if not available locally
        if not self._image_exists(self._image_to_use):
            logger.info(f"Pulling image {self._image_to_use}...")
            result = subprocess.run(
                self._get_docker_cmd_prefix() + ["pull", self._image_to_use],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                logger.error(f"Failed to pull {self._image_to_use}: {result.stderr}")
                return False
        
        logger.info(f"Using Docker image: {self._image_to_use}")
        
        try:
            # Create container with Node.js environment
            cmd = self._get_docker_cmd_prefix() + [
                "run", "-d",
                "--name", container_name,
                "-w", "/project",
                "--memory", "8g",
                "--cpus", "4",
                "-e", "CI=true",
                "-e", "NODE_OPTIONS=--max-old-space-size=4096",
                self._image_to_use,
                "tail", "-f", "/dev/null"  # Keep container running
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to create container: {result.stderr}")
                return False
            
            self._reusable_container_ready = True
            logger.info(f"Container {container_name} created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error creating container: {e}")
            return False
    
    def initialize_node_once(self) -> Tuple[bool, str]:
        """Initialize Node.js environment with nvm in the reusable container.
        
        Installs nvm and a default Node.js version. The actual version used
        will be determined per-project by detect_and_switch_node_version()
        which reads from package.json.
        """
        if self._node_initialized:
            return True, ""
        
        if not self._reusable_container_ready:
            if not self.ensure_reusable_container():
                return False, "Failed to create reusable container"
        
        logger.info("Initializing Node.js environment with nvm...")
        
        # Default version - will be switched per-project based on package.json
        default_version = "20"
        
        # Build initialization commands
        commands = [
            "git config --global --add safe.directory /project",
            # Install system dependencies:
            # - jq, curl: required by some React Native projects
            # - build-essential, python3: needed for native module compilation
            # - libcairo2-dev, libpango1.0-dev, libjpeg-dev, libgif-dev, librsvg2-dev: required by canvas/jsdom for Jest tests
            "apt-get update && apt-get install -y jq curl build-essential python3 libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev",
            # Install nvm if not present
            "export NVM_DIR=/root/.nvm && [ -s \"$NVM_DIR/nvm.sh\" ] || (curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash)",
            # Source nvm and install a default Node.js version
            f"export NVM_DIR=/root/.nvm && . \"$NVM_DIR/nvm.sh\" && nvm install {default_version} && nvm use {default_version} && nvm alias default {default_version}",
            # Create symlinks using explicit nvm paths
            f"""export NVM_DIR=/root/.nvm && . "$NVM_DIR/nvm.sh" && \
                rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx && \
                NVM_NODE_PATH=$(nvm which {default_version}) && \
                NVM_BIN_DIR=$(dirname $NVM_NODE_PATH) && \
                ln -sf $NVM_NODE_PATH /usr/local/bin/node && \
                ln -sf $NVM_BIN_DIR/npm /usr/local/bin/npm && \
                ln -sf $NVM_BIN_DIR/npx /usr/local/bin/npx && \
                echo "Symlinks created from $NVM_BIN_DIR"
            """,
            "node --version",
            "npm --version",
            # Install yarn and pnpm globally (common package managers for RN projects)
            "npm install -g yarn pnpm 2>&1 || true",
        ]
        
        all_output = []
        for cmd in commands:
            # Don't source nvm during initialization (it's being installed)
            exit_code, output = self._exec_in_reusable(cmd, timeout=300, source_nvm=False)
            all_output.append(f"$ {cmd}\n{output}")
            if exit_code != 0 and ("node --version" in cmd or "nvm install" in cmd):
                # Node/nvm installation failed, this is critical
                logger.error(f"Command failed: {cmd}\nOutput: {output}")
                return False, "\n".join(all_output)
        
        self._node_initialized = True
        self._current_node_version = default_version
        logger.info(f"Node.js environment initialized with nvm (default: Node {default_version})")
        return True, "\n".join(all_output)
    
    def _exec_in_reusable(self, command: str, workdir: str = "/project", 
                          timeout: int = 300, source_nvm: bool = True) -> Tuple[int, str]:
        """Execute a command in the reusable container.
        
        Args:
            command: The command to execute
            workdir: Working directory for the command
            timeout: Timeout in seconds
            source_nvm: Whether to source nvm before running the command (for Node.js access)
        """
        container_name = self.REUSABLE_CONTAINER_NAME
        
        # Add node_modules/.bin to PATH so local binaries (jest, etc.) are available
        # This is needed because npm scripts expect local binaries to be in PATH
        path_prefix = 'export PATH="./node_modules/.bin:$PATH" && '
        
        # Prepend nvm sourcing if needed and nvm is initialized
        if source_nvm and self._node_initialized:
            # Source nvm to ensure correct Node version is used
            nvm_prefix = 'export NVM_DIR=/root/.nvm && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && '
            command = nvm_prefix + path_prefix + command
        else:
            command = path_prefix + command
        
        try:
            cmd = self._get_docker_cmd_prefix() + [
                "exec", "-w", workdir, container_name,
                "bash", "-c", command
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode, result.stdout + result.stderr
            
        except subprocess.TimeoutExpired:
            return -1, f"Command timed out after {timeout}s: {command}"
        except Exception as e:
            return -1, f"Error executing command: {e}"
    
    def setup_repo_in_container(self, instance_id: str, repo_path: str) -> bool:
        """Copy repo files into the reusable container and setup for testing."""
        if not self._reusable_container_ready:
            if not self.ensure_reusable_container():
                return False
        
        logger.info(f"Setting up repo in container for {instance_id}...")
        
        try:
            container_name = self.REUSABLE_CONTAINER_NAME
            
            # Clear previous repo contents
            self._exec_in_reusable("rm -rf /project/* /project/.[!.]* 2>/dev/null || true")
            
            # Copy repo to container
            cmd = self._get_docker_cmd_prefix() + [
                "cp", f"{repo_path}/.", f"{container_name}:/project/"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"Failed to copy repo to container: {result.stderr}")
                return False
            
            # Track this instance as using the reusable container
            self.containers[instance_id] = {
                'name': container_name,
                'initialized': True,
                'using_reusable': True
            }
            
            self._current_repo_path = repo_path
            return True
            
        except Exception as e:
            logger.error(f"Error setting up repo: {e}")
            return False
    
    def prepare_repo_for_instance(self, instance_id: str, repo_path: str, 
                                   base_commit: str) -> bool:
        """Prepare repository for a specific instance in the reusable container.
        
        This copies the repo, resets to base commit, and cleans up any stale state.
        """
        # Copy repo files into container
        if not self.setup_repo_in_container(instance_id, repo_path):
            return False
        
        # Verify git repository was copied correctly
        exit_code, output = self._exec_in_reusable("git status 2>&1")
        if exit_code != 0:
            logger.error(f"Git repository not properly set up: {output}")
            return False
        
        # Check if the commit exists in the repository
        exit_code, output = self._exec_in_reusable(f"git cat-file -t {base_commit} 2>&1")
        if exit_code != 0:
            logger.error(f"Commit {base_commit} not found in repository. May need to fetch: {output}")
            # Try to fetch the commit
            logger.info(f"Attempting to fetch commit {base_commit}...")
            fetch_code, fetch_output = self._exec_in_reusable(f"git fetch origin {base_commit} 2>&1", timeout=120)
            if fetch_code != 0:
                logger.error(f"Failed to fetch commit: {fetch_output}")
                return False
        
        # Checkout the base commit
        logger.info(f"Checking out base commit: {base_commit}")
        exit_code, output = self._exec_in_reusable(f"git checkout {base_commit} 2>&1")
        if exit_code != 0:
            logger.error(f"Failed to checkout base commit: {output}")
            return False
        
        # Reset to clean state (in case there are any modifications)
        self._exec_in_reusable("git reset --hard HEAD")
        self._exec_in_reusable("git clean -fdx")
        
        return True
    
    def detect_package_manager(self, instance_id: str) -> str:
        """Detect which package manager to use (npm, yarn, pnpm)."""
        # Check for lock files in order of preference
        exit_code, _ = self._exec_in_reusable("test -f yarn.lock")
        if exit_code == 0:
            return "yarn"
        
        exit_code, _ = self._exec_in_reusable("test -f pnpm-lock.yaml")
        if exit_code == 0:
            return "pnpm"
        
        exit_code, _ = self._exec_in_reusable("test -f package-lock.json")
        if exit_code == 0:
            return "npm"
        
        # Default to npm if no lock file found
        return "npm"
    
    def detect_and_switch_node_version(self, instance_id: str, fallback_date: str = None) -> Tuple[bool, str, str]:
        """Detect required Node.js version from package.json and switch to it using nvm.
        
        Reads the 'engines.node' field from package.json to determine the required
        Node.js version. If not specified, falls back to date-based version selection.
        
        Args:
            instance_id: The instance ID for logging
            fallback_date: ISO date string to use for version selection if engines.node is not specified
            
        Returns:
            Tuple of (success, version_used, output)
        """
        # Try to read engines.node from package.json
        exit_code, output = self._exec_in_reusable(
            "cat package.json | grep -A5 '\"engines\"' | grep '\"node\"' | head -1",
            source_nvm=True
        )
        
        required_version = None
        
        if exit_code == 0 and output.strip():
            # Parse the node version requirement
            # Examples: "node": ">=18.0.0", "node": "20.x", "node": "^20.10.0", "node": "20.19.1"
            import re
            match = re.search(r'"node":\s*"([^"]+)"', output)
            if match:
                version_spec = match.group(1)
                logger.info(f"Found engines.node requirement: {version_spec}")
                
                # Check if it's an exact version (no range specifiers)
                # Exact version: 20.19.1, 18.0.0
                # Range specifiers: >=, <=, >, <, ^, ~, ||, x, *
                exact_version_match = re.match(r'^(\d+\.\d+\.\d+)$', version_spec.strip())
                if exact_version_match:
                    # Exact version specified - use it as-is
                    required_version = exact_version_match.group(1)
                    logger.info(f"Using exact Node version: {required_version}")
                else:
                    # Range specifier - need to pick an appropriate version
                    # For >= or > ranges, use the latest LTS that satisfies the range
                    # because dependencies in lock file often require newer Node than the minimum
                    
                    # Check for >= or > with a version
                    ge_match = re.match(r'^>=?\s*(\d+)', version_spec.strip())
                    if ge_match:
                        min_version = int(ge_match.group(1))
                        # For >= ranges, use Node 20 LTS (current stable) if minimum allows it
                        # This avoids issues where lock file deps need newer Node than minimum
                        if min_version <= 20:
                            required_version = "20"
                            logger.info(f"Using Node 20 LTS for '>={min_version}' range (satisfies minimum, works with modern deps)")
                        else:
                            # Minimum is higher than 20, use that version
                            required_version = str(min_version)
                            logger.info(f"Using minimum Node version from range: {required_version}")
                    else:
                        # Other range specifiers (^, ~, x) - extract major version
                        # ^20.10.0 -> 20, 20.x -> 20
                        version_match = re.search(r'(\d+)', version_spec)
                        if version_match:
                            required_version = version_match.group(1)
                            logger.info(f"Parsed major Node version from range: {required_version}")
        
        # Also check .nvmrc file if package.json doesn't specify
        if not required_version:
            exit_code, output = self._exec_in_reusable("cat .nvmrc 2>/dev/null", source_nvm=True)
            if exit_code == 0 and output.strip():
                # .nvmrc can contain version like "20", "v20.10.0", "lts/iron", etc.
                import re
                version_match = re.search(r'v?(\d+)', output.strip())
                if version_match:
                    required_version = version_match.group(1)
                    logger.info(f"Found Node version in .nvmrc: {required_version}")
        
        # Fall back to default version if not specified
        if not required_version:
            required_version = "20"  # Default to Node 20 LTS
            logger.info(f"No Node version specified in package.json or .nvmrc, using default: {required_version}")
        
        # Check if we need to switch versions
        if self._current_node_version == required_version:
            logger.info(f"Already using Node {required_version}, no switch needed")
            return True, required_version, ""
        
        logger.info(f"Switching Node.js version from {self._current_node_version} to {required_version}")
        
        # Use nvm to install and switch to the required version
        # We need to:
        # 1. Install the specific version with nvm
        # 2. Set it as default so it persists
        # 3. Remove old symlinks and create new ones pointing to nvm-managed binaries
        # 4. Verify the correct version is now active
        switch_cmd = f"""
            export NVM_DIR=/root/.nvm && . "$NVM_DIR/nvm.sh" && \
            nvm install {required_version} && \
            nvm use {required_version} && \
            nvm alias default {required_version} && \
            rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx && \
            NVM_NODE_PATH=$(nvm which {required_version}) && \
            NVM_BIN_DIR=$(dirname $NVM_NODE_PATH) && \
            ln -sf $NVM_NODE_PATH /usr/local/bin/node && \
            ln -sf $NVM_BIN_DIR/npm /usr/local/bin/npm && \
            ln -sf $NVM_BIN_DIR/npx /usr/local/bin/npx && \
            echo "Symlinks created from $NVM_BIN_DIR" && \
            /usr/local/bin/node --version && /usr/local/bin/npm --version
        """
        
        exit_code, output = self._exec_in_reusable(switch_cmd, timeout=120, source_nvm=False)
        
        if exit_code != 0:
            logger.error(f"Failed to switch Node version: {output}")
            # Try to continue with current version
            return False, self._current_node_version or "unknown", output
        
        self._current_node_version = required_version
        logger.info(f"Successfully switched to Node {required_version}")
        return True, required_version, output
    
    def run_install(self, instance_id: str, package_manager: str = None) -> Tuple[bool, str]:
        """Run package installation for the current repo.
        
        Runs full install (without --ignore-scripts) to ensure native modules
        like canvas are properly built. This is required for Jest tests that
        use jsdom.
        
        Uses --legacy-peer-deps for npm to handle peer dependency conflicts
        that are common in React Native projects.
        
        Returns:
            Tuple of (success, output)
        """
        if package_manager is None:
            package_manager = self.detect_package_manager(instance_id)
        
        logger.info(f"Running {package_manager} install...")
        
        if package_manager == "yarn":
            # Try frozen lockfile first, then regular install
            cmd = "yarn install --frozen-lockfile 2>&1 || yarn install 2>&1"
        elif package_manager == "pnpm":
            cmd = "pnpm install --frozen-lockfile 2>&1 || pnpm install 2>&1"
        else:
            # npm: use --legacy-peer-deps to handle peer dependency conflicts
            # Try npm ci first (faster, uses package-lock.json), fall back to npm install
            cmd = "npm ci --legacy-peer-deps 2>&1 || npm install --legacy-peer-deps 2>&1"
        
        exit_code, output = self._exec_in_reusable(cmd, timeout=600)
        
        # npm may return non-zero exit code for warnings, check if node_modules was created
        if exit_code != 0:
            # Check if node_modules exists and has content (install partially succeeded)
            check_code, check_output = self._exec_in_reusable("test -d node_modules && ls node_modules | head -5")
            if check_code == 0 and check_output.strip():
                logger.warning(f"npm install had warnings but node_modules exists, continuing...")
                return True, output
            
            logger.error(f"Package installation failed: {output[:500]}")
            return False, output
        
        return True, output
    
    def cleanup_repo(self, instance_id: str):
        """Clean up git state in container (but keep container running)."""
        if instance_id in self.containers and self.containers[instance_id].get('using_reusable'):
            self._exec_in_reusable("git reset --hard HEAD 2>/dev/null || true")
            self._exec_in_reusable("git clean -fdx 2>/dev/null || true")
    
    def exec_command(self, instance_id: str, command: str, 
                     workdir: str = "/project", timeout: int = 300) -> Tuple[int, str]:
        """Execute a command in the container."""
        if instance_id not in self.containers:
            return -1, "Container not found"
        
        # If using reusable container, delegate to reusable exec
        if self.containers[instance_id].get('using_reusable'):
            return self._exec_in_reusable(command, workdir, timeout)
        
        container_name = self.containers[instance_id]['name']
        
        try:
            cmd = self._get_docker_cmd_prefix() + [
                "exec", "-w", workdir, container_name,
                "bash", "-c", command
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode, result.stdout + result.stderr
            
        except subprocess.TimeoutExpired:
            return -1, f"Command timed out after {timeout}s"
        except Exception as e:
            return -1, f"Error: {e}"
    
    def get_versions(self, instance_id: str) -> Tuple[str, str, str]:
        """Get Node.js, npm, and React Native versions."""
        node_version = ""
        npm_version = ""
        rn_version = ""
        
        exit_code, output = self.exec_command(instance_id, "node --version")
        if exit_code == 0:
            node_version = output.strip()
        
        exit_code, output = self.exec_command(instance_id, "npm --version")
        if exit_code == 0:
            npm_version = output.strip()
        
        # Try to get React Native version from package.json
        exit_code, output = self.exec_command(
            instance_id, 
            "cat package.json | grep '\"react-native\"' | head -1"
        )
        if exit_code == 0 and output.strip():
            # Parse version from line like: "react-native": "0.72.0",
            match = re.search(r'"react-native":\s*"([^"]+)"', output)
            if match:
                rn_version = match.group(1)
        
        return node_version, npm_version, rn_version
    
    def _remove_container(self, container_name: str):
        """Remove a container if it exists."""
        try:
            subprocess.run(
                self._get_docker_cmd_prefix() + ["rm", "-f", container_name],
                capture_output=True, timeout=30
            )
        except Exception:
            pass
    
    def cleanup_container(self, instance_id: str):
        """Cleanup container for an instance."""
        if instance_id not in self.containers:
            return
        
        container_info = self.containers[instance_id]
        
        # If using reusable container, just clean up the repo state
        if container_info.get('using_reusable'):
            self.cleanup_repo(instance_id)
            del self.containers[instance_id]
            return
        
        # Legacy: remove per-instance container
        self._remove_container(container_info['name'])
        del self.containers[instance_id]
    
    def cleanup_all(self):
        """Cleanup all managed containers."""
        for instance_id in list(self.containers.keys()):
            self.cleanup_container(instance_id)
    
    def destroy_reusable_container(self):
        """Destroy the reusable container (call at end of batch processing)."""
        if self._reusable_container_ready:
            logger.info(f"Destroying reusable container: {self.REUSABLE_CONTAINER_NAME}")
            self._remove_container(self.REUSABLE_CONTAINER_NAME)
            self._reusable_container_ready = False
            self._node_initialized = False
            self._current_repo_path = None
            self._current_node_version = None


class ReactNativeTestRunner:
    """Runs React Native tests and parses results."""
    
    def __init__(self, container_manager: ReactNativeContainerManager):
        self.containers = container_manager
    
    def detect_test_framework(self, instance_id: str) -> str:
        """Detect which test framework is being used."""
        # Check package.json for test frameworks
        exit_code, output = self.containers.exec_command(
            instance_id, "cat package.json"
        )
        
        if exit_code != 0:
            return "jest"  # Default to Jest
        
        pkg = output.lower()
        
        if "vitest" in pkg:
            return "vitest"
        elif "mocha" in pkg:
            return "mocha"
        elif "jest" in pkg:
            return "jest"
        
        return "jest"  # Default
    
    def run_tests(self, instance_id: str, test_files: List[str] = None,
                  phase: str = "UNKNOWN", package_manager: str = "npm") -> ReactNativeTestExecutionResult:
        """Run tests using the appropriate test framework."""
        import time
        start_time = time.time()
        
        logger.info(f"=== STARTING {phase} REACT NATIVE TEST PHASE for {instance_id} ===")
        
        # Detect test framework
        framework = self.detect_test_framework(instance_id)
        
        # Node options needed for Jest with ES modules support
        # --experimental-vm-modules: Required for dynamic imports in Jest
        node_options = "NODE_OPTIONS='--experimental-vm-modules --max-old-space-size=4096'"
        
        # Build the test command using npx --no-install to run local binaries directly
        # This avoids PATH issues with npm run test spawning a shell without node_modules/.bin
        # npx --no-install ensures we use the locally installed binary (from npm ci)
        if test_files:
            test_paths = " ".join(test_files)
            if framework == "jest":
                # Use npx to run jest directly from node_modules/.bin
                # npx --no-install ensures we use the local binary, not download a new one
                command = f"{node_options} npx --no-install jest {test_paths} --json --outputFile=/tmp/test-results.json --passWithNoTests 2>&1"
            elif framework == "vitest":
                command = f"{node_options} npx --no-install vitest run {test_paths} 2>&1"
            else:
                command = f"{node_options} npx --no-install jest {test_paths} --passWithNoTests 2>&1"
        else:
            # Run all tests
            if framework == "jest":
                command = f"{node_options} npx --no-install jest --json --outputFile=/tmp/test-results.json --passWithNoTests 2>&1"
            elif framework == "vitest":
                command = f"{node_options} npx --no-install vitest run 2>&1"
            else:
                command = f"{node_options} npx --no-install jest --passWithNoTests 2>&1"
        
        logger.info(f"Running test command: {command}")
        
        exit_code, output = self.containers.exec_command(
            instance_id, command, timeout=900
        )
        
        # Log output for debugging
        if "not found" in output.lower() or "command not found" in output.lower():
            logger.error(f"Test runner not found. Output: {output[:500]}")
        
        duration = time.time() - start_time
        
        # Parse test results
        test_results = self._parse_test_output(instance_id, output, framework)
        
        # Calculate summary
        passed = sum(1 for t in test_results if t.status == 'PASSED')
        failed = sum(1 for t in test_results if t.status == 'FAILED')
        skipped = sum(1 for t in test_results if t.status == 'SKIPPED')
        errors = sum(1 for t in test_results if t.status == 'ERROR')
        
        result = ReactNativeTestExecutionResult(
            total_tests=len(test_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration=duration,
            exit_code=exit_code,
            raw_output=output,
            test_results=test_results,
            test_command=command
        )
        
        logger.info(f"[{instance_id}] {phase} tests: {passed} passed, {failed} failed, "
                   f"{skipped} skipped, {errors} errors (exit code: {exit_code})")
        
        return result
    
    def _parse_test_output(self, instance_id: str, output: str, 
                           framework: str = "jest") -> List[ReactNativeTestResult]:
        """Parse test output to extract individual test results."""
        test_results = []
        
        if framework == "jest":
            # Try to read JSON output first
            exit_code, json_output = self.containers.exec_command(
                instance_id, "cat /tmp/test-results.json 2>/dev/null"
            )
            
            if exit_code == 0 and json_output.strip():
                try:
                    return self._parse_jest_json(json_output)
                except Exception as e:
                    logger.debug(f"Failed to parse Jest JSON: {e}")
            
            # Fall back to text parsing
            return self._parse_jest_text(output)
        
        elif framework == "vitest":
            return self._parse_vitest_output(output)
        
        elif framework == "mocha":
            return self._parse_mocha_output(output)
        
        return test_results
    
    def _parse_jest_json(self, json_output: str) -> List[ReactNativeTestResult]:
        """Parse Jest JSON output."""
        results = []
        
        try:
            data = json.loads(json_output)
            
            for test_result in data.get('testResults', []):
                file_path = test_result.get('name', '')
                
                for assertion in test_result.get('assertionResults', []):
                    test_name = ' > '.join(assertion.get('ancestorTitles', []) + [assertion.get('title', '')])
                    status = assertion.get('status', 'failed').upper()
                    
                    # Map Jest status to our status
                    if status == 'PASSED':
                        status = 'PASSED'
                    elif status == 'PENDING':
                        status = 'SKIPPED'
                    else:
                        status = 'FAILED'
                    
                    failure_msg = ''
                    if assertion.get('failureMessages'):
                        failure_msg = '\n'.join(assertion['failureMessages'])
                    
                    results.append(ReactNativeTestResult(
                        test_name=test_name,
                        file_path=file_path,
                        status=status,
                        duration=assertion.get('duration', 0) / 1000.0,  # Convert ms to s
                        failure_message=failure_msg
                    ))
        
        except json.JSONDecodeError:
            logger.debug("Failed to parse Jest JSON output")
        
        return results
    
    def _parse_jest_text(self, output: str) -> List[ReactNativeTestResult]:
        """Parse Jest text output when JSON is not available."""
        results = []
        
        # Pattern for Jest test results
        # Examples:
        #   ✓ should render correctly (15 ms)
        #   ✕ should handle error case (23 ms)
        #   ○ skipped test name
        
        # Pattern for describe blocks to get context
        describe_pattern = re.compile(r'^\s*(describe|PASS|FAIL)\s+(.+)$', re.MULTILINE)
        
        # Pattern for individual tests
        test_patterns = [
            # Passed tests: ✓ test name (time ms)
            (re.compile(r'^\s*[✓✔]\s+(.+?)(?:\s+\((\d+)\s*m?s?\))?\s*$', re.MULTILINE), 'PASSED'),
            # Failed tests: ✕ test name (time ms)
            (re.compile(r'^\s*[✕✗×]\s+(.+?)(?:\s+\((\d+)\s*m?s?\))?\s*$', re.MULTILINE), 'FAILED'),
            # Skipped tests: ○ test name
            (re.compile(r'^\s*[○◌]\s+skipped\s+(.+)$', re.MULTILINE), 'SKIPPED'),
            (re.compile(r'^\s*[○◌]\s+(.+)$', re.MULTILINE), 'SKIPPED'),
        ]
        
        current_file = ""
        
        # Extract file context from PASS/FAIL lines
        file_pattern = re.compile(r'^\s*(PASS|FAIL)\s+(.+\.(?:js|jsx|ts|tsx))\s*$', re.MULTILINE)
        for match in file_pattern.finditer(output):
            current_file = match.group(2)
        
        for pattern, status in test_patterns:
            for match in pattern.finditer(output):
                test_name = match.group(1).strip()
                duration = 0.0
                if len(match.groups()) > 1 and match.group(2):
                    try:
                        duration = float(match.group(2)) / 1000.0
                    except ValueError:
                        pass
                
                # Skip if it looks like a file path or summary line
                if test_name.endswith('.js') or test_name.endswith('.ts'):
                    continue
                if 'Tests:' in test_name or 'Snapshots:' in test_name:
                    continue
                
                results.append(ReactNativeTestResult(
                    test_name=test_name,
                    file_path=current_file,
                    status=status,
                    duration=duration
                ))
        
        return results
    
    def _parse_vitest_output(self, output: str) -> List[ReactNativeTestResult]:
        """Parse Vitest output."""
        results = []
        
        # Vitest patterns similar to Jest
        test_patterns = [
            (re.compile(r'^\s*[✓✔]\s+(.+?)(?:\s+(\d+)ms)?\s*$', re.MULTILINE), 'PASSED'),
            (re.compile(r'^\s*[×✗]\s+(.+?)(?:\s+(\d+)ms)?\s*$', re.MULTILINE), 'FAILED'),
            (re.compile(r'^\s*[-]\s+(.+?)\s+\[skipped\]', re.MULTILINE), 'SKIPPED'),
        ]
        
        for pattern, status in test_patterns:
            for match in pattern.finditer(output):
                test_name = match.group(1).strip()
                duration = 0.0
                if len(match.groups()) > 1 and match.group(2):
                    try:
                        duration = float(match.group(2)) / 1000.0
                    except ValueError:
                        pass
                
                results.append(ReactNativeTestResult(
                    test_name=test_name,
                    file_path="",
                    status=status,
                    duration=duration
                ))
        
        return results
    
    def _parse_mocha_output(self, output: str) -> List[ReactNativeTestResult]:
        """Parse Mocha output."""
        results = []
        
        # Mocha patterns
        # ✓ test name
        # 1) test name (for failed)
        
        pass_pattern = re.compile(r'^\s*[✓✔]\s+(.+?)(?:\s+\((\d+)ms\))?\s*$', re.MULTILINE)
        fail_pattern = re.compile(r'^\s*\d+\)\s+(.+)$', re.MULTILINE)
        
        for match in pass_pattern.finditer(output):
            test_name = match.group(1).strip()
            duration = 0.0
            if match.group(2):
                try:
                    duration = float(match.group(2)) / 1000.0
                except ValueError:
                    pass
            
            results.append(ReactNativeTestResult(
                test_name=test_name,
                file_path="",
                status='PASSED',
                duration=duration
            ))
        
        for match in fail_pattern.finditer(output):
            test_name = match.group(1).strip()
            results.append(ReactNativeTestResult(
                test_name=test_name,
                file_path="",
                status='FAILED'
            ))
        
        return results


class ReactNativeConfigParser:
    """Parses React Native project configuration."""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
    
    def parse_package_json(self) -> Dict[str, Any]:
        """Parse package.json file."""
        pkg_path = self.project_path / "package.json"
        if not pkg_path.exists():
            return {}
        
        try:
            with open(pkg_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error parsing package.json: {e}")
            return {}
    
    def get_package_manager(self) -> str:
        """Detect package manager from lock files."""
        if (self.project_path / "yarn.lock").exists():
            return "yarn"
        elif (self.project_path / "pnpm-lock.yaml").exists():
            return "pnpm"
        return "npm"
    
    def extract_test_files_from_patch(self, test_patch: str) -> List[str]:
        """Extract test file paths from a patch."""
        if not test_patch:
            return []
        
        test_files = []
        
        # Pattern to match file paths in diff headers for various test file naming conventions
        # Common patterns:
        # - *.test.js, *.test.ts, *.test.jsx, *.test.tsx
        # - *.spec.js, *.spec.ts, *.spec.jsx, *.spec.tsx
        # - __tests__/*.js, __tests__/*.ts (Jest convention)
        # - tests/*.js, tests/*.ts (common convention)
        # - test/*.js, test/*.ts
        
        # Match any file in diff headers
        file_pattern = re.compile(r'diff --git a/(.+?) b/')
        
        for match in file_pattern.finditer(test_patch):
            file_path = match.group(1)
            
            # Skip if already added
            if file_path in test_files:
                continue
            
            # Skip snapshot files - these are Jest artifacts, not runnable tests
            # Snapshot files have .snap extension (e.g., Component.test.js.snap)
            if file_path.endswith('.snap'):
                continue
            
            # Skip non-JavaScript/TypeScript files
            if not re.search(r'\.(js|jsx|ts|tsx)$', file_path):
                continue
            
            # Skip e2e/integration tests - these require device/emulator and can't run with Jest
            # Common e2e directories: e2e/, __e2e__/, integration/, detox/
            if '/e2e/' in file_path or file_path.startswith('e2e/'):
                continue
            if '/__e2e__/' in file_path or file_path.startswith('__e2e__/'):
                continue
            if '/integration/' in file_path or file_path.startswith('integration/'):
                continue
            if '/detox/' in file_path or file_path.startswith('detox/'):
                continue
            
            # Check if it's a test file using various patterns
            is_test_file = False
            
            # Pattern 1: Files ending with .test.* or .spec.*
            if re.search(r'\.(test|spec)\.(js|jsx|ts|tsx)$', file_path):
                is_test_file = True
            
            # Pattern 2: Files in __tests__ directory (but not __snapshots__ subdirectory)
            elif ('/__tests__/' in file_path or file_path.startswith('__tests__/')) and '/__snapshots__/' not in file_path:
                is_test_file = True
            
            # Pattern 3: Files in tests/ or test/ directory (common for JS projects)
            elif '/tests/' in file_path or file_path.startswith('tests/'):
                is_test_file = True
            elif '/test/' in file_path or file_path.startswith('test/'):
                is_test_file = True
            
            # Pattern 4: Files with Test or Spec in the name (e.g., IOUTest.ts)
            elif re.search(r'(Test|Spec)\.(js|jsx|ts|tsx)$', file_path):
                is_test_file = True
            
            if is_test_file:
                test_files.append(file_path)
        
        return test_files
    
    def is_react_native_project(self) -> bool:
        """Check if this is a React Native project."""
        pkg = self.parse_package_json()
        if not pkg:
            return False
        
        deps = pkg.get('dependencies', {})
        dev_deps = pkg.get('devDependencies', {})
        all_deps = {**deps, **dev_deps}
        
        return 'react-native' in all_deps or 'expo' in all_deps


class ReactNativeValidator:
    """Main React Native validation engine."""
    
    def __init__(self, output_dir: str = "react_native_validation_results",
                 docker_context: str = None,
                 reuse_container: bool = True):
        """
        Initialize the React Native validator.
        
        Args:
            output_dir: Directory to save validation results
            docker_context: Docker context to use (optional)
            reuse_container: Whether to reuse container between instances
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.containers = ReactNativeContainerManager(docker_context, reuse_container)
        self.test_runner = ReactNativeTestRunner(self.containers)
        self.reuse_container = reuse_container
    
    def validate_instance(self, instance: Dict[str, Any]) -> ReactNativeValidationResult:
        """Validate a single React Native instance."""
        import time
        start_time = time.time()
        
        instance_id = instance.get('instance_id', 'unknown')
        repo = instance.get('repo', '')
        base_commit = instance.get('base_commit', '')
        
        logger.info(f"{'='*60}")
        logger.info(f"Validating React Native instance: {instance_id}")
        logger.info(f"{'='*60}")
        
        result = ReactNativeValidationResult(
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
            
            # 2. Check if it's a React Native project
            config_parser = ReactNativeConfigParser(repo_path)
            if not config_parser.is_react_native_project():
                result.error_message = "Not a React Native project"
                return result
            
            # 3. Detect package manager
            package_manager = config_parser.get_package_manager()
            result.package_manager = package_manager
            
            # 4. Get or create reusable container (one-time)
            if not self.containers.ensure_reusable_container():
                result.error_message = "Failed to create/get reusable container"
                return result
            
            # 5. Initialize Node.js environment with nvm
            if not self.containers._node_initialized:
                init_success, init_output = self.containers.initialize_node_once()
                result.init_output = init_output
                
                if not init_success:
                    result.error_message = "Failed to initialize Node.js environment"
                    return result
            
            # 6. Prepare repo for this instance (copy, reset, checkout)
            if not self.containers.prepare_repo_for_instance(instance_id, repo_path, base_commit):
                result.error_message = "Failed to prepare repository in container"
                return result
            
            # 7. Detect and switch to the correct Node.js version from package.json
            node_switch_success, detected_version, node_switch_output = \
                self.containers.detect_and_switch_node_version(instance_id)
            if node_switch_success:
                logger.info(f"Switched to Node.js {detected_version} based on package.json")
                result.node_version = detected_version
            else:
                logger.warning(f"Could not switch Node.js version: {node_switch_output[:200] if node_switch_output else 'unknown error'}")
                # Continue anyway - the default version may work
            
            # 8. Run package installation
            install_success, install_output = self.containers.run_install(instance_id, package_manager)
            if not install_success:
                result.error_message = f"Failed to install dependencies: {install_output[:200]}"
                return result
            
            # Get versions
            result.node_version, result.npm_version, result.react_native_version = \
                self.containers.get_versions(instance_id)
            
            # 9. Extract test files from patch
            test_patch = instance.get('test_patch', '')
            test_files = config_parser.extract_test_files_from_patch(test_patch)
            
            if not test_files:
                logger.warning(f"No test files found in patch for {instance_id}, skipping instance")
                logger.debug(f"test_patch content (first 200 chars): {test_patch[:200] if test_patch else 'EMPTY'}")
                result.error_message = "No test files found in patch - skipping instance"
                return result
            else:
                logger.info(f"Found {len(test_files)} test file(s): {test_files}")
            
            # 10. Apply test patch and run PRE-solution tests
            if not self._apply_patch(instance_id, test_patch, "test"):
                result.error_message = "Failed to apply test patch"
                return result
            
            result.pre_solution_tests = self.test_runner.run_tests(
                instance_id, test_files if test_files else None, 
                phase="PRE-SOLUTION", package_manager=package_manager
            )
            
            # 11. Apply solution patch
            solution_patch = instance.get('patch', '')
            if not self._apply_patch(instance_id, solution_patch, "solution"):
                result.error_message = "Failed to apply solution patch"
                return result
            
            # 12. Run POST-solution tests
            result.post_solution_tests = self.test_runner.run_tests(
                instance_id, test_files if test_files else None, 
                phase="POST-SOLUTION", package_manager=package_manager
            )
            
            # 13. Analyze test transitions
            self._analyze_test_transitions(result)
            
            # 14. Determine success
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
            temp_dir = tempfile.mkdtemp(prefix="react-native-bench-")
            
            # Clone repository
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
        # This avoids "Argument list too long" error for large patches
        patch_file = f"/tmp/{patch_type}_patch.diff"
        local_patch_file = None
        
        try:
            # Write patch to local temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False) as f:
                f.write(patch)
                local_patch_file = f.name
            
            # Copy patch file to container
            container_name = self.containers.REUSABLE_CONTAINER_NAME
            cmd = self.containers._get_docker_cmd_prefix() + [
                "cp", local_patch_file, f"{container_name}:{patch_file}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                logger.error(f"Failed to copy patch file to container: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to write/copy patch file: {e}")
            return False
        finally:
            # Clean up local temp file
            if local_patch_file and os.path.exists(local_patch_file):
                os.unlink(local_patch_file)
        
        # Try multiple patch application strategies
        patch_applied = False
        
        # Strategy 1: Standard git apply
        exit_code, output = self.containers.exec_command(
            instance_id,
            f"git apply --verbose {patch_file} 2>&1"
        )
        if exit_code == 0:
            patch_applied = True
        
        # Strategy 2: Try with 3-way merge (can resolve some conflicts)
        if not patch_applied:
            logger.info(f"Standard apply failed, trying 3-way merge...")
            exit_code, output = self.containers.exec_command(
                instance_id,
                f"git apply --verbose --3way {patch_file} 2>&1"
            )
            if exit_code == 0:
                patch_applied = True
        
        # Strategy 3: Try excluding lock files (they get regenerated anyway)
        if not patch_applied:
            logger.info(f"3-way merge failed, trying without lock files...")
            exit_code, output = self.containers.exec_command(
                instance_id,
                f"git apply --verbose --exclude='*lock.json' --exclude='*lock.yaml' --exclude='*.lock' {patch_file} 2>&1"
            )
            if exit_code == 0:
                patch_applied = True
                logger.info("Applied patch excluding lock files")
        
        # Strategy 4: Use --reject to apply what we can
        if not patch_applied:
            logger.info(f"Trying with --reject to apply partial changes...")
            exit_code, output = self.containers.exec_command(
                instance_id,
                f"git apply --verbose --reject --whitespace=fix {patch_file} 2>&1"
            )
            # Check if any files were patched (even with rejects)
            if "Applied patch" in output or "patching file" in output.lower():
                logger.warning(f"Patch applied with some rejections - check .rej files")
                patch_applied = True
        
        if not patch_applied:
            logger.error(f"Failed to apply {patch_type} patch: {output}")
            return False
        
        logger.info(f"Applied {patch_type} patch successfully")
        
        # Run package install after applying patch (in case dependencies changed)
        package_manager = self.containers.detect_package_manager(instance_id)
        if package_manager == "yarn":
            self.containers.exec_command(instance_id, "yarn install 2>&1")
        elif package_manager == "pnpm":
            self.containers.exec_command(instance_id, "pnpm install 2>&1")
        else:
            self.containers.exec_command(instance_id, "npm install 2>&1")
        
        return True
    
    def _analyze_test_transitions(self, result: ReactNativeValidationResult):
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
    
    def _determine_success(self, result: ReactNativeValidationResult) -> bool:
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
    
    def _save_result(self, result: ReactNativeValidationResult):
        """Save validation result to disk."""
        instance_dir = self.output_dir / result.instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        
        # Save result JSON
        result_file = instance_dir / "validation_result.json"
        with open(result_file, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        
        # Save initialization logs
        if result.init_output:
            init_log = instance_dir / "node_init.log"
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
                         max_instances: int = None) -> Dict[str, ReactNativeValidationResult]:
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
        
        # Sort by created_at date to potentially minimize environment switches
        instances.sort(key=lambda x: x.get('created_at', '')[:7])  # Sort by YYYY-MM
        
        logger.info(f"Validating {len(instances)} React Native instances")
        
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
    
    def _save_summary(self, results: Dict[str, ReactNativeValidationResult]):
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
    
    parser = argparse.ArgumentParser(description="React Native Validation Engine")
    parser.add_argument("dataset_file", help="Path to dataset JSONL file")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to validate")
    parser.add_argument("--exclude-instances", nargs="+", help="Instance IDs to exclude")
    parser.add_argument("--skip-existing", action="store_true", 
                        help="Skip instances that already have results in output dir")
    parser.add_argument("--max-instances", type=int, help="Maximum instances to validate")
    parser.add_argument("--output-dir", default="react_native_validation_results", help="Output directory")
    parser.add_argument("--docker-context", help="Docker context to use")
    parser.add_argument("--no-reuse", action="store_true", 
                        help="Don't reuse container between instances (slower but more isolated)")
    
    args = parser.parse_args()
    
    validator = ReactNativeValidator(
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
    print(f"React Native Validation Complete")
    print(f"{'='*60}")
    print(f"Total: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(results) - successful}")
    print(f"Results saved to: {args.output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
