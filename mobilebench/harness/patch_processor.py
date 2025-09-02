#!/usr/bin/env python3
"""
Consolidated Patch Processing Script for Mobile Bench

This script extracts patches from model outputs and validates them against target repositories.
It combines patch extraction and validation functionality in a single tool.

Usage:
    # Extract patches only
    python patch_processor.py extract input.jsonl output.jsonl
    
    # Validate existing patches
    python patch_processor.py validate --predictions results.jsonl --dataset data.jsonl --report validation_report.json
    
    # Extract and validate in one step
    python patch_processor.py extract-and-validate input.jsonl --dataset data.jsonl --output results.jsonl --report validation_report.json
    
    # Extract with overwrite
    python patch_processor.py extract input.jsonl output.jsonl --overwrite-existing
    
    # Validate specific instances
    python patch_processor.py validate --predictions results.jsonl --dataset data.jsonl --instance-ids ID1 ID2 ID3
"""

import json
import argparse
import re
import subprocess
import tempfile
import os
import logging
from typing import List, Optional, Dict, Tuple
from pathlib import Path
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    """Result of patch validation"""
    instance_id: str
    valid: bool = False
    error_message: str = ""
    patch_extracted: bool = False
    patch_length: int = 0

class PatchExtractor:
    """Extract patches from model output text"""
    
    @staticmethod
    def extract_patch_from_markdown(text: str) -> str:
        """Extract patches from markdown code blocks."""
        patterns = [
            r'```(?:diff|patch)\n(.*?)\n```',
            r'```\n(--- a/.*?)\n```',  # Patches that start with --- a/
            r'```(?:text)?\n((?:--- a/|diff --git).*?)\n```',  # Generic code blocks containing patches
        ]
        
        patches = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL | re.MULTILINE)
            for match in matches:
                cleaned_patch = PatchExtractor.clean_and_validate_patch(match)
                if cleaned_patch:
                    patches.append(cleaned_patch)
        
        return '\n'.join(patches) if patches else ""

    @staticmethod
    def extract_raw_patch(text: str) -> str:
        """Extract patches from raw text (no markdown formatting)."""
        lines = text.split('\n')
        patches = []
        current_patch = []
        in_patch = False
        consecutive_non_patch_lines = 0
        
        for line in lines:
            line_stripped = line.strip()
            
            # Check for patch start indicators
            if PatchExtractor.is_patch_start(line):
                # If we were already in a patch, save the current one
                if in_patch and current_patch:
                    patch_content = '\n'.join(current_patch)
                    cleaned = PatchExtractor.clean_and_validate_patch(patch_content)
                    if cleaned:
                        patches.append(cleaned)
                
                # Start new patch
                current_patch = [line]
                in_patch = True
                consecutive_non_patch_lines = 0
                continue
            
            if in_patch:
                # Check if this looks like a patch line
                if PatchExtractor.is_patch_line(line):
                    current_patch.append(line)
                    consecutive_non_patch_lines = 0
                elif line_stripped == "":
                    # Empty lines are okay in patches
                    current_patch.append(line)
                    consecutive_non_patch_lines = 0
                else:
                    consecutive_non_patch_lines += 1
                    
                    # If we hit too many consecutive non-patch lines, end the patch
                    if consecutive_non_patch_lines >= 3:
                        # Don't include the non-patch lines in the final patch
                        final_patch = current_patch[:-consecutive_non_patch_lines+1] if consecutive_non_patch_lines > 1 else current_patch
                        patch_content = '\n'.join(final_patch)
                        cleaned = PatchExtractor.clean_and_validate_patch(patch_content)
                        if cleaned:
                            patches.append(cleaned)
                        
                        current_patch = []
                        in_patch = False
                        consecutive_non_patch_lines = 0
                    else:
                        # Include this line for now, might be part of the patch
                        current_patch.append(line)
        
        # Handle any remaining patch
        if in_patch and current_patch:
            # Remove trailing non-patch lines
            while current_patch and not PatchExtractor.is_patch_line(current_patch[-1]) and current_patch[-1].strip() != "":
                current_patch.pop()
            
            if current_patch:
                patch_content = '\n'.join(current_patch)
                cleaned = PatchExtractor.clean_and_validate_patch(patch_content)
                if cleaned:
                    patches.append(cleaned)
        
        return '\n'.join(patches) if patches else ""

    @staticmethod
    def extract_diff_like_content(text: str) -> str:
        """Fallback: extract any content that looks diff-like."""
        lines = text.split('\n')
        diff_lines = []
        
        for line in lines:
            # Look for lines that could be part of a diff
            if (line.startswith(('+', '-', ' ', '@@')) or 
                '--- a/' in line or '+++ b/' in line or 
                'diff --git' in line):
                diff_lines.append(line)
            elif diff_lines and line.strip() == "":
                # Include empty lines if we're collecting diff content
                diff_lines.append(line)
        
        if diff_lines:
            return PatchExtractor.clean_and_validate_patch('\n'.join(diff_lines))
        
        return ""

    @staticmethod
    def is_patch_start(line: str) -> bool:
        """Check if line indicates the start of a patch."""
        indicators = ['diff --git', '--- a/', '+++ b/', '@@']
        return any(indicator in line for indicator in indicators)

    @staticmethod
    def is_patch_line(line: str) -> bool:
        """Check if line is a valid patch line."""
        if not line:
            return True  # Empty lines are valid in patches
        
        # Standard patch line prefixes
        if line.startswith(('+', '-', ' ', '@@')):
            return True
        
        # Patch headers
        if any(indicator in line for indicator in ['--- a/', '+++ b/', 'diff --git']):
            return True
        
        # Index lines in git patches
        if line.startswith('index '):
            return True
        
        # File mode changes
        if re.match(r'^(new|deleted) file mode \d+', line):
            return True
        
        return False

    @staticmethod
    def clean_and_validate_patch(patch_text: str) -> str:
        """Clean and validate patch content."""
        if not patch_text or not patch_text.strip():
            return ""
        
        lines = patch_text.split('\n')
        
        # Remove leading/trailing empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        
        if not lines:
            return ""
        
        # Check if this looks like a valid patch
        has_patch_header = False
        has_hunks = False
        
        for line in lines:
            # Look for patch headers
            if any(indicator in line for indicator in ['--- a/', '+++ b/', 'diff --git']):
                has_patch_header = True
            
            # Look for hunk headers or changes
            if line.startswith('@@') or (line.startswith(('+', '-')) and len(line) > 1):
                has_hunks = True
        
        # Must have either patch headers or actual changes
        if not (has_patch_header or has_hunks):
            return ""
        
        # Join lines and ensure proper ending
        result = '\n'.join(lines)
        if result and not result.endswith('\n'):
            result += '\n'
        
        return result

    @staticmethod
    def extract_patch(text: str) -> str:
        """
        Enhanced patch extraction from model output.
        Handles markdown code blocks, multiple patches, and various formats.
        """
        if not text or not text.strip():
            return ""
        
        # First, try to extract from markdown code blocks
        markdown_patch = PatchExtractor.extract_patch_from_markdown(text)
        if markdown_patch:
            return markdown_patch
        
        # If no markdown blocks, try to extract raw patch content
        raw_patch = PatchExtractor.extract_raw_patch(text)
        if raw_patch:
            return raw_patch
        
        # Fallback: look for any diff-like content
        return PatchExtractor.extract_diff_like_content(text)


class PatchValidator:
    """Validate patches by testing if they can be applied"""
    
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
        
        result = ValidationResult(
            instance_id=instance_id, 
            patch_extracted=bool(patch_content.strip()),
            patch_length=len(patch_content)
        )
        
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


class PatchProcessor:
    """Main processor that combines extraction and validation"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.extractor = PatchExtractor()
        self.validator = PatchValidator(verbose=verbose)
    
    def extract_patches(self, input_file: str, output_file: str, overwrite_existing: bool = False):
        """Extract patches from JSONL file"""
        input_path = Path(input_file)
        output_path = Path(output_file)
        
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        processed_count = 0
        extracted_count = 0
        skipped_count = 0
        
        logger.info(f"Extracting patches from {input_file}...")
        
        with open(input_path, 'r', encoding='utf-8') as infile, \
             open(output_path, 'w', encoding='utf-8') as outfile:
            
            for line_num, line in enumerate(infile, 1):
                original_line = line
                line = line.strip()
                
                if not line:
                    outfile.write(original_line)
                    continue
                
                try:
                    data = json.loads(line)
                    processed_count += 1
                    
                    # Skip if generated_patch already exists and not overwriting
                    if 'generated_patch' in data and not overwrite_existing:
                        skipped_count += 1
                        outfile.write(json.dumps(data, ensure_ascii=False) + '\n')
                        continue
                    
                    # Extract patch from full_output
                    full_output = data.get('full_output', '')
                    extracted_patch = self.extractor.extract_patch(full_output)
                    
                    # Update the data with extracted patch
                    data['generated_patch'] = extracted_patch
                    
                    if extracted_patch:
                        extracted_count += 1
                    
                    # Write updated data to output file
                    outfile.write(json.dumps(data, ensure_ascii=False) + '\n')
                    
                    # Progress indicator
                    if processed_count % 100 == 0:
                        logger.info(f"Processed {processed_count} records...")
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON on line {line_num}: {e}")
                    outfile.write(original_line)
                    continue
                except Exception as e:
                    logger.warning(f"Error processing line {line_num}: {e}")
                    outfile.write(original_line)
                    continue
        
        logger.info(f"Extraction complete!")
        logger.info(f"Total records processed: {processed_count}")
        logger.info(f"Patches extracted: {extracted_count}")
        logger.info(f"Records skipped: {skipped_count}")
        logger.info(f"Success rate: {(extracted_count/processed_count*100):.1f}%" if processed_count > 0 else "0%")
    
    def validate_patches(self, predictions_file: str, dataset_file: str, 
                        report_file: Optional[str] = None, max_instances: Optional[int] = None,
                        instance_ids: Optional[List[str]] = None) -> List[ValidationResult]:
        """Validate patches against their repositories"""
        
        # Load predictions
        logger.info(f"Loading predictions from {predictions_file}")
        predictions = {}
        with open(predictions_file, 'r') as f:
            for line in f:
                if line.strip():
                    pred = json.loads(line)
                    # Accept files with either 'generated_patch' (extracted) or 'full_output' (raw)
                    if 'instance_id' in pred:
                        # If no generated_patch, try to extract from full_output on the fly
                        if 'generated_patch' not in pred and 'full_output' in pred:
                            pred['generated_patch'] = self.extractor.extract_patch(pred['full_output'])
                        predictions[pred['instance_id']] = pred
        
        logger.info(f"Loaded {len(predictions)} predictions")
        
        # Load dataset
        logger.info(f"Loading dataset from {dataset_file}")
        dataset = {}
        with open(dataset_file, 'r') as f:
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
        
        if instance_ids:
            instances_to_validate = list(set(instance_ids) & available_instances)
        else:
            instances_to_validate = list(available_instances)
        
        if max_instances:
            instances_to_validate = instances_to_validate[:max_instances]
        
        logger.info(f"Validating {len(instances_to_validate)} instances")
        
        # Validate patches
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
            
            validation_result = self.validator.validate_patch(
                instance_id, patch_content, repo_url, base_commit
            )
            
            results.append(validation_result)
        
        # Generate summary
        self._print_validation_summary(results)
        
        # Save validation report
        if report_file:
            self._save_validation_report(results, report_file)
        
        return results
    
    def extract_and_validate(self, input_file: str, dataset_file: str, 
                           output_file: Optional[str] = None, 
                           report_file: Optional[str] = None,
                           overwrite_existing: bool = False) -> List[ValidationResult]:
        """Extract patches and validate them in one step"""
        
        # Use temporary file if no output specified
        if not output_file:
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
            output_file = temp_file.name
            temp_file.close()
            cleanup_output = True
        else:
            cleanup_output = False
        
        try:
            # Extract patches
            self.extract_patches(input_file, output_file, overwrite_existing)
            
            # Validate patches
            results = self.validate_patches(output_file, dataset_file, report_file)
            
            return results
            
        finally:
            if cleanup_output:
                try:
                    os.unlink(output_file)
                except:
                    pass
    
    def _print_validation_summary(self, results: List[ValidationResult]):
        """Print validation summary"""
        total = len(results)
        valid = sum(1 for r in results if r.valid)
        extracted = sum(1 for r in results if r.patch_extracted)
        
        logger.info("=== VALIDATION SUMMARY ===")
        logger.info(f"Total instances: {total}")
        logger.info(f"Patches extracted: {extracted} ({extracted/total*100:.1f}%)")
        logger.info(f"Valid patches: {valid} ({valid/total*100:.1f}%)")
        logger.info(f"Failed patches: {total-valid} ({(total-valid)/total*100:.1f}%)")
        
        # Show common error patterns
        error_patterns = {}
        for r in results:
            if not r.valid and r.error_message:
                # Extract error type
                if "corrupt patch" in r.error_message.lower():
                    error_type = "Corrupt patch format"
                elif "patch does not apply" in r.error_message.lower():
                    error_type = "Context mismatch"
                elif "no such file" in r.error_message.lower():
                    error_type = "Missing file"
                elif "patch fragment without header" in r.error_message.lower():
                    error_type = "Missing patch header"
                elif "empty patch content" in r.error_message.lower():
                    error_type = "No patch extracted"
                else:
                    error_type = "Other error"
                
                error_patterns[error_type] = error_patterns.get(error_type, 0) + 1
        
        if error_patterns:
            logger.info("\nError breakdown:")
            for error_type, count in sorted(error_patterns.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"  {error_type}: {count}")
    
    def _save_validation_report(self, results: List[ValidationResult], report_file: str):
        """Save validation report to JSON file"""
        logger.info(f"Saving validation report to {report_file}")
        
        total = len(results)
        valid = sum(1 for r in results if r.valid)
        extracted = sum(1 for r in results if r.patch_extracted)
        
        # Error breakdown
        error_patterns = {}
        for r in results:
            if not r.valid and r.error_message:
                if "corrupt patch" in r.error_message.lower():
                    error_type = "Corrupt patch format"
                elif "patch does not apply" in r.error_message.lower():
                    error_type = "Context mismatch"
                elif "no such file" in r.error_message.lower():
                    error_type = "Missing file"
                elif "patch fragment without header" in r.error_message.lower():
                    error_type = "Missing patch header"
                elif "empty patch content" in r.error_message.lower():
                    error_type = "No patch extracted"
                else:
                    error_type = "Other error"
                
                error_patterns[error_type] = error_patterns.get(error_type, 0) + 1
        
        report_data = {
            "summary": {
                "total_instances": total,
                "patches_extracted": extracted,
                "valid_patches": valid,
                "failed_patches": total - valid,
                "extraction_rate": round(extracted/total*100, 2) if total > 0 else 0,
                "validation_rate": round(valid/total*100, 2) if total > 0 else 0
            },
            "error_breakdown": error_patterns,
            "results": [
                {
                    "instance_id": r.instance_id,
                    "patch_extracted": r.patch_extracted,
                    "patch_length": r.patch_length,
                    "valid": r.valid,
                    "error_message": r.error_message
                }
                for r in results
            ]
        }
        
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)

def generate_output_filename(input_file: str, suffix: str = "_processed") -> str:
    """Generate output filename based on input filename"""
    input_path = Path(input_file)
    stem = input_path.stem
    parent = input_path.parent
    return str(parent / f"{stem}{suffix}.jsonl")

def generate_report_filename(input_file: str, suffix: str = "_validation_report") -> str:
    """Generate report filename based on input filename"""
    input_path = Path(input_file)
    stem = input_path.stem
    parent = input_path.parent
    return str(parent / f"{stem}{suffix}.json")


def main():
    parser = argparse.ArgumentParser(
        description="Consolidated patch extraction and validation for Mobile Bench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract patches (auto-generates output filename)
  python patch_processor.py extract input.jsonl
  python patch_processor.py extract input.jsonl custom_output.jsonl
  
  # Validate raw model outputs OR processed patches (auto-generates report)
  python patch_processor.py validate --predictions raw_model_outputs.jsonl --dataset data.jsonl
  python patch_processor.py validate --predictions processed_results.jsonl --dataset data.jsonl --report custom_report.json
  
  # Extract and validate in one step (auto-generates both files)
  python patch_processor.py extract-and-validate --predictions input.jsonl --dataset data.jsonl
  
  # Specify custom filenames
  python patch_processor.py extract-and-validate --predictions input.jsonl --dataset data.jsonl --output results.jsonl --report validation.json
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract patches from model outputs')
    extract_parser.add_argument('input_file', help='Input JSONL file with model outputs')
    extract_parser.add_argument('output_file', nargs='?', help='Output JSONL file with extracted patches (auto-generated if not specified)')
    extract_parser.add_argument('--overwrite-existing', action='store_true',
                               help='Overwrite existing generated_patch fields')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate existing patches')
    validate_parser.add_argument('--predictions', required=True, help='Input predictions JSONL file (can be raw model outputs or processed patches)')
    validate_parser.add_argument('--dataset', required=True, help='Dataset JSONL file with repo info')
    validate_parser.add_argument('--report', help='Validation report JSON file (auto-generated if not specified)')
    validate_parser.add_argument('--max-instances', type=int, help='Limit number of instances to validate')
    validate_parser.add_argument('--instance-ids', nargs='+', help='Specific instance IDs to validate')
    
    # Extract and validate command
    extract_validate_parser = subparsers.add_parser('extract-and-validate', 
                                                   help='Extract patches and validate them')
    extract_validate_parser.add_argument('--predictions', required=True, help='Input JSONL file with model outputs')
    extract_validate_parser.add_argument('--dataset', required=True, help='Dataset JSONL file with repo info')
    extract_validate_parser.add_argument('--output', help='Output JSONL file with extracted patches (auto-generated if not specified)')
    extract_validate_parser.add_argument('--report', help='Validation report JSON file (auto-generated if not specified)')
    extract_validate_parser.add_argument('--overwrite-existing', action='store_true',
                                        help='Overwrite existing generated_patch fields')
    
    # Global options
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    processor = PatchProcessor(verbose=args.verbose)
    
    try:
        if args.command == 'extract':
            # Auto-generate output filename if not provided
            output_file = args.output_file or generate_output_filename(args.input_file, "_extracted")
            logger.info(f"Output will be saved to: {output_file}")
            processor.extract_patches(args.input_file, output_file, args.overwrite_existing)
            
        elif args.command == 'validate':
            # Auto-generate report filename if not provided
            report_file = args.report or generate_report_filename(args.predictions, "_validation_report")
            if not args.report:
                logger.info(f"Report will be saved to: {report_file}")
            processor.validate_patches(
                args.predictions, args.dataset, report_file, 
                args.max_instances, args.instance_ids
            )
            
        elif args.command == 'extract-and-validate':
            # Auto-generate filenames if not provided
            output_file = args.output or generate_output_filename(args.predictions, "_processed")
            report_file = args.report or generate_report_filename(args.predictions, "_validation_report")
            if not args.output:
                logger.info(f"Output will be saved to: {output_file}")
            if not args.report:
                logger.info(f"Report will be saved to: {report_file}")
            processor.extract_and_validate(
                args.predictions, args.dataset, output_file, 
                report_file, args.overwrite_existing
            )
        
        return 0
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())