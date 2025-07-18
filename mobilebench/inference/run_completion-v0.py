#!/usr/bin/env python3
"""
Mobile Bench OpenRouter Inference Script

This script uses OpenRouter API to prompt multiple language models 
(DeepSeek V3, Claude Sonnet 4, GPT-4.1) with generated prompts from 
mobile bench smart oracle retrieval for Android projects.

Usage:
    python run_completion.py --input data.jsonl --output results.jsonl
"""

import json
import asyncio
import aiohttp
import argparse
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import time
import os
from datetime import datetime
from tqdm.asyncio import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    generated_patch: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time: float
    error: Optional[str] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

class OpenRouterClient:
    """Client for OpenRouter API"""
    
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1",
                 temperature: Optional[float] = None, max_tokens_override: Optional[int] = None,
                 top_p: Optional[float] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
        self.temperature_override = temperature
        self.max_tokens_override = max_tokens_override
        self.top_p_override = top_p
        
        # Model configurations with actual context window sizes and realistic limits
        base_configs = {
            "claude-sonnet-4": ("Claude Sonnet 4", "anthropic/claude-4-sonnet-20250522", 8192),  # 200K available, using 8K for cost control
            "claude-opus-4": ("Claude Opus 4", "anthropic/claude-4-opus-20250522", 8192),  # 200K available, using 8K for cost control  
            "deepseek-v3": ("DeepSeek V3", "deepseek/deepseek-chat-v3-0324", 8192),       # 163,840 context, API limited to 64K input, using 8K for cost control
            "deepseek-r1": ("DeepSeek R1(free)", "deepseek/deepseek-r1-0528:free", 8192),       # 163,840 context, API limited to 64K input, using 8K for cost control
            "gpt-41": ("GPT-4.1", "openai/gpt-4.1-2025-04-14", 4096),       # 1,047,576 context available, using 4K for cost control
        
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
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "Mobile Bench Inference"  # Optional: for OpenRouter analytics
            },
            timeout=aiohttp.ClientTimeout(total=300)  # 5 minute timeout
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def generate_response(self, model_key: str, prompt: str) -> InferenceResult:
        """Generate response from specified model"""
        model_config = self.models[model_key]
        
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
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API request failed for {model_config.name}: {response.status} - {error_text}")
                    return InferenceResult(
                        instance_id="",
                        model_name=model_config.name,
                        generated_patch="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        response_time=response_time,
                        error=f"HTTP {response.status}: {error_text}"
                    )
                
                data = await response.json()
                
                # Extract response content
                generated_patch = data["choices"][0]["message"]["content"]
                
                # Extract token usage
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0) 
                total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
                
                logger.info(f"✓ {model_config.name} completed in {response_time:.2f}s")
                
                return InferenceResult(
                    instance_id="",
                    model_name=model_config.name,
                    generated_patch=generated_patch,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    response_time=response_time
                )
                
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"Error with {model_config.name}: {str(e)}")
            return InferenceResult(
                instance_id="",
                model_name=model_config.name,
                generated_patch="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_time=response_time,
                error=str(e)
            )

class MobileBenchInference:
    """Main inference class for Mobile Bench"""
    
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
                if not line:  # Skip empty lines
                    continue
                
                try:
                    instance = json.loads(line)
                    data.append(instance)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line {line_num}: {e}")
                    logger.warning(f"Line content: {line[:100]}...")
                    continue
        
        logger.info(f"Loaded {len(data)} instances")
        return data
    
    async def run_inference_for_instance(self, instance: Dict[str, Any], models_to_run: List[str]) -> List[InferenceResult]:
        """Run inference for a single instance across specified models"""
        instance_id = instance.get('instance_id', 'unknown')
        prompt = instance.get('prompt', '')
        
        if not prompt:
            logger.warning(f"No prompt found for instance {instance_id}")
            return []
        
        logger.info(f"Processing instance {instance_id}")
        logger.info(f"Prompt length: {len(prompt)} characters")
        
        async with OpenRouterClient(self.api_key, 
                                    temperature=self.temperature,
                                    max_tokens_override=self.max_tokens,
                                    top_p=self.top_p) as client:
            tasks = []
            for model_key in models_to_run:
                if model_key in client.models:
                    task = client.generate_response(model_key, prompt)
                    tasks.append(task)
                else:
                    logger.warning(f"Unknown model key: {model_key}")
            
            if not tasks:
                logger.error(f"No valid models specified for instance {instance_id}")
                return []
            
            # Run all models concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle exceptions
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Exception in model {models_to_run[i]}: {result}")
                    error_result = InferenceResult(
                        instance_id=instance_id,
                        model_name=models_to_run[i],
                        generated_patch="",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        response_time=0.0,
                        error=str(result)
                    )
                    processed_results.append(error_result)
                else:
                    result.instance_id = instance_id
                    processed_results.append(result)
            
            return processed_results
    
    async def run_inference(self, 
                          input_path: str, 
                          output_path: str, 
                          models: List[str] = None,
                          max_instances: int = None) -> None:
        """Run inference on mobile bench data"""
        
        if models is None:
            models = ["deepseek-v3", "claude-sonnet-4", "gpt-4"]
        
        # Load data
        instances = self.load_data(input_path)
        
        if max_instances:
            instances = instances[:max_instances]
            logger.info(f"Limiting to first {max_instances} instances")
        
        logger.info(f"Running inference with models: {models}")
        logger.info(f"Configuration: temperature={self.temperature}, max_tokens={self.max_tokens}, top_p={self.top_p}")
        
        all_results = []
        
        # Create progress bar for instances
        with tqdm(total=len(instances), desc="Processing instances", unit="instance") as pbar:
            # Process each instance
            for i, instance in enumerate(instances, 1):
                pbar.set_description(f"Processing instance {i}/{len(instances)}")
                
                try:
                    instance_results = await self.run_inference_for_instance(instance, models)
                    all_results.extend(instance_results)
                    
                    # Update progress bar with current stats
                    successful = len([r for r in all_results if r.error is None])
                    total_results = len(all_results)
                    pbar.set_postfix({
                        'Success': f"{successful}/{total_results}",
                        'Rate': f"{(successful/total_results*100):.1f}%" if total_results > 0 else "0%"
                    })
                    
                    # Add small delay between instances to be respectful to API
                    if i < len(instances):
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Error processing instance {i}: {e}")
                    continue
                finally:
                    pbar.update(1)
        
        # Save results
        self.save_results(all_results, output_path)
        
        # Print summary
        self.print_summary(all_results)
    
    def save_results(self, results: List[InferenceResult], output_path: str) -> None:
        """Save results to JSONL file"""
        logger.info(f"Saving {len(results)} results to {output_path}")
        
        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for result in results:
                result_dict = asdict(result)
                f.write(json.dumps(result_dict, ensure_ascii=False) + '\n')
        
        logger.info(f"Results saved to {output_path}")
        
        # Also save a summary file
        summary_path = output_path.replace('.jsonl', '_summary.json')
        summary_dict = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_results": len(results),
                "script_version": "1.0",
                "output_file": output_path
            },
            "statistics": self._generate_statistics(results)
        }
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_dict, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Summary saved to {summary_path}")
    
    def _generate_statistics(self, results: List[InferenceResult]) -> Dict[str, Any]:
        """Generate statistics for results"""
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
        
        # Per-model breakdown
        model_stats = {}
        for result in results:
            model = result.model_name
            if model not in model_stats:
                model_stats[model] = {"total": 0, "successful": 0, "tokens": 0, "avg_response_time": 0}
            
            model_stats[model]["total"] += 1
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
        """Print summary statistics"""
        logger.info("\n=== INFERENCE SUMMARY ===")
        
        total_results = len(results)
        successful_results = len([r for r in results if r.error is None])
        failed_results = total_results - successful_results
        
        logger.info(f"Total results: {total_results}")
        logger.info(f"Successful: {successful_results}")
        logger.info(f"Failed: {failed_results}")
        
        if successful_results > 0:
            avg_response_time = sum(r.response_time for r in results if r.error is None) / successful_results
            total_tokens = sum(r.total_tokens for r in results if r.error is None)
            
            logger.info(f"Average response time: {avg_response_time:.2f}s")
            logger.info(f"Total tokens used: {total_tokens:,}")
        
        # Per-model breakdown
        model_stats = {}
        for result in results:
            model = result.model_name
            if model not in model_stats:
                model_stats[model] = {"total": 0, "successful": 0, "tokens": 0}
            
            model_stats[model]["total"] += 1
            if result.error is None:
                model_stats[model]["successful"] += 1
                model_stats[model]["tokens"] += result.total_tokens
        
        logger.info("\nPer-model statistics:")
        for model, stats in model_stats.items():
            success_rate = (stats["successful"] / stats["total"]) * 100 if stats["total"] > 0 else 0
            logger.info(f"  {model}: {stats['successful']}/{stats['total']} ({success_rate:.1f}%) - {stats['tokens']:,} tokens")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Mobile Bench OpenRouter Inference Script")
    parser.add_argument("--input", "-i", required=True, help="Input JSONL file with mobile bench data")
    parser.add_argument("--output", "-o", required=True, help="Output JSONL file for results")
    parser.add_argument("--api-key", help="OpenRouter API key (or set OPENROUTER_API_KEY env var)")
    parser.add_argument("--models", nargs="+", 
                       choices=["deepseek-v3", "claude-sonnet-4", "gpt-4o"],
                       default=["deepseek-v3", "claude-sonnet-4", "gpt-4o"],
                       help="Models to run inference with")
    parser.add_argument("--max-instances", type=int, help="Maximum number of instances to process")
    parser.add_argument("--temperature", type=float, default=None, 
                       help="Temperature for sampling (0.0=deterministic, 1.0=creative). Default: 0.0 for reproducibility")
    parser.add_argument("--max-tokens", type=int, default=None,
                       help="Override max tokens for all models (default: model-specific limits)")
    parser.add_argument("--top-p", type=float, default=None,
                       help="Top-p (nucleus sampling) parameter (0.1=focused, 1.0=diverse). Default: 1.0")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get API key
    api_key = args.api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OpenRouter API key required. Set --api-key or OPENROUTER_API_KEY environment variable")
        return 1
    
    # Validate input file
    if not Path(args.input).exists():
        logger.error(f"Input file not found: {args.input}")
        return 1
    
    # Ensure output has .jsonl extension
    if not args.output.endswith('.jsonl'):
        logger.warning(f"Output file should have .jsonl extension. Current: {args.output}")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            return 1
    
    # Run inference
    inference = MobileBenchInference(api_key)
    
    try:
        asyncio.run(inference.run_inference(
            args.input, 
            args.output, 
            args.models,
            args.max_instances
        ))
        logger.info("Inference completed successfully!")
        return 0
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())