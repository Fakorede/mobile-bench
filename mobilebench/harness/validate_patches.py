#!/usr/bin/env python3
"""
Simple Patch Validation Script for Mobile Bench

This script validates patches by testing if they can be applied to their target repositories
without any automatic repair attempts.

Usage:
    python validate_patches.py --predictions results.jsonl --dataset data.jsonl --report validation_report.json
    python validate_patches.py --predictions results.jsonl --dataset data.jsonl --max-instances 10 --verbose
"""

import argparse
import json
import logging
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    """Result of patch validation"""
    instance_id: str
    valid: bool = False
    error_message: str = ""

class PatchValidator:
    """Simple patch validator - tests if patches can be applied"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        
    def clone_repo_temp(self, repo_url: str, base_commit: str) -> Optional[str]:
        """Clone repository to temporary directory and checkout base commit"""
        try:
            temp_dir = tempfile.mkdtemp(prefix="patch_validator_")
            
            # Clone repository
            result = subprocess.run(
                ["git", "clone", repo_url, temp_dir],
                capture_output=True, text=True, timeout=300
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to clone {repo_url}: {result.stderr}")
                return None
            
            # Checkout base commit
            result = subprocess.run(
                ["git", "checkout", base_commit],
                cwd=temp_dir, capture_output=True, text=True
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to checkout {base_commit}: {result.stderr}")
                return None
            
            return temp_dir
            
        except Exception as e:
            logger.error(f"Error cloning repository: {e}")
            return None
    
    def test_patch_application(self, patch_content: str, repo_dir: str) -> Tuple[bool, str]:
        """Test if patch can be applied using git apply --check"""
        try:
            # Write patch to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(patch_content)
                patch_file = f.name
            
            try:
                # Test with git apply --check
                result = subprocess.run(
                    ["git", "apply", "--check", "--verbose", patch_file],
                    cwd=repo_dir, capture_output=True, text=True, timeout=30
                )
                
                success = result.returncode == 0
                error_msg = result.stderr if not success else ""
                
                return success, error_msg
                
            finally:
                os.unlink(patch_file)
                
        except Exception as e:
            return False, str(e)
    
    def validate_patch(self, instance_id: str, patch_content: str, 
                      repo_url: str, base_commit: str) -> ValidationResult:
        """Validate a single patch"""
        if self.verbose:
            logger.info(f"Validating patch for {instance_id}")
        
        result = ValidationResult(instance_id=instance_id)
        
        # Check if patch content exists
        if not patch_content or not patch_content.strip():
            result.error_message = "Empty patch content"
            return result
        
        # Clone repository for testing
        repo_dir = self.clone_repo_temp(repo_url, base_commit)
        if not repo_dir:
            result.error_message = "Failed to clone repository"
            return result
        
        try:
            # Test patch application
            applies, error_msg = self.test_patch_application(patch_content, repo_dir)
            result.valid = applies
            result.error_message = error_msg
            
            if applies:
                logger.info(f"✓ Patch for {instance_id} is valid")
            else:
                logger.info(f"✗ Patch for {instance_id} failed: {error_msg}")
            
            return result
            
        finally:
            # Cleanup
            try:
                subprocess.run(["rm", "-rf", repo_dir], check=True)
            except:
                pass

def main():
    parser = argparse.ArgumentParser(
        description="Simple patch validation for Mobile Bench evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--predictions", required=True, help="Input predictions JSONL file")
    parser.add_argument("--dataset", required=True, help="Dataset JSONL file with repo info")
    parser.add_argument("--report", help="Validation report JSON file")
    parser.add_argument("--max-instances", type=int, help="Limit number of instances to validate")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to validate")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load predictions
    logger.info(f"Loading predictions from {args.predictions}")
    predictions = {}
    with open(args.predictions, 'r') as f:
        for line in f:
            if line.strip():
                pred = json.loads(line)
                if 'instance_id' in pred and 'generated_patch' in pred:
                    predictions[pred['instance_id']] = pred
    
    logger.info(f"Loaded {len(predictions)} predictions")
    
    # Load dataset
    logger.info(f"Loading dataset from {args.dataset}")
    dataset = {}
    with open(args.dataset, 'r') as f:
        for line in f:
            if line.strip():
                entry = json.loads(line)
                if 'instance_id' in entry:
                    # Convert repo field to URL if needed
                    if 'repo' in entry and not entry['repo'].startswith('https://'):
                        entry['repo_url'] = f"https://github.com/{entry['repo']}.git"
                    elif 'repo' in entry:
                        entry['repo_url'] = entry['repo']
                    dataset[entry['instance_id']] = entry
    
    logger.info(f"Loaded {len(dataset)} dataset entries")
    
    # Find instances to validate
    available_instances = set(predictions.keys()) & set(dataset.keys())
    
    if args.instance_ids:
        instances_to_validate = list(set(args.instance_ids) & available_instances)
    else:
        instances_to_validate = list(available_instances)
    
    if args.max_instances:
        instances_to_validate = instances_to_validate[:args.max_instances]
    
    logger.info(f"Validating {len(instances_to_validate)} instances")
    
    # Validate patches
    validator = PatchValidator(verbose=args.verbose)
    results = []
    
    for i, instance_id in enumerate(instances_to_validate, 1):
        logger.info(f"[{i}/{len(instances_to_validate)}] Processing {instance_id}")
        
        pred = predictions[instance_id]
        dataset_entry = dataset[instance_id]
        
        patch_content = pred.get('generated_patch', '')
        repo_url = dataset_entry.get('repo_url')
        base_commit = dataset_entry.get('base_commit')
        
        if not repo_url or not base_commit:
            logger.warning(f"Missing repo_url or base_commit for {instance_id}")
            continue
        
        validation_result = validator.validate_patch(
            instance_id, patch_content, repo_url, base_commit
        )
        
        results.append(validation_result)
    
    # Generate summary
    total = len(results)
    valid = sum(1 for r in results if r.valid)
    
    logger.info("=== VALIDATION SUMMARY ===")
    logger.info(f"Total patches: {total}")
    logger.info(f"Valid patches: {valid} ({valid/total*100:.1f}%)")
    logger.info(f"Failed patches: {total-valid} ({(total-valid)/total*100:.1f}%)")
    
    # Show common error patterns
    error_patterns = {}
    for r in results:
        if not r.valid and r.error_message:
            # Extract error type
            if "corrupt patch" in r.error_message:
                error_type = "Corrupt patch format"
            elif "patch does not apply" in r.error_message:
                error_type = "Context mismatch"
            elif "No such file" in r.error_message:
                error_type = "Missing file"
            elif "patch fragment without header" in r.error_message:
                error_type = "Missing patch header"
            else:
                error_type = "Other error"
            
            error_patterns[error_type] = error_patterns.get(error_type, 0) + 1
    
    if error_patterns:
        logger.info("\nError breakdown:")
        for error_type, count in sorted(error_patterns.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {error_type}: {count}")
    
    # Save validation report
    if args.report:
        logger.info(f"Saving validation report to {args.report}")
        report_data = {
            "summary": {
                "total_patches": total,
                "valid_patches": valid,
                "failed_patches": total - valid,
                "success_rate": round(valid/total*100, 2) if total > 0 else 0
            },
            "error_breakdown": error_patterns,
            "results": [
                {
                    "instance_id": r.instance_id,
                    "valid": r.valid,
                    "error_message": r.error_message
                }
                for r in results
            ]
        }
        
        with open(args.report, 'w') as f:
            json.dump(report_data, f, indent=2)

if __name__ == "__main__":
    main()