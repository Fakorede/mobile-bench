#!/usr/bin/env python3

"""
Tokenizer functions for different model families to enforce max_context_len limits.
Supports GPT models, Claude models (with safety margin), and Gemini models.
"""

import tiktoken
from transformers import AutoTokenizer
import logging

logger = logging.getLogger(__name__)


def cl100k_gpt(text, tokenizer):
    """Tokenizer function for GPT models using cl100k_base encoding."""
    return tokenizer.encode(text, disallowed_special=())


def cl100k_claude_safe(text, tokenizer):
    """
    Tokenizer function for Claude models using cl100k_base as approximation
    with 20% safety margin to account for tokenizer differences.
    """
    tokens = tokenizer.encode(text, disallowed_special=())
    # Add 20% safety margin for Claude tokenizer differences
    safety_margin = int(len(tokens) * 0.2)
    # Return tokens with safety margin added to length estimation
    return tokens + [0] * safety_margin


def sentencepiece_gemini(text, tokenizer):
    """Tokenizer function for Gemini models using SentencePiece tokenizer."""
    try:
        # Try the standard HuggingFace tokenizer interface
        if hasattr(tokenizer, 'encode'):
            return tokenizer.encode(text, add_special_tokens=False)
        else:
            # Fallback to tokenizer call
            result = tokenizer(text, add_special_tokens=False, return_attention_mask=False)
            return result["input_ids"]
    except Exception as e:
        logger.warning(f"SentencePiece tokenization failed, using fallback: {e}")
        # Fallback to simple word-based estimation (very rough)
        return text.split()


def simple_word_tokenizer(text, tokenizer=None):
    """
    Simple word-based tokenizer as ultimate fallback.
    Estimates ~1.3 tokens per word (typical for English).
    """
    words = text.split()
    # Rough estimation: 1.3 tokens per word for English
    estimated_tokens = [0] * int(len(words) * 1.3)
    return estimated_tokens


# Initialize tokenizers with error handling
def _init_tokenizers():
    """Initialize all tokenizers with proper error handling."""
    tokenizers = {}
    
    # GPT tokenizer (cl100k_base)
    try:
        gpt_tokenizer = tiktoken.get_encoding("cl100k_base")
        tokenizers["gpt"] = (gpt_tokenizer, cl100k_gpt)
        logger.info("Initialized GPT tokenizer (cl100k_base)")
    except Exception as e:
        logger.error(f"Failed to initialize GPT tokenizer: {e}")
    
    # Claude tokenizer (cl100k_base with safety margin)
    try:
        claude_tokenizer = tiktoken.get_encoding("cl100k_base")
        tokenizers["claude"] = (claude_tokenizer, cl100k_claude_safe)
        logger.info("Initialized Claude tokenizer (cl100k_base with safety margin)")
    except Exception as e:
        logger.error(f"Failed to initialize Claude tokenizer: {e}")
    
    # Gemini tokenizer (try multiple approaches)
    gemini_initialized = False
    
    # First try: publicly available SentencePiece models
    public_sp_models = [
        "t5-small",                   # T5 uses SentencePiece
        "facebook/bart-base",         # BART tokenizer
    ]
    
    for model_name in public_sp_models:
        try:
            gemini_tokenizer = AutoTokenizer.from_pretrained(model_name)
            tokenizers["gemini"] = (gemini_tokenizer, sentencepiece_gemini)
            logger.info(f"Initialized Gemini tokenizer using {model_name}")
            gemini_initialized = True
            break
        except Exception as e:
            logger.debug(f"Failed to load {model_name}: {e}")
            continue
    
    # Second try: use cl100k_base as reasonable approximation
    if not gemini_initialized:
        try:
            gemini_fallback_tokenizer = tiktoken.get_encoding("cl100k_base")
            tokenizers["gemini"] = (gemini_fallback_tokenizer, cl100k_gpt)
            logger.info("Using cl100k_base as approximation for Gemini tokenizer")
            gemini_initialized = True
        except Exception as e:
            logger.debug(f"cl100k_base fallback failed: {e}")
    
    # Final fallback: simple word-based estimation
    if not gemini_initialized:
        tokenizers["gemini"] = (None, simple_word_tokenizer)
        logger.warning("Using simple word-based tokenizer as final fallback for Gemini")
    
    return tokenizers


# Initialize tokenizers
TOKENIZER_FUNCS = _init_tokenizers()


def get_token_count(text, model_family="gpt"):
    """
    Get token count for text using specified model family tokenizer.
    
    Args:
        text (str): Text to tokenize
        model_family (str): One of 'gpt', 'claude', 'gemini'
    
    Returns:
        int: Number of tokens
    """
    if model_family not in TOKENIZER_FUNCS:
        raise ValueError(f"Unsupported model family: {model_family}. Available: {list(TOKENIZER_FUNCS.keys())}")
    
    tokenizer, tokenizer_func = TOKENIZER_FUNCS[model_family]
    tokens = tokenizer_func(text, tokenizer)
    return len(tokens)


def check_context_limit(text, max_tokens, model_family="gpt"):
    """
    Check if text exceeds context limit for specified model family.
    
    Args:
        text (str): Text to check
        max_tokens (int): Maximum allowed tokens
        model_family (str): One of 'gpt', 'claude', 'gemini'
    
    Returns:
        tuple: (bool, int) - (within_limit, actual_token_count)
    """
    token_count = get_token_count(text, model_family)
    within_limit = token_count <= max_tokens
    return within_limit, token_count


# Mapping for common model names to families
MODEL_NAME_TO_FAMILY = {
    # GPT models
    "gpt-4o-mini": "gpt",
    "gpt-4o": "gpt", 
    
    # Claude models
    "claude-3.7-sonnet": "claude",
    "claude-sonnet-4": "claude",
    
    # Gemini models
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
}


def get_model_family(model_name):
    """
    Get model family from model name.
    
    Args:
        model_name (str): Full model name
        
    Returns:
        str: Model family ('gpt', 'claude', 'gemini')
    """
    model_name_lower = model_name.lower()
    
    for name_pattern, family in MODEL_NAME_TO_FAMILY.items():
        if name_pattern in model_name_lower:
            return family


if __name__ == "__main__":
    # Test the tokenizers
    test_text = "Hello, this is a test message for tokenization across different model families."
    
    print("Testing tokenizers:")
    for family in TOKENIZER_FUNCS.keys():
        try:
            token_count = get_token_count(test_text, family)
            print(f"{family.upper()}: {token_count} tokens")
        except Exception as e:
            print(f"{family.upper()}: Error - {e}")
    
    print(f"\nTest text: '{test_text}'")
    
    # Test model name mapping
    test_models = ["gpt-4o", "claude-sonnet-4", "gemini-2.5-flash"]
    print(f"\nModel family mapping:")
    for model in test_models:
        family = get_model_family(model)
        print(f"{model} -> {family}")