#!/usr/bin/env python3
"""
Git repository management for Android-bench evaluation.
"""

import os
import tempfile
import shutil
import logging
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class AndroidRepositoryManager:
    """Manages Git repositories for Android-bench evaluation."""
    
    def __init__(self, workspace_dir: Optional[str] = None):
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir)
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.workspace_dir = Path(tempfile.mkdtemp(prefix="android_bench_repos_"))
        
        self.repositories = {}  # instance_id -> repo_path mapping
        
        logger.info(f"Repository workspace: {self.workspace_dir}")
    
    def clone_repository(self, instance_id: str, repo_name: str, base_commit: str) -> Optional[str]:
        """
        Clone repository for a specific instance.
        
        Args:
            instance_id: Unique instance identifier
            repo_name: Repository name in format "owner/repo"
            base_commit: Base commit to checkout
            
        Returns:
            Path to cloned repository or None if failed
        """
        try:
            # Create instance-specific directory
            instance_dir = self.workspace_dir / instance_id
            if instance_dir.exists():
                shutil.rmtree(instance_dir)
            instance_dir.mkdir(parents=True)
            
            # Clone URL
            clone_url = f"https://github.com/{repo_name}.git"
            repo_path = instance_dir / "repo"
            
            logger.info(f"Cloning {clone_url} to {repo_path}")
            
            # Configure git for the environment
            git_commands = [
                "git config --global safe.directory '*'",
                "git config --global user.email 'android-bench@example.com'",
                "git config --global user.name 'Android Bench Evaluator'",
                "git config --global init.defaultBranch main"
            ]
            
            for cmd in git_commands:
                exit_code = os.system(cmd)
                if exit_code != 0:
                    logger.warning(f"Git config command failed: {cmd}")
            
            # Clone with specific depth
            clone_cmd = f"git clone --depth 100 {clone_url} {repo_path}"
            exit_code = os.system(clone_cmd)
            
            if exit_code != 0:
                logger.error(f"Failed to clone repository: {repo_name}")
                return None
            
            # Change to repo directory and fetch more history if needed
            original_dir = os.getcwd()
            try:
                os.chdir(repo_path)
                
                # Try to checkout the base commit
                checkout_cmd = f"git checkout {base_commit}"
                exit_code = os.system(checkout_cmd)
                
                if exit_code != 0:
                    # If shallow clone doesn't have the commit, fetch more
                    logger.info(f"Base commit not found in shallow clone, fetching more history")
                    fetch_cmd = "git fetch --unshallow"
                    fetch_exit = os.system(fetch_cmd)
                    
                    if fetch_exit != 0:
                        # Try regular fetch
                        os.system("git fetch origin")
                    
                    # Try checkout again
                    exit_code = os.system(checkout_cmd)
                    
                    if exit_code != 0:
                        logger.error(f"Failed to checkout base commit {base_commit}")
                        return None
                
                # Verify the checkout
                verify_cmd = "git rev-parse HEAD"
                current_commit = os.popen(verify_cmd).read().strip()
                
                if not current_commit.startswith(base_commit):
                    logger.error(f"Checkout verification failed. Expected: {base_commit}, Got: {current_commit}")
                    return None
                
                logger.info(f"Successfully cloned and checked out {base_commit}")
                
                # Set proper permissions
                os.system(f"chmod -R 755 {repo_path}")
                
                self.repositories[instance_id] = str(repo_path)
                return str(repo_path)
                
            finally:
                os.chdir(original_dir)
                
        except Exception as e:
            logger.error(f"Error cloning repository {repo_name}: {e}")
            return None
    
    def get_repository_path(self, instance_id: str) -> Optional[str]:
        """Get the path to a cloned repository."""
        return self.repositories.get(instance_id)
    
    def cleanup_repository(self, instance_id: str):
        """Clean up repository for a specific instance."""
        repo_path = self.repositories.get(instance_id)
        if repo_path and os.path.exists(repo_path):
            try:
                # Remove the entire instance directory
                instance_dir = Path(repo_path).parent
                shutil.rmtree(instance_dir)
                logger.info(f"Cleaned up repository for {instance_id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup repository for {instance_id}: {e}")
        
        # Remove from tracking
        if instance_id in self.repositories:
            del self.repositories[instance_id]
    
    def cleanup_all(self):
        """Clean up all repositories."""
        instance_ids = list(self.repositories.keys())
        for instance_id in instance_ids:
            self.cleanup_repository(instance_id)
        
        # Clean up workspace directory if it's temporary
        try:
            if self.workspace_dir.exists():
                shutil.rmtree(self.workspace_dir)
                logger.info("Cleaned up repository workspace")
        except Exception as e:
            logger.warning(f"Failed to cleanup workspace directory: {e}")
    
    def get_repository_info(self, instance_id: str) -> dict:
        """Get information about a repository."""
        repo_path = self.repositories.get(instance_id)
        if not repo_path or not os.path.exists(repo_path):
            return {}
        
        info = {}
        original_dir = os.getcwd()
        
        try:
            os.chdir(repo_path)
            
            # Get current commit
            current_commit = os.popen("git rev-parse HEAD").read().strip()
            if current_commit:
                info['current_commit'] = current_commit
            
            # Get current branch
            current_branch = os.popen("git branch --show-current").read().strip()
            if current_branch:
                info['current_branch'] = current_branch
            
            # Get remote origin URL
            origin_url = os.popen("git config --get remote.origin.url").read().strip()
            if origin_url:
                info['origin_url'] = origin_url
            
            # Get repository status
            status = os.popen("git status --porcelain").read().strip()
            info['has_changes'] = bool(status)
            
        except Exception as e:
            logger.error(f"Error getting repository info for {instance_id}: {e}")
        finally:
            os.chdir(original_dir)
        
        return info
    
    def validate_repository(self, instance_id: str) -> bool:
        """Validate that repository is properly set up."""
        repo_path = self.repositories.get(instance_id)
        if not repo_path or not os.path.exists(repo_path):
            return False
        
        # Check if it's a git repository
        git_dir = Path(repo_path) / ".git"
        if not git_dir.exists():
            return False
        
        # Check if we can get repository status
        original_dir = os.getcwd()
        try:
            os.chdir(repo_path)
            exit_code = os.system("git status > /dev/null 2>&1")
            return exit_code == 0
        except Exception:
            return False
        finally:
            os.chdir(original_dir)


def create_repository_manager(workspace_dir: Optional[str] = None) -> AndroidRepositoryManager:
    """
    Create a repository manager instance.
    
    Args:
        workspace_dir: Optional workspace directory for repositories
        
    Returns:
        AndroidRepositoryManager instance
    """
    return AndroidRepositoryManager(workspace_dir)


if __name__ == "__main__":
    # Test the repository manager
    logging.basicConfig(level=logging.INFO)
    
    repo_manager = create_repository_manager()
    
    try:
        # Test cloning a small repository
        test_repo = "octocat/Hello-World"
        test_commit = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"  # Known commit
        
        repo_path = repo_manager.clone_repository("test_instance", test_repo, test_commit)
        
        if repo_path:
            print(f"Successfully cloned repository to: {repo_path}")
            
            # Get repository info
            info = repo_manager.get_repository_info("test_instance")
            print(f"Repository info: {info}")
            
            # Validate repository
            is_valid = repo_manager.validate_repository("test_instance")
            print(f"Repository is valid: {is_valid}")
        else:
            print("Failed to clone repository")
            
    finally:
        repo_manager.cleanup_all()