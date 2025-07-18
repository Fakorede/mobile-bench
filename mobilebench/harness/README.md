



### Usage


```bash
# Basic evaluation
python3 mobile_bench_evaluator.py \
    --dataset_path instances.jsonl \
    --predictions_path predictions.jsonl \
    --run_id evaluation_run_2024

# Advanced configuration
python3 mobile_bench_evaluator.py \
    --dataset_path data/instances.jsonl \
    --predictions_path data/predictions.jsonl \
    --run_id detailed_run \
    --max_workers 6 \
    --timeout 2400 \
    --log_level DEBUG \
    --instance_ids specific_instance_1 specific_instance_2

# Validation only
python3 mobile_bench_evaluator.py \
    --dataset_path instances.jsonl \
    --predictions_path predictions.jsonl \
    --run_id validation \
    --validate_only


```