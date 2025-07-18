#!/usr/bin/env python3
"""
Enhanced Mobile Bench Inference Script

This script uses OpenRouter API to prompt multiple language models 
with mobile bench smart oracle retrieval for Android projects.
Enhanced with SWE-bench features: cost tracking, progress resumption, 
retry logic, dataset filtering, and sharding support.

Usage:
    python run_completion.py --input data.jsonl --output results.jsonl
    python run_completion.py --input data.jsonl --output results.jsonl --max-cost 50.0
    python run_completion.py --input data.jsonl --output results.jsonl --shard-id 0 --num-shards 4
"""

import json
import asyncio
import aiohttp
import argparse
import logging
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, asdict
from pathlib import Path
import time
import os
from datetime import datetime
from tqdm.asyncio import tqdm
import numpy as np
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type
)
import dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
dotenv.load_dotenv()

# Model limits (context windows)
MODEL_LIMITS = {
    "anthropic/claude-3.7-sonnet": 200_000,
    "anthropic/claude-4-sonnet-20250522": 200_000,
    "anthropic/claude-4-opus-20250522": 200_000,
    "deepseek/deepseek-chat-v3-0324": 163_840,
    "deepseek/deepseek-r1-0528:free": 163_840,
    "openai/gpt-4.1-2025-04-14": 1_047_576,
    "openai/gpt-4o-2024-08-06": 128_000,
    "openai/gpt-4o-mini-2024-07-18": 128_000,
    "google/gemini-2.5-pro": 1_048_576,
    "google/gemini-2.5-flash": 1_048_576,
}

# Cost per token for input (estimates based on OpenRouter pricing)
MODEL_COST_PER_INPUT = {
    "anthropic/claude-3.7-sonnet": 0.000003,
    "anthropic/claude-4-sonnet-20250522": 0.000015,
    "anthropic/claude-4-opus-20250522": 0.000075,
    "deepseek/deepseek-chat-v3-0324": 0.0000014,
    "deepseek/deepseek-r1-0528:free": 0.0,  # Free tier
    "openai/gpt-4.1-2025-04-14": 0.00003,
    "openai/gpt-4o-2024-08-06": 0.0000025,
    "openai/gpt-4o-mini-2024-07-18": 0.00000015,
    "google/gemini-2.5-pro": 0.00000125,
    "google/gemini-2.5-flash": 0.0000003,
}

# Cost per token for output
MODEL_COST_PER_OUTPUT = {
    "anthropic/claude-3.7-sonnet": 0.000015,
    "anthropic/claude-4-sonnet-20250522": 0.000075,
    "anthropic/claude-4-opus-20250522": 0.000375,
    "deepseek/deepseek-chat-v3-0324": 0.0000028,
    "deepseek/deepseek-r1-0528:free": 0.0,  # Free tier
    "openai/gpt-4.1-2025-04-14": 0.00012,
    "openai/gpt-4o-2024-08-06": 0.00001,
    "openai/gpt-4o-mini-2024-07-18": 0.0000006,
    "google/gemini-2.5-pro": 0.00001,
    "google/gemini-2.5-flash": 0.0000025,
}

@dataclass
class ModelConfig:
    """Configuration for each model"""
    name: str
    api_name: str
    max_tokens: int
    temperature: float = 0.0
    top_p: float = 1.0
    
    @classmethod
    def create_with_overrides(cls, name: str, api_name: str, base_max_tokens: int, 
                            temperature_override: Optional[float] = None,
                            max_tokens_override: Optional[int] = None,
                            top_p_override: Optional[float] = None) -> 'ModelConfig':
        """Create model config with optional overrides"""
        return cls(
            name=name,
            api_name=api_name,
            max_tokens=max_tokens_override or base_max_tokens,
            temperature=temperature_override if temperature_override is not None else 0.0,
            top_p=top_p_override if top_p_override is not None else 1.0
        )

@dataclass
class InferenceResult:
    """Result from model inference"""
    instance_id: str
    model_name: str
    model_name_or_path: str
    generated_patch: str
    full_output: str  # Store complete response
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time: float
    cost: float
    base_commit: Optional[str] = None  # Store base_commit from input
    error: Optional[str] = None
    timestamp: str = None
    prompt: str = ""

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

def calc_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost of API call"""
    if model_name not in MODEL_COST_PER_INPUT:
        logger.warning(f"Unknown model for cost calculation: {model_name}")
        return 0.0
    
    cost = (
        MODEL_COST_PER_INPUT[model_name] * input_tokens
        + MODEL_COST_PER_OUTPUT[model_name] * output_tokens
    )
    logger.info(f"input_tokens={input_tokens}, output_tokens={output_tokens}, cost=${cost:.4f}")
    return cost

def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token average) - fallback only"""
    return len(text) // 4

def gpt_tokenize(text: str, model_name: str) -> int:
    """Accurate GPT tokenization using tiktoken"""
    try:
        # Only try to import if tiktoken is available
        import tiktoken
        
        # Map OpenRouter model names to tiktoken model names
        tiktoken_models = {
            "openai/gpt-4o-2024-08-06": "gpt-4o",
            "openai/gpt-4o-mini-2024-07-18": "gpt-4o-mini", 
            "openai/gpt-4.1-2025-04-14": "gpt-4o",  # Use gpt-4o as fallback
        }
        
        tiktoken_model = tiktoken_models.get(model_name, "gpt-4o")  # Default to gpt-4o
        encoding = tiktoken.encoding_for_model(tiktoken_model)
        return len(encoding.encode(text))
    except ImportError:
        logger.warning("tiktoken package not installed, using estimation for GPT tokenization")
        return estimate_tokens(text)
    except Exception as e:
        logger.warning(f"Failed to tokenize with tiktoken for {model_name}: {e}, using estimate")
        return estimate_tokens(text)

async def claude_tokenize(text: str, api_key: str) -> int:
    """Accurate Claude tokenization using Anthropic API"""
    try:
        # Only try to import if anthropic is available
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        return client.count_tokens(text)
    except ImportError:
        logger.warning("anthropic package not installed, using estimation for Claude tokenization")
        return estimate_tokens(text)
    except Exception as e:
        logger.warning(f"Failed to tokenize with Claude API: {e}, using estimate")
        return estimate_tokens(text)

def get_tokenizer_for_model(model_api_name: str, api_key: str = None):
    """Get appropriate tokenization function for model"""
    if "openai/" in model_api_name:
        return lambda text: gpt_tokenize(text, model_api_name)
    elif "anthropic/" in model_api_name:
        if api_key:
            # Return a synchronous wrapper for Claude tokenization
            def claude_sync_tokenize(text):
                try:
                    from anthropic import Anthropic
                    client = Anthropic(api_key=api_key)
                    return client.count_tokens(text)
                except ImportError:
                    logger.warning("anthropic package not installed, using estimation for Claude tokenization")
                    return estimate_tokens(text)
                except Exception as e:
                    logger.warning(f"Failed to tokenize with Claude API: {e}, using estimate")
                    return estimate_tokens(text)
            return claude_sync_tokenize
        else:
            logger.warning("No API key provided for Claude tokenization, using estimate")
            return estimate_tokens
    elif "deepseek/" in model_api_name:
        # DeepSeek uses similar tokenization to GPT, use rough estimate
        return estimate_tokens
    else:
        return estimate_tokens

def parse_model_args(model_args: str) -> Dict[str, Any]:
    """Parse model arguments string into dictionary"""
    kwargs = dict()
    if model_args is not None:
        for arg in model_args.split(","):
            if "=" not in arg:
                continue
            key, value = arg.split("=", 1)
            # infer value type
            if value in {"True", "False"}:
                kwargs[key] = value == "True"
            elif value.isnumeric():
                kwargs[key] = int(value)
            elif value.replace(".", "", 1).isnumeric():
                kwargs[key] = float(value)
            elif value in {"None"}:
                kwargs[key] = None
            elif value in {"[]"}:
                kwargs[key] = []
            elif value in {"{}"}:
                kwargs[key] = {}
            elif value.startswith("'") and value.endswith("'"):
                kwargs[key] = value[1:-1]
            elif value.startswith('"') and value.endswith('"'):
                kwargs[key] = value[1:-1]
            else:
                kwargs[key] = value
    return kwargs

class OpenRouterClient:
    """Client for OpenRouter API with retry logic and cost tracking"""
    
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1",
                 temperature: Optional[float] = None, max_tokens_override: Optional[int] = None,
                 top_p: Optional[float] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
        self.temperature_override = temperature
        self.max_tokens_override = max_tokens_override
        self.top_p_override = top_p
        
        # Model configurations
        base_configs = {
            "claude-sonnet-3.7": ("Claude Sonnet 3.7", "anthropic/claude-3.7-sonnet", 8192),
            "claude-sonnet-4": ("Claude Sonnet 4", "anthropic/claude-4-sonnet-20250522", 8192),
            "claude-opus-4": ("Claude Opus 4", "anthropic/claude-4-opus-20250522", 8192),  
            "deepseek-v3": ("DeepSeek V3", "deepseek/deepseek-chat-v3-0324", 8192),
            "deepseek-r1": ("DeepSeek R1(free)", "deepseek/deepseek-r1-0528:free", 8192),
            "gpt-4.1": ("GPT-4.1", "openai/gpt-4.1-2025-04-14", 4096),
            "gpt-4o": ("GPT-4o", "openai/gpt-4o-2024-08-06", 4096),
            "gpt-4o-mini": ("GPT-4o Mini", "openai/gpt-4o-mini-2024-07-18", 4096),
            "gemini-pro": ("Gemini 2.5 Pro", "google/gemini-2.5-pro", 8192),
            "gemini-flash": ("Gemini 2.5 Flash", "google/gemini-2.5-flash", 8192),
        }
        
        self.models = {}
        for key, (name, api_name, base_max_tokens) in base_configs.items():
            self.models[key] = ModelConfig.create_with_overrides(
                name=name,
                api_name=api_name, 
                base_max_tokens=base_max_tokens,
                temperature_override=temperature,
                max_tokens_override=max_tokens_override,
                top_p_override=top_p
            )
    
    async def __aenter__(self):
        """Async context manager entry"""
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "Mobile Bench Inference"
            },
            timeout=aiohttp.ClientTimeout(total=300),
            connector=connector
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    @retry(
        wait=wait_random_exponential(min=30, max=600), 
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def generate_response(self, model_key: str, prompt: str, instance_id: str = "") -> InferenceResult:
        """Generate response from specified model with retry logic"""
        model_config = self.models[model_key]
        
        # Check token limits with accurate tokenization
        tokenizer_func = get_tokenizer_for_model(model_config.api_name, None)  # Don't pass API key to avoid extra calls
        
        try:
            if "anthropic/" in model_config.api_name:
                # For Claude, use a more conservative estimate to avoid API calls during filtering
                prompt_tokens = estimate_tokens(prompt) * 1.2  # Add 20% buffer for Claude
            else:
                prompt_tokens = tokenizer_func(prompt) if callable(tokenizer_func) else estimate_tokens(prompt)
        except Exception as e:
            logger.warning(f"Tokenization failed for {model_config.name}: {e}, using estimate")
            prompt_tokens = estimate_tokens(prompt)
        max_context = MODEL_LIMITS.get(model_config.api_name, 128_000)
        
        if prompt_tokens > max_context:
            return InferenceResult(
                instance_id=instance_id,
                model_name=model_config.name,
                model_name_or_path=model_config.api_name,
                generated_patch="",
                full_output="",
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                total_tokens=prompt_tokens,
                response_time=0.0,
                cost=0.0,
                base_commit=None,  # Will be set by caller
                error=f"Context length exceeded: {prompt_tokens} > {max_context}",
                prompt=prompt  # Store complete prompt
            )
        
        payload = {
            "model": model_config.api_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": model_config.max_tokens,
            "temperature": model_config.temperature,
            "top_p": model_config.top_p,
            "stream": False
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload
            ) as response:
                response_time = time.time() - start_time
                
                if response.status == 429:  # Rate limit
                    logger.warning(f"Rate limited for {model_config.name}, retrying...")
                    await asyncio.sleep(60)  # Wait 1 minute
                    raise aiohttp.ClientError("Rate limited")
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API request failed for {model_config.name}: {response.status} - {error_text}")
                    return InferenceResult(
                        instance_id=instance_id,
                        model_name=model_config.name,
                        model_name_or_path=model_config.api_name,
                        generated_patch="",
                        full_output="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        response_time=response_time,
                        cost=0.0,
                        base_commit=None,  # Will be set by caller
                        error=f"HTTP {response.status}: {error_text}",
                        prompt=prompt  # Store complete prompt
                    )
                
                data = await response.json()
                
                # Extract response content
                full_output = data["choices"][0]["message"]["content"]
                generated_patch = self.extract_patch(full_output)
                
                # Extract token usage
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", int(prompt_tokens))
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
                
                # Calculate cost
                cost = calc_cost(model_config.api_name, prompt_tokens, completion_tokens)
                
                logger.info(f"✓ {model_config.name} completed in {response_time:.2f}s")
                
                return InferenceResult(
                    instance_id=instance_id,
                    model_name=model_config.name,
                    model_name_or_path=model_config.api_name,
                    generated_patch=generated_patch,
                    full_output=full_output,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    response_time=response_time,
                    cost=cost,
                    base_commit=None,  # Will be set by caller
                    prompt=prompt  # Store complete prompt
                )
                
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"Error with {model_config.name}: {str(e)}")
            return InferenceResult(
                instance_id=instance_id,
                model_name=model_config.name,
                model_name_or_path=model_config.api_name,
                generated_patch="",
                full_output="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_time=response_time,
                cost=0.0,
                base_commit=None,  # Will be set by caller
                error=str(e),
                prompt=prompt  # Store complete prompt
            )
    
    def extract_patch(self, text: str) -> str:
        """Extract patch/diff from model output"""
        # Look for common patch patterns
        lines = text.split('\n')
        patch_lines = []
        in_patch = False
        
        for line in lines:
            # Start of patch indicators
            if any(indicator in line for indicator in ['diff --git', '--- a/', '+++ b/', '@@']):
                in_patch = True
                patch_lines.append(line)
            elif in_patch and (line.startswith('+') or line.startswith('-') or line.startswith(' ') or line.startswith('@@')):
                patch_lines.append(line)
            elif in_patch and line.strip() == '':
                patch_lines.append(line)
            elif in_patch and not line.startswith(('+', '-', ' ', '@')) and line.strip():
                # End of patch
                break
        
        return '\n'.join(patch_lines) if patch_lines else ""

class MobileBenchInference:
    """Main inference class for Mobile Bench with SWE-bench features"""
    
    def __init__(self, api_key: str, temperature: Optional[float] = None, 
                 max_tokens: Optional[int] = None, top_p: Optional[float] = None):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.results = []
    
    def load_data(self, input_path: str) -> List[Dict[str, Any]]:
        """Load mobile bench data from JSONL file"""
        logger.info(f"Loading data from {input_path}")
        
        data = []
        with open(input_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    instance = json.loads(line)
                    data.append(instance)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line {line_num}: {e}")
                    continue
        
        logger.info(f"Loaded {len(data)} instances")
        return data
    
    def filter_by_length(self, instances: List[Dict[str, Any]], models: List[str]) -> List[Dict[str, Any]]:
        """Filter instances by accurate token length limits for each model"""
        logger.info("Filtering instances by accurate token limits...")
        
        # Get the minimum context limit across all selected models
        min_limit = float('inf')
        tokenizer_func = estimate_tokens  # fallback
        
        # Create a temporary model config mapping (without async)
        model_api_mapping = {
            "claude-sonnet-3.7": "anthropic/claude-3.7-sonnet",  
            "claude-sonnet-4": "anthropic/claude-4-sonnet-20250522",
            "claude-opus-4": "anthropic/claude-4-opus-20250522",  
            "deepseek-v3": "deepseek/deepseek-chat-v3-0324",
            "deepseek-r1": "deepseek/deepseek-r1-0528:free",
            "gpt-4.1": "openai/gpt-4.1-2025-04-14",
            "gpt-4o": "openai/gpt-4o-2024-08-06",
            "gpt-4o-mini": "openai/gpt-4o-mini-2024-07-18",     
            "gemini-pro":"google/gemini-2.5-pro",
            "gemini-flash":"google/gemini-2.5-flash",
        }
        
        for model_key in models:
            if model_key in model_api_mapping:
                api_name = model_api_mapping[model_key]
                limit = MODEL_LIMITS.get(api_name, 128_000)
                
                if limit < min_limit:
                    min_limit = limit
                    # Use the most restrictive model's tokenizer
                    tokenizer_func = get_tokenizer_for_model(api_name, self.api_key)
        
        if min_limit == float('inf'):
            min_limit = 128_000  # Default fallback
            tokenizer_func = estimate_tokens
        
        logger.info(f"Using minimum context limit: {min_limit:,} tokens")
        
        # Filter instances with accurate tokenization
        filtered_instances = []
        skipped_count = 0
        
        for instance in instances:
            prompt = instance.get('prompt', '')
            
            try:
                if callable(tokenizer_func):
                    token_count = tokenizer_func(prompt)
                else:
                    token_count = estimate_tokens(prompt)
                
                if token_count <= min_limit:
                    filtered_instances.append(instance)
                else:
                    skipped_count += 1
                    instance_id = instance.get('instance_id', 'unknown')
                    logger.debug(f"Filtered out instance {instance_id}: {token_count:,} > {min_limit:,} tokens")
                    
            except Exception as e:
                logger.warning(f"Error tokenizing instance {instance.get('instance_id', 'unknown')}: {e}")
                # Include instance if tokenization fails (with warning)
                filtered_instances.append(instance)
        
        logger.info(f"Filtered to {len(filtered_instances):,} instances (removed {skipped_count:,} instances)")
        
        if skipped_count > 0:
            removal_pct = (skipped_count / len(instances)) * 100
            logger.info(f"Removed {removal_pct:.1f}% of instances due to token limits")
        
        return filtered_instances
    
    def get_existing_ids(self, output_path: str) -> Set[str]:
        """Get IDs of already processed instances"""
        existing_ids = set()
        if os.path.exists(output_path):
            try:
                with open(output_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            instance_id = data.get("instance_id")
                            if instance_id:
                                existing_ids.add(instance_id)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning(f"Error reading existing file {output_path}: {e}")
        
        logger.info(f"Found {len(existing_ids)} already completed instances")
        return existing_ids
    
    def shard_dataset(self, instances: List[Dict[str, Any]], shard_id: int, num_shards: int) -> List[Dict[str, Any]]:
        """Shard dataset for parallel processing"""
        if num_shards <= 1:
            return instances
        
        # Sort by instance_id for consistent sharding
        instances.sort(key=lambda x: x.get('instance_id', ''))
        
        # Calculate shard boundaries
        total_instances = len(instances)
        instances_per_shard = total_instances // num_shards
        remainder = total_instances % num_shards
        
        start_idx = shard_id * instances_per_shard + min(shard_id, remainder)
        end_idx = start_idx + instances_per_shard + (1 if shard_id < remainder else 0)
        
        sharded_instances = instances[start_idx:end_idx]
        logger.info(f"Shard {shard_id}/{num_shards}: Processing {len(sharded_instances)} instances ({start_idx}-{end_idx-1})")
        
        return sharded_instances
    
    async def run_inference_for_instance(self, instance: Dict[str, Any], models_to_run: List[str]) -> List[InferenceResult]:
        """Run inference for a single instance across specified models"""
        instance_id = instance.get('instance_id', 'unknown')
        prompt = instance.get('prompt', '')
        base_commit = instance.get('base_commit', None)  # Extract base_commit from input
        
        if not prompt:
            logger.warning(f"No prompt found for instance {instance_id}")
            return []
        
        logger.debug(f"Processing instance {instance_id} (prompt length: {len(prompt)} chars)")
        
        async with OpenRouterClient(self.api_key, 
                                    temperature=self.temperature,
                                    max_tokens_override=self.max_tokens,
                                    top_p=self.top_p) as client:
            tasks = []
            for model_key in models_to_run:
                if model_key in client.models:
                    task = client.generate_response(model_key, prompt, instance_id)
                    tasks.append(task)
                else:
                    logger.warning(f"Unknown model key: {model_key}")
            
            if not tasks:
                logger.error(f"No valid models specified for instance {instance_id}")
                return []
            
            # Run all models concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and set base_commit
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Exception in model {models_to_run[i]}: {result}")
                    error_result = InferenceResult(
                        instance_id=instance_id,
                        model_name=models_to_run[i],
                        model_name_or_path="unknown",
                        generated_patch="",
                        full_output="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        response_time=0.0,
                        cost=0.0,
                        base_commit=base_commit,  # Set base_commit
                        error=str(result),
                        prompt=prompt  # Store complete prompt
                    )
                    processed_results.append(error_result)
                else:
                    # Set base_commit for successful results
                    result.base_commit = base_commit
                    processed_results.append(result)
            
            return processed_results
    
    async def run_inference(self, 
                          input_path: str, 
                          output_path: str, 
                          models: List[str] = None,
                          max_instances: int = None,
                          max_cost: float = None,
                          shard_id: int = None,
                          num_shards: int = None) -> None:
        """Run inference on mobile bench data with enhanced features"""
        
        if models is None:
            models = ["gemini-flash", "claude-sonnet-3.7", "gpt-4o"]
        
        # Load data
        instances = self.load_data(input_path)
        
        # Filter by token limits
        instances = self.filter_by_length(instances, models)
        
        # Sort by prompt length (shorter first for efficiency)
        instances.sort(key=lambda x: len(x.get('prompt', '')))
        
        # Handle existing results (resume capability)
        existing_ids = self.get_existing_ids(output_path)
        if existing_ids:
            instances = [inst for inst in instances if inst.get('instance_id') not in existing_ids]
            logger.info(f"Filtered out {len(existing_ids)} already processed instances")
        
        # Shard dataset if requested
        if shard_id is not None and num_shards is not None:
            instances = self.shard_dataset(instances, shard_id, num_shards)
        
        # Limit instances if requested
        if max_instances:
            instances = instances[:max_instances]
            logger.info(f"Limiting to first {max_instances} instances")
        
        logger.info(f"Running inference on {len(instances)} instances with models: {models}")
        logger.info(f"Configuration: temperature={self.temperature}, max_tokens={self.max_tokens}, top_p={self.top_p}")
        if max_cost:
            logger.info(f"Max cost limit: ${max_cost:.2f}")
        
        all_results = []
        total_cost = 0.0
        
        # Process instances
        with tqdm(total=len(instances), desc="Processing instances", unit="instance") as pbar:
            for i, instance in enumerate(instances, 1):
                pbar.set_description(f"Processing instance {i}/{len(instances)}")
                
                try:
                    instance_results = await self.run_inference_for_instance(instance, models)
                    
                    # Calculate cost for this batch
                    batch_cost = sum(r.cost for r in instance_results)
                    total_cost += batch_cost
                    
                    # Check cost limit
                    if max_cost and total_cost >= max_cost:
                        logger.info(f"Reached max cost ${max_cost:.2f}, stopping inference")
                        all_results.extend(instance_results)
                        break
                    
                    all_results.extend(instance_results)
                    
                    # Save results incrementally
                    self.save_results_incremental(instance_results, output_path)
                    
                    # Update progress bar
                    successful = len([r for r in all_results if r.error is None])
                    total_results = len(all_results)
                    pbar.set_postfix({
                        'Success': f"{successful}/{total_results}",
                        'Rate': f"{(successful/total_results*100):.1f}%" if total_results > 0 else "0%",
                        'Cost': f"${total_cost:.2f}"
                    })
                    
                    # Add delay between instances
                    if i < len(instances):
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Error processing instance {i}: {e}")
                    continue
                finally:
                    pbar.update(1)
        
        # Print summary
        logger.info(f"Total cost: ${total_cost:.2f}")
        self.print_summary(all_results)
    
    def save_results_incremental(self, results: List[InferenceResult], output_path: str) -> None:
        """Save results incrementally (append mode)"""
        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'a', encoding='utf-8') as f:
            for result in results:
                result_dict = asdict(result)
                f.write(json.dumps(result_dict, ensure_ascii=False) + '\n')
    
    def save_results(self, results: List[InferenceResult], output_path: str) -> None:
        """Save all results to JSONL file"""
        logger.info(f"Saving {len(results)} results to {output_path}")
        
        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for result in results:
                result_dict = asdict(result)
                f.write(json.dumps(result_dict, ensure_ascii=False) + '\n')
        
        logger.info(f"Results saved to {output_path}")
        
        # Save summary
        summary_path = output_path.replace('.jsonl', '_summary.json')
        summary_dict = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_results": len(results),
                "script_version": "2.0",
                "output_file": output_path
            },
            "statistics": self._generate_statistics(results)
        }
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_dict, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Summary saved to {summary_path}")
    
    def _generate_statistics(self, results: List[InferenceResult]) -> Dict[str, Any]:
        """Generate comprehensive statistics"""
        total_results = len(results)
        successful_results = len([r for r in results if r.error is None])
        failed_results = total_results - successful_results
        
        stats = {
            "total_results": total_results,
            "successful_results": successful_results,
            "failed_results": failed_results,
            "success_rate": (successful_results / total_results * 100) if total_results > 0 else 0
        }
        
        if successful_results > 0:
            successful = [r for r in results if r.error is None]
            stats["average_response_time"] = sum(r.response_time for r in successful) / len(successful)
            stats["total_tokens"] = sum(r.total_tokens for r in successful)
            stats["total_prompt_tokens"] = sum(r.prompt_tokens for r in successful)
            stats["total_completion_tokens"] = sum(r.completion_tokens for r in successful)
            stats["total_cost"] = sum(r.cost for r in results)  # Include all results for total cost
        
        # Per-model breakdown
        model_stats = {}
        for result in results:
            model = result.model_name
            if model not in model_stats:
                model_stats[model] = {
                    "total": 0, 
                    "successful": 0, 
                    "tokens": 0, 
                    "cost": 0.0,
                    "avg_response_time": 0
                }
            
            model_stats[model]["total"] += 1
            model_stats[model]["cost"] += result.cost
            if result.error is None:
                model_stats[model]["successful"] += 1
                model_stats[model]["tokens"] += result.total_tokens
        
        # Calculate averages for each model
        for model, model_stat in model_stats.items():
            if model_stat["successful"] > 0:
                successful_for_model = [r for r in results if r.model_name == model and r.error is None]
                model_stat["avg_response_time"] = sum(r.response_time for r in successful_for_model) / len(successful_for_model)
                model_stat["success_rate"] = (model_stat["successful"] / model_stat["total"]) * 100
            else:
                model_stat["avg_response_time"] = 0
                model_stat["success_rate"] = 0
        
        stats["per_model"] = model_stats
        return stats
    
    def print_summary(self, results: List[InferenceResult]) -> None:
        """Print comprehensive summary statistics"""
        logger.info("\n=== INFERENCE SUMMARY ===")
        
        total_results = len(results)
        successful_results = len([r for r in results if r.error is None])
        failed_results = total_results - successful_results
        total_cost = sum(r.cost for r in results)
        
        logger.info(f"Total results: {total_results}")
        logger.info(f"Successful: {successful_results}")
        logger.info(f"Failed: {failed_results}")
        logger.info(f"Success rate: {(successful_results/total_results*100):.1f}%" if total_results > 0 else "0%")
        logger.info(f"Total cost: ${total_cost:.4f}")
        
        if successful_results > 0:
            successful = [r for r in results if r.error is None]
            avg_response_time = sum(r.response_time for r in successful) / len(successful)
            total_tokens = sum(r.total_tokens for r in successful)
            
            logger.info(f"Average response time: {avg_response_time:.2f}s")
            logger.info(f"Total tokens used: {total_tokens:,}")
            logger.info(f"Average cost per successful result: ${total_cost/successful_results:.4f}")
        
        # Per-model breakdown
        model_stats = {}
        for result in results:
            model = result.model_name
            if model not in model_stats:
                model_stats[model] = {"total": 0, "successful": 0, "tokens": 0, "cost": 0.0}
            
            model_stats[model]["total"] += 1
            model_stats[model]["cost"] += result.cost
            if result.error is None:
                model_stats[model]["successful"] += 1
                model_stats[model]["tokens"] += result.total_tokens
        
        logger.info("\nPer-model statistics:")
        for model, stats in model_stats.items():
            success_rate = (stats["successful"] / stats["total"]) * 100 if stats["total"] > 0 else 0
            logger.info(f"  {model}: {stats['successful']}/{stats['total']} ({success_rate:.1f}%) - "
                       f"{stats['tokens']:,} tokens - ${stats['cost']:.4f}")
        
        # Error breakdown
        error_counts = {}
        for result in results:
            if result.error:
                error_type = result.error.split(':')[0] if ':' in result.error else result.error
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        if error_counts:
            logger.info(f"\nError breakdown:")
            for error_type, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"  {error_type}: {count}")

def main():
    """Main entry point with enhanced argument parsing"""
    parser = argparse.ArgumentParser(
        description="Enhanced Mobile Bench OpenRouter Inference Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python run_completion.py --input data.jsonl --output results.jsonl
  
  # With cost limit
  python run_completion.py --input data.jsonl --output results.jsonl --max-cost 50.0
  
  # Parallel processing with shards
  python run_completion.py --input data.jsonl --output results_shard0.jsonl --shard-id 0 --num-shards 4
  
  # Custom model parameters
  python run_completion.py --input data.jsonl --output results.jsonl --temperature 0.7 --max-tokens 6000
  
  # Resume interrupted run (automatically skips completed instances)
  python run_completion.py --input data.jsonl --output results.jsonl
        """
    )
    
    # Required arguments
    parser.add_argument("--input", "-i", required=True, 
                       help="Input JSONL file with mobile bench data")
    parser.add_argument("--output", "-o", required=True, 
                       help="Output JSONL file for results")
    
    # API configuration
    parser.add_argument("--api-key", 
                       help="OpenRouter API key (or set OPENROUTER_API_KEY env var)")
    
    # Model selection
    parser.add_argument("--models", nargs="+", 
                       choices=["claude-sonnet-3.7", "claude-sonnet-4", "claude-opus-4", "deepseek-v3", "deepseek-r1", "gpt-4.1", "gpt-4o", "gpt-4o-mini", "gemini-pro", "gemini-flash"],
                       default=["gemini-flash", "claude-sonnet-3.7", "gpt-4o"],
                       help="Models to run inference with")
    
    # Processing control
    parser.add_argument("--max-instances", type=int, 
                       help="Maximum number of instances to process")
    parser.add_argument("--max-cost", type=float, 
                       help="Maximum cost to spend on inference (in USD)")
    
    # Parallel processing
    parser.add_argument("--shard-id", type=int, default=None,
                       help="Shard id to process (0-based). Use with --num-shards")
    parser.add_argument("--num-shards", type=int, default=None,
                       help="Total number of shards. Use with --shard-id")
    
    # Model parameters
    parser.add_argument("--temperature", type=float, default=None, 
                       help="Temperature for sampling (0.0=deterministic, 1.0=creative). Default: 0.0")
    parser.add_argument("--max-tokens", type=int, default=None,
                       help="Override max tokens for all models (default: model-specific limits)")
    parser.add_argument("--top-p", type=float, default=None,
                       help="Top-p (nucleus sampling) parameter. Default: 1.0")
    parser.add_argument("--model-args", type=str, default=None,
                       help="Additional model arguments as comma-separated key=value pairs")
    
    # Logging and debugging
    parser.add_argument("--verbose", "-v", action="store_true", 
                       help="Enable verbose logging")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging (very verbose)")
    
    args = parser.parse_args()
    
    # Set logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    
    # Validate shard arguments
    if args.shard_id is not None and args.num_shards is None:
        logger.error("--shard-id requires --num-shards")
        return 1
    if args.num_shards is not None and args.shard_id is None:
        logger.error("--num-shards requires --shard-id")
        return 1
    if args.shard_id is not None and (args.shard_id < 0 or args.shard_id >= args.num_shards):
        logger.error(f"--shard-id must be between 0 and {args.num_shards-1}")
        return 1
    
    # Get API key
    api_key = args.api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OpenRouter API key required. Set --api-key or OPENROUTER_API_KEY environment variable")
        return 1
    
    # Validate input file
    if not Path(args.input).exists():
        logger.error(f"Input file not found: {args.input}")
        return 1
    
    # Validate output file extension
    if not args.output.endswith('.jsonl'):
        logger.warning(f"Output file should have .jsonl extension. Current: {args.output}")
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            return 1
    
    # Parse additional model arguments
    additional_model_args = {}
    if args.model_args:
        try:
            additional_model_args = parse_model_args(args.model_args)
            logger.info(f"Additional model arguments: {additional_model_args}")
        except Exception as e:
            logger.error(f"Failed to parse model arguments: {e}")
            return 1
    
    # Apply additional model arguments to main parameters
    temperature = args.temperature
    max_tokens = args.max_tokens
    top_p = args.top_p
    
    if 'temperature' in additional_model_args:
        temperature = additional_model_args['temperature']
    if 'max_tokens' in additional_model_args:
        max_tokens = additional_model_args['max_tokens']
    if 'top_p' in additional_model_args:
        top_p = additional_model_args['top_p']
    
    # Create inference object
    inference = MobileBenchInference(
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p
    )
    
    # Log configuration
    logger.info("=== CONFIGURATION ===")
    logger.info(f"Input file: {args.input}")
    logger.info(f"Output file: {args.output}")
    logger.info(f"Models: {args.models}")
    logger.info(f"Max instances: {args.max_instances or 'unlimited'}")
    logger.info(f"Max cost: ${args.max_cost}" if args.max_cost else "Max cost: unlimited")
    if args.shard_id is not None:
        logger.info(f"Shard: {args.shard_id}/{args.num_shards}")
    logger.info(f"Temperature: {temperature}")
    logger.info(f"Max tokens: {max_tokens}")
    logger.info(f"Top-p: {top_p}")
    logger.info("=" * 20)
    
    # Run inference
    try:
        asyncio.run(inference.run_inference(
            input_path=args.input,
            output_path=args.output,
            models=args.models,
            max_instances=args.max_instances,
            max_cost=args.max_cost,
            shard_id=args.shard_id,
            num_shards=args.num_shards
        ))
        logger.info("Inference completed successfully!")
        return 0
    except KeyboardInterrupt:
        logger.info("Inference interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())