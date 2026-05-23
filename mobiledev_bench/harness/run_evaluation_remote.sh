#!/bin/bash

# Script to run evaluation with remote images from GHCR
# This script provides a convenient way to run evaluations for different models
# without needing to build images locally.
# You need to authenticate with a GitHub personal access token (PAT) that has read:packages scope.
# echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
#
# Usage:
#   ./mobiledev_bench/harness/run_evaluation_remote.sh <model_name> [options]
#   # Or from the project root:
#   bash mobiledev_bench/harness/run_evaluation_remote.sh <model_name> [options]
#
# Examples:
#   ./mobiledev_bench/harness/run_evaluation_remote.sh claude-sonnet-4.5 --repo WordPress-Android --max-workers 2 --dry-run
#   ./mobiledev_bench/harness/run_evaluation_remote.sh gemini-2.5-flash --specifics PalisadoesFoundation/talawa:pr-2220 PalisadoesFoundation/talawa:pr-2216
#   ./mobiledev_bench/harness/run_evaluation_remote.sh qwen3-coder --max-workers 2
#   ./mobiledev_bench/harness/run_evaluation_remote.sh gpt-5.2 --dry-run

# ✓ Evaluation completed successfully
#   Final report:    data/results/evaluation/oracle/react-native/claude-sonnet-4.5/final_report.json
#   Output dir:      data/results/evaluation/oracle/react-native/claude-sonnet-4.5/
#   Logs:            data/results/evaluation/oracle/react-native/claude-sonnet-4.5/logs/run_evaluation.log

# ✓ Evaluation completed successfully

# Results available at:
#   Final report:    data/results/evaluation/oracle/android-native/claude-sonnet-4.5/final_report.json
#   Output dir:      data/results/evaluation/oracle/android-native/claude-sonnet-4.5/
#   Logs:            data/results/evaluation/oracle/android-native/claude-sonnet-4.5/logs/run_evaluation.log


set -e  # Exit on error

# ============================================================================
# CONFIGURATION - Edit these values for your setup
# ============================================================================

# Common paths
REPO_DIR="/tmp"  # Dummy value - not used with remote images, but required by CLI

# Dataset files (shared across all models)
DATASET_FILES="/home/researchuser/dev/inri/mobiledev-bench/paper-neurips/data/final_verified_dataset_90.jsonl"
# data/instances/final_verified_dataset.jsonl

# GHCR settings
GHCR_USERNAME="mobiledev-bench"

# Execution settings
MAX_WORKERS_RUN_INSTANCE=1  # Set to 1 to avoid parallel runs
STOP_ON_ERROR=false         # Continue on errors
LOG_LEVEL="INFO"

# ============================================================================
# MODEL-SPECIFIC CONFIGURATIONS
# Define patch files and output directories for each model
# ============================================================================

declare -A MODEL_PATCH_FILES
declare -A MODEL_OUTPUT_DIRS

# Claude Sonnet 4.5 configuration
MODEL_PATCH_FILES["claude-sonnet-4.5"]="data/results/predictions/agentless/mobiledev_bench_rn_typescript-claude-sonnet-4.5_converted_patches.jsonl"
MODEL_OUTPUT_DIRS["claude-sonnet-4.5"]="data/results/evaluation/agentless/react-native/claude-sonnet-4.5"

# Gemini 2.5 Flash configuration
MODEL_PATCH_FILES["gemini-2.5-flash"]="data/results/predictions/agentless/mobiledev_bench_rn_typescript-gemini-2.5-flash_converted_patches.jsonl"
MODEL_OUTPUT_DIRS["gemini-2.5-flash"]="data/results/evaluation/agentless/react-native/gemini-2.5-flash"

# Qwen3 Coder configuration
MODEL_PATCH_FILES["qwen3-coder"]="data/results/predictions/agentless/mobiledev_bench_rn_typescript-qwen3-coder_converted_patches.jsonl"
MODEL_OUTPUT_DIRS["qwen3-coder"]="data/results/evaluation/agentless/react-native/qwen3-coder"

# GPT 5.2 configuration
MODEL_PATCH_FILES["gpt-5.2"]="data/results/predictions/agentless/mobiledev_bench_rn_typescript-gpt-5.2_converted_patches.jsonl"
MODEL_OUTPUT_DIRS["gpt-5.2"]="data/results/evaluation/agentless/react-native/gpt-5.2"

# Add more models as needed
# MODEL_PATCH_FILES["model_name"]="data/results/model_name_converted_patches.jsonl"
# MODEL_OUTPUT_DIRS["model_name"]="results/evaluation/model_name"

# ============================================================================
# SCRIPT LOGIC - No need to edit below this line
# ============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print usage
usage() {
    echo "Usage: $0 <model_name> [options]"
    echo ""
    echo "Available models:"
    for model in "${!MODEL_PATCH_FILES[@]}"; do
        echo "  - $model"
    done | sort
    echo ""
    echo "Options:"
    echo "  --specifics <id1> <id2> ...  Only evaluate specific instances/repos (supports multiple values)"
    echo "  --skips <id1> <id2> ...      Skip specific instances/repos (supports multiple values)"
    echo "  --max-workers <N>            Set max workers for parallel instances (default: $MAX_WORKERS_RUN_INSTANCE)"
    echo "  --dry-run                    Print command without executing"
    echo "  --help                       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 claude-sonnet-4.5"
    echo "  $0 gemini-2.5-flash --specifics Anki-Android"
    echo "  $0 qwen3-coder --specifics WordPress-Android element-x-android thunderbird-android"
    echo "  $0 gpt-5.2 --max-workers 2"
    exit 1
}

# Check if model is provided
if [ $# -lt 1 ]; then
    echo -e "${RED}Error: Model name required${NC}"
    usage
fi

MODEL_NAME="$1"
shift

# Check if model exists in configuration
if [ -z "${MODEL_PATCH_FILES[$MODEL_NAME]}" ]; then
    echo -e "${RED}Error: Unknown model '$MODEL_NAME'${NC}"
    echo ""
    echo "Available models:"
    for model in "${!MODEL_PATCH_FILES[@]}"; do
        echo "  - $model"
    done | sort
    exit 1
fi

# Get model-specific configuration
PATCH_FILES="${MODEL_PATCH_FILES[$MODEL_NAME]}"
OUTPUT_DIR="${MODEL_OUTPUT_DIRS[$MODEL_NAME]}"
WORKDIR="${OUTPUT_DIR}/workdir"
LOG_DIR="${OUTPUT_DIR}/logs"

# Parse additional arguments
SPECIFICS=""
SKIPS=""
DRY_RUN=false

while [ $# -gt 0 ]; do
    case "$1" in
        --specifics)
            shift
            while [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; do
                SPECIFICS="$SPECIFICS $1"
                shift
            done
            ;;
        --skips)
            shift
            while [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; do
                SKIPS="$SKIPS $1"
                shift
            done
            ;;
        --max-workers)
            MAX_WORKERS_RUN_INSTANCE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option '$1'${NC}"
            usage
            ;;
    esac
done

# Build the command
CMD="python3 -m mobiledev_bench.harness.run_evaluation"
CMD="$CMD --mode evaluation"
CMD="$CMD --use_remote_images true"
CMD="$CMD --ghcr_username $GHCR_USERNAME"
CMD="$CMD --patch_files $PATCH_FILES"
CMD="$CMD --dataset_files $DATASET_FILES"
CMD="$CMD --workdir $WORKDIR"
CMD="$CMD --repo_dir $REPO_DIR"
CMD="$CMD --output_dir $OUTPUT_DIR"
CMD="$CMD --log_dir $LOG_DIR"
CMD="$CMD --max_workers_run_instance $MAX_WORKERS_RUN_INSTANCE"
CMD="$CMD --stop_on_error $STOP_ON_ERROR"
CMD="$CMD --log_level $LOG_LEVEL"

# Add specifics if provided
if [ -n "$SPECIFICS" ]; then
    CMD="$CMD --specifics$SPECIFICS"
fi

# Add skips if provided
if [ -n "$SKIPS" ]; then
    CMD="$CMD --skips$SKIPS"
fi

# Print header
echo ""
echo -e "${BLUE}================================================================================${NC}"
echo -e "${GREEN}Running Evaluation for Model: $MODEL_NAME${NC}"
echo -e "${BLUE}================================================================================${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Model:              $MODEL_NAME"
echo "  Patch files:        $PATCH_FILES"
echo "  Dataset files:      $DATASET_FILES"
echo "  Output directory:   $OUTPUT_DIR"
echo "  Log directory:      $LOG_DIR"
echo "  GHCR username:      $GHCR_USERNAME"
echo "  Max workers:        $MAX_WORKERS_RUN_INSTANCE"
echo "  Use remote images:  true"
if [ -n "$SPECIFICS" ]; then
    echo "  Specifics:          $SPECIFICS"
fi
if [ -n "$SKIPS" ]; then
    echo "  Skips:              $SKIPS"
fi
echo ""
echo -e "${YELLOW}Command:${NC}"
echo "$CMD"
echo ""
echo -e "${BLUE}================================================================================${NC}"
echo ""

# Create required directories
mkdir -p "$OUTPUT_DIR" "$WORKDIR" "$LOG_DIR"

# Execute or dry run
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Dry run mode - command not executed${NC}"
    exit 0
fi

# Execute the command
eval $CMD
EXIT_CODE=$?

# Print result
echo ""
echo -e "${BLUE}================================================================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Evaluation completed successfully${NC}"
    echo ""
    echo -e "${YELLOW}Results available at:${NC}"
    echo "  Final report:    ${OUTPUT_DIR}/final_report.json"
    echo "  Output dir:      ${OUTPUT_DIR}/"
    echo "  Logs:            ${LOG_DIR}/run_evaluation.log"
else
    echo -e "${RED}✗ Evaluation failed with exit code: $EXIT_CODE${NC}"
    echo ""
    echo -e "${YELLOW}Check logs at:${NC}"
    echo "  ${LOG_DIR}/run_evaluation.log"
fi
echo -e "${BLUE}================================================================================${NC}"
echo ""

exit $EXIT_CODE
