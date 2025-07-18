#!/usr/bin/env bash
# Mobile Bench Inference Runner
# Usage: ./run_completion.sh [OPTIONS]
# Example: ./run_completion.sh --profile research --max-instances 5

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set the project root two levels up from this script
PROJECT_ROOT="$SCRIPT_DIR/../.."

# Default values
TEMPERATURE=0.1
TOP_P=0.9
MAX_TOKENS=12000
MAX_INSTANCES=10
MODELS="deepseek-v3 claude-sonnet-4 gpt-4o"
PROFILE="research"
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print usage information
usage() {
    cat << EOF
Mobile Bench Inference Runner

USAGE:
    $0 [OPTIONS]

OPTIONS:
    --models MODEL1 MODEL2    Models to run (default: deepseek-v3 claude-sonnet-4)
                             Available: deepseek-v3, claude-sonnet-4, gpt-4o, codestral
    --max-instances N        Maximum instances to process (default: 10)
    --temperature T          Temperature 0.0-1.0 (default: 0.1)
    --top-p P               Top-p 0.0-1.0 (default: 0.9)  
    --max-tokens N          Max output tokens (default: 12000)
    --profile PROFILE       Use predefined profile (research|production|budget|creative)
    --input DIR             Input directory (default: data/prompts/)
    --output DIR            Output directory (default: data/completions/)
    --verbose               Enable verbose logging
    --help                  Show this help message

PROFILES:
    research     : temp=0.0, top_p=1.0, max_tokens=8000  (reproducible)
    production   : temp=0.1, top_p=0.9, max_tokens=16000 (balanced)
    budget       : temp=0.0, top_p=0.9, max_tokens=8000  (cost-effective)
    creative     : temp=0.5, top_p=0.95, max_tokens=16000 (diverse solutions)

EXAMPLES:
    # Basic usage with defaults
    $0
    
    # Research profile with specific models
    $0 --profile research --models deepseek-v3 --max-instances 5
    
    # Custom parameters
    $0 --temperature 0.3 --top-p 0.8 --max-tokens 16000 --verbose
    
    # Budget run with single model
    $0 --profile budget --models claude-sonnet-4 --max-instances 50

EOF
}

# Apply profile settings
apply_profile() {
    case "$PROFILE" in
        research)
            TEMPERATURE=0.0
            TOP_P=1.0
            MAX_TOKENS=8000
            echo -e "${BLUE}📊 Applied RESEARCH profile: reproducible, deterministic${NC}"
            ;;
        production)
            TEMPERATURE=0.1
            TOP_P=0.9
            MAX_TOKENS=16000
            echo -e "${GREEN}🚀 Applied PRODUCTION profile: balanced performance${NC}"
            ;;
        budget)
            TEMPERATURE=0.0
            TOP_P=0.9
            MAX_TOKENS=8000
            echo -e "${YELLOW}💰 Applied BUDGET profile: cost-effective${NC}"
            ;;
        creative)
            TEMPERATURE=0.5
            TOP_P=0.95
            MAX_TOKENS=16000
            echo -e "${BLUE}🎨 Applied CREATIVE profile: diverse solutions${NC}"
            ;;
        *)
            if [[ -n "$PROFILE" ]]; then
                echo -e "${RED}❌ Unknown profile: $PROFILE${NC}"
                echo "Available profiles: research, production, budget, creative"
                exit 1
            fi
            ;;
    esac
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --models)
            shift
            MODELS=""
            while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                MODELS="$MODELS $1"
                shift
            done
            ;;
        --max-instances)
            MAX_INSTANCES="$2"
            shift 2
            ;;
        --temperature)
            TEMPERATURE="$2"
            shift 2
            ;;
        --top-p)
            TOP_P="$2"
            shift 2
            ;;
        --max-tokens)
            MAX_TOKENS="$2"
            shift 2
            ;;
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --input)
            INPUT_DIR="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            usage
            exit 1
            ;;
    esac
done

# Set default directories if not provided
INPUT_DIR="${INPUT_DIR:-$PROJECT_ROOT/data/prompts/}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_ROOT/data/completions/}"

# Apply profile if specified
if [[ -n "$PROFILE" ]]; then
    apply_profile
fi

# Validation
if [[ ! -d "$INPUT_DIR" ]]; then
    echo -e "${RED}❌ Input directory does not exist: $INPUT_DIR${NC}"
    exit 1
fi

# Check for API key
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo -e "${RED}❌ OPENROUTER_API_KEY environment variable not set${NC}"
    echo "Please set your OpenRouter API key:"
    echo "export OPENROUTER_API_KEY='your-api-key-here'"
    exit 1
fi

# Ensure required directories exist
mkdir -p "$OUTPUT_DIR"

# Find input files
INPUT_FILES=$(find "$INPUT_DIR" -name "*.jsonl" | head -1)
if [[ -z "$INPUT_FILES" ]]; then
    echo -e "${RED}❌ No JSONL files found in $INPUT_DIR${NC}"
    exit 1
fi

# Generate output filename with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_FILE="$OUTPUT_DIR/mobile_bench_results_${TIMESTAMP}.jsonl"

# Print configuration
echo -e "${GREEN}🚀 Mobile Bench Inference Configuration${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "📁 Input:        ${BLUE}$INPUT_FILES${NC}"
echo -e "📁 Output:       ${BLUE}$OUTPUT_FILE${NC}"
echo -e "🤖 Models:       ${BLUE}$MODELS${NC}"
echo -e "📊 Max instances: ${BLUE}$MAX_INSTANCES${NC}"
echo -e "🌡️  Temperature:  ${BLUE}$TEMPERATURE${NC}"
echo -e "🎯 Top-p:        ${BLUE}$TOP_P${NC}"
echo -e "📝 Max tokens:   ${BLUE}$MAX_TOKENS${NC}"
echo -e "🔍 Verbose:      ${BLUE}$VERBOSE${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Confirm before running (for production safety)
if [[ "$MAX_INSTANCES" -gt 20 ]]; then
    echo -e "${YELLOW}⚠️  Large run detected ($MAX_INSTANCES instances)${NC}"
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# Build command arguments
CMD_ARGS=(
    --input "$INPUT_FILES"
    --output "$OUTPUT_FILE"
    --models $MODELS
    --max-instances "$MAX_INSTANCES"
    --temperature "$TEMPERATURE"
    --top-p "$TOP_P"
    --max-tokens "$MAX_TOKENS"
)

if [[ "$VERBOSE" == true ]]; then
    CMD_ARGS+=(--verbose)
fi

# Run the inference
echo -e "${GREEN}🏃 Starting Mobile Bench inference...${NC}"
echo

# Check if Python script exists
PYTHON_SCRIPT="$SCRIPT_DIR/run_completion.py"
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo -e "${RED}❌ Python script not found: $PYTHON_SCRIPT${NC}"
    exit 1
fi

# Execute with error handling
if python "$PYTHON_SCRIPT" "${CMD_ARGS[@]}"; then
    echo
    echo -e "${GREEN}✅ Inference completed successfully!${NC}"
    echo -e "📄 Results saved to: ${BLUE}$OUTPUT_FILE${NC}"
    
    # Show quick stats if results exist
    if [[ -f "$OUTPUT_FILE" ]]; then
        RESULT_COUNT=$(wc -l < "$OUTPUT_FILE" 2>/dev/null || echo "0")
        echo -e "📊 Generated ${BLUE}$RESULT_COUNT${NC} results"
        
        # Check for summary file
        SUMMARY_FILE="${OUTPUT_FILE/_results_/_summary_}"
        SUMMARY_FILE="${SUMMARY_FILE/.jsonl/.json}"
        if [[ -f "$SUMMARY_FILE" ]]; then
            echo -e "📈 Summary: ${BLUE}$SUMMARY_FILE${NC}"
        fi
    fi
else
    echo -e "${RED}❌ Inference failed!${NC}"
    exit 1
fi

echo -e "${GREEN}🎉 Mobile Bench inference complete!${NC}"