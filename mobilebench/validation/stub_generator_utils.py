#!/usr/bin/env python3
"""
stub_generator_utils.py - LLM-Powered Stub Generation Utilities

This module handles LLM-based stub generation for compilation failures using OpenRouter API.
"""

import os
import re
import time
import asyncio
import aiohttp
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from dataclasses import dataclass

logger = logging.getLogger(__name__)


class JavaElement:
    """Represents a Java element (field, method, constructor, etc.)"""
    def __init__(self, element_type: str, name: str, signature: str, content: str, 
                 start_line: int = 0, end_line: int = 0):
        self.element_type = element_type  # 'field', 'method', 'constructor', 'constant'
        self.name = name
        self.signature = signature  # Full signature for comparison
        self.content = content
        self.start_line = start_line
        self.end_line = end_line


class JavaFileAnalyzer:
    """Analyzes Java file structure to identify existing elements"""
    
    def __init__(self, content: str):
        self.content = content
        self.lines = content.split('\n')
        
    def extract_elements(self) -> List[JavaElement]:
        """Extract all fields, methods, and constructors from the Java file"""
        elements = []
        
        # Find class boundaries
        class_start, class_end = self._find_class_boundaries()
        if class_start == -1:
            logger.warning("Could not find class boundaries in Java file")
            return elements
        
        # Extract elements within the class
        elements.extend(self._extract_fields(class_start, class_end))
        elements.extend(self._extract_methods(class_start, class_end))
        elements.extend(self._extract_constants(class_start, class_end))
        
        return elements
    
    def _find_class_boundaries(self) -> Tuple[int, int]:
        """Find the start and end lines of the main class"""
        class_pattern = r'^(public\s+)?class\s+\w+.*\{'
        
        class_start = -1
        brace_count = 0
        
        for i, line in enumerate(self.lines):
            if class_start == -1 and re.match(class_pattern, line.strip()):
                class_start = i
                brace_count += line.count('{') - line.count('}')
            elif class_start != -1:
                brace_count += line.count('{') - line.count('}')
                if brace_count == 0:
                    return class_start, i
        
        return class_start, len(self.lines) - 1
    
    def _extract_fields(self, start: int, end: int) -> List[JavaElement]:
        """Extract field declarations"""
        fields = []
        field_pattern = r'^\s*(private|protected|public)?\s+\w+(?:\[\])?\s+(\w+)\s*[=;]'
        
        for i in range(start + 1, end):
            line = self.lines[i].strip()
            if not line or line.startswith('//') or line.startswith('*'):
                continue
                
            match = re.match(field_pattern, line)
            if match and not self._is_inside_method(i, start, end):
                field_name = match.group(2)
                signature = self._normalize_field_signature(line)
                
                fields.append(JavaElement(
                    element_type='field',
                    name=field_name,
                    signature=signature,
                    content=line,
                    start_line=i,
                    end_line=i
                ))
        
        return fields
    
    def _extract_methods(self, start: int, end: int) -> List[JavaElement]:
        """Extract method declarations"""
        methods = []
        method_pattern = r'^\s*(private|protected|public)?\s+(?:static\s+)?(?:\w+\s+)*(\w+)\s*\('
        
        i = start + 1
        while i < end:
            line = self.lines[i].strip()
            
            if not line or line.startswith('//') or line.startswith('*'):
                i += 1
                continue
                
            match = re.match(method_pattern, line)
            if match:
                method_name = match.group(2)
                
                # Don't treat class names as methods
                if method_name.istitle():
                    i += 1
                    continue
                
                # Find method boundaries
                method_start = i
                method_end = self._find_method_end(i, end)
                
                if method_end > method_start:
                    method_content = '\n'.join(self.lines[method_start:method_end + 1])
                    signature = self._normalize_method_signature(method_content)
                    
                    methods.append(JavaElement(
                        element_type='method',
                        name=method_name,
                        signature=signature,
                        content=method_content,
                        start_line=method_start,
                        end_line=method_end
                    ))
                
                i = method_end + 1
            else:
                i += 1
        
        return methods
    
    def _extract_constants(self, start: int, end: int) -> List[JavaElement]:
        """Extract constant declarations (public static final)"""
        constants = []
        constant_pattern = r'^\s*public\s+static\s+final\s+\w+\s+(\w+)\s*='
        
        for i in range(start + 1, end):
            line = self.lines[i].strip()
            match = re.match(constant_pattern, line)
            
            if match:
                constant_name = match.group(1)
                signature = self._normalize_constant_signature(line)
                
                constants.append(JavaElement(
                    element_type='constant',
                    name=constant_name,
                    signature=signature,
                    content=line,
                    start_line=i,
                    end_line=i
                ))
        
        return constants
    
    def _find_method_end(self, start: int, class_end: int) -> int:
        """Find the end line of a method"""
        brace_count = 0
        found_opening_brace = False
        
        for i in range(start, class_end):
            line = self.lines[i]
            
            for char in line:
                if char == '{':
                    brace_count += 1
                    found_opening_brace = True
                elif char == '}':
                    brace_count -= 1
                    
            if found_opening_brace and brace_count == 0:
                return i
                
        return start  # Fallback
    
    def _is_inside_method(self, line_num: int, class_start: int, class_end: int) -> bool:
        """Check if a line is inside a method body"""
        method_pattern = r'^\s*(private|protected|public)?\s+(?:static\s+)?(?:\w+\s+)*\w+\s*\('
        
        brace_count = 0
        inside_method = False
        
        for i in range(class_start + 1, min(line_num + 1, class_end)):
            line = self.lines[i].strip()
            
            if re.match(method_pattern, line) and not inside_method:
                inside_method = True
                brace_count = 0
                
            if inside_method:
                brace_count += line.count('{') - line.count('}')
                if brace_count == 0 and i > class_start + 1:
                    inside_method = False
                elif i == line_num:
                    return inside_method
                    
        return False
    
    def _normalize_field_signature(self, line: str) -> str:
        """Create normalized signature for field comparison"""
        # Remove comments and normalize whitespace
        line = re.sub(r'//.*$', '', line).strip()
        line = re.sub(r'\s+', ' ', line)
        
        # Extract field name for signature
        match = re.match(r'^\s*(?:private|protected|public)?\s+(\w+(?:\[\])?)\s+(\w+)', line)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return line
    
    def _normalize_method_signature(self, method_content: str) -> str:
        """Create normalized signature for method comparison"""
        first_line = method_content.split('\n')[0].strip()
        
        # Remove comments and normalize whitespace
        first_line = re.sub(r'//.*$', '', first_line).strip()
        first_line = re.sub(r'\s+', ' ', first_line)
        
        # Extract method signature (up to opening brace)
        signature = first_line.split('{')[0].strip()
        
        return signature
    
    def _normalize_constant_signature(self, line: str) -> str:
        """Create normalized signature for constant comparison"""
        # Extract constant name
        match = re.match(r'^\s*public\s+static\s+final\s+\w+\s+(\w+)', line)
        if match:
            return f"KEY_{match.group(1)}"
        return line


@dataclass
class StubGenerationResult:
    """Result of LLM stub generation."""
    success: bool
    generated_stubs: str
    files_created: Dict[str, str]  # file_path -> content
    error_message: Optional[str] = None
    api_cost: float = 0.0
    response_time: float = 0.0
    model_used: str = ""


class StubGenerator:
    """Handles LLM-powered stub generation using OpenRouter API."""
    
    # Context management constants
    TARGET_CONTEXT_TOKENS = 180000  # Target context window size
    CHARS_PER_TOKEN_ESTIMATE = 4    # Rough estimate: 1 token ≈ 4 characters
    MIN_BUILD_LOG_CHARS = 1000      # Minimum build log content to include
    MAX_BUILD_LOG_CHARS = 50000     # Maximum build log content to include
    
    def __init__(self, api_key: str, model: str = "anthropic/claude-3.7-sonnet", base_output_dir: str = "validation_results"):
        self.api_key = api_key
        self.model = model
        self.model_costs = {
            "anthropic/claude-3.7-sonnet": {"input": 0.000003, "output": 0.000015},
            "anthropic/claude-4-sonnet-20250522": {"input": 0.000015, "output": 0.000075},
            "anthropic/claude-4-opus-20250522": {"input": 0.000075, "output": 0.000375},
            "deepseek/deepseek-chat-v3-0324": {"input": 0.0000014, "output": 0.0000028},
            "openai/gpt-4o-2024-08-06": {"input": 0.0000025, "output": 0.00001}
        }

        self.base_output_dir = Path(base_output_dir)
        self.base_output_dir.mkdir(exist_ok=True, parents=True)

    def _get_instance_output_dir(self, instance_id: str) -> Path:
        """Get the output directory for a specific instance."""
        if hasattr(self, '_current_instance_id') and self._current_instance_id:
            instance_dir = self.base_output_dir / self._current_instance_id / "stub_generation_logs"
        else:
            # Fallback to generic logs if no instance ID available
            instance_dir = self.base_output_dir / "stub_generation_logs"
        
        instance_dir.mkdir(exist_ok=True, parents=True)
        return instance_dir

    async def generate_stubs(self, build_log: str, test_patch: str, 
                           oracle_files: Dict[str, str], instance_id: str = None) -> 'StubGenerationResult':
        """
        Generate stub code using LLM with intelligent context management.
        
        Args:
            build_log: Complete build log with compilation errors
            test_patch: The test patch that was applied
            oracle_files: Contents of files modified in solution patch
            
        Returns:
            StubGenerationResult with generated code and metadata
        """
        if instance_id:
            self._current_instance_id = instance_id

        logger.info(f"Generating stubs using model {self.model}")
        start_time = time.time()
        
        try:
            # Step 1: Extract and compute relevant compilation errors from build log
            logger.info(f"Original build log size: {len(build_log)} chars")
            relevant_build_log = self._compute_relevant_build_log(build_log)
            logger.info(f"Relevant build log size: {len(relevant_build_log)} chars")
            
            # Step 2: Create initial prompt components (without build log)
            base_prompt = self._create_base_prompt(test_patch, oracle_files)
            
            # Step 3: Estimate context size and determine how much build log to include
            base_prompt_tokens = len(base_prompt) // self.CHARS_PER_TOKEN_ESTIMATE
            available_tokens_for_build_log = self.TARGET_CONTEXT_TOKENS - base_prompt_tokens - 1000  # Reserve 1000 tokens for response
            available_chars_for_build_log = available_tokens_for_build_log * self.CHARS_PER_TOKEN_ESTIMATE
            
            logger.info(f"Base prompt tokens: ~{base_prompt_tokens}")
            logger.info(f"Available tokens for build log: ~{available_tokens_for_build_log}")
            logger.info(f"Available chars for build log: ~{available_chars_for_build_log}")
            
            # Step 4: Truncate relevant build log to fit context window
            final_build_log = self._fit_build_log_to_context(
                relevant_build_log, 
                available_chars_for_build_log
            )
            logger.info(f"Final build log size: {len(final_build_log)} chars")
            
            # Step 5: Create final prompt
            final_prompt = base_prompt + f"""

**Build Log (compilation errors):**
```
{final_build_log}
```
"""
            
            # Final token count verification
            final_tokens = len(final_prompt) // self.CHARS_PER_TOKEN_ESTIMATE
            logger.info(f"Final prompt size: {len(final_prompt)} chars (~{final_tokens} tokens)")
            
            # Log prompt to file for debugging
            self._log_prompt_to_file(final_prompt, instance_id)
            
            # Step 6: Call LLM API
            result = await self._call_llm_api(final_prompt)
            
            if result and result.get('choices'):
                generated_content = result['choices'][0]['message']['content']
                files_created = self._parse_generated_stubs(generated_content)
                
                response_time = time.time() - start_time
                usage = result.get('usage', {})
                cost = self._calculate_cost(usage)
                
                # Log response for debugging
                self._log_response_to_file(generated_content, files_created, instance_id)
                
                logger.info(f"Stub generation completed: {len(files_created)} files, "
                           f"cost=${cost:.4f}, time={response_time:.1f}s")
                
                return StubGenerationResult(
                    success=True,
                    generated_stubs=generated_content,
                    files_created=files_created,
                    api_cost=cost,
                    response_time=response_time,
                    model_used=self.model
                )
            else:
                raise Exception("No valid response from LLM API")
                
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"Error generating stubs: {e}")
            return StubGenerationResult(
                success=False,
                generated_stubs="",
                files_created={},
                error_message=str(e),
                response_time=response_time,
                model_used=self.model
            )

    def _compute_relevant_build_log(self, build_log: str) -> str:
        """
        Extract only the relevant compilation errors from verbose Gradle build log.
        This is the key function that filters out noise and focuses on compilation issues.
        """
        lines = build_log.split('\n')
        relevant_lines = []
        
        # Patterns to identify compilation errors
        error_patterns = [
            r'error: cannot find symbol',
            r'error: package .+ does not exist',
            r'error: .+ cannot be resolved',
            r'error: The method .+ is undefined',
            r'Compilation failed',
            r'BUILD FAILED',
            r'Execution failed for task'
        ]
        
        # Patterns for file paths and line numbers with errors
        file_error_patterns = [
            r'^/.+\.java:\d+: error:',
            r'^/.+\.kt:\d+: error:',
        ]
        
        # Patterns to exclude (verbose Gradle output)
        exclude_patterns = [
            r'Caching disabled',
            r'Task .+ is not up-to-date',
            r'No history is available',
            r'Simple merging task',
            r'AAPT2 aapt2.*shutdown',
            r'Resolve mutations for',
            r'.*\.gradle/caches/',
            r'AndroidManifest\.xml',
            r'transformed/.*\.xml',
            r'at org\.gradle\.',
            r'Daemon #\d+',
            r'Working directory:',
            r'Using Java:'
        ]
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # Skip verbose gradle output
            if any(re.search(pattern, line) for pattern in exclude_patterns):
                i += 1
                continue
            
            # Check if this line contains a compilation error
            is_error_line = any(re.search(pattern, line) for pattern in error_patterns)
            is_file_error = any(re.search(pattern, line) for pattern in file_error_patterns)
            
            if is_error_line or is_file_error:
                # Found an error line, include it and context
                relevant_lines.append(line)
                
                # If this is a file error, also include the next few lines for context
                if is_file_error:
                    context_lines = 0
                    j = i + 1
                    while j < len(lines) and context_lines < 5:
                        context_line = lines[j].strip()
                        if context_line and not any(re.search(pattern, context_line) for pattern in exclude_patterns):
                            relevant_lines.append(context_line)
                            context_lines += 1
                            # Stop if we hit another file error or major break
                            if any(re.search(pattern, context_line) for pattern in file_error_patterns):
                                break
                        j += 1
                    i = j - 1  # Skip the context lines we just processed
            
            # Include lines with symbol information and locations
            elif 'symbol:' in line or 'location:' in line:
                relevant_lines.append(line)
            
            # Include build failure summary
            elif 'FAILURE: Build failed' in line:
                relevant_lines.append(line)
                # Include next few lines for context
                for j in range(i + 1, min(i + 10, len(lines))):
                    if lines[j].strip():
                        relevant_lines.append(lines[j].strip())
                        if 'Try:' in lines[j]:
                            break
            
            i += 1
        
        relevant_log = '\n'.join(relevant_lines)
        
        # If we didn't find any obvious compilation errors, fall back to the end of the log
        if len(relevant_log) < 500:  # Too little relevant content found
            logger.warning("Limited compilation errors found, including build log tail")
            # Take last 10,000 characters which usually contain the errors
            fallback_log = build_log[-10000:] if len(build_log) > 10000 else build_log
            relevant_log = relevant_log + "\n\n" + fallback_log
        
        return relevant_log

    def _fit_build_log_to_context(self, relevant_build_log: str, max_chars: int) -> str:
        """
        Fit the relevant build log to the available context window.
        Prioritizes keeping the most important compilation errors.
        """
        if len(relevant_build_log) <= max_chars:
            return relevant_build_log
        
        if max_chars < self.MIN_BUILD_LOG_CHARS:
            logger.warning(f"Very limited space for build log: {max_chars} chars")
            return relevant_build_log[:max_chars] + "\n... [truncated due to context limit]"
        
        # Strategy: Keep the most important error information
        lines = relevant_build_log.split('\n')
        important_lines = []
        regular_lines = []
        
        # Patterns for high-priority lines
        high_priority_patterns = [
            r'error: cannot find symbol',
            r'symbol:.*method',
            r'symbol:.*class', 
            r'location:.*variable.*of type',
            r'BUILD FAILED',
            r'Compilation failed'
        ]
        
        for line in lines:
            if any(re.search(pattern, line) for pattern in high_priority_patterns):
                important_lines.append(line)
            else:
                regular_lines.append(line)
        
        # Build result prioritizing important lines
        result_lines = important_lines[:]
        result_length = sum(len(line) + 1 for line in result_lines)  # +1 for newline
        
        # Add regular lines until we reach the limit
        for line in regular_lines:
            if result_length + len(line) + 1 <= max_chars:
                result_lines.append(line)
                result_length += len(line) + 1
            else:
                break
        
        result = '\n'.join(result_lines)
        
        if len(result) >= max_chars:
            result = result[:max_chars] + "\n... [truncated for context]"
        
        return result

    def _create_base_prompt(self, test_patch: str, oracle_files: Dict[str, str]) -> str:
        """Create the base prompt without the build log section."""
        oracle_section = ""
        if oracle_files:
            oracle_section = "\n\n**Oracle Files (contents of files modified in the solution patch):**\n"
            for filename, content in oracle_files.items():
                oracle_section += f"\n--- {filename} ---\n{content}\n"
        
        prompt = f"""You are an Android development expert. A test patch has been applied to a project, but the build is failing due to compilation errors. Your task is to generate minimal stub classes, methods, and fields that will make the build compile successfully.

**Important Guidelines:**
- Analyze the compilation errors in the build log carefully
- Use the test patch to understand what the tests are trying to access
- If oracle files are provided, examine them to understand the expected implementation
- Only generate what's absolutely necessary for compilation
- Use simple default implementations
- Use appropriate default return values (null, false, 0, empty collections)
- Include proper imports if needed
- Focus on making tests runnable, not making them pass
- Include proper package declarations and imports

**CRITICAL INSTRUCTIONS:**
1. For MISSING FILES: Generate complete stub classes
2. For EXISTING FILES: Generate ONLY the missing methods/fields that need to be added
3. PRESERVE existing functionality - do not regenerate existing methods
4. Use oracle files to understand expected method signatures

**Analysis Guidelines:**
1. "cannot find symbol: class XYZ" → Generate complete new file for XYZ
2. "cannot find symbol: method methodName" in existing class → Generate only that method
3. "cannot find symbol: variable fieldName" → Generate only that field
4. "package com.example.missing does not exist" → Generate missing package files
5. Look at oracle files to understand proper method signatures and return types

**Test Patch Applied:**
```
{test_patch}
```{oracle_section}

**Output Format:**
For NEW files, provide complete class:

```FILE: path/to/NewClass.java
package com.example.package;

// other imports as needed

public class NewClass {{
    // Minimal stub implementation
    // For fields that are missing
    public static final String FIELD_NAME = "default_value";
    
    // For methods that are missing
    public ReturnType methodName(ParamType param) {{
        return null; // or appropriate default
    }}
}}
```

For EXISTING files, provide only missing pieces:

```FILE: path/to/ExistingClass.java
// Missing field only
public static final String MISSING_FIELD = "default_value";

// Missing method only - will be merged with existing file
public ReturnType missingMethod(ParamType param) {{
    return null; // or appropriate default
}}
```

Generate the minimal stubs needed to fix the compilation errors:"""
        
        return prompt

    def _log_prompt_to_file(self, prompt: str, instance_id: str = None):
        """Log the prompt to an organized file."""
        if instance_id:
            self._current_instance_id = instance_id
        
        instance_dir = self._get_instance_output_dir(instance_id)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        prompt_file = instance_dir / f"prompt_{timestamp}.log"
        
        try:
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(f"Stub Generation Prompt\n")
                f.write(f"Instance: {instance_id or 'unknown'}\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Prompt length: {len(prompt)} chars\n")
                f.write("=" * 80 + "\n")
                f.write(prompt)
            
            logger.info(f"Saved prompt to: {prompt_file}")
        except Exception as e:
            logger.error(f"Error saving prompt to file: {e}")

    def _log_response_to_file(self, response: str, files_created: Dict[str, str], instance_id: str = None):
        """Log the LLM response to an organized file."""
        if instance_id:
            self._current_instance_id = instance_id
        
        instance_dir = self._get_instance_output_dir(instance_id)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        response_file = instance_dir / f"response_{timestamp}.log"
        
        try:
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write(f"Stub Generation Response\n")
                f.write(f"Instance: {instance_id or 'unknown'}\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Response length: {len(response)} chars\n")
                f.write(f"Files created: {len(files_created)}\n")
                f.write("=" * 80 + "\n")
                f.write("FILES CREATED:\n")
                for file_path, content in files_created.items():
                    f.write(f"  - {file_path} ({len(content)} chars)\n")
                f.write("\n" + "=" * 80 + "\n")
                f.write("FULL RESPONSE:\n")
                f.write(response)
            
            logger.info(f"Saved response to: {response_file}")
        except Exception as e:
            logger.error(f"Error saving response to file: {e}")

    async def _call_llm_api(self, prompt: str) -> Dict[str, Any]:
        """Call the OpenRouter API with the prompt."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/swebench",
            "X-Title": "SWE-bench Stub Generator"
        }
        
        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": 8192,
            "temperature": 0.1,
            "top_p": 0.95,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"API call failed with status {response.status}: {error_text}")

    def _parse_generated_stubs(self, content: str) -> Dict[str, str]:
        """Parse the generated content - handles ```FILE: format specifically."""
        files = {}
        
        # Split on ```FILE: markers
        sections = content.split('```FILE:')
        
        for section in sections[1:]:  # Skip first empty section
            lines = section.split('\n')
            if not lines:
                continue
                
            # First line is the file path
            file_path = lines[0].strip()
            
            # Collect content lines until closing ``` 
            content_lines = []
            for line in lines[1:]:
                if line.strip() == '```':
                    break
                content_lines.append(line)
            
            file_content = '\n'.join(content_lines).strip()
            
            if file_content:
                files[file_path] = file_content
                logger.info(f"Parsed {file_path}: {len(file_content)} chars")
        
        return files

    def _calculate_cost(self, usage: Dict[str, Any]) -> float:
        """Calculate API cost based on token usage."""
        input_tokens = usage.get('prompt_tokens', 0)
        output_tokens = usage.get('completion_tokens', 0)
        
        if self.model in self.model_costs:
            costs = self.model_costs[self.model]
            return (input_tokens * costs["input"]) + (output_tokens * costs["output"])
        
        # Fallback rough estimation for unknown models
        return (input_tokens * 0.000003) + (output_tokens * 0.000015)


class SmartStubApplicator:
    """Applies stubs intelligently without overwriting existing functionality."""
    
    def __init__(self, containers_manager, base_output_dir: str = "validation_results"):
        self.containers = containers_manager
        self.base_output_dir = Path(base_output_dir)
        self.base_output_dir.mkdir(exist_ok=True, parents=True)

    def _get_instance_output_dir(self, instance_id: str) -> Path:
        """Get the output directory for a specific instance."""
        instance_dir = self.base_output_dir / instance_id / "stub_logs"
        instance_dir.mkdir(exist_ok=True, parents=True)
        return instance_dir
    
    def apply_stubs(self, instance_id: str, stub_files: Dict[str, str]) -> bool:
        """Apply generated stub files intelligently."""
        logger.info(f"Applying {len(stub_files)} stub files intelligently for instance {instance_id}")
        
        success_count = 0
        
        for file_path, stub_content in stub_files.items():
            if self._apply_stub_intelligently(instance_id, file_path, stub_content):
                success_count += 1
            else:
                logger.warning(f"Failed to apply stub file: {file_path}")
        
        logger.info(f"Successfully applied {success_count}/{len(stub_files)} stub files")
        return success_count == len(stub_files)
    
    def _apply_stub_intelligently(self, instance_id: str, file_path: str, stub_content: str) -> bool:
        """Apply stub intelligently - create new or merge with existing."""
        try:
            # Check if file exists
            check_command = f"cd /workspace && test -f {file_path}"
            exit_code, _ = self.containers.exec_command(
                instance_id, check_command, workdir="/workspace", timeout=10
            )
            
            if exit_code != 0:
                # File doesn't exist, create it
                return self._create_new_file(instance_id, file_path, stub_content)
            else:
                # File exists, merge intelligently
                return self._merge_with_existing_file(instance_id, file_path, stub_content)
                
        except Exception as e:
            logger.error(f"Error applying stub to {file_path}: {e}")
            return False
    
    def _create_new_file(self, instance_id: str, file_path: str, stub_content: str) -> bool:
        """Create a new file with stub content."""
        try:
            # Ensure directory exists
            dir_path = '/'.join(file_path.split('/')[:-1])
            if dir_path:
                mkdir_command = f"cd /workspace && mkdir -p {dir_path}"
                self.containers.exec_command(instance_id, mkdir_command, workdir="/workspace", timeout=30)
            
            # Write file
            write_command = f"""cd /workspace && cat > {file_path} << 'STUB_EOF'
{stub_content}
STUB_EOF"""
            
            exit_code, output = self.containers.exec_command(
                instance_id, write_command, workdir="/workspace", timeout=60
            )
            
            if exit_code == 0:
                logger.info(f"Successfully created new stub file: {file_path}")
                return True
            else:
                logger.error(f"Failed to create new file {file_path}: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating new file {file_path}: {e}")
            return False

    def _merge_with_existing_file(self, instance_id: str, file_path: str, stub_content: str) -> bool:
        """Merge stub content with existing file intelligently."""
        try:
            # Read existing file
            read_command = f"cd /workspace && cat {file_path}"
            exit_code, existing_content = self.containers.exec_command(
                instance_id, read_command, workdir="/workspace", timeout=30
            )
            
            if exit_code != 0:
                logger.error(f"Could not read existing file {file_path}")
                return False
            
            # Parse and merge content
            merged_content = self._merge_java_content(existing_content, stub_content, file_path)
            
            if merged_content == existing_content:
                logger.info(f"No changes needed for {file_path}")
                return True
            
            # Validate merged content before writing
            if not self._validate_java_syntax(merged_content):
                logger.error(f"Merged content for {file_path} has syntax errors, skipping")
                return False
            
            # Write merged content
            write_command = f"""cd /workspace && cat > {file_path} << 'MERGE_EOF'
{merged_content}
MERGE_EOF"""
            
            exit_code, output = self.containers.exec_command(
                instance_id, write_command, workdir="/workspace", timeout=60
            )
            
            if exit_code == 0:
                logger.info(f"Successfully merged stub content into {file_path}")
                return True
            else:
                logger.error(f"Failed to write merged content to {file_path}: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Error merging stub with existing file {file_path}: {e}")
            return False
    
    def _merge_java_content(self, existing: str, stub: str, file_path: str) -> str:
        """Intelligently merge stub content with existing Java file."""
        logger.info(f"Merging stub content into {file_path}")
        
        # Analyze existing file
        analyzer = JavaFileAnalyzer(existing)
        existing_elements = analyzer.extract_elements()
        
        # Extract elements from stub
        stub_elements = self._extract_stub_elements(stub)
        
        # Filter out elements that already exist
        new_elements = []
        for stub_elem in stub_elements:
            if not self._element_exists(stub_elem, existing_elements):
                new_elements.append(stub_elem)
                logger.info(f"Will add new {stub_elem.element_type}: {stub_elem.name}")
            else:
                logger.info(f"Skipping existing {stub_elem.element_type}: {stub_elem.name}")
        
        if not new_elements:
            logger.info(f"No new elements to add to {file_path}")
            return existing
        
        # Insert new elements into existing file
        return self._insert_elements_into_java_file(existing, new_elements)
    
    def _extract_stub_elements(self, stub_content: str) -> List[JavaElement]:
        """Extract elements from stub content."""
        elements = []
        lines = stub_content.split('\n')
        
        current_element = None
        element_lines = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            if not line or line.startswith('//') or line.startswith('*'):
                if current_element:
                    element_lines.append(line)
                continue
            
            # Detect field
            field_match = re.match(r'^\s*(private|protected|public)?\s+\w+(?:\[\])?\s+(\w+)\s*[=;]', line)
            if field_match:
                if current_element:
                    elements.append(self._create_element_from_lines(current_element, element_lines))
                
                field_name = field_match.group(2)
                current_element = ('field', field_name)
                element_lines = [line]
                continue
            
            # Detect method
            method_match = re.match(r'^\s*(private|protected|public)?\s+(?:static\s+)?(?:\w+\s+)*(\w+)\s*\(', line)
            if method_match and not method_match.group(2).istitle():  # Not a constructor
                if current_element:
                    elements.append(self._create_element_from_lines(current_element, element_lines))
                
                method_name = method_match.group(2)
                current_element = ('method', method_name)
                element_lines = [line]
                continue
            
            # Detect constant
            constant_match = re.match(r'^\s*public\s+static\s+final\s+\w+\s+(\w+)\s*=', line)
            if constant_match:
                if current_element:
                    elements.append(self._create_element_from_lines(current_element, element_lines))
                
                constant_name = constant_match.group(1)
                current_element = ('constant', constant_name)
                element_lines = [line]
                continue
            
            # Add to current element
            if current_element:
                element_lines.append(line)
        
        # Add last element
        if current_element:
            elements.append(self._create_element_from_lines(current_element, element_lines))
        
        return elements
    
    def _create_element_from_lines(self, element_info: Tuple[str, str], lines: List[str]) -> JavaElement:
        """Create JavaElement from parsed lines."""
        element_type, name = element_info
        content = '\n'.join(lines).strip()
        
        if element_type == 'field':
            signature = self._normalize_field_signature(lines[0])
        elif element_type == 'method':
            signature = self._normalize_method_signature(content)
        elif element_type == 'constant':
            signature = f"KEY_{name}"
        else:
            signature = content
        
        return JavaElement(element_type, name, signature, content)
    
    def _element_exists(self, stub_element: JavaElement, existing_elements: List[JavaElement]) -> bool:
        """Check if an element already exists in the file."""
        for existing in existing_elements:
            if existing.element_type == stub_element.element_type:
                if stub_element.element_type == 'field':
                    # For fields, match by name
                    if existing.name == stub_element.name:
                        return True
                elif stub_element.element_type == 'method':
                    # For methods, match by name (could be enhanced to match full signature)
                    if existing.name == stub_element.name:
                        return True
                elif stub_element.element_type == 'constant':
                    # For constants, match by name
                    if existing.name == stub_element.name:
                        return True
        return False
    
    def _insert_elements_into_java_file(self, existing: str, new_elements: List[JavaElement]) -> str:
        """Insert new elements into the Java file at appropriate locations."""
        lines = existing.split('\n')
        
        # Find class boundaries
        analyzer = JavaFileAnalyzer(existing)
        class_start, class_end = analyzer._find_class_boundaries()
        
        if class_start == -1:
            logger.error("Cannot find class boundaries for element insertion")
            return existing
        
        # Group elements by type for better organization
        fields = [e for e in new_elements if e.element_type == 'field']
        constants = [e for e in new_elements if e.element_type == 'constant']
        methods = [e for e in new_elements if e.element_type == 'method']
        
        # Insert in reverse order to maintain line numbers
        insertions = []
        
        # Find insertion points
        field_insertion_point = self._find_field_insertion_point(lines, class_start, class_end)
        constant_insertion_point = self._find_constant_insertion_point(lines, class_start, class_end)
        method_insertion_point = self._find_method_insertion_point(lines, class_start, class_end)
        
        # Prepare insertions (in reverse order)
        for method in reversed(methods):
            insertions.append((method_insertion_point, method.content.split('\n')))
        
        for field in reversed(fields):
            insertions.append((field_insertion_point, ['', f'    {field.content}']))
        
        for constant in reversed(constants):
            insertions.append((constant_insertion_point, ['', f'    {constant.content}']))
        
        # Apply insertions
        for insertion_line, content_lines in insertions:
            for i, content_line in enumerate(reversed(content_lines)):
                lines.insert(insertion_line, content_line)
        
        return '\n'.join(lines)
    
    def _find_field_insertion_point(self, lines: List[str], class_start: int, class_end: int) -> int:
        """Find appropriate location to insert fields."""
        # Look for existing fields or after the class declaration
        for i in range(class_start + 1, class_end):
            line = lines[i].strip()
            if re.match(r'^\s*(private|protected|public)?\s+\w+(?:\[\])?\s+\w+\s*[=;]', line):
                # Found a field, insert after the last field
                j = i
                while j < class_end:
                    next_line = lines[j + 1].strip() if j + 1 < len(lines) else ""
                    if not re.match(r'^\s*(private|protected|public)?\s+\w+(?:\[\])?\s+\w+\s*[=;]', next_line):
                        return j + 1
                    j += 1
                return j + 1
        
        # No fields found, insert after class declaration
        return class_start + 1
    
    def _find_constant_insertion_point(self, lines: List[str], class_start: int, class_end: int) -> int:
        """Find appropriate location to insert constants."""
        # Look for existing constants or after class declaration
        for i in range(class_start + 1, class_end):
            line = lines[i].strip()
            if re.match(r'^\s*public\s+static\s+final\s+\w+\s+\w+', line):
                # Found constants, insert after the last one
                j = i
                while j < class_end:
                    next_line = lines[j + 1].strip() if j + 1 < len(lines) else ""
                    if not re.match(r'^\s*public\s+static\s+final\s+\w+\s+\w+', next_line):
                        return j + 1
                    j += 1
                return j + 1
        
        return class_start + 1
    
    def _find_method_insertion_point(self, lines: List[str], class_start: int, class_end: int) -> int:
        """Find appropriate location to insert methods."""
        # Insert before the closing brace of the class
        return class_end
    
    def _validate_java_syntax(self, content: str) -> bool:
        """Basic Java syntax validation."""
        try:
            # Check balanced braces
            brace_count = 0
            for char in content:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count < 0:
                        return False
            
            if brace_count != 0:
                logger.warning("Unbalanced braces in merged content")
                return False
            
            # Check for methods outside class
            lines = content.split('\n')
            analyzer = JavaFileAnalyzer(content)
            class_start, class_end = analyzer._find_class_boundaries()
            
            if class_start == -1:
                logger.warning("No class found in merged content")
                return False
            
            # Look for method-like patterns outside class boundaries
            method_pattern = r'^\s*(private|protected|public)?\s+(?:static\s+)?(?:\w+\s+)*\w+\s*\('
            
            for i, line in enumerate(lines):
                if (i < class_start or i > class_end) and re.match(method_pattern, line):
                    logger.warning(f"Method found outside class at line {i}: {line}")
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error validating syntax: {e}")
            return False
    
    def _normalize_field_signature(self, line: str) -> str:
        """Create normalized signature for field comparison."""
        line = re.sub(r'//.*$', '', line).strip()
        line = re.sub(r'\s+', ' ', line)
        
        match = re.match(r'^\s*(?:private|protected|public)?\s+(\w+(?:\[\])?)\s+(\w+)', line)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return line
    
    def _normalize_method_signature(self, method_content: str) -> str:
        """Create normalized signature for method comparison."""
        first_line = method_content.split('\n')[0].strip()
        first_line = re.sub(r'//.*$', '', first_line).strip()
        first_line = re.sub(r'\s+', ' ', first_line)
        signature = first_line.split('{')[0].strip()
        return signature

    def log_files_after_stub_application(self, instance_id: str, stub_files: Dict[str, str]) -> None:
        """Simple logging of file contents after stub application to organized logs."""
        instance_dir = self._get_instance_output_dir(instance_id)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        
        # Create a simple after-application log
        simple_log_file = instance_dir / f"simple_after_{timestamp}.log"
        
        logger.info("=== FILE CONTENTS AFTER STUB APPLICATION ===")
        
        try:
            with open(simple_log_file, 'w', encoding='utf-8') as log_file:
                log_file.write(f"Stub Application Results\n")
                log_file.write(f"Instance: {instance_id}\n")
                log_file.write(f"Timestamp: {timestamp}\n")
                log_file.write("=" * 80 + "\n\n")
                
                for file_path in stub_files.keys():
                    try:
                        read_command = f"cd /workspace && cat {file_path}"
                        exit_code, content = self.containers.exec_command(
                            instance_id, read_command, workdir="/workspace", timeout=30
                        )
                        
                        if exit_code == 0:
                            logger.info(f"\n--- {file_path} ---")
                            logger.info(f"Size: {len(content)} chars")
                            logger.info(f"Content:\n{content}")
                            logger.info(f"--- END {file_path} ---")
                            
                            # Write to organized log file
                            log_file.write(f"File: {file_path}\n")
                            log_file.write(f"Size: {len(content)} chars\n")
                            log_file.write("-" * 40 + "\n")
                            log_file.write(content)
                            log_file.write("\n" + "=" * 40 + "\n\n")
                        else:
                            logger.error(f"Could not read {file_path}: {content}")
                            log_file.write(f"File: {file_path}\n")
                            log_file.write(f"Error: Could not read file - {content}\n")
                            log_file.write("=" * 40 + "\n\n")
                            
                    except Exception as e:
                        logger.error(f"Error reading {file_path}: {e}")
                        log_file.write(f"File: {file_path}\n")
                        log_file.write(f"Exception: {e}\n")
                        log_file.write("=" * 40 + "\n\n")
            
            logger.info(f"Saved simple after-application log: {simple_log_file}")
            
        except Exception as e:
            logger.error(f"Error creating simple log file: {e}")

    def apply_stubs_with_simple_logging(self, instance_id: str, stub_files: Dict[str, str]) -> bool:
        """Apply stubs and log the resulting file contents to organized logs."""
        
        # Apply stubs using existing method
        success = self.apply_stubs(instance_id, stub_files)
        
        # Log file contents after application
        if success:
            self.log_files_after_stub_application(instance_id, stub_files)
        
        return success
    
    def save_file_contents_before_stubs(self, instance_id: str, stub_files: Dict[str, str]) -> Dict[str, str]:
        """Save file contents before stub application to organized log files."""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        before_contents = {}
        instance_dir = self._get_instance_output_dir(instance_id)
        
        logger.info(f"Saving stub files BEFORE application for {instance_id}")
        
        for file_path in stub_files.keys():
            try:
                read_command = f"cd /workspace && cat {file_path}"
                exit_code, content = self.containers.exec_command(
                    instance_id, read_command, workdir="/workspace", timeout=30
                )
                
                if exit_code == 0:
                    before_contents[file_path] = content
                    
                    # Organized log file path: validation_results/{instance_id}/stub_logs/
                    safe_filename = Path(file_path).name.replace('/', '_').replace('\\', '_')
                    log_file_name = f"before_{timestamp}_{safe_filename}.log"
                    log_file_path = instance_dir / log_file_name
                    
                    with open(log_file_path, 'w', encoding='utf-8') as f:
                        f.write(f"Instance: {instance_id}\n")
                        f.write(f"File: {file_path}\n")
                        f.write(f"Timestamp: {timestamp}\n")
                        f.write(f"Content length: {len(content)} chars\n")
                        f.write("=" * 80 + "\n")
                        f.write(content)
                    
                    logger.info(f"Saved BEFORE content: {log_file_path}")
                else:
                    logger.warning(f"Could not read {file_path} before stub application")
                    
            except Exception as e:
                logger.error(f"Error saving before content for {file_path}: {e}")
        
        return before_contents

    def save_file_contents_after_stubs(self, instance_id: str, stub_files: Dict[str, str]) -> None:
        """Save file contents after stub application to organized log files."""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        instance_dir = self._get_instance_output_dir(instance_id)
        
        logger.info(f"Saving stub files AFTER application for {instance_id}")
        
        for file_path in stub_files.keys():
            try:
                read_command = f"cd /workspace && cat {file_path}"
                exit_code, content = self.containers.exec_command(
                    instance_id, read_command, workdir="/workspace", timeout=30
                )
                
                if exit_code == 0:
                    # Organized log file path: validation_results/{instance_id}/stub_logs/
                    safe_filename = Path(file_path).name.replace('/', '_').replace('\\', '_')
                    log_file_name = f"after_{timestamp}_{safe_filename}.log"
                    log_file_path = instance_dir / log_file_name
                    
                    with open(log_file_path, 'w', encoding='utf-8') as f:
                        f.write(f"Instance: {instance_id}\n")
                        f.write(f"File: {file_path}\n")
                        f.write(f"Timestamp: {timestamp}\n")
                        f.write(f"Content length: {len(content)} chars\n")
                        f.write("=" * 80 + "\n")
                        f.write(content)
                    
                    logger.info(f"Saved AFTER content: {log_file_path}")
                else:
                    logger.warning(f"Could not read {file_path} after stub application")
                    
            except Exception as e:
                logger.error(f"Error saving after content for {file_path}: {e}")

    def apply_stubs_with_file_logging(self, instance_id: str, stub_files: Dict[str, str]) -> bool:
        """Apply stubs and save file contents before and after to organized log files."""
        
        # Save contents before application
        logger.info(f"Saving file contents before stub application for {instance_id}...")
        before_contents = self.save_file_contents_before_stubs(instance_id, stub_files)
        
        # Apply stubs (using the original apply_stubs method)
        success = self.apply_stubs(instance_id, stub_files)
        
        # Save contents after application
        if success:
            logger.info(f"Saving file contents after stub application for {instance_id}...")
            self.save_file_contents_after_stubs(instance_id, stub_files)
            
            # Create a diff summary log
            self.create_diff_summary(instance_id, stub_files, before_contents)
        
        return success

    def create_diff_summary(self, instance_id: str, stub_files: Dict[str, str], before_contents: Dict[str, str]) -> None:
        """Create a summary showing what changed in each file."""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        instance_dir = self._get_instance_output_dir(instance_id)
        
        # Create organized diff summary file
        summary_file = instance_dir / f"diff_summary_{timestamp}.log"
        
        try:
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(f"Stub Application Diff Summary\n")
                f.write(f"Instance: {instance_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Files processed: {len(stub_files)}\n")
                f.write("=" * 80 + "\n\n")
                
                for file_path in stub_files.keys():
                    f.write(f"File: {file_path}\n")
                    f.write("-" * 40 + "\n")
                    
                    # Read current content
                    try:
                        read_command = f"cd /workspace && cat {file_path}"
                        exit_code, after_content = self.containers.exec_command(
                            instance_id, read_command, workdir="/workspace", timeout=30
                        )
                        
                        if exit_code == 0:
                            before_content = before_contents.get(file_path, "")
                            
                            # Simple diff analysis
                            if before_content == after_content:
                                f.write("Status: No changes detected\n")
                            else:
                                before_lines = len(before_content.splitlines())
                                after_lines = len(after_content.splitlines())
                                f.write(f"Status: Modified\n")
                                f.write(f"Before: {before_lines} lines, {len(before_content)} chars\n")
                                f.write(f"After: {after_lines} lines, {len(after_content)} chars\n")
                                f.write(f"Line diff: {after_lines - before_lines:+d}\n")
                                f.write(f"Char diff: {len(after_content) - len(before_content):+d}\n")
                        else:
                            f.write("Status: Could not read after content\n")
                            
                    except Exception as e:
                        f.write(f"Status: Error reading file - {e}\n")
                    
                    f.write("\n")
            
            logger.info(f"Created diff summary: {summary_file}")
            
        except Exception as e:
            logger.error(f"Error creating diff summary: {e}")


def extract_oracle_files(containers_manager, instance_id: str, solution_patch: str) -> Dict[str, str]:
    """
    Extract and read the content of files that will be modified in solution patch.
    
    Args:
        containers_manager: Container manager for file operations
        instance_id: Instance ID for container execution
        solution_patch: The solution patch content
        
    Returns:
        Dictionary mapping file paths to their current content
    """
    oracle_files = {}
    
    if not solution_patch:
        return oracle_files
    
    try:
        # Extract file paths from solution patch
        file_patterns = [
            r'\+\+\+ b/(.+\.(?:java|kt))',
            r'diff --git a/.+ b/(.+\.(?:java|kt))'
        ]
        
        modified_files = set()
        for pattern in file_patterns:
            matches = re.findall(pattern, solution_patch)
            modified_files.update(matches)
        
        logger.info(f"Found {len(modified_files)} oracle files to read")
        
        # Read content of these files from the current workspace
        for file_path in modified_files:
            try:
                read_command = f"cd /workspace && cat {file_path} 2>/dev/null || echo 'FILE_NOT_FOUND'"
                exit_code, content = containers_manager.exec_command(
                    instance_id, read_command, workdir="/workspace", timeout=30
                )
                
                if exit_code == 0 and content != "FILE_NOT_FOUND":
                    oracle_files[file_path] = content
                    logger.debug(f"Read oracle file: {file_path} ({len(content)} chars)")
                else:
                    logger.debug(f"Oracle file not found or empty: {file_path}")
                    
            except Exception as e:
                logger.warning(f"Error reading oracle file {file_path}: {e}")
        
    except Exception as e:
        logger.error(f"Error extracting oracle files: {e}")
    
    return oracle_files


# High-level convenience function for easy integration
async def generate_and_apply_stubs(containers_manager, instance_id: str, 
                                  build_log: str, test_patch: str, 
                                  solution_patch: str, api_key: str,
                                  model: str = "anthropic/claude-3.7-sonnet",
                                  base_output_dir: str = "validation_results") -> StubGenerationResult:
    """
    Complete stub generation and application workflow.
    
    Args:
        containers_manager: Container manager instance
        instance_id: Instance ID
        build_log: Build log with compilation errors
        test_patch: Applied test patch
        solution_patch: Solution patch for oracle files
        api_key: OpenRouter API key
        model: LLM model to use
        base_output_dir: Base directory for organizing results
        
    Returns:
        StubGenerationResult with all metadata
    """
    # Extract oracle files
    oracle_files = extract_oracle_files(containers_manager, instance_id, solution_patch)
    
    # Generate stubs
    generator = StubGenerator(api_key, model, base_output_dir)
    result = await generator.generate_stubs(build_log, test_patch, oracle_files, instance_id)
    
    # Apply stubs if generation was successful
    if result.success and result.files_created:
        applicator = SmartStubApplicator(containers_manager, base_output_dir)
        # apply_success = applicator.apply_stubs(instance_id, result.files_created)
        # apply_success = applicator.apply_stubs_with_simple_logging(instance_id, result.files_created)
        apply_success = applicator.apply_stubs_with_file_logging(instance_id, result.files_created)
        
        if not apply_success:
            result.error_message = "Stub generation succeeded but application failed"
            result.success = False
    
    return result