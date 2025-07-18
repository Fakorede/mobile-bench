#!/bin/bash

# Example usage of Mobile-Bench
# Make sure to activate the virtual environment first

source venv/bin/activate

# Example 1: Run evaluation on sample data
python3 mobile_bench_evaluator.py \
    --dataset_path ./sample_data/instances.jsonl \
    --predictions_path ./sample_data/predictions.jsonl \
    --run_id "example_run_$(date +%Y%m%d_%H%M%S)" \
    --max_workers 2 \
    --timeout 1200 \
    --log_level INFO

# Example 2: Validate only (no actual execution)
python3 mobile_bench_evaluator.py \
    --dataset_path ./sample_data/instances.jsonl \
    --predictions_path ./sample_data/predictions.jsonl \
    --run_id "validation_run" \
    --validate_only

# Example 3: Run specific instances
python3 mobile_bench_evaluator.py \
    --dataset_path ./sample_data/instances.jsonl \
    --predictions_path ./sample_data/predictions.jsonl \
    --run_id "specific_instances" \
    --instance_ids instance_1 instance_2 instance_3 \
    --max_workers 1
