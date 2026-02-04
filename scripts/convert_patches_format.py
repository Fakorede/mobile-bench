#!/usr/bin/env python3
"""Convert patch file from model format to mobiledev-bench format.

Input format:
{"model_name_or_path": "...", "instance_id": "org__repo-number", "model_patch": "diff..."}

Output format:
{"org": "org", "repo": "repo", "number": number, "fix_patch": "diff..."}

python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_dart-gemini-2.5-flash/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/gemini_openrouter_converted_patches.jsonl

python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_java-gemini-2.5-flash/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/antennapod/gemini_openrouter_converted_patches.jsonl

python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_kotlin-gemini-2.5-flash/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gemini_openrouter_converted_patches.jsonl

python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_typescript-gemini-2.5-flash/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gemini_openrouter_converted_patches.jsonl



python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_kotlin-gpt-5.2/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/jerboa/gpt_converted_patches.jsonl

python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_typescript-gpt-5.2/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/rocketchat/gpt_converted_patches.jsonl

python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_java-gpt-5.2/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/antennapod/gpt_converted_patches.jsonl


python3 /home/researchuser/dev/inri/mobiledev-bench/scripts/convert_patches_format.py \
    /home/researchuser/dev/inri/mobiledev-bench/magentless/results/mobiledev_bench_dart-gpt-5.2/all_preds.jsonl \
    /home/researchuser/dev/inri/mobiledev-bench/data/evaluation/zulip/gpt_converted_patches.jsonl

"""

import json
import sys
from pathlib import Path


def parse_instance_id(instance_id: str) -> tuple[str, str, int]:
    """Parse instance_id like 'zulip__zulip-flutter-1952' into (org, repo, number)."""
    # Split on '__' to separate org from repo-number
    parts = instance_id.split("__")
    if len(parts) != 2:
        raise ValueError(f"Invalid instance_id format: {instance_id}")

    org = parts[0]
    repo_with_number = parts[1]

    # Split repo-number on the last '-' to get repo and number
    last_dash = repo_with_number.rfind("-")
    if last_dash == -1:
        raise ValueError(f"Invalid instance_id format (no number): {instance_id}")

    repo = repo_with_number[:last_dash]
    number = int(repo_with_number[last_dash + 1:])

    return org, repo, number


def convert_patch_file(input_file: Path, output_file: Path):
    """Convert patch file from model format to mobiledev-bench format."""
    converted_count = 0

    with open(input_file, "r") as f_in, open(output_file, "w") as f_out:
        for line_num, line in enumerate(f_in, 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)

                # Parse instance_id
                instance_id = data.get("instance_id")
                if not instance_id:
                    print(f"Warning: Line {line_num} missing instance_id, skipping", file=sys.stderr)
                    continue

                org, repo, number = parse_instance_id(instance_id)

                # Get model_patch (could be model_patch or fix_patch)
                fix_patch = data.get("model_patch") or data.get("fix_patch")
                if not fix_patch:
                    print(f"Warning: Line {line_num} missing patch, skipping", file=sys.stderr)
                    continue

                # Create output format
                output_data = {
                    "org": org,
                    "repo": repo,
                    "number": number,
                    "fix_patch": fix_patch
                }

                f_out.write(json.dumps(output_data, ensure_ascii=False) + "\n")
                converted_count += 1

            except Exception as e:
                print(f"Error processing line {line_num}: {e}", file=sys.stderr)
                continue

    print(f"Converted {converted_count} patches from {input_file} to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_patches_format.py <input_file> <output_file>")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])

    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    convert_patch_file(input_file, output_file)
