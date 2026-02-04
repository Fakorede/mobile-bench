#!/usr/bin/env python3
"""Construct dataset files for each repo from model generated patches across multiple runs.

This script collects patches from multiple prediction result folders and creates
JSONL files for each repository in the mobiledev-bench format.

Usage:
    python3 construct_dataset_from_patches.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional


def parse_instance_id(instance_id: str) -> tuple[str, str, int]:
    """Parse instance_id like 'zulip__zulip-flutter-1952' into (org, repo, number)."""
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


def read_patch_file(patch_path: Path) -> Optional[str]:
    """Read a patch file and return its contents, or None if it doesn't exist."""
    if not patch_path.exists():
        return None

    try:
        with open(patch_path, "r") as f:
            content = f.read().strip()
            return content if content else None
    except Exception as e:
        print(f"Warning: Could not read {patch_path}: {e}", file=sys.stderr)
        return None


def collect_patches(base_dir: Path, run_folders: list[str]) -> dict[str, dict]:
    """Collect all patches from multiple run folders.

    Returns a dict mapping instance_id to patch data. If a patch is missing in earlier runs
    but present in later runs, the later run's patch will be used.
    """
    patches = {}

    for run_folder in run_folders:
        run_path = base_dir / run_folder / "gemini-2_5-flash"

        if not run_path.exists():
            print(f"Warning: Run folder not found: {run_path}", file=sys.stderr)
            continue

        # Find all instance directories
        for instance_dir in sorted(run_path.iterdir()):
            if not instance_dir.is_dir():
                continue

            instance_id = instance_dir.name
            patch_file = instance_dir / "model.patch"

            # Check if patch exists for this instance in this run
            patch_content = read_patch_file(patch_file)

            if patch_content:
                # Only add/update if we don't have a patch yet, or update with found patch
                if instance_id not in patches:
                    try:
                        org, repo, number = parse_instance_id(instance_id)
                        patches[instance_id] = {
                            "org": org,
                            "repo": repo,
                            "number": number,
                            "fix_patch": patch_content,
                            "source_run": run_folder
                        }
                        print(f"Collected patch for {instance_id} from {run_folder}")
                    except ValueError as e:
                        print(f"Warning: {e}", file=sys.stderr)

    return patches


def group_by_repo(patches: dict[str, dict]) -> dict[tuple[str, str], list[dict]]:
    """Group patches by repository (org, repo)."""
    repos = defaultdict(list)

    for instance_id, patch_data in patches.items():
        repo_key = (patch_data["org"], patch_data["repo"])
        repos[repo_key].append({
            "org": patch_data["org"],
            "repo": patch_data["repo"],
            "number": patch_data["number"],
            "fix_patch": patch_data["fix_patch"]
        })

    return repos


def write_repo_datasets(repos: dict[tuple[str, str], list[dict]], output_dir: Path):
    """Write JSONL files for each repository."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for (org, repo), patches in repos.items():
        # Sort by issue number for consistent output
        patches.sort(key=lambda x: x["number"])

        output_file = output_dir / f"{org}__{repo}-gemini_2_5_flash_patches.jsonl"

        with open(output_file, "w") as f:
            for patch in patches:
                f.write(json.dumps(patch, ensure_ascii=False) + "\n")

        print(f"Wrote {len(patches)} patches to {output_file}")


def generate_summary(patches: dict[str, dict], repos: dict[tuple[str, str], list[dict]]):
    """Generate and print a summary of collected patches."""
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total instances with patches: {len(patches)}")
    print(f"Total repositories: {len(repos)}")
    print("\nPatches per repository:")
    for (org, repo), repo_patches in sorted(repos.items()):
        print(f"  {org}__{repo}: {len(repo_patches)} patches")

    # Count patches by source run
    source_counts = defaultdict(int)
    for patch_data in patches.values():
        source_counts[patch_data["source_run"]] += 1

    print("\nPatches by source run:")
    for run, count in sorted(source_counts.items()):
        print(f"  {run}: {count} patches")


def main():
    base_dir = Path("/home/researchuser/dev/inri/mobiledev-bench")

    # Define run folders in priority order (earlier runs take precedence)
    run_folders = [
        "full_prediction_results_gemini_25",
        "full_prediction_results_gemini_25_run2",
        "full_prediction_results_gemini_25_run3",
        "full_prediction_results_gemini_25_run4",
    ]

    output_dir = base_dir / "data" / "evaluation"

    print("Collecting patches from multiple runs...")
    patches = collect_patches(base_dir, run_folders)

    if not patches:
        print("Error: No patches found!", file=sys.stderr)
        sys.exit(1)

    print(f"\nGrouping {len(patches)} patches by repository...")
    repos = group_by_repo(patches)

    print(f"\nWriting dataset files to {output_dir}...")
    write_repo_datasets(repos, output_dir)

    generate_summary(patches, repos)
    print("\nDone!")


if __name__ == "__main__":
    main()
