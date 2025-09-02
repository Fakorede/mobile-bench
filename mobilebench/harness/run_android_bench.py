#!/usr/bin/env python3
"""
Main runner script for Android-bench evaluation.
"""

import sys
import logging
from pathlib import Path

# Add current directory to path for module imports
sys.path.insert(0, str(Path(__file__).parent))

from evaluator import AndroidBenchEvaluator, main as evaluator_main


def main():
    """Main entry point - delegates to evaluator main."""
    return evaluator_main()


if __name__ == "__main__":
    exit(main())