#!/bin/bash

echo "Cleaning up Mobile-Bench environment..."

# Stop and remove all mobile-bench containers
docker ps -a --filter "name=mobile_bench_*" --format "{{.Names}}" | xargs -r docker rm -f

# Remove mobile-bench images (optional - uncomment if needed)
# docker images --filter "reference=mobile_bench_*" --format "{{.Repository}}:{{.Tag}}" | xargs -r docker rmi

# Clean up logs and temporary files
find mobile_bench_logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
find mobile_bench_cache -type f -mtime +3 -delete 2>/dev/null || true

# Clean up Docker system (optional)
# docker system prune -f

echo "Cleanup completed"
