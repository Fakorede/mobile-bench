#!/usr/bin/env python3
# create_evaluation_prompts.py

"""
Create evaluation prompts from task instances for model evaluation.
"""

import json
import logging
import os
import glob
from argparse import ArgumentParser
from pathlib import Path
from tqdm import tqdm

from create_instance import add_text_inputs, PROMPT_FUNCTIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_jsonl_file(filename):
    """Load task instances from JSONL or JSON files."""
    if type(filename) == str:
        filename = Path(filename)
    if filename.name.endswith(".jsonl") or filename.name.endswith(".jsonl.all"):
        with open(filename) as f:
            return [json.loads(line) for line in f]
    elif filename.name.endswith(".json"):
        with open(filename) as f:
            return json.load(f)
    else:
        raise ValueError(f"Unknown file type {filename}")


def find_input_files(input_path):
    """Find all task instance files to process."""
    input_path = Path(input_path)
    
    if input_path.is_file():
        return [input_path]
    elif input_path.is_dir():
        # Find all task instance files in directory
        patterns = ["*task-instances.jsonl", "*task-instances.jsonl.all", "*.jsonl", "*.json"]
        files = []
        for pattern in patterns:
            files.extend(input_path.glob(pattern))
        return sorted(files)
    else:
        # Try glob pattern
        files = glob.glob(str(input_path))
        return [Path(f) for f in sorted(files)]


def get_output_filename(input_file, output_dir, prompt_style, file_source, smart_selection=False):
    """Generate output filename based on input file and parameters."""
    input_file = Path(input_file)
    base_name = input_file.stem
    
    # Remove common suffixes
    if base_name.endswith("-task-instances"):
        base_name = base_name[:-len("-task-instances")]

    # Remove .jsonl extension if present
    if base_name.endswith(".jsonl"):
        base_name = base_name[:-len(".jsonl")]
    
    # Add parameters to filename
    suffix = "_smart" if smart_selection else ""
    output_name = f"{base_name}_prompts_{prompt_style}_{file_source}{suffix}.jsonl"
    return Path(output_dir) / output_name


def validate_arguments(file_source, max_context_len, tokenizer_name):
    """Validate command line arguments."""
    if max_context_len is not None:
        assert file_source not in {"all", "oracle"}, (
            "Cannot use max_context_len with oracle or all file sources"
        )
        assert tokenizer_name is not None, (
            "Must provide tokenizer_name if max_context_len is not None"
        )


def process_single_file(
    input_file,
    output_file,
    prompt_style,
    file_source,
    retrieval_file=None,
    k=None,
    max_context_len=None,
    tokenizer_name=None,
    enable_smart_selection=True,
    enable_caching=True,
    max_files=20,
    chunk_large_contexts=True,
    cache_dir=None,
):
    """Process a single task instance file."""
    logger.info(f"Processing {input_file}")
    
    # Create output directory if it doesn't exist
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if output already exists
    if output_path.exists():
        logger.info(f"Output file {output_file} already exists, skipping...")
        return
    
    # Load task instances
    try:
        instances_list = load_jsonl_file(input_file)
        instances = {x["instance_id"]: x for x in instances_list}
        logger.info(f"Loaded {len(instances)} task instances from {input_file}")
        
        if len(instances) == 0:
            logger.warning(f"No instances found in {input_file}")
            return
            
    except Exception as e:
        logger.error(f"Failed to load {input_file}: {e}")
        return
    
    # Generate evaluation prompts
    try:
        add_text_inputs(
            instances=instances,
            retrieval_file=retrieval_file,
            k=k,
            prompt_style=prompt_style,
            file_source=file_source,
            max_context_len=max_context_len,
            tokenizer_name=tokenizer_name,
            progress_file=str(output_file),
            enable_smart_selection=enable_smart_selection,
            enable_caching=enable_caching,
            max_files=max_files,
            chunk_large_contexts=chunk_large_contexts,
            cache_dir=cache_dir,
        )
        
        # Count successful prompts
        prompt_count = 0
        failed_count = 0
        
        if os.path.exists(output_file):
            with open(output_file) as f:
                for line in f:
                    instance = json.loads(line)
                    if instance.get("prompt") is not None:
                        prompt_count += 1
                    else:
                        failed_count += 1
        
        logger.info(f"✅ Generated {prompt_count} prompts for {input_file}")
        if failed_count > 0:
            logger.warning(f"⚠️  {failed_count} instances failed for {input_file}")
            
    except Exception as e:
        logger.error(f"❌ Failed to process {input_file}: {e}")


def main(
    input_path,
    output_dir,
    prompt_style,
    file_source,
    retrieval_file=None,
    k=None,
    max_context_len=None,
    tokenizer_name=None,
    enable_smart_selection=True,
    enable_caching=True,
    max_files=20,
    chunk_large_contexts=True,
    cache_dir=None,
):
    """
    Main function to create evaluation prompts from task instances.
    Supports batch processing of multiple files with smart features.
    
    Args:
        input_path: Path to task instances file, directory, or glob pattern
        output_dir: Directory to save evaluation prompts
        prompt_style: Style of prompt to generate
        file_source: Source of files to include (oracle, bm25, all, none)
        retrieval_file: Path to retrieval results (only for bm25)
        k: Max number of files for retrieval (only for bm25)
        max_context_len: Max context length in tokens (only for bm25)
        tokenizer_name: Tokenizer to use for context length (only for bm25)
        enable_smart_selection: Use smart file selection for oracle mode
        enable_caching: Cache processed contexts
        max_files: Maximum number of files to include in oracle mode
        chunk_large_contexts: Split large contexts into chunks
        cache_dir: Directory for caching
    """
    
    # Validate arguments
    validate_arguments(file_source, max_context_len, tokenizer_name)
    
    # Validate prompt style
    if prompt_style not in PROMPT_FUNCTIONS:
        raise ValueError(f"Invalid prompt_style {prompt_style}. Must be one of {list(PROMPT_FUNCTIONS.keys())}")
    
    # Validate file source and retrieval requirements
    if file_source == "bm25" and retrieval_file is None:
        raise ValueError("Must provide retrieval_file when using bm25 file source")
    
    # Find input files
    input_files = find_input_files(input_path)
    if not input_files:
        logger.error(f"No input files found at {input_path}")
        return
    
    logger.info(f"Found {len(input_files)} files to process")
    logger.info(f"Output directory: {output_dir}")
    
    # Log configuration
    if file_source == "oracle":
        logger.info(f"Smart selection: {'enabled' if enable_smart_selection else 'disabled'}")
        logger.info(f"Max files: {max_files}")
        logger.info(f"Chunking: {'enabled' if chunk_large_contexts else 'disabled'}")
    logger.info(f"Caching: {'enabled' if enable_caching else 'disabled'}")
    if cache_dir:
        logger.info(f"Cache directory: {cache_dir}")
    
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Create cache directory if caching enabled
    if enable_caching and cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
    
    # Process each file
    total_prompts = 0
    successful_files = 0
    
    for input_file in tqdm(input_files, desc="Processing files"):
        output_file = get_output_filename(
            input_file, output_dir, prompt_style, file_source, enable_smart_selection
        )
        
        try:
            process_single_file(
                input_file=input_file,
                output_file=output_file,
                prompt_style=prompt_style,
                file_source=file_source,
                retrieval_file=retrieval_file,
                k=k,
                max_context_len=max_context_len,
                tokenizer_name=tokenizer_name,
                enable_smart_selection=enable_smart_selection,
                enable_caching=enable_caching,
                max_files=max_files,
                chunk_large_contexts=chunk_large_contexts,
                cache_dir=cache_dir,
            )
            
            # Count prompts in this file
            if os.path.exists(output_file):
                with open(output_file) as f:
                    file_prompts = sum(1 for line in f if json.loads(line).get("prompt"))
                    total_prompts += file_prompts
                    successful_files += 1
                    
        except Exception as e:
            logger.error(f"Failed to process {input_file}: {e}")
    
    logger.info(f"✅ Batch processing complete!")
    logger.info(f"📁 Processed {successful_files}/{len(input_files)} files successfully")
    logger.info(f"📝 Generated {total_prompts} total evaluation prompts")
    logger.info(f"💾 Results saved to {output_dir}")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    
    # Required arguments
    parser.add_argument(
        "input_path",
        type=str,
        help="Path to task instances file, directory, or glob pattern (e.g., 'data/tasks/*.jsonl')"
    )
    parser.add_argument(
        "output_dir", 
        type=str,
        help="Directory to save evaluation prompts"
    )
    
    # Prompt configuration
    parser.add_argument(
        "--prompt_style",
        type=str,
        default="style-3",
        choices=list(PROMPT_FUNCTIONS.keys()),
        help="Prompt style to use for generating evaluation prompts"
    )
    parser.add_argument(
        "--file_source",
        type=str,
        default="oracle",
        choices=["oracle", "bm25", "all", "none"],
        help="Source of files to include in prompts"
    )
    
    # Retrieval arguments (for bm25 only)
    parser.add_argument(
        "--retrieval_file",
        type=str,
        default=None,
        help="Path to retrieval results file (required for bm25 file_source)"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help="Maximum number of files to include from retrieval results"
    )
    
    # Context limiting arguments (for bm25 only)
    parser.add_argument(
        "--max_context_len",
        type=int,
        default=None,
        help="Maximum context length in tokens (only for bm25 file_source)"
    )
    parser.add_argument(
        "--tokenizer_name",
        type=str,
        default=None,
        choices=["gpt4", "llama", "claude"],  # Add available tokenizers
        help="Tokenizer to use for context length counting"
    )
    
    # Smart features for oracle mode
    parser.add_argument(
        "--enable_smart_selection",
        action="store_true",
        default=True,
        help="Enable smart file selection for oracle mode (default: True)"
    )
    parser.add_argument(
        "--disable_smart_selection",
        action="store_true",
        help="Disable smart file selection for oracle mode"
    )
    parser.add_argument(
        "--max_files",
        type=int,
        default=20,
        help="Maximum number of files to include in oracle mode (default: 20)"
    )
    
    # Caching
    parser.add_argument(
        "--enable_caching",
        action="store_true",
        default=True,
        help="Enable caching of processed contexts (default: True)"
    )
    parser.add_argument(
        "--disable_caching",
        action="store_true",
        help="Disable caching of processed contexts"
    )
    parser.add_argument(
        "--cache_dir",
        type=str,
        default="cache/contexts",
        help="Directory for caching processed contexts (default: cache/contexts)"
    )
    
    # Chunking
    parser.add_argument(
        "--chunk_large_contexts",
        action="store_true",
        default=True,
        help="Enable chunking of large contexts (default: True)"
    )
    parser.add_argument(
        "--disable_chunking",
        action="store_true",
        help="Disable chunking of large contexts"
    )
    
    args = parser.parse_args()
    
    # Handle disable flags
    if args.disable_smart_selection:
        args.enable_smart_selection = False
    if args.disable_caching:
        args.enable_caching = False
    if args.disable_chunking:
        args.chunk_large_contexts = False
    
    # Remove disable flags from args
    delattr(args, 'disable_smart_selection')
    delattr(args, 'disable_caching') 
    delattr(args, 'disable_chunking')
    
    main(**vars(args))