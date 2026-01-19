#!/bin/bash
set -e

# Unresolved PR numbers to delete (for zulip/zulip-flutter)
UNRESOLVED_PRS=(
    5205
    5056
)

# Repository name pattern in Docker images
REPO_NAME="mobiledevbench/{org_mb_repo}"

echo "Deleting Docker images for unresolved zulip/zulip-flutter PRs..."
echo ""

for pr in "${UNRESOLVED_PRS[@]}"; do
    tag="pr-${pr}"
    image="${REPO_NAME}:${tag}"

    echo "Processing PR-${pr}..."

    # Check if image exists
    if docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${image}$"; then
        echo "  Found image: $image"
        echo "  Deleting..."
        if docker rmi "$image"; then
            echo "  ✓ Deleted $image"
        else
            echo "  ✗ Failed to delete $image"
        fi
    else
        echo "  No image found for: $image"
    fi

    echo ""
done

echo "Done!"
