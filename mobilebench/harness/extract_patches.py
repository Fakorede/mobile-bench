#!/usr/bin/env python3
"""
Script to extract valid patches from the `full_output` field in a JSONL file
and save them to a `generated_patch` field.

Usage:
    python extract_patches.py input.jsonl output.jsonl
    python extract_patches.py input.jsonl output.jsonl --overwrite-existing
"""

import json
import argparse
import re
from typing import List, Optional
from pathlib import Path


def extract_patch_from_markdown(text: str) -> str:
    """Extract patches from markdown code blocks."""
    # Pattern to match markdown code blocks with diff/patch language
    patterns = [
        r'```(?:diff|patch)\n(.*?)\n```',
        r'```\n(--- a/.*?)\n```',  # Patches that start with --- a/
        r'```(?:text)?\n((?:--- a/|diff --git).*?)\n```',  # Generic code blocks containing patches
    ]
    
    patches = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL | re.MULTILINE)
        for match in matches:
            cleaned_patch = clean_and_validate_patch(match)
            if cleaned_patch:
                patches.append(cleaned_patch)
    
    if patches:
        return '\n'.join(patches)
    
    return ""


def extract_raw_patch(text: str) -> str:
    """Extract patches from raw text (no markdown formatting)."""
    lines = text.split('\n')
    patches = []
    current_patch = []
    in_patch = False
    consecutive_non_patch_lines = 0
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        # Check for patch start indicators
        if is_patch_start(line):
            # If we were already in a patch, save the current one
            if in_patch and current_patch:
                patch_content = '\n'.join(current_patch)
                cleaned = clean_and_validate_patch(patch_content)
                if cleaned:
                    patches.append(cleaned)
            
            # Start new patch
            current_patch = [line]
            in_patch = True
            consecutive_non_patch_lines = 0
            continue
        
        if in_patch:
            # Check if this looks like a patch line
            if is_patch_line(line):
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
                    cleaned = clean_and_validate_patch(patch_content)
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
        while current_patch and not is_patch_line(current_patch[-1]) and current_patch[-1].strip() != "":
            current_patch.pop()
        
        if current_patch:
            patch_content = '\n'.join(current_patch)
            cleaned = clean_and_validate_patch(patch_content)
            if cleaned:
                patches.append(cleaned)
    
    return '\n'.join(patches) if patches else ""


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
        return clean_and_validate_patch('\n'.join(diff_lines))
    
    return ""


def is_patch_start(line: str) -> bool:
    """Check if line indicates the start of a patch."""
    indicators = [
        'diff --git',
        '--- a/',
        '+++ b/',
        '@@',
    ]
    return any(indicator in line for indicator in indicators)


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


def extract_patch(text: str) -> str:
    """
    Enhanced patch extraction from model output.
    Handles markdown code blocks, multiple patches, and various formats.
    """
    if not text or not text.strip():
        return ""
    
    # First, try to extract from markdown code blocks
    markdown_patch = extract_patch_from_markdown(text)
    if markdown_patch:
        return markdown_patch
    
    # If no markdown blocks, try to extract raw patch content
    raw_patch = extract_raw_patch(text)
    if raw_patch:
        return raw_patch
    
    # Fallback: look for any diff-like content
    return extract_diff_like_content(text)


def process_jsonl_file(input_file: str, output_file: str, overwrite_existing: bool = False):
    """Process JSONL file and extract patches from full_output field."""
    
    input_path = Path(input_file)
    output_path = Path(output_file)
    
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    processed_count = 0
    extracted_count = 0
    skipped_count = 0
    
    print(f"Processing {input_file}...")
    
    with open(input_path, 'r', encoding='utf-8') as infile, \
         open(output_path, 'w', encoding='utf-8') as outfile:
        
        for line_num, line in enumerate(infile, 1):
            original_line = line
            line = line.strip()
            
            # Debug: print first few lines
            if line_num <= 3:
                print(f"Debug line {line_num}: length={len(line)}, empty={not bool(line)}")
            
            if not line:
                # Write empty lines as-is
                outfile.write(original_line)
                continue
            
            try:
                data = json.loads(line)
                processed_count += 1
                
                # Debug for first few records
                if processed_count <= 3:
                    print(f"Debug: Processing record {processed_count}, has generated_patch: {'generated_patch' in data}")
                
                # Skip if generated_patch already exists and not overwriting
                if 'generated_patch' in data and not overwrite_existing:
                    skipped_count += 1
                    outfile.write(json.dumps(data, ensure_ascii=False) + '\n')
                    if processed_count <= 3:
                        print(f"Debug: Skipped record {processed_count} (already has generated_patch)")
                    continue
                
                # Extract patch from full_output
                full_output = data.get('full_output', '')
                if processed_count <= 3:
                    print(f"Debug: full_output length: {len(full_output)}")
                
                extracted_patch = extract_patch(full_output)
                
                if processed_count <= 3:
                    print(f"Debug: extracted_patch length: {len(extracted_patch)}")
                
                # Update the data with extracted patch
                data['generated_patch'] = extracted_patch
                
                if extracted_patch:
                    extracted_count += 1
                
                # Write updated data to output file
                outfile.write(json.dumps(data, ensure_ascii=False) + '\n')
                
                # Progress indicator
                if processed_count % 100 == 0:
                    print(f"Processed {processed_count} records...")
                    
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse JSON on line {line_num}: {e}")
                # Write the original line if JSON parsing fails
                outfile.write(original_line)
                continue
            except Exception as e:
                print(f"Warning: Error processing line {line_num}: {e}")
                # Write the original line if processing fails
                outfile.write(original_line)
                continue
    
    print(f"\nProcessing complete!")
    print(f"Total records processed: {processed_count}")
    print(f"Patches extracted: {extracted_count}")
    print(f"Records skipped (already had generated_patch): {skipped_count}")
    print(f"Success rate: {(extracted_count/processed_count*100):.1f}%" if processed_count > 0 else "0%")
    print(f"Output saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract valid patches from full_output field in JSONL file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python extract_patches.py input.jsonl output.jsonl
  
  # Overwrite existing generated_patch fields
  python extract_patches.py input.jsonl output.jsonl --overwrite-existing
  
  # Process in place (overwrite input file)
  python extract_patches.py data.jsonl data.jsonl --overwrite-existing
        """
    )
    
    parser.add_argument("input_file", help="Input JSONL file")
    parser.add_argument("output_file", help="Output JSONL file")
    parser.add_argument("--overwrite-existing", action="store_true",
                       help="Overwrite existing generated_patch fields")
    
    args = parser.parse_args()
    
    try:
        process_jsonl_file(args.input_file, args.output_file, args.overwrite_existing)
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())