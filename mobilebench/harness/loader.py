#!/usr/bin/env python3
"""
Dataset and prediction loading utilities for Android-bench.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TaskInstance:
    """Android-bench task instance."""
    repo: str
    pull_number: int
    instance_id: str
    issue_numbers: List[int]
    base_commit: str
    merge_sha: str
    patch: str
    test_patch: str
    problem_statement: str
    hints_text: str
    created_at: str


@dataclass
class ModelPrediction:
    """Model prediction for a task instance."""
    instance_id: str
    model_name: str
    model_name_or_path: str
    full_output: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time: float
    cost: float
    base_commit: str
    error: Optional[str]
    timestamp: str
    prompt: str


class DatasetLoader:
    """Loads and filters Android-bench datasets and predictions."""
    
    def __init__(self, dataset_path: str, predictions_path: str):
        self.dataset_path = Path(dataset_path)
        self.predictions_path = Path(predictions_path)
        
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
        if not self.predictions_path.exists():
            raise FileNotFoundError(f"Predictions file not found: {predictions_path}")
    
    def load_dataset(self) -> Dict[str, TaskInstance]:
        """Load task instances from JSONL file."""
        instances = {}
        
        logger.info(f"Loading dataset from {self.dataset_path}")
        with open(self.dataset_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    data = json.loads(line)
                    instance = TaskInstance(**data)
                    instances[instance.instance_id] = instance
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON on line {line_num}: {e}")
                    continue
                except TypeError as e:
                    logger.error(f"Invalid task instance format on line {line_num}: {e}")
                    continue
        
        logger.info(f"Loaded {len(instances)} task instances")
        return instances
    
    def load_predictions(self) -> Dict[str, ModelPrediction]:
        """Load model predictions from JSONL file."""
        predictions = {}
        
        logger.info(f"Loading predictions from {self.predictions_path}")
        with open(self.predictions_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    data = json.loads(line)
                    prediction = ModelPrediction(**data)
                    predictions[prediction.instance_id] = prediction
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON on line {line_num}: {e}")
                    continue
                except TypeError as e:
                    logger.error(f"Invalid prediction format on line {line_num}: {e}")
                    continue
        
        logger.info(f"Loaded {len(predictions)} predictions")
        return predictions
    
    def filter_instances(
        self,
        instances: Dict[str, TaskInstance],
        predictions: Dict[str, ModelPrediction],
        instance_ids: Optional[List[str]] = None,
        completed_instances: Optional[Set[str]] = None,
        exclude_empty_patches: bool = True
    ) -> Dict[str, TaskInstance]:
        """Filter instances based on various criteria."""
        
        # Start with instances that have predictions
        filtered = {}
        for instance_id, instance in instances.items():
            if instance_id not in predictions:
                continue
            
            # Filter by specific instance IDs if provided
            if instance_ids and instance_id not in instance_ids:
                continue
            
            # Skip already completed instances
            if completed_instances and instance_id in completed_instances:
                logger.debug(f"Skipping completed instance: {instance_id}")
                continue
            
            # Filter out empty/null patches if requested
            prediction = predictions[instance_id]
            if exclude_empty_patches:
                patch_content = self._extract_patch_from_output(prediction.full_output)
                if not patch_content or not patch_content.strip():
                    logger.debug(f"Skipping instance with empty patch: {instance_id}")
                    continue
            
            filtered[instance_id] = instance
        
        logger.info(f"Filtered to {len(filtered)} instances for evaluation")
        return filtered
    
    def _extract_patch_from_output(self, full_output: str) -> str:
        """Extract patch content from model's full output."""
        if not full_output:
            return ""
        
        # Look for diff blocks in markdown code blocks
        import re
        
        # Pattern for markdown code blocks with diff
        diff_pattern = r'```(?:diff)?\n(.*?)```'
        matches = re.findall(diff_pattern, full_output, re.DOTALL)
        
        if matches:
            return matches[0].strip()
        
        # If no markdown blocks, check if the entire output is a diff
        if full_output.strip().startswith('diff --git') or full_output.strip().startswith('---'):
            return full_output.strip()
        
        return ""
    
    def get_completed_instances(self, run_id: str, output_dir: str) -> Set[str]:
        """Get set of already completed instance IDs from previous runs."""
        completed = set()
        results_dir = Path(output_dir) / run_id
        
        if not results_dir.exists():
            return completed
        
        # Look for completed evaluations (presence of report.json files)
        for model_dir in results_dir.iterdir():
            if not model_dir.is_dir():
                continue
                
            for instance_dir in model_dir.iterdir():
                if not instance_dir.is_dir():
                    continue
                
                report_file = instance_dir / "report.json"
                if report_file.exists():
                    completed.add(instance_dir.name)
        
        logger.info(f"Found {len(completed)} completed instances from previous runs")
        return completed


def load_dataset_and_predictions(
    dataset_path: str,
    predictions_path: str,
    instance_ids: Optional[List[str]] = None,
    run_id: Optional[str] = None,
    output_dir: str = "android_evaluation_results",
    exclude_completed: bool = True,
    exclude_empty_patches: bool = True
) -> tuple[Dict[str, TaskInstance], Dict[str, ModelPrediction]]:
    """
    Convenience function to load and filter dataset and predictions.
    
    Returns:
        Tuple of (filtered_instances, all_predictions)
    """
    loader = DatasetLoader(dataset_path, predictions_path)
    
    # Load raw data
    all_instances = loader.load_dataset()
    all_predictions = loader.load_predictions()
    
    # Get completed instances if needed
    completed_instances = set()
    if exclude_completed and run_id:
        completed_instances = loader.get_completed_instances(run_id, output_dir)
    
    # Filter instances
    filtered_instances = loader.filter_instances(
        all_instances,
        all_predictions,
        instance_ids=instance_ids,
        completed_instances=completed_instances,
        exclude_empty_patches=exclude_empty_patches
    )
    
    return filtered_instances, all_predictions


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Load and filter Android-bench dataset")
    parser.add_argument("dataset_path", help="Path to dataset JSONL file")
    parser.add_argument("predictions_path", help="Path to predictions JSONL file")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to load")
    parser.add_argument("--output-dir", default="android_evaluation_results", 
                       help="Output directory for results")
    parser.add_argument("--run-id", help="Run ID for checking completed instances")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    instances, predictions = load_dataset_and_predictions(
        args.dataset_path,
        args.predictions_path,
        instance_ids=args.instance_ids,
        run_id=args.run_id,
        output_dir=args.output_dir
    )
    
    print(f"Loaded {len(instances)} filtered instances")
    print(f"Loaded {len(predictions)} total predictions")