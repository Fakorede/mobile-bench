#!/bin/bash

# Mobile Bench Inference Runner Script
# 
# This script runs the enhanced Mobile Bench inference with proper environment setup
# and configurable parameters for different execution scenarios.
#
# Usage:
#   ./run_mobile_bench.sh                    # Basic run with defaults
#   ./run_mobile_bench.sh --max-cost 50      # With cost limit
#   ./run_mobile_bench.sh --shard 0 4        # Shard 0 of 4 parallel runs
#   ./run_mobile_bench.sh --debug            # Debug mode
#
# Environment variables can be set to override defaults:
#   export INPUT_FILE="/path/to/data.jsonl"
#   export OUTPUT_DIR="/path/to/results"
#   export MODELS="deepseek-v3 claude-sonnet-4"
#   export MAX_COST="100.0"
#   export TEMPERATURE="0.1"

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_debug "Script directory: $SCRIPT_DIR"

# Set the project root (adjust levels as needed for your project structure)
PROJECT_ROOT="$SCRIPT_DIR/../.."
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"  # Get absolute path
log_debug "Project root: $PROJECT_ROOT"

# Default configuration (can be overridden by environment variables)
DEFAULT_INPUT_FILE="$PROJECT_ROOT/data/prompts/Antennapod_prompts_style-3_oracle_gemini.jsonl"
DEFAULT_OUTPUT_DIR="$PROJECT_ROOT/data/inference"
DEFAULT_MODELS="gemini-flash"
DEFAULT_MAX_INSTANCES=""
DEFAULT_MAX_COST=""
DEFAULT_TEMPERATURE="0.1"
DEFAULT_MAX_TOKENS=""
DEFAULT_TOP_P="0.9"
DEFAULT_VERBOSE="false"
DEFAULT_DEBUG="false"

# Load configuration from environment or use defaults
INPUT_FILE="${INPUT_FILE:-$DEFAULT_INPUT_FILE}"
OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
MODELS="${MODELS:-$DEFAULT_MODELS}"
MAX_INSTANCES="${MAX_INSTANCES:-$DEFAULT_MAX_INSTANCES}"
MAX_COST="${MAX_COST:-$DEFAULT_MAX_COST}"
TEMPERATURE="${TEMPERATURE:-$DEFAULT_TEMPERATURE}"
MAX_TOKENS="${MAX_TOKENS:-$DEFAULT_MAX_TOKENS}"
TOP_P="${TOP_P:-$DEFAULT_TOP_P}"
VERBOSE="${VERBOSE:-$DEFAULT_VERBOSE}"
DEBUG="${DEBUG:-$DEFAULT_DEBUG}"

# Initialize variables for command line arguments
SHARD_ID=""
NUM_SHARDS=""
OUTPUT_SUFFIX=""
CUSTOM_OUTPUT=""
EXTRA_ARGS=()

# Function to show usage
show_usage() {
    cat << EOF
Mobile Bench Inference Runner

Usage: $0 [OPTIONS]

OPTIONS:
    --input FILE              Input JSONL file (default: $DEFAULT_INPUT_FILE)
    --output-dir DIR          Output directory (default: $DEFAULT_OUTPUT_DIR)
    --output FILE             Custom output file path (overrides --output-dir)
    --models MODEL1 MODEL2    Space-separated list of models (default: $DEFAULT_MODELS)
    --max-instances N         Maximum number of instances to process
    --max-cost AMOUNT         Maximum cost in USD (e.g., 50.0)
    --temperature TEMP        Temperature for sampling (0.0-1.0, default: $DEFAULT_TEMPERATURE)
    --max-tokens N            Maximum tokens per response
    --top-p VALUE             Top-p parameter (0.0-1.0, default: $DEFAULT_TOP_P)
    --shard ID TOTAL          Run shard ID out of TOTAL shards (e.g., --shard 0 4)
    --suffix SUFFIX           Add suffix to output filename
    --verbose                 Enable verbose logging
    --debug                   Enable debug logging
    --help                    Show this help message

ENVIRONMENT VARIABLES:
    OPENROUTER_API_KEY        OpenRouter API key (required)
    INPUT_FILE                Override default input file
    OUTPUT_DIR                Override default output directory
    MODELS                    Override default models
    MAX_COST                  Override default max cost
    TEMPERATURE               Override default temperature

EXAMPLES:
    # Basic run
    $0

    # With cost limit
    $0 --max-cost 50.0

    # Parallel processing (run 4 shards)
    $0 --shard 0 4 --suffix "shard0" &
    $0 --shard 1 4 --suffix "shard1" &
    $0 --shard 2 4 --suffix "shard2" &
    $0 --shard 3 4 --suffix "shard3" &
    wait

    # Custom models and parameters
    $0 --models "deepseek-v3 claude-opus-4" --temperature 0.2 --max-tokens 6000

    # Debug run with limited instances
    $0 --debug --max-instances 10 --verbose

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --input)
            INPUT_FILE="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --output)
            CUSTOM_OUTPUT="$2"
            shift 2
            ;;
        --models)
            MODELS=""
            shift
            # Collect all models until next option or end
            while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                MODELS="$MODELS $1"
                shift
            done
            MODELS=$(echo "$MODELS" | sed 's/^ *//')  # Trim leading space
            ;;
        --max-instances)
            MAX_INSTANCES="$2"
            shift 2
            ;;
        --max-cost)
            MAX_COST="$2"
            shift 2
            ;;
        --temperature)
            TEMPERATURE="$2"
            shift 2
            ;;
        --max-tokens)
            MAX_TOKENS="$2"
            shift 2
            ;;
        --top-p)
            TOP_P="$2"
            shift 2
            ;;
        --shard)
            SHARD_ID="$2"
            NUM_SHARDS="$3"
            shift 3
            ;;
        --suffix)
            OUTPUT_SUFFIX="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE="true"
            shift
            ;;
        --debug)
            DEBUG="true"
            VERBOSE="true"  # Debug implies verbose
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            # Pass unknown arguments to Python script
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Validation
log_debug "Validating configuration..."

# Check if input file exists
if [[ ! -f "$INPUT_FILE" ]]; then
    log_error "Input file not found: $INPUT_FILE"
    log_info "You can specify a different input file with --input /path/to/file.jsonl"
    exit 1
fi

# Check API key
if [[ -z "$OPENROUTER_API_KEY" ]]; then
    log_error "OPENROUTER_API_KEY environment variable is required"
    log_info "Set it with: export OPENROUTER_API_KEY='your-api-key'"
    exit 1
fi

# Validate shard parameters
if [[ -n "$SHARD_ID" && -z "$NUM_SHARDS" ]] || [[ -z "$SHARD_ID" && -n "$NUM_SHARDS" ]]; then
    log_error "Both --shard ID and TOTAL must be specified together"
    exit 1
fi

if [[ -n "$SHARD_ID" && -n "$NUM_SHARDS" ]]; then
    if [[ ! "$SHARD_ID" =~ ^[0-9]+$ ]] || [[ ! "$NUM_SHARDS" =~ ^[0-9]+$ ]]; then
        log_error "Shard ID and NUM_SHARDS must be integers"
        exit 1
    fi
    if [[ "$SHARD_ID" -ge "$NUM_SHARDS" ]]; then
        log_error "Shard ID ($SHARD_ID) must be less than NUM_SHARDS ($NUM_SHARDS)"
        exit 1
    fi
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"
log_debug "Created output directory: $OUTPUT_DIR"

# Determine output file
if [[ -n "$CUSTOM_OUTPUT" ]]; then
    OUTPUT_FILE="$CUSTOM_OUTPUT"
else
    # Extract base filename from input file (without path and extension)
    INPUT_BASENAME=$(basename "$INPUT_FILE")
    INPUT_NAME="${INPUT_BASENAME%.*}"  # Remove extension
    
    # Generate output filename based on input filename
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    OUTPUT_FILENAME="${INPUT_NAME}_${TIMESTAMP}"
    
    # Add shard info to filename
    if [[ -n "$SHARD_ID" && -n "$NUM_SHARDS" ]]; then
        OUTPUT_FILENAME="${OUTPUT_FILENAME}_shard${SHARD_ID}of${NUM_SHARDS}"
    fi
    
    # Add custom suffix
    if [[ -n "$OUTPUT_SUFFIX" ]]; then
        OUTPUT_FILENAME="${OUTPUT_FILENAME}_${OUTPUT_SUFFIX}"
    fi
    
    OUTPUT_FILE="$OUTPUT_DIR/${OUTPUT_FILENAME}.jsonl"
fi

# Ensure output file has .jsonl extension
if [[ ! "$OUTPUT_FILE" =~ \.jsonl$ ]]; then
    OUTPUT_FILE="${OUTPUT_FILE}.jsonl"
fi

log_debug "Output file: $OUTPUT_FILE"

# Build Python command arguments
PYTHON_ARGS=(
    "--input" "$INPUT_FILE"
    "--output" "$OUTPUT_FILE"
)

# Add models
if [[ -n "$MODELS" ]]; then
    PYTHON_ARGS+=("--models")
    for model in $MODELS; do
        PYTHON_ARGS+=("$model")
    done
fi

# Add optional parameters
[[ -n "$MAX_INSTANCES" ]] && PYTHON_ARGS+=("--max-instances" "$MAX_INSTANCES")
[[ -n "$MAX_COST" ]] && PYTHON_ARGS+=("--max-cost" "$MAX_COST")
[[ -n "$TEMPERATURE" ]] && PYTHON_ARGS+=("--temperature" "$TEMPERATURE")
[[ -n "$MAX_TOKENS" ]] && PYTHON_ARGS+=("--max-tokens" "$MAX_TOKENS")
[[ -n "$TOP_P" ]] && PYTHON_ARGS+=("--top-p" "$TOP_P")

# Add shard parameters
if [[ -n "$SHARD_ID" && -n "$NUM_SHARDS" ]]; then
    PYTHON_ARGS+=("--shard-id" "$SHARD_ID" "--num-shards" "$NUM_SHARDS")
fi

# Add logging flags
[[ "$VERBOSE" == "true" ]] && PYTHON_ARGS+=("--verbose")
[[ "$DEBUG" == "true" ]] && PYTHON_ARGS+=("--debug")

# Add any extra arguments
PYTHON_ARGS+=("${EXTRA_ARGS[@]}")

# Print configuration
log_info "=== MOBILE BENCH INFERENCE CONFIGURATION ==="
log_info "Input file:      $INPUT_FILE"
log_info "Output file:     $OUTPUT_FILE"
log_info "Models:          $MODELS"
[[ -n "$MAX_INSTANCES" ]] && log_info "Max instances:   $MAX_INSTANCES"
[[ -n "$MAX_COST" ]] && log_info "Max cost:        \$${MAX_COST}"
log_info "Temperature:     $TEMPERATURE"
[[ -n "$MAX_TOKENS" ]] && log_info "Max tokens:      $MAX_TOKENS"
log_info "Top-p:           $TOP_P"
if [[ -n "$SHARD_ID" && -n "$NUM_SHARDS" ]]; then
    log_info "Shard:           $SHARD_ID/$NUM_SHARDS"
fi
log_info "Verbose:         $VERBOSE"
log_info "Debug:           $DEBUG"
log_info "============================================="

# Check if Python script exists
PYTHON_SCRIPT="$SCRIPT_DIR/run_inference.py"
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    log_error "Python script not found: $PYTHON_SCRIPT"
    exit 1
fi

# Set PYTHONPATH to include project root
export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"
log_debug "PYTHONPATH: $PYTHONPATH"

# Create a function to handle cleanup on interruption
cleanup() {
    log_warn "Inference interrupted by user"
    log_info "Partial results may be available in: $OUTPUT_FILE"
    exit 1
}
trap cleanup INT TERM

# Run the Python script
log_info "Starting Mobile Bench inference..."
log_debug "Running: python $PYTHON_SCRIPT ${PYTHON_ARGS[*]}"

# Execute with proper error handling
if python "$PYTHON_SCRIPT" "${PYTHON_ARGS[@]}"; then
    log_info "✅ Inference completed successfully!"
    log_info "Results saved to: $OUTPUT_FILE"
    
    # Show summary if file exists and has content
    if [[ -f "$OUTPUT_FILE" && -s "$OUTPUT_FILE" ]]; then
        RESULT_COUNT=$(wc -l < "$OUTPUT_FILE")
        log_info "📊 Generated $RESULT_COUNT result(s)"
        
        # Check for summary file
        SUMMARY_FILE="${OUTPUT_FILE%.*}_summary.json"
        if [[ -f "$SUMMARY_FILE" ]]; then
            log_info "📋 Summary available: $SUMMARY_FILE"
        fi
    fi
else
    EXIT_CODE=$?
    log_error "❌ Inference failed with exit code $EXIT_CODE"
    log_info "Check the logs above for error details"
    exit $EXIT_CODE
fi