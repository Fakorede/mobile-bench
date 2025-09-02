#!/usr/bin/env python3
"""
Fixed Docker container management for Android build environments using subprocess approach.
Addresses git safe directory and test detection issues.
"""

import subprocess
import logging
import os
import tempfile
import time
from typing import Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidContainers:
    """Manages Docker containers for Android build environments using subprocess."""
    
    BASE_IMAGE = "mingc/android-build-box:latest"
    
    def __init__(self, docker_context: str = None):
        self.containers = {}
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
                        repo_path: str) -> bool:
        """Create container configuration."""
        
        logger.info(f"Setting up container configuration for {instance_id}")
        
        # Store configuration for later use
        self.containers[instance_id] = {
            'config': config,
            'repo_path': os.path.abspath(repo_path),
            'name': f"android-bench-{instance_id.replace('_', '-').replace('__', '-').lower()}"
        }
        
        logger.info(f"Container configuration ready for {instance_id}")
        return True
    
    def start_container(self, instance_id: str) -> bool:
        """Start container (validate configuration)."""
        if instance_id not in self.containers:
            raise ValueError(f"Container not found for instance: {instance_id}")
        
        try:
            # Test basic Docker connectivity and fix git safe directory issue
            setup_command = """
# Fix git safe directory issue immediately
git config --global --add safe.directory /workspace
git config --global user.email 'validator@android-bench.local'
git config --global user.name 'Android Bench Validator'
echo 'Container ready and git configured'
"""
            
            exit_code, output = self.exec_command(instance_id, setup_command)
            
            if exit_code == 0:
                logger.info(f"Container validated and configured for {instance_id}")
                return True
            else:
                raise RuntimeError(f"Container validation failed: {output}")
                
        except Exception as e:
            logger.error(f"Failed to start container for {instance_id}: {e}")
            raise
    
    def exec_command(self, instance_id: str, command: str, 
                    workdir: str = "/workspace", timeout: int = 300) -> Tuple[int, str]:
        """Execute command in container using subprocess approach."""
        if instance_id not in self.containers:
            raise ValueError(f"Container not found for instance: {instance_id}")
        
        container_info = self.containers[instance_id]
        config = container_info['config']
        repo_path = container_info['repo_path']
        
        # Build environment variables
        env_vars = self._build_environment_vars(config)
        
        # Build Docker command with improved setup
        docker_cmd = self._get_docker_cmd_prefix() + [
            "run", "--rm",
            "--network", "host",
            "--dns", "8.8.8.8",
            "--dns", "8.8.4.4",
            "-v", f"{repo_path}:{workdir}",
            "-w", workdir,
            "-e", f"HOME=/tmp",
            "-e", f"GRADLE_USER_HOME=/tmp/.gradle",
            # Fix ownership issues
            "--user", "root"
        ]
        
        # Add environment variables
        for key, value in env_vars.items():
            docker_cmd.extend(["-e", f"{key}={value}"])
        
        # Wrap command with git safety setup
        wrapped_command = f"""
# Always set git safe directory first
git config --global --add safe.directory /workspace 2>/dev/null || true
git config --global user.email 'validator@android-bench.local' 2>/dev/null || true
git config --global user.name 'Android Bench Validator' 2>/dev/null || true

# Now run the actual command
{command}
"""
        
        # Add image and command
        docker_cmd.append(self.BASE_IMAGE)
        docker_cmd.extend(["bash", "-c", wrapped_command])
        
        try:
            logger.debug(f"Executing Docker command for {instance_id}")
            
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
            logger.error(f"Command timed out for {instance_id}")
            return 124, f"Command timed out after {timeout} seconds"
        except Exception as e:
            logger.error(f"Failed to execute command in {instance_id}: {e}")
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
        """Install specific SDK components based on configuration."""
        compile_sdk = config.get('compile_sdk', '35')
        build_tools = config.get('build_tools', '35.0.0')
        ndk_version = config.get('ndk_version')
        
        # Install required SDK components
        sdk_components = [
            f"platforms;android-{compile_sdk}",
            f"build-tools;{build_tools}",
            "platform-tools",
            "cmdline-tools;latest"
        ]
        
        if ndk_version:
            sdk_components.append(f"ndk;{ndk_version}")
        
        # Accept licenses first
        license_cmd = """
yes | ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager --licenses 2>/dev/null || true
"""
        exit_code, output = self.exec_command(instance_id, license_cmd)
        if exit_code != 0:
            logger.warning(f"License acceptance had issues: {output}")
        
        # Install components
        for component in sdk_components:
            cmd = f"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager '{component}'"
            exit_code, output = self.exec_command(instance_id, cmd)
            if exit_code != 0:
                logger.warning(f"Failed to install {component}: {output}")
            else:
                logger.info(f"Installed SDK component: {component}")
    
    def cleanup_container(self, instance_id: str):
        """Cleanup container configuration."""
        if instance_id in self.containers:
            del self.containers[instance_id]
            logger.info(f"Cleaned up container configuration for {instance_id}")
    
    def cleanup_all(self):
        """Cleanup all container configurations."""
        instance_ids = list(self.containers.keys())
        for instance_id in instance_ids:
            self.cleanup_container(instance_id)
        logger.info("All container configurations cleaned up")
    
    def get_container_logs(self, instance_id: str) -> str:
        """Get container logs (not applicable with subprocess approach)."""
        return "Logs available in command outputs"
    
    def get_container_status(self, instance_id: str) -> str:
        """Get container status."""
        if instance_id in self.containers:
            return "ready"
        return "not_found"


if __name__ == "__main__":
    # Test the containers manager
    logging.basicConfig(level=logging.INFO)
    
    manager = AndroidContainers()
    
    # Test configuration
    test_config = {
        'java_version': '17',
        'gradle_version': '8.6',
        'compile_sdk': '35',
        'jvm_args': '-Xmx4096m'
    }
    
    try:
        manager.create_container("test-instance", test_config, "/tmp")
        manager.start_container("test-instance")
        
        exit_code, output = manager.exec_command("test-instance", "echo 'Test successful'")
        print(f"Test command result: {exit_code}")
        print(output[:200] + "..." if len(output) > 200 else output)
        
    finally:
        manager.cleanup_all()