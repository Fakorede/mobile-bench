#!/bin/bash
set -e

# Remove ghcr.io tagged duplicates, keeping only local mobiledevbench/* images
echo "Cleaning up ghcr.io tagged images (keeping local mobiledevbench versions)..."
echo ""

# Get all ghcr.io mobiledevbench images
images=$(docker images --filter=reference="ghcr.io/mobiledev-bench/mobiledevbench/*" --format "{{.Repository}}:{{.Tag}}")

if [ -z "$images" ]; then
    echo "No ghcr.io tagged images found to clean up"
    exit 0
fi

count=$(echo "$images" | wc -l)
echo "Found $count ghcr.io tagged images to remove"
echo ""

# Remove each image
for image in $images; do
    echo "Removing: $image"
    docker rmi "$image"
done

echo ""
echo "Cleanup complete!"
echo ""
echo "Remaining mobiledev images:"
docker images --filter=reference="*mobiledev*" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | head -20
remaining=$(docker images --filter=reference="*mobiledev*" --format "{{.ID}}" | wc -l)
echo ""
echo "Total remaining: $remaining images"
