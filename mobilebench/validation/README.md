

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

THUNDERBIRD

$ python validator.py /home/researchuser/dev/mobile-bench/data/tasks/thunderbird-android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-batch2 --exclude-instance-ids 9508 9481 9469 9448 9428 9423 9414 9405 9399 9398 9388 9386 9381 9374 9367 9362 9360 9351 9346 9341 9332 9329 9322 9299 9279 9272 9268 9254 9241 9213



python validator.py ../../data/tasks/thunderbird-android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-SSG-1 --instance-ids 

python validator.py ../../data/tasks/thunderbird-android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-SSG-1 \
  --instance-ids 9508 9481 9469 9448 9428 9423 9414 9405 9399 9398 9388 9386 9381 9374 9367 9362 9360 9351 9346 9341 9332 9329 9322 9299 9279 9272 9268 9254 9241 9213 9209 9208 9207 9186 9182 9179 9163 9161 9158 9150 9137 9130 9128 9115 9104 9030 9028 9026 9011 9010 9004 8999 8958 8906 8904 8903 8891 8890 8889 8846 8813 8804 8735 8602 8547 8541 8382 8339 8329 8306 8305 8272 8267 8259 8243 8176 8166 8155 8151 8147 8136

python validator.py ../../data/tasks/thunderbird-android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-SSG-2 \
  --instance-ids 8134 8130 8107 8099 8020 8014 7978 7931 7891 7722 7699 7569 7489 7403 7398 7377 7365 7340 7299 7292 7180 7179 7113 7008 6987 6962 6946 6873 6846 6840 6811 6762 6693 6630 6624 6618 6600 6588 6561 6555 6546 6522 6507 6486 6482 6453 6447 6435 6424 6360 6335 6301 6280 6263 6256 6190 6172 6158 6105 6082 6080 6056 6051 6049 6044 6043 6041 6030 6022 6019 5989 5958 5946 5926 5909 5896 5881 5872 5859 5848



ANTENNAPOD

python mobilebench/validation/validator.py data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod-SSG --exclude-instance-ids 7730 6652 6333 6029 5835 7713 7192 7176 7096 7011 6434 6403 6400 6384 6328 6286 6276 6236 6095 6041 6001 5726 7159

--instance-ids 5644 5679 5751 5872 5886 6057 6147 6153 6210 6266 6358 6420 6529 6530 6573 6659 6739 6808

python validator.py ../../data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod-SSG-batch --instance-ids 7060 7815 7581 7537 6739 7215 6529 6530 7098 6147 6057 5872 5644 6808 6659 6573 6358 6266 6210 6153 5886 5751

python validator.py ../../data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod-SSG-7815 --instance-ids 7815





python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod --max-instances 1

export OPENROUTER_API_KEY=xxxxxxxxx
```




https://spin.atomicobject.com/android-test-script/
https://andresand.medium.com/android-emulator-on-docker-container-f20c49b129ef



