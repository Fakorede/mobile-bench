#!/usr/bin/env python3
"""
Enhanced Docker container management for Android build environments using mingc/android-build-box.
Added comprehensive Java version verification to ensure proper configuration.
"""

import docker
import logging
import os
import tempfile
from typing import Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidContainerManager:
    """Manages Docker containers for Android build environments with verification."""
    
    BASE_IMAGE = "mingc/android-build-box:latest"
    
    def __init__(self):
        self.client = docker.from_env()
        self.containers = {}
        self._ensure_base_image()
        
    def _ensure_base_image(self):
        """Ensure the base image is available locally."""
        try:
            self.client.images.get(self.BASE_IMAGE)
            logger.info(f"Base image {self.BASE_IMAGE} found locally")
        except docker.errors.ImageNotFound:
            logger.info(f"Pulling base image {self.BASE_IMAGE}...")
            self.client.images.pull(self.BASE_IMAGE)
            logger.info("Base image pulled successfully")
    
    def create_container(self, instance_id: str, config: Dict[str, str], 
                        repo_path: str) -> docker.models.containers.Container:
        """Create Android build container with custom configuration."""
        
        logger.info(f"Creating container for {instance_id} with config: {config}")
        
        # Build environment variables
        env_vars = self._build_environment_vars(config)
        
        # Log the Java configuration being set
        logger.info(f"Setting Java configuration for {instance_id}:")
        logger.info(f"  JAVA_VERSION: {env_vars.get('JAVA_VERSION')}")
        logger.info(f"  JAVA_HOME: {env_vars.get('JAVA_HOME')}")
        logger.info(f"  GRADLE_JAVA_HOME: {env_vars.get('GRADLE_JAVA_HOME')}")
        
        # Create container
        container = self.client.containers.create(
            image=self.BASE_IMAGE,
            name=f"android-bench-{instance_id.replace('_', '-').replace('__', '-').lower()}",
            detach=True,
            tty=True,
            stdin_open=True,
            working_dir="/workspace",
            volumes={
                os.path.abspath(repo_path): {
                    'bind': '/workspace',
                    'mode': 'rw'
                }
            },
            environment=env_vars,
            mem_limit='8g',
            cpu_count=4,
            network_mode='bridge'
        )
        
        self.containers[instance_id] = container
        logger.info(f"Created container {container.name} for {instance_id}")
        return container
    
    def _build_environment_vars(self, config: Dict[str, str]) -> Dict[str, str]:
        """Build environment variables based on configuration."""
        java_version = config.get('java_version', '17')
        gradle_version = config.get('gradle_version', '8.6')
        jvm_args = config.get('jvm_args', '-Xmx4096m')
        
        # Base environment from mingc/android-build-box
        env_vars = {
            # Java configuration
            'JAVA_VERSION': java_version,
            'JAVA_HOME': f'/usr/lib/jvm/java-{java_version}-openjdk-amd64',
            
            # Android SDK configuration
            'ANDROID_HOME': '/opt/android-sdk',
            'ANDROID_SDK_ROOT': '/opt/android-sdk',
            'ANDROID_SDK_HOME': '/opt/android-sdk',
            
            # Gradle configuration
            'GRADLE_VERSION': gradle_version,
            'GRADLE_HOME': f'/opt/gradle/gradle-{gradle_version}',
            'GRADLE_OPTS': jvm_args,
            
            # Ensure gradle uses the correct Java version
            'GRADLE_JAVA_HOME': f'/usr/lib/jvm/java-{java_version}-openjdk-amd64',
            
            # Build configuration
            'COMPILE_SDK_VERSION': config.get('compile_sdk', '35'),
            'TARGET_SDK_VERSION': config.get('target_sdk', '35'),
            'MIN_SDK_VERSION': config.get('min_sdk', '21'),
            'BUILD_TOOLS_VERSION': config.get('build_tools', '35.0.0'),
            
            # Path configuration with correct Java version first
            'PATH': f'/usr/lib/jvm/java-{java_version}-openjdk-amd64/bin:/opt/gradle/gradle-{gradle_version}/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/tools/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        }
        
        # Add NDK configuration if specified
        if config.get('ndk_version'):
            env_vars.update({
                'NDK_VERSION': config['ndk_version'],
                'ANDROID_NDK_HOME': f"/opt/android-sdk/ndk/{config['ndk_version']}",
                'ANDROID_NDK_ROOT': f"/opt/android-sdk/ndk/{config['ndk_version']}"
            })
        
        return env_vars
    
    def start_container(self, instance_id: str) -> docker.models.containers.Container:
        """Start container and configure it for the specific build with verification."""
        container = self.containers.get(instance_id)
        if not container:
            raise ValueError(f"Container not found for instance: {instance_id}")
            
        try:
            container.start()
            logger.info(f"Started container for {instance_id}: {container.id}")
            
            # Wait for container to be ready
            result = container.exec_run("echo 'Container ready'", workdir="/workspace")
            if result.exit_code != 0:
                raise RuntimeError("Container failed to start properly")
            
            # ENHANCED: Verify Java configuration before proceeding
            self._verify_java_configuration(instance_id)
            
            # Configure container for this specific build
            self._configure_container(instance_id)
            
            return container
            
        except Exception as e:
            logger.error(f"Failed to start container for {instance_id}: {e}")
            raise
    
    def _verify_java_configuration(self, instance_id: str):
        """Comprehensive Java version and configuration verification."""
        logger.info(f"🔍 VERIFYING Java configuration for {instance_id}")
        logger.info("=" * 60)
        
        # 1. Check Java version
        exit_code, java_version_output = self.exec_command(instance_id, "java -version 2>&1")
        if exit_code == 0:
            logger.info(f"✅ Java version check PASSED:")
            for line in java_version_output.strip().split('\n'):
                logger.info(f"   {line}")
        else:
            logger.error(f"❌ Java version check FAILED (exit code: {exit_code})")
            logger.error(f"   Output: {java_version_output}")
        
        # 2. Check JAVA_HOME environment variable
        exit_code, java_home_output = self.exec_command(instance_id, "echo $JAVA_HOME")
        if exit_code == 0:
            java_home = java_home_output.strip()
            logger.info(f"✅ JAVA_HOME: {java_home}")
            
            # Verify JAVA_HOME directory exists
            exit_code, exists_check = self.exec_command(instance_id, f"test -d {java_home} && echo 'EXISTS' || echo 'NOT_FOUND'")
            if exists_check.strip() == 'EXISTS':
                logger.info(f"✅ JAVA_HOME directory exists")
            else:
                logger.error(f"❌ JAVA_HOME directory NOT FOUND: {java_home}")
        else:
            logger.error(f"❌ JAVA_HOME check FAILED")
        
        # 3. Check which java binary is being used
        exit_code, which_java_output = self.exec_command(instance_id, "which java")
        if exit_code == 0:
            java_binary_path = which_java_output.strip()
            logger.info(f"✅ Java binary path: {java_binary_path}")
        else:
            logger.error(f"❌ 'which java' FAILED")
        
        # 4. Check Gradle version and its Java detection
        exit_code, gradle_version_output = self.exec_command(instance_id, "./gradlew --version")
        if exit_code == 0:
            logger.info(f"✅ Gradle version check PASSED:")
            for line in gradle_version_output.strip().split('\n'):
                if line.strip():  # Skip empty lines
                    logger.info(f"   {line}")
        else:
            logger.error(f"❌ Gradle version check FAILED (exit code: {exit_code})")
            logger.error(f"   Output: {gradle_version_output}")
        
        # 5. Check GRADLE_JAVA_HOME
        exit_code, gradle_java_home_output = self.exec_command(instance_id, "echo $GRADLE_JAVA_HOME")
        if exit_code == 0:
            gradle_java_home = gradle_java_home_output.strip()
            logger.info(f"✅ GRADLE_JAVA_HOME: {gradle_java_home}")
        else:
            logger.error(f"❌ GRADLE_JAVA_HOME check FAILED")
        
        # 6. List available Java versions in the container
        exit_code, java_versions_output = self.exec_command(instance_id, "ls -la /usr/lib/jvm/ | grep java")
        if exit_code == 0:
            logger.info(f"✅ Available Java versions in container:")
            for line in java_versions_output.strip().split('\n'):
                if line.strip():
                    logger.info(f"   {line}")
        else:
            logger.warning(f"⚠️  Could not list Java versions in /usr/lib/jvm/")
        
        # 7. Check PATH variable
        exit_code, path_output = self.exec_command(instance_id, "echo $PATH")
        if exit_code == 0:
            path_dirs = path_output.strip().split(':')
            logger.info(f"✅ PATH verification:")
            for i, path_dir in enumerate(path_dirs[:5]):  # Show first 5 entries
                logger.info(f"   [{i+1}] {path_dir}")
            if len(path_dirs) > 5:
                logger.info(f"   ... and {len(path_dirs) - 5} more directories")
        
        logger.info("=" * 60)
        logger.info(f"🔍 Java configuration verification completed for {instance_id}")
    
    def _configure_container(self, instance_id: str):
        """Configure container with build-specific settings."""
        container = self.containers[instance_id]
        
        # Make gradlew executable
        self.exec_command(instance_id, "find . -name 'gradlew' -exec chmod +x {} \\;")
        
        # Setup gradle daemon configuration
        self.exec_command(instance_id, "mkdir -p ~/.gradle")
        gradle_props = """
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.configureondemand=true
org.gradle.caching=false
"""
        self.exec_command(instance_id, f"echo '{gradle_props}' > ~/.gradle/gradle.properties")
        
        # Accept Android SDK licenses
        license_cmd = """
yes | ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager --licenses 2>/dev/null || true
"""
        self.exec_command(instance_id, license_cmd)
        
        logger.info(f"Configured container for {instance_id}")
    
    def exec_command(self, instance_id: str, command: str, 
                    workdir: str = "/workspace", user: str = "root") -> tuple[int, str]:
        """Execute command in container and return exit code and output."""
        container = self.containers.get(instance_id)
        if not container:
            raise ValueError(f"Container not found for instance: {instance_id}")
        
        try:
            logger.debug(f"Executing in {instance_id}: {command}")
            
            exec_result = container.exec_run(
                ["bash", "-c", command],
                workdir=workdir,
                user=user,
                demux=True,
                stdout=True,
                stderr=True,
                tty=False
            )
            
            stdout = exec_result.output[0] if exec_result.output[0] else b""
            stderr = exec_result.output[1] if exec_result.output[1] else b""
            
            output = stdout.decode('utf-8', errors='ignore') + stderr.decode('utf-8', errors='ignore')
            
            logger.debug(f"Command exit code: {exec_result.exit_code}")
            if exec_result.exit_code != 0:
                logger.debug(f"Command output: {output}")
            
            return exec_result.exit_code, output
            
        except Exception as e:
            logger.error(f"Failed to execute command in {instance_id}: {e}")
            raise
    
    def copy_to_container(self, instance_id: str, src_path: str, dst_path: str):
        """Copy file to container."""
        container = self.containers.get(instance_id)
        if not container:
            raise ValueError(f"Container not found for instance: {instance_id}")
            
        try:
            # Check if source file exists
            if not os.path.exists(src_path):
                logger.error(f"Source file does not exist: {src_path}")
                raise FileNotFoundError(f"Source file not found: {src_path}")
            
            # Create a tar archive in memory
            import tarfile
            import io
            
            tar_buffer = io.BytesIO()
            
            with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
                # Get the filename that we want in the container
                dst_filename = os.path.basename(dst_path)
                
                # Add the file to the tar archive with the desired name
                tar.add(src_path, arcname=dst_filename)
            
            # Reset buffer position to beginning
            tar_buffer.seek(0)
            
            # Extract directory path and ensure it exists in container
            dst_dir = os.path.dirname(dst_path)
            if not dst_dir or dst_dir == '.':
                dst_dir = '/'
            
            # Create the directory in the container if it doesn't exist
            if dst_dir != '/':
                mkdir_cmd = f"mkdir -p {dst_dir}"
                exit_code, output = self.exec_command(instance_id, mkdir_cmd)
                if exit_code != 0:
                    logger.warning(f"Failed to create directory {dst_dir}: {output}")
            
            # Copy the tar archive to the container
            success = container.put_archive(dst_dir, tar_buffer.getvalue())
            
            if not success:
                raise RuntimeError("Failed to put archive in container")
            
            logger.debug(f"Successfully copied {src_path} to {dst_path} in {instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to copy file to container {instance_id}: {e}")
            raise
    
    def copy_from_container(self, instance_id: str, src_path: str, dst_path: str):
        """Copy file from container."""
        container = self.containers.get(instance_id)
        if not container:
            raise ValueError(f"Container not found for instance: {instance_id}")
            
        try:
            # Get archive from container
            archive, _ = container.get_archive(src_path)
            
            # Extract to destination
            import tarfile
            import io
            
            tar_data = b''.join(archive)
            tar_file = tarfile.open(fileobj=io.BytesIO(tar_data))
            tar_file.extractall(dst_path)
            tar_file.close()
            
            logger.debug(f"Copied {src_path} from {instance_id} to {dst_path}")
        except Exception as e:
            logger.error(f"Failed to copy file from container {instance_id}: {e}")
            raise
    
    def cleanup_container(self, instance_id: str):
        """Stop and remove container with improved error handling."""
        container = self.containers.get(instance_id)
        if not container:
            return
            
        try:
            # Refresh container status
            container.reload()
            
            # Stop container if it's running
            if container.status == 'running':
                logger.info(f"Stopping running container for {instance_id}")
                container.stop(timeout=30)  # Increased timeout for graceful shutdown
                
                # Wait a bit for the container to fully stop
                import time
                time.sleep(2)
            
            # Force remove the container to handle any lingering state issues
            container.remove(force=True)
            del self.containers[instance_id]
            
            logger.info(f"Successfully cleaned up container for {instance_id}")
            
        except docker.errors.NotFound:
            # Container doesn't exist anymore, just remove from tracking
            if instance_id in self.containers:
                del self.containers[instance_id]
            logger.info(f"Container for {instance_id} was already removed")
            
        except docker.errors.APIError as e:
            if "is not running" in str(e) or "No such container" in str(e):
                # Container is already stopped or doesn't exist
                try:
                    container.remove(force=True)
                    del self.containers[instance_id]
                    logger.info(f"Force removed container for {instance_id}")
                except Exception as remove_error:
                    logger.warning(f"Could not remove container for {instance_id}: {remove_error}")
                    # Still remove from tracking
                    if instance_id in self.containers:
                        del self.containers[instance_id]
            else:
                logger.error(f"Docker API error during cleanup of {instance_id}: {e}")
                # Try force removal as last resort
                try:
                    container.remove(force=True)
                    del self.containers[instance_id]
                    logger.info(f"Force removed container for {instance_id} after API error")
                except Exception as force_error:
                    logger.error(f"Force removal also failed for {instance_id}: {force_error}")
                    # Remove from tracking anyway to prevent memory leaks
                    if instance_id in self.containers:
                        del self.containers[instance_id]
                        
        except Exception as e:
            logger.error(f"Unexpected error during cleanup of {instance_id}: {e}")
            # Try force removal as last resort
            try:
                container.remove(force=True)
                del self.containers[instance_id]
                logger.info(f"Force removed container for {instance_id} after unexpected error")
            except Exception as force_error:
                logger.error(f"Force removal also failed for {instance_id}: {force_error}")
                # Remove from tracking anyway
                if instance_id in self.containers:
                    del self.containers[instance_id]

    def cleanup_all(self):
        """Cleanup all containers with better error handling."""
        instance_ids = list(self.containers.keys())  # Create a copy to avoid modification during iteration
        
        for instance_id in instance_ids:
            try:
                self.cleanup_container(instance_id)
            except Exception as e:
                logger.error(f"Failed to cleanup container {instance_id}: {e}")
                # Continue with other containers
                continue
        
        # Final cleanup: remove any orphaned containers that might be from previous runs
        try:
            client = docker.from_env()
            orphaned_containers = client.containers.list(
                all=True, 
                filters={"name": "android-bench-"}
            )
            
            for container in orphaned_containers:
                try:
                    logger.info(f"Cleaning up orphaned container: {container.name}")
                    if container.status == 'running':
                        container.stop(timeout=10)
                    container.remove(force=True)
                except Exception as e:
                    logger.warning(f"Could not cleanup orphaned container {container.name}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error during orphaned container cleanup: {e}")
    
    def get_container_logs(self, instance_id: str) -> str:
        """Get container logs."""
        container = self.containers.get(instance_id)
        if not container:
            raise ValueError(f"Container not found for instance: {instance_id}")
            
        try:
            return container.logs().decode('utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to get logs for {instance_id}: {e}")
            return ""
    
    def get_container_status(self, instance_id: str) -> str:
        """Get container status."""
        container = self.containers.get(instance_id)
        if not container:
            return "not_found"
        
        try:
            container.reload()
            return container.status
        except Exception as e:
            logger.error(f"Failed to get status for {instance_id}: {e}")
            return "error"
    
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
        
        for component in sdk_components:
            cmd = f"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager '{component}'"
            exit_code, output = self.exec_command(instance_id, cmd)
            if exit_code != 0:
                logger.warning(f"Failed to install {component}: {output}")
            else:
                logger.info(f"Installed SDK component: {component}")


if __name__ == "__main__":
    # Test the containers manager
    logging.basicConfig(level=logging.INFO)
    
    manager = AndroidContainerManager()
    
    # Test configuration
    test_config = {
        'java_version': '17',
        'gradle_version': '8.6',
        'compile_sdk': '35',
        'jvm_args': '-Xmx4096m'
    }
    
    try:
        container = manager.create_container("test-instance", test_config, "/tmp")
        manager.start_container("test-instance")
        
        exit_code, output = manager.exec_command("test-instance", "./gradlew --version")
        print(f"Gradle version check: {exit_code}")
        print(output[:200] + "..." if len(output) > 200 else output)
        
    finally:
        manager.cleanup_all()