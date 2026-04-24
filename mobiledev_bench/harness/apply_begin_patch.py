#!/usr/bin/env python3
"""
Convert *** Begin Patch format to unified diff in-place.

Reads /home/fix.patch, converts to unified diff using the repo source files
(already checked out at the correct base commit inside the container),
then overwrites /home/fix.patch so fix-run.sh can apply it with git apply.

Usage: python3 apply_begin_patch.py <patch_file> <repo_root>
"""

import sys
from pathlib import Path


def parse_begin_patch(patch_text: str) -> list[dict]:
    """Parse *** Begin Patch format into a list of file operations."""
    operations = []
    lines = patch_text.splitlines()
    i = 0

    while i < len(lines) and lines[i].strip() != "*** Begin Patch":
        i += 1
    i += 1  # skip the Begin Patch line

    while i < len(lines):
        line = lines[i]

        if line.strip() == "*** End Patch":
            break

        if line.startswith("*** Update File: "):
            filepath = line[len("*** Update File: "):].strip()
            hunks = []
            i += 1
            while i < len(lines) and not lines[i].startswith("*** "):
                if lines[i] == "@@":
                    hunk_lines = []
                    i += 1
                    while i < len(lines) and lines[i] != "@@" and not lines[i].startswith("*** "):
                        hunk_lines.append(lines[i])
                        i += 1
                    if hunk_lines:
                        hunks.append(hunk_lines)
                else:
                    i += 1
            operations.append({"type": "update", "path": filepath, "hunks": hunks})

        elif line.startswith("*** Add File: "):
            filepath = line[len("*** Add File: "):].strip()
            content_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("*** "):
                content_lines.append(lines[i])
                i += 1
            operations.append({"type": "add", "path": filepath, "lines": content_lines})

        elif line.startswith("*** Delete File: "):
            filepath = line[len("*** Delete File: "):].strip()
            operations.append({"type": "delete", "path": filepath})
            i += 1

        else:
            i += 1

    return operations


def find_context_in_file(file_lines: list[str], context_lines: list[str]) -> int:
    """
    Find where context_lines appear in file_lines (0-indexed).
    Returns the start index or -1 if not found.
    Tries exact match first, then falls back to stripped whitespace comparison.
    """
    if not context_lines:
        return 0

    n = len(file_lines)
    k = len(context_lines)

    for start in range(n - k + 1):
        if all(
            file_lines[start + j].rstrip("\n\r") == context_lines[j]
            for j in range(k)
        ):
            return start

    # Whitespace-stripped fallback
    stripped_context = [l.strip() for l in context_lines]
    for start in range(n - k + 1):
        if all(
            file_lines[start + j].strip() == stripped_context[j]
            for j in range(k)
        ):
            return start

    return -1


def convert_update_file(filepath: str, file_lines: list[str], hunks: list[list[str]]) -> str:
    """
    Convert a sequence of hunks for one file into a unified diff string.
    Raises ValueError if any hunk's context cannot be located.
    """
    diff_lines = [f"--- a/{filepath}", f"+++ b/{filepath}"]
    cumulative_offset = 0  # tracks how prior hunks shift new-file line numbers

    for hunk_lines in hunks:
        # Collect lines that exist in the original file (context + removals)
        orig_lines = []
        for line in hunk_lines:
            if line.startswith("+"):
                continue
            elif line.startswith("-"):
                orig_lines.append(line[1:])
            elif line.startswith(" "):
                orig_lines.append(line[1:])
            else:
                orig_lines.append(line)  # bare line treated as context

        start_idx = find_context_in_file(file_lines, orig_lines)
        if start_idx == -1:
            context_preview = repr(orig_lines[:3])
            raise ValueError(
                f"Could not locate hunk context in '{filepath}': {context_preview}"
            )

        old_count = len(orig_lines)
        new_count = sum(1 for l in hunk_lines if not l.startswith("-"))

        old_start = start_idx + 1  # 1-indexed
        new_start = old_start + cumulative_offset

        diff_lines.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@")

        for line in hunk_lines:
            if line.startswith("+") or line.startswith("-"):
                diff_lines.append(line)
            elif line.startswith(" "):
                diff_lines.append(line)
            else:
                diff_lines.append(" " + line)

        cumulative_offset += new_count - old_count

    return "\n".join(diff_lines)


def convert_to_unified_diff(patch_text: str, repo_root: Path) -> str:
    """Convert *** Begin Patch format to a unified diff string."""
    operations = parse_begin_patch(patch_text)
    diff_parts = []
    errors = []

    for op in operations:
        if op["type"] == "update":
            file_path = repo_root / op["path"]
            if not file_path.exists():
                errors.append(f"File not found: {file_path}")
                continue

            file_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()

            try:
                diff_parts.append(convert_update_file(op["path"], file_lines, op["hunks"]))
            except ValueError as e:
                errors.append(str(e))

        elif op["type"] == "add":
            stripped = [l[1:] if l.startswith("+") else l for l in op["lines"]]
            count = len(stripped)
            hunk_body = "\n".join("+" + l for l in stripped)
            diff_parts.append(
                f"--- /dev/null\n+++ b/{op['path']}\n"
                f"@@ -0,0 +1,{count} @@\n{hunk_body}"
            )

        elif op["type"] == "delete":
            file_path = repo_root / op["path"]
            if file_path.exists():
                file_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                count = len(file_lines)
                hunk_body = "\n".join("-" + l for l in file_lines)
                diff_parts.append(
                    f"--- a/{op['path']}\n+++ /dev/null\n"
                    f"@@ -1,{count} +0,0 @@\n{hunk_body}"
                )

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    return "\n".join(diff_parts) + "\n"


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <patch_file> <repo_root>", file=sys.stderr)
        sys.exit(1)

    patch_file = Path(sys.argv[1])
    repo_root = Path(sys.argv[2])

    if not patch_file.exists():
        print(f"Patch file not found: {patch_file}", file=sys.stderr)
        sys.exit(1)

    if not repo_root.exists():
        print(f"Repo root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    patch_text = patch_file.read_text(encoding="utf-8")

    if "*** Begin Patch" not in patch_text:
        print("Not a Begin Patch format, skipping conversion.", file=sys.stderr)
        sys.exit(0)

    print(f"Converting Begin Patch format to unified diff (repo: {repo_root})...")
    unified = convert_to_unified_diff(patch_text, repo_root)
    patch_file.write_text(unified, encoding="utf-8")
    print(f"Converted patch written to {patch_file}")
    print(unified[:500] + ("..." if len(unified) > 500 else ""))


if __name__ == "__main__":
    main()
