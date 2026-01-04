#!/bin/bash

# Script to pull Docker images from GitHub Container Registry (GHCR)
# Usage: ./pull_images_from_gcr.sh [GITHUB_USERNAME]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_LIST="${SCRIPT_DIR}/images.txt"

# Get GitHub username from argument or use default
GHCR_USERNAME="${1:-mobiledev-bench}"

# Validate inputs
if [ ! -f "$IMAGE_LIST" ]; then
    echo "Error: Image list file not found at $IMAGE_LIST"
    exit 1
fi

echo ""
echo "Pulling images from: ghcr.io/${GHCR_USERNAME}/"
echo "Image list: $IMAGE_LIST"
echo ""

# Count non-empty lines
total=0
while IFS= read -r line || [ -n "$line" ]; do
    [ -n "${line// }" ] && total=$((total + 1))
done < "$IMAGE_LIST"

echo "Found $total images to pull"
echo ""

current=0
success=0
failed=0

# Process each image
while IFS= read -r local_image || [ -n "$local_image" ]; do
    # Skip empty lines
    [ -z "${local_image// }" ] && continue
    
    current=$((current + 1))

    # Extract tag and repo from local image (mobiledevbench/repo:tag)
    tag="${local_image##*:}"
    repo_name="${local_image%:*}"

    # GHCR format: ghcr.io/username/mobiledevbench/repo:tag
    ghcr_image="ghcr.io/${GHCR_USERNAME}/${repo_name}:${tag}"

    echo "[$current/$total] Pulling: $ghcr_image"

    # Pull image
    if docker pull "$ghcr_image" > /dev/null 2>&1; then
        # Tag with local name
        if docker tag "$ghcr_image" "$local_image" > /dev/null 2>&1; then
            echo "          -> Tagged as: $local_image"
            # Remove the GHCR remote tag
            if docker rmi "$ghcr_image" > /dev/null 2>&1; then
                echo "          -> Removed remote tag"
            fi
            echo "          ✓ Success"
            success=$((success + 1))
        else
            echo "          ✗ Failed to tag as: $local_image"
            failed=$((failed + 1))
        fi
    else
        echo "          ✗ Failed to pull"
        failed=$((failed + 1))
    fi
    echo ""
done < "$IMAGE_LIST"

echo "========================================"
echo "Summary:"
echo "  Total images:  $total"
echo "  Successful:    $success"
echo "  Failed:        $failed"
echo "========================================"

if [ $failed -eq 0 ]; then
    echo "All images pulled successfully!"
    exit 0
else
    echo "Some images failed to pull"
    exit 1
fi
