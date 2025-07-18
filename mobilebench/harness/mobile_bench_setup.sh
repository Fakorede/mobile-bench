#!/bin/bash

# Mobile-Bench Setup Script
# Sets up the mobile-bench evaluation environment

set -e

echo "=================================================="
echo "Mobile-Bench Evaluation Harness Setup"
echo "=================================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_warning "Running as root. Consider running as a regular user for better security."
fi

# Check system requirements
print_step "Checking system requirements..."

# Check operating system
OS=$(uname -s)
print_status "Operating System: $OS"

# Check Docker installation
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

print_status "Docker is installed: $(docker --version)"

# Check Docker daemon
if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker."
    exit 1
fi

print_status "Docker daemon is running"

# Check Python installation
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed. Please install Python 3.8 or later."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
print_status "Python is installed: $PYTHON_VERSION"

# Check pip installation
if ! command -v pip3 &> /dev/null; then
    print_error "pip3 is not installed. Please install pip3."
    exit 1
fi

# Setup directories
print_step "Setting up directories..."

mkdir -p mobile_bench_logs
mkdir -p mobile_bench_reports
mkdir -p mobile_bench_cache
mkdir -p test_specs

print_status "Created necessary directories"

# Create Python virtual environment
print_step "Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_status "Created virtual environment"
else
    print_status "Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
print_step "Installing Python dependencies..."

cat > requirements.txt << EOF
docker>=7.1.0
requests>=2.25.0
python-dotenv>=0.19.0
pyyaml>=6.0
xmltodict>=0.12.0
EOF

pip install --upgrade pip
pip install -r requirements.txt

print_status "Python dependencies installed"

# Pull Docker image
print_step "Pulling Android build Docker image..."

if ! docker images mingc/android-build-box:latest --format "{{.Repository}}" | grep -q "mingc/android-build-box"; then
    print_status "Downloading Android build box image (this may take several minutes)..."
    docker pull mingc/android-build-box:latest
    print_status "Docker image pulled successfully"
else
    print_status "Android build box image already exists, skipping download"
fi

# Create configuration file
print_step "Creating configuration file..."

cat > mobile_bench_config.yaml << EOF
# Mobile-Bench Configuration

# Docker settings
docker:
  image: "mingc/android-build-box:latest"
  memory_limit: "4g"
  cpu_count: null  # Use all available CPUs
  timeout: 1800  # 30 minutes default timeout

# Execution settings
execution:
  max_workers: 4
  force_rebuild: false
  cache_level: "none"
  
# Java version mapping (Gradle version -> Java version)
java_versions:
  "8.0": "17"
  "8.1": "17"
  "7.6": "17"
  "7.5": "17"
  "7.0": "17"
  "6.9": "11"
  "6.0": "11"
  "5.0": "8"
  "4.0": "8"

# Test settings
testing:
  default_test_commands:
    - "./gradlew test"
    - "./gradlew connectedAndroidTest"
    - "./gradlew testDebugUnitTest"
  
  default_build_commands:
    - "./gradlew clean"
    - "./gradlew assembleDebug"
    - "./gradlew compileDebugSources"
    
  default_setup_commands:
    - "chmod +x ./gradlew"
    - "export ANDROID_SDK_ROOT=/opt/android-sdk"
    - "export ANDROID_HOME=/opt/android-sdk"

# Logging settings
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  log_to_file: true
  log_directory: "./mobile_bench_logs"

# Report settings
reporting:
  output_directory: "./mobile_bench_reports"
  generate_html: true
  generate_csv: true
  include_individual_reports: true

# Validation settings
validation:
  validate_patches: true
  validate_repositories: true
  check_dangerous_commands: true
  
# Performance settings
performance:
  cleanup_containers: true
  remove_images_after: false
  disk_usage_limit: "50GB"
EOF

print_status "Configuration file created: mobile_bench_config.yaml"

# Create example usage script
print_step "Creating example usage scripts..."

cat > run_example.sh << 'EOF'
#!/bin/bash

# Example usage of Mobile-Bench
# Make sure to activate the virtual environment first

source venv/bin/activate

# Example 1: Run evaluation on sample data
python3 mobile_bench_evaluator.py \
    --dataset_path ./sample_data/instances.jsonl \
    --predictions_path ./sample_data/predictions.jsonl \
    --run_id "example_run_$(date +%Y%m%d_%H%M%S)" \
    --max_workers 2 \
    --timeout 1200 \
    --log_level INFO

# Example 2: Validate only (no actual execution)
python3 mobile_bench_evaluator.py \
    --dataset_path ./sample_data/instances.jsonl \
    --predictions_path ./sample_data/predictions.jsonl \
    --run_id "validation_run" \
    --validate_only

# Example 3: Run specific instances
python3 mobile_bench_evaluator.py \
    --dataset_path ./sample_data/instances.jsonl \
    --predictions_path ./sample_data/predictions.jsonl \
    --run_id "specific_instances" \
    --instance_ids instance_1 instance_2 instance_3 \
    --max_workers 1
EOF

chmod +x run_example.sh

cat > create_sample_data.py << 'EOF'
#!/usr/bin/env python3

import json
import os

# Create sample data directory
os.makedirs('sample_data', exist_ok=True)

# Sample instance data
sample_instances = [
    {
        "instance_id": "sample_android_1",
        "repo": "https://github.com/bitwarden/android.git",
        "base_commit": "main",
        "test_commands": ["./gradlew test"],
        "PASS_TO_PASS": ["com.bitwarden.ExampleTest::testExample"],
        "FAIL_TO_PASS": [],
        "issue_description": "Sample Android issue",
        "metadata": {"complexity": "low"}
    },
    {
        "instance_id": "sample_android_2", 
        "repo": "https://github.com/example/android-app.git",
        "base_commit": "develop",
        "test_commands": ["./gradlew testDebugUnitTest"],
        "PASS_TO_PASS": [],
        "FAIL_TO_PASS": ["com.example.FailingTest::testShouldPass"],
        "issue_description": "Another sample Android issue",
        "metadata": {"complexity": "medium"}
    }
]

# Sample predictions
sample_predictions = [
    {
        "instance_id": "sample_android_1",
        "model_name_or_path": "example_model",
        "patch": '''diff --git a/app/src/main/java/Example.java b/app/src/main/java/Example.java
index 1234567..abcdefg 100644
--- a/app/src/main/java/Example.java
+++ b/app/src/main/java/Example.java
@@ -10,7 +10,7 @@ public class Example {
     }
     
     public String getMessage() {
-        return "Hello World";
+        return "Hello Mobile-Bench";
     }
 }'''
    },
    {
        "instance_id": "sample_android_2",
        "model_name_or_path": "example_model", 
        "patch": '''diff --git a/app/src/test/java/ExampleTest.java b/app/src/test/java/ExampleTest.java
index 1234567..abcdefg 100644
--- a/app/src/test/java/ExampleTest.java
+++ b/app/src/test/java/ExampleTest.java
@@ -15,6 +15,6 @@ public class ExampleTest {
     @Test
     public void testExample() {
-        assertEquals("wrong", getValue());
+        assertEquals("correct", getValue());
     }
 }'''
    }
]

# Save sample data
with open('sample_data/instances.jsonl', 'w') as f:
    for instance in sample_instances:
        f.write(json.dumps(instance) + '\n')

with open('sample_data/predictions.jsonl', 'w') as f:
    for prediction in sample_predictions:
        f.write(json.dumps(prediction) + '\n')

print("Sample data created in ./sample_data/")
print("- instances.jsonl: Sample test instances")
print("- predictions.jsonl: Sample model predictions")
EOF

chmod +x create_sample_data.py

print_status "Example scripts created"

# Create cleanup script
cat > cleanup.sh << 'EOF'
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
EOF

chmod +x cleanup.sh

# Create health check script
cat > health_check.sh << 'EOF'
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
EOF

chmod +x health_check.sh

print_status "Utility scripts created"

# Final setup steps
print_step "Running final setup checks..."

# Test Docker connectivity
if docker run --rm hello-world &> /dev/null; then
    print_status "Docker test successful"
else
    print_warning "Docker test failed - you may need to restart Docker"
fi

# Test Python imports
if python3 -c "import docker; print('Docker Python library is working')" 2>/dev/null; then
    print_status "Python Docker library is working"
else
    print_warning "Python Docker library test failed"
fi

# Create desktop shortcut (Linux only)
if [ "$OS" = "Linux" ] && command -v desktop-file-install &> /dev/null; then
    cat > mobile-bench.desktop << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Mobile-Bench
Comment=Mobile-Bench Evaluation Harness
Exec=$(pwd)/run_example.sh
Icon=application-x-executable
Terminal=true
Categories=Development;
EOF
    print_status "Desktop shortcut created (mobile-bench.desktop)"
fi

print_step "Creating documentation..."

cat > README_SETUP.md << 'EOF'
# Mobile-Bench Setup Complete

## Quick Start

1. **Activate the environment:**
   ```bash
   source venv/bin/activate
   ```

2. **Create sample data (optional):**
   ```bash
   python3 create_sample_data.py
   ```

3. **Run health check:**
   ```bash
   ./health_check.sh
   ```

4. **Run example evaluation:**
   ```bash
   ./run_example.sh
   ```

## Usage

### Basic Usage
```bash
python3 mobile_bench_evaluator.py \
    --dataset_path /path/to/instances.jsonl \
    --predictions_path /path/to/predictions.jsonl \
    --run_id my_evaluation_run
```

### Advanced Usage
```bash
python3 mobile_bench_evaluator.py \
    --dataset_path ./data/instances.jsonl \
    --predictions_path ./data/predictions.jsonl \
    --run_id detailed_run_$(date +%Y%m%d) \
    --max_workers 6 \
    --timeout 2400 \
    --log_level DEBUG \
    --report_dir ./custom_reports
```

## Configuration

Edit `mobile_bench_config.yaml` to customize:
- Docker settings
- Java version mappings
- Default test commands
- Logging configuration
- Report settings

## Maintenance

- **Health check:** `./health_check.sh`
- **Cleanup:** `./cleanup.sh`
- **Update Docker image:** `docker pull mingc/android-build-box:latest`

## Troubleshooting

1. **Docker issues:** Ensure Docker daemon is running
2. **Permission issues:** Check file permissions and user groups
3. **Memory issues:** Reduce max_workers or increase Docker memory limit
4. **Timeout issues:** Increase timeout value for complex projects

## File Structure

```
mobile-bench/
├── mobile_bench_evaluator.py     # Main evaluation script
├── mobile_bench_utils.py         # Utility functions
├── mobile_bench_test_spec.py     # Test specification handling
├── mobile_bench_grading.py       # Grading and evaluation logic
├── mobile_bench_config.yaml      # Configuration file
├── requirements.txt              # Python dependencies
├── venv/                         # Python virtual environment
├── mobile_bench_logs/            # Execution logs
├── mobile_bench_reports/         # Generated reports
├── mobile_bench_cache/           # Cache directory
├── test_specs/                   # Test specifications
└── sample_data/                  # Sample data for testing
```

## Support

For issues and questions:
1. Check the logs in `mobile_bench_logs/`
2. Run health check: `./health_check.sh`
3. Review the configuration: `mobile_bench_config.yaml`
EOF

print_status "Documentation created: README_SETUP.md"

echo ""
echo "=================================================="
print_status "Mobile-Bench setup completed successfully!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Activate the environment: source venv/bin/activate"
echo "2. Run health check: ./health_check.sh"
echo "3. Create sample data: python3 create_sample_data.py"
echo "4. Run example: ./run_example.sh"
echo ""
echo "For detailed usage instructions, see: README_SETUP.md"
echo ""

# Deactivate virtual environment if it was activated
deactivate 2>/dev/null || true

print_status "Setup script completed!"