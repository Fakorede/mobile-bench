#!/usr/bin/env python3

"""
Mobile-Bench Test Specification
Defines test specifications and execution plans for Android projects.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import docker


@dataclass
class AndroidTestSpec:
    """Complete specification for testing an Android instance"""
    
    # Core identification
    instance_id: str
    repo_url: str
    base_commit: str
    patch: str
    
    # Test configuration
    test_commands: List[str] = field(default_factory=list)
    build_commands: List[str] = field(default_factory=list)
    setup_commands: List[str] = field(default_factory=list)
    
    # Environment configuration
    java_version: str = "17"
    gradle_version: Optional[str] = None
    has_kotlin: bool = False
    min_sdk: Optional[int] = None
    target_sdk: Optional[int] = None
    compile_sdk: Optional[int] = None
    
    # Execution configuration
    timeout: int = 1800
    memory_limit: str = "4g"
    cpu_count: Optional[int] = None
    
    # Test expectations
    expected_pass_tests: List[str] = field(default_factory=list)
    expected_fail_tests: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def repo_name(self) -> str:
        """Extract repository name from URL"""
        if '/' in self.repo_url:
            return self.repo_url.split('/')[-1].replace('.git', '')
        return self.repo_url
    
    @property
    def container_name(self) -> str:
        """Generate unique container name"""
        hash_str = hashlib.md5(f"{self.instance_id}_{self.repo_url}_{self.base_commit}".encode()).hexdigest()[:8]
        return f"mobile_bench_{self.instance_id}_{hash_str}"
    
    @property
    def workspace_path(self) -> str:
        """Get workspace path inside container"""
        return f"/workspace/{self.repo_name}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'instance_id': self.instance_id,
            'repo_url': self.repo_url,
            'base_commit': self.base_commit,
            'patch': self.patch,
            'test_commands': self.test_commands,
            'build_commands': self.build_commands,
            'setup_commands': self.setup_commands,
            'java_version': self.java_version,
            'gradle_version': self.gradle_version,
            'has_kotlin': self.has_kotlin,
            'min_sdk': self.min_sdk,
            'target_sdk': self.target_sdk,
            'compile_sdk': self.compile_sdk,
            'timeout': self.timeout,
            'memory_limit': self.memory_limit,
            'cpu_count': self.cpu_count,
            'expected_pass_tests': self.expected_pass_tests,
            'expected_fail_tests': self.expected_fail_tests,
            'created_at': self.created_at,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AndroidTestSpec':
        """Create from dictionary"""
        return cls(**data)


class AndroidTestSpecBuilder:
    """Builds AndroidTestSpec from various input formats"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def build_from_instance(self, 
                          instance: Dict[str, Any], 
                          prediction: Dict[str, Any]) -> AndroidTestSpec:
        """Build test spec from instance and prediction data"""
        
        # Extract core information
        instance_id = instance['instance_id']
        repo_url = instance.get('repo', instance.get('repository', ''))
        base_commit = instance.get('base_commit', instance.get('commit', ''))
        patch = prediction.get('patch', prediction.get('model_patch', ''))
        
        # Extract test configuration
        test_commands = self._extract_test_commands(instance)
        build_commands = self._extract_build_commands(instance)
        setup_commands = self._extract_setup_commands(instance)
        
        # Extract expected test results
        expected_pass_tests = instance.get('PASS_TO_PASS', [])
        expected_fail_tests = instance.get('FAIL_TO_PASS', [])
        
        # Create test spec
        spec = AndroidTestSpec(
            instance_id=instance_id,
            repo_url=repo_url,
            base_commit=base_commit,
            patch=patch,
            test_commands=test_commands,
            build_commands=build_commands,
            setup_commands=setup_commands,
            expected_pass_tests=expected_pass_tests,
            expected_fail_tests=expected_fail_tests,
            timeout=instance.get('timeout', 1800),
            metadata=instance.get('metadata', {})
        )
        
        return spec
    
    def _extract_test_commands(self, instance: Dict[str, Any]) -> List[str]:
        """Extract test commands from instance data"""
        commands = []
        
        # Check for explicit test commands
        if 'test_commands' in instance:
            commands.extend(instance['test_commands'])
        elif 'test_cmd' in instance:
            cmd = instance['test_cmd']
            if isinstance(cmd, list):
                commands.extend(cmd)
            else:
                commands.append(cmd)
        
        # Default Android test commands if none specified
        if not commands:
            commands = [
                "./gradlew test",
                "./gradlew connectedAndroidTest",
                "./gradlew testDebugUnitTest"
            ]
        
        return commands
    
    def _extract_build_commands(self, instance: Dict[str, Any]) -> List[str]:
        """Extract build commands from instance data"""
        commands = []
        
        if 'build_commands' in instance:
            commands.extend(instance['build_commands'])
        elif 'build_cmd' in instance:
            cmd = instance['build_cmd']
            if isinstance(cmd, list):
                commands.extend(cmd)
            else:
                commands.append(cmd)
        
        # Default Android build commands if none specified
        if not commands:
            commands = [
                "./gradlew clean",
                "./gradlew assembleDebug",
                "./gradlew compileDebugSources"
            ]
        
        return commands
    
    def _extract_setup_commands(self, instance: Dict[str, Any]) -> List[str]:
        """Extract setup commands from instance data"""
        commands = []
        
        if 'setup_commands' in instance:
            commands.extend(instance['setup_commands'])
        elif 'pre_install' in instance:
            commands.extend(instance['pre_install'])
        
        # Default setup commands for Android projects
        if not commands:
            commands = [
                "chmod +x ./gradlew",
                "export ANDROID_SDK_ROOT=/opt/android-sdk",
                "export ANDROID_HOME=/opt/android-sdk"
            ]
        
        return commands


class AndroidExecutionPlan:
    """Defines execution plan for Android test instances"""
    
    def __init__(self, test_spec: AndroidTestSpec):
        self.test_spec = test_spec
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def generate_setup_script(self) -> str:
        """Generate setup script for the container"""
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            "# Setup Android environment",
            "export ANDROID_SDK_ROOT=/opt/android-sdk",
            "export ANDROID_HOME=/opt/android-sdk",
            "export PATH=$PATH:$ANDROID_SDK_ROOT/tools:$ANDROID_SDK_ROOT/platform-tools",
            "",
            "# Setup Java environment",
            f"export JAVA_VERSION={self.test_spec.java_version}",
            "",
            "# Initialize jenv if available",
            "if command -v jenv &> /dev/null; then",
            '    eval "$(jenv init -)"',
            f"    jenv global {self.test_spec.java_version} || jenv global {self.test_spec.java_version}.0 || true",
            "fi",
            "",
            "# Create workspace",
            f"mkdir -p {self.test_spec.workspace_path}",
            f"cd {self.test_spec.workspace_path}",
            "",
            "# Clone repository",
            f"git clone --recursive {self.test_spec.repo_url} .",
            f"git checkout {self.test_spec.base_commit}",
            "git submodule update --init --recursive",
            "",
            "# Run custom setup commands"
        ]
        
        for command in self.test_spec.setup_commands:
            script_lines.append(command)
        
        return "\n".join(script_lines)
    
    def generate_patch_script(self) -> str:
        """Generate script to apply the patch"""
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            f"cd {self.test_spec.workspace_path}",
            "",
            "# Save current git state",
            "git stash push -m 'pre-patch-state' || true",
            "",
            "# Apply patch using different methods",
            "echo 'Applying patch...'",
            "",
            "# Method 1: git apply",
            "if git apply --check - <<'EOF'",
            self.test_spec.patch,
            "EOF",
            "then",
            "    git apply - <<'EOF'",
            self.test_spec.patch,
            "EOF",
            "    echo 'Patch applied successfully with git apply'",
            "    exit 0",
            "fi",
            "",
            "# Method 2: git apply with --reject",
            "if git apply --reject --verbose - <<'EOF'",
            self.test_spec.patch,
            "EOF",
            "then",
            "    echo 'Patch applied with some rejects using git apply --reject'",
            "    exit 0",
            "fi",
            "",
            "# Method 3: patch command",
            "if patch -p1 --batch --fuzz=5 <<'EOF'",
            self.test_spec.patch,
            "EOF",
            "then",
            "    echo 'Patch applied successfully with patch command'",
            "    exit 0",
            "fi",
            "",
            "echo 'Failed to apply patch'",
            "exit 1"
        ]
        
        return "\n".join(script_lines)
    
    def generate_build_script(self) -> str:
        """Generate build script"""
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            f"cd {self.test_spec.workspace_path}",
            "",
            "# Clear Gradle caches",
            "rm -rf ~/.gradle/caches/ || true",
            "rm -rf .gradle/ || true",
            "",
            "# Ensure gradlew is executable",
            "chmod +x ./gradlew || true",
            "",
            "# Set Gradle properties",
            "export GRADLE_OPTS='-Xmx4g -Dorg.gradle.daemon=false'",
            "",
            "# Run build commands"
        ]
        
        for command in self.test_spec.build_commands:
            script_lines.extend([
                f"echo 'Running: {command}'",
                f"timeout {self.test_spec.timeout} {command}",
                ""
            ])
        
        return "\n".join(script_lines)
    
    def generate_test_script(self) -> str:
        """Generate test execution script"""
        script_lines = [
            "#!/bin/bash",
            "",
            f"cd {self.test_spec.workspace_path}",
            "",
            "# Ensure gradlew is executable",
            "chmod +x ./gradlew || true",
            "",
            "# Set test environment",
            "export GRADLE_OPTS='-Xmx4g -Dorg.gradle.daemon=false'",
            "",
            "# Run test commands",
            "TEST_EXIT_CODE=0"
        ]
        
        for i, command in enumerate(self.test_spec.test_commands):
            script_lines.extend([
                f"echo 'Running test command {i+1}: {command}'",
                f"timeout {self.test_spec.timeout} {command} || TEST_EXIT_CODE=$?",
                ""
            ])
        
        script_lines.extend([
            "# Collect test results",
            "echo '=== COLLECTING TEST RESULTS ==='",
            "find . -name 'TEST-*.xml' -o -name '*test-results.xml' | head -10",
            "",
            "exit $TEST_EXIT_CODE"
        ])
        
        return "\n".join(script_lines)


class AndroidTestSpecValidator:
    """Validates Android test specifications"""
    
    @staticmethod
    def validate(test_spec: AndroidTestSpec) -> tuple[bool, List[str]]:
        """Validate test specification"""
        errors = []
        
        # Check required fields
        if not test_spec.instance_id:
            errors.append("instance_id is required")
        
        if not test_spec.repo_url:
            errors.append("repo_url is required")
        
        if not test_spec.base_commit:
            errors.append("base_commit is required")
        
        # Validate repository URL
        if test_spec.repo_url and not AndroidTestSpecValidator._is_valid_repo_url(test_spec.repo_url):
            errors.append(f"Invalid repository URL: {test_spec.repo_url}")
        
        # Validate commit hash
        if test_spec.base_commit and not AndroidTestSpecValidator._is_valid_commit_hash(test_spec.base_commit):
            errors.append(f"Invalid commit hash: {test_spec.base_commit}")
        
        # Validate patch
        if test_spec.patch:
            patch_valid, patch_error = AndroidTestSpecValidator._validate_patch(test_spec.patch)
            if not patch_valid:
                errors.append(f"Invalid patch: {patch_error}")
        
        # Validate Java version
        if not AndroidTestSpecValidator._is_valid_java_version(test_spec.java_version):
            errors.append(f"Invalid Java version: {test_spec.java_version}")
        
        # Validate timeout
        if test_spec.timeout <= 0:
            errors.append("timeout must be positive")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def _is_valid_repo_url(url: str) -> bool:
        """Check if repository URL is valid"""
        patterns = [
            r'^https://github\.com/[^/]+/[^/]+(?:\.git)?',
            r'^git@github\.com:[^/]+/[^/]+(?:\.git)?',
            r'^https://gitlab\.com/[^/]+/[^/]+(?:\.git)?'
        ]
        return any(re.match(pattern, url) for pattern in patterns)
    
    @staticmethod
    def _is_valid_commit_hash(commit: str) -> bool:
        """Check if commit hash is valid"""
        return re.match(r'^[a-f0-9]{7,40}, commit) is not None')
    
    @staticmethod
    def _validate_patch(patch: str) -> tuple[bool, str]:
        """Validate patch content"""
        if not patch.strip():
            return False, "Empty patch"
        
        # Check for basic patch format
        if not any(marker in patch for marker in ['diff --git', '--- a/', '+++ b/']):
            return False, "Invalid patch format"
        
        # Check for dangerous commands
        dangerous_patterns = [
            r'rm -rf /',
            r'sudo ',
            r'chmod 777',
            r'>\s*/dev/',
            r'eval.*\$\('
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, patch, re.IGNORECASE):
                return False, f"Patch contains dangerous pattern: {pattern}"
        
        return True, "Valid patch"
    
    @staticmethod
    def _is_valid_java_version(version: str) -> bool:
        """Check if Java version is valid"""
        return re.match(r'^(8|11|17|21), str(version)) is not None')


class AndroidTestSpecManager:
    """Manages Android test specifications"""
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path("./test_specs")
        self.storage_path.mkdir(exist_ok=True)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def save_spec(self, test_spec: AndroidTestSpec) -> Path:
        """Save test specification to file"""
        spec_file = self.storage_path / f"{test_spec.instance_id}.json"
        
        with open(spec_file, 'w') as f:
            json.dump(test_spec.to_dict(), f, indent=2)
        
        self.logger.info(f"Saved test spec for {test_spec.instance_id} to {spec_file}")
        return spec_file
    
    def load_spec(self, instance_id: str) -> AndroidTestSpec:
        """Load test specification from file"""
        spec_file = self.storage_path / f"{instance_id}.json"
        
        if not spec_file.exists():
            raise FileNotFoundError(f"Test spec not found: {spec_file}")
        
        with open(spec_file, 'r') as f:
            data = json.load(f)
        
        return AndroidTestSpec.from_dict(data)
    
    def list_specs(self) -> List[str]:
        """List all available test specifications"""
        spec_files = self.storage_path.glob("*.json")
        return [f.stem for f in spec_files]
    
    def delete_spec(self, instance_id: str) -> bool:
        """Delete test specification"""
        spec_file = self.storage_path / f"{instance_id}.json"
        
        if spec_file.exists():
            spec_file.unlink()
            self.logger.info(f"Deleted test spec for {instance_id}")
            return True
        
        return False
    
    def batch_create_specs(self, 
                          instances: List[Dict[str, Any]], 
                          predictions: Dict[str, Dict[str, Any]]) -> List[AndroidTestSpec]:
        """Create multiple test specifications"""
        builder = AndroidTestSpecBuilder()
        specs = []
        
        for instance in instances:
            instance_id = instance['instance_id']
            
            if instance_id not in predictions:
                self.logger.warning(f"No prediction found for {instance_id}")
                continue
            
            try:
                spec = builder.build_from_instance(instance, predictions[instance_id])
                
                # Validate specification
                is_valid, errors = AndroidTestSpecValidator.validate(spec)
                if not is_valid:
                    self.logger.error(f"Invalid spec for {instance_id}: {errors}")
                    continue
                
                specs.append(spec)
                self.save_spec(spec)
                
            except Exception as e:
                self.logger.error(f"Failed to create spec for {instance_id}: {e}")
        
        self.logger.info(f"Created {len(specs)} valid test specifications")
        return specs
