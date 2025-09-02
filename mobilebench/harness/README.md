
```
android_evaluation_results/
├── {run_id}/
│   ├── logs/
│   │   └── android_bench.log                    # Main application log
│   ├── {model_name}/                            # Model-specific directory
│   │   └── {instance_id}/                       # Instance-specific directory
│   │       ├── instance.log                     # Instance-specific execution log
│   │       ├── test_output.txt                  # Raw test execution output
│   │       ├── container.log                    # Docker container logs
│   │       ├── test.patch                       # Original test patch file
│   │       ├── prediction.patch                 # Model's generated patch
│   │       ├── test_results.json                # Structured test results with pass/fail lists
│   │       ├── test_summary.txt                 # Human-readable test summary
│   │       └── evaluation_result.json           # Structured result data
│   ├── evaluation_summary.json                  # Run-wide summary
│   └──# Android-Bench Evaluation Harness
```

A comprehensive evaluation framework for Android development tasks, inspired by SWE-bench but tailored for Android projects using the `mingc/android-build-box` Docker environment.

## Overview

This harness evaluates language models on real-world Android development tasks by:

1. **Loading** datasets and model predictions
2. **Parsing** Android project configurations (Gradle, SDK versions, etc.)
3. **Creating** customized Docker containers with proper build environments
4. **Applying** test patches and model-generated patches
5. **Executing** Android tests in isolated environments
6. **Reporting** comprehensive results and statistics

### Basic Usage

```bash
# Run evaluation on a dataset
python run_android_bench.py dataset.jsonl predictions.jsonl --run-id my_evaluation

# Evaluate specific instances
python run_android_bench.py dataset.jsonl predictions.jsonl \
  --run-id my_evaluation \
  --instance-ids "AntennaPod__AntennaPod-5644" "MyApp__MyApp-1234"

python run_android_bench.py \
    "/home/researchuser/dev/mobile-bench/data/tasks/Antennapod-task-instances.jsonl" \
    "/home/researchuser/dev/mobile-bench/data/inference/Antennapod_prompts_style-3_oracle_gemini_20250722_091215.jsonl" \
    --run-id test_evaluation_3 \
    --instance-ids "AntennaPod__AntennaPod-7215" \
    --log-level DEBUG

# Run with parallel workers
python run_android_bench.py dataset.jsonl predictions.jsonl \
  --run-id my_evaluation \
  --max-workers 4

# Generate reports
python reporter.py results/ --run-id my_evaluation
```


### Debug Mode

```bash
python run_android_bench.py dataset.jsonl predictions.jsonl \
  --run-id debug_run \
  --log-level DEBUG \
  --max-instances 1

python run_android_bench.py \
    "/home/researchuser/dev/mobile-bench/data/tasks/Antennapod-task-instances.jsonl" \
    "/home/researchuser/dev/mobile-bench/data/inference/Antennapod_prompts_style-3_oracle_gemini_20250722_091215.jsonl" \
    --run-id test_evaluation_1 \
    --log-level DEBUG
```

## Architecture

### Core Components

1. **`loader.py`** - Dataset and prediction loading with filtering capabilities
2. **`parser.py`** - Android build configuration detection and parsing
3. **`containers.py`** - Docker container management with Android build environments
4. **`executor.py`** - Test execution engine with patch application strategies
5. **`repository.py`** - Git repository management and cloning
6. **`logger.py`** - Structured logging and result tracking
7. **`evaluator.py`** - Main evaluation orchestration engine
8. **`reporter.py`** - Results analysis and report generation

### Data Flow

```
Dataset + Predictions → Loader → Filter Instances
    ↓
Repository Manager → Clone Repos → Parse Config
    ↓
Container Manager → Create Android Environment
    ↓
Executor → Apply Patches → Run Tests → Collect Results
    ↓
Logger → Save Logs → Generate Reports
```