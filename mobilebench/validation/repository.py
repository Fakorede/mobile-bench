#!/usr/bin/env python3
"""
Git repository and patch management for Android validation using subprocess approach.
"""

import os
import tempfile
import logging
import re
from typing import Tuple, List
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidRepository:
    """Handles git operations and patch application for Android projects using subprocess."""
    
    def __init__(self, containers_manager):
        self.containers = containers_manager
    
    def checkout_base_commit(self, instance_id: str, base_commit: str) -> bool:
        """Checkout the base commit and reset to clean state."""
        try:
            # Comprehensive git setup and checkout command
            checkout_command = f"""
cd /workspace &&
echo "=== Setting up git configuration ===" &&
git config --global --add safe.directory /workspace &&
git config --global user.email 'validator@android-bench.local' &&
git config --global user.name 'Android Bench Validator' &&

echo "=== Cleaning repository state ===" &&
# Handle submodules more carefully
git submodule foreach --recursive 'git reset --hard' 2>/dev/null || true &&
git reset --hard HEAD 2>/dev/null || true &&
git clean -fdx 2>/dev/null || true &&

echo "=== Fetching latest changes ===" &&
git fetch origin --unshallow 2>/dev/null || git fetch origin 2>/dev/null || true &&

echo "=== Deinitializing submodules before checkout ===" &&
git submodule deinit --all -f 2>/dev/null || true &&

echo "=== Cleaning untracked files before checkout ===" &&
git clean -fdx 2>/dev/null || true &&

echo "=== Checking out base commit {base_commit} ===" &&
git checkout --force {base_commit} &&

echo "=== Updating submodules ===" &&
git submodule update --init --recursive --force 2>/dev/null || true &&

echo "=== Verifying checkout ===" &&
CURRENT_COMMIT=$(git rev-parse HEAD) &&
echo "Current commit: $CURRENT_COMMIT" &&
echo "Target commit: {base_commit}" &&

# Check if we're on the right commit (allow partial matches)
if [[ "$CURRENT_COMMIT" == {base_commit}* ]]; then
    echo "Successfully checked out {base_commit}"
    exit 0
else
    echo "Failed to checkout {base_commit}"
    exit 1
fi
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                checkout_command,
                workdir="/workspace",
                timeout=300
            )
            
            if exit_code == 0:
                logger.info(f"Successfully checked out {base_commit} for {instance_id}")
                return True
            else:
                logger.error(f"Failed to checkout {base_commit} for {instance_id}: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error during checkout for {instance_id}: {e}")
            return False
    
    def apply_patch(self, instance_id: str, patch_content: str, patch_name: str = "patch") -> Tuple[bool, str]:
        """Apply a patch to the repository using multiple strategies."""
        import tempfile
        import os
        
        try:
            # Validate patch content
            if not patch_content.strip():
                return True, "Empty patch - nothing to apply"
            
            # For large patches, write to temporary file and copy to container
            # to avoid "Argument list too long" error
            temp_patch_file = None
            try:
                # Create temporary file on host
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.patch') as f:
                    f.write(patch_content)
                    temp_patch_file = f.name
                
                # Copy patch file to container
                container_name = self.containers.containers[instance_id]['name']
                docker_cmd = ["docker", "cp", temp_patch_file, f"{container_name}:/tmp/{patch_name}.patch"]
                
                import subprocess
                result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    logger.error(f"Failed to copy patch file to container: {result.stderr}")
                    return False, f"Failed to copy patch to container: {result.stderr}"
                    
            finally:
                # Clean up temporary file
                if temp_patch_file and os.path.exists(temp_patch_file):
                    os.unlink(temp_patch_file)
            
            # Comprehensive patch application command (without embedding patch content)
            patch_command = f"""
cd /workspace &&
echo "=== Applying patch: {patch_name} ===" &&

echo "=== Patch file info ===" &&
ls -la /tmp/{patch_name}.patch &&

echo "=== Patch file created ===" &&
echo "Patch size: $(wc -l < /tmp/{patch_name}.patch) lines" &&

# Try different patch application strategies
echo "=== Strategy 1: git apply --verbose ===" &&
if git apply --verbose /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: git apply worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 2: git apply --verbose --reject ===" &&
if git apply --verbose --reject /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: git apply --reject worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 3: git apply with whitespace options ===" &&
if git apply --verbose --ignore-space-change --ignore-whitespace /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: git apply with whitespace options worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 4: patch -p1 ===" &&
if patch -p1 < /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: patch -p1 worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 5: patch with fuzz ===" &&
if patch --batch --fuzz=5 -p1 < /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: patch with fuzz worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== All patch strategies failed ===" &&
rm -f /tmp/{patch_name}.patch &&
exit 1
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                patch_command,
                workdir="/workspace",
                timeout=120
            )
            
            if exit_code == 0:
                logger.info(f"Successfully applied patch {patch_name} for {instance_id}")
                
                # Verify patch was applied by checking git status
                status_success, git_status = self.get_git_status(instance_id)
                if status_success and git_status.strip():
                    logger.info(f"Patch applied successfully, files changed: {len(git_status.split())}")
                else:
                    logger.warning("Patch applied but no changes detected in git status")
                
                return True, output
            else:
                logger.error(f"Failed to apply patch {patch_name} for {instance_id}")
                return False, output
            
        except Exception as e:
            logger.error(f"Error applying patch for {instance_id}: {e}")
            return False, str(e)
    
    def apply_patch_to_path(self, instance_id: str, patch_content: str, patch_name: str = "patch", workdir: str = "/workspace") -> Tuple[bool, str]:
        """Apply a patch to a specific path in the repository using multiple strategies."""
        import tempfile
        import os
        
        try:
            # Validate patch content
            if not patch_content.strip():
                return True, "Empty patch - nothing to apply"
            
            # For large patches, write to temporary file and copy to container
            # to avoid "Argument list too long" error
            temp_patch_file = None
            try:
                # Create temporary file on host
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.patch') as f:
                    f.write(patch_content)
                    temp_patch_file = f.name
                
                # Copy patch file to container
                container_name = self.containers.containers[instance_id]['name']
                docker_cmd = ["docker", "cp", temp_patch_file, f"{container_name}:/tmp/{patch_name}.patch"]
                
                import subprocess
                result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    logger.error(f"Failed to copy patch file to container: {result.stderr}")
                    return False, f"Failed to copy patch to container: {result.stderr}"
                    
            finally:
                # Clean up temporary file
                if temp_patch_file and os.path.exists(temp_patch_file):
                    os.unlink(temp_patch_file)
            
            # Comprehensive patch application command (without embedding patch content)
            patch_command = f"""
cd {workdir} &&
echo "=== Applying patch: {patch_name} to {workdir} ===" &&

# Set up git config for this directory
git config --global --add safe.directory {workdir} &&

echo "=== Patch file info ===" &&
ls -la /tmp/{patch_name}.patch &&
echo "Patch size: $(wc -l < /tmp/{patch_name}.patch) lines" &&

echo "=== Patch content ===" &&
head -20 /tmp/{patch_name}.patch &&

echo "=== Repository state ===" &&
pwd &&
git status --porcelain || echo "Not a git repo or git status failed" &&

echo "=== Strategy 1: git apply --3way ===" &&
if git apply --3way --verbose /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: git apply --3way worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 2: git apply ===" &&
if git apply --verbose /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: git apply worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 3: git apply with whitespace options ===" &&
if git apply --verbose --ignore-space-change --ignore-whitespace /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: git apply with whitespace options worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 4: patch -p1 ===" &&
if patch -p1 < /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: patch -p1 worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== Strategy 5: patch with fuzz ===" &&
if patch --batch --fuzz=5 -p1 < /tmp/{patch_name}.patch 2>&1; then
    echo "SUCCESS: patch with fuzz worked"
    rm -f /tmp/{patch_name}.patch
    exit 0
fi

echo "=== All patch strategies failed ===" &&
rm -f /tmp/{patch_name}.patch &&
exit 1
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                patch_command,
                workdir=workdir,
                timeout=120
            )
            
            if exit_code == 0:
                logger.info(f"Successfully applied patch {patch_name} for {instance_id} at {workdir}")
                
                # Verify patch was applied by checking git status
                status_command = f"cd {workdir} && git status --porcelain"
                status_exit, git_status = self.containers.exec_command(
                    instance_id, status_command, workdir=workdir
                )
                if status_exit == 0 and git_status.strip():
                    logger.info(f"Patch applied successfully, files changed: {len(git_status.split())}")
                else:
                    logger.warning("Patch applied but no changes detected in git status")
                
                return True, output
            else:
                logger.error(f"Failed to apply patch {patch_name} for {instance_id} at {workdir}")
                return False, output
            
        except Exception as e:
            logger.error(f"Error applying patch for {instance_id} at {workdir}: {e}")
            return False, str(e)
    
    def get_git_diff(self, instance_id: str) -> Tuple[bool, str]:
        """Get git diff to see current changes."""
        try:
            command = "cd /workspace && git -c core.fileMode=false diff"
            exit_code, output = self.containers.exec_command(
                instance_id,
                command,
                workdir="/workspace"
            )
            
            return exit_code == 0, output.strip()
            
        except Exception as e:
            logger.error(f"Error getting git diff for {instance_id}: {e}")
            return False, str(e)
    
    def get_git_status(self, instance_id: str) -> Tuple[bool, str]:
        """Get git status to see repository state."""
        try:
            command = "cd /workspace && git status --porcelain"
            exit_code, output = self.containers.exec_command(
                instance_id,
                command,
                workdir="/workspace"
            )
            
            return exit_code == 0, output.strip()
            
        except Exception as e:
            logger.error(f"Error getting git status for {instance_id}: {e}")
            return False, str(e)
    
    def reset_to_clean_state(self, instance_id: str, repo_name: str = None, base_commit: str = None, use_fresh_clone: bool = True) -> bool:
        """Reset repository to clean state (remove all changes including stub patches)."""
        if use_fresh_clone and repo_name and base_commit:
            return self._reset_with_fresh_clone(instance_id, repo_name, base_commit)
        else:
            return self._reset_with_git(instance_id)
    
    def _reset_with_fresh_clone(self, instance_id: str, repo_name: str, base_commit: str) -> bool:
        """Reset by recloning the repository fresh to avoid any state issues."""
        try:
            logger.info(f"Performing fresh clone reset for {instance_id}: {repo_name}@{base_commit}")
            
            # Kill any gradle processes and cleanup workspace more carefully
            cleanup_command = r"""
cd / &&
echo "=== Stopping all processes in workspace ===" &&
# Kill any gradle or java processes that might be holding files
pkill -f gradle 2>/dev/null || true &&
pkill -f java 2>/dev/null || true &&
sleep 2 &&

# Force kill any remaining processes using workspace files
lsof +D /workspace 2>/dev/null | awk 'NR>1 {print $2}' | xargs -r kill -9 2>/dev/null || true &&
sleep 1 &&

echo "=== Removing existing workspace ===" &&
# Use force and multiple attempts
rm -rf /workspace 2>/dev/null || (
    echo "First rm attempt failed, trying with force..." &&
    chmod -R 755 /workspace 2>/dev/null || true &&
    rm -rf /workspace 2>/dev/null || (
        echo "Second rm attempt failed, using find..." &&
        find /workspace -type f -exec rm -f {} \; 2>/dev/null || true &&
        find /workspace -type d -exec rmdir {} \; 2>/dev/null || true &&
        rm -rf /workspace 2>/dev/null || true
    )
) &&
echo "=== Workspace removed ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                cleanup_command,
                workdir="/",
                timeout=120  # Longer timeout for cleanup
            )
            
            if exit_code != 0:
                logger.warning(f"Primary cleanup failed: {output}")
                logger.info("Attempting alternative cleanup approach...")
                
                # Alternative approach: move workspace and create new one
                alt_cleanup_command = """
cd / &&
echo "=== Alternative cleanup approach ===" &&
# Move workspace to temp location and create new empty one
mv /workspace /workspace_old_$(date +%s) 2>/dev/null || true &&
mkdir -p /workspace &&
echo "=== Alternative cleanup complete ==="
"""
                
                exit_code2, output2 = self.containers.exec_command(
                    instance_id,
                    alt_cleanup_command,
                    workdir="/",
                    timeout=60
                )
                
                if exit_code2 != 0:
                    logger.error(f"Failed to cleanup workspace with alternative method: {output2}")
                    return False
                else:
                    logger.info("Alternative cleanup succeeded")
            
            # Clone fresh repository
            clone_command = f"""
cd / &&
echo "=== Cloning repository fresh ===" &&
git config --global safe.directory '*' &&
git config --global user.email 'android-bench@example.com' &&
git config --global user.name 'Android Bench Evaluator' &&
git clone --depth 100 https://github.com/{repo_name}.git /workspace &&
cd /workspace &&
echo "=== Deinitializing submodules before checkout ===" &&
git submodule deinit --all -f 2>/dev/null || true &&
echo "=== Cleaning untracked files before checkout ===" &&
git clean -fdx 2>/dev/null || true &&
echo "=== Checking out base commit ===" &&
git checkout {base_commit} || (git fetch --unshallow && git submodule deinit --all -f 2>/dev/null && git clean -fdx 2>/dev/null && git checkout {base_commit}) &&
echo "=== Fresh clone complete ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                clone_command,
                workdir="/"
            )
            
            if exit_code == 0:
                logger.info(f"Successfully reset {instance_id} with fresh clone")
                logger.debug(f"Clone output: {output}")
                return True
            else:
                logger.error(f"CRITICAL: Fresh clone failed for {instance_id}")
                logger.error(f"Clone command output: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error performing fresh clone reset for {instance_id}: {e}")
            return False
    
    def _reset_with_git(self, instance_id: str) -> bool:
        """Reset repository using git commands (fallback method)."""
        try:
            reset_command = """
cd /workspace &&
echo "=== Resetting repository to clean state ===" &&

# Handle submodules first
git submodule foreach --recursive 'git reset --hard' 2>/dev/null || true &&

# Check if we have an original commit hash saved (before stub patches)
if [ -f '.original_commit_before_stubs' ]; then
    ORIGINAL_COMMIT=$(cat .original_commit_before_stubs)
    echo "Found original commit before stubs: $ORIGINAL_COMMIT" &&
    echo "Resetting to original commit (before stub patches)..." &&
    git reset --hard "$ORIGINAL_COMMIT" &&
    echo "Reset to original commit successful" &&
    # Clean the marker file since we're back to original state
    rm -f .original_commit_before_stubs
else
    echo "No original commit marker found, resetting to current HEAD" &&
    # Reset all changes to current HEAD (fallback behavior)
    git reset --hard HEAD
fi &&

# Clean untracked files
git clean -fdx &&

echo "=== Repository reset to clean state ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                reset_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.info(f"Successfully reset {instance_id} to clean state (removed stub patches)")
                logger.debug(f"Reset output: {output}")
                return True
            else:
                logger.error(f"CRITICAL: Git reset failed for {instance_id} - stub patches not removed!")
                logger.error(f"Reset command output: {output}")
                logger.error("This will likely cause post-solution test failures due to conflicting stub patches!")
                return False
            
        except Exception as e:
            logger.error(f"Error resetting {instance_id} to clean state: {e}")
            return False
    
    def validate_patch_format(self, patch_content: str) -> Tuple[bool, str]:
        """Validate that patch content is properly formatted."""
        if not patch_content.strip():
            return False, "Empty patch content"
        
        # Check for basic patch format indicators
        patch_indicators = [
            "diff --git",
            "--- a/",
            "+++ b/",
            "@@",
            "index "
        ]
        
        has_patch_format = any(indicator in patch_content for indicator in patch_indicators)
        
        if not has_patch_format:
            return False, "Does not appear to be a valid patch format"
        
        # Check for proper line structure
        lines = patch_content.split('\n')
        if len(lines) < 2:
            return False, "Patch too short"
        
        return True, "Valid patch format"
    
    def extract_changed_files(self, patch_content: str) -> List[str]:
        """Extract list of files changed in the patch."""
        # Pattern to match file paths in patch
        file_patterns = [
            r'\+\+\+ b/(.+)',
            r'diff --git a/.+ b/(.+)'
        ]
        
        changed_files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, patch_content)
            changed_files.update(matches)
        
        return list(changed_files)
    
    def extract_test_files_from_patch(self, patch_content: str) -> List[str]:
        """Extract test files from patch content."""
        changed_files = self.extract_changed_files(patch_content)
        
        test_files = []
        for file_path in changed_files:
            file_lower = file_path.lower()
            if ('test' in file_lower and 
                (file_path.endswith('.java') or file_path.endswith('.kt'))):
                test_files.append(file_path)
        
        return test_files
    
    def get_repository_info(self, instance_id: str) -> dict:
        """Get basic repository information."""
        info = {}
        
        try:
            # Get repository information
            info_command = """
cd /workspace &&
echo "CURRENT_COMMIT=$(git rev-parse HEAD)" &&
echo "CURRENT_BRANCH=$(git branch --show-current)" &&
echo "REPO_ROOT=$(git rev-parse --show-toplevel)" &&
echo "ORIGIN_URL=$(git config --get remote.origin.url)"
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                info_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                # Parse the output
                for line in output.split('\n'):
                    if line.startswith('CURRENT_COMMIT='):
                        info['current_commit'] = line.split('=', 1)[1].strip()
                    elif line.startswith('CURRENT_BRANCH='):
                        info['current_branch'] = line.split('=', 1)[1].strip()
                    elif line.startswith('REPO_ROOT='):
                        info['repo_root'] = line.split('=', 1)[1].strip()
                    elif line.startswith('ORIGIN_URL='):
                        info['origin_url'] = line.split('=', 1)[1].strip()
                
        except Exception as e:
            logger.error(f"Error getting repository info for {instance_id}: {e}")
        
        return info
    
    def create_patch_from_changes(self, instance_id: str) -> Tuple[bool, str]:
        """Create a patch from current uncommitted changes."""
        try:
            command = "cd /workspace && git diff HEAD"
            exit_code, patch_content = self.containers.exec_command(
                instance_id,
                command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                return True, patch_content
            else:
                return False, "Failed to create patch from changes"
                
        except Exception as e:
            logger.error(f"Error creating patch for {instance_id}: {e}")
            return False, str(e)


if __name__ == "__main__":
    # Test the repository manager
    logging.basicConfig(level=logging.INFO)
    print("Android Repository Manager (subprocess) module loaded successfully")