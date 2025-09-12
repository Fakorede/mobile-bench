

```
output_directory/
├── final_validation_summary.json      # Complete results
├── validation_report.txt              # Human-readable report  
├── incremental_statistics.json        # Running statistics
├── validation_progress.json           # Resume tracking
├── validation_checkpoint.json         # Detailed checkpoints
└── [instance_id]/                     # Per-instance results
    ├── test_analysis.json
    ├── test_results_pre.json
    └── test_results_post.json
```

## Basic Usage

```shell
# Run with your JSONL file
# Basic validation with auto-resume
python validator.py dataset.jsonl

# Resume after interruption (automatic)
python validator.py dataset.jsonl --output-dir previous_results

# Force restart from beginning
python validator.py dataset.jsonl --force-restart

# Validate specific instances with resume capability
python validator.py dataset.jsonl --instance-ids "6044" "6045"

$ python validator.py /home/researchuser/dev/mobile-bench/data/tasks/thunderbird-android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-batch2 --exclude-instance-ids 9508 9481 9469 9448 9428 9423 9414 9405 9399 9398 9388 9386 9381 9374 9367 9362 9360 9351 9346 9341 9332 9329 9322 9299 9279 9272 9268 9254 9241 9213


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/thunderbird-android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-9423 --instance-ids 9423


python mobilebench/validation/validator.py data/tasks/thunderbird-android-task-instances.jsonl --instance-ids thunderbird__thunderbird-android-9423


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod --max-instances 1

export OPENROUTER_API_KEY=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
```




https://spin.atomicobject.com/android-test-script/
https://andresand.medium.com/android-emulator-on-docker-container-f20c49b129ef



