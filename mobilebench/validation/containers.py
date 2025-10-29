#!/usr/bin/env python3
"""
Clean persistent Docker container management for Android builds.
Fixed version with proper error handling and simplified logic.
"""

import subprocess
import logging
import os
import time
from typing import Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidContainersPersistent:
    """Manages persistent Docker containers with caching for Android builds."""
    
    BASE_IMAGE = "mingc/android-build-box:latest"
    
    def __init__(self, docker_context: str = None):
        self.containers = {}  # instance_id -> container_info
        self.docker_context = docker_context
        self._ensure_base_image()
        
    def _get_docker_cmd_prefix(self):
        """Get Docker command prefix with context if specified."""
        if self.docker_context:
            return ["docker", "--context", self.docker_context]
        else:
            return ["docker"]
    
    def _ensure_base_image(self):
        """Ensure the base image is available locally."""
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            
            # Check if Docker is running
            result = subprocess.run(
                docker_cmd + ["info"],
                capture_output=True,
                timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError("Docker is not running or not accessible")
            
            # Check if image exists locally
            result = subprocess.run(
                docker_cmd + ["images", "-q", self.BASE_IMAGE],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f"Base image {self.BASE_IMAGE} found locally")
                return
            
            # Pull the image
            logger.info(f"Pulling base image {self.BASE_IMAGE}...")
            result = subprocess.run(
                docker_cmd + ["pull", self.BASE_IMAGE],
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                logger.info("Base image pulled successfully")
            else:
                raise RuntimeError(f"Failed to pull image: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker command timed out")
        except Exception as e:
            raise RuntimeError(f"Error ensuring Docker image: {e}")
    
    def create_container(self, instance_id: str, config: Dict[str, str], 
                        repo_path: str, mount_repo: bool = False) -> bool:
        """Create persistent container for the instance."""
        
        logger.info(f"Creating persistent container for {instance_id}")
        
        container_name = f"android-bench-{instance_id.replace('_', '-').replace('__', '-').lower()}"
        
        # Check if container already exists and is usable
        if self._container_exists(container_name):
            logger.info(f"Container {container_name} already exists, checking if usable")
            if self._is_container_usable(container_name):
                logger.info(f"Reusing existing container {container_name}")
                self.containers[instance_id] = {
                    'config': config,
                    'repo_path': os.path.abspath(repo_path) if mount_repo else None,
                    'name': container_name,
                    'persistent': True,
                    'mount_repo': mount_repo
                }
                return True
            else:
                logger.info(f"Existing container {container_name} not usable, removing it")
                self._remove_container(container_name)
        
        # Create new persistent container
        return self._create_new_container(instance_id, config, repo_path, container_name, mount_repo)
    
    def _container_exists(self, container_name: str) -> bool:
        """Check if container exists (running or stopped)."""
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            result = subprocess.run(
                docker_cmd + ["ps", "-a", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return bool(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Error checking if container exists: {e}")
            return False
    
    def _is_container_usable(self, container_name: str) -> bool:
        """Check if existing container is in a usable state."""
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            
            # Check container status
            result = subprocess.run(
                docker_cmd + ["ps", "-a", "-f", f"name=^{container_name}$", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                return False
                
            status = result.stdout.strip().lower()
            
            # Container should be either running or exited cleanly
            return "up" in status or "exited (0)" in status
            
        except Exception as e:
            logger.warning(f"Error checking container status: {e}")
            return False
    
    def _remove_container(self, container_name: str):
        """Remove existing container."""
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            
            # Stop if running
            subprocess.run(
                docker_cmd + ["stop", container_name],
                capture_output=True,
                timeout=30
            )
            
            # Remove container
            subprocess.run(
                docker_cmd + ["rm", container_name],
                capture_output=True,
                timeout=30
            )
            
            logger.info(f"Removed existing container {container_name}")
            
        except Exception as e:
            logger.warning(f"Error removing container {container_name}: {e}")
    
    def _create_new_container(self, instance_id: str, config: Dict[str, str], 
                             repo_path: str, container_name: str, mount_repo: bool = False) -> bool:
        """Create a new persistent container."""
        
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            
            # Build environment variables
            env_vars = self._build_environment_vars(config)
            
            # Create persistent container with volume mounts for caching
            create_cmd = docker_cmd + [
                "create",
                "--name", container_name,
                "--network", "host",
                "-w", "/workspace",
                # Persistent volumes for caching
                "-v", f"gradle-cache-{instance_id}:/tmp/.gradle",
                "-v", f"android-cache-{instance_id}:/root/.android",
                # Environment setup
                "-e", f"HOME=/tmp",
                "-e", f"GRADLE_USER_HOME=/tmp/.gradle",
                "--user", "root"
            ]
            
            # Add repository mount only if mount_repo is True
            if mount_repo:
                create_cmd.extend(["-v", f"{os.path.abspath(repo_path)}:/workspace"])
                logger.info(f"Mounting repository from {repo_path} to /workspace")
            else:
                logger.info("Creating container without repository mount - will copy files later")
            
            # Add environment variables
            for key, value in env_vars.items():
                create_cmd.extend(["-e", f"{key}={value}"])
            
            # Add image and keep-alive command
            create_cmd.extend([self.BASE_IMAGE, "tail", "-f", "/dev/null"])
            
            result = subprocess.run(create_cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                logger.info(f"Created persistent container: {container_name}")
                self.containers[instance_id] = {
                    'config': config,
                    'repo_path': os.path.abspath(repo_path) if mount_repo else None,
                    'name': container_name,
                    'persistent': True,
                    'mount_repo': mount_repo
                }
                return True
            else:
                logger.error(f"Failed to create container: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Container creation timed out for {instance_id}")
            return False
        except Exception as e:
            logger.error(f"Error creating container: {e}")
            return False
    
    def start_container(self, instance_id: str) -> bool:
        """Start persistent container and initialize if needed."""
        if instance_id not in self.containers:
            raise ValueError(f"Container not found for instance: {instance_id}")
        
        container_name = self.containers[instance_id]['name']
        
        try:
            # Start container if not running
            if not self._is_container_running(container_name):
                logger.info(f"Starting container {container_name}")
                docker_cmd = self._get_docker_cmd_prefix()
                result = subprocess.run(
                    docker_cmd + ["start", container_name],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode != 0:
                    logger.error(f"Failed to start container: {result.stderr}")
                    return False
                
                # Wait a moment for container to be ready
                time.sleep(2)
            
            # Initialize container if this is the first time
            if not self._is_container_initialized(instance_id):
                logger.info(f"Initializing container {container_name}")
                return self._initialize_container(instance_id)
            
            logger.info(f"Container {container_name} is ready")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start container for {instance_id}: {e}")
            return False
    
    def _is_container_running(self, container_name: str) -> bool:
        """Check if container is currently running."""
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            result = subprocess.run(
                docker_cmd + ["ps", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return bool(result.stdout.strip())
        except Exception:
            return False
    
    def _is_container_initialized(self, instance_id: str) -> bool:
        """Check if container has been initialized."""
        try:
            exit_code, output = self.exec_command(
                instance_id, 
                "test -f /tmp/.container_initialized",
                timeout=10
            )
            return exit_code == 0
        except Exception:
            return False
    
    def _initialize_container(self, instance_id: str) -> bool:
        """Initialize container with dependencies and setup."""
        
        config = self.containers[instance_id]['config']
        java_version = config.get('java_version', '17')
        compile_sdk = config.get('compile_sdk', '35')
        build_tools = config.get('build_tools', '35.0.0')
        
        # Simple, robust initialization command
        init_command = f"""
echo "=== Initializing persistent container ===" &&

# Git configuration
git config --global --add safe.directory /workspace &&
git config --global --add safe.directory '*' &&
git config --global user.email 'validator@android-bench.local' &&
git config --global user.name 'Android Bench Validator' &&

# Java setup
export JAVA_HOME=/usr/lib/jvm/java-{java_version}-openjdk-amd64 &&
export PATH="$JAVA_HOME/bin:$PATH" &&
echo "Java version: $(java -version 2>&1 | head -1)" &&

# Android SDK setup
export ANDROID_HOME='/opt/android-sdk' &&
export ANDROID_SDK_ROOT='/opt/android-sdk' &&

# Accept SDK licenses
yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses 2>/dev/null || true &&

# Install essential SDK components
echo "=== Installing SDK components ===" &&
$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
    "platforms;android-{compile_sdk}" \
    "build-tools;{build_tools}" \
    "platform-tools" \
    "cmdline-tools;latest" 2>/dev/null || echo "SDK installation completed" &&

# Setup Gradle configuration
mkdir -p /tmp/.gradle &&
cat > /tmp/.gradle/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m -XX:+UseG1GC
org.gradle.caching=true
android.enableJetifier=true
android.useAndroidX=true
EOF

# Mark as initialized
touch /tmp/.container_initialized &&
echo "Container initialization completed successfully"
"""
        
        try:
            # Execute initialization with extended timeout
            exit_code, output = self.exec_command(
                instance_id, 
                init_command,
                timeout=1800  # 30 minutes for initialization
            )
            
            if exit_code == 0:
                logger.info(f"Container {instance_id} initialized successfully")
                return True
            else:
                logger.error(f"Container initialization failed: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing container {instance_id}: {e}")
            return False
    
    def exec_command(self, instance_id: str, command: str, 
                    workdir: str = "/workspace", timeout: int = 600) -> Tuple[int, str]:
        """Execute command in persistent container."""
        if instance_id not in self.containers:
            raise ValueError(f"Container not found for instance: {instance_id}")
        
        container_name = self.containers[instance_id]['name']
        config = self.containers[instance_id]['config']
        java_version = config.get('java_version', '17')
        
        # Simple wrapper with essential environment
        wrapped_command = f"""
export JAVA_HOME=/usr/lib/jvm/java-{java_version}-openjdk-amd64
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_ROOT='/opt/android-sdk'
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
export PATH="$JAVA_HOME/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH"

# Ensure git is configured
git config --global --add safe.directory /workspace 2>/dev/null || true

cd {workdir}
{command}
"""
        
        # Build Docker exec command
        docker_cmd = self._get_docker_cmd_prefix() + [
            "exec",
            "-w", workdir,
            container_name,
            "bash", "-c", wrapped_command
        ]
        
        try:
            logger.debug(f"Executing command in persistent container {container_name}")
            
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            output = result.stdout + result.stderr
            
            logger.debug(f"Command exit code: {result.returncode}")
            if result.returncode != 0:
                logger.debug(f"Command output: {output[:500]}...")
            
            return result.returncode, output
            
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out in container {container_name}")
            return 124, f"Command timed out after {timeout} seconds"
        except Exception as e:
            logger.error(f"Failed to execute command in {container_name}: {e}")
            return 1, str(e)
    
    def _build_environment_vars(self, config: Dict[str, str]) -> Dict[str, str]:
        """Build environment variables based on configuration."""
        java_version = config.get('java_version', '17')
        
        env_vars = {
            'JAVA_VERSION': java_version,
            'JAVA_HOME': f'/usr/lib/jvm/java-{java_version}-openjdk-amd64',
            'ANDROID_HOME': '/opt/android-sdk',
            'ANDROID_SDK_ROOT': '/opt/android-sdk',
            'ANDROID_SDK_HOME': '/opt/android-sdk',
            'GRADLE_OPTS': config.get('jvm_args', '-Xmx4096m'),
            'PATH': f'/usr/lib/jvm/java-{java_version}-openjdk-amd64/bin:/opt/gradle/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/tools/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        }
        
        # Add NDK configuration if specified
        if config.get('ndk_version'):
            env_vars.update({
                'NDK_VERSION': config['ndk_version'],
                'ANDROID_NDK_HOME': f"/opt/android-sdk/ndk/{config['ndk_version']}",
                'ANDROID_NDK_ROOT': f"/opt/android-sdk/ndk/{config['ndk_version']}"
            })
        
        return env_vars
    
    def install_sdk_components(self, instance_id: str, config: Dict[str, str]):
        """Install SDK components (handled during initialization for persistent containers)."""
        if self._is_container_initialized(instance_id):
            logger.info(f"Container {instance_id} already initialized, SDK components already installed")
            return
        
        logger.info(f"SDK components will be installed during container initialization for {instance_id}")
    
    def prepare_for_test_execution(self, instance_id: str, phase: str = "pre", workdir: str = "/workspace", preserve_build_artifacts: bool = False) -> bool:
        """Prepare container for test execution phase."""
        logger.info(f"Preparing container for {phase}-test execution in {workdir}: {instance_id}")
        
        if preserve_build_artifacts:
            # Skip build cleanup for debugging
            cleanup_command = f"""
echo "=== Preparing for test execution (preserving build artifacts) in {workdir} ===" &&
cd {workdir} &&

# Skip build artifact cleanup for debugging
echo "Preserving build artifacts for debugging" &&

# Stop any running Gradle daemons to prevent workspace interference
./gradlew --stop 2>/dev/null || true &&

# Ensure proper permissions
chmod +x ./gradlew 2>/dev/null || true &&

echo "Container prepared for test execution in {workdir}"
"""
        else:
            # Clean build artifacts for isolation between phases
            cleanup_command = f"""
echo "=== Preparing for test execution in {workdir} ===" &&
cd {workdir} &&

# Clean build artifacts for proper isolation between pre/post phases
rm -rf build/ app/build/ */build/ .gradle/daemon/ || true &&
echo "Cleaned build artifacts from {workdir}" &&

# Stop any running Gradle daemons to prevent workspace interference
./gradlew --stop 2>/dev/null || true &&

# Ensure proper permissions
chmod +x ./gradlew 2>/dev/null || true &&

echo "Container prepared for test execution in {workdir}"
"""
        
        try:
            exit_code, output = self.exec_command(
                instance_id,
                cleanup_command,
                workdir=workdir,
                timeout=120
            )
            
            if exit_code == 0:
                logger.info(f"Container prepared for {phase}-test execution")
                return True
            else:
                logger.warning(f"Container preparation had issues: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error preparing container for {instance_id}: {e}")
            return False
    
    def copy_to_container(self, instance_id: str, host_path: str, container_path: str) -> bool:
        """Copy file or directory from host to container."""
        if instance_id not in self.containers:
            raise ValueError(f"Container not found for instance: {instance_id}")
        
        container_name = self.containers[instance_id]['name']
        
        try:
            logger.info(f"Copying {host_path} to {container_name}:{container_path}")
            
            # Check if host_path is a file or directory
            if os.path.isfile(host_path):
                # Copy single file
                docker_cmd = self._get_docker_cmd_prefix() + [
                    "cp", host_path, f"{container_name}:{container_path}"
                ]
            else:
                # Copy directory contents 
                docker_cmd = self._get_docker_cmd_prefix() + [
                    "cp", f"{host_path}/.", f"{container_name}:{container_path}"
                ]
            
            result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                logger.info(f"Successfully copied to container")
                
                # Set proper permissions inside container
                perm_command = f"chmod -R 755 {container_path}"
                self.exec_command(instance_id, perm_command, workdir="/", timeout=60)
                
                # If copying workspace, ensure Gradle wrapper is executable
                if "workspace" in container_path.lower():
                    gradle_setup = f"""
cd {container_path} &&
if [ -f gradlew ]; then
    chmod +x gradlew &&
    echo 'Made gradlew executable'
fi &&
if [ -f gradle/wrapper/gradle-wrapper.jar ]; then
    echo 'Gradle wrapper JAR found'
else
    echo 'WARNING: gradle-wrapper.jar not found!'
fi
"""
                    self.exec_command(instance_id, gradle_setup, workdir="/", timeout=60)
                
                return True
            else:
                logger.error(f"Failed to copy to container: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error copying to container {instance_id}: {e}")
            return False
    
    def cleanup_container(self, instance_id: str, keep_persistent: bool = True, preserve_for_debug: bool = False):
        """Cleanup container."""
        if instance_id not in self.containers:
            return
        
        container_name = self.containers[instance_id]['name']
        
        if keep_persistent and self.containers[instance_id].get('persistent', False):
            if preserve_for_debug:
                logger.info(f"Keeping persistent container {container_name} for debugging - preserving all workspace state")
                # Don't clean anything when preserving for debug
                logger.info("Preserving both /workspace and /workspace_post for manual debugging")
            else: # MARKER
                logger.info(f"Keeping persistent container {container_name} for potential reuse")
                # Just clean build artifacts
                try:
                    # self.exec_command(
                    #     instance_id,
                    #     "cd /workspace && rm -rf build/ app/build/ */build/ .gradle/daemon/ || true",
                    #     timeout=60
                    # )
                    pass
                except Exception as e:
                    logger.warning(f"Error cleaning build artifacts: {e}")
        else:
            # Fully remove container
            logger.info(f"Removing container {container_name}")
            self._remove_container(container_name)
        
        # Remove from tracking
        if instance_id in self.containers:
            del self.containers[instance_id]
    
    def cleanup_all(self, keep_persistent: bool = False):
        """Cleanup all containers."""
        instance_ids = list(self.containers.keys())
        
        for instance_id in instance_ids:
            try:
                self.cleanup_container(instance_id, keep_persistent=keep_persistent)
            except Exception as e:
                logger.error(f"Failed to cleanup container {instance_id}: {e}")
        
        if not keep_persistent:
            # Also cleanup any orphaned containers and volumes
            self._cleanup_orphaned_resources()
        
        logger.info("Container cleanup completed")
    
    def _cleanup_orphaned_resources(self):
        """Clean up orphaned containers and volumes."""
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            
            # Remove orphaned containers
            result = subprocess.run(
                docker_cmd + ["ps", "-a", "-q", "-f", "name=android-bench-"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.stdout.strip():
                container_ids = result.stdout.strip().split('\n')
                subprocess.run(
                    docker_cmd + ["rm", "-f"] + container_ids,
                    capture_output=True,
                    timeout=60
                )
                logger.info(f"Removed {len(container_ids)} orphaned containers")
            
            # Remove orphaned volumes
            for volume_prefix in ["gradle-cache-", "android-cache-"]:
                result = subprocess.run(
                    docker_cmd + ["volume", "ls", "-q", "-f", f"name={volume_prefix}"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.stdout.strip():
                    volume_names = result.stdout.strip().split('\n')
                    subprocess.run(
                        docker_cmd + ["volume", "rm"] + volume_names,
                        capture_output=True,
                        timeout=60
                    )
                    logger.info(f"Removed {len(volume_names)} orphaned volumes with prefix {volume_prefix}")
                    
        except Exception as e:
            logger.warning(f"Error during orphaned resource cleanup: {e}")
    
    def get_container_logs(self, instance_id: str) -> str:
        """Get container logs."""
        if instance_id not in self.containers:
            return "Container not found"
        
        container_name = self.containers[instance_id]['name']
        
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            result = subprocess.run(
                docker_cmd + ["logs", "--tail", "1000", container_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Error getting logs: {e}"
    
    def get_container_status(self, instance_id: str) -> str:
        """Get container status."""
        if instance_id not in self.containers:
            return "not_found"
        
        container_name = self.containers[instance_id]['name']
        
        try:
            docker_cmd = self._get_docker_cmd_prefix()
            result = subprocess.run(
                docker_cmd + ["ps", "-f", f"name=^{container_name}$", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.stdout.strip():
                return "running" if "Up" in result.stdout else "stopped"
            else:
                return "not_found"
                
        except Exception as e:
            logger.error(f"Error getting container status: {e}")
            return "error"


if __name__ == "__main__":
    # Test the persistent containers manager
    logging.basicConfig(level=logging.INFO)
    
    manager = AndroidContainersPersistent()
    
    # Test configuration
    test_config = {
        'java_version': '17',
        'gradle_version': '8.6',
        'compile_sdk': '35',
        'jvm_args': '-Xmx4096m'
    }
    
    try:
        success = manager.create_container("test-instance", test_config, "/tmp")
        if success:
            manager.start_container("test-instance")
            
            # Test command execution
            exit_code, output = manager.exec_command("test-instance", "echo 'Test successful'")
            print(f"Test command result: {exit_code}")
            print(output[:200] + "..." if len(output) > 200 else output)
            
            # Test preparation for different phases
            manager.prepare_for_test_execution("test-instance", "pre")
            
    finally:
        # Keep container for reuse
        manager.cleanup_all(keep_persistent=True)