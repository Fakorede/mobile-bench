## Build dataset


- Metamask

python3 -m mobiledev_bench.harness.build_dataset \
  --raw_dataset_files /home/researchuser/dev/mobile-bench/data/instances/all/MetaMask__metamask-mobile_instances_with_test_commands_filtered.jsonl \
  --workdir /home/researchuser/dev/mobile-bench/data/docker_images/metamask/ \
  --repo_dir /home/researchuser/dev/mobile-bench/data/repos/ \
  --output_dir /home/researchuser/dev/mobile-bench/data/results/reactnative/metamask/builds \
  --log_dir /home/researchuser/dev/mobile-bench/data/results/reactnative/metamask/logs \
  --max_workers 1 \
  --max_workers_build_image 1 \
  --max_workers_run_instance 1 \
  --need_clone true


- StreetComplete

python3 -m mobiledev_bench.harness.build_dataset \
  --raw_dataset_files /home/researchuser/dev/mobile-bench/data/instances/all/streetcomplete__StreetComplete_instances_with_test_commands.jsonl \
  --workdir /home/researchuser/dev/mobile-bench/data/docker_images/streetcomplete/ \
  --repo_dir /home/researchuser/dev/mobile-bench/data/repos/ \
  --output_dir /home/researchuser/dev/mobile-bench/data/results/kotlin/streetcomplete/builds/ \
  --log_dir /home/researchuser/dev/mobile-bench/data/results/kotlin/streetcomplete/logs/ \
  --max_workers 2 \
  --need_clone true


## Run evaluation
