#!/usr/bin/env python3
"""
Test script for patch-based stub generation integration.

This script demonstrates how to use the new patch-based stub generation
in the validation module.
"""

import os
import sys
import logging
import asyncio
from pathlib import Path

# Add the validation module to the path
sys.path.insert(0, str(Path(__file__).parent))

from patch_based_stub_integration import generate_and_apply_patches, enable_patch_based_stubs_globally


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_patch_based_integration():
    """Test the patch-based stub generation integration."""
    
    logger.info("Testing patch-based stub generation integration")
    
    # Enable patch-based stubs globally
    enable_patch_based_stubs_globally()
    
    # Mock containers manager for testing
    class MockContainersManager:
        def exec_command(self, instance_id, command, workdir=None, timeout=30):
            logger.info(f"Mock exec_command: {command}")
            return 0, "mock output"
    
    # Test parameters
    containers_manager = MockContainersManager()
    instance_id = "test_instance"
    build_log = """
    error: cannot find symbol
      symbol:   class PrivacySettings
      location: package net.thunderbird.core.preference.privacy
    """
    test_patch = "mock test patch"
    solution_patch = "mock solution patch"
    api_key = "mock_api_key"
    
    # Test the integration
    try:
        result = await generate_and_apply_patches(
            containers_manager=containers_manager,
            instance_id=instance_id,
            build_log=build_log,
            test_patch=test_patch,
            solution_patch=solution_patch,
            api_key=api_key
        )
        
        logger.info(f"Test result: success={result.success}")
        if not result.success:
            logger.info(f"Error: {result.error_message}")
        
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")


def show_integration_status():
    """Show the current integration status."""
    
    logger.info("=== Patch-Based Stub Generation Integration Status ===")
    
    # Check if files exist
    integration_file = Path(__file__).parent / "patch_based_stub_integration.py"
    patch_generator_file = Path(__file__).parent / "patch_based_stub_generator.py"
    
    logger.info(f"Integration file exists: {integration_file.exists()}")
    logger.info(f"Patch generator file exists: {patch_generator_file.exists()}")
    
    # Check environment variables
    stub_method = os.getenv('STUB_GENERATION_METHOD', 'patch_based')
    logger.info(f"Current stub generation method: {stub_method}")
    
    # Check OpenRouter API key
    api_key = os.getenv('OPENROUTER_API_KEY')
    logger.info(f"OpenRouter API key configured: {'Yes' if api_key else 'No'}")
    
    logger.info("=== Integration Ready ===")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        show_integration_status()
    else:
        asyncio.run(test_patch_based_integration())
