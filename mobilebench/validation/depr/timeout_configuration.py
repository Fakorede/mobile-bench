#!/usr/bin/env python3
"""
Timeout configuration for Android validation.
Modify these values to increase timeouts.
"""

class TimeoutConfig:
    """Centralized timeout configuration."""
    
    # Container command timeouts (seconds)
    CONTAINER_COMMAND_DEFAULT = 600       # 10 minutes (was 300)
    CONTAINER_SETUP = 180                 # 3 minutes
    SDK_INSTALL = 300                     # 5 minutes per component
    
    # Test execution timeouts (seconds)  
    TEST_EXECUTION_TOTAL = 2400          # 40 minutes (was 1200 = 20 min)
    INDIVIDUAL_GRADLE_TASK = 1200        # 20 minutes (was 600 = 10 min)
    DEPENDENCY_DOWNLOAD = 600            # 10 minutes
    
    # Git operation timeouts (seconds)
    GIT_CLONE = 900                      # 15 minutes (was 600)
    GIT_CHECKOUT = 300                   # 5 minutes
    PATCH_APPLICATION = 180              # 3 minutes
    
    # Docker operation timeouts (seconds)
    DOCKER_PULL = 900                    # 15 minutes
    DOCKER_BUILD = 1800                  # 30 minutes
    
    @classmethod
    def get_test_timeout_for_project_size(cls, is_large_project: bool = False) -> int:
        """Get appropriate test timeout based on project size."""
        if is_large_project:
            return cls.TEST_EXECUTION_TOTAL * 2  # 80 minutes for large projects
        return cls.TEST_EXECUTION_TOTAL
    
    @classmethod
    def get_gradle_timeout_for_task_count(cls, task_count: int) -> int:
        """Get gradle timeout based on number of test tasks."""
        base_timeout = cls.INDIVIDUAL_GRADLE_TASK
        # Add extra time for multiple tasks
        return base_timeout + (task_count * 300)  # +5 minutes per additional task
