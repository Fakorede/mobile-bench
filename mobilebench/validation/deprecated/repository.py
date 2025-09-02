#!/usr/bin/env python3
"""
Git repository and patch management for Android validation.
"""

import os
import tempfile
import logging
import re
from typing import Tuple, List
from pathlib import Path

logger = logging.getLogger(__name__)


class AndroidRepository:
    """Handles git operations and patch application for Android projects."""
    
    def __init__(self, containers_manager):
        self.containers = containers_manager
    
    def checkout_base_commit(self, instance_id: str, base_commit: str) -> bool:
        """Checkout the base commit and reset to clean state."""
        try:
            # Fix git ownership issue first
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git config --global --add safe.directory /workspace",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.warning(f"Git safe directory warning for {instance_id}: {output}")
            
            # Reset to clean state first
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git reset --hard HEAD && git clean -fd",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.warning(f"Git reset/clean warning for {instance_id}: {output}")
            
            # Fetch to ensure we have the commit
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git fetch origin",
                workdir="/workspace"
            )
            
            # if exit_code != 0:
            #     logger.warning(f"Git unshallow failed for {instance_id}: {output}")
            #     # Fallback to regular fetch
            #     exit_code, output = self.containers.exec_command(
            #         instance_id,
            #         "git fetch origin",
            #         workdir="/workspace"
            #     )
            #     if exit_code != 0:
            #         logger.warning(f"Git fetch still failed for {instance_id}: {output}")
            
            # Checkout the specific base commit
            exit_code, output = self.containers.exec_command(
                instance_id,
                f"git checkout {base_commit}",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.error(f"Failed to checkout {base_commit} for {instance_id}: {output}")
                return False
                
            # Verify we're on the right commit
            exit_code, current_commit = self.containers.exec_command(
                instance_id,
                "git rev-parse HEAD",
                workdir="/workspace"
            )
            
            if exit_code == 0 and current_commit.strip().startswith(base_commit):
                logger.info(f"Successfully checked out {base_commit} for {instance_id}")
                return True
            else:
                logger.error(f"Commit verification failed for {instance_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error during checkout for {instance_id}: {e}")
            return False
    
    def apply_patch(self, instance_id: str, patch_content: str, patch_name: str = "patch") -> Tuple[bool, str]:
        """Apply a patch to the repository using multiple strategies."""
        try:
            # Validate patch content
            if not patch_content.strip():
                return True, "Empty patch - nothing to apply"
            
            # Create patch file in container
            container_patch_path = f"/tmp/{patch_name}.patch"
            
            # Write patch content to container (escape special characters)
            escaped_patch = patch_content.replace("'", "'\"'\"'").replace("\n", "\\n")
            exit_code, output = self.containers.exec_command(
                instance_id,
                f"printf '{escaped_patch}' > {container_patch_path}",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.error(f"Failed to create patch file in container: {output}")
                return False, output
            
            # Try different patch application strategies
            patch_strategies = [
                f"git apply --verbose {container_patch_path}",
                f"git apply --verbose --reject {container_patch_path}",
                f"git apply --verbose --ignore-space-change --ignore-whitespace {container_patch_path}",
                f"patch -p1 < {container_patch_path}",
                f"patch --batch --fuzz=5 -p1 < {container_patch_path}"
            ]
            
            success = False
            final_output = ""
            
            for strategy in patch_strategies:
                logger.info(f"Trying patch strategy: {strategy}")
                exit_code, output = self.containers.exec_command(
                    instance_id,
                    strategy,
                    workdir="/workspace"
                )
                
                final_output += f"\n--- Strategy: {strategy} ---\n{output}\n"
                
                if exit_code == 0:
                    logger.info(f"Successfully applied patch with: {strategy}")
                    success = True
                    break
                else:
                    logger.debug(f"Patch strategy failed: {strategy}")
            
            # Clean up patch file
            self.containers.exec_command(
                instance_id,
                f"rm -f {container_patch_path}",
                workdir="/workspace"
            )
            
            if success:
                # Verify patch was applied by checking git status
                exit_code, git_status = self.get_git_status(instance_id)
                if exit_code and git_status.strip():
                    logger.info(f"Patch applied successfully, files changed: {len(git_status.split())}")
                else:
                    logger.warning("Patch applied but no changes detected in git status")
            
            return success, final_output
            
        except Exception as e:
            logger.error(f"Error applying patch for {instance_id}: {e}")
            return False, str(e)
    
    def get_git_diff(self, instance_id: str) -> Tuple[bool, str]:
        """Get git diff to see current changes."""
        try:
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git -c core.fileMode=false diff",
                workdir="/workspace"
            )
            
            return exit_code == 0, output.strip()
            
        except Exception as e:
            logger.error(f"Error getting git diff for {instance_id}: {e}")
            return False, str(e)
    
    def get_git_status(self, instance_id: str) -> Tuple[bool, str]:
        """Get git status to see repository state."""
        try:
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git status --porcelain",
                workdir="/workspace"
            )
            
            return exit_code == 0, output.strip()
            
        except Exception as e:
            logger.error(f"Error getting git status for {instance_id}: {e}")
            return False, str(e)
    
    def reset_to_clean_state(self, instance_id: str) -> bool:
        """Reset repository to clean state (remove all changes)."""
        try:
            # Reset all changes
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git reset --hard HEAD",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.error(f"Git reset failed for {instance_id}: {output}")
                return False
            
            # Clean untracked files
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git clean -fd",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.warning(f"Git clean warning for {instance_id}: {output}")
            
            logger.info(f"Reset {instance_id} to clean state")
            return True
            
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
            # Get current commit
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git rev-parse HEAD",
                workdir="/workspace"
            )
            if exit_code == 0:
                info['current_commit'] = output.strip()
            
            # Get current branch
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git branch --show-current",
                workdir="/workspace"
            )
            if exit_code == 0:
                info['current_branch'] = output.strip()
            
            # Get repository root
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git rev-parse --show-toplevel",
                workdir="/workspace"
            )
            if exit_code == 0:
                info['repo_root'] = output.strip()
                
            # Get remote origin URL
            exit_code, output = self.containers.exec_command(
                instance_id,
                "git config --get remote.origin.url",
                workdir="/workspace"
            )
            if exit_code == 0:
                info['origin_url'] = output.strip()
                
        except Exception as e:
            logger.error(f"Error getting repository info for {instance_id}: {e}")
        
        return info
    
    def create_patch_from_changes(self, instance_id: str) -> Tuple[bool, str]:
        """Create a patch from current uncommitted changes."""
        try:
            exit_code, patch_content = self.containers.exec_command(
                instance_id,
                "git diff HEAD",
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
    print("Android Repository Manager module loaded successfully")