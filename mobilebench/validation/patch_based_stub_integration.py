#!/usr/bin/env python3
"""
Patch-based stub generator integration for validation module.

This module provides a drop-in replacement for the existing stub generation system
using a Git patch-based approach instead of complex file merging.
"""

import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from patch_based_stub_generator import PatchBasedStubGenerator
from stub_generator_utils import StubGenerationResult

logger = logging.getLogger(__name__)


async def generate_and_apply_patches(containers_manager, instance_id: str, 
                                   build_log: str, test_patch: str, 
                                   solution_patch: str, api_key: str,
                                   model: str = "anthropic/claude-3.7-sonnet",
                                   base_output_dir: str = "validation_results",
                                   gradle_command: str = None) -> StubGenerationResult:
    """
    Complete patch-based stub generation and application workflow.
    
    This is a drop-in replacement for generate_and_apply_stubs() that uses
    the patch-based approach instead of complex file merging.
    
    Args:
        containers_manager: Container manager instance
        instance_id: Instance ID
        build_log: Build log with compilation errors
        test_patch: Applied test patch
        solution_patch: Solution patch for oracle files
        api_key: OpenRouter API key
        model: LLM model to use
        base_output_dir: Base directory for organizing results
        
    Returns:
        StubGenerationResult with all metadata
    """
    logger.info(f"Starting patch-based stub generation for {instance_id}")
    start_time = time.time()
    
    try:
        # Initialize patch-based generator
        generator = PatchBasedStubGenerator(
            containers_manager=containers_manager,
            api_key=api_key,
            model=model,
            base_output_dir=base_output_dir
        )
        
        # Extract oracle files for context
        oracle_files = extract_oracle_files(containers_manager, instance_id, solution_patch)
        logger.info(f"Extracted {len(oracle_files)} oracle files for context")
        
        # Generate and apply patches
        result = await generator.generate_and_apply_patches(
            instance_id=instance_id,
            build_log=build_log,
            test_patch=test_patch,
            oracle_files=oracle_files,
            gradle_command=gradle_command
        )
        
        # Add timing information
        result.response_time = time.time() - start_time
        
        if result.success:
            logger.info(f"Patch-based stub generation successful for {instance_id}: "
                       f"{len(result.files_created)} files modified, "
                       f"cost=${result.api_cost:.4f}, time={result.response_time:.1f}s")
        else:
            logger.warning(f"Patch-based stub generation failed for {instance_id}: {result.error_message}")
        
        return result
        
    except Exception as e:
        response_time = time.time() - start_time
        logger.error(f"Error in patch-based stub generation for {instance_id}: {e}")
        
        return StubGenerationResult(
            success=False,
            generated_stubs="",
            files_created={},
            oracle_files={},
            error_message=str(e),
            response_time=response_time,
            model_used=model
        )


def extract_oracle_files(containers_manager, instance_id: str, solution_patch: str) -> Dict[str, str]:
    """
    Extract and read the content of files that will be modified in solution patch.
    
    Args:
        containers_manager: Container manager for file operations
        instance_id: Instance ID for container execution
        solution_patch: The solution patch content
        
    Returns:
        Dictionary mapping file paths to their current content
    """
    import re
    
    oracle_files = {}
    
    if not solution_patch:
        return oracle_files
    
    try:
        # Extract file paths from solution patch
        file_patterns = [
            r'\+\+\+ b/(.+\.(?:java|kt))',
            r'diff --git a/.+ b/(.+\.(?:java|kt))'
        ]
        
        modified_files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, solution_patch)
            modified_files.update(matches)
        
        logger.info(f"Found {len(modified_files)} oracle files to read")
        
        # Read content of these files from the current workspace
        for file_path in modified_files:
            try:
                read_command = f"cd /workspace && cat {file_path} 2>/dev/null || echo 'FILE_NOT_FOUND'"
                exit_code, content = containers_manager.exec_command(
                    instance_id, read_command, workdir="/workspace", timeout=30
                )
                
                if exit_code == 0 and content != "FILE_NOT_FOUND":
                    oracle_files[file_path] = content
                    logger.debug(f"Read oracle file: {file_path} ({len(content)} chars)")
                else:
                    logger.debug(f"Oracle file not found or empty: {file_path}")
                    
            except Exception as e:
                logger.warning(f"Error reading oracle file {file_path}: {e}")
        
    except Exception as e:
        logger.error(f"Error extracting oracle files: {e}")
    
    return oracle_files


class PatchBasedStubValidatorMixin:
    """
    Mixin class that can be added to existing validators to enable patch-based stub generation.
    
    This provides the same interface as the existing stub generation but uses patches internally.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._use_patch_based_stubs = True  # Flag to enable patch-based approach
    
    async def generate_stubs_patch_based(self, instance_id: str, build_log: str, 
                                       test_patch: str, solution_patch: str, 
                                       api_key: str, model: str = "anthropic/claude-3.7-sonnet") -> StubGenerationResult:
        """
        Generate stubs using patch-based approach.
        
        This method can be called instead of the existing stub generation methods.
        """
        return await generate_and_apply_patches(
            containers_manager=self.containers,  # Assuming containers attribute exists
            instance_id=instance_id,
            build_log=build_log,
            test_patch=test_patch,
            solution_patch=solution_patch,
            api_key=api_key,
            model=model,
            base_output_dir=getattr(self, 'output_dir', 'validation_results')
        )


def monkey_patch_existing_stub_generator():
    """
    Monkey patch the existing stub generator to use patch-based approach.
    
    Call this function at the start of your validation script to replace
    the existing stub generation with patch-based approach.
    """
    try:
        # Import the existing module
        import stub_generator_utils
        
        # Replace the main function with our patch-based version
        stub_generator_utils.generate_and_apply_stubs = generate_and_apply_patches
        
        logger.info("Successfully monkey patched stub generator to use patch-based approach")
        return True
        
    except ImportError as e:
        logger.warning(f"Could not monkey patch stub generator: {e}")
        return False


def enable_patch_based_stubs_globally():
    """
    Enable patch-based stub generation globally for the validation module.
    
    This function should be called before any validation operations to ensure
    the patch-based approach is used instead of the existing file merging approach.
    """
    success = monkey_patch_existing_stub_generator()
    
    if success:
        logger.info("Patch-based stub generation enabled globally")
    else:
        logger.warning("Failed to enable patch-based stub generation globally")
    
    return success
