#!/bin/bash
set -e

# Configuration
GITHUB_ORG="MobileDev-Bench"
REGISTRY="ghcr.io"

GITHUB_ORG_LOWER=$(echo "$GITHUB_ORG" | tr '[:upper:]' '[:lower:]')

# Get all mobiledevbench images
images=$(docker images --filter=reference="mobiledevbench/*" --format "{{.Repository}}:{{.Tag}}" | sort -u)

if [ -z "$images" ]; then
    echo "No mobiledevbench images found to push"
    exit 1
fi

echo "Found $(echo "$images" | wc -l) images to push"
echo ""

# Push each image
for image in $images; do
    # Extract repo and tag
    repo=$(echo $image | cut -d: -f1)
    tag=$(echo $image | cut -d: -f2)

    # Create new tag with ghcr.io prefix (using lowercase org name)
    new_tag="${REGISTRY}/${GITHUB_ORG_LOWER}/${repo}:${tag}"

    echo "Tagging: $image -> $new_tag"
    docker tag "$image" "$new_tag"

    echo "Pushing: $new_tag"
    docker push "$new_tag"
    echo ""
done

echo "All images pushed successfully!"
