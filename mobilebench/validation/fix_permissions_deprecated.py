#!/usr/bin/env python3
"""
Utility script to fix common Docker and Git permission issues.
"""

import docker
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def fix_docker_permissions():
    """Fix Docker permission issues and clean up containers."""
    try:
        client = docker.from_env()
        
        # List all android-bench containers
        containers = client.containers.list(all=True, filters={'name': 'android-bench'})
        
        print(f"Found {len(containers)} android-bench containers")
        
        for container in containers:
            try:
                print(f"Cleaning up container: {container.name}")
                
                # Stop if running
                if container.status == 'running':
                    container.stop(timeout=10)
                    print(f"  Stopped {container.name}")
                
                # Remove container
                container.remove(force=True)
                print(f"  Removed {container.name}")
                
            except Exception as e:
                print(f"  Error cleaning {container.name}: {e}")
        
        # Clean up dangling images
        try:
            client.images.prune()
            print("Cleaned up dangling images")
        except Exception as e:
            print(f"Error cleaning images: {e}")
            
    except Exception as e:
        print(f"Error accessing Docker: {e}")
        print("Make sure Docker is running and you have permissions")


def fix_git_permissions():
    """Fix global git configuration for container compatibility."""
    try:
        git_commands = [
            "git config --global safe.directory '*'",
            "git config --global user.email 'validator@android-bench.local'",
            "git config --global user.name 'Android Bench Validator'",
            "git config --global init.defaultBranch main"
        ]
        
        for cmd in git_commands:
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✓ {cmd}")
                else:
                    print(f"✗ {cmd}: {result.stderr}")
            except Exception as e:
                print(f"✗ {cmd}: {e}")
                
    except Exception as e:
        print(f"Error configuring git: {e}")


def check_docker_status():
    """Check Docker daemon status and connectivity."""
    try:
        client = docker.from_env()
        
        # Test connection
        info = client.info()
        print(f"✓ Docker connected successfully")
        print(f"  Version: {info.get('ServerVersion', 'Unknown')}")
        print(f"  Containers: {info.get('Containers', 0)}")
        print(f"  Images: {info.get('Images', 0)}")
        
        # Check if mingc/android-build-box is available
        try:
            image = client.images.get("mingc/android-build-box:latest")
            print(f"✓ Base image mingc/android-build-box:latest found")
            print(f"  Size: {image.attrs.get('Size', 0) / (1024*1024*1024):.1f} GB")
        except docker.errors.ImageNotFound:
            print("⚠ Base image mingc/android-build-box:latest not found")
            print("  Run: docker pull mingc/android-build-box:latest")
        
        return True
        
    except Exception as e:
        print(f"✗ Docker connection failed: {e}")
        print("  Make sure Docker is running")
        return False


def cleanup_temp_directories():
    """Clean up temporary directories from previous runs."""
    import tempfile
    import glob
    
    temp_dir = tempfile.gettempdir()
    pattern = os.path.join(temp_dir, "android_bench_*")
    
    temp_dirs = glob.glob(pattern)
    print(f"Found {len(temp_dirs)} temporary directories")
    
    for temp_path in temp_dirs:
        try:
            import shutil
            shutil.rmtree(temp_path)
            print(f"  Removed {temp_path}")
        except Exception as e:
            print(f"  Error removing {temp_path}: {e}")


def main():
    """Main fix script."""
    print("Android-Bench Validation Fix Script")
    print("=" * 40)
    
    print("\n1. Checking Docker status...")
    docker_ok = check_docker_status()
    
    print("\n2. Fixing Git permissions...")
    fix_git_permissions()
    
    print("\n3. Cleaning up Docker containers...")
    if docker_ok:
        fix_docker_permissions()
    
    print("\n4. Cleaning up temp directories...")
    cleanup_temp_directories()
    
    print("\n5. System status:")
    if docker_ok:
        print("✓ Docker is ready")
    else:
        print("✗ Docker needs attention")
    
    print("✓ Git configuration updated")
    print("✓ Cleanup completed")
    
    print("\nNow you can retry your validation:")
    print("  python run.py --sample")
    print("  python validator.py dataset.jsonl")


if __name__ == "__main__":
    main()