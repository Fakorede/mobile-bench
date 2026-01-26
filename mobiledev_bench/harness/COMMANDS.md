# Steps

sonnet 4.5 ✅
wordpress
thunderbird
elementxandroid


qwen3-coder
===========
get magentless patch ✅
then run convert_patches_format script ✅
then compare_patch_files ✅
Run build & evaluation
 - metamask
 - streetcomplete

gpt 5
=======
get magentless patches from krishna PC (generating again)
then run convert_patches_format script
then compare_patch_files
then build & evaluation

```sh
find results -type f -path "results/mobiledev_bench_*/all_preds.jsonl" -print0 \
  | rsync -av --relative --from0 --files-from=- . \
    researchuser@cse2327pc07u.lsu.edu:/home/researchuser/dev/inri/mobiledev-bench/magentless/
```

Build Dataset (docker images & test transiions)
Run Evaluation (applies patches & run test)
Campare patch (run convert patch scrript, upload to servers, then gold and model-generated)
Generate other metrics

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



## Re-generate report (optional)

python3 -m mobiledev_bench.harness.gen_report \
  --mode dataset \
  --workdir /home/researchuser/dev/mobile-bench/data/docker_images/metamask/ \
  --log_dir /home/researchuser/dev/mobile-bench/data/results/reactnative/metamask/logs \
  --output_dir /home/researchuser/dev/mobile-bench/data/results/reactnative/metamask/builds \
  --raw_dataset_files /home/researchuser/dev/mobile-bench/data/instances/all/MetaMask__metamask-mobile_instances_with_test_commands_filtered.jsonl \
  --regen true \
  --specifics metamask


## Run evaluation (test model predictions)

METAMASK
=========

python3 -m mobiledev_bench.harness.run_evaluation \
  --patch_file /home/researchuser/dev/mobile-bench/data/evaluation/metamask/qwen_converted_patches.jsonl \
  --dataset_files /home/researchuser/dev/mobile-bench/data/results/reactnative/metamask/builds/MetaMask__metamask-mobile_dataset.jsonl \
  --workdir /home/researchuser/dev/mobile-bench/data/docker_images/metamask/ \
  --repo_dir /home/researchuser/dev/mobile-bench/data/repos/ \
  --output_dir /home/researchuser/dev/mobile-bench/data/evaluation/metamask/ \
  --log_dir /home/researchuser/dev/mobile-bench/data/evaluation/metamask/logs/ \
  --mode evaluation \
  --max_workers 1 \
  --max_workers_build_image 1 \
  --max_workers_run_instance 1 \
  --need_clone true

StreetComplete
==============

python3 -m mobiledev_bench.harness.run_evaluation \
  --patch_file /home/moshood/dev/mobile-bench/data/evaluation/streetcomplete/qwen_converted_patches.jsonl \
  --dataset_files /home/moshood/dev/mobile-bench/data/results/kotlin/streetcomplete/builds/streetcomplete__StreetComplete_dataset.jsonl \
  --workdir /home/moshood/dev/mobile-bench/data/docker_images/streetcomplete/ \
  --repo_dir /home/moshood/dev/mobile-bench/data/repos/ \
  --output_dir /home/moshood/dev/mobile-bench/data/results/kotlin/streetcomplete/builds/ \
  --log_dir /home/moshood/dev/mobile-bench/data/results/kotlin/streetcomplete/logs/ \
  --mode evaluation \
  --max_workers 2 \
  --max_workers_build_image 2 \
  --max_workers_run_instance 2 \
  --need_clone true

