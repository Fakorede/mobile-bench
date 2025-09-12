#!/usr/bin/env python3
"""
Patch-based stub generation system - a better approach than file merging.
"""

import subprocess
import tempfile
import os
import logging
import time
import json
import aiohttp
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any, Set
import re

logger = logging.getLogger(__name__)

class PatchBasedStubGenerator:
    """Generate and apply patches instead of complex file merging."""
    
    def __init__(self, containers_manager=None, api_key: str = None, model: str = "anthropic/claude-3.7-sonnet", base_output_dir: str = "validation_results"):
        if containers_manager:
            # Use container workspace - all git operations will be executed inside the container
            self.containers = containers_manager
        else:
            # Fallback for direct usage - this shouldn't be used in production
            self.containers = None
        
        self.api_key = api_key
        self.model = model
        self.base_output_dir = Path(base_output_dir)
        
        # Model costs for API billing
        self.model_costs = {
            "anthropic/claude-3.7-sonnet": {"input": 0.000003, "output": 0.000015},
            "anthropic/claude-4-sonnet-20250522": {"input": 0.000015, "output": 0.000075},
            "anthropic/claude-4-opus-20250522": {"input": 0.000075, "output": 0.000375},
            "deepseek/deepseek-chat-v3-0324": {"input": 0.0000014, "output": 0.0000028},
            "openai/gpt-4o-2024-08-06": {"input": 0.0000025, "output": 0.00001}
        }
    
    def generate_patch_from_llm_response(self, llm_response: str) -> List[Tuple[str, str]]:
        """Extract patches from LLM response instead of MODIFY blocks."""
        patches = []
        
        # Look for patch blocks instead of MODIFY blocks
        patch_pattern = r'```PATCH:\s*(.*?)\s*\n(.*?)```'
        matches = re.findall(patch_pattern, llm_response, re.DOTALL)
        
        for file_path, patch_content in matches:
            patches.append((file_path.strip(), patch_content.strip()))
        
        return patches
    
    def apply_patches(self, instance_id: str, patches: List[Tuple[str, str]]) -> Tuple[bool, List[str]]:
        """Apply patches using git apply for robust merging."""
        applied_files = []
        failed_files = []
        
        # Ensure we're in a git repository
        if not self._is_git_repo(instance_id):
            logger.warning("Project root is not a git repository - attempting to initialize")
            if not self._ensure_git_repo(instance_id):
                logger.error("Failed to initialize git repository - patch application requires git")
                return False, []
        
        # Save original commit hash before making any changes (only if not already saved)
        self._save_original_commit_hash(instance_id)
        
        for file_path, patch_content in patches:
            success = self._apply_single_patch(instance_id, file_path, patch_content)
            if success:
                applied_files.append(file_path)
                logger.info(f"Successfully applied patch to {file_path}")
            else:
                failed_files.append(file_path)
                logger.warning(f"Failed to apply patch to {file_path}")
        
        if failed_files:
            logger.warning(f"Failed to apply patches to {len(failed_files)} files: {failed_files}")
            return len(applied_files) > 0, applied_files
        
        logger.info(f"Successfully applied patches to {len(applied_files)} files")
        return True, applied_files
    
    async def generate_and_apply_patches(self, instance_id: str, build_log: str, test_patch: str, oracle_files: dict, gradle_command: str = None):
        """Complete workflow: generate patches via LLM and apply them."""
        # Import here to avoid circular imports
        try:
            from stub_generator_utils import StubGenerationResult
        except ImportError:
            # Fallback: create a minimal result class
            class StubGenerationResult:
                def __init__(self, success, generated_stubs, files_created, oracle_files=None, error_message=None, api_cost=0.0, response_time=0.0, model_used=""):
                    self.success = success
                    self.generated_stubs = generated_stubs
                    self.files_created = files_created
                    self.oracle_files = oracle_files or {}
                    self.error_message = error_message
                    self.api_cost = api_cost
                    self.response_time = response_time
                    self.model_used = model_used
        
        start_time = time.time()
        
        try:
            # Generate the complete prompt with build log and context
            prompt = self._create_comprehensive_prompt(build_log, test_patch, oracle_files)
            
            # Call LLM API to generate patches
            llm_response = await self._call_llm_api(prompt, "first_pass", instance_id)
            
            if not llm_response:
                return StubGenerationResult(
                    success=False,
                    generated_stubs="",
                    files_created={},
                    oracle_files=oracle_files,
                    error_message="Failed to get response from LLM",
                    response_time=time.time() - start_time,
                    model_used=self.model
                )
            
            # Parse patches from LLM response
            patches = self.generate_patch_from_llm_response(llm_response)
            
            # Log generated patches for debugging and save to files
            logger.info(f"Generated {len(patches)} patches from LLM response")
            self._save_patches_to_files(instance_id, patches, "first_pass")
            for i, (file_path, patch_content) in enumerate(patches):
                logger.info(f"Patch {i+1}/{len(patches)}: {file_path}")
                logger.debug(f"Patch content for {file_path}:\n{patch_content}")
            
            if not patches:
                return StubGenerationResult(
                    success=False,
                    generated_stubs=llm_response,
                    files_created={},
                    oracle_files=oracle_files,
                    error_message="No patches found in LLM response",
                    response_time=time.time() - start_time,
                    model_used=self.model
                )
            
            # Create checkpoint before applying first pass patches
            self._create_git_checkpoint(instance_id, "before_first_pass")
            
            # Apply patches using git
            success, applied_files = self.apply_patches(instance_id, patches)
            
            # Validate compilation if patches were applied
            compilation_output = ""
            if success and applied_files:
                # Use the same gradle command from the build step if provided
                build_cmd = gradle_command if gradle_command else "./gradlew compileDebugSources"
                logger.info(f"DEBUG: About to validate compilation with command: {build_cmd}")
                compilation_success, compilation_output = self.validate_compilation(instance_id, build_cmd)
                logger.info(f"DEBUG: First pass compilation result: success={compilation_success}")
                if not compilation_success:
                    logger.warning("First pass: Patches applied but compilation still fails, attempting second pass")
                    logger.info("DEBUG: Starting second pass execution...")
                    
                    # Create checkpoint after first pass
                    self._create_git_checkpoint(instance_id, "after_first_pass")
                    
                    # Analyze first pass results and determine strategy
                    try:
                        conflict_analysis = self._analyze_compilation_conflicts(compilation_output, patches)
                        
                        # Get updated oracle files after first pass changes
                        updated_oracle_files = self._get_updated_oracle_files(instance_id, oracle_files)
                        logger.info(f"Updated {len(updated_oracle_files)} oracle files with first pass changes")
                        
                        if conflict_analysis["has_conflicts"]:
                            logger.info("Detected conflicts from first pass - using selective fix strategy")
                            logger.info("DEBUG: Starting selective second pass...")
                            second_pass_success = await self._attempt_selective_second_pass(
                                instance_id, build_log, test_patch, updated_oracle_files, 
                                compilation_output, applied_files, conflict_analysis
                            )
                            logger.info(f"DEBUG: Selective second pass result: success={second_pass_success}")
                        else:
                            logger.info("No conflicts detected - using additive second pass strategy")
                            logger.info("DEBUG: Starting additive second pass...")
                            second_pass_success = await self._attempt_additive_second_pass(
                                instance_id, build_log, test_patch, updated_oracle_files, compilation_output
                            )
                            logger.info(f"DEBUG: Additive second pass result: success={second_pass_success}")
                    except Exception as e:
                        logger.error(f"DEBUG: Exception during second pass attempt: {e}")
                        logger.exception("Full exception details:")
                        second_pass_success = False
                    
                    if second_pass_success:
                        # Re-validate compilation after second pass using same gradle command
                        build_cmd = gradle_command if gradle_command else "./gradlew compileDebugSources"
                        final_compilation_success, final_output = self.validate_compilation(instance_id, build_cmd)
                        if final_compilation_success:
                            logger.info("Second pass successful - compilation now passes")
                            success = True
                        else:
                            logger.warning("Second pass failed - rolling back to first pass state")
                            self._reset_to_checkpoint(instance_id, "after_first_pass")
                            success = False
                            compilation_output = final_output
                    else:
                        logger.warning("Second pass patch generation failed - keeping first pass changes")
                        # Keep first pass changes as they might be partially helpful
                        success = False
            
            # Create result
            files_created = {file_path: f"Patch applied to {file_path}" for file_path in applied_files}
            
            # Prepare detailed error message if compilation failed
            error_message = None
            if not success:
                if compilation_output:
                    error_message = f"Patch application or compilation failed. Compilation output:\n{compilation_output[:1000]}..."
                else:
                    error_message = "Patch application or compilation failed"
            
            return StubGenerationResult(
                success=success,
                generated_stubs=llm_response,
                files_created=files_created,
                oracle_files=oracle_files,
                error_message=error_message,
                api_cost=self._calculate_api_cost(prompt, llm_response),
                response_time=time.time() - start_time,
                model_used=self.model
            )
            
        except Exception as e:
            logger.error(f"Error in patch-based stub generation: {e}")
            return StubGenerationResult(
                success=False,
                generated_stubs="",
                files_created={},
                oracle_files=oracle_files,
                error_message=str(e),
                response_time=time.time() - start_time,
                model_used=self.model
            )
    
    def _apply_single_patch(self, instance_id: str, file_path: str, patch_content: str) -> bool:
        """Apply a single patch using git apply."""
        try:
            if not self.containers:
                logger.error("No container manager available")
                return False
            
            # Ensure proper patch format
            if not patch_content.startswith('---'):
                # Convert simple diff to proper patch format
                patch_content = self._convert_to_proper_patch(file_path, patch_content)
            
            # Escape patch content for safe transmission
            escaped_patch = patch_content.replace("'", "'\"'\"'")
            
            # Apply patch using git apply with multiple strategies
            patch_apply_command = f"""
cd /workspace &&
echo "=== Applying patch to {file_path} ===" &&

# Create patch file
cat > /tmp/patch.patch << 'PATCH_EOF'
{patch_content}
PATCH_EOF

echo "=== Patch file created ===" &&

# Try git apply with 3-way merge
echo "=== Strategy 1: git apply --3way ===" &&
if git apply --3way --whitespace=nowarn /tmp/patch.patch 2>&1; then
    echo "SUCCESS: 3-way merge worked"
    rm -f /tmp/patch.patch
    exit 0
fi

echo "=== Strategy 2: git apply with reject ===" &&
if git apply --reject --whitespace=nowarn /tmp/patch.patch 2>&1; then
    echo "SUCCESS: apply with reject worked"
    rm -f /tmp/patch.patch
    exit 0
fi

echo "=== Strategy 3: git apply with ignore-whitespace ===" &&
if git apply --ignore-space-change --ignore-whitespace /tmp/patch.patch 2>&1; then
    echo "SUCCESS: apply with whitespace options worked"
    rm -f /tmp/patch.patch
    exit 0
fi

echo "=== Strategy 4: patch with batch and fuzz ===" &&
if patch --batch --fuzz=5 -p1 -i /tmp/patch.patch 2>&1; then
    echo "SUCCESS: patch with batch and fuzz worked"
    rm -f /tmp/patch.patch
    exit 0
fi

echo "=== Strategy 5: patch with force and fuzz ===" &&
if patch --force --fuzz=3 -p1 < /tmp/patch.patch 2>&1; then
    echo "SUCCESS: patch with force and fuzz worked"
    rm -f /tmp/patch.patch
    exit 0
fi

echo "=== All patch strategies failed ===" &&
rm -f /tmp/patch.patch &&
exit 1
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                patch_apply_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                return True
            else:
                logger.warning(f"Git apply failed for {file_path}: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Exception applying patch to {file_path}: {e}")
            return False
    
    def _convert_to_proper_patch(self, file_path: str, diff_content: str) -> str:
        """Convert simple diff content to proper patch format."""
        lines = diff_content.split('\n')
        
        # If it's already a proper patch, return as-is
        if any(line.startswith('---') or line.startswith('+++') for line in lines):
            return diff_content
        
        # Convert to unified diff format
        patch_lines = [
            f"--- a/{file_path}",
            f"+++ b/{file_path}",
            "@@ -1,1 +1,1 @@"  # Simple hunk header - git will figure out the rest
        ]
        
        for line in lines:
            if line.strip():
                if not line.startswith(('+', '-', ' ')):
                    # Assume it's an addition
                    patch_lines.append(f"+{line}")
                else:
                    patch_lines.append(line)
        
        return '\n'.join(patch_lines)
    
    def _is_git_repo(self, instance_id: str) -> bool:
        """Check if project root is a git repository."""
        try:
            if not self.containers:
                logger.error("No container manager available")
                return False
            
            # Check if .git directory exists in the container
            exit_code, output = self.containers.exec_command(
                instance_id,
                "cd /workspace && test -d .git",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.warning(f"No .git directory found in /workspace")
                return False
            
            # Verify git repository status
            exit_code, output = self.containers.exec_command(
                instance_id,
                "cd /workspace && git rev-parse --git-dir",
                workdir="/workspace"
            )
            
            if exit_code != 0:
                logger.warning(f"Git repo check failed: {output}")
                return False
                
            return True
        except Exception as e:
            logger.warning(f"Exception checking git repo: {e}")
            return False
    
    def _ensure_git_repo(self, instance_id: str) -> bool:
        """Initialize git repository if it doesn't exist or is corrupted."""
        try:
            if not self.containers:
                logger.error("No container manager available")
                return False
            
            # Initialize git repository in the container
            git_init_command = """
cd /workspace &&
echo "=== Initializing git repository ===" &&
git init &&

echo "=== Configuring git user ===" &&
git config user.email 'patch-generator@android-bench.local' &&
git config user.name 'Patch Generator' &&
git config --add safe.directory /workspace &&

echo "=== Adding files to git ===" &&
git add . &&

echo "=== Creating initial commit ===" &&
(git commit -m 'Initial commit for patch application' || echo 'Commit skipped - files may already be committed') &&

echo "=== Git initialization complete ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                git_init_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.info("Successfully initialized git repository for patch application")
                return True
            else:
                logger.error(f"Failed to initialize git repository: {output}")
                return False
            
        except Exception as e:
            logger.error(f"Exception during git repo initialization: {e}")
            return False
    
    def validate_compilation(self, instance_id: str, build_command: str = "./gradlew compileDebugSources") -> Tuple[bool, str]:
        """Validate that the project compiles after patch application using the same test command as the build step."""
        try:
            if not self.containers:
                logger.error("No container manager available")
                return False, "No container manager available"
            
            # Run compilation test in container using the same command pattern as the build step
            compile_command = f"""
cd /workspace &&
echo "=== Testing compilation after stub patch application ===" &&
echo "Using same gradle command from build step: {build_command}" &&

# Java setup (same as testing framework)
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
if [ -d "$JAVA_HOME" ]; then export PATH="$JAVA_HOME/bin:$PATH"; fi

# Android environment setup (same as testing framework)
export ANDROID_HOME='/opt/android-sdk'
export ANDROID_SDK_ROOT='/opt/android-sdk'
export HOME=/tmp
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p /tmp/.gradle

# Configure Gradle (same as testing framework)
cat > /tmp/.gradle/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.configureondemand=true
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.lang.invoke=ALL-UNNAMED --add-opens java.prefs/java.util.prefs=ALL-UNNAMED --add-opens java.base/java.nio.charset=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Stopping existing Gradle daemons ===" &&
./gradlew --stop 2>/dev/null || true &&

if [ -f './gradlew' ]; then
    chmod +x ./gradlew
    echo "=== Running compilation test with same command from build step ===" &&
    echo "Executing: {build_command} --no-daemon --stacktrace" &&
    timeout 1200 {build_command} --no-daemon --stacktrace
    GRADLE_EXIT_CODE=$?
    echo "=== Gradle exit code: $GRADLE_EXIT_CODE ==="
    exit $GRADLE_EXIT_CODE
else
    echo "ERROR: No gradlew found in workspace"
    exit 1
fi
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                compile_command,
                workdir="/workspace"
            )
            
            # Save gradle output to file but don't log to main logger to avoid cluttering validation logs
            self._save_gradle_output_to_file(instance_id, output, exit_code)
            
            logger.info(f"DEBUG: validate_compilation exit_code={exit_code}, success_check={exit_code == 0}")
            
            if exit_code == 0:
                logger.info(f"Compilation successful after patch application using build step command: {build_command}")
                return True, output
            else:
                logger.warning(f"Compilation failed after patch application using build step command: {build_command} (exit_code: {exit_code})")
                return False, output
                
        except Exception as e:
            error_msg = f"Error during compilation validation: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def rollback_patches(self, instance_id: str, applied_files: List[str]) -> bool:
        """Rollback applied patches using git reset."""
        try:
            if not self.containers:
                logger.error("No container manager available")
                return False
            
            # Reset all changes to tracked files
            files_list = " ".join(applied_files)
            rollback_command = f"""
cd /workspace &&
echo "=== Rolling back patches for {len(applied_files)} files ===" &&
git checkout HEAD -- {files_list} &&
echo "=== Rollback complete ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                rollback_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.info(f"Successfully rolled back patches for {len(applied_files)} files")
                return True
            else:
                logger.error(f"Failed to rollback patches: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Exception during rollback: {e}")
            return False
    
    def _filter_conflicting_patches(self, instance_id: str, new_patches: List[Tuple[str, str]], 
                                   existing_patch: str) -> List[Tuple[str, str]]:
        """Filter out patches that would create conflicts with existing changes."""
        try:
            logger.info(f"Analyzing {len(new_patches)} patches for potential conflicts...")
            
            # Parse existing patch to understand what was already changed
            existing_modifications = self._parse_existing_modifications(existing_patch)
            logger.info(f"Found existing modifications in {len(existing_modifications)} files")
            
            filtered_patches = []
            for file_path, patch_content in new_patches:
                # Check for conflicts with existing modifications
                if self._patch_creates_conflicts(file_path, patch_content, existing_modifications):
                    logger.warning(f"❌ Filtering out conflicting patch for {file_path}")
                    continue
                
                # Additional validation: check if patch adds duplicates within itself
                if self._patch_adds_duplicates(file_path, patch_content):
                    logger.warning(f"❌ Filtering out duplicate-creating patch for {file_path}")
                    continue
                
                # Extra safety: check for files that were already modified (exact path or base name match)
                already_modified = False
                for existing_file in existing_modifications.keys():
                    # Check exact path match or same base filename
                    if (file_path == existing_file or 
                        file_path.split('/')[-1] == existing_file.split('/')[-1]):
                        logger.warning(f"❌ Filtering out patch for already modified file: {file_path} (matches {existing_file})")
                        already_modified = True
                        break
                
                if already_modified:
                    continue
                
                logger.info(f"✅ Approved patch for {file_path}")
                filtered_patches.append((file_path, patch_content))
            
            logger.info(f"Conflict analysis complete: {len(new_patches)} → {len(filtered_patches)} patches")
            
            # If all patches were filtered, log why
            if len(filtered_patches) == 0 and len(new_patches) > 0:
                logger.warning("⚠️  All patches were filtered due to conflicts!")
                logger.info("Existing modifications detected in files:")
                for file_path, mods in existing_modifications.items():
                    logger.info(f"  - {file_path}: {mods}")
            
            return filtered_patches
            
        except Exception as e:
            logger.error(f"Error in conflict detection: {e}")
            # Return empty list on error to be safe
            return []
    
    def _parse_existing_modifications(self, existing_patch: str) -> Dict[str, Set[str]]:
        """Parse existing patch to identify what has been modified."""
        modifications = {}
        
        current_file = None
        for line in existing_patch.split('\n'):
            # Handle both patch format and git diff format
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                # Extract file path
                if line.startswith('+++ b/'):
                    current_file = line[6:]
                    if current_file not in modifications:
                        modifications[current_file] = set()
            elif line.startswith('diff --git'):
                # Git diff format: diff --git a/file b/file
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[3][2:]  # Remove 'b/' prefix
                    if current_file not in modifications:
                        modifications[current_file] = set()
            elif line.startswith('+') and not line.startswith('+++') and current_file:
                # Track added content
                added_content = line[1:].strip()
                if added_content:
                    # Extract identifiers (properties, methods, classes)
                    identifiers = self._extract_identifiers(added_content)
                    modifications[current_file].update(identifiers)
                    
                    # Also store the raw line for debugging
                    logger.debug(f"Tracked modification in {current_file}: {added_content}")
        
        # Log what was parsed for debugging
        for file_path, identifiers in modifications.items():
            if identifiers:
                logger.info(f"Parsed {len(identifiers)} modifications in {file_path}: {identifiers}")
        
        return modifications
    
    def _extract_identifiers(self, content: str) -> Set[str]:
        """Extract identifiers (property names, method names, etc.) from code line."""
        identifiers = set()
        
        # Common patterns for Kotlin/Java identifiers - comprehensive list
        patterns = [
            # Kotlin properties (various forms)
            r'val\s+(\w+)\s*[:,=]',           # val properties with type or assignment
            r'var\s+(\w+)\s*[:,=]',           # var properties with type or assignment
            r'const\s+val\s+(\w+)',           # constants
            # Kotlin functions
            r'fun\s+(\w+)\s*\(',              # functions
            r'override\s+fun\s+(\w+)\s*\(',   # override functions
            r'suspend\s+fun\s+(\w+)\s*\(',    # suspend functions
            # Access modifiers + declarations
            r'(?:private|public|protected|internal)\s+val\s+(\w+)',     # modified properties
            r'(?:private|public|protected|internal)\s+var\s+(\w+)',     # modified properties
            r'(?:private|public|protected|internal)\s+fun\s+(\w+)',     # modified functions
            # Classes and interfaces
            r'class\s+(\w+)',                 # classes
            r'interface\s+(\w+)',             # interfaces
            r'object\s+(\w+)',                # objects
            r'enum\s+class\s+(\w+)',          # enum classes
            r'data\s+class\s+(\w+)',          # data classes
            r'sealed\s+class\s+(\w+)',        # sealed classes
            # Java-style declarations
            r'(?:private|public|protected)\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(',  # Java methods
            r'(?:private|public|protected)\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*[;=]', # Java fields
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            identifiers.update(matches)
        
        return identifiers
    
    def _patch_creates_conflicts(self, file_path: str, patch_content: str, 
                               existing_modifications: Dict[str, Set[str]]) -> bool:
        """Check if a patch would create conflicts with existing modifications."""
        if file_path not in existing_modifications:
            return False
        
        existing_identifiers = existing_modifications[file_path]
        
        # Check if patch tries to add something that already exists
        for line in patch_content.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                added_content = line[1:].strip()
                new_identifiers = self._extract_identifiers(added_content)
                
                # Check for conflicts
                conflicts = new_identifiers.intersection(existing_identifiers)
                if conflicts:
                    logger.warning(f"Detected identifier conflicts in {file_path}: {conflicts}")
                    return True
        
        return False
    
    def _patch_adds_duplicates(self, file_path: str, patch_content: str) -> bool:
        """Check if patch adds duplicate declarations within itself."""
        added_identifiers = set()
        added_lines = []  # Track actual lines for better duplicate detection
        
        for line in patch_content.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                added_content = line[1:].strip()
                if not added_content:  # Skip empty lines
                    continue
                    
                # Extract identifiers
                new_identifiers = self._extract_identifiers(added_content)
                
                # Check for duplicate identifiers
                duplicates = new_identifiers.intersection(added_identifiers)
                if duplicates:
                    logger.warning(f"Detected internal duplicate identifiers in {file_path}: {duplicates}")
                    return True
                
                # Check for near-duplicate lines (same property with different defaults)
                for existing_line in added_lines:
                    if (self._lines_are_similar_declarations(added_content, existing_line) and 
                        added_content != existing_line):
                        logger.warning(f"Detected similar declarations in {file_path}: '{existing_line}' vs '{added_content}'")
                        return True
                
                added_identifiers.update(new_identifiers)
                added_lines.append(added_content)
        
        return False
    
    def _lines_are_similar_declarations(self, line1: str, line2: str) -> bool:
        """Check if two lines are similar property/method declarations."""
        # Remove whitespace and common modifiers for comparison
        normalized1 = re.sub(r'\s+', ' ', line1.strip()).lower()
        normalized2 = re.sub(r'\s+', ' ', line2.strip()).lower()
        
        # Check if both are property declarations of same name but different defaults
        prop_pattern = r'val\s+(\w+)\s*:'
        match1 = re.search(prop_pattern, normalized1)
        match2 = re.search(prop_pattern, normalized2)
        
        if match1 and match2:
            return match1.group(1) == match2.group(1)
        
        return False
    
    def _create_git_checkpoint(self, instance_id: str, checkpoint_name: str) -> bool:
        """Create a git checkpoint to enable non-cumulative patch application."""
        try:
            if not self.containers:
                logger.error("No container manager available for checkpoint")
                return False
            
            # Create a git commit with current state for checkpoint
            checkpoint_command = f"""
cd /workspace &&
echo "=== Creating git checkpoint: {checkpoint_name} ===" &&
git add -A &&
git commit -m "Checkpoint: {checkpoint_name}" --allow-empty &&
echo "=== Checkpoint '{checkpoint_name}' created ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                checkpoint_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.info(f"Successfully created checkpoint: {checkpoint_name}")
                return True
            else:
                logger.warning(f"Failed to create checkpoint {checkpoint_name}: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Exception creating checkpoint: {e}")
            return False
    
    def _reset_to_checkpoint(self, instance_id: str, checkpoint_name: str) -> bool:
        """Reset to a specific git checkpoint to avoid cumulative patches."""
        try:
            if not self.containers:
                logger.error("No container manager available for reset")
                return False
            
            # Reset to the specific checkpoint
            reset_command = f"""
cd /workspace &&
echo "=== Resetting to checkpoint: {checkpoint_name} ===" &&
git reset --hard HEAD~1 &&
git clean -fd &&
echo "=== Reset to '{checkpoint_name}' completed ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                reset_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.info(f"Successfully reset to checkpoint: {checkpoint_name}")
                return True
            else:
                logger.error(f"Failed to reset to checkpoint {checkpoint_name}: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Exception resetting to checkpoint: {e}")
            return False
    
    def _analyze_compilation_conflicts(self, compilation_output: str, first_pass_patches: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Analyze compilation output to detect conflicts caused by first pass patches."""
        analysis = {
            "has_conflicts": False,
            "conflicting_declarations": [],
            "conflicting_files": [],
            "safe_files": [],
            "error_types": []
        }
        
        lines = compilation_output.split('\n')
        
        # Look for specific conflict patterns
        conflict_patterns = [
            r"Conflicting declarations",
            r"Conflicting overloads",
            r"Duplicate.*declaration",
            r"redeclaration of",
            r"already declared"
        ]
        
        for line in lines:
            for pattern in conflict_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    analysis["has_conflicts"] = True
                    analysis["conflicting_declarations"].append(line.strip())
                    
                    # Extract file path if present
                    file_match = re.search(r'file://.*?([^/\s]+\.kt)', line)
                    if file_match:
                        conflicting_file = file_match.group(1)
                        if conflicting_file not in analysis["conflicting_files"]:
                            analysis["conflicting_files"].append(conflicting_file)
        
        # Categorize first pass patches as safe or conflicting
        first_pass_files = {os.path.basename(file_path) for file_path, _ in first_pass_patches}
        
        for file_path, _ in first_pass_patches:
            file_name = os.path.basename(file_path)
            if any(cf in file_name for cf in analysis["conflicting_files"]):
                if file_path not in analysis["conflicting_files"]:
                    analysis["conflicting_files"].append(file_path)
            else:
                analysis["safe_files"].append(file_path)
        
        logger.info(f"Conflict analysis: {len(analysis['conflicting_files'])} conflicting, {len(analysis['safe_files'])} safe files")
        return analysis
    
    async def _attempt_selective_second_pass(self, instance_id: str, original_build_log: str,
                                           test_patch: str, oracle_files: Dict[str, str],
                                           compilation_output: str, applied_files: List[str],
                                           conflict_analysis: Dict[str, Any]) -> bool:
        """Attempt second pass by only reverting conflicting files and regenerating those."""
        try:
            logger.info("=== STARTING SELECTIVE SECOND PASS ===")
            
            # Revert only the conflicting files to clean state
            if conflict_analysis["conflicting_files"]:
                logger.info(f"Reverting {len(conflict_analysis['conflicting_files'])} conflicting files")
                revert_success = self._selective_revert_files(instance_id, conflict_analysis["conflicting_files"])
                if not revert_success:
                    logger.warning("Failed to selectively revert files, falling back to full reset")
                    self._reset_to_checkpoint(instance_id, "before_first_pass")
            
            # Generate patches only for the problematic areas
            selective_prompt = self._create_selective_second_pass_prompt(
                original_build_log, test_patch, oracle_files, compilation_output, 
                conflict_analysis, applied_files
            )
            
            llm_response = await self._call_llm_api(selective_prompt, "second_pass_selective", instance_id)
            if not llm_response:
                logger.error("Selective second pass: Failed to get LLM response")
                return False
            
            # Parse and apply selective patches
            selective_patches = self.generate_patch_from_llm_response(llm_response)
            logger.info(f"Selective second pass: Generated {len(selective_patches)} targeted patches")
            self._save_patches_to_files(instance_id, selective_patches, "second_pass_selective")
            
            if selective_patches:
                success, newly_applied = self.apply_patches(instance_id, selective_patches)
                if success:
                    logger.info(f"Selective second pass: Successfully applied {len(newly_applied)} patches")
                    return True
                else:
                    logger.warning("Selective second pass: Failed to apply patches")
                    return False
            else:
                logger.warning("Selective second pass: No patches generated")
                return False
                
        except Exception as e:
            logger.error(f"Exception during selective second pass: {e}")
            return False
    
    async def _attempt_additive_second_pass(self, instance_id: str, original_build_log: str,
                                          test_patch: str, oracle_files: Dict[str, str],
                                          compilation_output: str) -> bool:
        """Attempt additive second pass that builds on successful first pass changes."""
        try:
            logger.info("=== STARTING ADDITIVE SECOND PASS ===")
            
            # Create prompt that acknowledges first pass successes and addresses remaining issues
            additive_prompt = self._create_additive_second_pass_prompt(
                original_build_log, test_patch, oracle_files, compilation_output
            )
            
            llm_response = await self._call_llm_api(additive_prompt, "second_pass_additive", instance_id)
            if not llm_response:
                logger.error("Additive second pass: Failed to get LLM response")
                return False
            
            # Parse and apply additive patches
            additive_patches = self.generate_patch_from_llm_response(llm_response)
            logger.info(f"Additive second pass: Generated {len(additive_patches)} additional patches")
            self._save_patches_to_files(instance_id, additive_patches, "second_pass_additive")
            
            if additive_patches:
                # Get first pass patches to check for conflicts
                first_pass_patches_content = self._get_applied_first_pass_patches(instance_id)
                
                # Analyze patches for potential conflicts before applying
                filtered_patches = self._filter_conflicting_patches(instance_id, additive_patches, first_pass_patches_content)
                logger.info(f"Additive second pass: Filtered to {len(filtered_patches)} non-conflicting patches")
                
                if filtered_patches:
                    success, newly_applied = self.apply_patches(instance_id, filtered_patches)
                    if success:
                        logger.info(f"Additive second pass: Successfully applied {len(newly_applied)} patches")
                        return True
                    else:
                        logger.warning("Additive second pass: Failed to apply patches")
                        return False
                else:
                    logger.warning("Additive second pass: All patches filtered out due to conflicts")
                    return False
            else:
                logger.warning("Additive second pass: No patches generated")
                return False
                
        except Exception as e:
            logger.error(f"Exception during additive second pass: {e}")
            return False
    
    def _get_updated_oracle_files(self, instance_id: str, original_oracle_files: Dict[str, str]) -> Dict[str, str]:
        """Get oracle files with their current content after first pass patches."""
        updated_oracle_files = {}
        
        if not self.containers:
            logger.warning("No container manager available - returning original oracle files")
            return original_oracle_files
            
        for file_path, original_content in original_oracle_files.items():
            try:
                # Read current file content from container
                read_command = f"""
cd /workspace &&
if [ -f "{file_path}" ]; then
    cat "{file_path}"
else
    echo "FILE_NOT_FOUND"
fi
"""
                
                exit_code, current_content = self.containers.exec_command(
                    instance_id, read_command, timeout=30
                )
                
                if exit_code == 0 and current_content.strip() != "FILE_NOT_FOUND":
                    updated_oracle_files[file_path] = current_content.strip()
                    logger.debug(f"Updated oracle file: {file_path} ({len(current_content)} chars)")
                else:
                    # If file can't be read, use original content
                    updated_oracle_files[file_path] = original_content
                    logger.debug(f"Keeping original content for: {file_path}")
                    
            except Exception as e:
                logger.warning(f"Failed to read updated content for {file_path}: {e}")
                updated_oracle_files[file_path] = original_content
                
        return updated_oracle_files

    def _get_applied_first_pass_patches(self, instance_id: str) -> str:
        """Get the content of applied first pass patches for conflict analysis."""
        try:
            if not self.containers:
                return ""
            
            # Get git diff showing what was added in first pass
            git_diff_command = """
cd /workspace &&
git diff HEAD~1 HEAD --no-color
"""
            
            exit_code, diff_output = self.containers.exec_command(
                instance_id,
                git_diff_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.debug(f"Retrieved first pass diff: {len(diff_output)} characters")
                return diff_output
            else:
                logger.warning(f"Failed to retrieve first pass diff: {diff_output}")
                return ""
                
        except Exception as e:
            logger.error(f"Exception getting first pass patches: {e}")
            return ""
    
    def _selective_revert_files(self, instance_id: str, conflicting_files: List[str]) -> bool:
        """Revert only specific files that have conflicts."""
        try:
            if not self.containers or not conflicting_files:
                return False
            
            # Create git command to revert only specific files
            files_to_revert = " ".join(f'"{file_path}"' for file_path in conflicting_files)
            revert_command = f"""
cd /workspace &&
echo "=== Reverting conflicting files ===" &&
git checkout HEAD -- {files_to_revert} &&
echo "=== Selective revert completed ==="
"""
            
            exit_code, output = self.containers.exec_command(
                instance_id,
                revert_command,
                workdir="/workspace"
            )
            
            if exit_code == 0:
                logger.info(f"Successfully reverted {len(conflicting_files)} conflicting files")
                return True
            else:
                logger.error(f"Failed to revert files: {output}")
                return False
                
        except Exception as e:
            logger.error(f"Exception during selective revert: {e}")
            return False
    
    def _create_comprehensive_prompt(self, build_log: str, test_patch: str, oracle_files: Dict[str, str]) -> str:
        """Create comprehensive prompt with build log, test patch, and oracle files context."""
        
        oracle_section = ""
        if oracle_files:
            oracle_section = "\n\n**Oracle Files (CURRENT STATE after first pass changes):**\n"
            for filename, content in oracle_files.items():
                oracle_section += f"\n--- {filename} (UPDATED) ---\n{content}\n"
        
        # Extract relevant compilation errors
        relevant_errors = self._extract_relevant_build_errors(build_log)
        
        prompt = f"""You are an Android development expert. Generate Git PATCHES to fix compilation errors.

**CRITICAL: Output patches in unified diff format:**

```PATCH: path/to/file.kt
--- a/path/to/file.kt
+++ b/path/to/file.kt
@@ -line,count +line,count @@
 context line
-removed line  
+added line
 context line
```

**Guidelines:**
1. Generate proper unified diff patches (--- and +++ headers)
2. Include 3-5 context lines before/after changes
3. Make minimal changes to fix compilation only
4. Focus on missing classes, methods, properties
5. Use appropriate default values for new properties
6. Each patch must be self-contained and applicable

**Test Patch Applied:**
```
{test_patch}
```{oracle_section}

**Compilation Errors to Fix:**
```
{relevant_errors}
```

Generate patches to fix these compilation errors. Create missing classes, add missing methods/properties, fix type mismatches.
"""
        
        return prompt
    
    async def _attempt_second_pass(self, instance_id: str, original_build_log: str, 
                                 test_patch: str, oracle_files: Dict[str, str], 
                                 compilation_failure_output: str) -> bool:
        """Attempt a second pass to fix remaining compilation issues."""
        try:
            logger.info("=== STARTING SECOND PASS PATCH GENERATION (CUMULATIVE) ===")
            
            # Create enhanced prompt with both original errors and new compilation failures
            second_pass_prompt = self._create_second_pass_prompt(
                original_build_log, test_patch, oracle_files, compilation_failure_output
            )
            
            # Generate second round of patches
            llm_response = await self._call_llm_api(second_pass_prompt, "second_pass", instance_id)
            if not llm_response:
                logger.error("Second pass: Failed to get LLM response")
                return False
            
            # Parse and log second pass patches
            second_patches = self.generate_patch_from_llm_response(llm_response)
            logger.info(f"Second pass: Generated {len(second_patches)} additional patches")
            self._save_patches_to_files(instance_id, second_patches, "second_pass")
            for i, (file_path, patch_content) in enumerate(second_patches):
                logger.info(f"Second pass patch {i+1}/{len(second_patches)}: {file_path}")
                logger.debug(f"Second pass patch content for {file_path}:\n{patch_content}")
            
            if not second_patches:
                logger.warning("Second pass: No additional patches generated")
                return False
            
            # Apply second round of patches
            success, applied_files = self.apply_patches(instance_id, second_patches)
            
            if success:
                logger.info(f"Second pass: Successfully applied {len(applied_files)} additional patches")
                return True
            else:
                logger.warning("Second pass: Failed to apply additional patches")
                return False
                
        except Exception as e:
            logger.error(f"Exception during second pass: {e}")
            return False
    
    async def _attempt_second_pass_independent(self, instance_id: str, original_build_log: str, 
                                             test_patch: str, oracle_files: Dict[str, str], 
                                             compilation_failure_output: str) -> bool:
        """Attempt independent second pass without cumulative patches."""
        try:
            logger.info("=== STARTING SECOND PASS PATCH GENERATION (INDEPENDENT) ===")
            
            # Create comprehensive prompt that addresses ALL original errors in one go
            # This avoids the cumulative issue by generating complete patches
            second_pass_prompt = self._create_comprehensive_second_pass_prompt(
                original_build_log, test_patch, oracle_files, compilation_failure_output
            )
            
            # Generate complete second round of patches
            llm_response = await self._call_llm_api(second_pass_prompt, "second_pass_independent", instance_id)
            if not llm_response:
                logger.error("Second pass independent: Failed to get LLM response")
                return False
            
            # Parse and log second pass patches
            second_patches = self.generate_patch_from_llm_response(llm_response)
            logger.info(f"Second pass independent: Generated {len(second_patches)} complete patches")
            self._save_patches_to_files(instance_id, second_patches, "second_pass_independent")
            for i, (file_path, patch_content) in enumerate(second_patches):
                logger.info(f"Second pass independent patch {i+1}/{len(second_patches)}: {file_path}")
                logger.debug(f"Second pass independent patch content for {file_path}:\n{patch_content}")
            
            if not second_patches:
                logger.warning("Second pass independent: No patches generated")
                return False
            
            # Apply complete second round of patches
            success, applied_files = self.apply_patches(instance_id, second_patches)
            
            if success:
                logger.info(f"Second pass independent: Successfully applied {len(applied_files)} complete patches")
                return True
            else:
                logger.warning("Second pass independent: Failed to apply patches")
                return False
                
        except Exception as e:
            logger.error(f"Exception during second pass independent: {e}")
            return False
    
    def _create_second_pass_prompt(self, original_build_log: str, test_patch: str, 
                                  oracle_files: Dict[str, str], compilation_failure_output: str) -> str:
        """Create enhanced prompt for second pass with compilation failure analysis."""
        
        oracle_section = ""
        if oracle_files:
            oracle_section = "\n\n**Oracle Files (CURRENT STATE after first pass changes):**\n"
            for filename, content in oracle_files.items():
                oracle_section += f"\n--- {filename} (UPDATED) ---\n{content}\n"
        
        # Extract relevant errors from both logs
        original_errors = self._extract_relevant_build_errors(original_build_log)
        new_errors = self._extract_relevant_build_errors(compilation_failure_output)
        
        prompt = f"""You are an Android development expert. This is a SECOND PASS to fix remaining compilation errors after initial patches were applied.

**CRITICAL: Output patches in unified diff format:**

```PATCH: path/to/file.kt
--- a/path/to/file.kt
+++ b/path/to/file.kt
@@ -line,count +line,count @@
 context line
-removed line  
+added line
 context line
```

**CONTEXT:**
- Initial patches were applied but compilation still fails
- Focus on NEW/REMAINING errors from the latest compilation attempt
- Some issues may have been partially fixed, look for follow-up problems
- Consider dependencies between classes that may now be missing

**Test Patch Applied:**
```
{test_patch}
```{oracle_section}

**ORIGINAL Build Errors (for context):**
```
{original_errors}
```

**REMAINING Compilation Errors After First Pass:**
```
{new_errors}
```

**Guidelines for Second Pass:**
1. Focus ONLY on the remaining errors from the latest compilation
2. Look for cascading issues caused by first pass changes
3. Add missing imports, methods, or properties that are now needed
4. Fix type mismatches introduced by first pass
5. Ensure consistency across related files
6. Make minimal, targeted fixes only

Generate patches to fix the REMAINING compilation errors shown above.
"""
        
        return prompt
    
    def _create_comprehensive_second_pass_prompt(self, original_build_log: str, test_patch: str, 
                                                oracle_files: Dict[str, str], compilation_failure_output: str) -> str:
        """Create comprehensive prompt for independent second pass that addresses all errors."""
        
        oracle_section = ""
        if oracle_files:
            oracle_section = "\n\n**Oracle Files (CURRENT STATE after first pass changes):**\n"
            for filename, content in oracle_files.items():
                oracle_section += f"\n--- {filename} (UPDATED) ---\n{content}\n"
        
        # Extract and combine all relevant errors
        original_errors = self._extract_relevant_build_errors(original_build_log)
        first_pass_errors = self._extract_relevant_build_errors(compilation_failure_output)
        
        prompt = f"""You are an Android development expert. Generate COMPLETE patches to fix ALL compilation errors.

**CRITICAL INSTRUCTIONS:**
1. This is a FRESH START - ignore any previous patch attempts
2. Generate patches that fix ALL the original compilation errors in one comprehensive pass
3. Learn from the first pass errors to avoid conflicts (e.g., duplicate declarations)
4. Output patches in unified diff format with proper headers

**PATCH FORMAT:**
```PATCH: path/to/file.kt
--- a/path/to/file.kt
+++ b/path/to/file.kt
@@ -line,count +line,count @@
 context line
-removed line  
+added line
 context line
```

**ANALYSIS:**
- Original compilation had missing symbols/references
- First pass attempt caused conflicting declarations
- Need to provide complete, non-conflicting implementations

**Test Patch Applied:**
```
{test_patch}
```{oracle_section}

**ORIGINAL Compilation Errors (main issues to fix):**
```
{original_errors}
```

**First Pass Attempt Results (learn from these conflicts):**
```
{first_pass_errors}
```

**STRATEGY:**
1. Create complete class/interface definitions without default values that cause conflicts
2. Add all required properties and methods in proper Kotlin syntax
3. Ensure consistent property declarations across all related files
4. Provide complete implementations, not partial additions

Generate comprehensive patches that fix ALL compilation errors while avoiding the conflicts seen in the first attempt.
"""
        
        return prompt
    
    def _create_selective_second_pass_prompt(self, original_build_log: str, test_patch: str,
                                           oracle_files: Dict[str, str], compilation_output: str,
                                           conflict_analysis: Dict[str, Any], preserved_files: List[str]) -> str:
        """Create prompt for selective second pass that preserves successful first pass changes."""
        
        oracle_section = ""
        if oracle_files:
            oracle_section = "\n\n**Oracle Files (CURRENT STATE after first pass changes):**\n"
            for filename, content in oracle_files.items():
                oracle_section += f"\n--- {filename} (UPDATED) ---\n{content}\n"
        
        preserved_section = ""
        if preserved_files:
            preserved_section = f"\n\n**PRESERVED FILES (DO NOT MODIFY - these were successfully fixed in first pass):**\n"
            for file_path in conflict_analysis["safe_files"]:
                preserved_section += f"- {file_path}\n"
        
        conflicting_files_section = ""
        if conflict_analysis["conflicting_files"]:
            conflicting_files_section = f"\n\n**CONFLICTING FILES (these have been reverted and need fixes):**\n"
            for file_path in conflict_analysis["conflicting_files"]:
                conflicting_files_section += f"- {file_path}\n"
        
        original_errors = self._extract_relevant_build_errors(original_build_log)
        conflict_errors = self._extract_relevant_build_errors(compilation_output)
        
        prompt = f"""You are an Android development expert. Generate SELECTIVE patches to fix ONLY the conflicting files.

**CRITICAL INSTRUCTIONS:**
1. Some files were successfully fixed in the first pass - DO NOT touch preserved files
2. Only generate patches for conflicting files that have been reverted to clean state
3. Learn from the conflict patterns to avoid duplicate declarations
4. Focus on the specific files that caused conflicts

**PATCH FORMAT:**
```PATCH: path/to/file.kt
--- a/path/to/file.kt
+++ b/path/to/file.kt
@@ -line,count +line,count @@
 context line
-removed line  
+added line
 context line
```

**Test Patch Applied:**
```
{test_patch}
```{oracle_section}{preserved_section}{conflicting_files_section}

**ORIGINAL Compilation Errors:**
```
{original_errors}
```

**FIRST PASS CONFLICT Analysis:**
```
{conflict_errors}
```

**STRATEGY:**
1. ONLY create patches for files in the conflicting files list
2. Ensure compatibility with preserved files that were successfully fixed
3. Avoid the specific conflict patterns identified (duplicate declarations, etc.)
4. Generate complete, non-conflicting implementations for conflicting files only

Generate patches ONLY for the conflicting files to resolve the conflicts while preserving first pass successes.
"""
        
        return prompt
    
    def _create_additive_second_pass_prompt(self, original_build_log: str, test_patch: str,
                                          oracle_files: Dict[str, str], compilation_output: str) -> str:
        """Create prompt for additive second pass that builds on first pass success."""
        
        oracle_section = ""
        if oracle_files:
            oracle_section = "\n\n**Oracle Files (CURRENT STATE after first pass changes):**\n"
            for filename, content in oracle_files.items():
                oracle_section += f"\n--- {filename} (UPDATED) ---\n{content}\n"
        
        original_errors = self._extract_relevant_build_errors(original_build_log)
        remaining_errors = self._extract_relevant_build_errors(compilation_output)
        
        prompt = f"""You are an Android development expert. Generate ADDITIVE patches to complete the compilation fix.

**CONTEXT:**
- First pass patches were successful but compilation still has remaining issues
- Build on the existing successful changes, don't duplicate them
- Focus on the NEW/REMAINING errors that weren't addressed by first pass

**PATCH FORMAT:**
```PATCH: path/to/file.kt
--- a/path/to/file.kt
+++ b/path/to/file.kt
@@ -line,count +line,count @@
 context line
-removed line  
+added line
 context line
```

**CONFLICT AVOIDANCE STRATEGY:**
1. **ANALYZE FIRST:** Examine the test patch to understand what was already changed
2. **AVOID DUPLICATES:** Never add properties, methods, or classes that already exist
3. **CHECK CONFLICTS:** Look for "Conflicting declarations" errors - these mean duplicate definitions
4. **COMPLEMENT CHANGES:** Add only what's missing, don't recreate existing elements
5. **VERIFY SYNTAX:** Ensure proper Kotlin/Java syntax and access modifiers

**ERROR-SPECIFIC STRATEGIES:**
- **"Conflicting declarations"**: Remove duplicate definitions, keep only one version
- **"cannot be applied to given types"**: Fix constructor/method signatures, don't add new ones
- **"has private access"**: Change access modifiers or use proper APIs, don't create duplicates
- **"Unresolved reference"**: Add missing imports or create missing elements, check existing first

**ADDITIVE APPROACH:**
1. First pass already made some successful changes - build on them
2. EXAMINE the updated oracle files to see current file state after first pass
3. Address ONLY the remaining compilation errors shown below
4. Add missing pieces without conflicting with existing changes
5. Complete the implementation where first pass left gaps
6. DO NOT recreate anything that exists in the current file state

**Test Patch Applied (analyze this first):**
```
{test_patch}
```{oracle_section}

**ORIGINAL Compilation Errors (for context):**
```
{original_errors}
```

**REMAINING Errors (focus ONLY on these specific errors):**
```
{remaining_errors}
```

**CRITICAL:** Before generating any patch, analyze the remaining errors carefully:
- If you see "Conflicting declarations", identify what's duplicated and remove conflicts
- If you see constructor errors, fix signatures without adding new constructors
- If you see access errors, modify access levels without creating duplicates

Generate ADDITIVE patches that complete the compilation fix by addressing the remaining errors.
"""
        
        return prompt
    
    def _save_patches_to_files(self, instance_id: str, patches: List[Tuple[str, str]], pass_name: str):
        """Save generated patches to organized log files."""
        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            output_dir = self.base_output_dir / instance_id / "patch_logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Save individual patch files
            for i, (file_path, patch_content) in enumerate(patches):
                # Create safe filename from file path
                safe_filename = file_path.replace('/', '_').replace('\\', '_').replace(':', '_')
                patch_filename = f"{pass_name}_{timestamp}_{i+1:02d}_{safe_filename}.patch"
                patch_file = output_dir / patch_filename
                
                with open(patch_file, 'w', encoding='utf-8') as f:
                    f.write(f"# Patch for: {file_path}\n")
                    f.write(f"# Generated: {timestamp}\n")
                    f.write(f"# Pass: {pass_name}\n")
                    f.write(f"# Patch {i+1}/{len(patches)}\n\n")
                    f.write(patch_content)
                
                logger.debug(f"Saved patch to: {patch_file}")
            
            # Save summary file with all patches
            summary_filename = f"{pass_name}_{timestamp}_all_patches.txt"
            summary_file = output_dir / summary_filename
            
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(f"Patch Generation Summary - {pass_name.upper()}\n")
                f.write(f"Instance ID: {instance_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Total Patches: {len(patches)}\n")
                f.write("=" * 80 + "\n\n")
                
                for i, (file_path, patch_content) in enumerate(patches):
                    f.write(f"PATCH {i+1}/{len(patches)}: {file_path}\n")
                    f.write("-" * 60 + "\n")
                    f.write(patch_content)
                    f.write("\n\n" + "=" * 80 + "\n\n")
            
            logger.info(f"Saved {len(patches)} patches to: {output_dir}")
            
        except Exception as e:
            logger.error(f"Failed to save patches to files: {e}")
    
    def _save_gradle_output_to_file(self, instance_id: str, gradle_output: str, exit_code: int):
        """Save gradle compilation output to organized log files."""
        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            output_dir = self.base_output_dir / instance_id / "compilation_logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Determine success/failure for filename
            status = "success" if exit_code == 0 else "failure"
            filename = f"gradle_{status}_{timestamp}.log"
            log_file = output_dir / filename
            
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"Gradle Compilation Log\n")
                f.write(f"Instance ID: {instance_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Exit Code: {exit_code}\n")
                f.write(f"Status: {status.upper()}\n")
                f.write("=" * 80 + "\n\n")
                f.write(gradle_output)
            
            logger.info(f"Saved gradle output ({status}) to: {log_file}")
            
        except Exception as e:
            logger.error(f"Failed to save gradle output to file: {e}")
    
    def _save_prompt_to_file(self, instance_id: str, prompt: str, pass_name: str):
        """Save LLM prompt to organized log files."""
        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            output_dir = self.base_output_dir / instance_id / "llm_logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"{pass_name}_prompt_{timestamp}.txt"
            log_file = output_dir / filename
            
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"LLM Prompt Log - {pass_name.upper()}\n")
                f.write(f"Instance ID: {instance_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Model: {self.model}\n")
                f.write("=" * 80 + "\n\n")
                f.write(prompt)
            
            logger.info(f"Saved {pass_name} prompt to: {log_file}")
            
        except Exception as e:
            logger.error(f"Failed to save prompt to file: {e}")
    
    def _save_llm_response_to_file(self, instance_id: str, response: str, pass_name: str):
        """Save LLM response to organized log files."""
        try:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            output_dir = self.base_output_dir / instance_id / "llm_logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"{pass_name}_response_{timestamp}.txt"
            log_file = output_dir / filename
            
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"LLM Response Log - {pass_name.upper()}\n")
                f.write(f"Instance ID: {instance_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Model: {self.model}\n")
                f.write("=" * 80 + "\n\n")
                f.write(response)
            
            logger.info(f"Saved {pass_name} response to: {log_file}")
            
        except Exception as e:
            logger.error(f"Failed to save response to file: {e}")
    
    def _extract_relevant_build_errors(self, build_log: str) -> str:
        """Extract detailed compilation errors from verbose build log."""
        lines = build_log.split('\n')
        relevant_lines = []
        
        # Enhanced patterns for detailed compilation errors
        error_patterns = [
            # Kotlin compilation errors
            r'e: file:///.+\.kt:\d+:\d+',  # Kotlin error location
            r'No parameter with name', # Missing parameter
            r'Too many arguments for', # Extra arguments
            r'Conflicting declarations:',   # Conflicting declarations
            r'Conflicting overloads:',   # Conflicting overloads
            r'Unresolved reference',        # Missing references
            r'overrides nothing',      # Override errors
            r'Type mismatch',              # Type errors
            r'cannot be applied to given types',  # Constructor/method signature errors
            r'has private access',         # Access violations
            r'cannot find symbol',        # Java symbol errors
            r'package .+ does not exist', # Missing packages
            # Java compilation errors
            r'error: cannot find symbol',
            r'error: package .+ does not exist',
            r'error: constructor .+ cannot be applied to given types',
            r'error: .+ has private access',
            r'error: incompatible types',
            # General build failures
            r'BUILD FAILED',
            r'Compilation failed',
            r'FAILED$',  # Task failures
        ]
        
        # Track context for multi-line errors
        in_error_context = False
        context_lines = 0
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Check if this line matches an error pattern
            if any(re.search(pattern, line_stripped, re.IGNORECASE) for pattern in error_patterns):
                relevant_lines.append(line_stripped)
                in_error_context = True
                context_lines = 0
            
            # Capture context after error lines (for multi-line error details)
            elif in_error_context and context_lines < 3:
                # Include indented lines or lines that look like error details
                if (line_stripped and 
                    (line.startswith('  ') or line.startswith('\t') or 
                     any(keyword in line_stripped.lower() for keyword in 
                         ['val ', 'fun ', 'class ', 'interface ', ':', '=', 'expected', 'actual']))):
                    relevant_lines.append(line_stripped)
                    context_lines += 1
                else:
                    in_error_context = False
                    context_lines = 0
            else:
                in_error_context = False
                context_lines = 0
        
        # Enhanced extraction: look for task failure sections
        if not relevant_lines or len(relevant_lines) < 5:
            # Look for task failure sections with more context
            task_failure_section = []
            in_failure_section = False
            
            for line in lines:
                if 'FAILED' in line and ('Task' in line or ':' in line):
                    in_failure_section = True
                    task_failure_section = [line.strip()]
                elif in_failure_section:
                    if line.strip() and not line.startswith('>'):
                        task_failure_section.append(line.strip())
                    elif line.startswith('>') and len(task_failure_section) > 10:
                        break
            
            if task_failure_section:
                relevant_lines.extend(task_failure_section)
        
        # If we found relevant errors, return them with better formatting
        if relevant_lines:
            # Remove duplicates while preserving order
            seen = set()
            unique_lines = []
            for line in relevant_lines:
                if line not in seen and len(line.strip()) > 0:
                    seen.add(line)
                    unique_lines.append(line)
            
            return '\n'.join(unique_lines)
        
        # Enhanced fallback: look for any compilation output section
        compilation_section = []
        for i, line in enumerate(lines):
            if ('compileDebug' in line or 'compilation' in line.lower()) and 'FAILED' in line:
                # Get surrounding context
                start = max(0, i - 10)
                end = min(len(lines), i + 20)
                compilation_section = lines[start:end]
                break
        
        if compilation_section:
            return '\n'.join([l.strip() for l in compilation_section if l.strip()])
        
        # Final fallback: return last part of build log
        return '\n'.join(lines[-50:]) if len(lines) > 50 else build_log
    
    async def _call_llm_api(self, prompt: str, pass_name: str = "first_pass", instance_id: str = None) -> str:
        """Call OpenRouter API to generate patches."""
        if not self.api_key:
            raise Exception("No API key provided for LLM call")

        # Save prompt to log file before making API call
        if instance_id:
            self._save_prompt_to_file(instance_id, prompt, pass_name)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/mobile-bench",
            "X-Title": "Mobile-Bench Patch Generator"
        }

        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0.1,
            "top_p": 0.95
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    llm_response = result['choices'][0]['message']['content']
                    
                    # Save LLM response to log file
                    if instance_id:
                        self._save_llm_response_to_file(instance_id, llm_response, pass_name)
                    
                    return llm_response
                else:
                    error_text = await response.text()
                    raise Exception(f"API call failed with status {response.status}: {error_text}")
    
    def _calculate_api_cost(self, prompt: str, response: str) -> float:
        """Calculate API cost based on token usage estimate."""
        # Rough estimation: 1 token ≈ 4 characters
        input_tokens = len(prompt) // 4
        output_tokens = len(response) // 4
        
        if self.model in self.model_costs:
            costs = self.model_costs[self.model]
            return (input_tokens * costs["input"]) + (output_tokens * costs["output"])
        
        # Fallback estimation
        return (input_tokens * 0.000003) + (output_tokens * 0.000015)
    
    def _save_original_commit_hash(self, instance_id: str) -> bool:
        """Save the original commit hash before applying stub patches."""
        try:
            if not self.containers:
                logger.warning("No container manager available to save original commit hash")
                return False
                
            # Check if already saved to avoid overwriting
            check_existing_command = """
cd /workspace &&
if [ -f '.original_commit_before_stubs' ]; then
    echo "ALREADY_EXISTS"
else
    echo "NOT_EXISTS"
fi
"""
            
            exit_code, check_result = self.containers.exec_command(
                instance_id, check_existing_command, timeout=30
            )
            
            if exit_code == 0 and check_result.strip() == "ALREADY_EXISTS":
                logger.debug(f"Original commit hash already saved for {instance_id}")
                return True
                
            # Get current commit hash
            get_commit_command = """
cd /workspace &&
git rev-parse HEAD
"""
            
            exit_code, commit_hash = self.containers.exec_command(
                instance_id, get_commit_command, timeout=30
            )
            
            if exit_code == 0 and commit_hash.strip():
                # Save the original commit hash to a file
                save_commit_command = f"""
cd /workspace &&
echo '{commit_hash.strip()}' > .original_commit_before_stubs &&
echo "Saved original commit: {commit_hash.strip()}"
"""
                
                exit_code, output = self.containers.exec_command(
                    instance_id, save_commit_command, timeout=30
                )
                
                if exit_code == 0:
                    logger.info(f"Saved original commit hash for {instance_id}: {commit_hash.strip()}")
                    return True
                else:
                    logger.warning(f"Failed to save original commit hash: {output}")
                    return False
            else:
                logger.warning(f"Failed to get current commit hash: {commit_hash}")
                return False
                
        except Exception as e:
            logger.error(f"Exception saving original commit hash: {e}")
            return False
    
    def get_original_commit_hash(self, instance_id: str) -> str:
        """Get the original commit hash before stub patches were applied."""
        try:
            if not self.containers:
                logger.warning("No container manager available to get original commit hash")
                return ""
                
            # Read the saved commit hash
            get_saved_commit_command = """
cd /workspace &&
if [ -f '.original_commit_before_stubs' ]; then
    cat .original_commit_before_stubs
else
    echo "NOT_FOUND"
fi
"""
            
            exit_code, commit_hash = self.containers.exec_command(
                instance_id, get_saved_commit_command, timeout=30
            )
            
            if exit_code == 0 and commit_hash.strip() != "NOT_FOUND":
                logger.debug(f"Retrieved original commit hash for {instance_id}: {commit_hash.strip()}")
                return commit_hash.strip()
            else:
                logger.warning(f"Original commit hash not found for {instance_id}")
                return ""
                
        except Exception as e:
            logger.error(f"Exception getting original commit hash: {e}")
            return ""


def create_enhanced_prompt_for_patches() -> str:
    """Create a prompt that asks LLM to generate patches instead of MODIFY blocks."""
    
    return """
You are an Android development expert. Generate PATCHES (not stub files) to fix compilation errors.

**CRITICAL: Generate patches in this format:**

```PATCH: path/to/file.kt
--- a/path/to/file.kt
+++ b/path/to/file.kt
@@ -line,count +line,count @@
 context line
-removed line
+added line
 context line
```

**Guidelines:**
1. Use proper unified diff format (--- and +++ headers)
2. Include sufficient context lines (3-5 before/after changes)
3. Make minimal, targeted changes only
4. Focus on compilation fixes, not full implementations
5. Each patch should be self-contained and applicable

**Example:**
```PATCH: core/preference/privacy/PrivacySettings.kt
--- a/core/preference/privacy/PrivacySettings.kt
+++ b/core/preference/privacy/PrivacySettings.kt
@@ -1,3 +1,4 @@
 data class PrivacySettings(
     val isHideTimeZone: Boolean,
+    val isHideUserAgent: Boolean = false,
 )
```

Generate patches to fix the compilation errors in the build log.
"""


if __name__ == "__main__":
    # Example usage
    generator = PatchBasedStubGenerator("/home/researchuser/dev/mobile-bench")
    
    # Mock LLM response with patches
    llm_response = """
```PATCH: core/preference/privacy/PrivacySettings.kt
--- a/core/preference/privacy/PrivacySettings.kt
+++ b/core/preference/privacy/PrivacySettings.kt
@@ -1,3 +1,4 @@
 data class PrivacySettings(
     val isHideTimeZone: Boolean,
+    val isHideUserAgent: Boolean = false,
 )
```
"""

