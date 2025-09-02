#!/bin/bash

# Simple script to run evaluation prompt creation
# Usage: ./run_evaluation_prompts.sh [options] <input_path> <output_dir>

set -e

# Directory configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set the project root two levels up from this script
PROJECT_ROOT="$SCRIPT_DIR/../.."

PYTHON_SCRIPT="$SCRIPT_DIR/create_evaluation_prompts.py"

# Check if Python script exists
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo "Error: create_evaluation_prompts.py not found"
    exit 1
fi


# Default values (relative to project root)
INPUT_PATH="$PROJECT_ROOT/data/tasks/Antennapod-task-instances.jsonl"
OUTPUT_DIR="$PROJECT_ROOT/data/prompts/"
MODEL_NAME="gemini-2.5-flash"
PROMPT_STYLE="style-3"
FILE_SOURCE="oracle"

# Help function
show_help() {
    cat << EOF
Usage: $0 [options] [input_path] [output_dir]

Create evaluation prompts from task instances.

Default values:
  input_path    = $INPUT_PATH
  output_dir    = $OUTPUT_DIR
  model_name    = $MODEL_NAME
  prompt_style  = $PROMPT_STYLE
  file_source   = $FILE_SOURCE

Options:
  -m, --model MODEL     Target model (gpt-4o, claude-sonnet-4, gemini-2.5-flash)
  -s, --style STYLE     Prompt style (style-2, style-3, full_file_gen, style-2-edits-only)
  -f, --source SOURCE   File source (oracle)
  -h, --help           Show this help

Examples:
  $0                                    # Use all defaults
  $0 data/tasks/ output/prompts/        # Custom paths
  $0 -m claude-sonnet-4                 # Different model
  $0 -f bm25 -m gpt-4o                  # BM25 source with GPT-4o
EOF
}

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--model)
            MODEL_NAME="$2"
            shift 2
            ;;
        -s|--style)
            PROMPT_STYLE="$2"
            shift 2
            ;;
        -f|--source)
            FILE_SOURCE="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            # Positional arguments
            if [[ -z "$CUSTOM_INPUT" ]]; then
                INPUT_PATH="$1"
                CUSTOM_INPUT=true
            elif [[ -z "$CUSTOM_OUTPUT" ]]; then
                OUTPUT_DIR="$1"
                CUSTOM_OUTPUT=true
            else
                echo "Too many arguments"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# Show configuration
echo "Creating evaluation prompts..."
echo "Input: $INPUT_PATH"
echo "Output: $OUTPUT_DIR" 
echo "Model: $MODEL_NAME"
echo "Style: $PROMPT_STYLE"
echo "Source: $FILE_SOURCE"
echo

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Run the Python script
python3 "$PYTHON_SCRIPT" \
    "$INPUT_PATH" \
    "$OUTPUT_DIR" \
    --model_name "$MODEL_NAME" \
    --prompt_style "$PROMPT_STYLE" \
    --file_source "$FILE_SOURCE"

echo "Done! Results saved to: $OUTPUT_DIR"