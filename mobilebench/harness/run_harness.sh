#!/bin/bash

# Mobile Bench Android Evaluation Harness
#
# This script evaluates AI-generated patches for Android projects using Docker containers
# with the mingchen/docker-android-build-box image for consistent Android build environments.
#
# Usage:
#   ./run_mobile_bench_harness.sh --predictions results.jsonl --dataset data.jsonl --run-id test_run_001
#   ./run_mobile_bench_harness.sh --predictions results.jsonl --dataset data.jsonl --run-id test_run_001 --max-workers 2 --timeout 1800
#
# The script expects predictions in the format:
# {
#   "instance_id": "AntennaPod-123",
#   "model_name_or_path": "gpt-4", 
#   "generated_patch": "diff --git a/...",
#   "base_commit": "abc123def456"
# }

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    if [[ "$DEBUG" == "true" ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1"
    fi
}

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../.."
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"

# Default configuration
DEFAULT_DOCKER_IMAGE="mingchen/docker-android-build-box:latest"
DEFAULT_MAX_WORKERS=4
DEFAULT_TIMEOUT=1800  # 30 minutes
DEFAULT_LOG_DIR="$PROJECT_ROOT/logs/harness"
DEFAULT_REPORT_DIR="$PROJECT_ROOT/reports"
DEFAULT_CACHE_DIR="$PROJECT_ROOT/cache"
DEFAULT_DEBUG="false"
DEFAULT_CLEAN_CONTAINERS="true"
DEFAULT_FORCE_REBUILD="false"
DEFAULT_ANDROID_API_LEVEL="33"
DEFAULT_BUILD_TOOLS_VERSION="33.0.2"

# Configuration variables
PREDICTIONS_FILE=""
DATASET_FILE=""
RUN_ID=""
MAX_WORKERS="${MAX_WORKERS:-$DEFAULT_MAX_WORKERS}"
TIMEOUT="${TIMEOUT:-$DEFAULT_TIMEOUT}"
LOG_DIR="${LOG_DIR:-$DEFAULT_LOG_DIR}"
REPORT_DIR="${REPORT_DIR:-$DEFAULT_REPORT_DIR}"
CACHE_DIR="${CACHE_DIR:-$DEFAULT_CACHE_DIR}"
DOCKER_IMAGE="${DOCKER_IMAGE:-$DEFAULT_DOCKER_IMAGE}"
DEBUG="${DEBUG:-$DEFAULT_DEBUG}"
CLEAN_CONTAINERS="${CLEAN_CONTAINERS:-$DEFAULT_CLEAN_CONTAINERS}"
FORCE_REBUILD="${FORCE_REBUILD:-$DEFAULT_FORCE_REBUILD}"
ANDROID_API_LEVEL="${ANDROID_API_LEVEL:-$DEFAULT_ANDROID_API_LEVEL}"
BUILD_TOOLS_VERSION="${BUILD_TOOLS_VERSION:-$DEFAULT_BUILD_TOOLS_VERSION}"
INSTANCE_IDS=()
DRY_RUN="false"

# Function to show usage
show_usage() {
    cat << EOF
Mobile Bench Android Evaluation Harness

Evaluates AI-generated patches for Android projects using Docker containers.

USAGE:
    $0 --predictions FILE --dataset FILE --run-id ID [OPTIONS]

REQUIRED ARGUMENTS:
    --predictions FILE        Path to predictions JSONL file
    --dataset FILE           Path to dataset JSONL file  
    --run-id ID             Unique identifier for this evaluation run

OPTIONS:
    --max-workers N          Maximum parallel workers (default: $DEFAULT_MAX_WORKERS)
    --timeout SECONDS        Timeout per instance in seconds (default: $DEFAULT_TIMEOUT)
    --log-dir DIR           Directory for logs (default: $DEFAULT_LOG_DIR)
    --report-dir DIR        Directory for reports (default: $DEFAULT_REPORT_DIR)
    --cache-dir DIR         Directory for caching (default: $DEFAULT_CACHE_DIR)
    --docker-image IMAGE    Docker image to use (default: $DEFAULT_DOCKER_IMAGE)
    --android-api-level N   Android API level (default: $DEFAULT_ANDROID_API_LEVEL)
    --build-tools-version V Build tools version (default: $DEFAULT_BUILD_TOOLS_VERSION)
    --instance-ids ID1 ID2  Specific instance IDs to evaluate (space-separated)
    --force-rebuild         Force rebuild of all containers
    --no-clean              Don't clean up containers after evaluation
    --dry-run               Show what would be done without executing
    --debug                 Enable debug logging
    --help                  Show this help message

EXAMPLES:
    # Basic evaluation
    $0 --predictions results.jsonl --dataset data.jsonl --run-id test_001

    # Evaluate specific instances with debug output
    $0 --predictions results.jsonl --dataset data.jsonl --run-id debug_001 \\
       --instance-ids AntennaPod-123 AntennaPod-456 --debug

    # Production run with custom settings
    $0 --predictions results.jsonl --dataset data.jsonl --run-id prod_001 \\
       --max-workers 8 --timeout 3600 --android-api-level 34

    # Dry run to see what would happen
    $0 --predictions results.jsonl --dataset data.jsonl --run-id test_001 --dry-run

PREDICTION FILE FORMAT:
    Each line should be a JSON object with:
    {
        "instance_id": "AntennaPod-123",
        "model_name_or_path": "gpt-4",
        "generated_patch": "diff --git a/app/src/main/...",
        "base_commit": "abc123def456"
    }

DATASET FILE FORMAT:
    Each line should be a JSON object with:
    {
        "instance_id": "AntennaPod-123", 
        "repo_url": "https://github.com/AntennaPod/AntennaPod",
        "base_commit": "abc123def456",
        "test_commands": ["./gradlew testDebugUnitTest"],
        "build_commands": ["./gradlew assembleDebug"]
    }

EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --predictions)
                PREDICTIONS_FILE="$2"
                shift 2
                ;;
            --dataset)
                DATASET_FILE="$2"
                shift 2
                ;;
            --run-id)
                RUN_ID="$2"
                shift 2
                ;;
            --max-workers)
                MAX_WORKERS="$2"
                shift 2
                ;;
            --timeout)
                TIMEOUT="$2"
                shift 2
                ;;
            --log-dir)
                LOG_DIR="$2"
                shift 2
                ;;
            --report-dir)
                REPORT_DIR="$2"
                shift 2
                ;;
            --cache-dir)
                CACHE_DIR="$2"
                shift 2
                ;;
            --docker-image)
                DOCKER_IMAGE="$2"
                shift 2
                ;;
            --android-api-level)
                ANDROID_API_LEVEL="$2"
                shift 2
                ;;
            --build-tools-version)
                BUILD_TOOLS_VERSION="$2"
                shift 2
                ;;
            --instance-ids)
                shift
                while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                    INSTANCE_IDS+=("$1")
                    shift
                done
                ;;
            --force-rebuild)
                FORCE_REBUILD="true"
                shift
                ;;
            --no-clean)
                CLEAN_CONTAINERS="false"
                shift
                ;;
            --dry-run)
                DRY_RUN="true"
                shift
                ;;
            --debug)
                DEBUG="true"
                shift
                ;;
            --help)
                show_usage
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

# Validation functions
validate_arguments() {
    log_debug "Validating arguments..."
    
    # Check required arguments
    if [[ -z "$PREDICTIONS_FILE" ]]; then
        log_error "Predictions file is required (--predictions)"
        exit 1
    fi
    
    if [[ -z "$DATASET_FILE" ]]; then
        log_error "Dataset file is required (--dataset)"
        exit 1
    fi
    
    if [[ -z "$RUN_ID" ]]; then
        log_error "Run ID is required (--run-id)"
        exit 1
    fi
    
    # Validate run ID format (no spaces, special chars)
    if [[ ! "$RUN_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        log_error "Run ID must contain only letters, numbers, underscores, and dashes"
        exit 1
    fi
    
    # Check file existence
    if [[ ! -f "$PREDICTIONS_FILE" ]]; then
        log_error "Predictions file not found: $PREDICTIONS_FILE"
        exit 1
    fi
    
    if [[ ! -f "$DATASET_FILE" ]]; then
        log_error "Dataset file not found: $DATASET_FILE"
        exit 1
    fi
    
    # Validate numeric arguments
    if [[ ! "$MAX_WORKERS" =~ ^[0-9]+$ ]] || [[ "$MAX_WORKERS" -lt 1 ]]; then
        log_error "Max workers must be a positive integer"
        exit 1
    fi
    
    if [[ ! "$TIMEOUT" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT" -lt 60 ]]; then
        log_error "Timeout must be at least 60 seconds"
        exit 1
    fi
    
    # Check Docker availability
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running or not accessible"
        exit 1
    fi
    
    log_debug "All arguments validated successfully"
}

# Setup functions
setup_directories() {
    log_step "Setting up directories..."
    
    # Create necessary directories
    mkdir -p "$LOG_DIR/$RUN_ID"
    mkdir -p "$REPORT_DIR"
    mkdir -p "$CACHE_DIR"
    
    log_debug "Created directories:"
    log_debug "  Log dir: $LOG_DIR/$RUN_ID"
    log_debug "  Report dir: $REPORT_DIR"
    log_debug "  Cache dir: $CACHE_DIR"
}

# Docker functions
pull_docker_image() {
    log_step "Checking Docker image: $DOCKER_IMAGE"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would pull Docker image $DOCKER_IMAGE"
        return 0
    fi
    
    if ! docker image inspect "$DOCKER_IMAGE" &> /dev/null; then
        log_info "Pulling Docker image: $DOCKER_IMAGE"
        if ! docker pull "$DOCKER_IMAGE"; then
            log_error "Failed to pull Docker image: $DOCKER_IMAGE"
            exit 1
        fi
    else
        log_info "Docker image already available: $DOCKER_IMAGE"
    fi
}

# Data processing functions
load_predictions() {
    log_step "Loading predictions from $PREDICTIONS_FILE"
    
    local count=0
    local valid_count=0
    
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        count=$((count + 1))
        
        # Basic JSON validation
        if echo "$line" | jq empty 2>/dev/null; then
            local instance_id=$(echo "$line" | jq -r '.instance_id // empty')
            local model_path=$(echo "$line" | jq -r '.model_name_or_path // empty')
            local patch=$(echo "$line" | jq -r '.generated_patch // empty')
            
            if [[ -n "$instance_id" && -n "$model_path" && -n "$patch" ]]; then
                valid_count=$((valid_count + 1))
            else
                log_warn "Line $count: Missing required fields (instance_id, model_name_or_path, generated_patch)"
            fi
        else
            log_warn "Line $count: Invalid JSON format"
        fi
    done < "$PREDICTIONS_FILE"
    
    log_info "Loaded $valid_count valid predictions out of $count total lines"
    
    if [[ $valid_count -eq 0 ]]; then
        log_error "No valid predictions found"
        exit 1
    fi
}

load_dataset() {
    log_step "Loading dataset from $DATASET_FILE"
    
    local count=0
    local valid_count=0
    
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        count=$((count + 1))
        
        if echo "$line" | jq empty 2>/dev/null; then
            local instance_id=$(echo "$line" | jq -r '.instance_id // empty')
            local repo_url=$(echo "$line" | jq -r '.repo_url // empty')
            local base_commit=$(echo "$line" | jq -r '.base_commit // empty')
            
            if [[ -n "$instance_id" && -n "$repo_url" && -n "$base_commit" ]]; then
                valid_count=$((valid_count + 1))
            else
                log_warn "Line $count: Missing required fields (instance_id, repo_url, base_commit)"
            fi
        else
            log_warn "Line $count: Invalid JSON format"
        fi
    done < "$DATASET_FILE"
    
    log_info "Loaded $valid_count valid dataset entries out of $count total lines"
    
    if [[ $valid_count -eq 0 ]]; then
        log_error "No valid dataset entries found"
        exit 1
    fi
}

# Get instances to evaluate
get_instances_to_evaluate() {
    log_step "Determining instances to evaluate..."
    
    local temp_dir=$(mktemp -d)
    local predictions_ids="$temp_dir/prediction_ids.txt"
    local dataset_ids="$temp_dir/dataset_ids.txt"
    local instances_file="$temp_dir/instances_to_eval.txt"
    
    # Extract instance IDs from predictions
    jq -r '.instance_id' "$PREDICTIONS_FILE" 2>/dev/null | grep -v '^null$' | sort > "$predictions_ids"
    
    # Extract instance IDs from dataset
    jq -r '.instance_id' "$DATASET_FILE" 2>/dev/null | grep -v '^null$' | sort > "$dataset_ids"
    
    # Find intersection (instances that have both predictions and dataset entries)
    comm -12 "$predictions_ids" "$dataset_ids" > "$instances_file"
    
    # Filter by specific instance IDs if provided
    if [[ ${#INSTANCE_IDS[@]} -gt 0 ]]; then
        local filtered_file="$temp_dir/filtered_instances.txt"
        printf '%s\n' "${INSTANCE_IDS[@]}" | sort > "$temp_dir/requested_ids.txt"
        comm -12 "$instances_file" "$temp_dir/requested_ids.txt" > "$filtered_file"
        cp "$filtered_file" "$instances_file"
        
        local missing_ids=($(comm -23 "$temp_dir/requested_ids.txt" "$instances_file"))
        if [[ ${#missing_ids[@]} -gt 0 ]]; then
            log_warn "Requested instance IDs not found in data: ${missing_ids[*]}"
        fi
    fi
    
    local instance_count=$(wc -l < "$instances_file")
    log_info "Found $instance_count instances to evaluate"
    
    if [[ $instance_count -eq 0 ]]; then
        log_error "No instances to evaluate"
        rm -rf "$temp_dir"
        exit 1
    fi
    
    # Store instances for later use
    INSTANCES_TO_EVAL=()
    while IFS= read -r instance_id; do
        INSTANCES_TO_EVAL+=("$instance_id")
    done < "$instances_file"
    
    rm -rf "$temp_dir"
}

# Single instance evaluation
evaluate_instance() {
    local instance_id="$1"
    local instance_log_dir="$LOG_DIR/$RUN_ID/$instance_id"
    local container_name="mobile_bench_${RUN_ID}_${instance_id}"
    
    log_info "Starting evaluation for instance: $instance_id"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would evaluate instance $instance_id"
        return 0
    fi
    
    # Create instance log directory
    mkdir -p "$instance_log_dir"
    
    # Get prediction and dataset data for this instance
    local prediction=$(jq --arg id "$instance_id" 'select(.instance_id == $id)' "$PREDICTIONS_FILE")
    local dataset_entry=$(jq --arg id "$instance_id" 'select(.instance_id == $id)' "$DATASET_FILE")
    
    if [[ -z "$prediction" || -z "$dataset_entry" ]]; then
        log_error "Missing data for instance $instance_id"
        echo '{"instance_id": "'$instance_id'", "status": "error", "error": "Missing prediction or dataset entry"}' > "$instance_log_dir/report.json"
        return 1
    fi
    
    # Extract data from JSON
    local model_name=$(echo "$prediction" | jq -r '.model_name_or_path')
    local patch_content=$(echo "$prediction" | jq -r '.generated_patch')
    local repo_url=$(echo "$dataset_entry" | jq -r '.repo_url')
    local base_commit=$(echo "$dataset_entry" | jq -r '.base_commit')
    local test_commands=$(echo "$dataset_entry" | jq -r '.test_commands[]? // "./gradlew testDebugUnitTest"')
    local build_commands=$(echo "$dataset_entry" | jq -r '.build_commands[]? // "./gradlew assembleDebug"')
    
    # Save patch to file
    local patch_file="$instance_log_dir/patch.diff"
    echo "$patch_content" > "$patch_file"
    
    # Start container
    log_debug "Starting container: $container_name"
    if ! docker run -d \
        --name "$container_name" \
        --workdir /workspace \
        -v "$instance_log_dir:/logs" \
        -v "$patch_file:/patch.diff:ro" \
        -e "ANDROID_API_LEVEL=$ANDROID_API_LEVEL" \
        -e "BUILD_TOOLS_VERSION=$BUILD_TOOLS_VERSION" \
        "$DOCKER_IMAGE" \
        sleep 3600; then
        log_error "Failed to start container for $instance_id"
        return 1
    fi
    
    local success=true
    local error_msg=""
    
    # Function to run command in container with logging
    run_in_container() {
        local cmd="$1"
        local step_name="$2"
        local log_file="$instance_log_dir/${step_name}.log"
        
        log_debug "Running $step_name: $cmd"
        
        if timeout "$TIMEOUT" docker exec "$container_name" bash -c "$cmd" > "$log_file" 2>&1; then
            log_debug "$step_name completed successfully"
            return 0
        else
            local exit_code=$?
            log_error "$step_name failed with exit code $exit_code"
            error_msg="$step_name failed"
            success=false
            return $exit_code
        fi
    }
    
    # Clone repository
    if $success; then
        run_in_container "git clone $repo_url /workspace/repo" "clone"
    fi
    
    # Checkout specific commit
    if $success; then
        run_in_container "cd /workspace/repo && git checkout $base_commit" "checkout"
    fi
    
    # Apply patch
    if $success; then
        # Try multiple patch application methods
        local patch_applied=false
        for method in "git apply --verbose" "git apply --verbose --reject" "patch -p1"; do
            if run_in_container "cd /workspace/repo && $method < /patch.diff" "patch_${method// /_}"; then
                patch_applied=true
                break
            fi
        done
        
        if [[ "$patch_applied" != "true" ]]; then
            success=false
            error_msg="Failed to apply patch with any method"
        fi
    fi
    
    # Build project
    if $success; then
        run_in_container "cd /workspace/repo && $build_commands" "build"
    fi
    
    # Run tests
    local test_results=""
    if $success; then
        if run_in_container "cd /workspace/repo && $test_commands" "test"; then
            test_results="PASSED"
        else
            test_results="FAILED"
            # Don't mark as overall failure - test failures are expected
        fi
    fi
    
    # Generate report
    local report_file="$instance_log_dir/report.json"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    if $success; then
        cat > "$report_file" << EOF
{
    "instance_id": "$instance_id",
    "model_name_or_path": "$model_name",
    "status": "completed",
    "patch_applied": true,
    "build_success": true,
    "test_results": "$test_results",
    "resolved": $([ "$test_results" = "PASSED" ] && echo "true" || echo "false"),
    "timestamp": "$timestamp",
    "container_name": "$container_name"
}
EOF
        log_info "Instance $instance_id completed: Tests $test_results"
    else
        cat > "$report_file" << EOF
{
    "instance_id": "$instance_id", 
    "model_name_or_path": "$model_name",
    "status": "error",
    "error": "$error_msg",
    "patch_applied": false,
    "build_success": false,
    "test_results": "ERROR",
    "resolved": false,
    "timestamp": "$timestamp",
    "container_name": "$container_name"
}
EOF
        log_error "Instance $instance_id failed: $error_msg"
    fi
    
    # Cleanup container
    if [[ "$CLEAN_CONTAINERS" == "true" ]]; then
        log_debug "Cleaning up container: $container_name"
        docker stop "$container_name" &> /dev/null || true
        docker rm "$container_name" &> /dev/null || true
    else
        log_debug "Keeping container for debugging: $container_name"
        docker stop "$container_name" &> /dev/null || true
    fi
    
    return 0
}

# Parallel evaluation
run_evaluation() {
    log_step "Starting evaluation of ${#INSTANCES_TO_EVAL[@]} instances with $MAX_WORKERS workers"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would evaluate instances: ${INSTANCES_TO_EVAL[*]}"
        return 0
    fi
    
    # Create a temporary directory for coordination
    local temp_dir=$(mktemp -d)
    local pids_file="$temp_dir/pids.txt"
    local completed_file="$temp_dir/completed.txt"
    
    # Initialize counters
    local total_instances=${#INSTANCES_TO_EVAL[@]}
    local completed=0
    local running=0
    local max_workers=$MAX_WORKERS
    
    # Function to wait for workers to finish
    wait_for_worker() {
        wait
        running=0
        # Count completed instances
        completed=$(find "$LOG_DIR/$RUN_ID" -name "report.json" -type f | wc -l)
    }
    
    # Process instances
    local instance_index=0
    while [[ $instance_index -lt $total_instances ]]; do
        # Start workers up to max_workers
        while [[ $running -lt $max_workers && $instance_index -lt $total_instances ]]; do
            local instance_id="${INSTANCES_TO_EVAL[$instance_index]}"
            
            log_info "Starting worker for instance $((instance_index + 1))/$total_instances: $instance_id"
            
            # Start evaluation in background
            evaluate_instance "$instance_id" &
            local pid=$!
            echo "$pid:$instance_id" >> "$pids_file"
            
            running=$((running + 1))
            instance_index=$((instance_index + 1))
        done
        
        # Wait for at least one worker to finish
        wait_for_worker
        
        # Show progress
        log_info "Progress: $completed/$total_instances completed"
    done
    
    # Wait for all remaining workers
    log_info "Waiting for remaining workers to complete..."
    wait_for_worker
    
    rm -rf "$temp_dir"
    log_info "All instances completed: $completed/$total_instances"
}

# Report generation
generate_final_report() {
    log_step "Generating final report..."
    
    local report_file="$REPORT_DIR/mobile_bench_${RUN_ID}_report.json"
    local summary_file="$REPORT_DIR/mobile_bench_${RUN_ID}_summary.txt"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would generate reports at:"
        log_info "  $report_file"
        log_info "  $summary_file" 
        return 0
    fi
    
    # Collect all individual reports
    local reports_json="["
    local first=true
    local total=0
    local resolved=0
    local applied=0
    local build_success=0
    local errors=0
    
    for instance_id in "${INSTANCES_TO_EVAL[@]}"; do
        local instance_report="$LOG_DIR/$RUN_ID/$instance_id/report.json"
        
        if [[ -f "$instance_report" ]]; then
            if [[ "$first" != "true" ]]; then
                reports_json+=","
            fi
            reports_json+=$(cat "$instance_report")
            first=false
            
            # Count statistics
            total=$((total + 1))
            if jq -e '.resolved == true' "$instance_report" &>/dev/null; then
                resolved=$((resolved + 1))
            fi
            if jq -e '.patch_applied == true' "$instance_report" &>/dev/null; then
                applied=$((applied + 1))
            fi
            if jq -e '.build_success == true' "$instance_report" &>/dev/null; then
                build_success=$((build_success + 1))
            fi
            if jq -e '.status == "error"' "$instance_report" &>/dev/null; then
                errors=$((errors + 1))
            fi
        fi
    done
    reports_json+="]"
    
    # Generate final report JSON
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    cat > "$report_file" << EOF
{
    "run_id": "$RUN_ID",
    "timestamp": "$timestamp",
    "configuration": {
        "max_workers": $MAX_WORKERS,
        "timeout": $TIMEOUT,
        "docker_image": "$DOCKER_IMAGE",
        "android_api_level": "$ANDROID_API_LEVEL",
        "build_tools_version": "$BUILD_TOOLS_VERSION"
    },
    "statistics": {
        "total_instances": $total,
        "resolved": $resolved,
        "patch_applied": $applied,
        "build_success": $build_success,
        "errors": $errors,
        "resolve_rate": $(echo "scale=4; $resolved * 100 / $total" | bc -l 2>/dev/null || echo "0"),
        "patch_apply_rate": $(echo "scale=4; $applied * 100 / $total" | bc -l 2>/dev/null || echo "0"),
        "build_success_rate": $(echo "scale=4; $build_success * 100 / $total" | bc -l 2>/dev/null || echo "0")
    },
    "results": $reports_json
}
EOF
    
    # Generate summary text report
    cat > "$summary_file" << EOF
Mobile Bench Evaluation Report
===============================

Run ID: $RUN_ID
Timestamp: $timestamp
Docker Image: $DOCKER_IMAGE

Configuration:
- Max Workers: $MAX_WORKERS
- Timeout: ${TIMEOUT}s
- Android API Level: $ANDROID_API_LEVEL
- Build Tools Version: $BUILD_TOOLS_VERSION

Results Summary:
- Total Instances: $total
- Resolved (Tests Passed): $resolved ($(echo "scale=1; $resolved * 100 / $total" | bc -l 2>/dev/null || echo "0")%)
- Patch Applied: $applied ($(echo "scale=1; $applied * 100 / $total" | bc -l 2>/dev/null || echo "0")%)
- Build Success: $build_success ($(echo "scale=1; $build_success * 100 / $total" | bc -l 2>/dev/null || echo "0")%)
- Errors: $errors ($(echo "scale=1; $errors * 100 / $total" | bc -l 2>/dev/null || echo "0")%)

Detailed Results:
$(for instance_id in "${INSTANCES_TO_EVAL[@]}"; do
    local report="$LOG_DIR/$RUN_ID/$instance_id/report.json"
    if [[ -f "$report" ]]; then
        local status=$(jq -r '.status' "$report")
        local resolved=$(jq -r '.resolved' "$report")
        local test_results=$(jq -r '.test_results' "$report")
        echo "- $instance_id: $status (resolved: $resolved, tests: $test_results)"
    else
        echo "- $instance_id: missing report"
    fi
done)

Log Directory: $LOG_DIR/$RUN_ID
Report Files: $report_file
EOF
    
    log_info "Final report generated:"
    log_info "  JSON: $report_file"
    log_info "  Summary: $summary_file"
    
    # Print summary to console
    echo
    log_info "=== EVALUATION SUMMARY ==="
    log_info "Run ID: $RUN_ID"
    log_info "Total instances: $total"
    log_info "Resolved: $resolved ($(echo "scale=1; $resolved * 100 / $total" | bc -l 2>/dev/null || echo "0")%)"
    log_info "Patch applied: $applied ($(echo "scale=1; $applied * 100 / $total" | bc -l 2>/dev/null || echo "0")%)"
    log_info "Build success: $build_success ($(echo "scale=1; $build_success * 100 / $total" | bc -l 2>/dev/null || echo "0")%)"
    log_info "Errors: $errors ($(echo "scale=1; $errors * 100 / $total" | bc -l 2>/dev/null || echo "0")%)"
    echo
}

# Cleanup function
cleanup_on_exit() {
    local exit_code=$?
    
    if [[ $exit_code -ne 0 ]]; then
        log_warn "Script interrupted or failed with exit code $exit_code"
    fi
    
    # Kill any remaining background processes
    jobs -p | xargs -r kill 2>/dev/null || true
    
    # Clean up containers if requested
    if [[ "$CLEAN_CONTAINERS" == "true" && "$DRY_RUN" != "true" ]]; then
        log_info "Cleaning up any remaining containers..."
        docker ps -a --filter "name=mobile_bench_${RUN_ID}_" --format "{{.Names}}" | \
            xargs -r docker rm -f 2>/dev/null || true
    fi
    
    exit $exit_code
}

# Progress monitoring
monitor_progress() {
    if [[ "$DRY_RUN" == "true" ]]; then
        return 0
    fi
    
    local total=${#INSTANCES_TO_EVAL[@]}
    
    while true; do
        local completed=$(find "$LOG_DIR/$RUN_ID" -name "report.json" -type f 2>/dev/null | wc -l)
        local running=$(docker ps --filter "name=mobile_bench_${RUN_ID}_" --format "{{.Names}}" 2>/dev/null | wc -l)
        
        if [[ $completed -ge $total ]]; then
            break
        fi
        
        log_info "Progress: $completed/$total completed, $running running"
        sleep 30
    done
}

# Configuration display
show_configuration() {
    log_info "=== MOBILE BENCH HARNESS CONFIGURATION ==="
    log_info "Run ID: $RUN_ID"
    log_info "Predictions file: $PREDICTIONS_FILE"
    log_info "Dataset file: $DATASET_FILE"
    log_info "Docker image: $DOCKER_IMAGE"
    log_info "Max workers: $MAX_WORKERS"
    log_info "Timeout: ${TIMEOUT}s"
    log_info "Android API level: $ANDROID_API_LEVEL"
    log_info "Build tools version: $BUILD_TOOLS_VERSION"
    log_info "Log directory: $LOG_DIR/$RUN_ID"
    log_info "Report directory: $REPORT_DIR"
    log_info "Cache directory: $CACHE_DIR"
    log_info "Force rebuild: $FORCE_REBUILD"
    log_info "Clean containers: $CLEAN_CONTAINERS"
    log_info "Debug mode: $DEBUG"
    log_info "Dry run: $DRY_RUN"
    
    if [[ ${#INSTANCE_IDS[@]} -gt 0 ]]; then
        log_info "Specific instances: ${INSTANCE_IDS[*]}"
    else
        log_info "Evaluate all available instances"
    fi
    log_info "============================================="
}

# Main function
main() {
    # Set up signal handlers
    trap cleanup_on_exit INT TERM EXIT
    
    # Parse and validate arguments
    parse_arguments "$@"
    validate_arguments
    
    # Show configuration
    show_configuration
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "=== DRY RUN MODE - NO ACTUAL EXECUTION ==="
    fi
    
    # Setup
    setup_directories
    pull_docker_image
    
    # Data processing
    load_predictions
    load_dataset
    get_instances_to_evaluate
    
    if [[ ${#INSTANCES_TO_EVAL[@]} -eq 0 ]]; then
        log_warn "No instances to evaluate"
        exit 0
    fi
    
    # Start progress monitoring in background
    if [[ "$DRY_RUN" != "true" ]]; then
        monitor_progress &
        local monitor_pid=$!
    fi
    
    # Run evaluation
    local start_time=$(date +%s)
    run_evaluation
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    # Stop progress monitoring
    if [[ "$DRY_RUN" != "true" ]]; then
        kill $monitor_pid 2>/dev/null || true
        wait $monitor_pid 2>/dev/null || true
    fi
    
    # Generate reports
    generate_final_report
    
    # Final summary
    log_info "Evaluation completed in ${duration}s"
    
    if [[ "$DRY_RUN" != "true" ]]; then
        log_info "Results available in: $REPORT_DIR/mobile_bench_${RUN_ID}_report.json"
        log_info "Logs available in: $LOG_DIR/$RUN_ID"
    fi
}

# Script execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Check dependencies
    for cmd in docker jq bc; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "Required command not found: $cmd"
            log_info "Please install: $cmd"
            exit 1
        fi
    done
    
    # Run main function
    main "$@"
fi