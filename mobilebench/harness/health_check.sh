#!/bin/bash

echo "Mobile-Bench Health Check"
echo "========================"

# Check Docker
if docker info &> /dev/null; then
    echo "✓ Docker daemon is running"
else
    echo "✗ Docker daemon is not running"
    exit 1
fi

# Check Docker image
if docker images mingc/android-build-box:latest --format "{{.Repository}}" | grep -q "mingc/android-build-box"; then
    echo "✓ Android build box image is available"
else
    echo "✗ Android build box image is not available"
    echo "  Run: docker pull mingc/android-build-box:latest"
fi

# Check Python environment
if [ -d "venv" ]; then
    echo "✓ Virtual environment exists"
    source venv/bin/activate
    
    if python -c "import docker" 2>/dev/null; then
        echo "✓ Python dependencies are installed"
    else
        echo "✗ Python dependencies are missing"
        echo "  Run: pip install -r requirements.txt"
    fi
else
    echo "✗ Virtual environment not found"
    echo "  Run: python3 -m venv venv"
fi

# Check directories
for dir in mobile_bench_logs mobile_bench_reports mobile_bench_cache test_specs; do
    if [ -d "$dir" ]; then
        echo "✓ Directory $dir exists"
    else
        echo "✗ Directory $dir missing"
    fi
done

echo ""
echo "Health check completed"
