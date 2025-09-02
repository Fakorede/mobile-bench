

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

$ python validator.py /home/researchuser/dev/mobile-bench/data/tasks/thunderbird-android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird--batch3 \
--exclude-instance-ids 9010 9011 9026 9028 9030 9104 9115 9128 9130 9137 9150 9158 9161 9163 9179 9182 9186 9207 9208 9209 9213 9241 9254 9268 9272 9279 9299 9322 9329 9332 9341 9346 9351 9360 9362 9367 9374 9381 9386 9388 9398 9399 9405 9414 9423 9428 9448 9469 9481 9508 6105 6158 6172 6190 6256 6263 6280 6301 6335 6360 6424 6435 6447 6453 6482 6486 6507 6522 6546 6555 6561 6588 6600 6618 6624 6630 6693 6762 6811 6840 6846 6873 6946 6962 6987 7008 7113 7179 7180 7292 7299 7340 7365 7377 7398 7403 7489 7569 7699 7722 7891 7931 7978 8014 8020 8099 8107 8130 8134 8136 8147 8151 8155 8166 8176 8243 8259 8267 8272 8305 8306 8329 8339 8382 8541 8547 8602 8735 8804 8813 8846 8889 8890 8891 8903 8904 8906 8958 8999 9004 9414 9423 9428 9448 9469 9481 9508


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod --max-instances 1

export OPENROUTER_API_KEY=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
```




https://spin.atomicobject.com/android-test-script/
https://andresand.medium.com/android-emulator-on-docker-container-f20c49b129ef



