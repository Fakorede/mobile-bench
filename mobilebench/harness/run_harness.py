#!/usr/bin/env python3

"""
Mobile Bench Android Evaluation Harness

This script evaluates AI-generated patches for Android projects using Docker containers
with the mingchen/docker-android-build-box image for consistent Android build environments.

Usage:
    python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl --run-id test_001
    python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl --run-id test_001 --max-workers 8 --timeout 1800

The script expects predictions in the format:
{
    "instance_id": "AntennaPod-123",
    "model_name_or_path": "gpt-4", 
    "generated_patch": "diff --git a/...",
    "base_commit": "abc123def456"
}
"""

import argparse
import asyncio
import docker
import json
import logging
import os
import subprocess
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_docker_client():
    """
    Get Docker client with fallback to explicit socket path
    """
    # Try the default connection first
    try:
        client = docker.from_env()
        client.ping()
        logger.debug("Docker connection successful with from_env()")
        return client
    except Exception as e:
        logger.debug(f"from_env() failed: {e}")
    
    # Try explicit socket paths
    socket_paths = [
        'unix:///home/thefabdev/.docker/desktop/docker.sock',
        'unix:///var/run/docker.sock',
        'unix:///home/{}/.docker/desktop/docker.sock'.format(os.getenv('USER', 'user')),
    ]
    
    for socket_path in socket_paths:
        try:
            if socket_path.startswith('unix://') and os.path.exists(socket_path[7:]):
                client = docker.DockerClient(base_url=socket_path)
                client.ping()
                logger.info(f"Docker connection successful with explicit path: {socket_path}")
                return client
        except Exception as e:
            logger.debug(f"Failed to connect to {socket_path}: {e}")
    
    raise RuntimeError("Could not establish Docker connection with any method")

@dataclass
class EvaluationConfig:
    """Configuration for the evaluation harness"""
    predictions_file: str
    dataset_file: str
    run_id: str
    max_workers: int = 4
    timeout: int = 1800
    log_dir: str = "logs/harness"
    report_dir: str = "reports"
    cache_dir: str = "cache"
    docker_image: str = "mingc/android-build-box:latest"
    android_api_level: str = "33"
    build_tools_version: str = "33.0.2"
    instance_ids: List[str] = None
    force_rebuild: bool = False
    clean_containers: bool = True
    debug: bool = False
    dry_run: bool = False

@dataclass
class InstanceResult:
    """Result of evaluating a single instance"""
    instance_id: str
    model_name_or_path: str
    status: str  # "completed", "error", "timeout"
    patch_applied: bool = False
    build_success: bool = False
    test_results: str = "UNKNOWN"  # "PASSED", "FAILED", "ERROR"
    resolved: bool = False
    error_message: str = ""
    timestamp: str = ""
    container_name: str = ""
    execution_time: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat() + "Z"

class MobileBenchHarness:
    """Main harness class for mobile bench evaluation"""
    
    def __init__(self, config: EvaluationConfig):
        self.config = config
        self.docker_client = None
        self.predictions = {}
        self.dataset = {}
        self.instances_to_eval = []
        self.results = {}
        self.running_containers = set()
        
        # Setup directories
        self.log_dir = Path(config.log_dir) / config.run_id
        self.report_dir = Path(config.report_dir)
        self.cache_dir = Path(config.cache_dir)
        
        # Setup logging for this run
        self.setup_run_logging()
        
        # Signal handling for cleanup
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def setup_run_logging(self):
        """Setup logging for this specific run"""
        if self.config.debug:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Create run-specific log file
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(self.log_dir / "harness.log")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle interruption signals"""
        logger.warning(f"Received signal {signum}, cleaning up...")
        self.cleanup()
        sys.exit(1)
    
    def setup_directories(self):
        """Create necessary directories"""
        logger.info("Setting up directories...")
        
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.debug(f"Created directories:")
        logger.debug(f"  Log dir: {self.log_dir}")
        logger.debug(f"  Report dir: {self.report_dir}")
        logger.debug(f"  Cache dir: {self.cache_dir}")
    
    def validate_dependencies(self):
        """Validate required dependencies"""
        logger.info("Validating dependencies...")
        
        # Check Docker
        try:
            self.docker_client = get_docker_client()
            self.docker_client.ping()
            logger.debug("Docker client initialized successfully")
        except Exception as e:
            raise RuntimeError(f"Docker is not available: {e}")
        
        # Check required files
        if not Path(self.config.predictions_file).exists():
            raise FileNotFoundError(f"Predictions file not found: {self.config.predictions_file}")
        
        if not Path(self.config.dataset_file).exists():
            raise FileNotFoundError(f"Dataset file not found: {self.config.dataset_file}")
        
        logger.info("All dependencies validated")
    
    def pull_docker_image(self):
        """Pull the Docker image if not available"""
        logger.info(f"Checking Docker image: {self.config.docker_image}")
        
        if self.config.dry_run:
            logger.info(f"DRY RUN: Would pull Docker image {self.config.docker_image}")
            return
        
        try:
            self.docker_client.images.get(self.config.docker_image)
            logger.info(f"Docker image already available: {self.config.docker_image}")
        except docker.errors.ImageNotFound:
            logger.info(f"Pulling Docker image: {self.config.docker_image}")
            try:
                # Try to pull without authentication first (for public images)
                self.docker_client.images.pull(self.config.docker_image, auth_config={})
                logger.info("Docker image pulled successfully")
            except Exception as pull_error:
                logger.warning(f"Failed to pull image with Docker API: {pull_error}")
                
                # Fallback: try using docker command directly
                logger.info("Attempting to pull image using docker command directly...")
                try:
                    import subprocess
                    result = subprocess.run(
                        ["docker", "pull", self.config.docker_image],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    logger.info("Docker image pulled successfully using docker command")
                    
                    # Verify the image is now available
                    self.docker_client.images.get(self.config.docker_image)
                    
                except subprocess.CalledProcessError as cmd_error:
                    logger.error(f"Docker pull command failed: {cmd_error.stderr}")
                    raise RuntimeError(f"Failed to pull Docker image with both API and command: {cmd_error.stderr}")
                except Exception as cmd_error:
                    logger.error(f"Error running docker pull command: {cmd_error}")
                    raise RuntimeError(f"Failed to pull Docker image: {cmd_error}")
                except docker.errors.ImageNotFound:
                    raise RuntimeError(f"Image {self.config.docker_image} still not found after pull attempt")
    
    def load_predictions(self):
        """Load predictions from JSONL file"""
        logger.info(f"Loading predictions from {self.config.predictions_file}")
        
        valid_count = 0
        total_count = 0
        
        with open(self.config.predictions_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                total_count += 1
                try:
                    pred = json.loads(line)
                    
                    # Validate required fields
                    required_fields = ['instance_id', 'model_name_or_path', 'generated_patch']
                    if all(field in pred and pred[field] for field in required_fields):
                        self.predictions[pred['instance_id']] = pred
                        valid_count += 1
                    else:
                        logger.warning(f"Line {line_num}: Missing required fields")
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Line {line_num}: Invalid JSON - {e}")
        
        logger.info(f"Loaded {valid_count} valid predictions out of {total_count} total lines")
        
        if valid_count == 0:
            raise ValueError("No valid predictions found")
    
    def load_dataset(self):
        """Load dataset from JSONL file"""
        logger.info(f"Loading dataset from {self.config.dataset_file}")
        
        valid_count = 0
        total_count = 0
        
        with open(self.config.dataset_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                total_count += 1
                try:
                    entry = json.loads(line)
                    
                    # Validate required fields - using 'repo' instead of 'repo_url'
                    required_fields = ['instance_id', 'repo', 'base_commit']
                    if all(field in entry and entry[field] for field in required_fields):
                        # Convert repo field (org/repo) to GitHub URL
                        repo_path = entry['repo']
                        if '/' in repo_path and not repo_path.startswith('https://'):
                            entry['repo_url'] = f"https://github.com/{repo_path}.git"
                        elif repo_path.startswith('https://'):
                            entry['repo_url'] = repo_path
                        else:
                            logger.warning(f"Line {line_num}: Invalid repo format '{repo_path}', expected 'org/repo'")
                            continue
                        
                        self.dataset[entry['instance_id']] = entry
                        valid_count += 1
                    else:
                        missing_fields = [field for field in required_fields if field not in entry or not entry[field]]
                        logger.warning(f"Line {line_num}: Missing required fields: {missing_fields}")
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Line {line_num}: Invalid JSON - {e}")
        
        logger.info(f"Loaded {valid_count} valid dataset entries out of {total_count} total lines")
        
        if valid_count == 0:
            raise ValueError("No valid dataset entries found")
    
    def determine_instances_to_evaluate(self):
        """Determine which instances to evaluate"""
        logger.info("Determining instances to evaluate...")
        
        # Find intersection of predictions and dataset
        prediction_ids = set(self.predictions.keys())
        dataset_ids = set(self.dataset.keys())
        available_ids = prediction_ids & dataset_ids
        
        # Filter by specific instance IDs if provided
        if self.config.instance_ids:
            requested_ids = set(self.config.instance_ids)
            self.instances_to_eval = list(available_ids & requested_ids)
            
            missing_ids = requested_ids - available_ids
            if missing_ids:
                logger.warning(f"Requested instance IDs not found: {missing_ids}")
        else:
            self.instances_to_eval = list(available_ids)
        
        # Filter out instances with empty patches
        filtered_instances = []
        for instance_id in self.instances_to_eval:
            patch = self.predictions[instance_id].get('generated_patch', '')
            if patch and patch.strip():
                filtered_instances.append(instance_id)
            else:
                logger.warning(f"Skipping instance {instance_id}: empty patch")
        
        self.instances_to_eval = filtered_instances
        
        logger.info(f"Found {len(self.instances_to_eval)} instances to evaluate")
        
        if not self.instances_to_eval:
            raise ValueError("No instances to evaluate")
    
    def evaluate_instance(self, instance_id: str) -> InstanceResult:
        """Evaluate a single instance"""
        start_time = time.time()
        
        # Get model name early for directory structure
        prediction = self.predictions[instance_id]
        model_name = prediction['model_name_or_path']
        
        # Clean model name for directory (replace invalid characters)
        clean_model_name = model_name.replace("/", "__").replace(":", "_").replace(" ", "_")
        
        # Create model-specific log directory structure
        model_log_dir = self.log_dir / clean_model_name
        instance_log_dir = model_log_dir / instance_id
        
        container_name = f"mobile_bench_{self.config.run_id}_{instance_id}"
        
        logger.info(f"Starting evaluation for instance: {instance_id} (model: {model_name})")
        
        if self.config.dry_run:
            logger.info(f"DRY RUN: Would evaluate instance {instance_id}")
            return InstanceResult(
                instance_id=instance_id,
                model_name_or_path="dry_run",
                status="dry_run",
                container_name=container_name
            )
        
        # Create instance log directory
        instance_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup instance-specific logger
        instance_logger = logging.getLogger(f"instance_{instance_id}")
        instance_handler = logging.FileHandler(instance_log_dir / "evaluation.log")
        instance_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        instance_logger.addHandler(instance_handler)
        instance_logger.setLevel(logging.DEBUG if self.config.debug else logging.INFO)
        
        try:
            # Get dataset data
            dataset_entry = self.dataset[instance_id]
            patch_content = prediction['generated_patch']
            repo_url = dataset_entry['repo_url']
            base_commit = dataset_entry['base_commit']
            test_commands = dataset_entry.get('test_commands', ['./gradlew testDebugUnitTest'])
            build_commands = dataset_entry.get('build_commands', ['./gradlew assembleDebug'])
            
            # Ensure commands are lists
            if isinstance(test_commands, str):
                test_commands = [test_commands]
            if isinstance(build_commands, str):
                build_commands = [build_commands]
            
            # Save patch to file
            patch_file = instance_log_dir / "patch.diff"
            patch_file.write_text(patch_content, encoding='utf-8')
            
            # Start container
            instance_logger.info(f"Starting container: {container_name}")
            
            # Use absolute paths for volume mounting
            abs_instance_log_dir = str(instance_log_dir.absolute())
            abs_patch_file = str(patch_file.absolute())
            
            container = self.docker_client.containers.run(
                self.config.docker_image,
                command="sleep 3600",
                name=container_name,
                working_dir="/workspace",
                volumes={
                    abs_instance_log_dir: {'bind': '/logs', 'mode': 'rw'},
                    abs_patch_file: {'bind': '/patch.diff', 'mode': 'ro'}
                },
                environment={
                    'ANDROID_API_LEVEL': self.config.android_api_level,
                    'BUILD_TOOLS_VERSION': self.config.build_tools_version
                },
                detach=True,
                remove=False  # We'll remove manually for cleanup control
            )
            
            self.running_containers.add(container_name)
            
            result = InstanceResult(
                instance_id=instance_id,
                model_name_or_path=model_name,
                status="error",  # Will be updated on success
                container_name=container_name
            )
            
            def run_command(cmd: str, step_name: str) -> Tuple[bool, str]:
                """Run a command in the container with timeout"""
                instance_logger.debug(f"Running {step_name}: {cmd}")
                
                try:
                    exec_result = container.exec_run(
                        f"bash -c '{cmd}'",
                        workdir="/workspace",
                        stdout=True,
                        stderr=True
                    )
                    
                    output = exec_result.output.decode('utf-8', errors='replace')
                    
                    # Save output to log file
                    log_file = instance_log_dir / f"{step_name}.log"
                    log_file.write_text(output, encoding='utf-8')
                    
                    success = exec_result.exit_code == 0
                    if success:
                        instance_logger.debug(f"{step_name} completed successfully")
                    else:
                        instance_logger.error(f"{step_name} failed with exit code {exec_result.exit_code}")
                    
                    return success, output
                    
                except Exception as e:
                    instance_logger.error(f"{step_name} failed with exception: {e}")
                    return False, str(e)
            
            # Execute evaluation steps
            success = True
            error_msg = ""
            
            # Clone repository
            if success:
                success, output = run_command(f"git clone {repo_url} /workspace/repo", "clone")
                if not success:
                    error_msg = "Failed to clone repository"
            
            # Checkout specific commit
            if success:
                success, output = run_command(f"cd /workspace/repo && git checkout {base_commit}", "checkout")
                if not success:
                    error_msg = "Failed to checkout commit"
            
            # Apply patch
            patch_applied = False
            if success:
                # Try multiple patch application methods
                patch_methods = [
                    "git apply --verbose --reject",
                    "patch -p1",
                    "git apply --verbose",
                ]
                
                for method in patch_methods:
                    cmd = f"cd /workspace/repo && {method} < /patch.diff"
                    patch_success, output = run_command(cmd, f"patch_{method.replace(' ', '_')}")
                    
                    if patch_success:
                        patch_applied = True
                        result.patch_applied = True
                        break
                
                if not patch_applied:
                    success = False
                    error_msg = "Failed to apply patch with any method"
            
            # Build project
            build_success = False
            if success:
                for build_cmd in build_commands:
                    cmd = f"cd /workspace/repo && {build_cmd}"
                    build_success, output = run_command(cmd, "build")
                    
                    if build_success:
                        result.build_success = True
                        break
                
                if not build_success:
                    # Don't mark as overall failure - build failures are part of evaluation
                    logger.warning(f"Build failed for {instance_id}")
            
            # Run tests
            test_results = "ERROR"
            if success and build_success:
                all_tests_passed = True
                
                for test_cmd in test_commands:
                    cmd = f"cd /workspace/repo && {test_cmd}"
                    test_success, output = run_command(cmd, "test")
                    
                    if not test_success:
                        all_tests_passed = False
                
                test_results = "PASSED" if all_tests_passed else "FAILED"
                result.test_results = test_results
                result.resolved = all_tests_passed
            
            # Update final result
            if success:
                result.status = "completed"
            else:
                result.status = "error"
                result.error_message = error_msg
            
            execution_time = time.time() - start_time
            result.execution_time = execution_time
            
            # Save result to JSON
            result_file = instance_log_dir / "report.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(result), f, indent=2)
            
            if result.status == "completed":
                logger.info(f"Instance {instance_id} completed: Tests {test_results} ({execution_time:.1f}s)")
            else:
                logger.error(f"Instance {instance_id} failed: {error_msg} ({execution_time:.1f}s)")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Evaluation failed with exception: {str(e)}"
            logger.error(f"Instance {instance_id}: {error_msg}")
            
            result = InstanceResult(
                instance_id=instance_id,
                model_name_or_path=self.predictions.get(instance_id, {}).get('model_name_or_path', 'unknown'),
                status="error",
                error_message=error_msg,
                container_name=container_name,
                execution_time=execution_time
            )
            
            # Save error result
            result_file = instance_log_dir / "report.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(result), f, indent=2)
            
            return result
            
        finally:
            # Cleanup container
            if not self.config.dry_run:
                try:
                    container = self.docker_client.containers.get(container_name)
                    
                    if self.config.clean_containers:
                        logger.debug(f"Cleaning up container: {container_name}")
                        container.stop(timeout=10)
                        container.remove()
                    else:
                        logger.debug(f"Stopping container for debugging: {container_name}")
                        container.stop(timeout=10)
                    
                    self.running_containers.discard(container_name)
                    
                except docker.errors.NotFound:
                    pass  # Container already removed
                except Exception as e:
                    logger.warning(f"Failed to cleanup container {container_name}: {e}")
            
            # Remove instance logger handler
            if 'instance_logger' in locals():
                for handler in instance_logger.handlers[:]:
                    instance_logger.removeHandler(handler)
                    handler.close()
    
    def run_evaluation(self):
        """Run evaluation on all instances using thread pool"""
        logger.info(f"Starting evaluation of {len(self.instances_to_eval)} instances with {self.config.max_workers} workers")
        
        if self.config.dry_run:
            logger.info(f"DRY RUN: Would evaluate instances: {self.instances_to_eval}")
            return
        
        # Use ThreadPoolExecutor for parallel evaluation
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit all evaluation tasks
            future_to_instance = {
                executor.submit(self.evaluate_instance, instance_id): instance_id
                for instance_id in self.instances_to_eval
            }
            
            # Process completed evaluations
            completed = 0
            total = len(self.instances_to_eval)
            
            for future in as_completed(future_to_instance):
                instance_id = future_to_instance[future]
                completed += 1
                
                try:
                    result = future.result()
                    self.results[instance_id] = result
                    
                    logger.info(f"Progress: {completed}/{total} completed - {instance_id}")
                    
                except Exception as e:
                    logger.error(f"Instance {instance_id} failed with exception: {e}")
                    # Create error result
                    self.results[instance_id] = InstanceResult(
                        instance_id=instance_id,
                        model_name_or_path="unknown",
                        status="error",
                        error_message=str(e)
                    )
        
        logger.info(f"Evaluation completed: {len(self.results)}/{total} instances processed")
    
    def generate_reports(self):
        """Generate final evaluation reports"""
        logger.info("Generating final reports...")
        
        if self.config.dry_run:
            report_file = self.report_dir / f"mobile_bench_{self.config.run_id}_report.json"
            summary_file = self.report_dir / f"mobile_bench_{self.config.run_id}_summary.txt"
            logger.info(f"DRY RUN: Would generate reports:")
            logger.info(f"  JSON: {report_file}")
            logger.info(f"  Summary: {summary_file}")
            return
        
        # Ensure report directory exists
        self.report_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate overall statistics
        total = len(self.results)
        resolved = sum(1 for r in self.results.values() if r.resolved)
        patch_applied = sum(1 for r in self.results.values() if r.patch_applied)
        build_success = sum(1 for r in self.results.values() if r.build_success)
        errors = sum(1 for r in self.results.values() if r.status == "error")
        
        # Calculate per-model statistics
        model_stats = {}
        for result in self.results.values():
            model = result.model_name_or_path
            if model not in model_stats:
                model_stats[model] = {
                    "total": 0,
                    "resolved": 0,
                    "patch_applied": 0,
                    "build_success": 0,
                    "errors": 0,
                    "avg_execution_time": 0.0
                }
            
            stats = model_stats[model]
            stats["total"] += 1
            if result.resolved:
                stats["resolved"] += 1
            if result.patch_applied:
                stats["patch_applied"] += 1
            if result.build_success:
                stats["build_success"] += 1
            if result.status == "error":
                stats["errors"] += 1
        
        # Calculate averages for each model
        for model, stats in model_stats.items():
            model_results = [r for r in self.results.values() if r.model_name_or_path == model]
            if model_results:
                stats["avg_execution_time"] = sum(r.execution_time for r in model_results) / len(model_results)
                if stats["total"] > 0:
                    stats["resolve_rate"] = round(stats["resolved"] * 100 / stats["total"], 2)
                    stats["patch_apply_rate"] = round(stats["patch_applied"] * 100 / stats["total"], 2)
                    stats["build_success_rate"] = round(stats["build_success"] * 100 / stats["total"], 2)
        
        # Generate JSON report
        report_data = {
            "run_id": self.config.run_id,
            "timestamp": datetime.now().isoformat() + "Z",
            "configuration": {
                "max_workers": self.config.max_workers,
                "timeout": self.config.timeout,
                "docker_image": self.config.docker_image,
                "android_api_level": self.config.android_api_level,
                "build_tools_version": self.config.build_tools_version
            },
            "statistics": {
                "overall": {
                    "total_instances": total,
                    "resolved": resolved,
                    "patch_applied": patch_applied,
                    "build_success": build_success,
                    "errors": errors,
                    "resolve_rate": round(resolved * 100 / total, 2) if total > 0 else 0,
                    "patch_apply_rate": round(patch_applied * 100 / total, 2) if total > 0 else 0,
                    "build_success_rate": round(build_success * 100 / total, 2) if total > 0 else 0
                },
                "per_model": model_stats
            },
            "results": [asdict(result) for result in self.results.values()]
        }
        
        report_file = self.report_dir / f"mobile_bench_{self.config.run_id}_report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        # Generate text summary
        summary_file = self.report_dir / f"mobile_bench_{self.config.run_id}_summary.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(f"""Mobile Bench Evaluation Report
===============================

Run ID: {self.config.run_id}
Timestamp: {report_data['timestamp']}
Docker Image: {self.config.docker_image}

Configuration:
- Max Workers: {self.config.max_workers}
- Timeout: {self.config.timeout}s
- Android API Level: {self.config.android_api_level}
- Build Tools Version: {self.config.build_tools_version}

Overall Results Summary:
- Total Instances: {total}
- Resolved (Tests Passed): {resolved} ({resolved * 100 / total:.1f}%)
- Patch Applied: {patch_applied} ({patch_applied * 100 / total:.1f}%)
- Build Success: {build_success} ({build_success * 100 / total:.1f}%)
- Errors: {errors} ({errors * 100 / total:.1f}%)

Per-Model Results:
""")
            
            for model_name, stats in model_stats.items():
                f.write(f"\n{model_name}:\n")
                f.write(f"  - Total: {stats['total']}\n")
                f.write(f"  - Resolved: {stats['resolved']} ({stats.get('resolve_rate', 0):.1f}%)\n")
                f.write(f"  - Patch Applied: {stats['patch_applied']} ({stats.get('patch_apply_rate', 0):.1f}%)\n")
                f.write(f"  - Build Success: {stats['build_success']} ({stats.get('build_success_rate', 0):.1f}%)\n")
                f.write(f"  - Errors: {stats['errors']}\n")
                f.write(f"  - Avg Execution Time: {stats['avg_execution_time']:.1f}s\n")
            
            f.write(f"\nDetailed Results by Model:\n")
            
            # Group results by model for detailed listing
            results_by_model = {}
            for result in self.results.values():
                model = result.model_name_or_path
                if model not in results_by_model:
                    results_by_model[model] = []
                results_by_model[model].append(result)
            
            for model_name in sorted(results_by_model.keys()):
                f.write(f"\n{model_name}:\n")
                for result in sorted(results_by_model[model_name], key=lambda x: x.instance_id):
                    f.write(f"  - {result.instance_id}: {result.status} "
                           f"(resolved: {result.resolved}, tests: {result.test_results}, "
                           f"time: {result.execution_time:.1f}s)\n")
            
            f.write(f"\nLog Directory Structure:\n")
            f.write(f"{self.log_dir}/\n")
            for model_name in sorted(results_by_model.keys()):
                clean_model_name = model_name.replace("/", "__").replace(":", "_").replace(" ", "_")
                f.write(f"├── {clean_model_name}/\n")
                model_instances = sorted([r.instance_id for r in results_by_model[model_name]])
                for i, instance_id in enumerate(model_instances):
                    prefix = "└──" if i == len(model_instances) - 1 else "├──"
                    f.write(f"│   {prefix} {instance_id}/\n")
            
            f.write(f"\nReport Files: {report_file}\n")
        
        logger.info(f"Reports generated:")
        logger.info(f"  JSON: {report_file}")
        logger.info(f"  Summary: {summary_file}")
        
        # Print summary to console
        logger.info("=== EVALUATION SUMMARY ===")
        logger.info(f"Run ID: {self.config.run_id}")
        logger.info(f"Total instances: {total}")
        logger.info(f"Resolved: {resolved} ({resolved * 100 / total:.1f}%)")
        logger.info(f"Patch applied: {patch_applied} ({patch_applied * 100 / total:.1f}%)")
        logger.info(f"Build success: {build_success} ({build_success * 100 / total:.1f}%)")
        logger.info(f"Errors: {errors} ({errors * 100 / total:.1f}%)")
        
        logger.info("\nPer-model summary:")
        for model_name, stats in model_stats.items():
            logger.info(f"  {model_name}: {stats['resolved']}/{stats['total']} resolved "
                       f"({stats.get('resolve_rate', 0):.1f}%)")
        logger.info("=" * 27)
    
    def cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up resources...")
        
        if self.config.clean_containers and not self.config.dry_run:
            # Stop and remove any remaining containers
            for container_name in list(self.running_containers):
                try:
                    container = self.docker_client.containers.get(container_name)
                    logger.debug(f"Stopping container: {container_name}")
                    container.stop(timeout=10)
                    container.remove()
                    self.running_containers.remove(container_name)
                except docker.errors.NotFound:
                    self.running_containers.discard(container_name)
                except Exception as e:
                    logger.warning(f"Failed to cleanup container {container_name}: {e}")
            
            # Also clean up any containers with our run_id pattern that might be orphaned
            try:
                containers = self.docker_client.containers.list(all=True, 
                    filters={"name": f"mobile_bench_{self.config.run_id}_"})
                for container in containers:
                    try:
                        logger.debug(f"Cleaning up orphaned container: {container.name}")
                        container.stop(timeout=5)
                        container.remove()
                    except Exception as e:
                        logger.warning(f"Failed to cleanup orphaned container {container.name}: {e}")
            except Exception as e:
                logger.warning(f"Failed to list containers for cleanup: {e}")
    
    def run(self):
        """Main execution method"""
        try:
            start_time = time.time()
            
            # Setup and validation
            self.setup_directories()
            self.validate_dependencies()
            self.pull_docker_image()
            
            # Data loading
            self.load_predictions()
            self.load_dataset()
            self.determine_instances_to_evaluate()
            
            # Evaluation
            self.run_evaluation()
            
            # Reporting
            self.generate_reports()
            
            end_time = time.time()
            duration = end_time - start_time
            
            logger.info(f"Evaluation completed successfully in {duration:.1f}s")
            
        except KeyboardInterrupt:
            logger.warning("Evaluation interrupted by user")
            return 1
        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            if self.config.debug:
                traceback.print_exc()
            return 1
        finally:
            self.cleanup()
        
        return 0

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Mobile Bench Android Evaluation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic evaluation (run ID auto-generated)
  python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl

  # Basic evaluation with custom run ID
  python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl --run-id test_001

  # Evaluate specific instances with debug output
  python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl --run-id debug_001 \\
         --instance-ids AntennaPod-123 AntennaPod-456 --debug

  # Production run with custom settings
  python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl --run-id prod_001 \\
         --max-workers 8 --timeout 3600 --android-api-level 34

  # Dry run to see what would happen (run ID auto-generated)
  python mobile_bench_harness.py --predictions results.jsonl --dataset data.jsonl --dry-run
        """
    )
    
    # Required arguments
    parser.add_argument("--predictions", required=True, help="Path to predictions JSONL file")
    parser.add_argument("--dataset", required=True, help="Path to dataset JSONL file")
    parser.add_argument("--run-id", help="Unique identifier for this evaluation run (auto-generated if not provided)")
    
    # Optional arguments
    parser.add_argument("--max-workers", type=int, default=4, help="Maximum parallel workers")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout per instance in seconds")
    parser.add_argument("--log-dir", default="logs/harness", help="Directory for logs")
    parser.add_argument("--report-dir", default="reports", help="Directory for reports")
    parser.add_argument("--cache-dir", default="cache", help="Directory for caching")
    parser.add_argument("--docker-image", default="mingc/android-build-box:latest", help="Docker image to use")
    parser.add_argument("--android-api-level", default="33", help="Android API level")
    parser.add_argument("--build-tools-version", default="33.0.2", help="Build tools version")
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to evaluate")
    parser.add_argument("--force-rebuild", action="store_true", help="Force rebuild of all containers")
    parser.add_argument("--no-clean", action="store_true", help="Don't clean up containers after evaluation")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Auto-generate run ID if not provided
    if not args.run_id:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.run_id = f"eval_{timestamp}"
        logger.info(f"Auto-generated run ID: {args.run_id}")
    
    # Create configuration
    config = EvaluationConfig(
        predictions_file=args.predictions,
        dataset_file=args.dataset,
        run_id=args.run_id,
        max_workers=args.max_workers,
        timeout=args.timeout,
        log_dir=args.log_dir,
        report_dir=args.report_dir,
        cache_dir=args.cache_dir,
        docker_image=args.docker_image,
        android_api_level=args.android_api_level,
        build_tools_version=args.build_tools_version,
        instance_ids=args.instance_ids,
        force_rebuild=args.force_rebuild,
        clean_containers=not args.no_clean,
        debug=args.debug,
        dry_run=args.dry_run
    )
    
    # Validate configuration
    if not config.run_id.replace('_', '').replace('-', '').isalnum():
        logger.error("Run ID must contain only letters, numbers, underscores, and dashes")
        return 1
    
    if config.max_workers < 1:
        logger.error("Max workers must be at least 1")
        return 1
    
    if config.timeout < 60:
        logger.error("Timeout must be at least 60 seconds")
        return 1
    
    # Show configuration
    logger.info("=== MOBILE BENCH HARNESS CONFIGURATION ===")
    logger.info(f"Run ID: {config.run_id}")
    logger.info(f"Predictions file: {config.predictions_file}")
    logger.info(f"Dataset file: {config.dataset_file}")
    logger.info(f"Docker image: {config.docker_image}")
    logger.info(f"Max workers: {config.max_workers}")
    logger.info(f"Timeout: {config.timeout}s")
    logger.info(f"Android API level: {config.android_api_level}")
    logger.info(f"Build tools version: {config.build_tools_version}")
    logger.info(f"Log directory: {config.log_dir}")
    logger.info(f"Report directory: {config.report_dir}")
    logger.info(f"Force rebuild: {config.force_rebuild}")
    logger.info(f"Clean containers: {config.clean_containers}")
    logger.info(f"Debug mode: {config.debug}")
    logger.info(f"Dry run: {config.dry_run}")
    
    if config.instance_ids:
        logger.info(f"Specific instances: {config.instance_ids}")
    else:
        logger.info("Evaluate all available instances")
    logger.info("=" * 45)
    
    if config.dry_run:
        logger.info("=== DRY RUN MODE - NO ACTUAL EXECUTION ===")
    
    # Create and run harness
    harness = MobileBenchHarness(config)
    return harness.run()

if __name__ == "__main__":
    sys.exit(main())